"""Lifecycle actions must settle the panel, release keys, and close Wi-Fi."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'device/CIRCUITPY/base')]
from native.micropython.base.xbrut_lifecycle import Device
from xbrut.simulator.portrait import PortraitSimulator
from tests.test_micropython import Clock
from tests.test_web_settings import FakeServer


class RecordingDevice:
    def __init__(self, sim): self.sim, self.calls = sim, []
    def flush(self): self.calls.append('flush')
    def sleep(self): self.calls.append('sleep'); self.sim.powered = False
    def soft_reload(self): self.calls.append('soft_reload')
    def hard_reload(self): self.calls.append('hard_reload')
    def wake(self): self.calls.append('wake'); self.sim.powered = True


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.sim = PortraitSimulator(root=self.temp.name, clock=self.clock)
        self.runtime = self.sim.runtime
        self.life = self.runtime.lifecycle
        self.device = RecordingDevice(self.sim)
        self.life.device = self.device
        self.released = True
        self.life.released = lambda: self.released

    def finish_screen(self):
        self.clock.advance(250); self.runtime.step([])
        self.clock.advance(250); self.runtime.step([])

    def finish_release(self):
        self.clock.advance(50); self.runtime.step([])

    def select(self, action):
        self.runtime.step(['left'])
        index = next(i for i, item in enumerate(self.sim.ui.actions) if item[1] == action)
        while self.sim.ui.focus != index:
            self.runtime.step(['down'])
        self.runtime.step(['confirm'])

    def test_sleep_waits_for_screen_and_stable_release_and_can_wake_in_preview(self):
        self.released = False
        self.runtime.step(['power'])
        self.assertEqual(self.sim.ui.page, 'splash')
        self.assertEqual(self.device.calls, [])
        self.finish_screen()
        self.assertEqual(self.device.calls, [])
        self.released = True
        self.clock.advance(1); self.runtime.step([])
        self.clock.advance(49); self.runtime.step([])
        self.assertEqual(self.device.calls, [])
        self.clock.advance(1); self.runtime.step([])
        self.assertEqual(self.device.calls, ['flush', 'sleep'])
        self.assertTrue(self.life.sleeping)
        self.assertFalse(self.sim.powered)
        self.runtime.step(['down'])
        self.assertEqual(self.sim.ui.page, 'splash')
        self.runtime.step(['power'])
        self.assertTrue(self.sim.powered)
        self.assertFalse(self.life.sleeping)
        self.assertEqual(self.sim.ui.page, 'home')

    def test_soft_and_hard_reload_call_distinct_operations_after_frame(self):
        for action in ('soft_reload', 'hard_reload'):
            with self.subTest(action=action):
                self.device.calls.clear()
                self.select(action)
                self.assertEqual(self.sim.ui.page, 'restarting')
                self.assertEqual(self.device.calls, [])
                self.finish_screen(); self.finish_release()
                self.assertEqual(self.device.calls, ['flush', action])
                self.assertEqual(self.sim.ui.page, 'home')

    def test_pending_transition_ignores_further_navigation(self):
        self.runtime.step(['power', 'left', 'down', 'confirm'])
        self.assertEqual(self.life.pending, 'sleep')
        self.assertEqual(self.sim.ui.page, 'splash')
        self.assertEqual(self.device.calls, [])

    def test_lifecycle_closes_even_a_connection_owned_by_another_feature(self):
        web = self.sim.controller.web
        web.server_factory = FakeServer
        web.radio.connect('external', 'password')
        web.poll()
        server = web.server
        self.runtime.step(['power'])
        self.assertFalse(web.radio.station)
        self.assertTrue(server.closed)
        self.assertIsNone(web.server)

    def test_action_failure_returns_a_usable_error_route(self):
        def fail(): raise OSError('flush failed')
        self.device.flush = fail
        self.select('soft_reload')
        self.finish_screen(); self.finish_release()
        self.assertEqual(self.sim.ui.page, 'lifecycle_error')
        self.assertIsNone(self.runtime.display_error)
        self.assertIsNone(self.life.pending)
        self.runtime.step(['left'])
        self.assertEqual(self.sim.ui.page, 'home')

    def test_soft_reset_system_exit_is_not_swallowed(self):
        def soft_reset(): raise SystemExit
        self.device.soft_reload = soft_reset
        self.select('soft_reload')
        self.finish_screen()
        with self.assertRaises(SystemExit): self.finish_release()
        self.assertIsNone(self.runtime.display_error)

    def test_device_uses_actual_micropython_reset_apis(self):
        calls = []
        machine = SimpleNamespace(soft_reset=lambda: calls.append('soft'), reset=lambda: calls.append('hard'))
        device = Device(SimpleNamespace(sleep=lambda: calls.append('sleep')))
        with patch.dict(sys.modules, {'machine': machine}):
            device.soft_reload(); device.hard_reload(); device.sleep()
        self.assertEqual(calls, ['soft', 'hard', 'sleep'])


if __name__ == '__main__': unittest.main()
