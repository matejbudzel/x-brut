"""Standard-library simulator for the exact base framebuffer protocol."""
import argparse, json, os, random, socket, sys, threading, uuid
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "device", "CIRCUITPY", "base"))
from ui import BaseUI
from ap import HTML as AP_HTML
from ota import OTA

SIMULATOR_DATA = os.path.join(ROOT, ".simulator")
CONFIG_PATH = os.path.join(SIMULATOR_DATA, "base-conf.json")
LOG_PATH = os.path.join(SIMULATOR_DATA, "base.log")
CONFIG_KEYS = ("wifi_ssid", "wifi_password", "manifest_url", "splash_url", "ap_ssid", "ap_password")


def read_config():
    try:
        with open(CONFIG_PATH, "r") as handle: return json.load(handle)
    except (OSError, ValueError): return {}


def write_config(value):
    os.makedirs(SIMULATOR_DATA, exist_ok=True)
    temporary = CONFIG_PATH + ".new"
    with open(temporary, "w") as handle: json.dump(value, handle)
    os.replace(temporary, CONFIG_PATH)


def log(message):
    os.makedirs(SIMULATOR_DATA, exist_ok=True)
    with open(LOG_PATH, "a") as handle: handle.write(message + "\n")


def ensure_ap_config():
    config = read_config()
    changed = False
    if not config.get("ap_ssid"): config["ap_ssid"] = "x-brut"; changed = True
    if not config.get("ap_password"):
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        config["ap_password"] = "".join(random.choice(alphabet) for _ in range(12)); changed = True
    if changed: write_config(config)
    return config


def ap_handler():
    class APHandler(BaseHTTPRequestHandler):
        def reply(self, status, content_type, body):
            self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def json(self, status, value): self.reply(status, "application/json", json.dumps(value).encode())
        def do_GET(self):
            if self.path == "/": return self.reply(200, "text/html; charset=utf-8", AP_HTML)
            if self.path == "/api/settings": return self.json(200, read_config())
            self.send_error(404)
        def do_POST(self):
            if self.path != "/api/settings": self.send_error(404); return
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                incoming = json.loads(raw.decode("utf-8"))
                config = read_config()
                config.pop("ap_base_ip", None)  # migrate old simulator data on save
                for key in CONFIG_KEYS:
                    if key in incoming: config[key] = incoming[key]
                write_config(config); self.json(200, {"ok": True})
            except Exception as error:
                log("settings save failed: %r" % error); self.json(400, {"ok": False, "error": str(error)})
        def log_message(self, format_string, *args): log("ap: " + format_string % args)
    return APHandler


class Bitmap:
    """Small displayio.Bitmap-compatible 1-bit surface for the simulator."""
    def __init__(self): self.data = bytearray(48000)
    def fill(self, value): self.data[:] = b"\xff" * 48000 if value else b"\0" * 48000
    def __setitem__(self, point, value):
        x, y = point
        offset, mask = y * 60 + x // 8, 128 >> (x & 7)
        if value: self.data[offset] |= mask
        else: self.data[offset] &= ~mask


class Platform:
    def __init__(self): self.bitmap = Bitmap(); self.frame = bytes(48000); self.wifi = False
    def present(self, frame):
        self.frame = bytes(frame)
        self.bitmap.data[:] = self.frame
    def refresh(self): self.frame = bytes(self.bitmap.data)
    def sleep(self): pass
    def connect(self, ssid, password):
        if password == "bad": raise RuntimeError("bad password")
        self.wifi = True
    def json(self, url): return json.loads(self.bytes(url).decode("utf-8"))
    def bytes(self, url):
        with urlopen(url, timeout=20) as response: return response.read()
    def start_ap(self, conf):
        if not conf.get("ap_password"):
            conf["ap_password"] = "SIMULATOR123"; conf["ap_ssid"] = conf.get("ap_ssid", "x-brut")


class Simulator:
    def __init__(self, ap_host, ap_port):
        self.platform = Platform(); self.ui = BaseUI(self.platform); self.powered = True; self.project_name = ""; self.revision = uuid.uuid4().hex
        self.ap_host, self.ap_port, self.ap_server, self.ap_thread = ap_host, ap_port, None, None
        self.ap_advertised_host = socket.gethostname()
        self.ui.home()

    def start_ap(self):
        config = ensure_ap_config()
        self.ap_server = ThreadingHTTPServer((self.ap_host, self.ap_port), ap_handler())
        self.ap_thread = threading.Thread(target=self.ap_server.serve_forever, daemon=True)
        self.ap_thread.start()
        return config

    def stop_ap(self):
        if self.ap_server:
            self.ap_server.shutdown(); self.ap_server.server_close(); self.ap_server = None; self.ap_thread = None
    def button(self, button):
        if button == "power":
            self.powered = not self.powered
            if self.powered: self.ui.home()
            elif os.path.exists(os.path.join(SIMULATOR_DATA, "splash.bin")):
                with open(os.path.join(SIMULATOR_DATA, "splash.bin"), "rb") as handle: self.platform.present(handle.read())
                self.ui.page = "splash"
            else: self.ui.splash(self.project_name)
            return
        if not self.powered: return
        if button == "left" and self.ui.page == "home": self.ui.settings(None); return
        result = self.ui.button(button)
        if result == "back":
            if self.ui.page == "ota": self.ui.settings(None)
            elif self.ui.page == "ap": self.stop_ap(); self.ui.settings(None, focus=2)
            elif self.ui.page == "splash_update": self.ui.settings(None, focus=1)
            else: self.ui.home()
            return
        if result == "ota":
            if read_config().get("manifest_url"):
                self.ui.show("ota", "OTA", ["UPDATE AVAILABLE"], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))
            else:
                self.ui.show("ota", "OTA", ["NO SOURCE URL PROVIDED.", "CONFIGURE ONE VIA AP MODE."], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
        elif result == "splash":
            if read_config().get("splash_url"):
                self.ui.show("splash_update", "SPLASH SCREEN", ["SPLASH AVAILABLE"], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))
            else:
                self.ui.show("splash_update", "SPLASH SCREEN", ["NO SOURCE URL PROVIDED.", "CONFIGURE ONE VIA AP MODE."], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
        elif result == "ap":
            try:
                config = self.start_ap()
                self.ui.show("ap", "AP MODE", [("SSID: ", config["ap_ssid"]), ("PWD: ", config["ap_password"]), "VISIT HTTP://%s:%d" % (self.ap_advertised_host, self.ap_port)], bottom_labels=("Exit", "", "", ""), side_labels=("", ""))
            except OSError as error:
                log("ap start failed: %r" % error)
                self.ui.show("ap", "AP MODE", ["- AP START FAILED -"], bottom_labels=("Exit", "", "", ""), side_labels=("", ""))
        elif result == "download":
            config = read_config()
            try:
                if self.ui.page == "splash_update":
                    OTA(self.platform, SIMULATOR_DATA).download_splash(config["splash_url"])
                    self.ui.show("splash_update", "SPLASH SCREEN", ["SPLASH SCREEN REPLACED"], bottom_labels=("Back", "Preview", "", "Revert"), side_labels=("", ""))
                else:
                    OTA(self.platform, SIMULATOR_DATA).install(self.platform.json(config["manifest_url"]), lambda line: None)
                    self.ui.show("ota", "OTA", ["DONE"], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
            except ValueError as error:
                message = "UNSUPPORTED FORMAT" if str(error) == "UNSUPPORTED_FORMAT" else "- FETCH FAILED -"
                self.ui.show(self.ui.page, self.ui.title, [message], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))
            except Exception as error:
                log("download failed: %r" % error)
                self.ui.show(self.ui.page, self.ui.title, ["- FETCH FAILED -"], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))


def handler(sim):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs): super().__init__(*args, directory=os.path.join(ROOT, "web"), **kwargs)
        def send_json(self, value):
            data = json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path == "/api/screen":
                self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(len(sim.platform.frame))); self.end_headers(); self.wfile.write(sim.platform.frame); return
            if self.path == "/api/reload": return self.send_json({"revision": sim.revision})
            if self.path == "/api/status": return self.send_json({"page": sim.ui.page, "focus": sim.ui.focus, "powered": sim.powered})
            return super().do_GET()
        def do_POST(self):
            if self.path != "/api/button": self.send_error(404); return
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            sim.button(data.get("button", "")); self.send_json({"ok": True})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="X Brut browser simulator")
    parser.add_argument("--host", default="0.0.0.0", help="bind address (default: all interfaces)"); parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true", help="disable source watching")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ap-host", default="0.0.0.0", help="simulated AP bind address")
    parser.add_argument("--ap-port", type=int, default=8001, help="simulated AP port")
    args = parser.parse_args()
    if not args.worker and not args.no_reload:
        from xbrut.simulator import reloader
        return reloader.run(args, (os.path.join(ROOT, "xbrut"), os.path.join(ROOT, "device"), os.path.join(ROOT, "web")))
    server = ThreadingHTTPServer((args.host, args.port), handler(Simulator(args.ap_host, args.ap_port)))
    print("X Brut simulator: http://%s:%d" % (args.host, args.port)); server.serve_forever()

if __name__ == "__main__": main()
