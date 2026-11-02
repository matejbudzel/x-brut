# Portrait and input checkpoint

The unfinished experiments from September are preserved at
[`archive/pre-mvp-experiments-2026-10-30`](https://github.com/matejbudzel/x-brut/tree/archive/pre-mvp-experiments-2026-10-30),
including the original recovery review. Main starts from the last confirmed
landscape browser and adds the portrait/application boundary. Portrait rendering and
Settings navigation have been confirmed on the real X4; reader and lifecycle
acceptance remain outstanding.

## What changed

- `xbrut_hardware.X4Platform` maps a 480×800 logical surface onto the native
  800×480 buffer. Application bits are 1=black; physical bits are 0=black.
  Portrait (x,y) maps to physical (y,479-x). Rectangles clip before rotation;
  native bitmap blits clip and rotate without per-pixel Python/native calls.
- Native `framebuffer_fill_rect` supports white erasure, and
  `framebuffer_blit_portrait` supports packed transparent monochrome bitmaps.
  Full presentation clears before loading; consecutive pages replace old bits.
- Shared `Framebuffer` uses native rectangle and bitmap operations for text
  and outlines. Shared `BaseUI(deferred=True)` updates its model immediately
  and stores only the latest screen request. Existing callers remain immediate.
- `Runtime` polls/dispatches controls before checking panel readiness. It paints
  only after `framebuffer_ready()` completes old-frame synchronization. A stalled
  display latches an error and prevents further rendering; state/input remain
  processable. Device entry reports the error over serial and exits.
- Calibrated input retains the browser's raw transition API. `Actions` adds
  logical mapping, debounced power, and mutually exclusive short/long Back.
  A held key emits once; there is no automatic repeat. Per-button acceptance
  ranges are precomputed instead of sorted on every ADC poll.
- The same migrated controller/runtime and deferred UI run in the portrait
  simulator. Settings preserves the library selection when returning Back.
- SD mount failure now leaves storage unavailable even if `/sd` exists as a
  directory. Storage rejects path traversal instead of checking only a prefix.

The panel transfer/chunk size and full/fast waveform commands are unchanged.
The existing first full refresh is synchronous, as are rendering and SPI
transfers. Input stays live during asynchronous panel BUSY between renders;
this is not a claim that all work is preemptible. On-device rendering latency
and memory still need measurement.

## Local validation

```sh
tools/validate.sh
python3 run_simulator.py --portrait
```

The validation command needs a host C compiler (`cc`). Tests compile the actual
production `raster.h` into a temporary shared library, use it behind a strict
native API fake, and compare inverse-rotated frames with the shared simulator.
They cover corners, erasure, clipping, non-byte-aligned blits, consecutive full
frames, text/UI equivalence, debounce and clock wrap, rapid presses during
BUSY, Back/history, timeout/fault behavior, migrated SD/logging, and staged
payload contents. CircuitPython Pyright/API tests still run as before.

The preview uses `.simulator/xviewer-docs/` filenames as library tiles. It
simulates 250 ms BUSY. Buttons update model state during this interval; the
latest selection is painted when ready. HTTP button handling only enqueues
events; one loop owns UI state and painting. SD/battery controls are disabled
in this preview. The original simulator remains available without `--portrait`.

## Explicit payloads

Stage into a new empty directory:

```sh
python3 tools/stage-micropython.py --app portrait --output .tools/portrait-payload
python3 tools/stage-micropython.py --app browser --output .tools/browser-payload
# Recommended for the X4's limited RAM; use its matching compiler:
python3 tools/stage-micropython.py --app portrait --output .tools/portrait-bytecode \
  --mpy-cross /build/micropython-x4/mpy-cross/build/mpy-cross
```

This only creates host files. It never touches a device. The portrait payload
contains the migrated base, shared UI/font, input adapter, and an opt-in
`main.py`. The browser payload contains the historical validation app and
input decoder. Existing firmware deployment still selects the browser.

The portrait payload requires firmware with the new drawing APIs. An older
image can continue running the browser, but cannot run this portrait adapter.
A clean firmware build is required after changing native public names:

```sh
ninja -C /build/micropython-x4/ports/esp32/build-XBRUT_X4 -t clean
tools/build-micropython-x4.sh
```

All build/toolchain output stays under `/build`. Do not flash firmware merely
to upload Python files. Once compatible firmware has been deliberately
installed, an application-only upload can copy the staged `base/` and input
files with `mpremote`, then copy the selected `main.py` last and reset. Read
back the entrypoint and critical modules before evaluating the display. Keep
the staged browser payload available for rollback.

With `--mpy-cross`, modules are staged as `.mpy` files while the boot
entrypoint remains `main.py`. Verify the uploaded bytecode before removing
the corresponding old `.py` files: source files take precedence on import.
The settings page is an immutable `base/settings.html` asset streamed from
flash; configuration and all other mutable state remain on `/sd`.

The checkpoint scans local document names and supports grid/settings
interaction and the SD file-tree manager. Opening a document and OTA/downloads still return
an unavailable screen; Back returns to the prior route. Implementing the
reader and lifecycle handoffs is the next milestone. The full legacy reader
is available in the default simulator, not this checkpoint.

## Hardware acceptance still required

1. Start with the known browser and confirm the panel and calibrated buttons.
2. Verify four asymmetric portrait corner marks and upright text. Exercise
   black → white → text → different text; serial success is insufficient.
3. Navigate repeatedly while panel BUSY, including two ordinary quick presses,
   a held key, short Back, long Back, and each independent ADC ladder.
4. Open Settings and return to the same library selection. Exercise an empty
   library and an unavailable SD card without enabling internal-flash writes.
5. Collect debug timestamps for input dispatch, render/presentation duration,
   BUSY completion, and heap. Rendering starts after readiness; first full
   refresh remains a measured startup cost. If the panel stalls, recover with
   reset/the browser rather than mutating an in-flight framebuffer.

Do not change the panel driver based solely on portrait composition failures.
Any necessary hardware diagnostic should be isolated and preserve the browser
rollback path. This checkpoint does not establish a usable reader MVP until
reading, bookmarks, and sleep/wake have passed on the X4.

## Deployment on gate — 2026-11-02

The X4 is accessible from the development host with `ssh gate`; its serial
port on that VM is `/dev/ttyACM0`. The VM user belongs to `dialout`.
`esptool` 5.6.0 and `mpremote` 1.29.0 are installed in the isolated environment
`/home/matej/.local/share/xbrut-tools`.

Deployment artifacts and the serial smoke/upload scripts are retained on gate
under `/home/matej/.local/share/xbrut-deploy/20261102-a2ad6a2/`. This includes
the prior boot/input source files, the portrait payload, and the browser
recovery payload. The firmware was built on the development host under
`/build`; no toolchain was installed on gate.

The initial application image (superseded by the initialization fix below)
was from the October 30 clean build of
`a2ad6a2`, SHA-256
`311f0f6f6a31e049913d44f22cdd85b090e67ed7be2bf380678f8103de0b9a9d`.
It was written at `0x10000` only; esptool verified the write. The bootloader,
partition table, application filesystem, and SD data were retained. The 16
portrait application files were uploaded with `main.py` last and checked
against device SHA-256 hashes.

Local validation was rerun successfully (68 tests, zero Pyright errors).
Serial checks on the X4 passed module-registry imports, the required drawing
API, SD mounting (29.1 GiB), six calibrated controls, and Home → Settings →
Home. Warm presentation checks completed in approximately 207/477/215 ms
respectively, with about 105 KB free heap after collection. These durations
are serial/controller observations, not visual confirmation or a cold-start
benchmark. The library directory was empty, so grid navigation was not yet
exercised on hardware. A subsequent normal reboot produced no traceback or
runtime display fault in the captured startup output.

Visible panel output and physical button behavior still require user
confirmation. The reader and sleep/wake handoffs remain unimplemented in this
checkpoint.

### Follow-up: stale image caused by chip-select ownership

The initial visual check failed: the panel retained its old landscape image.
Runtime logs showed that physical button events were reaching Settings and
its actions, so the apparently unresponsive controls were a stale-display
symptom. A standalone native white clear returned in only 124 ms.

The portrait entry mounted SD before constructing `X4Platform`. SD setup
configured the panel chip-select as an SPI output, but the constructor's
subsequent `xbrut_x4.init()` called `gpio_config(GPIO_MODE_OUTPUT)` on that
same pin. ESP-IDF's `gpio_output_enable()` resets the pin's GPIO-matrix output
selection to ordinary GPIO, disconnecting SPI chip-select and leaving it high.
This bypassed the desktop fake, whose native initializer had no GPIO effects.

The fix initializes the platform before mounting SD and makes native init
preserve all panel output pins once SPI owns them. No panel waveform or SPI
transfer code changed. The added regression compiles the production native
initializer with GPIO fakes and checks pin ownership before/after SPI setup.
All 69 local tests and Pyright pass; the incremental firmware build succeeds.

The corrected firmware is retained on gate as `micropython-init-fix.bin`,
SHA-256
`0bb1b084fab20ab58026c0925a51665c67a104707832c28694a5064afbbd0ca9`,
with the corrected boot source as `init-fix-main.py`. The write at `0x10000`
was verified, and the corrected `main.py` was uploaded. A transient serial
stall after the firmware reset was recovered with esptool's USB reset
sequence (`--before usb-reset --after hard-reset chip-id`), without an erase.

The repeated smoke sequence completed Home/Settings/Home in approximately
580/847/589 ms with stable free heap, followed by a normal reboot without a
traceback. The increase over the initial false-positive timings is consistent
with actual panel BUSY activity now being observed. The user subsequently confirmed that Settings navigation works on the panel.
Serial timings alone do not establish image quality.

### SD manager integration — 2026-11-02

Manage SD card now opens the migrated `SDManager` in both the portrait app and
preview, using the same boot controller. The tree is bounded to 50 items and
three directory levels. Side/lower navigation moves focus; OK opens the
existing delete dialog, Back cancels it, and Back from the tree restores the
Settings selection. Long Back returns Home. Card failure returns to read-only
Home. A queued second OK cannot delete an item until the confirmation dialog
has completed presentation.

The update changes Python only; it uses the existing firmware. Local tests
exercise the actual migrated manager through the controller/runtime, including
navigation, empty/unavailable SD, dialog cancellation, and confirmed deletion
of temporary host fixtures. Device verification uses navigation and cancellation
only, without deleting files.

On-device smoke passed with 51 bounded tree rows and approximately 97 KB free
heap while the tree was open: open → move → show delete dialog → cancel → Back
restored the Settings focus. Both updated modules were verified by device
SHA-256 hashes. Deployment artifacts are retained on gate under
`/home/matej/.local/share/xbrut-deploy/20261102-sd-manager/`.

### AP and station web settings — 2026-11-02

AP mode and the new Web settings action now share the settings page/API.
Both start only when selected, show a URL, and stop their session on Back.
See [web settings](web-settings.md) for setup and the shared networking
lifecycle. The app polls HTTP alongside input; no firmware update is required.

The real-device AP/page/API smoke passed over the X4's socket stack; Back
closed the hotspot and listener. The shared transport was also tested from a
host HTTP client. Home-network authentication/DHCP and access from a separate
wireless client remain user acceptance checks (credentials are entered through
the page, not chat).

### Saving feedback and device lifecycle — 2026-11-02

The settings form now shows loading/saving/errors and verifies saved Wi-Fi/AP
values by reading the API back before reporting success. It avoids the newer
Object.fromEntries/FormData conversion dependency, uses explicit named fields,
and displays AP password constraints. A full on-device form round-trip saved
both home Wi-Fi and AP fields to SD, read them back, and reopened the renamed
hotspot through the real WLAN API. Temporary test values were removed and the
original user configuration restored. The user's original failed save could
not be reproduced in current Chrome; testing that browser again remains
necessary, now with visible failure feedback.

Power/Sleep, Soft reload, and Hard reload are now implemented rather than
unavailable handoffs. See [device lifecycle](device-lifecycle.md). Local
validation passed 101 tests and Pyright. An actual Chromium form test passed
save/readback, reload persistence, password validation, an older-browser API
compatibility case, and visible reporting of a dropped request. Both reset
operations were exercised successfully on the X4.
