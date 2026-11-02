"""Lazy ESP32 Wi-Fi interfaces, reusable by settings and later downloads."""


class Radio:
    def __init__(self, network_module=None):
        self.network = network_module
        self.ap, self.station = None, None

    def _module(self):
        if self.network is None:
            import network
            self.network = network
        return self.network

    def start_ap(self, ssid, password):
        module = self._module()
        if self.ap is None:
            self.ap = module.WLAN(module.WLAN.IF_AP)
        self.ap.active(True)
        self.ap.config(ssid=ssid, key=password, security=module.WLAN.SEC_WPA2)

    def connect(self, ssid, password):
        module = self._module()
        if self.station is None:
            self.station = module.WLAN(module.WLAN.IF_STA)
        self.station.active(True)
        self.station.config(reconnects=0)
        self.station.connect(ssid, password)

    def ap_address(self):
        return self.ap.ifconfig()[0] if self.ap is not None and self.ap.active() else None

    def station_address(self):
        if self.station is not None and self.station.active() and self.station.isconnected():
            return self.station.ifconfig()[0]
        return None

    def station_error(self):
        if self.station is None or not self.station.active() or self.station.isconnected():
            return None
        status = self.station.status()
        # ESP32 exposes positive ESP-IDF disconnect reasons too, not just
        # the negative STAT_* values found on other MicroPython ports.
        if status in (self.network.STAT_IDLE, self.network.STAT_CONNECTING, self.network.STAT_GOT_IP):
            return None
        return 'WIFI CONNECTION FAILED'

    def stop_ap(self):
        if self.ap is not None:
            self.ap.active(False)

    def stop_station(self):
        if self.station is not None:
            try:
                self.station.disconnect()
            except OSError:
                pass
            self.station.active(False)
