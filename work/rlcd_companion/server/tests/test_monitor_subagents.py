import importlib.util
import json
from pathlib import Path
import time
from monitor_store import Store,TaskEvent,SessionLink

def test_children_nested_orphans_and_late_link(tmp_path):
    s=Store(tmp_path/'db');now=time.time()
    for name,status in [('root','running'),('child','running'),('nested','interrupted'),('orphan','running'),('other','running')]:
        s.event(TaskEvent(event_id=name,machine_id='pc',tool='codex',session_id=name,turn_id='t',sequence=0,occurred_at=now,status=status,project='same project'))
    assert len(s.summary()['tasks'])==5
    for name,parent in [('child','root'),('nested','child'),('orphan',None)]:
        s.session_link(SessionLink(machine_id='pc',session_id=name,parent_session_id=parent,is_subagent=True))
    result=Store(tmp_path/'db').summary()
    assert {t['session_id'] for t in result['tasks']}=={'root','other'}
    assert {t['session_id'] for t in result['subtasks']}=={'child','orphan'}
    assert any(t['session_id']=='nested' for t in result['history'])
    assert next(t for t in result['tasks'] if t['session_id']=='root')['subtask_count']==1

def test_terminal_leaves_screen_without_deleting_detail(tmp_path):
    s=Store(tmp_path/'db');now=time.time()
    s.event(TaskEvent(event_id='e',machine_id='pc',tool='codex',session_id='main',turn_id='t',sequence=0,occurred_at=now-301,status='interrupted'))
    assert len(s.summary()['tasks'])==1 and not s.summary()['screen_tasks']

def test_metadata_backfill_even_when_log_offset_is_current(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('subagent_test',Path(__file__).resolve().parents[2]/'agent/agent.py')
    agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
    agent.DB=tmp_path/'queue.db';agent.CONFIG=tmp_path/'config.json'
    agent.CONFIG.write_text(json.dumps({'machine_id':'pc'}))
    directory=tmp_path/'sessions';directory.mkdir()
    f=directory/'test.jsonl'
    f.write_text(json.dumps({'payload':{'id':'child','source':{'subagent':{'thread_spawn':{'parent_thread_id':'root'}}}}})+'\n')
    monkeypatch.setenv('CODEX_HOME',str(tmp_path))
    with agent.db() as db:db.execute('INSERT INTO offsets VALUES(?,?)',(str(f),f.stat().st_size))
    agent.scan_codex();agent.scan_codex()
    with agent.db() as db:rows=db.execute('SELECT path,body FROM queue').fetchall()
    assert len(rows)==1 and rows[0][0]=='session'
    assert json.loads(rows[0][1])['parent_session_id']=='root'
