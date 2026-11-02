"""Bounded HTTP/1 settings transport, polled by the application's main loop."""
import socket
import gc
import errno
import select
import time
from xbrut_log import error

HEADER_LIMIT = 2048
BODY_LIMIT = 8192
CLIENT_LIMIT = 2
CLIENT_TIMEOUT_MS = 10000
CHUNK = 512


def _key(stream):
    return stream.fileno() if hasattr(stream, 'fileno') else stream


def _would_block(problem):
    return bool(problem.args) and problem.args[0] in (errno.EAGAIN, getattr(errno, 'EWOULDBLOCK', errno.EAGAIN), errno.EINPROGRESS)


class Client:
    def __init__(self, stream, now):
        self.stream, self.started = stream, now
        self.input = bytearray()
        self.request = None
        self.response = None
        self.part, self.sent, self.chunk = 0, 0, None


class Server:
    def __init__(self, handler, host='0.0.0.0', port=80, clock=None, sockets=None, selector=None):
        self.handler, self.host, self.port = handler, host, port
        self.clock, self.sockets, self.selector = clock or time, sockets or socket, selector or select
        self.listener, self.poller = None, None
        self.clients = {}

    def start(self):
        if self.listener is not None:
            return
        stream = self.sockets.socket(self.sockets.AF_INET, self.sockets.SOCK_STREAM)
        try:
            stream.setsockopt(self.sockets.SOL_SOCKET, self.sockets.SO_REUSEADDR, 1)
            address = self.sockets.getaddrinfo(self.host, self.port, self.sockets.AF_INET, self.sockets.SOCK_STREAM)[0][-1]
            stream.bind(address)
            stream.listen(CLIENT_LIMIT)
            stream.setblocking(False)
            self.poller = self.selector.poll()
            self.poller.register(stream, self.selector.POLLIN)
            self.listener = stream
            # ESP32 MicroPython has no getsockname(); the device uses port 80.
            if self.port == 0:
                self.port = stream.getsockname()[1]
        except Exception:
            stream.close()
            raise

    def _close_body(self, client):
        if client.response is not None and hasattr(client.response[1], 'close'):
            client.response[1].close()
        client.response, client.chunk = None, None

    def _drop(self, key):
        client = self.clients.pop(key)
        client.input, client.request = None, None
        try:
            self._close_body(client)
        finally:
            try:
                self.poller.unregister(client.stream)
            finally:
                client.stream.close()
        # Reclaim parsing/JSON buffers between requests on fragmented heaps.
        gc.collect()

    def stop(self):
        for key in list(self.clients):
            self._drop(key)
        if self.listener is not None:
            self.poller.unregister(self.listener)
            self.listener.close()
        self.listener, self.poller = None, None

    def _reply(self, client, status, content_type, body):
        # Keep the static page separate; never concatenate a second page copy.
        header = ('HTTP/1.1 %d Response\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
                  'Connection: close\r\nCache-Control: no-store\r\n'
                  'X-Content-Type-Options: nosniff\r\n\r\n') % (status, content_type, body.length if hasattr(body, 'read') else len(body))
        client.response = (header.encode(), body)
        client.part, client.sent, client.chunk = 0, 0, None
        client.input = None
        self.poller.modify(client.stream, self.selector.POLLOUT)

    def _bad(self, client, status=400):
        self._reply(client, status, 'application/json', b'{"ok":false,"error":"Invalid HTTP request"}')

    def _request_error(self, client, status, problem):
        # Never log request contents, configuration, or exception arguments.
        error('web', 'request failed type=%s status=%d' % (type(problem).__name__, status))
        self._close_body(client)
        client.input = None
        gc.collect()
        body = (b'{"ok":false,"error":"Server busy; retry the request"}' if status == 503
                else b'{"ok":false,"error":"Settings request failed"}')
        self._reply(client, status, 'application/json', body)

    def _receive(self, client):
        data = client.stream.recv(CHUNK)
        if not data:
            return False
        client.input.extend(data)
        if client.request is None:
            boundary = client.input.find(b'\r\n\r\n')
            if boundary < 0:
                if len(client.input) > HEADER_LIMIT:
                    self._bad(client, 413)
                return True
            if boundary + 4 > HEADER_LIMIT:
                self._bad(client, 413)
                return True
            try:
                lines = bytes(client.input[:boundary]).decode('ascii').split('\r\n')
                method, target, version = lines[0].split(' ')
                if version not in ('HTTP/1.0', 'HTTP/1.1') or not target.startswith('/'):
                    raise ValueError('request line')
                headers = {}
                for line in lines[1:]:
                    name, value = line.split(':', 1)
                    name = name.lower().strip()
                    if not name or name in headers:
                        raise ValueError('duplicate header')
                    headers[name] = value.strip()
                if 'transfer-encoding' in headers:
                    raise ValueError('chunked request')
                length_text = headers.get('content-length', '0')
                if not length_text or any(c < '0' or c > '9' for c in length_text):
                    raise ValueError('content length')
                length = int(length_text)
                if length > BODY_LIMIT:
                    self._bad(client, 413)
                    return True
                if method == 'POST':
                    if 'content-length' not in headers:
                        raise ValueError('missing content length')
                    if headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
                        self._bad(client, 415)
                        return True
                client.request = (method, target.split('?', 1)[0], length)
                # MicroPython bytearray does not support slice deletion.
                client.input = client.input[boundary + 4:]
            except (ValueError, UnicodeError):
                self._bad(client)
                return True
        method, target, length = client.request
        if len(client.input) >= length:
            body = None
            try:
                status, content_type, body = self.handler(method, target, bytes(client.input[:length]))
                self._reply(client, status, content_type, body)
            except Exception as problem:
                if body is not None and hasattr(body, 'close'):
                    body.close()
                self._request_error(client, 503 if isinstance(problem, MemoryError) else 500, problem)
        return True

    def _send(self, client):
        part = client.response[client.part]
        if client.part == 1 and hasattr(part, 'read'):
            if client.chunk is None:
                client.chunk = part.read(CHUNK)
                if not client.chunk:
                    return False
            sent = client.stream.send(memoryview(client.chunk)[client.sent:])
            if sent:
                client.sent += sent
            if client.sent == len(client.chunk):
                client.sent, client.chunk = 0, None
            return True
        if client.sent < len(part):
            sent = client.stream.send(memoryview(part)[client.sent:client.sent + CHUNK])
            if sent:
                client.sent += sent
        if client.sent == len(part):
            client.part += 1
            client.sent = 0
        return client.part < 2

    def _accept(self, now):
        stream = None
        registered = False
        try:
            stream, _address = self.listener.accept()
            if len(self.clients) >= CLIENT_LIMIT:
                stream.close()
                return
            stream.setblocking(False)
            client = Client(stream, now)
            self.poller.register(stream, self.selector.POLLIN)
            registered = True
            self.clients[_key(stream)] = client
        except MemoryError:
            if stream is not None:
                if registered:
                    self.poller.unregister(stream)
                stream.close()
            gc.collect()
        except OSError as problem:
            if stream is not None:
                if registered:
                    self.poller.unregister(stream)
                stream.close()
            if not _would_block(problem):
                raise

    def poll(self):
        if self.listener is None:
            return
        now = self.clock.ticks_ms()
        for key in list(self.clients):
            if self.clock.ticks_diff(now, self.clients[key].started) >= CLIENT_TIMEOUT_MS:
                self._drop(key)
        for event in self.poller.poll(0):
            key, flags = _key(event[0]), event[1]
            if key == _key(self.listener):
                self._accept(now)
                continue
            client = self.clients.get(key)
            if client is None:
                continue
            try:
                if flags & (self.selector.POLLERR | self.selector.POLLHUP):
                    alive = False
                elif client.response is None:
                    alive = self._receive(client)
                else:
                    alive = self._send(client)
            except MemoryError as problem:
                # A per-client allocation failure must not shut down Wi-Fi.
                if client.response is None:
                    try:
                        self._request_error(client, 503, problem)
                        alive = True
                    except MemoryError:
                        alive = False
                else:
                    alive = False
            except OSError as problem:
                alive = _would_block(problem)
            if not alive:
                self._drop(key)
