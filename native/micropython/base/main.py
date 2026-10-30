"""Temporary boot entry for the MicroPython portrait-base checkpoint."""
import os
import time

import xbrut_x4
from xbrut_hardware import X4Platform
from xbrut_framebuffer import Framebuffer
from xbrut_input import Input


def mount_sd():
    try:
        os.mount(os.VfsFat(xbrut_x4.SDCard()), "/sd")
    except OSError:
        # The mount can already exist after a soft reset.
        pass


def draw(frame, states, message, power):
    frame.clear()
    frame.outline(12, 12, 456, 776)
    frame.text(42, 44, "X BRUT", 4)
    frame.text(42, 110, "PORTRAIT BASE", 2)
    frame.text(42, 160, "INPUT TEST", 2)
    frame.text(42, 250, "LEFT " + (states["left"] or "UP"), 2)
    frame.text(42, 310, "RIGHT " + (states["right"] or "UP"), 2)
    frame.text(42, 370, "POWER " + ("DOWN" if power else "UP"), 2)
    frame.text(42, 500, message, 1)
    frame.text(42, 740, "FULL REFRESH BASE", 1)
    frame.refresh()


def main():
    xbrut_x4.init()
    mount_sd()
    platform = X4Platform()
    frame = Framebuffer(platform)
    states = {"left": None, "right": None}
    power = xbrut_x4.power_button()
    try:
        controls = Input(xbrut_x4)
    except Exception:
        draw(frame, states, "NO BUTTON CALIBRATION", power)
        return
    draw(frame, states, "READY", power)
    while True:
        changes, states = controls.poll()
        new_power = xbrut_x4.power_button()
        if changes or new_power != power:
            power = new_power
            if changes:
                _channel, previous, current = changes[-1]
                message = "LAST " + (current or previous or "UNKNOWN")
            else:
                message = "POWER " + ("DOWN" if power else "UP")
            draw(frame, states, message, power)
        time.sleep_ms(20)


main()
