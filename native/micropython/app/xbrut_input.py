"""Calibrated, debounced X4 ADC-ladder input.

Unknown/out-of-band readings are ignored. The two independent ladders can
report simultaneous presses. Same-ladder chords cannot be identified reliably;
readings outside calibrated single-button ranges are rejected.
"""
import json
import time

DEBOUNCE_MS = 20


class Input:
    def __init__(self, hardware, path="/sd/button-calibration.json", clock=None, config=None):
        self.hardware = hardware
        self.clock = clock or time
        if config is None:
            with open(path) as handle:
                config = json.load(handle)
        self.baseline = config["baseline"]
        self.buttons = config["buttons"]
        self.ranges = {}
        for channel in ("left", "right"):
            values = [(name, item["raw"]) for name, item in self.buttons.items() if item["channel"] == channel]
            ranges = []
            for name, raw in values:
                distances = [abs(raw - other) for other_name, other in values if other_name != name]
                tolerance = min(300, min(distances) // 2 - 20 if distances else 300)
                if tolerance <= 0: raise ValueError("button calibration overlaps")
                ranges.append((name, raw, tolerance))
            self.ranges[channel] = ranges
        now = self.clock.ticks_ms()
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
        for name, raw, tolerance in self.ranges[channel]:
            if abs(value - raw) <= tolerance:
                return name
        return None

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
        now = self.clock.ticks_ms()
        changes = []
        for channel in ("left", "right"):
            reading = readings[channel]
            if reading != self.candidate[channel]:
                self.candidate[channel] = reading
                self.candidate_since[channel] = now
                continue
            if self.clock.ticks_diff(now, self.candidate_since[channel]) < DEBOUNCE_MS:
                continue
            if reading != self.active[channel]:
                previous = self.active[channel]
                self.active[channel] = reading
                changes.append((channel, previous, reading))
        return changes, dict(self.active)


class Actions:
    """Physical transitions to logical actions; no auto-repeat or display calls."""
    NAMES = {"lower-2": "confirm", "lower-3": "up", "lower-4": "down",
             "side-1": "up", "side-2": "down"}

    def __init__(self, controls, clock=None, back_ms=700):
        self.controls = controls
        self.clock = clock or time
        self.back_ms = back_ms
        self.back_since = None
        self.back_long = False
        # A key held through wake/reset must be released before it can
        # request sleep again. Deep-sleep wake is level-triggered on the X4.
        self.power_candidate = self.power_active = bool(self.controls.hardware.power_button())
        self.power_since = self.clock.ticks_ms()

    def released(self):
        return (not self.controls.hardware.power_button() and not self.power_active
                and all(value is None for value in self.controls.active.values())
                and all(value is None for value in self.controls.candidate.values()))

    def poll(self):
        changes, _states = self.controls.poll()
        now = self.clock.ticks_ms()
        events = []
        for _channel, previous, current in changes:
            if previous == "lower-1" and current != previous and self.back_since is not None:
                if not self.back_long:
                    events.append("left_long" if self.clock.ticks_diff(now, self.back_since) >= self.back_ms else "left")
                self.back_since = None
                self.back_long = False
            if current == "lower-1":
                self.back_since, self.back_long = now, False
            elif current in self.NAMES:
                events.append(self.NAMES[current])
        if self.back_since is not None and not self.back_long and self.clock.ticks_diff(now, self.back_since) >= self.back_ms:
            self.back_long = True
            events.append("left_long")
        power = bool(self.controls.hardware.power_button())
        if power != self.power_candidate:
            self.power_candidate, self.power_since = power, now
        elif power != self.power_active and self.clock.ticks_diff(now, self.power_since) >= DEBOUNCE_MS:
            self.power_active = power
            if power: events.append("power")
        return events
