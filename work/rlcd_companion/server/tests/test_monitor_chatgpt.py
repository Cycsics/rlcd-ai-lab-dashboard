import io
import json
import struct
import time
from monitor_service import Monitor
from monitor_chatgpt import ChatGPTMonitor, task_state, rpc, MAX_FRAME, MACHINE
from monitor_store import Heartbeat
import pytest

def test_explicit_statuses_only():
    assert task_state('active')=='running'
    assert task_state('idle')=='idle'
    assert task_state('unrecognized')=='unknown'
    assert task_state({'type':'active','activeFlags':['waitingOnApproval']})=='waiting_approval'
    assert task_state({'type':'active','activeFlags':['waitingOnUserInput']})=='waiting_input'

def test_transitions_parallel_restart_and_no_false_completion(tmp_path):
    m=Monitor(tmp_path);c=m.chatgpt;now=time.time()
    c.apply([{'id':'a','status':'idle','title':'Old chat'}],now)
    assert not m.store.summary()['tasks']
    c.apply([{'id':'a','status':'active','title':'Demo A'},{'id':'b','status':'active','title':'Demo B'}],now+1)
    first=m.store.summary()['tasks'];assert len(first)==2
    c.apply([{'id':'a','status':'idle','title':'Demo A'},{'id':'b','status':'active','title':'Demo B'}],now+2)
    tasks={t['session_id']:t for t in m.store.summary()['tasks']}
    assert tasks['a']['status']=='idle' and tasks['b']['status']=='running'
    restarted=ChatGPTMonitor(m)
    restarted.apply([{'id':'a','status':'active','title':'Demo A'}],now+3)
    tasks={t['session_id']:t for t in m.store.summary()['tasks']}
    assert tasks['a']['turn_id']!=next(t for t in first if t['session_id']=='a')['turn_id']
    assert tasks['b']['status']=='unknown'
    m.store.heartbeat(Heartbeat(machine_id=MACHINE,clients={'chatgpt':'unknown'}))
    assert all(t['display_status']=='unknown' for t in m.store.summary()['tasks'])

def test_idle_becomes_history_and_render_does_not_crash(tmp_path):
    m=Monitor(tmp_path);now=time.time()
    m.chatgpt.apply([{'id':'a','status':'active','title':'A long ChatGPT task title'}],now-90000)
    m.chatgpt.apply([{'id':'a','status':'idle','title':'A long ChatGPT task title'}],now-89999)
    assert not m.store.summary()['tasks']
    m.chatgpt.apply([{'id':'a','status':'active','title':'A long ChatGPT task title'}],now)
    assert len(m.image('bin'))==15000

def test_failed_poll_marks_source_unknown_without_destroying_status(tmp_path,monkeypatch):
    m=Monitor(tmp_path);m.chatgpt.apply([{'id':'a','status':'active'}])
    def fail(*args,**kwargs):raise TimeoutError()
    monkeypatch.setattr('monitor_chatgpt.subprocess.run',fail)
    m.chatgpt.poll()
    task=m.store.summary()['tasks'][0]
    assert task['status']=='running' and task['display_status']=='unknown'
    assert m.chatgpt.error

def test_pipe_response_size_and_disconnect():
    class Stream:
        def __init__(self,data):self.data=io.BytesIO(data)
        def write(self,data):pass
        def read(self,n):return self.data.read(n)
    with pytest.raises(ValueError):rpc(Stream(struct.pack('<I',MAX_FRAME+1)),'tools/list',{},1)
    with pytest.raises(ValueError):rpc(Stream(b''),'tools/list',{},1)
    body=json.dumps({'id':1,'result':{'tools':[]}}).encode()
    assert rpc(Stream(struct.pack('<I',len(body))+body),'tools/list',{},1)=={'tools':[]}
