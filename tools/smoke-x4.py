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
        result = command(device, "import alarm,board,gc,sys;from adafruit_xteink_x4 import InputManager;b=InputManager();b.update();names=','.join(b.button_name(i) for i in range(7));power=b.power_button_pressed;b.deinit();wake=alarm.pin.PinAlarm(pin=board.BUTTON,value=False,pull=True);print('board=%s cpy=%s display=%s size=%dx%d rotation=%d buttons=%s power=%s heap=%d' % (board.board_id,sys.implementation.version,type(board.DISPLAY).__name__,board.DISPLAY.width,board.DISPLAY.height,board.DISPLAY.rotation,names,power,gc.mem_free()));del wake")
        print(result, end="")
        device.write(b"\x04")  # Restore the installed application after the check.
        device.flush()


if __name__ == "__main__":
    main()
