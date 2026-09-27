"""Read-only Codex desktop ChatGPT status bridge (Windows, experimental).

Uses the installed app-tools pipe protocol: tools/list + list_threads only.
Never reads messages, attachments, login tokens, or invokes write tools.
Run --pair from a Codex terminal once to bind its real caller context.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import uuid
from monitor_store import TaskEvent, Heartbeat

MAX_FRAME=8*1024*1024
MACHINE='local-chatgpt'

def read_exact(stream,n):
    data=bytearray()
    while len(data)<n:
        chunk=stream.read(n-len(data))
        if not chunk:raise ValueError('App disconnected')
        data.extend(chunk)
    return bytes(data)

def rpc(stream,method,params,request_id):
    body=json.dumps({'jsonrpc':'2.0','id':request_id,'method':method,'params':params}).encode()
    stream.write(struct.pack('<I',len(body))+body)
    length=struct.unpack('<I',read_exact(stream,4))[0]
    if length>MAX_FRAME:raise ValueError('Response too large')
    result=json.loads(read_exact(stream,length))
    if result.get('id')!=request_id or 'error' in result:raise ValueError('App request failed')
    return result['result']

def app_snapshot(config):
    if os.name!='nt':raise ValueError('Windows only')
    pipes=[config['pipe']]
    # App restarts replace the pipe name. Only choose a unique matching desktop pipe.
    available=['\\\\.\\pipe\\'+p for p in os.listdir('\\\\.\\pipe\\') if p.startswith('codex-browser-use-')]
    if pipes[0] not in available:
        if len(available)!=1:raise ValueError('No unique app connection')
        pipes=available
    with open(pipes[0],'r+b',buffering=0) as stream:
        catalog=rpc(stream,'tools/list',{'threadStartKind':'all'},1)
        tool=next(t for t in catalog['tools'] if t['name']=='list_threads')
        result=rpc(stream,'tools/call',{'arguments':{'limit':50},'callerSource':'codex','callId':'monitor-'+str(uuid.uuid4()),'namespace':tool['namespace'],'threadId':config['thread_id'],'tool':'list_threads','turnId':'monitor-read-'+str(uuid.uuid4())},2)
    if not result.get('success'):raise ValueError('App status unavailable')
    data=json.loads(next(x['text'] for x in result['contentItems'] if x['type']=='inputText'))
    if 'chatgpt' in data.get('unavailableSources',[]):raise ValueError('ChatGPT unavailable')
    # Whitelist metadata before crossing the subprocess boundary; discard summaries.
    return [{'id':t['id'],'status':t.get('status'),'title':t.get('title','ChatGPT'),'updatedAt':t.get('updatedAt')} for t in data.get('pinnedThreads',[])+data.get('threads',[]) if t.get('kind')=='chatgpt']

def task_state(status):
    if isinstance(status,dict):
        flags=status.get('activeFlags',[])
        if 'waitingOnApproval' in flags:return 'waiting_approval'
        if 'waitingOnUserInput' in flags:return 'waiting_input'
        status=status.get('type')
    return {'active':'running','running':'running','in_progress':'running','waiting_approval':'waiting_approval','waiting_input':'waiting_input','needs_input':'waiting_input','completed':'completed','interrupted':'interrupted','failed':'failed','idle':'idle'}.get(status,'unknown')

class ChatGPTMonitor:
    def __init__(self,monitor):
        self.monitor=monitor;self.thread=None;self.error='';self.last_seen=0
        self.config=monitor.directory/'chatgpt-bridge.json'
        self.previous={}
        for t in monitor.store.summary()['tasks']:
            if t['machine_id']==MACHINE and t['tool']=='chatgpt':
                self.previous[t['session_id']]={'state':t['status'],'title':t['project'],'turn':t['turn_id'],'seq':t['sequence']}

    def apply(self,rows,now=None):
        now=now or time.time();seen=set()
        self.monitor.store.heartbeat(Heartbeat(machine_id=MACHINE,clients={'chatgpt':'connected'}))
        for row in rows:
            session=row['id'];seen.add(session);state=task_state(row.get('status'))
            old=self.previous.get(session)
            # Do not fill the small screen with old idle chat history on first connection.
            if old is None and state=='unknown':continue
            if old is None and state=='idle':
                updated=row.get('updatedAt')
                if not isinstance(updated,(int,float)) or not now-86400<updated<=now:continue
            title=str(row.get('title') or 'ChatGPT')[:80]
            if old and old['state']==state and old['title']==title:continue
            turn=str(uuid.uuid4()) if not old or (state=='running' and old['state'] in ('idle','completed','interrupted','failed')) else old['turn']
            seq=old['seq']+1 if old and old['turn']==turn else 0
            stamp=row['updatedAt'] if old is None and state=='idle' else now
            self.monitor.store.event(TaskEvent(event_id=str(uuid.uuid4()),machine_id=MACHINE,tool='chatgpt',session_id=session,turn_id=turn,sequence=seq,occurred_at=stamp,status=state,project=title))
            self.previous[session]={'state':state,'title':title,'turn':turn,'seq':seq}
        # Missing from a bounded list does not mean completed.
        for session,old in list(self.previous.items()):
            if session not in seen and old['state'] not in ('unknown','completed','interrupted','failed'):
                self.monitor.store.event(TaskEvent(event_id=str(uuid.uuid4()),machine_id=MACHINE,tool='chatgpt',session_id=session,turn_id=old['turn'],sequence=old['seq']+1,occurred_at=now,status='unknown',project=old['title']))
                old.update(state='unknown',seq=old['seq']+1)
        self.last_seen=now;self.error=''

    def poll(self):
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--snapshot',str(self.config)],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError('Unavailable')
            self.apply(json.loads(result.stdout))
        except Exception:
            self.error='ChatGPT 状态源不可用，请打开 Codex；应用升级或绑定失效时重新绑定'
            self.monitor.store.heartbeat(Heartbeat(machine_id=MACHINE,clients={'chatgpt':'unknown'}))

    def start(self):
        if not self.config.exists() or self.thread:return
        def run():
            while not self.monitor.stop.is_set():
                started=time.monotonic();self.poll()
                self.monitor.stop.wait(max(1,30-(time.monotonic()-started)))
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()

if __name__=='__main__':
    try:
        if sys.argv[1]=='--pair':
            path=Path(os.environ.get('RLCD_DATA_DIR',Path(__file__).parent/'data'))/'chatgpt-bridge.json'
            cfg={'pipe':os.environ['CODEX_APP_TOOLS_PIPE_PATH'],'thread_id':os.environ['CODEX_THREAD_ID']}
            rows=app_snapshot(cfg)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(cfg),encoding='utf-8')
            print('ChatGPT bridge paired; visible chat count:',len(rows))
        elif sys.argv[1]=='--snapshot':
            rows=app_snapshot(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
            sys.stdout.buffer.write(json.dumps(rows).encode())
        else:raise ValueError('Unknown action')
    except Exception:
        print('ChatGPT bridge unavailable; bind from a running Codex terminal.',file=sys.stderr)
        sys.exit(1)

