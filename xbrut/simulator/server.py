"""Standard-library simulator for the exact base framebuffer protocol."""
import argparse, json, os, random, socket, sys, threading, uuid
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "device", "CIRCUITPY", "base"))
sys.path.insert(0, os.path.join(ROOT, "device", "CIRCUITPY"))
from ui import BaseUI
from sd_manager import SDCardError, SDManager
from ap import HTML as AP_HTML
from ota import OTA
import xbrut_log
import project

SIMULATOR_DATA = os.path.join(ROOT, ".simulator")
CONFIG_PATH = os.path.join(SIMULATOR_DATA, "base-conf.json")
LOG_PATH = os.path.join(SIMULATOR_DATA, "base.log")
CONFIG_KEYS = ("wifi_ssid", "wifi_password", "manifest_url", "splash_url", "ap_ssid", "ap_password", "log_level")
xbrut_log.set_path(LOG_PATH)


def read_config():
    try:
        with open(CONFIG_PATH, "r") as handle: return json.load(handle)
    except (OSError, ValueError): return {}


def write_config(value):
    os.makedirs(SIMULATOR_DATA, exist_ok=True)
    temporary = CONFIG_PATH + ".new"
    with open(temporary, "w") as handle: json.dump(value, handle)
    os.replace(temporary, CONFIG_PATH)


def read_project_data(path, default=None):
    try:
        with open(path, "r") as handle: return json.load(handle)
    except (OSError, ValueError): return default


def write_project_data(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".new"
    with open(temporary, "w") as handle: json.dump(value, handle)
    os.replace(temporary, path)


def log(message):
    os.makedirs(SIMULATOR_DATA, exist_ok=True)
    xbrut_log.info("simulator", message)


def ensure_ap_config():
    config = read_config()
    changed = False
    if not config.get("ap_ssid"): config["ap_ssid"] = "x-brut"; changed = True
    if not config.get("log_level"): config["log_level"] = "debug"; changed = True
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
            if self.path == "/api/settings":
                value = read_config(); project.set_root(SIMULATOR_DATA)
                value.setdefault("log_level", "debug")
                # The shared AP page disables every field when this is absent
                # or false.  Simulator project data is always backed by its
                # writable .simulator directory, unless SD was toggled out.
                value["storage_available"] = True
                project_conf = project.config()
                value["document_urls"] = project_conf.get("document_urls", [])
                value["document_manifests"] = project_conf.get("document_manifests", [])
                return self.json(200, value)
            self.send_error(404)
        def do_POST(self):
            if self.path != "/api/settings": self.send_error(404); return
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                incoming = json.loads(raw.decode("utf-8"))
                if "log_level" in incoming and incoming["log_level"] not in xbrut_log.LOG_LEVELS:
                    raise ValueError("invalid log level")
                config = read_config()
                config.pop("ap_base_ip", None)  # migrate old simulator data on save
                for key in CONFIG_KEYS:
                    if key in incoming: config[key] = incoming[key]
                write_config(config); xbrut_log.configure(config); self.json(200, {"ok": True})
                if "document_urls" in incoming:
                    project.set_root(SIMULATOR_DATA)
                    project.save_urls(incoming["document_urls"])
                if "document_manifests" in incoming:
                    project.set_root(SIMULATOR_DATA)
                    project.save_manifests(incoming["document_manifests"])
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
    def __init__(self): self.bitmap = Bitmap(); self.frame = bytes(48000); self.wifi = False; self.battery_percent = 100; self.charging = False
    def battery_status(self): return self.battery_percent, self.charging
    def clear(self): self.bitmap.fill(0)
    def pixel(self, x, y, on=True): self.bitmap[x, y] = 1 if on else 0
    def blit(self, x, y, width, height, packed):
        row_bytes = (width + 7) // 8
        for row in range(height):
            for column in range(width):
                if packed[row * row_bytes + column // 8] & (128 >> (column & 7)):
                    self.bitmap[x + column, y + row] = 1
    def fill_rect(self, x, y, width, height, on=False):
        for row in range(y, y + height):
            for column in range(x, x + width): self.bitmap[column, row] = 1 if on else 0
    def present(self, packed):
        self.frame = bytes(packed)
        self.bitmap.data[:] = self.frame
    def refresh(self): self.frame = bytes(self.bitmap.data)
    def sleep(self): pass
    def connect(self, ssid, password):
        if password == "bad": raise RuntimeError("bad password")
        self.wifi = True
    def disconnect(self): self.wifi = False
    def json(self, url): return json.loads(self.bytes(url).decode("utf-8"))
    def bytes(self, url, progress=None):
        with urlopen(url, timeout=20) as response:
            total = int(response.headers.get("Content-Length", "0")); data = bytearray()
            while True:
                chunk = response.read(4096)
                if not chunk: break
                data.extend(chunk)
                if progress and total: progress(len(data) * 100 // total)
            if progress: progress(100)
            return bytes(data)
    def start_ap(self, conf):
        if not conf.get("ap_password"):
            conf["ap_password"] = "SIMULATOR123"; conf["ap_ssid"] = conf.get("ap_ssid", "x-brut")


class Simulator:
    def __init__(self, ap_host, ap_port):
        xbrut_log.configure(read_config())
        xbrut_log.info("simulator", "initializing")
        project.set_root(SIMULATOR_DATA)
        # The device writer requires a mounted physical SD card.  The simulator
        # maps the same project files to its persistent local data directory.
        project.read_json, project.write_json = read_project_data, write_project_data
        self.project = project
        self.platform = Platform(); self.ui = BaseUI(self.platform); self.powered = True; self.project_name = "xViewer"; self.revision = uuid.uuid4().hex
        self.sd_present, self.sd_reload_required = True, False
        self.ap_host, self.ap_port, self.ap_server, self.ap_thread = ap_host, ap_port, None, None
        self.ap_advertised_host = socket.gethostname()
        self.show_home()

    def show_home(self):
        self.ui.read_only = not self.sd_present or self.sd_reload_required
        self.ui.home(self.project)

    def show_settings(self, focus=0):
        status = "simulated" if self.sd_present and not self.sd_reload_required else "none"
        self.ui.read_only = status == "none"
        self.ui.settings(self.project, focus=focus, sd_status=status)

    def show_viewer(self, filename):
        self.viewer_filename = filename
        path = self.project._path(self.project.DOCUMENTS_PATH + "/" + filename)
        self.viewer_pages = self.project.page_count(path)
        self.viewer_page = min(self.project.bookmark(filename), self.viewer_pages - 1)
        self.viewer_chapters = self.project.toc(path)
        self.viewer_update_index = self.project.document_index(filename)
        self.viewer_menu_open = False
        self.ui.page, self.ui.actions, self.ui.lines = "viewer", [], []
        self.project.render_page(self.platform, path, self.viewer_page)

    def show_sd_manager(self, focus=0):
        self.settings_focus = focus
        self.manager = SDManager(SIMULATOR_DATA, lambda: self.sd_present and not self.sd_reload_required)
        self.ui.sd_manager(self.manager)

    def toggle_sd(self):
        self.sd_present = not self.sd_present
        if not self.sd_present:
            self.sd_reload_required = False
        else:
            self.sd_reload_required = True
        self.show_home()

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
            if self.powered: self.show_home()
            elif os.path.exists(os.path.join(SIMULATOR_DATA, "splash.bin")):
                with open(os.path.join(SIMULATOR_DATA, "splash.bin"), "rb") as handle: self.platform.present(handle.read())
                self.ui.page = "splash"
            else: self.ui.splash(self.project_name)
            return
        if not self.powered: return
        if button == "left_long":
            # Match the device's universal long-Back gesture. The simulator
            # does not retain the device route stack, but Home is its root.
            if self.ui.page == "viewer": self.project.save_bookmark(self.viewer_filename, self.viewer_page)
            self.show_home()
            return
        if self.ui.page == "sd_manager":
            if button == "left" and not self.manager.modal:
                self.show_settings(self.settings_focus); return
            try:
                self.manager.button(button)
                self.ui.sd_manager(self.manager)
            except SDCardError:
                self.show_home()
            return
        remove_index = getattr(self, "remote_remove_index", None)
        if remove_index is not None and self.ui.page == "remote_remove":
            if button in ("left", "left_long"):
                self.remote_remove_index = None; self.show_remote_document_list(); return
            if button in ("up", "side_up", "button_3", "down", "side_down", "button_4"):
                self.remote_remove_focus = 1 - self.remote_remove_focus
                self.ui.remote_remove_modal(self.remote_documents[remove_index][0], self.remote_remove_focus)
            elif button in ("confirm", "button_2"):
                self.project.remove_url(self.remote_documents[remove_index][1], self.remote_remove_focus == 1)
                self.remote_remove_index = None; self.show_remote_document_list()
            return
        if self.ui.page == "viewer":
            if button == "left":
                if self.viewer_menu_open:
                    self.viewer_menu_open = False
                    self.show_viewer_page()
                else:
                    self.project.save_bookmark(self.viewer_filename, self.viewer_page)
                    self.show_home()
            elif self.viewer_menu_open:
                menu_items = len(self.viewer_chapters) + (1 if self.viewer_update_index is not None else 0)
                if button in ("up", "side_up", "button_3") and menu_items:
                    self.viewer_chapter_focus = (self.viewer_chapter_focus - 1) % menu_items
                    self.show_viewer_menu()
                elif button in ("down", "side_down", "button_4") and menu_items:
                    self.viewer_chapter_focus = (self.viewer_chapter_focus + 1) % menu_items
                    self.show_viewer_menu()
                elif button in ("confirm", "button_2") and self.viewer_update_index is not None and self.viewer_chapter_focus == 0:
                    self.start_viewer_update()
                elif button in ("confirm", "button_2") and self.viewer_chapters:
                    chapter = self.viewer_chapter_focus - 1 if self.viewer_update_index is not None else self.viewer_chapter_focus
                    self.viewer_page = min(self.viewer_chapters[chapter][1], self.viewer_pages - 1)
                    self.viewer_menu_open = False
                    self.show_viewer_page()
            elif button in ("confirm", "button_2"):
                self.viewer_menu_open = True
                self.viewer_chapter_focus = self.project.toc_focus(self.viewer_chapters, self.viewer_page) + (1 if self.viewer_update_index is not None else 0)
                self.show_viewer_menu()
            elif button in ("up", "side_up", "button_3") and self.viewer_page > 0:
                self.viewer_page -= 1
                self.show_viewer_page()
            elif button in ("down", "side_down", "button_4") and self.viewer_page + 1 < self.viewer_pages:
                self.viewer_page += 1
                self.show_viewer_page()
            return
        if button == "left" and self.ui.page == "home": self.show_settings(); return
        if getattr(self, "viewer_update_pending", False) and self.ui.page == "document":
            if button in ("left", "confirm", "button_2"):
                self.viewer_update_pending = False
                self.show_viewer(self.viewer_filename)
            return
        result = self.ui.button(button)
        if result == "back":
            if self.ui.page == "ota": self.show_settings()
            elif self.ui.page == "ap": self.stop_ap(); self.show_settings(2)
            elif self.ui.page == "splash_update": self.show_settings(1)
            elif self.ui.page in ("remote_docs", "download_all"): self.show_settings(self.settings_focus)
            else: self.show_home()
            return
        if result in ("soft_reload", "hard_reload"):
            self.sd_reload_required = False
            self.show_home()
            return
        if result == "sleep":
            self.powered = False
            self.ui.splash(self.project_name)
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
        elif result and result.startswith("remote_docs:"):
            self.settings_focus = self.ui.focus
            self.show_remote_docs(int(result.split(":", 1)[1]))
        elif result == "download_all":
            self.settings_focus = self.ui.focus
            self.download_all()
        elif result == "fetch":
            self.fetch_remote_docs()
        elif result and result.startswith("add:"):
            self.project.add_url(self.remote_documents[int(result.split(":", 1)[1])][1])
            self.show_remote_document_list()
        elif result and result.startswith("remove:"):
            self.remote_remove_index = int(result.split(":", 1)[1])
            name = self.remote_documents[self.remote_remove_index][0]
            url = self.remote_documents[self.remote_remove_index][1]
            if self.project.has_download(url):
                self.remote_remove_focus = 0; self.ui.remote_remove_modal(name, self.remote_remove_focus)
            else:
                self.project.remove_url(url); self.remote_remove_index = None; self.show_remote_document_list()
        elif getattr(self, "remote_documents", None) and self.ui.page == "remote_docs":
            self.show_remote_document_list()
        elif result == "read_downloaded":
            self.show_viewer(self.project.document_name(self.current_document_index))
        elif result and result.startswith("read:"):
            self.show_viewer(result[5:])
        elif result and result.startswith("document:"):
            index = int(result.split(":", 1)[1]); self.current_document_index = index; url = self.project.config()["document_urls"][index]
            self.ui.show("document", "DOWNLOAD", ["DOWNLOAD", self.project.short_url(url)], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))
        elif result == "ap":
            try:
                config = self.start_ap()
                self.ui.show("ap", "AP MODE", [("SSID: ", config["ap_ssid"]), ("PWD: ", config["ap_password"]), "VISIT HTTP://%s:%d" % (self.ap_advertised_host, self.ap_port)], bottom_labels=("Exit", "", "", ""), side_labels=("", ""))
            except OSError as error:
                log("ap start failed: %r" % error)
                self.ui.show("ap", "AP MODE", ["- AP START FAILED -"], bottom_labels=("Exit", "", "", ""), side_labels=("", ""))
        elif result == "manage_sd":
            try: self.show_sd_manager(self.ui.focus)
            except SDCardError: self.show_home()
        elif result == "download":
            config = read_config()
            try:
                if self.ui.page == "document":
                    url = self.project.config()["document_urls"][self.current_document_index]
                    def progress(percent): self.ui.show("document", "DOWNLOAD", ["DOWNLOADING %d%%" % percent], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
                    info = self.project.download(self.platform, self.current_document_index, progress)
                    self.ui.show("document", "DOWNLOAD", [("Title: ", info.get("title") or "-"), ("Author: ", info.get("author") or "-")], [("READ", "read_downloaded")], ("Back", "Read", "", ""), ("", ""))
                elif self.ui.page == "splash_update":
                    OTA(self.platform, SIMULATOR_DATA).download_splash(config["splash_url"])
                    self.ui.show("splash_update", "SPLASH SCREEN", ["SPLASH SCREEN REPLACED"], bottom_labels=("Back", "Preview", "", "Revert"), side_labels=("", ""))
                else:
                    OTA(self.platform, SIMULATOR_DATA).install(self.platform.json(config["manifest_url"]), lambda line: None)
                    self.ui.show("ota", "OTA", ["DONE"], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
            except ValueError as error:
                message = "UNSUPPORTED FORMAT" if str(error) == "UNSUPPORTED_FORMAT" else "- FETCH FAILED -"
                self.ui.show(self.ui.page, self.ui.title, [message], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))
            except Exception as error:
                url = locals().get("url", "unknown")
                log("download failed for %s: %r" % (url, error))
                self.ui.show(self.ui.page, self.ui.title, ["- FETCH FAILED -"], [("DOWNLOAD", "download")], ("Back", "Start", "", ""), ("", ""))

    def show_viewer_page(self):
        path = self.project._path(self.project.DOCUMENTS_PATH + "/" + self.viewer_filename)
        self.project.render_page(self.platform, path, self.viewer_page)

    def show_viewer_menu(self):
        path = self.project._path(self.project.DOCUMENTS_PATH + "/" + self.viewer_filename)
        self.ui.viewer_menu(self.project.metadata(path), self.viewer_chapters, self.viewer_chapter_focus, self.viewer_update_index is not None)

    def start_viewer_update(self):
        self.viewer_update_pending = True
        self.ui.show("document", "DOWNLOAD", ["DOWNLOADING..."], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
        try:
            info = self.project.download(self.platform, self.viewer_update_index)
            self.ui.show("document", "DOWNLOAD", [("Title: ", info.get("title") or "-"), ("Author: ", info.get("author") or "-")], bottom_labels=("Back", "Read", "", ""), side_labels=("", ""))
        except Exception as error:
            self.viewer_update_pending = False
            log("viewer update failed: %r" % error)
            self.show_viewer_page()

    def show_remote_docs(self, manifest_index):
        self.remote_manifest_index = manifest_index
        if not 0 <= manifest_index < len(self.project.config().get("document_manifests", [])):
            self.ui.show("remote_docs", "REMOTE DOCS", ["- NO MANIFEST URL -"], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
        else:
            name = self.project.config()["document_manifests"][manifest_index]["name"].upper()
            self.ui.show("remote_docs", "REMOTE DOCS", [name, "REMOTE DOCUMENTS"], [("FETCH LIST", "fetch")], ("Back", "Fetch", "", ""), ("", ""))

    def show_remote_document_list(self):
        name = self.project.config()["document_manifests"][self.remote_manifest_index]["name"].upper()
        actions = []
        for index, (title, url) in enumerate(self.remote_documents):
            added = self.project.has_url(url)
            actions.append((("[x] " if added else "[ ] ") + title, ("remove:" if added else "add:") + str(index)))
        focus = min(max(0, self.ui.focus), len(actions) - 1) if actions else 0
        active = actions[focus][1] if actions else ""
        self.ui.show("remote_docs", "REMOTE DOCS", [name, "REMOTE DOCUMENTS"], actions, ("Back", "Remove" if active.startswith("remove:") else "Add", "v", "v"), ("", ""), focus)

    def fetch_remote_docs(self):
        name = self.project.config()["document_manifests"][self.remote_manifest_index]["name"].upper()
        self.ui.show("remote_docs", "REMOTE DOCS", [name, "- FETCHING LIST -"], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
        try:
            self.remote_documents = self.project.remote_documents(self.platform, self.remote_manifest_index)
            if self.remote_documents: self.show_remote_document_list()
            else: self.ui.show("remote_docs", "REMOTE DOCS", [name, "- NO XTC DOCUMENTS -"], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
        except Exception as error:
            log("remote document list failed: %r" % error)
            self.show_remote_docs(self.remote_manifest_index)

    def download_all(self):
        urls, failed = [(index, url) for index, url in enumerate(self.project.config().get("document_urls", [])) if url], 0
        if not urls:
            self.ui.show("download_all", "DOWNLOAD ALL", ["- NO DOCUMENTS -"], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
            return
        for order, (index, url) in enumerate(urls):
            self.ui.show("download_all", "DOWNLOAD ALL", ["DOWNLOADING %d/%d" % (order + 1, len(urls)), self.project.short_url(url)], bottom_labels=("Back", "", "", ""), side_labels=("", ""))
            try: self.project.download(self.platform, index)
            except Exception as error:
                failed += 1; log("download all item %d failed: %r" % (index, error))
        self.ui.show("download_all", "DOWNLOAD ALL", ["DONE" if not failed else "DONE - %d FAILED" % failed], bottom_labels=("Back", "", "", ""), side_labels=("", ""))


def handler(sim):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs): super().__init__(*args, directory=os.path.join(ROOT, "web"), **kwargs)
        def send_json(self, value):
            data = json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path == "/api/screen":
                self.send_response(200); self.send_header("Content-Type", "application/octet-stream"); self.send_header("Content-Length", str(len(sim.platform.frame))); self.end_headers(); self.wfile.write(sim.platform.frame); return
            if self.path == "/api/reload": return self.send_json({"revision": sim.revision})
            if self.path == "/api/status": return self.send_json({"page": sim.ui.page, "focus": sim.ui.focus, "powered": sim.powered, "buttons_only": getattr(sim, "buttons_only", False)})
            return super().do_GET()
        def do_POST(self):
            if self.path == "/api/battery":
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                sim.platform.battery_percent = int(data.get("percent", 100)); sim.platform.charging = bool(data.get("charging", False)); sim.show_home()
                return self.send_json({"ok": True})
            if self.path == "/api/sd":
                sim.toggle_sd(); return self.send_json({"present": sim.sd_present, "reload_required": sim.sd_reload_required})
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
    parser.add_argument("--portrait", action="store_true", help="preview migrated controller with deferred rendering")
    args = parser.parse_args()
    if not args.worker and not args.no_reload:
        from xbrut.simulator import reloader
        return reloader.run(args, (os.path.join(ROOT, "xbrut"), os.path.join(ROOT, "device"), os.path.join(ROOT, "native"), os.path.join(ROOT, "web")))
    if args.portrait:
        from xbrut.simulator.portrait import PortraitSimulator
        sim = PortraitSimulator()
        # HTTP handlers only enqueue button events. One thread owns model and
        # render work, just as the device's cooperative loop does.
        class PortraitHandler(handler(sim)):
            def do_POST(self):
                if self.path != "/api/button":
                    self.send_error(400, "Only button input is supported in portrait preview")
                    return
                super().do_POST()
        server = ThreadingHTTPServer((args.host, args.port), PortraitHandler)
        def tick():
            import time
            while True:
                sim.tick()
                time.sleep(0.01)
        threading.Thread(target=tick, daemon=True).start()
    else:
        server = ThreadingHTTPServer((args.host, args.port), handler(Simulator(args.ap_host, args.ap_port)))
    print("X Brut simulator: http://%s:%d" % (args.host, args.port)); server.serve_forever()

if __name__ == "__main__": main()
