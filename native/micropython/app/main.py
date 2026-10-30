"""First MicroPython X4 validation screen.

Code lives in internal flash.  The active 800x480 framebuffer is a single
native RAM buffer; persistent state (including button calibration) stays on
the SD card.
"""
import os
import time
import json
import xbrut_x4
from xbrut_input import Input

WIDTH = 800
HEIGHT = 480

# Compact 5x7 glyphs for the validation screen.  A missing glyph is a box.
FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0), "-": (0, 0, 0, 31, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 12, 12), ":": (0, 12, 12, 0, 12, 12, 0),
    "/": (1, 2, 4, 8, 16, 0, 0),
}
for char, rows in {
    "A": (14,17,17,31,17,17,17), "B": (30,17,17,30,17,17,30),
    "C": (15,16,16,16,16,16,15), "D": (30,17,17,17,17,17,30),
    "E": (31,16,16,30,16,16,31), "F": (31,16,16,30,16,16,16),
    "G": (15,16,16,23,17,17,15), "H": (17,17,17,31,17,17,17),
    "I": (31,4,4,4,4,4,31), "J": (7,2,2,2,18,18,12),
    "K": (17,18,20,24,20,18,17), "L": (16,16,16,16,16,16,31),
    "M": (17,27,21,21,17,17,17), "N": (17,25,21,19,17,17,17),
    "O": (14,17,17,17,17,17,14), "P": (30,17,17,30,16,16,16),
    "Q": (14,17,17,17,21,18,13), "R": (30,17,17,30,20,18,17),
    "S": (15,16,16,14,1,1,30), "T": (31,4,4,4,4,4,4),
    "U": (17,17,17,17,17,17,14), "V": (17,17,17,17,17,10,4),
    "W": (17,17,17,21,21,21,10), "X": (17,17,10,4,10,17,17),
    "Y": (17,17,10,4,4,4,4), "Z": (31,1,2,4,8,16,31),
    "0": (14,17,19,21,25,17,14), "1": (4,12,4,4,4,4,14),
    "2": (14,17,1,2,4,8,31), "3": (30,1,1,14,1,1,30),
    "4": (2,6,10,18,31,2,2), "5": (31,16,16,30,1,1,30),
    "6": (14,16,16,30,17,17,14), "7": (31,1,2,4,8,8,8),
    "8": (14,17,17,14,17,17,14), "9": (14,17,17,15,1,1,14),
}.items():
    FONT[char] = rows


class Frame:
    def __init__(self, _path=None):
        self.clear()

    def clear(self):
        # Calibration/status screens also respect async frame ownership.
        while not xbrut_x4.framebuffer_ready():
            time.sleep_ms(10)
        xbrut_x4.framebuffer_clear()

    def pixel(self, x, y):
        xbrut_x4.framebuffer_rect(x, y, 1, 1)

    def rect(self, x, y, width, height):
        xbrut_x4.framebuffer_rect(x, y, width, height)

    def outline(self, x, y, width, height):
        self.rect(x, y, width, 1)
        self.rect(x, y + height - 1, width, 1)
        self.rect(x, y, 1, height)
        self.rect(x + width - 1, y, 1, height)

    def text(self, x, y, text, scale=1):
        for char in text.upper():
            glyph = FONT.get(char, (31,17,17,17,17,17,31))
            for row, bits in enumerate(glyph):
                for column in range(5):
                    if bits & (16 >> column):
                        self.rect(x + column * scale, y + row * scale, scale, scale)
            x += 6 * scale

    def present(self, fast=False):
        xbrut_x4.framebuffer_present()


def mount_sd():
    sd = xbrut_x4.SDCard()
    try:
        os.mount(os.VfsFat(sd), "/sd")
    except OSError:
        # A soft reboot may leave the mount table intact.
        pass
    return sd


def median(values):
    values = sorted(values)
    return values[len(values) // 2]


def ladder_baseline():
    left = []
    right = []
    for _ in range(15):
        _, value_left, value_right = xbrut_x4.adc_raw()
        left.append(value_left)
        right.append(value_right)
        time.sleep_ms(15)
    return median(left), median(right)


def draw_message(frame, title, detail, fast=False):
    frame.clear()
    frame.outline(16, 16, 768, 448)
    frame.text(48, 65, "X BRUT X4", 4)
    frame.text(48, 155, title, 4)
    frame.text(48, 255, detail, 2)
    frame.text(48, 390, "FOLLOW THE SCREEN", 2)
    frame.present(fast)


def calibrate(frame):
    """Capture median ADC values for all physical buttons in one sitting."""
    labels = ("LOWER-1", "LOWER-2", "LOWER-3", "LOWER-4", "SIDE-1", "SIDE-2")
    baseline_left, baseline_right = ladder_baseline()
    result = {"version": 1, "baseline": {"left": baseline_left, "right": baseline_right}, "buttons": {}}
    draw_message(frame, "BUTTON SETUP", "RELEASE ALL BUTTONS")
    time.sleep_ms(800)
    for index, label in enumerate(labels):
        draw_message(frame, "HOLD " + label, "WAIT FOR CAPTURE", fast=index > 0)
        # A press is a meaningful displacement from the released ladder.
        channel = None
        while channel is None:
            _, left, right = xbrut_x4.adc_raw()
            if abs(left - baseline_left) > 100:
                channel = "left"
            elif abs(right - baseline_right) > 100:
                channel = "right"
            time.sleep_ms(20)
        samples = []
        for _ in range(25):
            _, left, right = xbrut_x4.adc_raw()
            samples.append(left if channel == "left" else right)
            time.sleep_ms(20)
        value = median(samples)
        result["buttons"][label.lower()] = {"channel": channel, "raw": value}
        draw_message(frame, label + " OK", channel.upper() + " " + str(value), fast=True)
        # Require release before the following prompt, avoiding accidental
        # double capture from the same held button.
        while True:
            _, left, right = xbrut_x4.adc_raw()
            if abs(left - baseline_left) <= 100 and abs(right - baseline_right) <= 100:
                break
            time.sleep_ms(20)
        time.sleep_ms(350)
    with open("/sd/button-calibration.json", "w") as handle:
        json.dump(result, handle)
    draw_message(frame, "SETUP COMPLETE", "SAVED TO SD", fast=True)
    return result


def draw_status(frame, sd):
    frame.clear()
    frame.outline(16, 16, 768, 448)
    frame.text(48, 55, "X BRUT X4", 5)
    frame.text(48, 130, "MICROPYTHON", 3)
    frame.text(48, 185, "SD SHARED SPI READY", 2)
    size, block = sd.info()
    frame.text(48, 235, "SD %d MB  %d B BLOCKS" % (size // 1048576, block), 2)
    frame.text(48, 285, "USB %s" % ("PRESENT" if xbrut_x4.usb_present() else "OFFLINE"), 2)
    frame.text(48, 335, "ADC %s" % (xbrut_x4.adc_raw(),), 2)
    frame.text(48, 405, "POWER BUTTON SLEEPS", 2)
    frame.present()


def join(path, name):
    return path.rstrip("/") + "/" + name


def directory(path):
    rows = []
    for name in os.listdir(path):
        if name in (".xbrut-frame.raw", "button-calibration.json"):
            continue
        target = join(path, name)
        try:
            stat = os.stat(target)
        except OSError:
            continue
        rows.append((name, bool(stat[0] & 16384), stat[6]))
    rows.sort(key=lambda row: (not row[1], row[0].lower()))
    return rows


def draw_browser(frame, path, rows, focus, message="", states=None, power=False, fast=False):
    frame.clear()
    frame.outline(16, 16, 768, 448)
    frame.text(42, 38, "SD FILES", 3)
    frame.text(42, 80, path[:28], 1)
    start = max(0, min(focus - 3, max(0, len(rows) - 7)))
    for slot, (name, is_dir, size) in enumerate(rows[start:start + 7]):
        index = start + slot
        y = 120 + slot * 40
        if index == focus:
            frame.outline(34, y - 4, 730, 32)
        label = ("DIR " if is_dir else "FILE ") + name[:18]
        frame.text(48, y, label, 2)
        frame.text(500, y, str(size), 1)
    if not rows:
        frame.text(48, 160, "EMPTY DIRECTORY", 2)
    states = states or {"left": None, "right": None}
    left = states["left"] or "UP"
    right = states["right"] or "UP"
    frame.text(42, 390, "L " + left + "  R " + right + "  P " + ("DOWN" if power else "UP"), 1)
    frame.text(42, 420, message or "SIDE: MOVE  LOWER-2: OPEN", 1)
    frame.present(fast)


def browser(frame):
    controls = Input(xbrut_x4)
    path = "/sd"
    rows = directory(path)
    focus = 0
    states = {"left": None, "right": None}
    power = False
    last = "READY"
    draw_browser(frame, path, rows, focus, last, states, power)
    redraw_pending = False
    while True:
        changes, states = controls.poll()
        new_power = xbrut_x4.power_button()
        if changes or new_power != power:
            power = new_power
            pressed = [current for _, previous, current in changes if current and current != previous]
            event = pressed[0] if pressed else None
            if event == "side-1" and rows:
                focus = (focus - 1) % len(rows)
            elif event == "side-2" and rows:
                focus = (focus + 1) % len(rows)
            elif event == "lower-1" and path != "/sd":
                path = path.rsplit("/", 1)[0] or "/sd"
                rows, focus = directory(path), 0
            elif event == "lower-2" and rows:
                name, is_dir, size = rows[focus]
                if is_dir:
                    path, rows, focus = join(path, name), directory(join(path, name)), 0
                else:
                    last = "FILE " + str(size) + " BYTES"
            elif event in ("lower-3", "lower-4"):
                rows, focus = directory(path), min(focus, max(0, len(rows) - 1))
            if changes:
                bits = []
                for channel, previous, current in changes:
                    bits.append((current or previous or "UNKNOWN") + (" DOWN" if current else " UP"))
                last = "LAST " + " ".join(bits)
            elif power:
                last = "LAST POWER DOWN"
            else:
                last = "LAST POWER UP"
            redraw_pending = True
        if not xbrut_x4.framebuffer_ready():
            time.sleep_ms(15)
            continue
        if redraw_pending:
            redraw_pending = False
            draw_browser(frame, path, rows, focus, last, states, power, True)
        else:
            time.sleep_ms(15)


def main():
    xbrut_x4.init()
    sd = mount_sd()
    frame = Frame()
    try:
        os.stat("/sd/button-calibration.json")
    except OSError:
        calibrate(frame)
    browser(frame)


main()
