#!/usr/bin/env python3
"""Print an X Brut log file through a CircuitPython serial REPL."""
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--path", default="/sd/base.log")
    args = parser.parse_args()
    parent, name = args.path.rsplit("/", 1)
    command = "import sys;sys.path.append('/base');from xbrut_storage import mount_sd;mount_sd();import os;print(open(%r).read() if %r in os.listdir(%r) else 'no log file')" % (args.path, name, parent or "/")
    with serial.Serial(args.port, 115200, timeout=0.1) as device:
        device.reset_input_buffer()
        device.write(b"\x03\x03\r\n")
        device.flush()
        prompt(device)
        device.write(command.encode("ascii") + b"\r\n")
        device.flush()
        print(prompt(device).decode("utf-8", "replace"), end="")
        device.write(b"\x04")  # Resume the installed application after reading.
        device.flush()


if __name__ == "__main__":
    main()
