"""Stable X Brut recovery entrypoint. Keep this file small and OTA-immutable."""
import sys

sys.path.append("/base")
from xbrut_storage import mount_sd

# The X4 display and microSD share its only user SPI peripheral. Mounting first
# lets the hardware adapter rebuild the display on that same, lockable bus.
mount_sd()
from boot import run

run()
