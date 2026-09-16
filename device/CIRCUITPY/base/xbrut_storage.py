"""Tiny filesystem helpers shared by device and simulator adapters."""
import json
from xbrut_log import debug, error


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
