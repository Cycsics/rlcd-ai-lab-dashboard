"""Persistent quota snapshots and task events. No prompts or credentials in this DB."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

Provider = Literal['codex', 'glm', 'qoder', 'claude', 'grok', 'api1', 'api2', 'api3']
TaskState = Literal['running', 'waiting_approval', 'waiting_input', 'completed', 'interrupted', 'failed', 'idle', 'unknown']
LABELS = {'running':'执行中','waiting_approval':'等你确认','waiting_input':'等你输入','completed':'本轮完成','interrupted':'已中断','failed':'执行失败','idle':'空闲','unknown':'状态未知','offline':'电脑离线'}
PRIORITY = {'waiting_approval':0,'waiting_input':0,'interrupted':1,'failed':1,'running':2,'unknown':3,'completed':4,'idle':5}

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Window(StrictModel):
    label: str = Field(max_length=30)
    remaining_percent: float | None = Field(None, ge=0, le=100)
    remaining: float | None = Field(None, ge=0)
    total: float | None = Field(None, ge=0)
    unit: str = Field('', max_length=20)
    resets_at: int | None = Field(None, ge=0)
    expires_at: int | None = Field(None, ge=0)

class Balance(StrictModel):
    currency: str = Field('USD',max_length=12)
    remaining: float | None = None
    used: float | None = Field(None,ge=0)
    total: float | None = Field(None,ge=0)

class Quota(StrictModel):
    provider: Provider
    account: str = Field(min_length=1, max_length=100)
    fetched_at: float = Field(gt=0)
    windows: list[Window] = Field(default_factory=list, max_length=8)
    plan: str = Field('', max_length=80)
    error: str = Field('', max_length=160)
    kind: Literal['subscription','api'] = 'subscription'
    balances: list[Balance] = Field(default_factory=list,max_length=8)

class TaskEvent(StrictModel):
    event_id: str = Field(min_length=1, max_length=160)
    machine_id: str = Field(min_length=1, max_length=80)
    tool: Literal['codex','qoder','chatgpt']
    session_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=0)
    occurred_at: float = Field(gt=0)
    status: TaskState
    project: str = Field('', max_length=80)

class Heartbeat(StrictModel):
    machine_id: str = Field(min_length=1, max_length=80)
    clients: dict[Literal['codex','qoder','chatgpt'], Literal['connected','closed','unknown']] = Field(default_factory=dict)

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS quotas(provider TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, received REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(machine TEXT,tool TEXT,session TEXT,turn TEXT,payload TEXT NOT NULL,stamp REAL,seq INTEGER,
                PRIMARY KEY(machine,tool,session,turn));
            CREATE TABLE IF NOT EXISTS machines(id TEXT PRIMARY KEY,seen REAL,clients TEXT);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA journal_mode=WAL')
        try:
            with db: yield db
        finally: db.close()

    def quota(self, q: Quota):
        value = q.model_dump()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,updated FROM quotas WHERE provider=?',(q.provider,)).fetchone()
            if row and q.fetched_at < row[1]: return False
            if row and q.error:
                old = json.loads(row[0])
                if old['account'] == q.account:
                    value = {**old, 'error':q.error}
            db.execute('INSERT OR REPLACE INTO quotas VALUES(?,?,?)',(q.provider,json.dumps(value),q.fetched_at))
        return True

    def event(self, event: TaskEvent):
        p = event.model_dump()
        now = time.time()
        if p['occurred_at'] > now + 300: raise ValueError('电脑时间超前，请同步系统时间')
        key = (event.machine_id,event.tool,event.session_id,event.turn_id)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM events WHERE id=?',(event.event_id,)).fetchone(): return False
            db.execute('INSERT INTO events VALUES(?,?)',(event.event_id,now))
            row = db.execute('SELECT stamp,seq FROM tasks WHERE machine=? AND tool=? AND session=? AND turn=?',key).fetchone()
            if row and (event.occurred_at,event.sequence) <= tuple(row): return False
            db.execute('INSERT OR REPLACE INTO tasks VALUES(?,?,?,?,?,?,?)',(*key,json.dumps(p),event.occurred_at,event.sequence))
            db.execute('DELETE FROM events WHERE received<?',(now-30*86400,))
            db.execute('DELETE FROM tasks WHERE stamp<?',(now-30*86400,))
        return True

    def heartbeat(self, h: Heartbeat):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO machines VALUES(?,?,?)',(h.machine_id,time.time(),json.dumps(h.clients)))

    def summary(self, now=None):
        now = time.time() if now is None else now
        with self.db() as db:
            quotas = {r[0]:json.loads(r[1]) for r in db.execute('SELECT provider,payload FROM quotas')}
            machines = {r[0]:{'id':r[0],'last_seen':r[1],'online':now-r[1]<60,'clients':json.loads(r[2])} for r in db.execute('SELECT * FROM machines')}
            raw = [json.loads(r[0]) for r in db.execute('SELECT payload FROM tasks ORDER BY stamp DESC,seq DESC')]
        tasks, seen, history = [],set(),[]
        for task in raw:
            key = (task['machine_id'],task['tool'],task['session_id'])
            terminal = task['status'] in ('completed','interrupted','failed')
            if key in seen or ((terminal or (task['tool']=='chatgpt' and task['status']=='idle')) and now-task['occurred_at']>86400):
                history.append(task)
                seen.add(key)
                continue
            seen.add(key)
            machine=machines.get(task['machine_id'])
            task['online']=bool(machine and machine['online'])
            display=task['status']
            if not task['online']: display='offline'
            elif machine['clients'].get(task['tool'])=='closed' and not terminal: display='unknown'
            elif task['tool']=='chatgpt' and machine['clients'].get('chatgpt')!='connected': display='unknown'
            task['display_status']=display
            task['status_label']=LABELS[display]
            tasks.append(task)
        tasks.sort(key=lambda t:(PRIORITY.get(t['status'],3),-t['occurred_at']))
        for q in quotas.values(): q['stale']=now-q['fetched_at']>900
        return {'now':now,'quotas':quotas,'machines':list(machines.values()),'tasks':tasks,'history':history[:100]}
