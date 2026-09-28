"""Restart the dashboard, collector and publisher after an unexpected exit."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    args = parser.parse_args()
    path = Path(args.config).resolve()
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    guard = socket.socket()
    try:
        guard.bind(('127.0.0.1', config.get('guard_port', 18787)))
    except OSError:
        return
    stop = path.parent / 'stop-supervisor'
    processes = {}
    streams = {}
    try:
        while not stop.exists():
            for job in config['jobs']:
                name = job['name']
                if name in processes and processes[name].poll() is None:
                    continue
                if name in streams:
                    streams[name].close()
                logfile = path.parent / (name + '.log')
                if logfile.exists() and logfile.stat().st_size > 2 * 1024 * 1024:
                    logfile.replace(logfile.with_suffix('.previous.log'))
                stream = open(logfile, 'ab', buffering=0)
                streams[name] = stream
                env = dict(os.environ, **job.get('env', {}))
                processes[name] = subprocess.Popen(job['command'], cwd=job['cwd'], env=env,
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            time.sleep(3)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for stream in streams.values():
            stream.close()
        guard.close()

if __name__ == '__main__':
    main()
