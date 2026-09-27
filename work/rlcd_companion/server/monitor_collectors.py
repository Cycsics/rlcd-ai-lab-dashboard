"""Read-only account collectors. Never run model prompts to collect usage."""
from __future__ import annotations
import asyncio
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
import urllib.request
from monitor_store import Quota, Window

def codex_command():
    bundled=Path(os.environ.get('LOCALAPPDATA',''))/'OpenAI/Codex/bin'
    candidates=list(bundled.glob('*/codex.exe')) if bundled.exists() else []
    if candidates: return [str(max(candidates,key=lambda p:p.stat().st_mtime))]
    executable=shutil.which('codex')
    if executable and Path(executable).suffix.lower()=='.exe': return [executable]
    npm=Path(os.environ.get('APPDATA',''))/'npm/node_modules/@openai/codex/bin/codex.js'
    if npm.exists() and shutil.which('node'): return [shutil.which('node'),str(npm)]
    if executable and os.name!='nt': return [executable]
    raise RuntimeError('未找到 Codex CLI；请安装并登录同一账户')

def rpc_codex():
    proc=subprocess.Popen(codex_command()+['app-server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    responses=queue.Queue()
    def reader():
        for line in proc.stdout:
            try: responses.put(json.loads(line))
            except ValueError: pass
        responses.put({'closed':True})
    threading.Thread(target=reader,daemon=True).start()
    def send(obj):
        proc.stdin.write(json.dumps(obj)+'\n');proc.stdin.flush()
    def receive(ident):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            message=responses.get(timeout=max(.1,deadline-time.monotonic()))
            if message.get('closed'): raise RuntimeError('Codex 查询进程已关闭')
            if message.get('id')==ident:
                if 'error' in message: raise RuntimeError('Codex 查询失败，请检查登录及 CLI 版本')
                return message.get('result',{})
        raise TimeoutError('Codex 查询超时')
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'rlcd-monitor','version':'1.0.0'}}})
        receive(1);send({'method':'initialized','params':{}})
        send({'id':2,'method':'account/rateLimits/read','params':{}})
        return receive(2)
    finally:
        proc.terminate()
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()

def normalize_codex(payload,account):
    buckets=payload.get('rateLimitsByLimitId') or {}
    bucket=buckets.get('codex') or payload.get('rateLimits') or next(iter(buckets.values()),{})
    windows=[]
    for key in ('primary','secondary'):
        w=bucket.get(key)
        if not w: continue
        minutes=w.get('windowDurationMins')
        label=f'{minutes//1440}天' if minutes and minutes%1440==0 else f'{minutes//60}小时' if minutes and minutes%60==0 else f'{minutes}分钟' if minutes else '周期'
        used=w.get('usedPercent')
        windows.append(Window(label=label,remaining_percent=max(0,min(100,100-float(used))) if used is not None else None,resets_at=w.get('resetsAt')))
    if not windows: raise ValueError('Codex 未返回额度，请检查是否为订阅账户')
    return Quota(provider='codex',account=account,fetched_at=time.time(),windows=windows,plan=bucket.get('planType') or '')

def normalize_qoder(payload,account):
    windows=[]
    for key,label in [('userQuota','套餐'),('addOnQuota','附加包')]:
        w=payload.get(key)
        if not w: continue
        remaining=w.get('remaining'); total=w.get('total')
        expiry=payload.get('expiresAt') if key=='userQuota' else None
        if expiry is not None:
            expiry=int(expiry/1000 if expiry>100000000000 else expiry)
            if expiry<=0: expiry=None
        windows.append(Window(label=label,remaining=remaining,total=total,unit='Credits',expires_at=expiry,remaining_percent=100*remaining/total if total and remaining is not None else None))
    if not windows: raise ValueError('Qoder 未返回账户额度')
    return Quota(provider='qoder',account=account,fetched_at=time.time(),windows=windows,plan=str(payload.get('userType') or ''))

class CollectorError(RuntimeError):
    pass

async def qoder_query(token,region='global'):
    if region=='cn':
        from qodercn_agent_sdk import QoderAgentOptions,QoderSDKClient,access_token_from_env
    else:
        from qoder_agent_sdk import QoderAgentOptions,QoderSDKClient,access_token_from_env
    # SDK reads auth from process environment. This collector runs in its own helper process.
    if token: os.environ['QODERCN_PERSONAL_ACCESS_TOKEN' if region=='cn' else 'QODER_PERSONAL_ACCESS_TOKEN']=token
    def auth_expired():
        print(json.dumps({'collector_error':'auth_rejected'}),flush=True)
    async with QoderSDKClient(options=QoderAgentOptions(auth=access_token_from_env(),on_auth_expired=auth_expired)) as client:
        return await asyncio.wait_for(client.get_usage_info(),timeout=25)

def qoder_subprocess(token,region='global'):
    import sys
    env=os.environ.copy()
    env['RLCD_QODER_REGION']=region
    if token: env['QODER_PERSONAL_ACCESS_TOKEN']=token
    try:
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'qoder'],capture_output=True,text=True,encoding='utf-8',env=env,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=result.stdout
    except subprocess.TimeoutExpired as exc:
        output=exc.stdout or b''
        if isinstance(output,bytes): output=output.decode('utf-8',errors='replace')
        if '"auth_rejected"' in output: raise CollectorError('Qoder 拒绝此令牌，请核对国际/中国站、有效期和权限') from None
        raise CollectorError('Qoder 连接超时，请检查网络或代理') from None
    if '"auth_rejected"' in output: raise CollectorError('Qoder 拒绝此令牌，请核对国际/中国站、有效期和权限')
    if result.returncode: raise CollectorError('Qoder 启动或认证失败，请检查账户和网络')
    return json.loads(output)

def normalize_glm(payload,account):
    data=payload.get('data') or {}
    limits=data.get('limits') or []
    windows=[]
    for item in limits:
        label='编程额度' if item.get('type')=='TOKENS_LIMIT' else '套餐额度'
        if item.get('type')=='TOKENS_LIMIT' and item.get('unit')==3 and item.get('number')==5:
            label='5小时'
        if item.get('type')=='TIME_LIMIT': label='工具调用'
        used=item.get('percentage'); total=item.get('usage'); current=item.get('currentValue')
        reset=item.get('nextResetTime')
        if reset and reset>100000000000: reset=int(reset/1000)
        windows.append(Window(label=label,remaining_percent=max(0,min(100,100-float(used))) if used is not None else None,remaining=max(0,total-current) if total is not None and current is not None else None,total=total,resets_at=reset))
    if not windows: raise ValueError('GLM 未返回个人套餐额度')
    return Quota(provider='glm',account=account,fetched_at=time.time(),windows=windows)

def collect(provider,settings):
    account=settings.get('account') or 'default'
    if provider in ('api1','api2','api3'):
        from monitor_api import collect_api
        return collect_api(provider,settings)
    if provider in ('claude','grok'):
        from monitor_subscription import collect_subscription
        return collect_subscription(provider,settings)
    if provider=='codex': return normalize_codex(rpc_codex(),account)
    if provider=='qoder': return normalize_qoder(qoder_subprocess(settings.get('token',''),settings.get('region','global')),account)
    token=settings.get('token','')
    if not token: raise ValueError('尚未设置 GLM Coding Plan Key')
    request=urllib.request.Request('https://open.bigmodel.cn/api/monitor/usage/quota/limit',headers={'Authorization':token,'Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response: payload=json.load(response)
    return normalize_glm(payload,account)

if __name__=='__main__':
    try: print(json.dumps(asyncio.run(qoder_query(os.environ.get('QODER_PERSONAL_ACCESS_TOKEN',''),os.environ.get('RLCD_QODER_REGION','global')))))
    except Exception: raise SystemExit(1)
