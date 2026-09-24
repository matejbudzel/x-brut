# X Brut X4 MicroPython baseplane

## Status

The X4 now has a real-device validated MicroPython baseplane. The next phase
is to port the Python base and application layers; do not restart hardware
bring-up or the earlier CircuitPython experiment.

Validated on `/dev/ttyACM0`:

- Custom `XBRUT_X4` firmware, USB Serial/JTAG REPL, battery ADC, USB-present,
  power button, and two calibrated ADC button ladders.
- Shared SPI2 safely alternates SSD1677 panel and SD card. Mount the card with
  `os.mount(os.VfsFat(xbrut_x4.SDCard()), "/sd")`.
- Full first frame, BUSY-synchronised fast differential updates, and RED-RAM
  previous-frame synchronisation.
- One native 48 KiB RAM framebuffer; the panel RED RAM is the old frame.
- Asynchronous fast presentation keeps ADC polling active during panel BUSY,
  coalescing rapid UI changes rather than dropping them.

## Source layout

- `native/micropython/boards/XBRUT_X4/`: board configuration and frozen
  manifest; stock `machine.SDCard` is disabled.
- `native/micropython/xbrut_x4/`: native SPI/SD/panel/GPIO/ADC/framebuffer
  module.
- `native/micropython/app/`: validation browser and calibrated input decoder.
- `native/micropython/base/`: incremental MicroPython ports of base modules.
- `tools/build-micropython-x4.sh`, `tools/deploy-micropython-x4.sh`: build and
  app-partition deployment commands.

`/build/micropython-x4` is a build checkout, not source of truth. It must be
configured to consume the board and user-module directories above.

## Hardware contract

| Function | GPIO |
| --- | ---: |
| Panel SCK / MOSI / CS / DC / RST / BUSY | 8 / 10 / 21 / 4 / 5 / 6 |
| SD MISO / CS (shared SCK/MOSI) | 7 / 12 |
| Power button | 3 |
| Button ladders, left / right | ADC1 / ADC2 (GPIO1 / GPIO2) |
| Battery ADC | ADC0 (GPIO0) |
| USB present | 20 |

Ladder calibration is durable SD state at `/sd/button-calibration.json`.

## Build and deploy

All toolchains and output stay on `/build`:

```sh
tools/build-micropython-x4.sh
tools/deploy-micropython-x4.sh /dev/ttyACM0
```

Deployment writes only the MicroPython application image at `0x10000`,
verifies its hash, restores the validation app, and leaves bootloader and
partition table untouched. Run `TMPDIR=$PWD/.tmp-validate tools/validate.sh`
before deploying Python changes.

When adding or removing a native-module public name, perform a clean firmware
build before flashing (`ninja -C /build/micropython-x4/ports/esp32/build-XBRUT_X4
-t clean`). MicroPython's generated QSTR/module registry otherwise can become
out of sync with old objects; the symptom is standard imports resolving to an
unrelated module (for example `import os` becoming `osdebug`).

## Display rules

- First frame after boot is full two-plane refresh.
- Use the controller's normal monochrome differential waveform (`0x1c`), not
  the extracted custom `0x0c` LUT, which corrupts sparse text transitions.
- BUSY is active high; fixed delays are invalid.
- Render only after `framebuffer_ready()` completes RED-RAM synchronisation.
- Durable mutable state belongs on `/sd`; the active framebuffer is transient
  native RAM.

## Porting next

Retain application logic in Python and port it incrementally onto `xbrut_x4`:
storage/path plumbing, input adaptation, navigation/UI, reader formats, then
network/OPDS. The initial storage/path/log/navigation/SD-tree adapters are in
`native/micropython/base/` and have been serial-tested against the X4 SD card.
`xbrut_boot.py` also carries the portable boot policy: project loading, route
history, and normalized button-to-action handoff. The concrete UI, display,
sleep, reload, and network operations remain platform-specific callers.

Keep the validation browser as the active device smoke app until equivalent
portrait UI coverage exists. The current native landscape renderer is known
good; the separate portrait adapter is intentionally not the boot app yet and
must not prompt further panel-driver changes without an isolated hardware
diagnostic.
