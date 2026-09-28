import importlib.util
from pathlib import Path
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import json
import pytest

spec = importlib.util.spec_from_file_location('frame_relay', Path(__file__).parents[2]/'relay/frame_relay.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)

@pytest.fixture
def service():
    server = relay.Relay(('127.0.0.1', 0), {'read_token': 'reader', 'write_token': 'writer'})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, 'http://127.0.0.1:' + str(server.server_port)
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)

def request(service, path, token='', data=None, headers=None):
    _, url = service
    request = Request(url+path, data=data, headers=dict(headers or {}, Authorization='Bearer '+token))
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers

def upload(service, token='writer', frame=None):
    return request(service, '/upload', token, frame if frame is not None else bytes(15000),
        {'X-RLCD-Layout':'monitor-v1','X-RLCD-Usb-Sleep-Enabled':'0','X-RLCD-Usb-Sleep-Seconds':'300'})

def test_auth_roles_and_only_frame_routes(service):
    assert request(service, '/frame.bin')[0] == 401
    assert request(service, '/frame.bin', 'writer')[0] == 401
    assert upload(service, 'reader')[0] == 401
    assert request(service, '/api/settings', 'reader')[0] == 404
    assert request(service, '/frame.bin', 'reader')[0] == 503

def test_size_headers_and_stale_frames(service):
    assert upload(service, frame=b'bad')[0] == 400
    assert upload(service)[0] == 200
    status, body, headers = request(service, '/frame.bin', 'reader')
    assert status == 200 and len(body) == 15000
    assert headers['X-RLCD-Layout'] == 'monitor-v1'
    assert headers['X-RLCD-Sound-Cue'] == 'none'
    service[0].received = time.monotonic()-31
    assert request(service, '/frame.bin', 'reader')[0] == 503

def test_telemetry_roundtrip_and_expiry(service):
    request(service, '/frame.bin?temp=24.5&humidity=60&battery=88&usb=0&power_version=1&secret=bad', 'reader')
    assert json.loads(upload(service)[1])['telemetry'] == {'temp':24.5,'humidity':60,'battery':88,'usb':0,'power_version':1}
    service[0].sensor_seen = time.monotonic()-31
    assert json.loads(upload(service)[1])['telemetry'] == {}
    assert relay.telemetry({'temp':['nan'],'humidity':[101],'usb':[0.5]}) == {}
