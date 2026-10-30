# Portrait and input checkpoint

The unfinished experiments from September are preserved at
[`archive/pre-mvp-experiments-2026-10-30`](https://github.com/matejbudzel/x-brut/tree/archive/pre-mvp-experiments-2026-10-30),
including the original recovery review. Main starts from the last confirmed
landscape browser and adds the portrait/application boundary. This checkpoint
has no real-device acceptance yet.

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

The checkpoint scans local document names and supports grid/settings
interaction. Opening a document, networking, reload, and sleep still return
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
