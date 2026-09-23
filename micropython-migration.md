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
network/OPDS. Keep the validation browser as a smoke app until equivalent
coverage exists in the migrated application.
