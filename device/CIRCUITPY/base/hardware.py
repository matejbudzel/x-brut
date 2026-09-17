"""Only hardware-dependent adapter. X4 display is initialized by CircuitPython."""
import board, displayio
from xbrut_log import debug, error, info, safe_url
from xbrut_paths import BASE_CONFIG_PATH, FRAME_PATH

BACK_LONG_PRESS_SECONDS = 0.8


class X4Platform:
    def __init__(self):
        # type: () -> None
        info("hardware", "X4Platform init begin")
        self.display = board.DISPLAY
        debug("hardware", "display=%s size=%sx%s" % (type(self.display).__name__, self.display.width, self.display.height))
        self.display.rotation = 270
        debug("hardware", "display rotation=270")
        self._back_pending = False
        self._back_long_emitted = False
        self._frame_path = FRAME_PATH
        self._ram_mode = False
        try:
            self._open_file_frame()
        except OSError as problem:
            info("hardware", "microSD framebuffer unavailable: %r; using RAM" % problem)
            self._ram_mode = True
            self._ram_bitmap = displayio.Bitmap(480, 800, 2)
            self._ram_bitmap.fill(0)
            palette = displayio.Palette(2)
            palette[0], palette[1] = 0xffffff, 0
            self._group = displayio.Group()
            self._group.append(displayio.TileGrid(self._ram_bitmap, pixel_shader=palette))
            self.display.root_group = self._group
            from adafruit_xteink_x4 import InputManager
            self.buttons = InputManager()
            from adafruit_xteink_x4 import BatteryMonitor
            self.battery = BatteryMonitor()
            info("hardware", "X4Platform init complete (RAM framebuffer)")
            return
        from adafruit_xteink_x4 import InputManager
        self.buttons = InputManager()
        from adafruit_xteink_x4 import BatteryMonitor
        self.battery = BatteryMonitor()
        info("hardware", "X4Platform init complete")

    def _open_file_frame(self):
        debug("hardware", "opening framebuffer %s" % self._frame_path)
        self._frame = open(self._frame_path, "w+b")
        # 480x800, 1-bit BMP. Rows are 60 bytes and naturally 4-byte aligned.
        self._frame.write(
            b"BM" + (48062).to_bytes(4, "little") + b"\0\0\0\0" + (62).to_bytes(4, "little") +
            (40).to_bytes(4, "little") + (480).to_bytes(4, "little") + (800).to_bytes(4, "little") +
            b"\1\0\1\0" + b"\0" * 16 + (2).to_bytes(4, "little") + b"\0" * 4 +
            b"\xff\xff\xff\0\0\0\0\0"
        )
        self.clear()
        self._frame.flush()
        debug("hardware", "framebuffer initialized bytes=48062")
        self._bitmap = displayio.OnDiskBitmap(self._frame_path)
        self._group = displayio.Group()
        self._group.append(displayio.TileGrid(self._bitmap, pixel_shader=self._bitmap.pixel_shader))
        self.display.root_group = self._group
        debug("hardware", "display root_group installed")
    def _row_offset(self, y):
        # type: (int) -> int
        return 62 + (799 - y) * 60
    def _write_row(self, y, row):
        # type: (int, bytes) -> None
        self._frame.seek(self._row_offset(y)); self._frame.write(row)
    def clear(self):
        # type: () -> None
        debug("hardware", "framebuffer clear begin")
        if self._ram_mode:
            self._ram_bitmap.fill(0)
            return
        for y in range(800): self._write_row(y, b"\0" * 60)
        debug("hardware", "framebuffer clear complete")
    def pixel(self, x, y, on=True):
        # type: (int, int, bool) -> None
        if self._ram_mode:
            self._ram_bitmap[x, y] = 1 if on else 0
            return
        offset, mask = self._row_offset(y) + x // 8, 128 >> (x & 7)
        self._frame.seek(offset); value = self._frame.read(1)[0]
        self._frame.seek(offset); self._frame.write(bytes((value | mask if on else value & ~mask,)))
    def present(self, packed):
        # type: (bytes) -> None
        debug("hardware", "present begin bytes=%d" % len(packed))
        if self._ram_mode:
            self.clear()
            for y in range(800):
                for x in range(480):
                    self._ram_bitmap[x, y] = 1 if packed[y * 60 + x // 8] & (128 >> (x & 7)) else 0
            self.refresh()
            return
        for y in range(800):
            self._write_row(y, packed[y * 60:(y + 1) * 60])
        self.refresh()
        debug("hardware", "present complete")
    def present_file(self, path):
        # type: (str) -> None
        """Refresh from a packed 1-bit file without allocating a second frame."""
        debug("hardware", "present_file begin %s" % path)
        with open(path, "rb") as handle:
            for y in range(800):
                row = handle.read(60)
                if len(row) != 60:
                    error("hardware", "present_file invalid row=%d bytes=%d" % (y, len(row)))
                    raise ValueError("invalid framebuffer size")
                self._write_row(y, row)
        self.refresh()
        debug("hardware", "present_file complete %s" % path)
    def refresh(self):
        # type: () -> None
        debug("hardware", "refresh begin time_to_refresh=%s busy=%s" % (self.display.time_to_refresh, self.display.busy))
        if not self._ram_mode: self._frame.flush()
        if self.display.time_to_refresh > 0:
            import time
            time.sleep(self.display.time_to_refresh)
        try: self.display.refresh()
        except Exception as problem:
            error("hardware", "refresh failed: %r" % problem)
            raise
        debug("hardware", "refresh complete")
    def button(self):
        self.buttons.update()
        # Defer the physical Back key until it is released. This lets a hold
        # mean "go home" without first applying a regular history Back.
        if self._back_pending:
            if self.buttons.is_pressed(self.buttons.BTN_BACK):
                if not self._back_long_emitted and self.buttons.held_time >= BACK_LONG_PRESS_SECONDS:
                    self._back_long_emitted = True
                    info("hardware", "back long press seconds=%.2f" % self.buttons.held_time)
                    return "left_long"
                return None
            if self.buttons.was_released(self.buttons.BTN_BACK):
                self._back_pending = False
                if not self._back_long_emitted:
                    debug("hardware", "back short press")
                    return "left"
                self._back_long_emitted = False
                debug("hardware", "back long press released")
                return None
        if not self.buttons.any_pressed: return None
        # InputManager names are documented by the official helper library.
        for index in range(7):
            if self.buttons.was_pressed(index):
                if index == self.buttons.BTN_BACK:
                    self._back_pending = True
                    self._back_long_emitted = False
                    debug("hardware", "back press pending long threshold=%.2f" % BACK_LONG_PRESS_SECONDS)
                    return None
                name = self.buttons.button_name(index).lower().replace(" ", "_")
                # The physical Back key is the leftmost under-display key.
                # The two side keys are additional menu navigation controls.
                # Back is the labeled Settings key; accept Left there too so
                # the home screen has an intuitive second way into Settings.
                translated = {"back": "left", "left": "left", "right": "button_4", "power_button": "power"}.get(name, name)
                debug("hardware", "button index=%d raw=%s translated=%s" % (index, name, translated))
                return translated
    def battery_status(self):
        import supervisor
        return self.battery.percentage, supervisor.runtime.usb_connected
    def sleep(self):
        # type: () -> None
        import alarm, time
        info("hardware", "sleep requested; waiting for initiating press release")
        # InputManager owns BUTTON, so release it before handing that pin to
        # the wake alarm. ESP32-C3 only supports level wake alarms, so wait
        # for the power-key press that initiated sleep to be released first.
        polls = 0
        while self.buttons.power_button_pressed:
            time.sleep(0.02)
            self.buttons.update()
            polls += 1
        debug("hardware", "power released after %d polls" % polls)
        self.buttons.deinit()
        debug("hardware", "InputManager deinitialized")
        wake = alarm.pin.PinAlarm(pin=board.BUTTON, value=False, pull=True)
        debug("hardware", "PinAlarm ready pin=BUTTON value=False pull=True")
        try:
            info("hardware", "entering light_sleep_until_alarms")
            woke = alarm.light_sleep_until_alarms(wake)
            info("hardware", "light sleep returned wake=%r" % woke)
        except Exception as problem:
            error("hardware", "light sleep failed: %r" % problem)
            raise
        finally:
            from adafruit_xteink_x4 import InputManager
            self.buttons = InputManager()
            debug("hardware", "InputManager reinitialized")
    def connect(self, ssid, password):
        # type: (str, str) -> None
        import wifi
        info("hardware", "wifi connect begin ssid=%s" % ssid)
        try: wifi.radio.connect(ssid, password)
        except Exception as problem:
            error("hardware", "wifi connect failed: %r" % problem)
            raise
        info("hardware", "wifi connected")
    def json(self, url):
        # type: (str) -> dict[str, object]
        import json
        debug("hardware", "json GET %s" % safe_url(url))
        return json.loads(self.bytes(url).decode("utf-8"))
    def bytes(self, url, progress=None):
        import adafruit_requests, socketpool, ssl, wifi
        info("hardware", "GET begin %s" % safe_url(url))
        try:
            session = adafruit_requests.Session(socketpool.SocketPool(wifi.radio), ssl.create_default_context()); response = session.get(url)
        except Exception as problem:
            error("hardware", "GET setup failed %s: %r" % (safe_url(url), problem))
            raise
        try:
            total, data, chunks = int(response.headers.get("content-length", "0")), bytearray(), 0
            debug("hardware", "GET response content_length=%d" % total)
            for chunk in response.iter_content(chunk_size=1024):
                data.extend(chunk)
                chunks += 1
                if chunks == 1 or chunks % 16 == 0: debug("hardware", "GET progress bytes=%d chunks=%d" % (len(data), chunks))
                if progress and total: progress(len(data) * 100 // total)
            if progress: progress(100)
            info("hardware", "GET complete bytes=%d chunks=%d" % (len(data), chunks))
            return bytes(data)
        except Exception as problem:
            error("hardware", "GET failed %s: %r" % (safe_url(url), problem))
            raise
        finally:
            response.close()
            debug("hardware", "GET response closed")
    def start_ap(self, conf):
        # type: (dict[str, str]) -> None
        import random, wifi
        info("hardware", "start AP requested ssid=%s" % conf.get("ap_ssid", "x-brut"))
        if not conf.get("ap_password"):
            alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; conf["ap_password"] = "".join(random.choice(alphabet) for _ in range(12))
            from xbrut_storage import SDCardUnavailable, write_json
            try:
                write_json(BASE_CONFIG_PATH, conf)
                debug("hardware", "generated and persisted AP password")
            except SDCardUnavailable:
                info("hardware", "generated temporary AP password; no microSD")
        try: wifi.radio.start_ap(conf.get("ap_ssid", "x-brut"), conf["ap_password"])
        except Exception as problem:
            error("hardware", "AP start failed: %r" % problem)
            raise
        info("hardware", "AP started address=%s" % wifi.radio.ipv4_address_ap)
    def socket_pool(self):
        import socketpool, wifi
        debug("hardware", "creating SocketPool")
        return socketpool.SocketPool(wifi.radio)
    def ap_address(self):
        import wifi
        debug("hardware", "AP address=%s" % wifi.radio.ipv4_address_ap)
        return wifi.radio.ipv4_address_ap
    def disconnect(self):
        # type: () -> None
        import wifi
        debug("hardware", "disconnect begin")
        try: wifi.radio.stop_station(); debug("hardware", "station stopped")
        except Exception as problem: debug("hardware", "stop station ignored: %r" % problem)
        try: wifi.radio.stop_ap(); debug("hardware", "AP stopped")
        except Exception as problem: debug("hardware", "stop AP ignored: %r" % problem)
        info("hardware", "disconnect complete")
