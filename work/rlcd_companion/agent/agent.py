"""Windows lab reporter: durable local events, read-only hooks, no model prompts."""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid
from datetime import datetime
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parent
DB=ROOT/'agent.sqlite3'
CONFIG=ROOT/'config.json'

@contextmanager
def db():
    conn=sqlite3.connect(DB,timeout=2)
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS queue(id TEXT PRIMARY KEY,path TEXT,body TEXT);
    CREATE TABLE IF NOT EXISTS sessions(tool TEXT,id TEXT,turn TEXT,seq INTEGER,status TEXT,PRIMARY KEY(tool,id));
    CREATE TABLE IF NOT EXISTS offsets(path TEXT PRIMARY KEY,offset INTEGER);
    CREATE TABLE IF NOT EXISTS session_times(tool TEXT,id TEXT,stamp REAL,PRIMARY KEY(tool,id));
    CREATE TABLE IF NOT EXISTS pending_inputs(session TEXT PRIMARY KEY,call_id TEXT);
    CREATE TABLE IF NOT EXISTS rejected(id TEXT PRIMARY KEY,path TEXT,body TEXT,http_status INTEGER);
    CREATE TABLE IF NOT EXISTS reported_links(session TEXT PRIMARY KEY,signature TEXT);
    ''')
    try:
        with conn: yield conn
    finally: conn.close()

def config(): return json.loads(CONFIG.read_text(encoding='utf-8'))

def enqueue(path,payload):
    with db() as conn:
        conn.execute('INSERT OR IGNORE INTO queue VALUES(?,?,?)',(payload.get('event_id',str(uuid.uuid4())),path,json.dumps(payload)))

def record(tool,session,state,project='',turn=None,stamp=None,new_turn=False,event_id=None):
    if not session: return
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        stamp = stamp if stamp is not None else time.time()
        previous=conn.execute('SELECT stamp FROM session_times WHERE tool=? AND id=?',(tool,session)).fetchone()
        if previous and stamp<previous[0]: return
        conn.execute('INSERT OR REPLACE INTO session_times VALUES(?,?,?)',(tool,session,stamp))
        row=conn.execute('SELECT turn,seq,status FROM sessions WHERE tool=? AND id=?',(tool,session)).fetchone()
        turn=turn or (str(uuid.uuid4()) if new_turn or not row else row[0])
        sequence=(row[1]+1) if row and row[0]==turn else 0
        payload={'event_id':event_id or str(uuid.uuid4()),'machine_id':config()['machine_id'],'tool':tool,'session_id':session[:160],'turn_id':turn[:160],'sequence':sequence,'occurred_at':stamp or time.time(),'status':state,'project':project[:80]}
        conn.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?)',(tool,session,turn,sequence,state))
        conn.execute('INSERT OR IGNORE INTO queue VALUES(?,?,?)',(payload['event_id'],'task',json.dumps(payload)))

def hook(tool,payload):
    event=payload.get('hook_event_name'); state=None
    session=payload.get('session_id') or payload.get('thread_id')
    tool_name=str(payload.get('tool_name',''))
    if event=='UserPromptSubmit': state='running'
    elif event=='SessionStart':
        with db() as conn: previous=conn.execute('SELECT 1 FROM sessions WHERE tool=? AND id=?',(tool,session)).fetchone()
        if not previous: state='idle'
    elif event=='PermissionRequest': state='waiting_approval'
    elif event=='PreToolUse': state='waiting_input' if 'request_user_input' in tool_name or 'AskUserQuestion' in tool_name else 'running'
    elif event=='PostToolUse': state='running'
    elif event=='Stop': state='completed'
    elif event=='Interrupt': state='interrupted'
    elif event=='StopFailure': state='failed'
    elif event=='Notification':
        typ=payload.get('notification_type')
        if typ in ('permission_prompt','permission'): state='waiting_approval'
        elif typ in ('elicitation_dialog','idle_prompt'): state='waiting_input'
    elif event=='PostToolUseFailure' and payload.get('is_interrupt'): state='interrupted'
    # A failed tool call is not a failed overall task. SessionEnd preserves the last result.
    if state:
        record(tool,session,state,Path(payload.get('cwd') or '').name,turn=payload.get('turn_id'),new_turn=event=='UserPromptSubmit')

def send(path,payload):
    cfg=config()
    request=urllib.request.Request(cfg['server_url'].rstrip('/')+'/api/ingest/'+path,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+cfg['token'],'Content-Type':'application/json'})
    # ZeroTier traffic must not go through an HTTP proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=4) as response: return json.load(response)

def flush():
    deadline=time.monotonic()+8
    with db() as conn: rows=conn.execute('SELECT id,path,body FROM queue ORDER BY rowid LIMIT 100').fetchall()
    for ident,path,body in rows:
        try: send(path,json.loads(body))
        except urllib.error.HTTPError as e:
            if e.code not in (400,409,422): return False
            # Retain invalid records for diagnosis without blocking unrelated task events.
            with db() as conn:
                conn.execute('INSERT OR REPLACE INTO rejected VALUES(?,?,?,?)',(ident,path,body,e.code))
                conn.execute('DELETE FROM queue WHERE id=?',(ident,))
            continue
        except Exception: return False
        with db() as conn: conn.execute('DELETE FROM queue WHERE id=?',(ident,))
        if time.monotonic()>=deadline: break
    return True

def clients():
    try:
        result=subprocess.run(['tasklist','/FO','CSV','/NH'],capture_output=True,text=True,timeout=5,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        names={r[0].lower() for r in csv.reader(io.StringIO(result.stdout)) if r}
        return {'codex':'connected' if 'codex.exe' in names else 'closed','qoder':'connected' if 'qoder.exe' in names else 'closed'}
    except Exception: return {'codex':'unknown','qoder':'unknown'}

def report_session_metadata(meta):
    session=meta.get('id')
    if not session:return
    source=meta.get('source',{})
    if isinstance(source,str):
        try:source=json.loads(source)
        except ValueError:source={'subagent':True} if source.startswith('subagent') else {}
    sub=source.get('subagent') if isinstance(source,dict) else None
    spawn=sub.get('thread_spawn',{}) if isinstance(sub,dict) else {}
    parent=meta.get('parent_thread_id') or (spawn.get('parent_thread_id') if isinstance(spawn,dict) else None)
    value={'machine_id':config()['machine_id'],'tool':'codex','session_id':session,'parent_session_id':parent,'is_subagent':bool(parent or sub is not None)}
    signature=json.dumps(value,sort_keys=True)
    with db() as conn:
        old=conn.execute('SELECT signature FROM reported_links WHERE session=?',(session,)).fetchone()
        if old and old[0]==signature:return
        conn.execute('INSERT OR REPLACE INTO reported_links VALUES(?,?)',(session,signature))
        conn.execute('INSERT INTO queue VALUES(?,?,?)',(str(uuid.uuid4()),'session',json.dumps(value)))

def scan_codex():
    directory=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'sessions'
    if not directory.exists(): return
    files=sorted(directory.rglob('*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]
    for file in files:
        if time.time()-file.stat().st_mtime>7*86400: continue
        with db() as conn: row=conn.execute('SELECT offset FROM offsets WHERE path=?',(str(file),)).fetchone()
        offset=row[0] if row else 0
        size=file.stat().st_size
        with file.open('rb') as f:
            try: meta=json.loads(f.readline()).get('payload',{})
            except ValueError: continue
            session=meta.get('id'); project=Path(meta.get('cwd') or '').name
            if not session: continue
            report_session_metadata(meta)
            if size==offset:continue
            if offset>size: offset=0
            if not offset and size>256000:
                f.seek(size-256000);f.readline()
            else: f.seek(offset)
            end=f.tell()
            while True:
                position=f.tell();line=f.readline()
                if not line or not line.endswith(b'\n'): break
                end=f.tell()
                try: entry=json.loads(line)
                except ValueError: continue
                p=entry.get('payload') or {};state=None;turn=p.get('turn_id')
                if entry.get('type')=='event_msg':
                    state={'task_started':'running','task_complete':'completed','task_completed':'completed','turn_aborted':'interrupted'}.get(p.get('type'))
                elif entry.get('type')=='response_item':
                    if p.get('type')=='function_call' and p.get('name')=='request_user_input':
                        state='waiting_input'
                        with db() as conn: conn.execute('INSERT OR REPLACE INTO pending_inputs VALUES(?,?)',(session,p.get('call_id')))
                    elif p.get('type')=='function_call_output':
                        with db() as conn:
                            pending=conn.execute('SELECT call_id FROM pending_inputs WHERE session=?',(session,)).fetchone()
                            if pending and pending[0] and pending[0]==p.get('call_id'):
                                state='running'
                                conn.execute('DELETE FROM pending_inputs WHERE session=?',(session,))
                if state:
                    try: stamp=datetime.fromisoformat(entry['timestamp'].replace('Z','+00:00')).timestamp()
                    except (KeyError,ValueError): continue
                    record('codex',session,state,project,turn=turn,stamp=stamp,event_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f'{file}:{position}')))
            with db() as conn: conn.execute('INSERT OR REPLACE INTO offsets VALUES(?,?)',(str(file),end))

def collect_accounts():
    for provider,settings in config().get('accounts',{}).items():
        if not settings.get('enabled'): continue
        try:
            from monitor_collectors import collect
            payload=collect(provider,settings).model_dump()
        except Exception:
            payload={'provider':provider,'account':settings.get('account','default'),'fetched_at':time.time(),'error':'实验室账户采集失败，请在实验室电脑检查授权','windows':[]}
        enqueue('quota',payload)

def run(stop_event=None):
    import threading
    # One agent instance per installation; tasklist does not count this Python helper as Codex.
    import socket
    guard=socket.socket(); port=43000+int(uuid.uuid5(uuid.NAMESPACE_URL,str(ROOT)).hex[:4],16)%10000
    try: guard.bind(('127.0.0.1',port))
    except OSError: return
    quota_at=0; heartbeat_at=0; quota_thread=None
    while stop_event is None or not stop_event.is_set():
        try:
            scan_codex()
            flush()
            if time.monotonic()-heartbeat_at>=15:
                send('heartbeat',{'machine_id':config()['machine_id'],'clients':clients()});heartbeat_at=time.monotonic()
            if time.monotonic()-quota_at>=300 and (quota_thread is None or not quota_thread.is_alive()):
                quota_thread=threading.Thread(target=collect_accounts,daemon=True);quota_thread.start();quota_at=time.monotonic()
        except Exception: pass
        if stop_event is None: time.sleep(2)
        else: stop_event.wait(2)

def merge_hooks(path,tool):
    path.parent.mkdir(parents=True,exist_ok=True)
    original=path.read_text(encoding='utf-8-sig') if path.exists() else None
    data=json.loads(original) if original else {}
    if original:
        backup=path.with_name(path.name+'.before-rlcd-'+str(int(time.time())))
        backup.write_text(original,encoding='utf-8')
    events=['SessionStart','UserPromptSubmit','PreToolUse','PermissionRequest','PostToolUse','Stop','SessionEnd']
    events+=['Interrupt'] if tool=='codex' else ['Notification','PostToolUseFailure']
    command=f'"{sys.executable}" "{Path(__file__).resolve()}" hook --tool {tool}'
    for event in events:
        groups=data.setdefault('hooks',{}).setdefault(event,[])
        # Replace only our own entries; preserve all unrelated hooks and permissions.
        for group in groups:
            group['hooks']=[h for h in group.get('hooks',[]) if 'agent.py" hook --tool' not in h.get('command','')]
        groups[:]=[g for g in groups if g.get('hooks')]
        groups.append({'hooks':[{'type':'command','command':command,'timeout':2}]})
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')

def install():
    cfg=config()
    for key in ('server_url','machine_id','token'):
        if not cfg.get(key): raise ValueError(f'Missing {key}')
    merge_hooks(Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'hooks.json','codex')
    merge_hooks(Path.home()/'.qoder/settings.json','qoder')
    startup=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup'
    launcher=startup/'RLCD-Lab-Agent.cmd'
    launcher.write_text(f'@echo off\nstart "" "{Path(sys.executable).with_name("pythonw.exe")}" "{Path(__file__).resolve()}" run\n',encoding='utf-8')
    subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(Path(__file__).resolve()),'run'],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    print('Installed. Restart Qoder. In Codex, review and trust the RLCD hooks using /hooks. No approval policy was changed.')

def stop():
    # PowerShell matches this exact installation path, never all Python processes.
    needle=str(Path(__file__).resolve()).replace("'","''")
    command=f"Get-CimInstance Win32_Process | Where-Object {{ $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like '*{needle}* run*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId }}"
    subprocess.run(['powershell','-NoProfile','-Command',command],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def doctor():
    cfg=config();print('Machine:',cfg['machine_id']);print('Clients:',clients())
    with db() as conn: print('Queued:',conn.execute('SELECT count(*) FROM queue').fetchone()[0])
    with db() as conn: print('Rejected (check account alias / clock):',conn.execute('SELECT count(*) FROM rejected').fetchone()[0])
    try:
        send('heartbeat',{'machine_id':cfg['machine_id'],'clients':clients()});print('Server: connected')
    except Exception: print('Server: unavailable. Check ZeroTier, service address and token.')
    print('Codex hook trust must be reviewed in the Codex client. Qoder must be restarted after installing hooks.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','hook','install','stop','doctor']);parser.add_argument('--tool',choices=['codex','qoder']);args=parser.parse_args()
    if args.action=='hook':
        try: hook(args.tool,json.load(sys.stdin))
        except Exception: pass
        print('{}')  # Neutral valid output; never approves, denies, or asks the model to continue.
        raise SystemExit(0)
    globals()[args.action]()
