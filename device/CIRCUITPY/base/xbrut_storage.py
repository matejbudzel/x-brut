"""Tiny filesystem helpers shared by device and simulator adapters."""
import json, os
from xbrut_log import configure, debug, error, info
from xbrut_paths import BASE_CONFIG_PATH, DATA_ROOT

_spi = None
_sd = None
_vfs = None


def _join(root, name):
    return root.rstrip("/") + "/" + name if root.rstrip("/") else "/" + name


def _exists(path):
    try: os.stat(path); return True
    except OSError: return False


def _copy_file(source, target):
    temporary = target + ".migrate"
    with open(source, "rb") as reader, open(temporary, "wb") as writer:
        while True:
            chunk = reader.read(4096)
            if not chunk: break
            writer.write(chunk)
    os.rename(temporary, target)


def _migrate_file(source, target):
    if not _exists(source): return False
    if not _exists(target): _copy_file(source, target)
    os.remove(source)
    return True


def _migrate_legacy_data(legacy_root="/", data_root=DATA_ROOT):
    """Move pre-SD mutable files after successful copies; safe to repeat."""
    migrated = 0
    for name in (
        "base-conf.json", "base-conf.json.new", "project-conf.json",
        "project-conf.json.new", "base.log", "base.log.1", "splash.bin",
        "splash.bin.bak", "splash.bin.new",
    ):
        if _migrate_file(_join(legacy_root, name), _join(data_root, name)):
            migrated += 1
    source_docs = _join(legacy_root, "xviewer-docs")
    target_docs = _join(data_root, "xviewer-docs")
    if _exists(source_docs):
        try: os.mkdir(target_docs)
        except OSError: pass
        for name in os.listdir(source_docs):
            if _migrate_file(source_docs + "/" + name, target_docs + "/" + name):
                migrated += 1
        try: os.rmdir(source_docs)
        except OSError: pass
    # This file is only a disposable display buffer, so do not copy it.
    try: os.remove(_join(legacy_root, ".xbrut-frame.bmp")); migrated += 1
    except OSError: pass
    return migrated


def mount_sd():
    """Mount the X4 microSD on the SPI bus shared with the board display."""
    global _spi, _sd, _vfs
    if _spi is not None: return
    import board, sdcardio, storage
    try: os.mkdir(DATA_ROOT)
    except OSError: pass
    # Fresh CircuitPython images place this stock file in the otherwise empty
    # mountpoint. FAT mounting rejects a non-empty mountpoint with EINVAL.
    try: os.remove(DATA_ROOT + "/placeholder.txt")
    except OSError: pass
    try:
        _spi = board.SPI()
        _sd = sdcardio.SDCard(_spi, board.SD_CS)
        _vfs = storage.VfsFat(_sd)
        storage.mount(_vfs, DATA_ROOT)
    except Exception:
        _spi = _sd = _vfs = None
        print("X Brut: microSD mount failed")
        raise
    migrated = _migrate_legacy_data()
    try:
        with open(BASE_CONFIG_PATH, "r") as handle: configure(json.load(handle))
    except (OSError, ValueError):
        configure({})
    info("storage", "microSD mounted at %s; migrated=%d" % (DATA_ROOT, migrated))


def shared_spi():
    """Return the SPI bus initialized by mount_sd for the shared display."""
    if _spi is None: raise RuntimeError("microSD is not mounted")
    return _spi


def read_json(path, default=None):
    debug("storage", "read_json %s" % path)
    try:
        with open(path, "r") as handle:
            value = json.load(handle)
        debug("storage", "read_json ok %s" % path)
        return value
    except (OSError, ValueError) as problem:
        debug("storage", "read_json default %s: %r" % (path, problem))
        return default


def write_json(path, value):
    debug("storage", "write_json begin %s" % path)
    temporary = path + ".new"
    try:
        with open(temporary, "w") as handle:
            json.dump(value, handle)
        try:
            import os
            os.rename(temporary, path)
        except OSError:
            # FAT does not always permit replacing an existing name.
            import os
            os.remove(path)
            os.rename(temporary, path)
    except Exception as problem:
        error("storage", "write_json failed %s: %r" % (path, problem))
        raise
    debug("storage", "write_json complete %s" % path)


def append_log(message):
    """Compatibility wrapper for project code using the old logging helper."""
    error("base", message)
