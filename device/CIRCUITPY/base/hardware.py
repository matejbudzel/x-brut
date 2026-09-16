"""Only hardware-dependent adapter. X4 display is initialized by CircuitPython."""
import board, displayio

class X4Platform:
    def __init__(self):
        self.display = board.DISPLAY
        self.display.rotation = 270
        self._frame_path = "/.xbrut-frame.bmp"
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
        self._bitmap = displayio.OnDiskBitmap(self._frame_path)
        self._group = displayio.Group()
        self._group.append(displayio.TileGrid(self._bitmap, pixel_shader=self._bitmap.pixel_shader))
        self.display.root_group = self._group
        from adafruit_xteink_x4 import InputManager
        self.buttons = InputManager()
    def _row_offset(self, y): return 62 + (799 - y) * 60
    def _write_row(self, y, row):
        self._frame.seek(self._row_offset(y)); self._frame.write(row)
    def clear(self):
        for y in range(800): self._write_row(y, b"\0" * 60)
    def pixel(self, x, y, on=True):
        offset, mask = self._row_offset(y) + x // 8, 128 >> (x & 7)
        self._frame.seek(offset); value = self._frame.read(1)[0]
        self._frame.seek(offset); self._frame.write(bytes((value | mask if on else value & ~mask,)))
    def present(self, packed):
        for y in range(800):
            self._write_row(y, packed[y * 60:(y + 1) * 60])
        self.refresh()
    def present_file(self, path):
        """Refresh from a packed 1-bit file without allocating a second frame."""
        with open(path, "rb") as handle:
            for y in range(800):
                row = handle.read(60)
                if len(row) != 60: raise ValueError("invalid framebuffer size")
                self._write_row(y, row)
        self.refresh()
    def refresh(self):
        self._frame.flush()
        self.display.refresh()
    def button(self):
        self.buttons.update()
        if not self.buttons.any_pressed: return None
        # InputManager names are documented by the official helper library.
        for index in range(7):
            if self.buttons.was_pressed(index):
                name = self.buttons.button_name(index).lower().replace(" ", "_")
                # The physical Back key is the leftmost under-display key.
                # The two side keys are additional menu navigation controls.
                # Back is the labeled Settings key; accept Left there too so
                # the home screen has an intuitive second way into Settings.
                return {"back": "left", "left": "left", "right": "button_4", "power_button": "power"}.get(name, name)
    def sleep(self):
        import alarm
        # InputManager owns BUTTON, so release it before handing that pin to
        # the wake alarm. Edge triggering avoids immediately waking on the
        # power-key press that put the device to sleep.
        self.buttons.deinit()
        wake = alarm.pin.PinAlarm(pin=board.BUTTON, value=False, edge=True, pull=True)
        alarm.light_sleep_until_alarms(wake)
        from adafruit_xteink_x4 import InputManager
        self.buttons = InputManager()
    def connect(self, ssid, password):
        import wifi
        wifi.radio.connect(ssid, password)
    def json(self, url):
        import json
        return json.loads(self.bytes(url).decode("utf-8"))
    def bytes(self, url, progress=None):
        import adafruit_requests, socketpool, ssl, wifi
        session = adafruit_requests.Session(socketpool.SocketPool(wifi.radio), ssl.create_default_context()); response = session.get(url)
        try:
            total, data = int(response.headers.get("content-length", "0")), bytearray()
            for chunk in response.iter_content(chunk_size=1024):
                data.extend(chunk)
                if progress and total: progress(len(data) * 100 // total)
            if progress: progress(100)
            return bytes(data)
        finally: response.close()
    def start_ap(self, conf):
        import random, wifi
        if not conf.get("ap_password"):
            alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; conf["ap_password"] = "".join(random.choice(alphabet) for _ in range(12))
            from xbrut_storage import write_json; write_json("/base-conf.json", conf)
        wifi.radio.start_ap(conf.get("ap_ssid", "x-brut"), conf["ap_password"])
    def socket_pool(self):
        import socketpool, wifi
        return socketpool.SocketPool(wifi.radio)
    def ap_address(self):
        import wifi
        return wifi.radio.ipv4_address_ap
    def disconnect(self):
        import wifi
        try: wifi.radio.stop_station()
        except Exception: pass
        try: wifi.radio.stop_ap()
        except Exception: pass
