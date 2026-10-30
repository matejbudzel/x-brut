"""MicroPython X4 hardware adapter for the legacy portrait base contract."""
import time
import xbrut_x4


class X4Platform:
    """Map the base's 480x800 portrait surface onto X4's 800x480 panel."""
    width = 480
    height = 800

    @staticmethod
    def _rect(x, y, width, height):
        # Portrait (x, y) maps to physical (y, 479-x). Rectangles rotate.
        return y, 480 - (x + width), height, width

    def __init__(self):
        xbrut_x4.init()
        self.clear()

    def clear(self):
        xbrut_x4.framebuffer_clear()

    def fill_rect(self, x, y, width, height, on=False):
        px, py, pw, ph = self._rect(x, y, width, height)
        if on:
            # The original black-only primitive is the tested display path.
            xbrut_x4.framebuffer_rect(px, py, pw, ph)
        else:
            xbrut_x4.framebuffer_fill_rect(px, py, pw, ph, False)

    def pixel(self, x, y, on=True):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.fill_rect(x, y, 1, 1, on)

    def blit(self, x, y, width, height, packed):
        row_bytes = (width + 7) // 8
        for row in range(height):
            for column in range(width):
                if packed[row * row_bytes + column // 8] & (128 >> (column & 7)):
                    self.pixel(x + column, y + row)

    def refresh(self):
        # The native differential waveform is not yet stable after a full
        # reset.  A base render therefore uses the reliable full-frame path;
        # async fast presentation will be restored once its waveform state is
        # validated independently.
        xbrut_x4.framebuffer_present_full()

    def battery_status(self):
        raw, _, _ = xbrut_x4.adc_raw()
        # Temporary raw ADC estimate; voltage calibration is a later base task.
        return max(0, min(100, (raw - 2200) * 100 // 700)), xbrut_x4.usb_present()

    def sleep(self):
        xbrut_x4.sleep()
