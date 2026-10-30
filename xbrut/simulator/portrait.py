"""Desktop preview of the migrated controller and cooperative portrait loop."""
import os
import time
import uuid
from collections import deque
from native.micropython.base.xbrut_boot import BootController
from native.micropython.base.xbrut_runtime import Runtime
from native.micropython.base.xbrut_library import Library
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


class PortraitSimulator:
    buttons_only = True

    def __init__(self, root=None, clock=None):
        self.root = root or server.SIMULATOR_DATA
        self.clock = clock or Clock()
        self.platform = BusyPlatform(self.clock)
        self.ui = server.BaseUI(self.platform, deferred=True)
        self.project = Library(os.path.join(self.root, "xviewer-docs"))
        self.powered, self.sd_present, self.sd_reload_required = True, True, False
        self.revision = uuid.uuid4().hex
        self.events = deque()
        self.controller = BootController(self.ui, lambda: self.project, storage=self)
        self.runtime = Runtime(self.controller, self.platform, clock=self.clock, on_action=self.action)
        self.controller.start()
        self.tick()

    def read_json(self, _path, default=None): return default
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
