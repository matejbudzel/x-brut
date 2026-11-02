"""One settings API/server for either an AP or a saved Wi-Fi connection."""
import json
import os
import time
from xbrut_paths import BASE_CONFIG_PATH, PROJECT_CONFIG_PATH
from xbrut_log import LOG_LEVELS, configure, info, error

BASE_KEYS = ('wifi_ssid', 'wifi_password', 'manifest_url', 'splash_url', 'ap_ssid', 'ap_password', 'log_level')
PROJECT_KEYS = ('document_urls', 'document_manifests')


class SettingsStore:
    def __init__(self, storage):
        self.storage = storage

    def base(self):
        value = self.storage.read_json(BASE_CONFIG_PATH, {})
        return value if isinstance(value, dict) else {}

    def get(self):
        base = self.base()
        value = {key: base[key] for key in BASE_KEYS if key in base}
        value.setdefault('log_level', 'info')
        value.setdefault('ap_ssid', 'x-brut')
        value['storage_available'] = self.storage.sd_available()
        project = self.storage.read_json(PROJECT_CONFIG_PATH, {}) or {}
        if not isinstance(project, dict):
            project = {}
        value['document_urls'] = project.get('document_urls', [])
        value['document_manifests'] = project.get('document_manifests', [])
        legacy = project.get('document_manifest_url')
        if not value['document_manifests'] and legacy:
            value['document_manifests'] = [{'name': 'REMOTE DOCS', 'url': legacy}]
        return value

    def save(self, incoming):
        if not self.storage.sd_available():
            raise ValueError('NO SD CARD: settings cannot be saved')
        if not isinstance(incoming, dict) or any(key not in BASE_KEYS + PROJECT_KEYS for key in incoming):
            raise ValueError('Invalid settings fields')
        base = self.base()
        project = self.storage.read_json(PROJECT_CONFIG_PATH, {}) or {}
        if not isinstance(project, dict):
            project = {}
        for key in BASE_KEYS:
            if key in incoming:
                if not isinstance(incoming[key], str):
                    raise ValueError('Settings fields must be text')
                base[key] = incoming[key]
        if base.get('log_level', 'info') not in LOG_LEVELS:
            raise ValueError('Invalid log level')
        for key in ('wifi_ssid', 'ap_ssid'):
            if len(base.get(key, '').encode()) > 32:
                raise ValueError('Wi-Fi name exceeds 32 bytes')
        password = base.get('ap_password', '')
        if password and (not 8 <= len(password) <= 63 or any(ord(c) < 32 or ord(c) > 126 for c in password)):
            raise ValueError('AP password must be 8-63 printable ASCII characters')
        for key in ('manifest_url', 'splash_url'):
            if key in base:
                base[key] = base[key].strip()
        if 'document_urls' in incoming:
            urls = incoming['document_urls']
            if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
                raise ValueError('Invalid document URLs')
            project['document_urls'] = [url.strip() for url in urls if url.strip()]
        if 'document_manifests' in incoming:
            manifests = incoming['document_manifests']
            if not isinstance(manifests, list):
                raise ValueError('Invalid OPDS feeds')
            normalized = []
            for item in manifests:
                if not isinstance(item, dict) or not isinstance(item.get('url'), str) or not isinstance(item.get('name', ''), str):
                    raise ValueError('Invalid OPDS feed')
                url = item['url'].strip()
                if url:
                    normalized.append({'name': item.get('name', '').strip() or url, 'url': url})
            project['document_manifests'] = normalized
            project.pop('document_manifest_url', None)
        # Validate everything before writing either configuration file. Keep
        # keys owned by other modules, and retain the /sd-only storage guard.
        if any(key in incoming for key in BASE_KEYS):
            base.pop('ap_base_ip', None)
            self.storage.write_json(BASE_CONFIG_PATH, base)
            configure(base)
        if any(key in incoming for key in PROJECT_KEYS):
            self.storage.write_json(PROJECT_CONFIG_PATH, project)
        info('web', 'settings saved')

    def ap_config(self):
        base = self.base()
        changed = False
        if not base.get('ap_ssid'):
            base['ap_ssid'], changed = 'x-brut', True
        if not base.get('ap_password'):
            alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
            base['ap_password'] = ''.join(alphabet[value % len(alphabet)] for value in os.urandom(12))
            changed = True
        if len(base['ap_ssid'].encode()) > 32 or not 8 <= len(base['ap_password']) <= 63:
            raise ValueError('INVALID AP SETTINGS')
        if changed and self.storage.sd_available():
            self.storage.write_json(BASE_CONFIG_PATH, base)
        return base

    def route(self, method, path, body):
        if method == 'GET' and path == '/':
            from ap_page import HTML
            return 200, 'text/html; charset=utf-8', HTML
        if path != '/api/settings':
            return 404, 'application/json', b'{"ok":false,"error":"Not found"}'
        if method == 'GET':
            return 200, 'application/json', json.dumps(self.get()).encode()
        if method != 'POST':
            return 405, 'application/json', b'{"ok":false,"error":"Method not allowed"}'
        info('web', 'settings POST received')
        try:
            self.save(json.loads(body.decode('utf-8')))
            return 200, 'application/json', b'{"ok":true}'
        except (ValueError, UnicodeError) as problem:
            info('web', 'settings save rejected by validation')
            return 400, 'application/json', json.dumps({'ok': False, 'error': str(problem)}).encode()
        except Exception:
            error('web', 'settings save failed')
            return 503, 'application/json', b'{"ok":false,"error":"Could not save settings to SD"}'


class WebSettings:
    """Own explicit settings sessions; reuse already-connected interfaces."""
    def __init__(self, storage, radio=None, clock=None, server_factory=None):
        self.store = SettingsStore(storage)
        self.radio, self.clock = radio, clock or time
        self.server_factory, self.server = server_factory, None
        self.mode, self.failure = None, None
        self.conf = {}
        self.started = 0
        self.own_ap = self.own_station = False
        self.phase = 'off'
        self.urls = ()

    def _radio(self):
        if self.radio is None:
            from xbrut_network import Radio
            self.radio = Radio()
        return self.radio

    def _make_server(self):
        if self.server_factory:
            return self.server_factory(self.store.route)
        from xbrut_http import Server
        return Server(self.store.route, clock=self.clock)

    def start(self, mode):
        self.stop()
        self.mode, self.failure, self.phase = mode, None, 'connecting'
        self.started = self.clock.ticks_ms()
        try:
            radio = self._radio()
            if mode == 'ap':
                self.conf = self.store.ap_config()
                self.own_ap = not bool(radio.ap_address())
                radio.start_ap(self.conf['ap_ssid'], self.conf['ap_password'])
            elif mode == 'station':
                self.conf = self.store.base()
                if not radio.station_address():
                    ssid = self.conf.get('wifi_ssid')
                    if not isinstance(ssid, str) or not ssid:
                        raise ValueError('NO SAVED WIFI - USE AP MODE')
                    self.own_station = True
                    radio.connect(ssid, self.conf.get('wifi_password', ''))
            else:
                raise ValueError('UNKNOWN NETWORK MODE')
            self.poll()
        except ValueError as problem:
            self._failed(str(problem))
        except Exception:
            self._failed('COULD NOT START WIFI SETTINGS')

    def close(self):
        """Stop every interface/listener before sleep, reset, or REPL exit."""
        if self.radio is not None:
            self.own_ap = self.own_station = True
        self._release()
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.mode, self.failure, self.phase, self.urls = None, None, 'off', ()

    def _release(self):
        if self.radio is not None:
            if self.own_ap:
                try:
                    self.radio.stop_ap()
                except OSError:
                    pass
            if self.own_station:
                try:
                    self.radio.stop_station()
                except OSError:
                    pass
        self.own_ap = self.own_station = False

    def _failed(self, message):
        self.failure, self.phase = message, 'error'
        self._release()
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.urls = ()
        error('web', message)

    def stop(self):
        self._release()
        self.mode, self.failure, self.phase = None, None, 'off'
        # Keep serving an interface owned by another feature, if any.
        self.poll()

    def poll(self):
        if self.radio is None or self.failure is not None:
            return
        try:
            station = self.radio.station_address()
            ap = self.radio.ap_address()
        except OSError:
            self._failed('WIFI STATUS FAILED')
            return
        if self.mode == 'station' and self.failure is None and not station:
            problem = self.radio.station_error()
            if problem or self.clock.ticks_diff(self.clock.ticks_ms(), self.started) >= 20000:
                self._failed(problem or 'WIFI CONNECTION TIMED OUT')
                return
        addresses = tuple(address for address in (ap, station) if address and address != '0.0.0.0')
        try:
            if addresses:
                if self.server is None:
                    self.server = self._make_server()
                    self.server.start()
                port = self.server.port
                suffix = '' if port == 80 else ':' + str(port)
                self.urls = tuple('http://' + address + suffix + '/' for address in addresses)
                if self.failure is None:
                    self.phase = 'ready'
                self.server.poll()
            else:
                self.urls = ()
                if self.server is not None:
                    self.server.stop()
                    self.server = None
                if self.mode and not self.failure:
                    self.phase = 'connecting'
        except Exception as problem:
            error('web', 'server poll failed: %r' % problem)
            self._failed('WEB SERVER FAILED')

    def screen(self):
        title = 'AP MODE' if self.mode == 'ap' else 'WEB SETTINGS'
        if self.failure:
            lines = [self.failure]
        elif self.phase != 'ready':
            lines = ['CONNECTING TO WIFI...', self.conf.get('wifi_ssid', '')]
        else:
            lines = []
            if self.mode == 'ap':
                lines.extend(['SSID: ' + self.conf.get('ap_ssid', ''), 'Password: ' + self.conf.get('ap_password', '')])
            else:
                lines.append('WIFI: ' + self.conf.get('wifi_ssid', ''))
            lines.extend(self.urls)
            lines.append('OPEN THIS URL IN YOUR BROWSER')
        lines.append('BACK CLOSES SETTINGS SESSION')
        wrapped = []
        for line in lines:
            wrapped.extend(line[start:start + 46] for start in range(0, len(line), 46))
        return title, tuple(wrapped)
