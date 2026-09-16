"""Tiny filesystem helpers shared by device and simulator adapters."""
import json


def read_json(path, default=None):
    try:
        with open(path, "r") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, value):
    temporary = path + ".new"
    with open(temporary, "w") as handle:
        json.dump(value, handle)
    try:
        import os
        os.rename(temporary, path)
    except OSError:
        # FAT does not always permit replacing an existing name.
        try:
            import os
            os.remove(path)
            os.rename(temporary, path)
        except OSError:
            raise


def append_log(message):
    try:
        with open("/base.log", "a") as handle:
            handle.write(message + "\n")
    except OSError:
        pass
