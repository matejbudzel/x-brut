import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import ModuleType
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "device" / "CIRCUITPY" / "base"


def load_logger():
    spec = importlib.util.spec_from_file_location("xbrut_log_under_test", BASE / "xbrut_log.py")
    if spec is None or spec.loader is None:
        raise AssertionError("could not load xbrut_log.py")
    module = importlib.util.module_from_spec(spec)
    paths = ModuleType("xbrut_paths")
    paths.BASE_CONFIG_PATH = "/sd/base-conf.json"
    paths.LOG_PATH = "/sd/base.log"
    with patch.dict("sys.modules", {"xbrut_paths": paths}):
        spec.loader.exec_module(module)
    return module


class LoggingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temporary.name) / "base.log"
        self.logger = load_logger()
        self.logger.set_path(str(self.log_path))
        self.logger.configure({})

    def tearDown(self):
        self.temporary.cleanup()

    def lines(self):
        return self.log_path.read_text().splitlines() if self.log_path.exists() else []

    def test_debug_is_default_and_levels_filter(self):
        self.logger.debug("test", "default debug")
        self.logger.info("test", "default info")
        self.assertTrue(any("DEBUG test" in line and line.endswith("default debug") for line in self.lines()))

        self.logger.configure({"log_level": "error"})
        self.assertEqual(self.logger.level(), "error")
        self.logger.debug("test", "hidden debug")
        self.logger.info("test", "hidden info")
        self.logger.error("test", "visible error")
        text = "\n".join(self.lines())
        self.assertNotIn("hidden debug", text)
        self.assertNotIn("hidden info", text)
        self.assertIn("visible error", text)

        self.logger.configure({"log_level": "off"})
        before = self.log_path.read_bytes()
        self.logger.error("test", "hidden error")
        self.assertEqual(self.log_path.read_bytes(), before)

    def test_invalid_or_missing_level_defaults_to_debug(self):
        self.logger.configure({})
        self.assertEqual(self.logger.level(), "debug")

    def test_safe_url_removes_secrets(self):
        sanitized = self.logger.safe_url("https://user:password@example.com/file?token=secret")
        self.assertEqual(sanitized, "https://***@example.com/file")

    def test_exception_includes_traceback(self):
        try:
            raise RuntimeError("diagnostic failure")
        except RuntimeError as problem:
            self.logger.exception("test", "operation failed", problem)
        text = self.log_path.read_text()
        self.assertIn("ERROR test", text)
        self.assertIn("operation failed", text)
        self.assertIn("Traceback", text)
        self.assertIn("RuntimeError: diagnostic failure", text)
        self.logger.configure({"log_level": "nonsense"})
        self.assertEqual(self.logger.level(), "debug")

    def test_log_rotates_to_single_backup(self):
        self.logger._max_bytes = 120
        for index in range(8):
            self.logger.info("rotate", "line-%d-xxxxxxxxxxxxxxxxxxxx" % index)
        self.assertTrue(self.log_path.exists())
        self.assertTrue(Path(str(self.log_path) + ".1").exists())
        self.assertIn("line-7", self.log_path.read_text())

    def test_ap_page_exposes_all_log_levels(self):
        namespace = {}
        exec((BASE / "ap_page.py").read_text(), namespace)
        html = namespace["HTML"]
        self.assertIn(b'name="log_level"', html)
        for level in (b"debug", b"info", b"error", b"off"):
            self.assertIn(b'value="' + level + b'"', html)

    def test_ota_manifest_contains_every_python_base_file(self):
        manifest = json.loads((ROOT / "ota-manifest.json").read_text())
        paths = {item["path"] for item in manifest["files"]}
        expected = {
            "base/" + source.name
            for source in BASE.glob("*.py")
        }
        self.assertTrue(expected <= paths)
        for item in manifest["files"]:
            self.assertTrue((ROOT / item["url"]).exists(), item["url"])


if __name__ == "__main__":
    unittest.main()
