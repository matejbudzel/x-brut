#!/bin/sh
# Flash only the MicroPython application partition, restore the validation
# app, and reboot normally.  Bootloader and partition table are untouched.
set -eu

PORT=${1:-/dev/ttyACM0}
IMAGE=/build/micropython-x4/ports/esp32/build-XBRUT_X4/micropython.bin

/build/idf-python/bin/python -m esptool --port "$PORT" --baud 460800 \
    write-flash 0x10000 "$IMAGE"
mpremote connect "$PORT" fs cp native/micropython/app/main.py :
mpremote connect "$PORT" fs cp native/micropython/app/xbrut_input.py :
# USB Serial/JTAG reset keeps the command attached after reset; bound it.
timeout 5s mpremote connect "$PORT" exec "import machine; machine.reset()" || true
