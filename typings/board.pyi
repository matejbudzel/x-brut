"""Xteink X4 board members from circuitpython-stubs 10.3.0."""

import busio
import displayio
import microcontroller

board_id: str
BUTTON: microcontroller.Pin
BUTTON_ADC_1: microcontroller.Pin
BUTTON_ADC_2: microcontroller.Pin
DISPLAY: displayio.EPaperDisplay
EPD_BUSY: microcontroller.Pin
EPD_CS: microcontroller.Pin
EPD_DC: microcontroller.Pin
EPD_RESET: microcontroller.Pin
SD_CS: microcontroller.Pin

def SPI() -> busio.SPI: ...
