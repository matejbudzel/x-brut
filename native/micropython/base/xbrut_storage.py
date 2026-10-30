"""MicroPython SD mount and atomic JSON helpers for X Brut mutable state."""
import json
import os

import xbrut_x4
from xbrut_log import configure, debug, error, info
from xbrut_paths import BASE_CONFIG_PATH, DATA_ROOT

_sd = None
_vfs = None


class SDCardUnavailable(RuntimeError):
    pass


def mount_sd():
    """Mount the native shared-SPI SD card once at /sd."""
    global _sd, _vfs
    if _vfs is not None:
        return True
    try:
        _sd = xbrut_x4.SDCard()
        _vfs = os.VfsFat(_sd)
        os.mount(_vfs, DATA_ROOT)
    except OSError as problem:
        # A directory named /sd is not evidence of a mounted card. Fail
        # closed so a mount error can never enable internal-flash writes.
        _sd = _vfs = None
        print("X Brut: microSD unavailable: %r" % problem)
        return False
    try:
        with open(BASE_CONFIG_PATH) as handle:
            configure(json.load(handle))
    except (OSError, ValueError):
        configure({})
    info("storage", "microSD mounted at " + DATA_ROOT)
    return True


def sd_available():
    return _vfs is not None


def sd_card_status():
    if not sd_available():
        return "none"
    try:
        values = os.statvfs(DATA_ROOT)
        total = values[0] * values[2]
        used = total - values[0] * values[3]
        gigabyte = 1024 * 1024 * 1024
        return "%.1f/%.1f GB" % (used / gigabyte, total / gigabyte)
    except OSError:
        return "mounted"


def read_json(path, default=None):
    debug("storage", "read_json " + path)
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError) as problem:
        debug("storage", "read_json default %s: %r" % (path, problem))
        return default


def _sd_path(path):
    if not path.startswith(DATA_ROOT + "/") or any(part in ("", ".", "..") for part in path[len(DATA_ROOT) + 1:].split("/")):
        raise ValueError("mutable X Brut state must be under /sd")


def write_json(path, value):
    _sd_path(path)
    if not sd_available():
        raise SDCardUnavailable("SD card is required to save settings")
    temporary = path + ".new"
    try:
        with open(temporary, "w") as handle:
            json.dump(value, handle)
        try:
            os.rename(temporary, path)
        except OSError:
            try: os.remove(path)
            except OSError: pass
            os.rename(temporary, path)
    except Exception as problem:
        error("storage", "write_json failed %s: %r" % (path, problem))
        raise


def append_log(message):
    error("base", message)
