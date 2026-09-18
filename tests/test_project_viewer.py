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
    values = {}
    storage.read_json = lambda path, default=None: values.get(path, default)
    storage.write_json = lambda path, value: values.__setitem__(path, value)
    paths.DATA_ROOT, paths.DOCUMENTS_PATH, paths.PROJECT_CONFIG_PATH, paths.BOOKMARKS_PATH, paths.THUMBNAILS_PATH = "/sd", "/sd/xviewer-docs", "/sd/project-conf.json", "/sd/xviewer-bookmarks.json", "/sd/xviewer-thumbnails"
    spec = importlib.util.spec_from_file_location("project_viewer_under_test", PROJECT_PATH)
    project = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"xbrut_storage": storage, "xbrut_paths": paths}): spec.loader.exec_module(project)
    return project, values


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
    def setUp(self):
        self.project, self.values = load_project()
        self.temp = tempfile.TemporaryDirectory()
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

    def test_bookmarks_are_per_document_and_can_be_cleared(self):
        self.project.save_bookmark("doc-000.xth", 3)
        self.project.save_bookmark("doc-001.xth", 1)
        self.assertEqual(self.project.bookmark("doc-000.xth"), 3)
        self.project.clear_bookmark("doc-000.xth")
        self.assertEqual(self.project.bookmark("doc-000.xth"), 0)
        self.assertEqual(self.project.bookmark("doc-001.xth"), 1)

    def test_successful_redownload_clears_its_bookmark(self):
        self.project.set_root(self.temp.name)
        self.values[self.temp.name + "/project-conf.json"] = {"document_urls": ["https://example.test/book.xth"]}
        self.project.save_bookmark("doc-000.xth", 4)
        platform = ModuleType("platform")
        platform.bytes = lambda url, progress=None: frame(b"XTG\0")
        self.project.download(platform, 0)
        self.assertEqual(self.project.bookmark("doc-000.xth"), 0)
        self.assertEqual(len(self.project.thumbnail("doc-000.xth")), 25 * 333)

    def test_active_home_backfills_only_one_missing_thumbnail(self):
        self.project.set_root(self.temp.name)
        documents = Path(self.temp.name) / "xviewer-docs"
        documents.mkdir()
        (documents / "doc-000.xth").write_bytes(frame(b"XTG\0"))
        (documents / "doc-001.xth").write_bytes(frame(b"XTG\0"))

        class UI:
            def document_grid(self, title, entries, focus): self.entries = entries

        ui = UI()
        self.project.home(ui)
        self.assertIsNotNone(self.project.thumbnail("doc-000.xth"))
        self.assertIsNone(self.project.thumbnail("doc-001.xth"))
        self.assertIsNotNone(ui.entries[0][2])
        self.assertIsNone(ui.entries[1][2])

    def test_reads_toc_and_focuses_the_current_chapter(self):
        path = Path(self.temp.name) / "toc.xtc"
        data = bytearray(56 + 256 + 96)
        data[:4], data[11], data[16:24], data[24:32], data[48:56] = b"XTC\0", 1, (56).to_bytes(8, "little"), (408).to_bytes(8, "little"), (312).to_bytes(8, "little")
        data[56 + 246:56 + 248] = (1).to_bytes(2, "little")
        data[312:319], data[392:394] = b"Chapter", (7).to_bytes(2, "little")
        path.write_bytes(data)
        chapters = self.project.toc(str(path))
        self.assertEqual(chapters, [("Chapter", 6)])
        self.assertEqual(self.project.toc_focus(chapters, 9), 0)

    def test_extracts_only_xtc_opds_acquisitions_and_preserves_query(self):
        self.values["/sd/project-conf.json"] = {"document_manifests": [{"name": "Current", "url": "https://example.test/opds?key=abc"}]}
        xml = b'''<feed><entry><title>Daily Digest</title><link type="application/x-xteink-xtc" href="https://docs.test/daily.xtc?key=abc&amp;v=1"/></entry><entry><title>EPUB only</title><link href="https://docs.test/book.epub" type="application/epub+zip"/></entry></feed>'''
        platform = ModuleType("platform")
        platform.bytes = lambda url: xml
        self.assertEqual(self.project.remote_documents(platform, 0), [("Daily Digest", "https://docs.test/daily.xtc?key=abc&v=1")])

    def test_adding_a_remote_url_keeps_existing_documents(self):
        self.values["/sd/project-conf.json"] = {"document_urls": ["https://docs.test/one.xtc"]}
        self.project.add_url("https://docs.test/two.xtc")
        self.project.add_url("https://docs.test/two.xtc")
        self.assertEqual(self.project.config()["document_urls"], ["https://docs.test/one.xtc", "https://docs.test/two.xtc"])

    def test_opds_url_order_does_not_create_a_duplicate_document(self):
        self.values["/sd/project-conf.json"] = {"document_urls": ["https://docs.test/book.xtc?release=current&key=abc"]}
        self.project.add_url("https://docs.test/book.xtc?key=abc&release=current")
        self.assertEqual(len(self.project.config()["document_urls"]), 1)

    def test_removing_a_remote_url_keeps_other_document_slots_stable(self):
        self.values["/sd/project-conf.json"] = {"document_urls": ["https://docs.test/one.xtc", "https://docs.test/two.xtc"]}
        self.assertTrue(self.project.remove_url("https://docs.test/one.xtc"))
        self.assertEqual(self.project.config()["document_urls"], [None, "https://docs.test/two.xtc"])
        self.assertEqual(self.project.document_index("doc-001.xth"), 1)


if __name__ == "__main__": unittest.main()
