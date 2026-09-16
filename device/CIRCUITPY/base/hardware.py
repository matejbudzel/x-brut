"""Only hardware-dependent adapter. X4 display is initialized by CircuitPython."""
import board, displayio

class X4Platform:
    def __init__(self):
        self.display = board.DISPLAY
        self.display.rotation = 270
        self.bitmap = displayio.Bitmap(480, 800, 2); self.palette = displayio.Palette(2)
        self.palette[0], self.palette[1] = 0xffffff, 0x000000
        group = displayio.Group(); group.append(displayio.TileGrid(self.bitmap, pixel_shader=self.palette)); self.display.root_group = group
        # Allocate the display bitmap before importing optional Python libraries.
        from adafruit_xteink_x4 import InputManager
        self.buttons = InputManager()
    def present(self, packed):
        for y in range(800):
            for x in range(480): self.bitmap[x, y] = 1 if packed[y * 60 + x // 8] & (128 >> (x & 7)) else 0
        self.display.refresh()
    def present_file(self, path):
        """Refresh from a packed 1-bit file without allocating a second frame."""
        with open(path, "rb") as handle:
            for y in range(800):
                row = handle.read(60)
                if len(row) != 60: raise ValueError("invalid framebuffer size")
                for x in range(480): self.bitmap[x, y] = 1 if row[x // 8] & (128 >> (x & 7)) else 0
        self.display.refresh()
    def refresh(self): self.display.refresh()
    def button(self):
        self.buttons.update()
        if not self.buttons.any_pressed: return None
        # InputManager names are documented by the official helper library.
        for index in range(7):
            if self.buttons.was_pressed(index):
                name = self.buttons.button_name(index).lower().replace(" ", "_")
                # The physical Back key is the leftmost under-display key.
                # The two side keys are additional menu navigation controls.
                return {"back": "left", "left": "button_3", "right": "button_4", "power_button": "power"}.get(name, name)
    def sleep(self):
        import alarm; self.display.sleep(); alarm.light_sleep_until_alarms()
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
