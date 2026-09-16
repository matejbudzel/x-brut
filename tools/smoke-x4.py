#!/usr/bin/env python3
"""Non-destructive CircuitPython smoke test for a connected Xteink X4."""
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


def command(device, value):
    device.write(value.encode("ascii") + b"\r\n")
    device.flush()
    result = prompt(device)
    if b"Traceback" in result:
        raise RuntimeError(result.decode("utf-8", "replace"))
    return result.decode("utf-8", "replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    with serial.Serial(args.port, 115200, timeout=0.1) as device:
        device.reset_input_buffer()
        device.write(b"\x03\x03\r\n")
        device.flush()
        prompt(device)
        # Keep this one line so it is valid at an ordinary CircuitPython REPL.
        result = command(device, "import board,gc,sys;from adafruit_xteink_x4 import InputManager;b=InputManager();b.update();print('board=%s cpy=%s display=%s heap=%d' % (board.board_id,sys.implementation.version,type(board.DISPLAY).__name__,gc.mem_free()));b.deinit()")
        print(result, end="")
        device.write(b"\x04")  # Restore the installed application after the check.
        device.flush()


if __name__ == "__main__":
    main()
