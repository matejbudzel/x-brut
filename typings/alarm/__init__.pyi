"""Used alarm API from circuitpython-stubs 10.3.0, with pin re-exported."""

from . import pin as pin


def light_sleep_until_alarms(*alarms: pin.PinAlarm) -> pin.PinAlarm: ...
