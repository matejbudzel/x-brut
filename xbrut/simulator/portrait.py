"""Desktop preview of the migrated controller and cooperative portrait loop."""
import os
import time
import uuid
import tempfile
from collections import deque
from native.micropython.base.xbrut_boot import BootController
from native.micropython.base.xbrut_runtime import Runtime
from native.micropython.base.xbrut_library import Library
from native.micropython.base import sd_manager
from native.micropython.base.xbrut_web import WebSettings
from native.micropython.base.xbrut_http import Server
from native.micropython.base.xbrut_lifecycle import Lifecycle
from xbrut.simulator import server


class Clock:
    @staticmethod
    def ticks_ms(): return int(time.monotonic() * 1000)
    @staticmethod
    def ticks_diff(now, then): return now - then


class BusyPlatform(server.Platform):
    def __init__(self, clock, busy_ms=250):
        super().__init__()
        self.clock, self.busy_ms, self.until = clock, busy_ms, 0

    def ready(self): return self.clock.ticks_ms() >= self.until

    def refresh(self):
        if not self.ready(): raise RuntimeError("drawing while display busy")
        super().refresh()
        self.until = self.clock.ticks_ms() + self.busy_ms


class PreviewRadio:
    """Simulated radio; HTTP itself runs on the host's real socket stack."""
    def __init__(self): self.ap, self.station = False, False
    def start_ap(self, ssid, password): self.ap = True
    def connect(self, ssid, password): self.station = True
    def ap_address(self): return "127.0.0.1" if self.ap else None
    def station_address(self): return "127.0.0.1" if self.station else None
    def station_error(self): return None
    def stop_ap(self): self.ap = False
    def stop_station(self): self.station = False


class PreviewDevice:
    def __init__(self, sim): self.sim = sim
    def flush(self): pass
    def sleep(self): self.sim.powered = False
    def soft_reload(self): self.sim.powered = True
    def hard_reload(self): self.sim.powered = True
    def wake(self): self.sim.powered = True


class PortraitSimulator:
    buttons_only = True

    def __init__(self, root=None, clock=None, ap_host="0.0.0.0", ap_port=8001):
        self.root = root or server.SIMULATOR_DATA
        self.clock = clock or Clock()
        self.platform = BusyPlatform(self.clock)
        self.ui = server.BaseUI(self.platform, deferred=True)
        self.project = Library(os.path.join(self.root, "xviewer-docs"))
        self.powered, self.sd_present, self.sd_reload_required = True, True, False
        self.revision = uuid.uuid4().hex
        self.events = deque()
        self.assets = tempfile.TemporaryDirectory(prefix="xbrut-settings-")
        page_path = os.path.join(self.assets.name, "settings.html")
        with open(page_path, "wb") as page:
            page.write(server.AP_HTML)
        web = WebSettings(self, radio=PreviewRadio(), clock=self.clock,
                          server_factory=lambda handler: Server(handler, host=ap_host, port=ap_port, clock=self.clock), page_path=page_path)
        self.controller = BootController(self.ui, lambda: self.project, storage=self, sd_root=self.root, sd_manager_api=sd_manager, web=web)
        lifecycle = Lifecycle(self.controller, PreviewDevice(self), clock=self.clock)
        self.runtime = Runtime(self.controller, self.platform, clock=self.clock, on_action=self.action, lifecycle=lifecycle)
        self.controller.start()
        self.tick()

    def close(self):
        self.controller.stop_web(force=True)
        self.assets.cleanup()

    def read_json(self, path, default=None):
        return server.read_project_data(self.root + path[3:], default)

    def write_json(self, path, value):
        if not self.sd_present:
            raise RuntimeError("SD card unavailable")
        if path not in ("/sd/base-conf.json", "/sd/project-conf.json"):
            raise ValueError("unsupported simulator settings path")
        server.write_project_data(self.root + path[3:], value)

    def sd_available(self): return self.sd_present
    def sd_card_status(self): return "simulated" if self.sd_present else "none"

    def action(self, name):
        self.controller.unavailable(name)

    def button(self, name): self.events.append(name)

    def tick(self):
        events = []
        while self.events: events.append(self.events.popleft())
        self.runtime.step(events)

    def show_home(self): self.controller._home()

    def toggle_sd(self):
        self.sd_present = not self.sd_present
        self.ui.read_only = not self.sd_present
        self.show_home()
