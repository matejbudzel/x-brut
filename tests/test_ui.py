import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "device" / "CIRCUITPY" / "base"))
from ui import BaseUI


class Platform:
    def __init__(self):
        self.pixels = set()
        self.refreshes = 0

    def clear(self): self.pixels.clear()
    def pixel(self, x, y, on=True):
        if on: self.pixels.add((x, y))
        else: self.pixels.discard((x, y))
    def blit(self, x, y, width, height, packed): pass
    def fill_rect(self, x, y, width, height, on=False):
        for yy in range(y, y + height):
            for xx in range(x, x + width): self.pixel(xx, yy, on)
    def refresh(self): self.refreshes += 1


class DocumentGridTest(unittest.TestCase):
    def setUp(self):
        self.platform = Platform()
        self.ui = BaseUI(self.platform)
        self.documents = [("doc-%03d.xth" % index, "Document %d" % index) for index in range(5)]
        self.ui.document_grid("xViewer", self.documents)

    def test_first_tile_is_initially_focused(self):
        self.assertEqual(self.ui.page, "home")
        self.assertEqual(self.ui.focus, 0)
        self.assertIn((32, 79), self.platform.pixels)
        self.assertEqual(self.ui.actions[0][1], "read:doc-000.xth")
        self.assertEqual(self.ui.button("confirm"), "read:doc-000.xth")

    def test_focus_follows_list_order_wraps_and_scrolls_the_grid(self):
        self.ui.button("down")
        self.assertEqual(self.ui.focus, 1)
        self.assertIn((242, 79), self.platform.pixels)
        for unused in range(3): self.ui.button("down")
        self.assertEqual(self.ui.focus, 4)
        self.assertIn((32, 422), self.platform.pixels)
        self.assertTrue(any(x == 468 for x, y in self.platform.pixels))
        self.ui.button("down")
        self.assertEqual(self.ui.focus, 0)
        self.ui.button("up")
        self.assertEqual(self.ui.focus, 4)

    def test_thumbnail_entries_keep_their_document_action(self):
        self.ui.document_grid("xViewer", [("doc-000.xth", "Document 0", b"\0" * (25 * 333))])
        self.assertEqual(self.ui.button("confirm"), "read:doc-000.xth")

    def test_viewer_menu_draws_without_base_chrome(self):
        refreshes = self.platform.refreshes
        self.ui.viewer_menu({"title": "Book", "author": "Author"}, [("Chapter", 0)], 0)
        self.assertEqual(self.platform.refreshes, refreshes + 1)


if __name__ == "__main__":
    unittest.main()
