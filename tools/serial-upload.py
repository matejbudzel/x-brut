#!/usr/bin/env python3
"""Minimal serial-REPL uploader used by install-x4.sh; no board mount needed."""
import argparse
import base64
import os
import time

import serial


WIPE_SCRIPT = b"""def remove_tree(path):
    for name in os.listdir(path):
        child = path + "/" + name
        try:
            os.remove(child)
        except OSError:
            remove_tree(child)
            os.rmdir(child)

for directory in ("/base", "/lib"):
    try:
        remove_tree(directory)
        os.rmdir(directory)
    except OSError:
        pass
for filename in ("/code.py", "/project.py", "/project.py.bak"):
    try:
        os.remove(filename)
    except OSError:
        pass
"""


def prompt(device, timeout=12):
    deadline, output = time.monotonic() + timeout, b""
    while time.monotonic() < deadline:
        output += device.read(device.in_waiting or 1)
        if output.endswith(b">>> "):
            return output
        time.sleep(0.02)
    raise RuntimeError("CircuitPython REPL did not return a prompt: " + repr(output[-200:]))


def command(device, value):
    device.write(value.encode("ascii") + b"\r\n")
    device.flush()
    response = prompt(device)
    if b"Traceback" in response:
        raise RuntimeError(response.decode("utf-8", "replace"))
    return response


def start_repl(device):
    device.reset_input_buffer()
    device.write(b"\x03\x03\r\n")
    device.flush()
    prompt(device)


def write_bytes(device, target, contents):
    command(device, "f=open(%r,'wb')" % target)
    for offset in range(0, len(contents), 360):
        command(device, "f.write(binascii.a2b_base64(%r))" % base64.b64encode(contents[offset:offset + 360]))
    command(device, "f.close()")


def wipe_application(device):
    """Remove X Brut code and libraries while retaining device configuration."""
    command(device, "import os,binascii")
    temporary = "/.__xbrut_wipe.py"
    write_bytes(device, temporary, WIPE_SCRIPT)
    command(device, "exec(open(%r).read())" % temporary)
    command(device, "os.remove(%r)" % temporary)


def upload(device, source, relative):
    target = "/" + relative.replace(os.sep, "/")
    # CircuitPython exposes the standard-library-compatible ``binascii``
    # module; ``ubinascii`` is MicroPython-only.
    command(device, "import os,binascii")
    parent = "/"
    for part in relative.replace(os.sep, "/").split("/")[:-1]:
        directory = parent.rstrip("/") + "/" + part
        command(device, "os.mkdir(%r) if %r not in os.listdir(%r) else None" % (directory, part, parent))
        parent = directory
    with open(os.path.join(source, relative), "rb") as handle:
        write_bytes(device, target, handle.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--source")
    parser.add_argument("--check-circuitpython", action="store_true")
    parser.add_argument("--wipe", action="store_true", help="remove managed app files before upload")
    args = parser.parse_args()
    if not args.check_circuitpython and not args.source:
        parser.error("--source is required unless --check-circuitpython is used")
    with serial.Serial(args.port, 115200, timeout=0.1) as device:
        start_repl(device)
        if args.check_circuitpython:
            response = command(device, "import sys;print(sys.implementation.name)")
            if b"circuitpython" not in response.lower():
                raise RuntimeError("connected REPL is not CircuitPython")
            print("CircuitPython REPL detected.")
            return
        if args.wipe:
            wipe_application(device)
    files = []
    for root, _, names in os.walk(args.source):
        for name in names:
            path = os.path.relpath(os.path.join(root, name), args.source)
            if path != "code.py": files.append(path)
    files.sort()
    # code.py runs immediately when closed, so it must be uploaded last.
    if os.path.exists(os.path.join(args.source, "code.py")): files.append("code.py")
    with serial.Serial(args.port, 115200, timeout=0.1) as device:
        start_repl(device)
        for path in files:
            print("upload", path)
            upload(device, args.source, path)


if __name__ == "__main__": main()
