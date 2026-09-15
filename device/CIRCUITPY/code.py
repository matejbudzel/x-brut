"""Stable X Brut recovery entrypoint. Keep this file small and OTA-immutable."""
import sys

sys.path.append("/base")
from boot import run

run()
