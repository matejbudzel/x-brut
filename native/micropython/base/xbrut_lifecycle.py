"""Queue sleep/reload until the screen is settled and buttons are released."""
import os
import time
from xbrut_log import info, error

ACTIONS = ('sleep', 'soft_reload', 'hard_reload')
RELEASE_MS = 50


class Device:
    def __init__(self, platform):
        self.platform = platform

    def flush(self):
        os.sync()

    def sleep(self):
        self.platform.sleep()

    def soft_reload(self):
        import machine
        machine.soft_reset()

    def hard_reload(self):
        import machine
        machine.reset()

    def wake(self):
        # Real deep sleep wakes through a fresh boot. Used by the simulator.
        pass


class Lifecycle:
    def __init__(self, controller, device, released=None, clock=None):
        self.controller, self.device = controller, device
        self.clock = clock or time
        self.released = released or (lambda: True)
        self.pending, self.release_since = None, None
        self.sleeping = False

    def request(self, action):
        if action not in ACTIONS or self.pending is not None or self.sleeping:
            return False
        self.controller.stop_web(force=True)
        self.pending, self.release_since = action, None
        if action == 'sleep':
            self.controller.ui.splash(getattr(self.controller.project, 'PROJECT_NAME', ''))
        else:
            self.controller.ui.show('restarting', 'RESTARTING', bottom_labels=('', '', '', ''), side_labels=('', ''))
        return True

    def poll(self):
        """Runtime calls only after the last queued screen has settled."""
        if self.pending is None:
            return
        if not self.released():
            self.release_since = None
            return
        now = self.clock.ticks_ms()
        if self.release_since is None:
            self.release_since = now
            return
        if self.clock.ticks_diff(now, self.release_since) < RELEASE_MS:
            return
        action, self.pending = self.pending, None
        info('power', 'executing ' + action)
        try:
            self.device.flush()
            if action == 'sleep':
                self.device.sleep()
                # A real deep sleep does not return. This state lets the
                # desktop preview show sleep until another power press.
                self.sleeping = True
            else:
                getattr(self.device, action)()
                # Desktop reset backends return instead of restarting Python.
                self.controller._home()
        except Exception as problem:
            error('power', '%s failed: %r' % (action, problem))
            self.controller._home()
            self.controller.navigation.push('lifecycle_error')
            self.controller.ui.show('lifecycle_error', 'DEVICE ACTION FAILED',
                                    ['PRESS BACK TO RETURN'], bottom_labels=('Back', '', '', ''), side_labels=('', ''))

    def wake(self):
        if self.sleeping:
            self.sleeping = False
            self.device.wake()
            self.controller._home()
