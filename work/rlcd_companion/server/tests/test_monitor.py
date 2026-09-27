import importlib.util
import io
import json
from pathlib import Path
import time
import zipfile
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from monitor_store import Store,Quota,Window,TaskEvent,Heartbeat
from monitor_service import Monitor
from monitor_collectors import normalize_codex,normalize_glm,normalize_qoder
from monitor_render import render_monitor

def event(**kwargs):
    return TaskEvent(**dict({'event_id':'e1','machine_id':'lab','tool':'codex','session_id':'s1','turn_id':'t1','sequence':0,'occurred_at':time.time(),'status':'running','project':'项目'},**kwargs))

def test_order_duplicates_parallel_and_restart(tmp_path):
    path=tmp_path/'db';s=Store(path);ts=time.time()
    assert s.event(event(occurred_at=ts))
    assert not s.event(event(occurred_at=ts))
    s.event(event(event_id='e2',sequence=2,occurred_at=ts+1,status='waiting_approval'))
    assert not s.event(event(event_id='old',sequence=1,occurred_at=ts-.1,status='completed'))
    s.event(event(event_id='parallel',session_id='s2',occurred_at=ts))
    s.heartbeat(Heartbeat(machine_id='lab',clients={'codex':'connected'}))
    rows=Store(path).summary(ts+2)['tasks']
    assert len(rows)==2 and rows[0]['status']=='waiting_approval'
    assert rows[0]['status_label']=='等你确认'

def test_new_turn_hides_old_and_offline_is_not_completed(tmp_path):
    s=Store(tmp_path/'db');ts=time.time()
    s.event(event(occurred_at=ts,status='completed'))
    s.event(event(event_id='next',turn_id='t2',occurred_at=ts+1,status='running'))
    s.heartbeat(Heartbeat(machine_id='lab',clients={'codex':'connected'}))
    summary=s.summary(ts+62)
    assert len(summary['tasks'])==1
    assert summary['tasks'][0]['status']=='running'
    assert summary['tasks'][0]['display_status']=='offline'
    assert len(summary['history'])==1
    s.heartbeat(Heartbeat(machine_id='lab',clients={'codex':'closed'}))
    assert s.summary()['tasks'][0]['display_status']=='unknown'

def test_terminal_expiration(tmp_path):
    s=Store(tmp_path/'db');s.event(event(status='completed',occurred_at=time.time()-86401))
    assert not s.summary()['tasks']

def test_quota_error_keeps_original_timestamp_and_no_double_count(tmp_path):
    s=Store(tmp_path/'db');ts=time.time()-1000
    s.quota(Quota(provider='codex',account='same',fetched_at=ts,windows=[Window(label='周',remaining_percent=75)]))
    s.quota(Quota(provider='codex',account='same',fetched_at=ts+1,windows=[Window(label='周',remaining_percent=74)]))
    s.quota(Quota(provider='codex',account='same',fetched_at=time.time(),error='无法连接'))
    q=s.summary()['quotas']['codex']
    assert q['windows'][0]['remaining_percent']==74 and q['stale']
    assert q['fetched_at']==ts+1
    assert not s.quota(Quota(provider='codex',account='same',fetched_at=ts,windows=[]))

def test_null_is_not_zero_and_actual_windows():
    q=normalize_codex({'rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':None,'windowDurationMins':10080}}}},'a')
    assert q.windows[0].remaining_percent is None and q.windows[0].label=='7天'
    q=normalize_qoder({'userQuota':{'remaining':0,'total':100},'addOnQuota':{'remaining':None}},'a')
    assert q.windows[0].remaining==0 and q.windows[1].remaining is None
    q=normalize_glm({'data':{'limits':[{'type':'TOKENS_LIMIT','percentage':20,'nextResetTime':1791000000000}]}},'a')
    assert q.windows[0].remaining_percent==80 and q.windows[0].resets_at==1791000000

def client(tmp_path):
    m=Monitor(tmp_path);app=FastAPI();app.include_router(m.router());return TestClient(app),m

def test_api_auth_local_csrf_validation_and_no_secret_leak(tmp_path):
    c,m=client(tmp_path)
    assert c.post('/api/ingest/task',json=event().model_dump()).status_code==401
    assert c.post('/api/ingest/task',json=event().model_dump(),headers={'Authorization':'Bearer '+m.token}).status_code==200
    assert c.put('/api/settings',json={},headers={'Origin':'https://untrusted.example'}).status_code==403
    assert c.put('/api/settings',json={'accounts':{'glm':{'token':'TOP-SECRET','enabled':True}}}).status_code==200
    assert 'TOP-SECRET' not in c.get('/api/monitor').text
    assert c.post('/api/ingest/task',json={**event().model_dump(),'prompt':'must not upload'},headers={'Authorization':'Bearer '+m.token}).status_code==422
    assert c.put('/api/settings',json={'prices':{'codex':{'amount':-1}}}).status_code==422
    assert c.post('/api/ingest/quota',json={'provider':'codex','account':'wrong','fetched_at':time.time()},headers={'Authorization':'Bearer '+m.token}).status_code==409

def test_bundle_contains_reporter_and_no_account_secrets(tmp_path):
    c,m=client(tmp_path)
    r=c.post('/api/lab-package',json={'server_url':'http://192.0.2.10:8787','machine_id':'lab-pc'})
    assert r.status_code==200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert {'agent.py','install.cmd','config.json','monitor_collectors.py','monitor_store.py'}<=set(z.namelist())
        cfg=json.loads(z.read('config.json'));assert cfg['token']==m.token and 'accounts' not in cfg

def test_render_dimensions_size_and_long_names(tmp_path):
    s=Store(tmp_path/'db');s.heartbeat(Heartbeat(machine_id='lab',clients={'codex':'connected'}))
    for i in range(5): s.event(event(event_id=str(i),session_id=str(i),project='一个非常长的项目名称'*6,status='waiting_input'))
    summary=s.summary();settings={'prices':{}}
    png=render_monitor(summary,{},settings)
    image=Image.open(io.BytesIO(png));assert image.size==(400,300) and image.mode=='1'
    assert len(render_monitor(summary,{},settings,'bin'))==15000

def test_two_codex_windows_bars_and_calendar_reset(tmp_path,monkeypatch):
    import monitor_render
    texts=[]
    original=monitor_render._draw_text
    def draw(d,pos,value,font,**kwargs):
        texts.append(str(value)); return original(d,pos,value,font,**kwargs)
    monkeypatch.setattr(monitor_render,'_draw_text',draw)
    s=Store(tmp_path/'db')
    s.quota(Quota(provider='codex',account='default',fetched_at=time.time(),windows=[Window(label='5小时',remaining_percent=0,resets_at=1791047688),Window(label='7天',remaining_percent=100,resets_at=1791047688)]))
    image=Image.open(io.BytesIO(render_monitor(s.summary(),{},{})))
    assert '5h' in texts and '7天' in texts
    assert '10月4日 01:14重置' in texts
    assert not any('其他额度' in t for t in texts)
    assert image.getpixel((50,76))!=0 and image.getpixel((50,119))==0

def test_missing_codex_five_hour_window_is_unknown(tmp_path,monkeypatch):
    import monitor_render
    texts=[]
    monkeypatch.setattr(monitor_render,'_draw_text',lambda d,pos,value,font,**kwargs:texts.append(str(value)))
    s=Store(tmp_path/'db')
    s.quota(Quota(provider='codex',account='default',fetched_at=time.time(),windows=[Window(label='7天',remaining_percent=91)]))
    render_monitor(s.summary(),{},{})
    assert '使用一次激活5h' in texts and '--' in texts and '91%' in texts
    assert '0%' not in texts

def test_pro_without_short_window_and_real_limits_take_precedence(tmp_path,monkeypatch):
    import monitor_render
    texts=[]
    monkeypatch.setattr(monitor_render,'_draw_text',lambda d,pos,value,font,**kwargs:texts.append(str(value)))
    s=Store(tmp_path/'db')
    s.quota(Quota(provider='codex',account='default',plan='pro',fetched_at=time.time(),windows=[Window(label='7天',remaining_percent=90)]))
    render_monitor(s.summary(),{},{})
    assert '∞' in texts and '额度与重置未返回' not in texts
    texts.clear()
    s.quota(Quota(provider='codex',account='default',plan='pro',fetched_at=time.time(),windows=[Window(label='5小时',remaining_percent=42),Window(label='7天',remaining_percent=90)]))
    render_monitor(s.summary(),{},{})
    assert '∞' not in texts and '42%' in texts

def test_billing_window_boundaries_and_holiday():
    from monitor_periods import billing_periods
    from datetime import datetime
    from zoneinfo import ZoneInfo
    def at(value): return billing_periods(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp())
    assert at('2026-10-08T14:00')['glm']['active']
    assert not at('2026-10-08T18:00')['glm']['active']
    assert not at('2026-09-28T15:00')['glm']['active']
    assert not at('2026-10-11T15:00')['glm']['active']
    assert at('2026-10-08T22:00')['qoder']['active']
    assert at('2026-10-09T07:59')['qoder']['active']
    assert not at('2026-10-09T08:00')['qoder']['active']

def test_agent_hook_mapping_is_neutral_and_durable(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[2]/'agent/agent.py'
    spec=importlib.util.spec_from_file_location('test_lab_agent',path);agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
    monkeypatch.setattr(agent,'DB',tmp_path/'queue.db');monkeypatch.setattr(agent,'CONFIG',tmp_path/'config.json')
    agent.CONFIG.write_text(json.dumps({'machine_id':'test','server_url':'http://127.0.0.1:1','token':'t'}))
    for typ in ['UserPromptSubmit','PermissionRequest','PostToolUse','PostToolUseFailure','Stop']:
        agent.hook('qoder',{'session_id':'s','hook_event_name':typ,'cwd':'C:/test/project','error':'not sent','last_assistant_message':'private reply'})
    with agent.db() as conn: rows=conn.execute('SELECT body FROM queue ORDER BY rowid').fetchall()
    assert [json.loads(row[0])['status'] for row in rows]==['running','waiting_approval','running','completed']
    assert all('private reply' not in row[0] and 'not sent' not in row[0] for row in rows)
    assert len({json.loads(row[0])['turn_id'] for row in rows})==1
    assert not agent.flush()
    with agent.db() as conn: assert conn.execute('SELECT count(*) FROM queue').fetchone()[0]==4
    agent.hook('qoder',{'session_id':'s','hook_event_name':'SessionStart'})
    agent.record('qoder','s','running',stamp=1)
    with agent.db() as conn:
        assert conn.execute('SELECT status FROM sessions').fetchone()[0]=='completed'
        assert conn.execute('SELECT count(*) FROM queue').fetchone()[0]==4
    attempts=[]
    def send_with_rejected_first(path,payload):
        attempts.append(payload)
        if len(attempts)==1: raise agent.urllib.error.HTTPError('http://test',422,'clock',{},None)
        return {'accepted':True}
    monkeypatch.setattr(agent,'send',send_with_rejected_first)
    assert agent.flush() and len(attempts)==4
    with agent.db() as conn:
        assert conn.execute('SELECT count(*) FROM queue').fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM rejected').fetchone()[0]==1

def test_qoder_sdk_uses_personal_access_token(monkeypatch):
    import asyncio, os, sys, types
    from monitor_collectors import qoder_query
    def auth():
        assert os.environ['QODER_PERSONAL_ACCESS_TOKEN']=='test-token'
        return 'auth'
    class Client:
        def __init__(self,options): assert options['auth']=='auth'
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get_usage_info(self): return {'userQuota':{'remaining':5}}
    monkeypatch.setenv('QODER_PERSONAL_ACCESS_TOKEN','old')
    monkeypatch.setitem(sys.modules,'qoder_agent_sdk',types.SimpleNamespace(QoderAgentOptions=lambda **kw:kw,QoderSDKClient=Client,access_token_from_env=auth))
    assert asyncio.run(qoder_query('test-token'))['userQuota']['remaining']==5

def test_hook_install_preserves_existing_permissions(tmp_path):
    path=Path(__file__).resolve().parents[2]/'agent/agent.py'
    spec=importlib.util.spec_from_file_location('install_agent',path);agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
    cfg=tmp_path/'hooks.json';cfg.write_text(json.dumps({'permissions':{'deny':['x']},'hooks':{'Stop':[{'hooks':[{'command':'my-command','type':'command'}]}]}}))
    agent.merge_hooks(cfg,'codex');agent.merge_hooks(cfg,'codex')
    result=json.loads(cfg.read_text());assert result['permissions']=={'deny':['x']}
    assert len(result['hooks']['Stop'])==2


def test_qoder_china_sdk_routing(monkeypatch):
    import asyncio,os,sys,types
    from monitor_collectors import qoder_query
    def auth():
        assert os.environ['QODERCN_PERSONAL_ACCESS_TOKEN']=='cn-test'
        return 'cn-auth'
    class Client:
        def __init__(self,options): assert options['auth']=='cn-auth'
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get_usage_info(self): return {'userQuota':{'remaining':819}}
    monkeypatch.setenv('QODERCN_PERSONAL_ACCESS_TOKEN','old')
    monkeypatch.setitem(sys.modules,'qodercn_agent_sdk',types.SimpleNamespace(QoderAgentOptions=lambda **kw:kw,QoderSDKClient=Client,access_token_from_env=auth))
    assert asyncio.run(qoder_query('cn-test','cn'))['userQuota']['remaining']==819

def test_qoder_region_roundtrip(tmp_path):
    c,m=client(tmp_path)
    assert c.put('/api/settings',json={'accounts':{'qoder':{'enabled':True,'region':'cn','token':'private'}}}).status_code==200
    data=c.get('/api/monitor').json()['settings']['accounts']['qoder']
    assert data['region']=='cn' and data['configured'] and 'token' not in data

def test_qoder_expiry_is_not_reset_or_addon_expiry():
    from monitor_collectors import normalize_qoder
    from monitor_render import window_date_label, credit_ratio
    q=normalize_qoder({'expiresAt':1790496000000,'userQuota':{'remaining':819,'total':6000},'addOnQuota':{'remaining':0,'total':700}},'demo')
    plan,addon=[w.model_dump() for w in q.windows]
    assert plan['expires_at']==1790496000 and plan['resets_at'] is None
    assert addon['expires_at'] is None
    assert window_date_label('qoder',plan)=='9月27日到期'
    assert window_date_label('qoder',addon)=='到期日未返回'
    assert credit_ratio(plan)=='819/6000' and credit_ratio(addon)=='0/700'
    assert credit_ratio({})=='--/--'
    assert window_date_label('glm',{'label':'5小时'})=='使用一次激活5h'
    assert '激活' not in window_date_label('glm',{'label':'7天'})

def test_renewal_date_validation_and_persistence(tmp_path):
    c,m=client(tmp_path)
    body={'prices':{'qoder':{'amount':169,'renewal_date':'2026-10-27'}}}
    assert c.put('/api/settings',json=body).status_code==200
    assert c.get('/api/monitor').json()['settings']['prices']['qoder']['renewal_date']=='2026-10-27'
    body['prices']['qoder']['renewal_date']='2026-02-30'
    assert c.put('/api/settings',json=body).status_code==422
    body['prices']['qoder']['renewal_date']=None
    assert c.put('/api/settings',json=body).status_code==200

def test_optional_remote_addresses(tmp_path):
    c,m=client(tmp_path)
    for address in ['http://192.0.2.10:8787','https://dashboard.example.com']:
        assert c.post('/api/lab-package',json={'server_url':address,'machine_id':'remote'}).status_code==200
    for address in ['http://8.8.8.8','http://127.0.0.1:8787','https://user:password@example.com','https://example.com/?token=secret']:
        assert c.post('/api/lab-package',json={'server_url':address,'machine_id':'remote'}).status_code==422

def test_power_settings_defaults_persistence_and_validation(tmp_path):
    c,m=client(tmp_path)
    assert c.get('/api/monitor').json()['settings']['power']=={'usb_sleep_enabled':True,'usb_sleep_minutes':5}
    assert m.power_headers()['X-RLCD-Usb-Sleep-Seconds']=='300'
    assert c.put('/api/settings',json={'power':{'usb_sleep_enabled':True,'usb_sleep_minutes':0}}).status_code==200
    assert m.power_headers()['X-RLCD-Usb-Sleep-Seconds']=='0'
    assert c.put('/api/settings',json={'prices':{}}).status_code==200
    assert Monitor(tmp_path).power_headers()['X-RLCD-Usb-Sleep-Seconds']=='0'
    assert c.put('/api/settings',json={'power':{'usb_sleep_enabled':False,'usb_sleep_minutes':5}}).status_code==200
    assert m.power_headers()['X-RLCD-Usb-Sleep-Enabled']=='0'
    for bad in [-1,1441,1.5]:
        assert c.put('/api/settings',json={'power':{'usb_sleep_minutes':bad}}).status_code==422

def test_power_frame_contract(tmp_path,monkeypatch):
    import app as application
    monitor=Monitor(tmp_path)
    monkeypatch.setattr(application,'monitor',monitor)
    response=TestClient(application.app).get('/frame.bin?usb=1&power_version=1')
    assert response.status_code==200 and len(response.content)==15000
    assert response.headers['X-RLCD-Usb-Sleep-Enabled']=='1'
    assert response.headers['X-RLCD-Usb-Sleep-Seconds']=='300'
    assert monitor.environment['usb_connected'] is True
    assert monitor.environment['power_firmware_version']==1

def test_cosmetic_settings_do_not_refresh_accounts(tmp_path):
    c,m=client(tmp_path)
    assert c.put('/api/settings',json={'prices':{'codex':{'renewal_date':'2026-01-31'}}}).status_code==200
    assert not m.wake.is_set()
    assert c.put('/api/settings',json={'power':{'usb_sleep_minutes':7}}).status_code==200
    assert not m.wake.is_set()
    assert c.put('/api/settings',json={'accounts':{'codex':{'enabled':True,'account':'default'}}}).status_code==200
    assert not m.wake.is_set()
    assert c.put('/api/settings',json={'accounts':{'codex':{'enabled':True,'account':'second'}}}).status_code==200
    assert m.wake.is_set()

def test_failed_settings_write_preserves_current_state(tmp_path,monkeypatch):
    import pytest
    from monitor_service import Settings
    _,m=client(tmp_path)
    before=json.dumps(m.settings)
    def fail(*args): raise OSError('Disk write unavailable')
    monkeypatch.setattr(Path,'replace',fail)
    with pytest.raises(OSError): m.save(Settings.model_validate({'prices':{'codex':{'amount':1}}}))
    assert json.dumps(m.settings)==before and not m.wake.is_set()

def test_old_account_response_cannot_replace_new_account(tmp_path,monkeypatch):
    import monitor_service
    _,m=client(tmp_path)
    old={'enabled':True,'account':'old'}
    m.settings['accounts']['codex']={'enabled':True,'account':'new'}
    monkeypatch.setattr(monitor_service,'collect',lambda *args:Quota(provider='codex',account='old',fetched_at=time.time(),windows=[Window(label='5小时',remaining_percent=40)]))
    m.collect_one('codex',old)
    assert 'codex' not in m.store.summary()['quotas']

def test_noop_save_during_collection_keeps_valid_response(tmp_path,monkeypatch):
    import monitor_service
    _,m=client(tmp_path)
    old=dict(m.settings['accounts']['codex'])
    def collect(*args):
        m.save(monitor_service.Settings.model_validate({'accounts':{'codex':old}}))
        return Quota(provider='codex',account='default',fetched_at=time.time(),windows=[Window(label='5小时',remaining_percent=40)])
    monkeypatch.setattr(monitor_service,'collect',collect)
    m.collect_one('codex',old)
    assert m.store.summary()['quotas']['codex']['windows'][0]['remaining_percent']==40
    assert not m.wake.is_set()

def test_local_agent_reports_without_remote_install(tmp_path,monkeypatch):
    import monitor_local
    monkeypatch.setenv('CODEX_HOME',str(tmp_path/'codex'))
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path/'home'))
    m=Monitor(tmp_path/'dashboard')
    # Finish after the first successful heartbeat; never inspect real session records.
    original=importlib.util.module_from_spec
    def module(spec):
        result=original(spec)
        loader=spec.loader.exec_module
        def execute(mod):
            loader(mod)
            mod.scan_codex=lambda:None
            mod.clients=lambda:{'codex':'connected','qoder':'closed'}
            def run(stop_event):
                mod.send('heartbeat',{'machine_id':'local-pc','clients':mod.clients()})
                mod.record('codex','local-session','running','demo')
                mod.flush()
            mod.run=run
        spec.loader.exec_module=execute
        return result
    monkeypatch.setattr(importlib.util,'module_from_spec',module)
    m.local.start();m.local.shutdown()
    assert not m.local.error
    summary=m.store.summary()
    assert summary['machines'][0]['id']=='local-pc'
    assert summary['tasks'][0]['display_status']=='running'
    assert (tmp_path/'codex/hooks.json').exists()
