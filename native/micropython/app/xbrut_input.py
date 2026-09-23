"""Calibrated, debounced X4 ADC-ladder input.

The two resistor ladders are not capable of unambiguous chords.  This module
therefore emits a press only when exactly one calibrated button is close to
the observed values; simultaneous or unknown readings are deliberately
ignored.
"""
import json
import time

DEBOUNCE_MS = 20


class Input:
    def __init__(self, hardware, path="/sd/button-calibration.json"):
        self.hardware = hardware
        with open(path) as handle:
            config = json.load(handle)
        self.baseline = config["baseline"]
        self.buttons = config["buttons"]
        now = time.ticks_ms()
        self.active = {"left": None, "right": None}
        self.candidate = {"left": None, "right": None}
        self.candidate_since = {"left": now, "right": now}

    def _channel_button(self, channel, value):
        baseline = self.baseline[channel]
        # Treat released and out-of-band values as no button.  The tolerance
        # is also capped below half the nearest pair distance so calibrated
        # neighbours cannot overlap on a normal single-button press.
        if abs(value - baseline) <= 100:
            return None
        options = [(abs(value - item["raw"]), name)
                   for name, item in self.buttons.items()
                   if item["channel"] == channel]
        if not options:
            return None
        distance, name = min(options)
        values = sorted(item["raw"] for item in self.buttons.values()
                        if item["channel"] == channel)
        raw = self.buttons[name]["raw"]
        neighbours = [abs(raw - other) for other in values if other != raw]
        tolerance = min(300, min(neighbours) // 2 - 20 if neighbours else 300)
        return name if distance <= tolerance else None

    def _readings(self):
        _, left, right = self.hardware.adc_raw()
        # These are electrically independent ladders. A valid press on each
        # can be displayed and tracked together. A same-ladder chord usually
        # yields an unknown voltage and is rejected by _channel_button.
        return {"left": self._channel_button("left", left),
                "right": self._channel_button("right", right)}

    def poll(self):
        """Return (changes, states) after independently debouncing ladders.

        ``changes`` contains ``(channel, previous, current)`` entries. The
        current states remain visible while held, so callers can distinguish
        press and release even when a display refresh delays the next sample.
        """
        readings = self._readings()
        now = time.ticks_ms()
        changes = []
        for channel in ("left", "right"):
            reading = readings[channel]
            if reading != self.candidate[channel]:
                self.candidate[channel] = reading
                self.candidate_since[channel] = now
                continue
            if time.ticks_diff(now, self.candidate_since[channel]) < DEBOUNCE_MS:
                continue
            if reading != self.active[channel]:
                previous = self.active[channel]
                self.active[channel] = reading
                changes.append((channel, previous, reading))
        return changes, dict(self.active)
