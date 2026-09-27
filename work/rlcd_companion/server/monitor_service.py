from __future__ import annotations
from typing import Literal
import asyncio
import copy
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import threading
import time
import zipfile
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import Field, field_validator
from datetime import date
from monitor_store import Store, Quota, TaskEvent, Heartbeat, StrictModel, Provider
from monitor_collectors import collect, CollectorError
from monitor_render import render_monitor
from monitor_periods import billing_periods

class AccountSettings(StrictModel):
    region: Literal['global','cn'] = 'global'
    enabled: bool = False
    account: str = Field('default',min_length=1,max_length=100)
    token: str | None = Field(None,max_length=4096)

class Price(StrictModel):
    amount: float | None = Field(None,ge=0,le=1000000)
    currency: str = Field('¥',pattern=r'^(¥|\$|€|CNY|USD|EUR)$')
    period: str = Field('月',pattern=r'^(月|年)$')
    renewal_date: str | None = None

    @field_validator('renewal_date')
    @classmethod
    def valid_renewal_date(cls, value):
        return date.fromisoformat(value).isoformat() if value else None

class Settings(StrictModel):
    accounts: dict[Provider,AccountSettings] = Field(default_factory=dict)
    prices: dict[Provider,Price] = Field(default_factory=dict)

class Pairing(StrictModel):
    server_url: str = Field(max_length=200)
    machine_id: str = Field('lab-pc',min_length=1,max_length=80,pattern=r'^[\w.-]+$')

def local_request(request):
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'仅允许在这台电脑上配置')
    if request.client.host!='testclient' and request.url.hostname not in ('127.0.0.1','localhost','::1'):
        raise HTTPException(403,'请使用 localhost 打开配置页')
    origin=request.headers.get('origin')
    if origin and origin!=f'{request.url.scheme}://{request.headers.get("host")}':
        raise HTTPException(403,'跨站请求被拒绝')

class Monitor:
    def __init__(self,data_dir=None):
        self.directory=Path(data_dir or os.environ.get('RLCD_DATA_DIR',Path(__file__).parent/'data'))
        self.directory.mkdir(parents=True,exist_ok=True)
        self.store=Store(self.directory/'monitor.sqlite3')
        self.settings_file=self.directory/'settings.json'
        self.lock=threading.RLock()
        self.settings=json.loads(self.settings_file.read_text(encoding='utf-8')) if self.settings_file.exists() else {'accounts':{'codex':{'enabled':True,'account':'default'}},'prices':{}}
        self.token_file=self.directory/'ingest-token.txt'
        if not self.token_file.exists(): self.token_file.write_text(secrets.token_urlsafe(32),encoding='utf-8')
        self.token=self.token_file.read_text(encoding='utf-8').strip()
        self.environment={'weather':'天气--','battery':None,'indoor_temperature_c':None,'indoor_humidity_percent':None}
        self.stop=threading.Event(); self.wake=threading.Event(); self.thread=None
        self.collect_lock=threading.Lock()

    def public_settings(self):
        with self.lock:
            result=copy.deepcopy(self.settings)
        for p in ('codex','glm','qoder'):
            cfg=result.setdefault('accounts',{}).setdefault(p,{'enabled':False,'account':'default'})
            cfg['configured']=bool(cfg.pop('token',None)) or p=='codex'
        return result

    def save(self,settings):
        with self.lock:
            for p,cfg in settings.accounts.items():
                value=cfg.model_dump(); token=value.pop('token')
                old=self.settings.setdefault('accounts',{}).get(p,{})
                if token is None: token=old.get('token','')
                value['token']=token; self.settings['accounts'][p]=value
                if old.get('account')!=value['account']:
                    with self.store.db() as db: db.execute('DELETE FROM quotas WHERE provider=?',(p,))
            self.settings['prices'].update({k:v.model_dump() for k,v in settings.prices.items()})
            temp=self.settings_file.with_suffix('.tmp')
            temp.write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),encoding='utf-8')
            temp.replace(self.settings_file)
        self.wake.set()

    def collect_one(self,p,cfg):
        try: q=collect(p,cfg)
        except Exception as exc:
            # Do not serialize upstream responses, tokens or command arguments into UI/logs.
            reason={'glm':'GLM 查询失败，请核对个人套餐 Key 和网络','qoder':'Qoder 查询失败，请核对 SDK 与同一账户授权','codex':'Codex 查询失败，请检查本机登录和程序版本'}[p]
            if isinstance(exc,CollectorError): reason=str(exc)
            q=Quota(provider=p,account=cfg.get('account','default'),fetched_at=time.time(),error=reason)
        self.store.quota(q)

    def collect_all(self):
        if not self.collect_lock.acquire(blocking=False): return
        try:
            with self.lock: settings=copy.deepcopy(self.settings)
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures=[pool.submit(self.collect_one,p,cfg) for p,cfg in settings.get('accounts',{}).items() if cfg.get('enabled')]
                for future in futures: future.result()
        finally: self.collect_lock.release()

    def worker(self):
        from integrations.weather import fetch_weather
        from config import load_config
        config=load_config()
        while not self.stop.is_set():
            self.wake.clear()
            self.collect_all()
            try:
                if config.weather.latitude==0 and config.weather.longitude==0: raise ValueError('Weather location not configured')
                weather=fetch_weather(config.weather.latitude,config.weather.longitude,timeout=10)
                self.environment['weather']=f'{weather.text}{weather.temperature_c}°'
            except Exception: pass
            self.wake.wait(300)

    def start(self):
        if not self.thread:
            self.thread=threading.Thread(target=self.worker,daemon=True);self.thread.start()

    def shutdown(self): self.stop.set();self.wake.set()

    def image(self,fmt='png',battery=None,temp=None,humidity=None):
        for k,v in [('battery',battery),('indoor_temperature_c',temp),('indoor_humidity_percent',humidity)]:
            if v is not None: self.environment[k]=v
        return render_monitor(self.store.summary(),self.environment,self.public_settings(),fmt)

    def router(self):
        router=APIRouter()
        def authorized(request):
            value=request.headers.get('authorization','')
            if not secrets.compare_digest(value,'Bearer '+self.token): raise HTTPException(401,'上报令牌无效')
        @router.get('/')
        def index(request:Request):
            local_request(request)
            return FileResponse(Path(__file__).parent/'monitor.html')
        @router.get('/api/monitor')
        def summary(request:Request):
            local_request(request)
            return {**self.store.summary(),'billing_periods':billing_periods(time.time()),'settings':self.public_settings(),'environment':self.environment}
        @router.put('/api/settings')
        def settings(request:Request,payload:Settings):
            local_request(request);self.save(payload);return {'ok':True}
        @router.post('/api/refresh')
        def refresh(request:Request):
            local_request(request);self.wake.set();return {'ok':True}
        @router.post('/api/ingest/quota')
        def quota(request:Request,payload:Quota):
            authorized(request)
            cfg=self.settings.get('accounts',{}).get(payload.provider,{})
            if payload.account!=cfg.get('account','default'): raise HTTPException(409,'账户标识与看板配置不一致')
            if payload.fetched_at>time.time()+300: raise HTTPException(422,'上报时间超前')
            return {'accepted':self.store.quota(payload)}
        @router.post('/api/ingest/task')
        def task(request:Request,payload:TaskEvent):
            authorized(request)
            try: return {'accepted':self.store.event(payload)}
            except ValueError as e: raise HTTPException(422,str(e)) from None
        @router.post('/api/ingest/heartbeat')
        def heartbeat(request:Request,payload:Heartbeat):
            authorized(request);self.store.heartbeat(payload);return {'ok':True}
        @router.post('/api/lab-package')
        def package(request:Request,payload:Pairing):
            local_request(request)
            url=urlsplit(payload.server_url)
            try: ip=ipaddress.ip_address(url.hostname or '')
            except ValueError: raise HTTPException(422,'请填写这台电脑的 ZeroTier IP 地址') from None
            if url.scheme!='http' or not ip.is_private or ip.is_loopback or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
                raise HTTPException(422,'请输入 http://本机ZeroTier-IP:8787')
            out=io.BytesIO(); root=Path(__file__).parent.parent/'agent'
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
                for file in root.iterdir():
                    if file.is_file() and file.suffix in ('.py','.cmd','.txt','.md'): z.write(file,file.name)
                for name in ('monitor_collectors.py','monitor_store.py'):
                    z.write(Path(__file__).parent/name,name)
                config={'server_url':payload.server_url.rstrip('/'),'machine_id':payload.machine_id,'token':self.token}
                z.writestr('config.json',json.dumps(config,ensure_ascii=False,indent=2))
            return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename=rlcd-lab-agent.zip','Cache-Control':'no-store'})
        router.add_event_handler('startup',self.start)
        router.add_event_handler('shutdown',self.shutdown)
        return router
