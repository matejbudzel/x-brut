import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "device" / "CIRCUITPY" / "base" / "navigation.py"
spec = importlib.util.spec_from_file_location("navigation_under_test", PATH)
navigation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(navigation)


class NavigationTest(unittest.TestCase):
    def test_push_back_restores_route_and_state(self):
        nav = navigation.Navigation("home")
        nav.push("settings", {"focus": 3})
        nav.push("ap")
        self.assertEqual(nav.back(), {"route": "settings", "state": {"focus": 3}})
        self.assertEqual(nav.back(), {"route": "home", "state": {}})
        self.assertIsNone(nav.back())

    def test_replace_and_home_clear_intermediate_history(self):
        nav = navigation.Navigation("home")
        nav.push("settings")
        nav.replace("ota", {"phase": "ready"})
        self.assertEqual(nav.route, "ota")
        self.assertEqual(nav.home(), {"route": "home", "state": {}})
        self.assertFalse(nav.can_back)
