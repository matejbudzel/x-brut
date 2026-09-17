import importlib.util
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[1] / "device" / "CIRCUITPY" / "base" / "sd_manager.py"
spec = importlib.util.spec_from_file_location("sd_manager_under_test", PATH)
sd_manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd_manager)


class SDManagerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "simulator"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def touch(self, name, content="x"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_tree_is_sorted_includes_dotfiles_and_marks_directories(self):
        self.touch("z.txt"); self.touch(".settings"); self.touch("Folder/a.txt")
        self.touch("alpha/nested.txt")
        rows = sd_manager.build_tree(str(self.root))
        self.assertEqual([row["text"] for row in rows], ["[D] alpha", "      nested.txt", "[D] Folder", "      a.txt", "    .settings", "    z.txt"])

    def test_depth_and_total_limits_add_informational_rows(self):
        self.touch("a/b/c/d/e.txt")
        rows = sd_manager.build_tree(str(self.root))
        self.assertEqual(rows[-1]["text"], "      ... lower levels trimmed ...")
        for index in range(55): self.touch("many/%02d" % index)
        rows = sd_manager.build_tree(str(self.root))
        self.assertEqual(len([row for row in rows if row.get("focusable")]), 50)
        self.assertEqual(rows[-1]["text"], "... other items not shown ...")

    def test_empty_directories_and_focus_skip_informational_rows(self):
        self.touch("empty/.keep", "")
        manager = sd_manager.SDManager(str(self.root), lambda: True)
        self.assertTrue(manager.selected()["focusable"])
        manager.rows.append({"text": "information", "focusable": False})
        manager.move(1)
        self.assertTrue(manager.selected()["focusable"])
        self.assertNotEqual(manager.rows[manager.focus]["text"], "information")

    def test_modal_cancel_and_recursive_delete_selects_nearest_item(self):
        self.touch("a/child/file"); self.touch("b")
        manager = sd_manager.SDManager(str(self.root), lambda: True)
        self.assertEqual(manager.selected()["path"], str(self.root / "a"))
        manager.button("confirm"); self.assertTrue(manager.modal)
        manager.button("down"); self.assertTrue(manager.modal)
        manager.button("left"); self.assertFalse(manager.modal); self.assertTrue((self.root / "a").exists())
        manager.button("confirm"); manager.button("confirm")
        self.assertFalse((self.root / "a").exists())
        self.assertEqual(manager.selected()["path"], str(self.root / "b"))

    def test_rejects_root_traversal_and_outside_paths(self):
        self.touch("inside")
        with self.assertRaises(ValueError): sd_manager.remove_tree(str(self.root), str(self.root))
        with self.assertRaises(ValueError): sd_manager.remove_tree(str(self.root), str(self.root / ".." / "elsewhere"))
        with self.assertRaises(ValueError): sd_manager.remove_tree(str(self.root), self.temporary.name)
        self.assertTrue((self.root / "inside").exists())

    def test_unavailable_card_fails_without_removing_anything(self):
        target = self.touch("keep")
        manager = sd_manager.SDManager(str(self.root), lambda: True)
        manager.button("confirm")
        manager.available = lambda: False
        with self.assertRaises(sd_manager.SDCardError): manager.button("confirm")
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
