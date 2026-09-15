"""Intentionally small dependency-free development process reloader."""
import os
import subprocess
import sys
import time


def _newest(paths):
    newest = 0
    for root in paths:
        for directory, _, names in os.walk(root):
            for name in names:
                if name.endswith((".py", ".html", ".css", ".js")):
                    newest = max(newest, os.path.getmtime(os.path.join(directory, name)))
    return newest


def run(arguments, paths):
    command = [sys.executable, "-m", "xbrut.simulator.server", "--worker", "--host", arguments.host, "--port", str(arguments.port), "--ap-host", arguments.ap_host, "--ap-port", str(arguments.ap_port)]
    known = _newest(paths)
    child = None
    try:
        while True:
            child = subprocess.Popen(command)
            while child.poll() is None:
                time.sleep(0.4)
                changed = _newest(paths)
                if changed > known:
                    known = changed
                    print("X Brut simulator: change detected; reloading")
                    child.terminate(); child.wait()
                    break
            else:
                return child.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        if child and child.poll() is None:
            child.terminate(); child.wait()
