"""Cooperative application loop shared by device and desktop preview."""
import gc
import time
from xbrut_log import debug, error


class Runtime:
    def __init__(self, controller, platform, controls=None, clock=None, on_action=None, timeout_ms=30000):
        self.controller, self.ui = controller, controller.ui
        if not self.ui.deferred:
            raise ValueError("runtime requires deferred UI")
        self.platform, self.controls = platform, controls
        self.clock = clock or time
        self.on_action = on_action
        self.timeout_ms = timeout_ms
        self.wait_since = None
        self.display_error = None

    def step(self, events=None):
        # Dispatch before checking BUSY: a refresh must never swallow input.
        if events is None:
            events = self.controls.poll() if self.controls else ()
        actions = []
        for event in events:
            debug("input", "dispatch %s at %d" % (event, self.clock.ticks_ms()))
            action = self.controller.handle(event)
            if action and action != "render":
                actions.append(action)
                if self.on_action:
                    # Handoffs must schedule work, not run blocking network or
                    # lifecycle operations inside this input-dispatch pass.
                    self.on_action(action)
        if self.display_error is not None:
            return actions
        now = self.clock.ticks_ms()
        try:
            ready = self.platform.ready()
            if not ready:
                if self.wait_since is None: self.wait_since = now
                if self.clock.ticks_diff(now, self.wait_since) >= self.timeout_ms:
                    raise OSError("display BUSY timeout")
                return actions
            if self.wait_since is not None:
                debug("display", "ready after %d ms" % self.clock.ticks_diff(now, self.wait_since))
                self.wait_since = None
                if not self.ui.pending:
                    self.controller.display_ready()
            if self.ui.pending:
                gc.collect()
                heap = gc.mem_free() if hasattr(gc, "mem_free") else -1
                debug("display", "render begin at %d heap=%d" % (now, heap))
                self.ui.render_pending()
                self.wait_since = self.clock.ticks_ms()
                debug("display", "presented render_ms=%d" % self.clock.ticks_diff(self.wait_since, now))
        except Exception as problem:
            # Latch the fault; keep processing controls/model updates, but do
            # not reuse a buffer whose previous-frame synchronization failed.
            self.display_error = problem
            error("display", "presentation stopped: %r" % problem)
        return actions
