import struct
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from monitor_api import normalize_api, QueryError, valid_query_url, request_bytes
from monitor_subscription import timestamp, normalize_claude, normalize_grok
from monitor_service import Monitor
from monitor_store import Quota, Balance, Store
from monitor_render import render_monitor

def test_balance_zero_missing_negative_and_currency():
    rows=normalize_api({'balance_infos':[{'currency':'CNY','total_balance':'0'},{'currency':'USD','total_balance':'2.50'}]}, {})
    assert [(r.currency,r.remaining) for r in rows]==[('CNY',0),('USD',2.5)]
    with pytest.raises(QueryError):normalize_api({'balance_infos':[{'currency':'USD'}]}, {})
    r=normalize_api({'data':{'total_credits':10,'total_usage':12}},{'template':'openrouter'})[0]
    assert r.remaining==-2 and r.used==12 and r.total==10
    with pytest.raises(QueryError):normalize_api({'data':{'total_credits':10}},{'template':'openrouter'})
    assert normalize_api({'code':0,'data':{'totalBalance':'0'}},{'template':'siliconflow','region':'cn'})[0].currency=='CNY'

def test_custom_and_newapi_units():
    r=normalize_api({'data':{'quota':500000,'used_quota':1000000}},{'template':'newapi','divisor':500000})[0]
    assert (r.remaining,r.used,r.total)==(1,2,3)
    r=normalize_api({'data':[{'balance':'1050'}]},{'template':'custom','balance_path':'data.0.balance','divisor':100,'currency':'CNY'})[0]
    assert r.remaining==10.5 and r.used is None and r.total is None
    with pytest.raises(QueryError):normalize_api({'balance':'NaN'},{'template':'custom'})

@pytest.mark.parametrize('url',['https://u:p@example.com/a','https://example.com/?token=secret','http://8.8.8.8/a','file:///a'])
def test_unsafe_query_addresses(url):
    assert not valid_query_url(url)

def test_redirect_never_forwards_token():
    paths=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(302);self.send_header('Location','/second');self.end_headers()
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        with pytest.raises(QueryError,match='重定向'):request_bytes(f'http://127.0.0.1:{server.server_port}/first','fake-test-token')
        assert paths==['/first']
    finally:server.shutdown();server.server_close();worker.join()

def test_claude_offsets_and_unknown_usage():
    assert timestamp('2026-01-01T00:00:00-05:00')==timestamp('2026-01-01T05:00:00Z')
    q=normalize_claude({'five_hour':{'utilization':0},'seven_day':{'utilization':None}},'a')
    assert q.windows[0].remaining_percent==100 and q.windows[1].remaining_percent is None
    with pytest.raises(QueryError):normalize_claude({'five_hour':{'utilization':101}},'a')

def frame(payload):return b'\x00'+len(payload).to_bytes(4,'big')+payload

def test_grok_schema_and_rpc_errors():
    body=b'\x0d'+struct.pack('<f',25)
    q=normalize_grok(frame(b'\x0a'+bytes([len(body)])+body),{},'a')
    assert q.windows[0].remaining_percent==75
    with pytest.raises(QueryError):normalize_grok(frame(b'\x0a\x00'),{},'a')
    with pytest.raises(QueryError):normalize_grok(frame(b'\x0a'+bytes([len(body)])+body),{'grpc-status':'16'},'a')
    with pytest.raises(QueryError):normalize_grok(b'\x00\x00',{},'a')

def test_api_failure_preserves_last_balance(tmp_path):
    s=Store(tmp_path/'db');ts=time.time()-1000
    s.quota(Quota(provider='api1',account='a',fetched_at=ts,kind='api',balances=[Balance(currency='USD',remaining=3)]))
    s.quota(Quota(provider='api1',account='a',fetched_at=time.time(),kind='api',error='offline'))
    q=s.summary()['quotas']['api1']
    assert q['balances'][0]['remaining']==3 and q['fetched_at']==ts and q['stale']

def test_modes_settings_and_secret_redaction(tmp_path):
    m=Monitor(tmp_path);app=FastAPI();app.include_router(m.router());c=TestClient(app)
    assert c.get('/api/monitor').json()['settings']['display']=={'mode':'subscription','subscriptions':['codex','glm','qoder']}
    for slots in [['codex','codex','glm'],['api1','glm','qoder']]:
        assert c.put('/api/settings',json={'display':{'mode':'api','subscriptions':slots}}).status_code==422
    assert c.put('/api/settings',json={'display':{'mode':'api'},'accounts':{'api1':{'token':'fake-secret-test-only','name':'Demo'}}}).status_code==200
    assert 'fake-secret-test-only' not in c.get('/api/monitor').text
    assert c.get('/api/monitor').json()['settings']['display']['mode']=='api'
    assert c.post('/api/connections/api1/test',headers={'Origin':'https://example.com'}).status_code==403
    assert len(render_monitor(m.store.summary(),{},m.public_settings(),'bin'))==15000

def test_api_render_keeps_currencies_separate(monkeypatch):
    import monitor_render
    texts=[];original=monitor_render._draw_text
    def capture(d,pos,value,font,**kwargs):
        texts.append(str(value));return original(d,pos,value,font,**kwargs)
    monkeypatch.setattr(monitor_render,'_draw_text',capture)
    q={'balances':[{'currency':'USD','remaining':5},{'currency':'CNY','remaining':8}]}
    render_monitor({'now':time.time(),'quotas':{'api1':q},'tasks':[],'machines':[]},{},{'display':{'mode':'api'}})
    assert any('USD' in t for t in texts) and any('CNY' in t for t in texts)
    assert not any('续费' in t for t in texts)
