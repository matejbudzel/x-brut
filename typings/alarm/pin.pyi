import microcontroller


class PinAlarm:
    def __init__(
        self,
        pin: microcontroller.Pin,
        value: bool,
        edge: bool = False,
        pull: bool = False,
    ) -> None: ...

    pin: microcontroller.Pin
    value: bool
