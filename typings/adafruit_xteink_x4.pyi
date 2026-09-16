"""Used X4 helper API from Adafruit_CircuitPython_Xteink_X4 1.0.2."""

import microcontroller


class InputManager:
    BTN_BACK: int
    BTN_CONFIRM: int
    BTN_LEFT: int
    BTN_RIGHT: int
    BTN_UP: int
    BTN_DOWN: int
    BTN_POWER: int

    def __init__(
        self,
        adc_pin_1: microcontroller.Pin | None = None,
        adc_pin_2: microcontroller.Pin | None = None,
        power_pin: microcontroller.Pin | None = None,
        debounce: float = 0.05,
    ) -> None: ...

    @property
    def any_pressed(self) -> bool: ...

    @property
    def power_button_pressed(self) -> bool: ...

    def update(self) -> None: ...
    def deinit(self) -> None: ...
    def was_pressed(self, button_index: int) -> bool: ...

    @staticmethod
    def button_name(button_index: int) -> str: ...
