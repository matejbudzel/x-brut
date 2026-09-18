import importlib.util
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = ROOT / "device" / "CIRCUITPY" / "project.py"


def load_project():
    storage, paths = ModuleType("xbrut_storage"), ModuleType("xbrut_paths")
    storage.read_json, storage.write_json = lambda path, default=None: default, lambda path, value: None
    paths.DATA_ROOT, paths.DOCUMENTS_PATH, paths.PROJECT_CONFIG_PATH = "/sd", "/sd/xviewer-docs", "/sd/project-conf.json"
    spec = importlib.util.spec_from_file_location("project_viewer_under_test", PROJECT_PATH)
    project = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"xbrut_storage": storage, "xbrut_paths": paths}): spec.loader.exec_module(project)
    return project


def frame(kind, first=255, second=None):
    size = 48000 if kind == b"XTG\0" else 96000
    header = bytearray(22)
    header[:4], header[4:6], header[6:8] = kind, (480).to_bytes(2, "little"), (800).to_bytes(2, "little")
    header[10:14] = size.to_bytes(4, "little")
    data = bytearray([first] * (48000 if kind == b"XTG\0" else 48000))
    if kind == b"XTH\0": data.extend([second if second is not None else first] * 48000)
    return bytes(header + data)


class Platform:
    def __init__(self): self.frames = []
    def present(self, packed): self.frames.append(packed)


class ProjectViewerTest(unittest.TestCase):
    def setUp(self): self.project, self.temp = load_project(), tempfile.TemporaryDirectory()
    def tearDown(self): self.temp.cleanup()

    def test_renders_and_inverts_a_fullscreen_xtg_page(self):
        path = Path(self.temp.name) / "page.xth"
        page = bytearray(frame(b"XTG\0")); page[22] = 127
        path.write_bytes(page)
        platform = Platform()
        self.project.render_page(platform, str(path), 0)
        self.assertEqual(self.project.page_count(str(path)), 1)
        self.assertEqual(len(platform.frames[0]), 48000)
        self.assertEqual(platform.frames[0][0], 128)

    def test_renders_xth_bitplanes_and_reads_xtc_page_index(self):
        path = Path(self.temp.name) / "book.xth"
        xth = bytearray(frame(b"XTH\0", 0, 0))
        # Source columns run right-to-left, so x=0 is column 479.
        xth[22 + 47900] = 128
        xth[22 + 48000 + 47900] = 128
        container = bytearray(56 + 16)
        container[:4], container[6:8], container[24:32] = b"XTC\0", (1).to_bytes(2, "little"), (56).to_bytes(8, "little")
        container[56:64] = (72).to_bytes(8, "little")
        path.write_bytes(container + xth)
        platform = Platform()
        self.project.render_page(platform, str(path), 0)
        self.assertEqual(self.project.page_count(str(path)), 1)
        self.assertEqual(platform.frames[0][0], 128)


if __name__ == "__main__": unittest.main()
