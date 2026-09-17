import builtins
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.hardware_fakes import HardwareEnvironment, InputManager


ROOT = Path(__file__).resolve().parents[1]
HARDWARE_PATH = ROOT / "device" / "CIRCUITPY" / "base" / "hardware.py"


class X4PlatformTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.frame_path = Path(self.temporary.name) / "frame.bmp"
        self.environment = HardwareEnvironment()
        self.modules = patch.dict("sys.modules", self.environment.modules)
        self.modules.start()

        spec = importlib.util.spec_from_file_location("hardware_under_test", HARDWARE_PATH)
        if spec is None or spec.loader is None:
            raise AssertionError("could not load hardware.py")
        self.hardware = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hardware)

        real_open = builtins.open
        frame_path = self.frame_path

        def redirected_open(path, *args, **kwargs):
            if path == "/sd/.xbrut-frame.bmp":
                path = frame_path
            return real_open(path, *args, **kwargs)

        self.hardware.open = redirected_open
        self.platform = self.hardware.X4Platform()

    def tearDown(self):
        self.platform._frame.close()
        self.modules.stop()
        self.temporary.cleanup()

    def frame_bytes(self):
        self.platform._frame.flush()
        return self.frame_path.read_bytes()

    def test_initializes_real_bmp_and_display_tree(self):
        data = self.frame_bytes()
        self.assertEqual(len(data), 48062)
        self.assertEqual(data[:2], b"BM")
        self.assertEqual(int.from_bytes(data[2:6], "little"), 48062)
        self.assertEqual(int.from_bytes(data[10:14], "little"), 62)
        self.assertEqual(int.from_bytes(data[18:22], "little"), 480)
        self.assertEqual(int.from_bytes(data[22:26], "little"), 800)
        self.assertEqual(int.from_bytes(data[28:30], "little"), 1)
        self.assertEqual(data[62:], b"\0" * 48000)
        self.assertEqual(self.environment.display.rotation, 270)
        # The firmware owns and initializes the X4 display. The adapter must
        # retain that object rather than rebuilding a competing display bus.
        self.assertIs(self.platform.display, self.environment.display)
        group = self.environment.display.root_group
        self.assertEqual(len(group.layers), 1)
        self.assertIs(group.layers[0].bitmap, self.platform._bitmap)

    def test_row_offsets_pixel_and_clear(self):
        self.assertEqual(self.platform._row_offset(0), 48002)
        self.assertEqual(self.platform._row_offset(799), 62)
        self.platform.pixel(9, 0)
        self.assertEqual(self.frame_bytes()[48003], 0x40)
        self.platform.pixel(9, 0, False)
        self.assertEqual(self.frame_bytes()[48003], 0)
        self.platform.pixel(0, 799)
        self.platform.clear()
        self.assertEqual(self.frame_bytes()[62:], b"\0" * 48000)

    def test_present_writes_portrait_rows_and_refreshes(self):
        packed = b"\x11" * 60 + b"\0" * (798 * 60) + b"\xee" * 60
        self.platform.present(packed)
        data = self.frame_bytes()
        self.assertEqual(data[self.platform._row_offset(0):][:60], b"\x11" * 60)
        self.assertEqual(data[self.platform._row_offset(799):][:60], b"\xee" * 60)
        self.assertEqual(self.environment.display.refresh_count, 1)

    def test_present_file_validates_rows_and_refreshes(self):
        packed = bytes(index % 251 for index in range(48000))
        source = Path(self.temporary.name) / "source.bin"
        source.write_bytes(packed)
        self.platform.present_file(str(source))
        data = self.frame_bytes()
        self.assertEqual(data[self.platform._row_offset(0):][:60], packed[:60])
        self.assertEqual(data[self.platform._row_offset(799):][:60], packed[-60:])
        self.assertEqual(self.environment.display.refresh_count, 1)

        source.write_bytes(b"short")
        with self.assertRaisesRegex(ValueError, "invalid framebuffer size"):
            self.platform.present_file(str(source))

    def test_refresh_flushes_before_display_refresh(self):
        self.platform.pixel(0, 0)
        self.platform.refresh()
        self.assertEqual(self.environment.display.refresh_count, 1)
        self.assertEqual(self.frame_path.read_bytes()[self.platform._row_offset(0)], 0x80)

    def test_button_names_are_translated_to_application_controls(self):
        expected = (None, "confirm", "left", "button_4", "up", "down", "power")
        for index, name in enumerate(expected):
            with self.subTest(index=index):
                self.platform.buttons.pressed_index = index
                self.assertEqual(self.platform.button(), name)
                self.platform.buttons.pressed_index = None
                self.platform.button()
        self.platform.buttons.pressed_index = None
        self.assertIsNone(self.platform.button())

    def test_back_short_press_is_emitted_only_on_release(self):
        self.platform.buttons.pressed_index = InputManager.BTN_BACK
        self.assertIsNone(self.platform.button())
        self.platform.buttons.pressed_index = None
        self.assertEqual(self.platform.button(), "left")

    def test_back_long_press_is_emitted_once_and_suppresses_short_press(self):
        self.platform.buttons.pressed_index = InputManager.BTN_BACK
        self.assertIsNone(self.platform.button())
        self.platform.buttons.held_seconds = 0.8
        self.assertEqual(self.platform.button(), "left_long")
        self.assertIsNone(self.platform.button())
        self.platform.buttons.pressed_index = None
        self.assertIsNone(self.platform.button())

    def test_sleep_releases_input_and_builds_level_wake_alarm(self):
        original_buttons = self.platform.buttons
        self.platform.sleep()
        self.assertTrue(original_buttons.deinitialized)
        self.assertEqual(len(self.environment.sleep_alarms), 1)
        wake = self.environment.sleep_alarms[0][0]
        self.assertIs(wake.pin, self.environment.button_pin)
        self.assertIs(wake.value, False)
        self.assertIs(wake.edge, False)
        self.assertIs(wake.pull, True)
        self.assertIsNot(self.platform.buttons, original_buttons)
        self.assertEqual(len(InputManager.instances), 2)
        messages = [message for _, component, message in self.environment.logs if component == "hardware"]
        self.assertIn("entering light_sleep_until_alarms", messages)
        self.assertTrue(any(message.startswith("light sleep returned wake=") for message in messages))
        self.assertIn("InputManager reinitialized", messages)

    def test_wifi_ap_pool_address_and_disconnect(self):
        self.platform.connect("network", "password")
        self.assertEqual(self.environment.radio.connect_calls, [("network", "password")])

        conf = {"ap_ssid": "reader", "ap_password": "long-enough"}
        self.platform.start_ap(conf)
        self.assertEqual(
            self.environment.radio.start_ap_calls,
            [("reader", "long-enough", 1, (), 4)],
        )
        pool = self.platform.socket_pool()
        self.assertIs(pool.radio, self.environment.radio)
        self.assertEqual(self.platform.ap_address(), "192.168.4.1")
        self.platform.disconnect()
        self.assertEqual(self.environment.radio.stop_station_count, 1)
        self.assertEqual(self.environment.radio.stop_ap_count, 1)

    def test_ap_generates_and_persists_missing_password(self):
        conf = {}
        self.platform.start_ap(conf)
        self.assertEqual(conf["ap_ssid"] if "ap_ssid" in conf else "x-brut", "x-brut")
        self.assertEqual(len(conf["ap_password"]), 12)
        self.assertTrue(set(conf["ap_password"]) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"))
        self.assertEqual(self.environment.storage_writes, [("/sd/base-conf.json", conf)])
        self.assertEqual(self.environment.radio.start_ap_calls[0][:2], ("x-brut", conf["ap_password"]))

    def test_bytes_streams_reports_progress_and_closes(self):
        response = self.environment.queue_response([b"abc", b"de"], content_length=5)
        progress = []
        self.assertEqual(self.platform.bytes("https://example.test/data", progress.append), b"abcde")
        self.assertEqual(progress, [60, 100, 100])
        self.assertTrue(response.closed)
        self.assertEqual(response.iter_calls, [(1024, False)])
        self.assertEqual(len(self.environment.sessions), 1)
        self.assertIs(self.environment.sessions[0].socket_pool.radio, self.environment.radio)

    def test_bytes_closes_response_after_stream_error(self):
        response = self.environment.queue_response([b"abc"], error=OSError("network lost"))
        with self.assertRaisesRegex(OSError, "network lost"):
            self.platform.bytes("https://example.test/data")
        self.assertTrue(response.closed)

    def test_json_decodes_utf8_response(self):
        payload = json.dumps({"version": 3}).encode("utf-8")
        response = self.environment.queue_response([payload], content_length=len(payload))
        self.assertEqual(self.platform.json("https://example.test/manifest"), {"version": 3})
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
