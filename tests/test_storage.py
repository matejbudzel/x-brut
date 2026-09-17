import importlib.util
from pathlib import Path
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
STORAGE_PATH = ROOT / "device" / "CIRCUITPY" / "base" / "xbrut_storage.py"
PROJECT_PATH = ROOT / "device" / "CIRCUITPY" / "project.py"


class Pin:
    pass


class SPI:
    pass


class DigitalInOut:
    def __init__(self, pin):
        if not isinstance(pin, Pin):
            raise TypeError("DigitalInOut requires a pin")
        self.pin, self.value, self.deinitialized = pin, None, False

    def switch_to_output(self, *, value=False, drive_mode=None):
        if not isinstance(value, bool):
            raise TypeError("output value must be bool")
        self.value = value

    def deinit(self):
        self.deinitialized = True


class SDCard:
    def __init__(self, bus, cs, baudrate=8000000):
        if not isinstance(bus, SPI) or not isinstance(cs, Pin):
            raise TypeError("invalid SDCard bus or CS")
        if not isinstance(baudrate, int):
            raise TypeError("baudrate must be int")
        self.bus, self.cs, self.baudrate = bus, cs, baudrate


class VfsFat:
    def __init__(self, block_device):
        if not isinstance(block_device, SDCard):
            raise TypeError("VfsFat requires an SDCard")
        self.block_device = block_device


def load_storage(extra_modules=None):
    logger = ModuleType("xbrut_log")
    logger.debug = lambda component, message: None
    logger.error = lambda component, message: None
    logger.info = lambda component, message: None
    logger.configure = lambda conf: None
    paths = ModuleType("xbrut_paths")
    paths.DATA_ROOT = "/sd"
    paths.BASE_CONFIG_PATH = "/sd/base-conf.json"
    modules = {"xbrut_log": logger, "xbrut_paths": paths}
    modules.update(extra_modules or {})
    spec = importlib.util.spec_from_file_location("xbrut_storage_under_test", STORAGE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load xbrut_storage.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", modules):
        spec.loader.exec_module(module)
    return module


class StorageTest(unittest.TestCase):
    def test_project_configuration_defaults_to_sd(self):
        calls = []
        storage = ModuleType("xbrut_storage")

        def read_json(path, default=None):
            calls.append(("read", path))
            return {"document_urls": ["https://example.test/book.xth"]}

        def write_json(path, value):
            calls.append(("write", path, value))

        storage.read_json, storage.write_json = read_json, write_json
        paths = ModuleType("xbrut_paths")
        paths.DATA_ROOT = "/sd"
        paths.PROJECT_CONFIG_PATH = "/sd/project-conf.json"
        paths.DOCUMENTS_PATH = "/sd/xviewer-docs"
        spec = importlib.util.spec_from_file_location("project_under_test", PROJECT_PATH)
        if spec is None or spec.loader is None:
            raise AssertionError("could not load project.py")
        project = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"xbrut_storage": storage, "xbrut_paths": paths}):
            spec.loader.exec_module(project)

        self.assertEqual(project.config()["document_urls"], ["https://example.test/book.xth"])
        project.save_urls(["https://example.test/new.xth"])
        self.assertEqual(calls[0], ("read", "/sd/project-conf.json"))
        self.assertEqual(calls[1], ("read", "/sd/project-conf.json"))
        self.assertEqual(calls[2][0:2], ("write", "/sd/project-conf.json"))

    def test_mount_uses_shared_x4_spi(self):
        spi, sd_cs = SPI(), Pin()
        board = ModuleType("board")
        board.SD_CS = sd_cs
        board.spi_calls = 0

        def board_spi():
            board.spi_calls += 1
            return spi

        board.SPI = board_spi
        sdcardio = ModuleType("sdcardio")
        sdcardio.SDCard = SDCard
        circuit_storage = ModuleType("storage")
        circuit_storage.VfsFat = VfsFat
        circuit_storage.mounts = []

        def mount(filesystem, mount_path, *, readonly=False):
            if not isinstance(filesystem, VfsFat) or not isinstance(mount_path, str):
                raise TypeError("invalid mount")
            circuit_storage.mounts.append((filesystem, mount_path, readonly))

        circuit_storage.mount = mount
        modules = {
            "board": board, "sdcardio": sdcardio, "storage": circuit_storage,
        }
        storage = load_storage(modules)
        storage._migrate_legacy_data = lambda: 0

        with patch.dict("sys.modules", modules):
            storage.mount_sd()

        self.assertEqual(board.spi_calls, 1)
        filesystem, mount_path, readonly = circuit_storage.mounts[0]
        self.assertIs(filesystem.block_device.bus, spi)
        self.assertIs(filesystem.block_device.cs, sd_cs)
        self.assertEqual(mount_path, "/sd")
        self.assertFalse(readonly)
        self.assertIs(storage.shared_spi(), spi)

        with patch.dict("sys.modules", modules):
            storage.mount_sd()
        self.assertEqual(board.spi_calls, 1)

    def test_mount_removes_only_stock_placeholder(self):
        spi, sd_cs = SPI(), Pin()
        board = ModuleType("board")
        board.SD_CS, board.SPI = sd_cs, lambda: spi
        sdcardio = ModuleType("sdcardio")
        sdcardio.SDCard = SDCard
        circuit_storage = ModuleType("storage")
        circuit_storage.VfsFat = VfsFat
        circuit_storage.mount = lambda filesystem, mount_path, readonly=False: None
        storage = load_storage({"board": board, "sdcardio": sdcardio, "storage": circuit_storage})
        storage._migrate_legacy_data = lambda: 0
        removed = []

        def remove(path):
            removed.append(path)
            if path != "/sd/placeholder.txt":
                raise OSError("unexpected deletion")

        with patch.object(storage.os, "mkdir", side_effect=OSError("exists")), patch.object(storage.os, "remove", side_effect=remove), patch.dict("sys.modules", {"board": board, "sdcardio": sdcardio, "storage": circuit_storage}):
            storage.mount_sd()
        self.assertEqual(removed, ["/sd/placeholder.txt"])

    def test_migrates_mutable_files_only_after_copy(self):
        storage = load_storage()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy, data = root / "legacy", root / "sd"
            legacy.mkdir(); data.mkdir()
            (legacy / "base-conf.json").write_text('{"log_level":"info"}')
            (legacy / "project-conf.json").write_text('{"document_urls":[]}')
            (legacy / "base.log").write_text("old diagnostics\n")
            (legacy / "splash.bin").write_bytes(b"splash")
            (legacy / ".xbrut-frame.bmp").write_bytes(b"scratch")
            documents = legacy / "xviewer-docs"
            documents.mkdir()
            (documents / "doc-000.xth").write_bytes(b"document")

            storage._migrate_legacy_data(str(legacy), str(data))

            self.assertEqual((data / "base-conf.json").read_text(), '{"log_level":"info"}')
            self.assertEqual((data / "project-conf.json").read_text(), '{"document_urls":[]}')
            self.assertEqual((data / "base.log").read_text(), "old diagnostics\n")
            self.assertEqual((data / "splash.bin").read_bytes(), b"splash")
            self.assertEqual((data / "xviewer-docs" / "doc-000.xth").read_bytes(), b"document")
            self.assertFalse((legacy / "base-conf.json").exists())
            self.assertFalse((legacy / ".xbrut-frame.bmp").exists())
            self.assertFalse(documents.exists())

    def test_failed_migration_keeps_flash_source(self):
        storage = load_storage()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "base-conf.json", root / "sd" / "base-conf.json"
            source.write_text('{"log_level":"debug"}')
            target.parent.mkdir()
            with patch.object(storage, "_copy_file", side_effect=OSError("card write failed")):
                with self.assertRaisesRegex(OSError, "card write failed"):
                    storage._migrate_file(str(source), str(target))
            self.assertTrue(source.exists())
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
