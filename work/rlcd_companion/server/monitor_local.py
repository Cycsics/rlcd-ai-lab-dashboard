"""Local task collection follows the dashboard lifecycle; remote reporting is optional."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import threading
from monitor_store import TaskEvent, Heartbeat, SessionLink

class LocalMonitor:
    def __init__(self, monitor):
        self.monitor=monitor
        self.thread=None
        self.error=''

    def start(self):
        if self.thread and self.thread.is_alive(): return
        try:
            root=self.monitor.directory/'local-agent'
            root.mkdir(parents=True,exist_ok=True)
            target=root/'agent.py'
            shutil.copy2(Path(__file__).resolve().parents[1]/'agent/agent.py',target)
            config={'server_url':'http://127.0.0.1:8787','machine_id':'local-pc','token':self.monitor.token,'accounts':{}}
            (root/'config.json').write_text(json.dumps(config),encoding='utf-8')
            spec=importlib.util.spec_from_file_location('rlcd_local_agent',target)
            agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
            # In-process reports do not depend on the HTTP listener being ready.
            def report(path,payload):
                if path=='task': return {'accepted':self.monitor.store.event(TaskEvent(**payload))}
                if path=='heartbeat': self.monitor.store.heartbeat(Heartbeat(**payload));return {'ok':True}
                if path=='session': self.monitor.store.session_link(SessionLink(**payload));return {'ok':True}
                raise ValueError('Unsupported local report')
            agent.send=report
            hooks=[(Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'hooks.json','codex'),(Path.home()/'.qoder/settings.json','qoder')]
            for path,tool in hooks:
                try:
                    content=path.read_text(encoding='utf-8-sig') if path.exists() else ''
                    # Avoid rewriting trusted hook files or making backups on every startup.
                    if str(target).replace('\\','\\\\') not in content:
                        agent.merge_hooks(path,tool)
                except Exception:
                    self.error='本机 Hooks 配置失败，请检查客户端配置文件；已有配置未主动清除'
            self.thread=threading.Thread(target=agent.run,args=(self.monitor.stop,),daemon=True)
            self.thread.start()
        except Exception:
            self.error='本机任务采集启动失败，请运行诊断工具'

    def shutdown(self):
        if self.thread: self.thread.join(timeout=3)
