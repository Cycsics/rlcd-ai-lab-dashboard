"""Private, memory-only HTTPS frame relay. Compatible with Python 3.6+."""
import argparse
import hmac
import json
import math
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit, parse_qs

FRAME_BYTES = 15000
HEADERS = ('X-RLCD-Layout', 'X-RLCD-Usb-Sleep-Enabled', 'X-RLCD-Usb-Sleep-Seconds')
RANGES = {'battery': (0, 100), 'temp': (-40, 85), 'humidity': (0, 100),
          'usb': (0, 1), 'power_version': (1, 10)}

def telemetry(query):
    result = {}
    for key, limits in RANGES.items():
        try:
            value = float(query[key][-1])
            if math.isfinite(value) and limits[0] <= value <= limits[1]:
                if key in ('battery', 'usb', 'power_version'):
                    if value != int(value):
                        continue
                    value = int(value)
                result[key] = value
        except (KeyError, ValueError, TypeError, IndexError):
            pass
    return result

class Relay(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, config):
        self.config = config
        self.lock = threading.Lock()
        self.frame = None
        self.received = 0
        self.frame_headers = {}
        self.sensor = {}
        self.sensor_seen = 0
        super().__init__(address, Handler)

class Handler(BaseHTTPRequestHandler):
    server_version = 'FrameRelay'

    def setup(self):
        self.request.settimeout(8)
        if getattr(self.server, 'tls', None):
            self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        super().setup()

    def log_message(self, *args):
        pass  # Never log authorization headers, query strings or device metadata.

    def reply(self, status, data=b'', headers=None):
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, role):
        expected = 'Bearer ' + self.server.config[role + '_token']
        return hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected.encode())

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path != '/frame.bin':
            return self.reply(404)
        if not self.authorized('read'):
            return self.reply(401)
        now = time.monotonic()
        with self.server.lock:
            sensor = telemetry(parse_qs(url.query))
            if sensor:
                self.server.sensor, self.server.sensor_seen = sensor, now
            if self.server.frame is None or now - self.server.received > 30:
                return self.reply(503)
            frame, headers = self.server.frame, dict(self.server.frame_headers)
        headers.update({'Content-Type': 'application/octet-stream', 'X-RLCD-Sound-Cue': 'none',
                        'X-RLCD-Alert-Level': 'normal', 'X-RLCD-Alert-Key': 'none'})
        return self.reply(200, frame, headers)

    def do_POST(self):
        if self.path != '/upload':
            return self.reply(404)
        if not self.authorized('write'):
            return self.reply(401)
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Length') != str(FRAME_BYTES):
            return self.reply(400)
        frame = self.rfile.read(FRAME_BYTES)
        if len(frame) != FRAME_BYTES or self.headers.get('X-RLCD-Layout') != 'monitor-v1':
            return self.reply(400)
        headers = {'X-RLCD-Layout': 'monitor-v1'}
        enabled = self.headers.get('X-RLCD-Usb-Sleep-Enabled', '0')
        seconds = self.headers.get('X-RLCD-Usb-Sleep-Seconds', '300')
        if enabled not in ('0', '1') or not seconds.isdigit() or not 0 <= int(seconds) <= 86400:
            return self.reply(400)
        headers.update({'X-RLCD-Usb-Sleep-Enabled': enabled, 'X-RLCD-Usb-Sleep-Seconds': seconds})
        now = time.monotonic()
        with self.server.lock:
            self.server.frame, self.server.frame_headers, self.server.received = frame, headers, now
            sensor = dict(self.server.sensor) if now - self.server.sensor_seen <= 30 else {}
        return self.reply(200, json.dumps({'telemetry': sensor}).encode(), {'Content-Type': 'application/json'})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    args = parser.parse_args()
    with open(args.config) as stream:
        config = json.load(stream)
    if min(len(config['read_token']), len(config['write_token'])) < 32 or config['read_token'] == config['write_token']:
        raise ValueError('Separate strong read/write tokens are required')
    server = Relay((config.get('host', '0.0.0.0'), config.get('port', 443)), config)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
    context.load_cert_chain(config['certificate'], config['key'])
    server.tls = context
    server.serve_forever()

if __name__ == '__main__':
    main()
