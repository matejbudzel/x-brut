"""Strict, deliberately small CPython fakes for hardware.py dependencies."""

from types import ModuleType


BUTTON_NAMES = ("Back", "Confirm", "Left", "Right", "Up", "Down", "Power")


class Pin:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class SPI:
    __slots__ = ()


class FourWire:
    __slots__ = ("spi_bus", "command", "chip_select", "reset", "baudrate", "polarity", "phase")

    def __init__(self, spi_bus, *, command=None, chip_select=None, reset=None,
                 baudrate=24000000, polarity=0, phase=0):
        if not isinstance(spi_bus, SPI):
            raise TypeError("FourWire requires the shared SPI bus")
        if not all(value is None or isinstance(value, Pin) for value in (command, chip_select, reset)):
            raise TypeError("display control lines must be pins")
        self.spi_bus, self.command, self.chip_select, self.reset = spi_bus, command, chip_select, reset
        self.baudrate, self.polarity, self.phase = baudrate, polarity, phase


class Display:
    __slots__ = (
        "rotation", "root_group", "refresh_count", "width", "height",
        "time_to_refresh", "busy", "configuration",
    )

    def __init__(self):
        self.rotation = 0
        self.root_group = None
        self.refresh_count = 0
        self.width = 800
        self.height = 480
        self.time_to_refresh = 0.0
        self.busy = False
        self.configuration = None

    def refresh(self):
        self.refresh_count += 1


class Palette:
    __slots__ = ()


class OnDiskBitmap:
    __slots__ = ("file", "pixel_shader")

    def __init__(self, file):
        if not isinstance(file, str):
            raise TypeError("file must be a path")
        self.file = file
        self.pixel_shader = Palette()


class TileGrid:
    __slots__ = (
        "bitmap", "pixel_shader", "width", "height", "tile_width",
        "tile_height", "default_tile", "x", "y",
    )

    def __init__(
        self, bitmap, *, pixel_shader, width=1, height=1,
        tile_width=None, tile_height=None, default_tile=0, x=0, y=0,
    ):
        if not isinstance(bitmap, OnDiskBitmap):
            raise TypeError("bitmap must be OnDiskBitmap")
        if not isinstance(pixel_shader, Palette):
            raise TypeError("pixel_shader must be Palette")
        self.bitmap, self.pixel_shader = bitmap, pixel_shader
        self.width, self.height = width, height
        self.tile_width, self.tile_height = tile_width, tile_height
        self.default_tile, self.x, self.y = default_tile, x, y


class Group:
    __slots__ = ("scale", "x", "y", "layers")

    def __init__(self, *, scale=1, x=0, y=0):
        self.scale, self.x, self.y, self.layers = scale, x, y, []

    def append(self, layer):
        if not isinstance(layer, (Group, TileGrid)):
            raise TypeError("unsupported display layer")
        self.layers.append(layer)


class InputManager:
    BTN_BACK = 0
    BTN_CONFIRM = 1
    BTN_LEFT = 2
    BTN_RIGHT = 3
    BTN_UP = 4
    BTN_DOWN = 5
    BTN_POWER = 6

    __slots__ = (
        "pressed_index", "power_held", "deinitialized", "update_count",
        "_current_index", "_pressed_event", "_released_event", "held_seconds",
    )

    instances = []

    def __init__(self, adc_pin_1=None, adc_pin_2=None, power_pin=None, debounce=0.05):
        for pin in (adc_pin_1, adc_pin_2, power_pin):
            if pin is not None and not isinstance(pin, Pin):
                raise TypeError("button pins must be board pins")
        if not isinstance(debounce, (int, float)):
            raise TypeError("debounce must be numeric")
        self.pressed_index = None
        self.power_held = False
        self.deinitialized = False
        self.update_count = 0
        self._current_index = None
        self._pressed_event = None
        self._released_event = None
        self.held_seconds = 0.0
        type(self).instances.append(self)

    @property
    def any_pressed(self):
        return self._pressed_event is not None

    @property
    def any_released(self):
        return self._released_event is not None

    @property
    def current_state(self):
        if self._current_index is None:
            return 0
        return 1 << self._current_index

    @property
    def held_time(self):
        return self.held_seconds

    @property
    def power_button_pressed(self):
        return self.power_held

    def update(self):
        self.update_count += 1
        current = 6 if self.power_held else self.pressed_index
        self._pressed_event = current if current != self._current_index and current is not None else None
        self._released_event = self._current_index if current != self._current_index and self._current_index is not None else None
        self._current_index = current

    def deinit(self):
        self.deinitialized = True

    def was_pressed(self, button_index):
        if not isinstance(button_index, int):
            raise TypeError("button index must be int")
        return self._pressed_event == button_index

    def was_released(self, button_index):
        if not isinstance(button_index, int):
            raise TypeError("button index must be int")
        return self._released_event == button_index

    def is_pressed(self, button_index):
        if not isinstance(button_index, int):
            raise TypeError("button index must be int")
        return self._current_index == button_index

    @staticmethod
    def button_name(button_index):
        if not isinstance(button_index, int):
            raise TypeError("button index must be int")
        return BUTTON_NAMES[button_index] if 0 <= button_index < 7 else "Unknown"


class Radio:
    __slots__ = (
        "connect_calls", "start_ap_calls", "stop_station_count",
        "stop_ap_count", "ipv4_address_ap", "stop_station_error", "stop_ap_error",
    )

    def __init__(self):
        self.connect_calls = []
        self.start_ap_calls = []
        self.stop_station_count = 0
        self.stop_ap_count = 0
        self.ipv4_address_ap = "192.168.4.1"
        self.stop_station_error = None
        self.stop_ap_error = None

    def connect(self, ssid, password):
        if not isinstance(ssid, str) or not isinstance(password, str):
            raise TypeError("credentials must be strings")
        self.connect_calls.append((ssid, password))

    def start_ap(self, ssid, password=b"", *, channel=1, authmode=(), max_connections=4):
        if not isinstance(ssid, (str, bytes)) or not isinstance(password, (str, bytes)):
            raise TypeError("AP credentials must be strings or bytes")
        self.start_ap_calls.append((ssid, password, channel, authmode, max_connections))

    def stop_station(self):
        self.stop_station_count += 1
        if self.stop_station_error:
            raise self.stop_station_error

    def stop_ap(self):
        self.stop_ap_count += 1
        if self.stop_ap_error:
            raise self.stop_ap_error


class SocketPool:
    __slots__ = ("radio",)

    def __init__(self, radio):
        if not isinstance(radio, Radio):
            raise TypeError("SocketPool requires wifi.radio")
        self.radio = radio


class Response:
    __slots__ = ("headers", "chunks", "closed", "error", "iter_calls")

    def __init__(self, chunks, content_length=None, error=None):
        self.chunks = list(chunks)
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self.closed = False
        self.error = error
        self.iter_calls = []

    def iter_content(self, chunk_size=1, decode_unicode=False):
        if not isinstance(chunk_size, int) or decode_unicode is not False:
            raise TypeError("invalid iter_content arguments")
        self.iter_calls.append((chunk_size, decode_unicode))
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class PinAlarm:
    __slots__ = ("pin", "value", "edge", "pull")

    def __init__(self, pin, value, edge=False, pull=False):
        if not isinstance(pin, Pin):
            raise TypeError("PinAlarm requires a board pin")
        if not isinstance(value, bool) or not isinstance(edge, bool) or not isinstance(pull, bool):
            raise TypeError("alarm flags must be bool")
        self.pin, self.value, self.edge, self.pull = pin, value, edge, pull


class HardwareEnvironment:
    def __init__(self):
        InputManager.instances = []
        self.display = Display()
        self.spi = SPI()
        self.button_pin = Pin("BUTTON")
        self.radio = Radio()
        self.responses = []
        self.sessions = []
        self.sleep_alarms = []
        self.storage_writes = []
        self.logs = []

        xbrut_log = ModuleType("xbrut_log")

        def record(level, component, message):
            if not isinstance(component, str) or not isinstance(message, str):
                raise TypeError("log component and message must be strings")
            self.logs.append((level, component, message))

        def debug(component, message): record("debug", component, message)
        def info(component, message): record("info", component, message)
        def error(component, message): record("error", component, message)
        def safe_url(url): return url.split("?", 1)[0]

        xbrut_log.debug = debug
        xbrut_log.info = info
        xbrut_log.error = error
        xbrut_log.safe_url = safe_url

        board = ModuleType("board")
        board.DISPLAY = self.display
        board.BUTTON = self.button_pin
        board.EPD_DC = Pin("EPD_DC")
        board.EPD_CS = Pin("EPD_CS")
        board.EPD_RESET = Pin("EPD_RESET")
        board.EPD_BUSY = Pin("EPD_BUSY")

        displayio = ModuleType("displayio")
        displayio.OnDiskBitmap = OnDiskBitmap
        displayio.Group = Group
        displayio.TileGrid = TileGrid

        fourwire = ModuleType("fourwire")
        fourwire.FourWire = FourWire

        epaperdisplay = ModuleType("epaperdisplay")

        def create_epaper(
            display_bus, start_sequence, stop_sequence, *, width, height,
            ram_width, ram_height, colstart=0, rowstart=0, rotation=0,
            set_column_window_command=None, set_row_window_command=None,
            set_current_column_command=None, set_current_row_command=None,
            write_black_ram_command, black_bits_inverted=False,
            write_color_ram_command=None, color_bits_inverted=False,
            highlight_color=0, highlight_color2=0,
            refresh_display_command, refresh_time=40, busy_pin=None,
            busy_state=True, seconds_per_frame=180,
            always_toggle_chip_select=False, grayscale=False,
            advanced_color_epaper=False, spectra6=False,
            two_byte_sequence_length=False, start_up_time=0,
            address_little_endian=False,
        ):
            if not isinstance(display_bus, FourWire):
                raise TypeError("EPaperDisplay requires FourWire")
            if not isinstance(start_sequence, bytes) or not isinstance(stop_sequence, bytes):
                raise TypeError("display sequences must be bytes")
            if not isinstance(busy_pin, Pin):
                raise TypeError("busy_pin must be a pin")
            self.display.width, self.display.height = width, height
            self.display.rotation = rotation
            self.display.configuration = {
                "bus": display_bus, "ram_width": ram_width, "ram_height": ram_height,
                "write_black_ram_command": write_black_ram_command,
                "black_bits_inverted": black_bits_inverted,
                "refresh_display_command": refresh_display_command,
                "refresh_time": refresh_time, "busy_pin": busy_pin,
                "busy_state": busy_state, "seconds_per_frame": seconds_per_frame,
                "grayscale": grayscale,
                "two_byte_sequence_length": two_byte_sequence_length,
                "address_little_endian": address_little_endian,
            }
            return self.display

        epaperdisplay.EPaperDisplay = create_epaper

        x4 = ModuleType("adafruit_xteink_x4")
        x4.InputManager = InputManager

        wifi = ModuleType("wifi")
        wifi.radio = self.radio

        socketpool = ModuleType("socketpool")
        socketpool.SocketPool = SocketPool

        requests = ModuleType("adafruit_requests")
        environment = self

        class Session:
            __slots__ = ("socket_pool", "ssl_context", "session_id")

            def __init__(self, socket_pool, ssl_context=None, session_id=None):
                if not isinstance(socket_pool, SocketPool):
                    raise TypeError("Session requires a SocketPool")
                self.socket_pool = socket_pool
                self.ssl_context = ssl_context
                self.session_id = session_id
                environment.sessions.append(self)

            def get(
                self, url, *, data=None, json=None, headers=None, stream=False,
                timeout=60, allow_redirects=True, files=None,
            ):
                if not isinstance(url, str):
                    raise TypeError("URL must be a string")
                if headers is not None and not isinstance(headers, dict):
                    raise TypeError("headers must be a dict")
                if not isinstance(stream, bool) or not isinstance(allow_redirects, bool):
                    raise TypeError("request flags must be bool")
                if not isinstance(timeout, (int, float)):
                    raise TypeError("timeout must be numeric")
                if not environment.responses:
                    raise AssertionError("no response queued")
                return environment.responses.pop(0)

        requests.Session = Session

        alarm_pin = ModuleType("alarm.pin")
        alarm_pin.PinAlarm = PinAlarm
        alarm = ModuleType("alarm")
        alarm.pin = alarm_pin

        def light_sleep_until_alarms(*alarms):
            if not alarms or not all(isinstance(item, PinAlarm) for item in alarms):
                raise TypeError("light sleep requires PinAlarm instances")
            self.sleep_alarms.append(alarms)
            return alarms[0]

        alarm.light_sleep_until_alarms = light_sleep_until_alarms

        storage = ModuleType("xbrut_storage")

        def write_json(path, value):
            if not isinstance(path, str) or not isinstance(value, dict):
                raise TypeError("invalid storage write")
            self.storage_writes.append((path, dict(value)))

        storage.write_json = write_json
        storage.shared_spi = lambda: self.spi
        storage.SDCardUnavailable = type("SDCardUnavailable", (RuntimeError,), {})

        paths = ModuleType("xbrut_paths")
        paths.BASE_CONFIG_PATH = "/sd/base-conf.json"
        paths.FRAME_PATH = "/sd/.xbrut-frame.bmp"

        self.modules = {
            "board": board,
            "displayio": displayio,
            "epaperdisplay": epaperdisplay,
            "fourwire": fourwire,
            "adafruit_xteink_x4": x4,
            "wifi": wifi,
            "socketpool": socketpool,
            "adafruit_requests": requests,
            "alarm": alarm,
            "alarm.pin": alarm_pin,
            "xbrut_storage": storage,
            "xbrut_log": xbrut_log,
            "xbrut_paths": paths,
        }

    def queue_response(self, chunks, content_length=None, error=None):
        response = Response(chunks, content_length, error)
        self.responses.append(response)
        return response
