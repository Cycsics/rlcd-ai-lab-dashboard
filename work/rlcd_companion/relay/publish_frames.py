"""Publish a local dashboard frame over authenticated, verified HTTPS."""
import argparse
import json
from pathlib import Path
import ssl
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler
from frame_relay import HEADERS, FRAME_BYTES, telemetry

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if urlsplit(config['url']).scheme != 'https':
        raise ValueError('HTTPS required')
    context = ssl.create_default_context(cafile=str(config_path.parent / config['ca']))
    # The local renderer must not travel through an environment-configured proxy.
    local = build_opener(ProxyHandler({}))
    remote = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
    sensor = {}
    sensor_seen = 0
    while True:
        started = time.monotonic()
        try:
            if started - sensor_seen > 30:
                sensor = {}
            with local.open('http://127.0.0.1:8787/frame.bin?' + urlencode(sensor), timeout=6) as response:
                frame = response.read(FRAME_BYTES + 1)
                headers = {key: response.headers.get(key, '') for key in HEADERS}
            if len(frame) != FRAME_BYTES or headers['X-RLCD-Layout'] != 'monitor-v1':
                raise ValueError('Invalid local frame')
            headers['Authorization'] = 'Bearer ' + config['token']
            headers['Content-Type'] = 'application/octet-stream'
            request = Request(config['url'], data=frame, headers=headers, method='POST')
            with remote.open(request, timeout=8) as response:
                result = json.loads(response.read(4096))
            sensor = telemetry({key: [value] for key, value in result.get('telemetry', {}).items()})
            sensor_seen = time.monotonic()
            (config_path.parent / 'publisher-status.json').write_text(json.dumps({'ok': True, 'at': time.time()}))
        except Exception as exc:
            # Avoid recording tokens, frame contents or URLs in logs/status.
            (config_path.parent / 'publisher-status.json').write_text(json.dumps({'ok': False, 'at': time.time(), 'error': type(exc).__name__}))
        time.sleep(max(0.1, 3 - (time.monotonic() - started)))

if __name__ == '__main__':
    main()
