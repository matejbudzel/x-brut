# Xteink X4 custom CircuitPython

X Brut currently requires a small CircuitPython patch for reliable microSD
access on the Xteink X4. The display and SD socket share SPI, and the board
uses GPIO12 as SD chip select. Stock ESP32-C3 protection treats that pin as a
flash signal and rejects it, producing `OSError: [Errno 22] Invalid argument`
during SD setup.

The exact patch is maintained in
[`patches/circuitpython-xteink-x4-sd.patch`](../patches/circuitpython-xteink-x4-sd.patch).
It was developed against CircuitPython `0dedbf744a` (`10.4.0-alpha.2`) in the
local `/home/matej/work/own/circuitpython` checkout.

## Build and flash

Apply the patch in a matching CircuitPython checkout, build the `xteink_x4`
board with the normal Espressif build command, and explicitly flash the
resulting firmware. Keep a full flash backup before doing so.

```sh
git apply /path/to/x-brut/patches/circuitpython-xteink-x4-sd.patch
make -C ports/espressif BOARD=xteink_x4
```

Firmware flashing is intentionally outside `tools/install-x4.sh` unless its
caller provides `--force-flash`. Normal X Brut deployment must preserve this
custom firmware and upload only managed application files and libraries.

After an explicit custom-firmware flash, use the normal app-only installer and
run `tools/smoke-x4.py`. The smoke test verifies that `/sd` can be mounted and
written without using internal flash for mutable state.
