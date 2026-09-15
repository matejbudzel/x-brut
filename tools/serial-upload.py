#!/usr/bin/env python3
"""Minimal serial-REPL uploader used by install-x4.sh; no board mount needed."""
import argparse
import base64
import os
import time

import serial


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


def upload(device, source, relative):
    target = "/" + relative.replace(os.sep, "/")
    command(device, "import os,ubinascii")
    parent = "/"
    for part in relative.replace(os.sep, "/").split("/")[:-1]:
        directory = parent.rstrip("/") + "/" + part
        command(device, "os.mkdir(%r) if %r not in os.listdir(%r) else None" % (directory, part, parent))
        parent = directory
    command(device, "f=open(%r,'wb')" % target)
    with open(os.path.join(source, relative), "rb") as handle:
        while True:
            chunk = handle.read(360)
            if not chunk: break
            command(device, "f.write(ubinascii.a2b_base64(%r))" % base64.b64encode(chunk))
    command(device, "f.close()")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True); parser.add_argument("--source", required=True)
    args = parser.parse_args()
    files = []
    for root, _, names in os.walk(args.source):
        for name in names:
            path = os.path.relpath(os.path.join(root, name), args.source)
            if path != "code.py": files.append(path)
    files.sort()
    # code.py runs immediately when closed, so it must be uploaded last.
    if os.path.exists(os.path.join(args.source, "code.py")): files.append("code.py")
    with serial.Serial(args.port, 115200, timeout=0.1) as device:
        device.write(b"\x03\x03\r\n"); prompt(device)
        for path in files:
            print("upload", path)
            upload(device, args.source, path)


if __name__ == "__main__": main()
