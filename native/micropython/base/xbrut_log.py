"""Small failure-safe MicroPython logger; logs are always SD-backed."""
import time

from xbrut_paths import BASE_CONFIG_PATH, LOG_PATH

LOG_LEVELS = ("debug", "info", "error", "off")
_VALUES = {"off": 0, "error": 1, "info": 2, "debug": 3}
_level = 3
_path = LOG_PATH
_max_bytes = 128 * 1024


def _ticks_seconds():
    return time.ticks_ms() / 1000


def set_path(path):
    """Redirect logs for an explicit test only; production uses /sd."""
    global _path
    _path = path


def configure(conf):
    global _level
    _level = _VALUES.get(str(conf.get("log_level", "debug")).lower(), 3)


def level():
    for name in LOG_LEVELS:
        if _VALUES[name] == _level:
            return name
    return "debug"


def safe_url(url):
    value = url.split("?", 1)[0]
    scheme = value.find("://")
    credentials = value.find("@", scheme + 3) if scheme >= 0 else -1
    return value[:scheme + 3] + "***@" + value[credentials + 1:] if credentials >= 0 else value


def _rotate():
    import os
    try: os.remove(_path + ".1")
    except OSError: pass
    try: os.rename(_path, _path + ".1")
    except OSError: pass


def _write(required, name, component, message):
    if _level < required:
        return
    line = "%010.3f %-5s %-12s %s\n" % (_ticks_seconds(), name, component, message)
    try:
        with open(_path, "a") as handle:
            rotate = handle.tell() + len(line) > _max_bytes
            if not rotate:
                handle.write(line)
        if rotate:
            _rotate()
            with open(_path, "w") as handle:
                handle.write(line)
    except Exception:
        pass


def debug(component, message): _write(3, "DEBUG", component, message)
def info(component, message): _write(2, "INFO", component, message)
def error(component, message): _write(1, "ERROR", component, message)


def exception(component, message, problem):
    error(component, "%s: %r" % (message, problem))
    if _level < 1:
        return
    try:
        import sys
        with open(_path, "a") as handle:
            sys.print_exception(problem, handle)
    except Exception:
        pass


try:
    import json
    with open(BASE_CONFIG_PATH) as _conf_file:
        configure(json.load(_conf_file))
except Exception:
    configure({})
