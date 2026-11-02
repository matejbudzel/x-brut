"""Strict API/transport tests for AP and station settings sessions."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'device/CIRCUITPY/base'))
from native.micropython.base.xbrut_web import SettingsStore, WebSettings
from native.micropython.base.xbrut_network import Radio
from native.micropython.base.xbrut_http import Server, CLIENT_TIMEOUT_MS
from tests.test_micropython import Clock


class Storage:
    def __init__(self):
        self.values, self.writes, self.available = {}, [], True
    def read_json(self, path, default=None):
        return json.loads(json.dumps(self.values.get(path, default)))
    def write_json(self, path, value):
        if not self.available: raise RuntimeError('No SD')
        assert path in ('/sd/base-conf.json', '/sd/project-conf.json')
        self.values[path] = json.loads(json.dumps(value))
        self.writes.append(path)
    def sd_available(self): return self.available


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        namespace = {}
        exec((ROOT / 'device/CIRCUITPY/base/ap_page.py').read_text(), namespace)
        self.page = Path(self.temp.name) / 'settings.html'
        self.page.write_bytes(namespace['HTML'])
        self.store = SettingsStore(self.storage, page_path=str(self.page))
    def test_page_and_api_share_existing_schema(self):
        status, kind, page = self.store.route('GET', '/', b'')
        self.assertEqual(status, 200)
        self.assertIn('text/html', kind)
        self.assertIn(b'/api/settings', page.read(10000))
        page.close()
        incoming = {'wifi_ssid':'Home', 'wifi_password':'secret', 'manifest_url':' https://example.test/update ',
                    'ap_ssid':'Reader', 'ap_password':'abcdefgh', 'log_level':'info',
                    'document_urls':[' https://example.test/book '],
                    'document_manifests':[{'name':'Books','url':' https://example.test/opds '}]}
        status, _, response = self.store.route('POST','/api/settings',json.dumps(incoming).encode())
        self.assertEqual((status,json.loads(response)),(200,{'ok':True}))
        status, _, body = self.store.route('GET','/api/settings',b'')
        settings = json.loads(body)
        self.assertTrue(settings['storage_available'])
        self.assertEqual(settings['wifi_password'],'secret')
        self.assertEqual(settings['manifest_url'],'https://example.test/update')
        self.assertEqual(settings['document_manifests'],[{'name':'Books','url':'https://example.test/opds'}])
        self.assertEqual(self.storage.writes,['/sd/base-conf.json','/sd/project-conf.json'])
    def test_page_is_file_backed_and_does_not_import_a_python_literal(self):
        with patch.dict(sys.modules, {'ap_page': None}):
            status, _, body = self.store.route('GET', '/', b'')
        self.assertEqual(status, 200)
        self.assertEqual(body.length, self.page.stat().st_size)
        self.assertEqual(body.read(512), self.page.read_bytes()[:512])
        body.close(); body.close()

    def test_validation_does_not_partially_save(self):
        for incoming in ({'log_level':'verbose'}, {'ap_password':'short'}, {'wifi_ssid':'x'*33},
                         {'wifi_password':True}, {'document_urls':'bad'}, {'document_manifests':[{'url':3}]},
                         {'wifi_ssid':'valid','document_manifests':[None]}, {'path':'/boot.py'}, []):
            with self.subTest(incoming=incoming):
                status, _, body = self.store.route('POST','/api/settings',json.dumps(incoming).encode())
                self.assertEqual(status,400)
                self.assertFalse(json.loads(body)['ok'])
                self.assertEqual(self.storage.writes,[])
    def test_read_only_ap_credentials_are_temporary(self):
        self.storage.available = False
        config = self.store.ap_config()
        self.assertEqual(config['ap_ssid'],'x-brut')
        self.assertEqual(len(config['ap_password']),12)
        self.assertFalse(self.store.get()['storage_available'])
        self.assertEqual(self.storage.writes,[])
        self.assertEqual(self.store.route('POST','/api/settings',b'{"log_level":"info"}')[0],400)
    def test_generated_ap_password_persists_and_other_config_is_preserved(self):
        self.storage.values['/sd/base-conf.json']={'other':42}
        config = self.store.ap_config()
        self.assertEqual(self.store.ap_config()['ap_password'],config['ap_password'])
        self.store.save({'log_level':'error'})
        self.assertEqual(self.storage.values['/sd/base-conf.json']['other'],42)
        self.assertEqual(len(self.storage.writes),2)
    def test_routes_invalid_json_and_unicode(self):
        self.assertEqual(self.store.route('GET','/unknown',b'')[0],404)
        self.assertEqual(self.store.route('OPTIONS','/api/settings',b'')[0],405)
        self.assertEqual(self.store.route('POST','/api/settings',b'broken')[0],400)
        self.assertEqual(self.store.route('POST','/api/settings',b'\xff')[0],400)


class FakeWLAN:
    IF_STA, IF_AP, SEC_WPA2 = 0, 1, 3
    def __init__(self, mode):
        self.mode, self.enabled, self.connected, self.state = mode, False, False, 1
        self.options, self.connections = [], []
    def active(self, enabled=None):
        if enabled is not None: self.enabled=enabled
        return self.enabled
    def config(self, *, ssid=None, key=None, security=None, reconnects=None):
        self.options.append((ssid,key,security,reconnects))
    def connect(self, ssid, password): self.connections.append((ssid,password))
    def disconnect(self): self.connected=False
    def isconnected(self): return self.connected
    def status(self): return self.state
    def ifconfig(self):
        return ('192.168.4.1' if self.mode==1 else '192.168.100.45','255.255.255.0','192.168.4.1','192.168.4.1')


class FakeServer:
    port = 80
    def __init__(self, handler): self.handler,self.started,self.polls,self.closed=handler,False,0,False
    def start(self): self.started=True
    def poll(self): self.polls+=1
    def stop(self): self.closed=True


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.clock,self.storage=Clock(),Storage()
        self.module=SimpleNamespace(WLAN=FakeWLAN,STAT_IDLE=0,STAT_CONNECTING=1,STAT_GOT_IP=3)
        self.radio=Radio(self.module)
        self.web=WebSettings(self.storage,self.radio,self.clock,FakeServer)
    def test_wifi_stays_off_until_selected_and_ap_serves_gateway(self):
        self.web.poll()
        self.assertIsNone(self.radio.ap)
        self.assertIsNone(self.radio.station)
        self.assertIsNone(self.web.server)
        self.web.start('ap')
        self.assertEqual(self.radio.ap.options[-1],('x-brut',self.web.conf['ap_password'],3,None))
        self.assertEqual(self.web.urls,('http://192.168.4.1/',))
        self.assertIn('Password:', '\n'.join(self.web.screen()[1]))
        server=self.web.server
        self.web.stop()
        self.assertFalse(self.radio.ap.active())
        self.assertTrue(server.closed)
    def test_station_connects_asynchronously_and_stops_on_back(self):
        self.storage.values['/sd/base-conf.json']={'wifi_ssid':'Home','wifi_password':'password'}
        self.web.start('station')
        self.assertEqual(self.web.phase,'connecting')
        self.assertEqual(self.radio.station.connections,[('Home','password')])
        self.assertIsNone(self.web.server)
        self.radio.station.connected=True
        self.web.poll()
        self.assertEqual(self.web.urls,('http://192.168.100.45/',))
        self.assertEqual(self.web.phase,'ready')
        self.web.stop()
        self.assertFalse(self.radio.station.active())
        self.assertIsNone(self.web.server)
    def test_server_reuses_external_connection_and_leaves_it_alive(self):
        self.radio.connect('External','password')
        self.radio.station.connected=True
        self.web.poll()
        server=self.web.server
        self.assertTrue(server.started)
        self.web.start('station')
        self.web.stop()
        self.assertTrue(self.radio.station.active())
        self.assertIs(self.web.server,server)
        self.assertFalse(server.closed)
    def test_ap_and_station_use_same_listener(self):
        self.radio.connect('External','password')
        self.radio.station.connected=True
        self.web.poll()
        server=self.web.server
        self.web.start('ap')
        self.assertIs(self.web.server,server)
        self.assertEqual(len(self.web.urls),2)
        self.web.stop()
        self.assertTrue(self.radio.station.active())
        self.assertFalse(self.radio.ap.active())
        self.assertIs(self.web.server,server)
    def test_missing_credentials_failure_and_connection_timeout(self):
        self.web.start('station')
        self.assertIn('NO SAVED WIFI',self.web.failure)
        self.storage.values['/sd/base-conf.json']={'wifi_ssid':'Missing'}
        self.web.start('station')
        self.clock.advance(20000);self.web.poll()
        self.assertIn('TIMED OUT',self.web.failure)
        self.assertFalse(self.radio.station.active())
        self.web.start('station')
        self.radio.station.state=202  # ESP32 positive authentication failure
        self.web.poll()
        self.assertEqual(self.web.phase,'error')
        self.assertFalse(self.radio.station.active())
    def test_long_password_remains_readable_and_server_failure_cleans_up(self):
        self.storage.values['/sd/base-conf.json']={'ap_ssid':'Reader','ap_password':'x'*63}
        self.web.start('ap')
        self.assertTrue(all(len(line)<=46 for line in self.web.screen()[1]))
        def fail(): raise OSError('socket error')
        self.web.server.poll=fail
        self.web.poll()
        self.assertEqual(self.web.phase,'error')
        self.assertFalse(self.radio.ap.active())
        self.assertIsNone(self.web.server)


class Stream:
    next_fd=10
    def __init__(self, data=b'', short_write=73):
        self.fd=Stream.next_fd;Stream.next_fd+=1
        self.input,self.output=bytearray(data),bytearray()
        self.closed,self.blocking,self.short_write=False,None,short_write
    def fileno(self): return self.fd
    def setblocking(self, value): self.blocking=value
    def recv(self, size):
        if not self.input: raise OSError(11)
        data=bytes(self.input[:size]);del self.input[:size];return data
    def send(self, data):
        size=min(len(data),self.short_write);self.output.extend(data[:size]);return size
    def close(self): self.closed=True


class Listener(Stream):
    def __init__(self): super().__init__();self.queue=[]
    def setsockopt(self, level, option, value): pass
    def bind(self, address): self.address=address
    def listen(self, backlog): self.backlog=backlog
    def accept(self):
        if not self.queue: raise OSError(11)
        return self.queue.pop(0),('192.168.4.2',1234)


class Poll:
    def __init__(self, object_events=False): self.items={};self.object_events=object_events
    def register(self, stream, flags): self.items[stream.fileno()]=(stream,flags)
    def modify(self, stream, flags): self.register(stream,flags)
    def unregister(self, stream): del self.items[stream.fileno()]
    def poll(self, timeout):
        assert timeout==0
        ready=[]
        for stream,flags in list(self.items.values()):
            if isinstance(stream,Listener): readable=bool(stream.queue)
            else: readable=bool(stream.input)
            if flags==4 or readable:
                ready.append((stream if self.object_events else stream.fileno(),flags))
        return ready


class HTTPTest(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.listener=Listener();self.selector=SimpleNamespace(POLLIN=1,POLLOUT=4,POLLERR=8,POLLHUP=16,poll=Poll)
        self.sockets=SimpleNamespace(AF_INET=2,SOCK_STREAM=1,SOL_SOCKET=1,SO_REUSEADDR=2,
            socket=lambda family,kind:self.listener,getaddrinfo=lambda *args:[(2,1,0,'',('0.0.0.0',80))])
        self.calls=[]
        def handler(method,path,body): self.calls.append((method,path,body));return 200,'text/plain',b'hello'*200
        self.server=Server(handler,clock=self.clock,sockets=self.sockets,selector=self.selector)
        self.server.start();self.addCleanup(self.server.stop)
    def request(self, raw, stream=None):
        stream=stream or Stream(raw)
        self.listener.queue.append(stream)
        for _ in range(100):
            self.server.poll()
            if stream.closed: break
        return stream
    def test_file_body_streams_in_bounded_chunks_with_short_writes(self):
        class Body:
            def __init__(self):
                self.length, self.position, self.reads, self.closed = 6000, 0, [], False
            def read(self, size):
                self.reads.append(size)
                self.assert_bounded = size <= 512
                if size > 512: raise AssertionError('unbounded file read')
                amount = min(size, self.length - self.position)
                self.position += amount
                return b'x' * amount
            def close(self): self.closed = True
        body = Body()
        self.server.handler = lambda *args: (200, 'text/html', body)
        stream = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(stream.closed)
        header, actual = bytes(stream.output).split(b'\r\n\r\n', 1)
        self.assertIn(b'Content-Length: 6000', header)
        self.assertEqual(actual, b'x' * 6000)
        self.assertTrue(body.closed)
        self.assertGreater(len(body.reads), 1)
        self.assertTrue(all(size <= 512 for size in body.reads))

    def test_open_body_is_closed_on_timeout_and_stop(self):
        from native.micropython.base.xbrut_web import FileBody
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'page.html'; path.write_bytes(b'x' * 6000)
            for stop in (False, True):
                body = FileBody(str(path))
                self.server.handler = lambda *args: (200, 'text/html', body)
                class StalledStream(Stream):
                    def send(self, data): raise OSError(11)
                stream = self.request(b'', StalledStream(b'GET / HTTP/1.1\r\n\r\n'))
                self.assertIsNotNone(body.stream)
                if stop:
                    self.server.stop()
                else:
                    self.clock.advance(CLIENT_TIMEOUT_MS); self.server.poll()
                self.assertTrue(stream.closed)
                self.assertIsNone(body.stream)

    def test_handler_memory_error_is_contained_and_next_request_succeeds(self):
        count = [0]
        def handler(*args):
            count[0] += 1
            if count[0] == 1: raise MemoryError('fragmented heap')
            return 200, 'text/plain', b'recovered'
        self.server.handler = handler
        first = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(bytes(first.output).startswith(b'HTTP/1.1 503'))
        self.assertFalse(self.listener.closed)
        second = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(bytes(second.output).endswith(b'recovered'))
        self.assertTrue(second.closed)
        self.assertFalse(self.server.clients)

    def test_accept_memory_error_closes_client_but_not_listener(self):
        from native.micropython.base import xbrut_http
        def fail(*args): raise MemoryError('no client memory')
        failed = Stream(b'GET / HTTP/1.1\r\n\r\n')
        self.listener.queue.append(failed)
        with patch.object(xbrut_http, 'Client', fail):
            self.server.poll()
        self.assertTrue(failed.closed)
        self.assertFalse(self.listener.closed)
        recovered = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(bytes(recovered.output).startswith(b'HTTP/1.1 200'))

    def test_receive_allocation_failure_does_not_stop_listener(self):
        from native.micropython.base import xbrut_http
        class LimitedBuffer(bytearray):
            def extend(self, data): raise MemoryError('no input memory')
        with patch.object(xbrut_http, 'bytearray', LimitedBuffer, create=True):
            failed = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(bytes(failed.output).startswith(b'HTTP/1.1 503'))
        recovered = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(bytes(recovered.output).startswith(b'HTTP/1.1 200'))

    def test_parser_works_without_bytearray_slice_deletion(self):
        from native.micropython.base import xbrut_http
        class MicroPythonBuffer(bytearray):
            def __delitem__(self, key):
                raise TypeError('bytearray does not support item deletion')
        with patch.object(xbrut_http, 'bytearray', MicroPythonBuffer, create=True):
            stream = self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(stream.closed)
        self.assertTrue(bytes(stream.output).startswith(b'HTTP/1.1 200'))

    def test_would_block_uses_port_error_constants(self):
        from native.micropython.base import xbrut_http
        esp_errno = SimpleNamespace(EAGAIN=11, EWOULDBLOCK=11, EINPROGRESS=119)
        with patch.object(xbrut_http, 'errno', esp_errno):
            self.assertTrue(xbrut_http._would_block(OSError(119)))
            self.assertFalse(xbrut_http._would_block(OSError(5)))

    def test_fragmented_request_short_writes_and_object_poll_events(self):
        self.server.poller.object_events=True
        stream=self.request(b'POST /api/settings HTTP/1.1\r\nContent-Length: 7\r\nContent-Type: application/json\r\n\r\n{"x"')
        self.assertFalse(stream.closed)
        self.assertEqual(self.calls,[])
        stream.input.extend(b':1}')
        for _ in range(100): self.server.poll()
        self.assertEqual(self.calls,[('POST','/api/settings',b'{"x":1}')])
        self.assertIn(b'Content-Length: 1000\r\n',stream.output)
        self.assertTrue(bytes(stream.output).endswith(b'hello'*200))
        self.assertTrue(stream.closed)
        self.assertFalse(stream.blocking)
    def test_bad_lengths_large_headers_chunked_and_non_json_posts(self):
        for header,status in ((b'Content-Length: 9000',413),(b'Content-Length: -1',400),
                              (b'Transfer-Encoding: chunked',400),
                              (b'Content-Length: 2\r\nContent-Length: 2',400),
                              (b'Content-Length: 2\r\nContent-Type: text/plain',415),
                              (b'X-Large: '+b'x'*2100,413)):
            with self.subTest(header=header[:50]):
                stream=self.request(b'POST /api/settings HTTP/1.1\r\n'+header+b'\r\n\r\n{}')
                self.assertTrue(bytes(stream.output).startswith(('HTTP/1.1 %d'%status).encode()))
        self.assertEqual(self.calls,[])
    def test_slow_connection_does_not_block_other_client_or_timeout_cleanup(self):
        slow=self.request(b'GET / HTTP/1.1\r\n')
        quick=self.request(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(quick.closed)
        self.assertFalse(slow.closed)
        self.clock.advance(CLIENT_TIMEOUT_MS);self.server.poll()
        self.assertTrue(slow.closed)
        self.assertFalse(self.server.clients)
    def test_connection_limit_and_stop_release_all_sockets(self):
        first=self.request(b'GET / HTTP/1.1\r\n')
        second=self.request(b'GET / HTTP/1.1\r\n')
        third=self.request(b'GET / HTTP/1.1\r\n')
        self.assertTrue(third.closed)
        self.server.stop()
        self.assertTrue(first.closed and second.closed and self.listener.closed)


if __name__=='__main__': unittest.main()
