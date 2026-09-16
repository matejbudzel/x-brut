"""Small, failure-safe logger for CircuitPython and the desktop simulator."""
import json, os, time

LOG_LEVELS = ("debug", "info", "error", "off")
_VALUES = {"off": 0, "error": 1, "info": 2, "debug": 3}
_level = 3
_path = "/base.log"
_max_bytes = 128 * 1024


def set_path(path):
    """Redirect logs; used by the desktop simulator and x64 tests."""
    global _path
    _path = path


def configure(conf):
    """Set overall verbosity from base-conf.json; invalid/missing means debug."""
    global _level
    name = str(conf.get("log_level", "debug")).lower()
    _level = _VALUES.get(name, _VALUES["debug"])


def level():
    for name in LOG_LEVELS:
        if _VALUES[name] == _level: return name
    return "debug"


def safe_url(url):
    """Remove query tokens and URL user info before writing diagnostics."""
    value = url.split("?", 1)[0]
    scheme = value.find("://")
    credentials = value.find("@", scheme + 3) if scheme >= 0 else -1
    if credentials >= 0:
        value = value[:scheme + 3] + "***@" + value[credentials + 1:]
    return value


def _rotate():
    backup = _path + ".1"
    try: os.remove(backup)
    except OSError: pass
    try: os.rename(_path, backup)
    except OSError: pass


def _write(required, name, component, message):
    if _level < required: return
    line = "%010.3f %-5s %-12s %s\n" % (time.monotonic(), name, component, message)
    try:
        rotate = False
        with open(_path, "a") as handle:
            rotate = handle.tell() + len(line) > _max_bytes
            if not rotate: handle.write(line)
        if rotate:
            _rotate()
            with open(_path, "w") as handle: handle.write(line)
    except Exception:
        # Diagnostics must never stop recovery, including on a full/read-only FS.
        pass


def debug(component, message): _write(3, "DEBUG", component, message)
def info(component, message): _write(2, "INFO", component, message)
def error(component, message): _write(1, "ERROR", component, message)


def exception(component, message, problem):
    """Log an error and its traceback without masking the original failure."""
    error(component, "%s: %r" % (message, problem))
    if _level < 1: return
    try:
        import traceback
        with open(_path, "a") as handle: traceback.print_exception(problem, file=handle)
    except Exception:
        pass


# Honor an existing device setting before imports elsewhere emit their first log.
try:
    with open("/base-conf.json", "r") as _conf_file: configure(json.load(_conf_file))
except Exception:
    configure({})
