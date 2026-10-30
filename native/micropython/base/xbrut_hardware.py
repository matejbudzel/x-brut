"""Portrait drawing adapter; panel timing/transport belongs to xbrut_x4."""


class X4Platform:
    width, height = 480, 800

    def __init__(self, hardware=None):
        if hardware is None:
            import xbrut_x4
            hardware = xbrut_x4
        for name in ("init", "framebuffer_ready", "framebuffer_clear", "framebuffer_fill_rect",
                     "framebuffer_blit_portrait", "framebuffer_present"):
            if not callable(getattr(hardware, name, None)):
                raise RuntimeError("X4 firmware lacks " + name + "; clean-build the current native module")
        self.hardware = hardware
        hardware.init()

    def ready(self):
        return self.hardware.framebuffer_ready()

    def clear(self):
        self.hardware.framebuffer_clear()

    def fill_rect(self, x, y, width, height, on=False):
        # Clip before rotation, including rectangles partly outside the screen.
        right, bottom = min(480, x + width), min(800, y + height)
        x, y = max(0, x), max(0, y)
        if right > x and bottom > y:
            self.hardware.framebuffer_fill_rect(y, 480 - right, bottom - y, right - x, on)

    def pixel(self, x, y, on=True):
        self.fill_rect(x, y, 1, 1, on)

    def blit(self, x, y, width, height, packed):
        if width <= 0 or height <= 0:
            return
        if len(packed) < ((width + 7) // 8) * height:
            raise ValueError("short bitmap")
        self.hardware.framebuffer_blit_portrait(x, y, width, height, packed)

    def present(self, packed):
        if len(packed) != 48000:
            raise ValueError("invalid framebuffer size")
        self.clear()
        self.blit(0, 0, 480, 800, packed)
        self.refresh()

    def present_file(self, path):
        # Stage all reads before touching the active frame. File presentation
        # is for the idle/startup caller, not while a refresh is in flight.
        with open(path, "rb") as handle:
            packed = handle.read(48001)
        self.present(packed)

    def refresh(self):
        self.hardware.framebuffer_present()

    def battery_status(self):
        raw, _, _ = self.hardware.adc_raw()
        return max(0, min(100, (raw - 2200) * 100 // 700)), self.hardware.usb_present()

    def sleep(self):
        self.hardware.sleep()
