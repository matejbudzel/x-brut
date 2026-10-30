# X Brut recovery plan — 2026-10-30

## Recommendation

Finish the MicroPython migration around the last user-confirmed working
landscape browser. Preserve the CircuitPython application as a source of
reader/UI behavior. Archive the competing display experiments before further
implementation. The immediate product target is an offline portrait reader;
networking and OTA follow once that reader works reliably on the X4.

This is a repository and session review, not a device certification. No X4 was
connected, no firmware was built or flashed, and existing unfinished code was
left intact.

## Recovered checkpoint

The September 18–19 session chose MicroPython after CircuitPython memory and
hardware integration problems. The September 19–24 migration session records
substantial display experiments, including several cases where successful
serial commands did not produce a visible update.

The strongest checkpoint is the user's September 24 15:38 UTC confirmation,
"yes, it's good", after restoring the landscape SD browser. Earlier feedback
on September 23 confirmed markedly better RAM-framebuffer performance, with
some remaining rapid-double-press glitches. Portrait experiments after that
earlier checkpoint failed and were rolled back.

The final session then ported and serial-tested non-UI modules without
replacing the browser:

- `983fa1b`: MicroPython board/native layer, calibrated input, validation app.
- `0a0682f`: paths, logging, storage, navigation, SD manager.
- `a1d9283`: dependency-injected boot policy, tested with a simulated UI.

The latest commit is therefore a partial application migration. It is not a
completed reader. Session evidence is historical; the currently installed
device image cannot be checked until reconnection.

## Working tree inventory

| Unfinished work | Assessment and proposed disposition |
| --- | --- |
| `AGENTS.md` build instructions | Useful operational guidance; retain. |
| `device/CIRCUITPY/base/hardware.py` | Experimental native presenter integration with regressions; preserve a patch, then restore the CircuitPython baseline in a separate cleanup change. |
| `native/xbrut_epd/`, `patches/circuitpython-xteink-x4-native-epd.patch` | Older CircuitPython display experiment; archive rather than pursue for MVP. It uses fixed refresh delays and the custom fast waveform that the MicroPython migration notes reject. |
| `native/micropython/xbrut_x4/xbrut_x4.c` | Adds white rectangle fill, explicit full presentation, and changes transfer chunks from 1024 to 4092 bytes. Separate useful drawing primitives from transport/presentation experiments; do not treat the whole diff as proven. |
| `native/micropython/base/{main.py,xbrut_hardware.py,xbrut_framebuffer.py,smoke_portrait.py}` | Abandoned portrait diagnostic checkpoint, not the application. Preserve as reference; do not deploy as the default app. |
| `patches/micropython-esp-idf-6-compat.patch` | Earlier IDF 6 experiment. Current MicroPython build script uses an IDF 5.5 environment; establish applicability before retaining it in the supported build recipe. |
| `.tmp-cp-build/`, `.tmp-validate/` | About 4 MiB of old caches, library copies, and staged deployments. Preserve any useful evidence, then remove/ignore deliberately; do not commit as source. |

## What verification actually says

On October 30, `tools/validate.sh` passed: Pyright reported zero errors and all
48 tests passed. `git diff --check` also passed.

A separate headless integration check used a temporary synthetic two-page XTC
and the actual legacy simulator: library → open → next page → back → resume
passed, including expected all-white/all-black packed page output. This did
not exercise the browser frontend or physical display.

Coverage is misleading for the migration: the validation script compiles
`device/CIRCUITPY`, `xbrut`, `tools`, and `tests`; Pyright and the tests exercise
the CircuitPython/simulator path. They do not validate the MicroPython ports,
calibrated input module, native C module, or portrait adapter.

Concrete gaps found:

1. CircuitPython `present_file()` now sets black pixels without clearing white
   ones. Reproduced with the existing strict hardware fakes: draw pixel (0,0),
   present an all-white file, and the output byte remains `0x80` instead of
   `0x00`. Existing tests start with an empty frame and miss this transition.
2. CircuitPython full-frame presentation changed from row writes to per-pixel
   file operations. An all-black frame can perform 384,000 read/modify/write
   operations. This is a performance regression by inspection; no device
   timing was measured. The optional native path is also untested, and its
   file-open failure path tries to use `self.display` when it is `None`.
3. The portrait MicroPython adapter forces a blocking full refresh every time.
   Its diagnostic loop cannot poll buttons during that call. This abandons
   the async behavior responsible for the browser's improved responsiveness.
4. That adapter lacks `present()` for reader pages and `button()` for normalized
   controls. Its tiny framebuffer/font module does not implement the full
   existing UI API. Copying the base UI onto it will not complete the port.
5. Simulator orchestration, CircuitPython boot, and `BootController` currently
   have separate control flows. The simulator does not exercise the migrated
   controller. A working simulator is therefore limited evidence for the X4.
6. The MicroPython browser indicates power-button state but does not implement
   the requested sleep/wake product flow. A native sleep function alone does
   not establish that flow works.
7. Build/deploy reproducibility needs work. The build script only invokes
   Ninja in an existing `/build` checkout; it does not bootstrap/configure it.
   Its current cache points to a board copy under `/build`, while the native
   module points to this repository. The deploy script flashes firmware and
   copies only the validation app/input module, not the migrated base. The
   README and `tools/smoke-x4.py` still describe/check CircuitPython.

## Ordered implementation milestones

### 1. Preserve and document one baseline

Save the unfinished source patches/files explicitly, without committing
caches. Split cleanup from functional changes. Make the supported runtime,
entrypoint, deployment payload, and experimental files explicit in the README
and migration notes. Pin the upstream MicroPython/IDF revisions and record the
board/native sources and clean-build requirements. The currently available
MicroPython checkout is `11094eaaaed1417f8be01c317c1ac6feba160831`.

Provide an application-only MicroPython upload path that selects an explicit
payload and leaves firmware alone. Keep firmware deployment separate. Add a
MicroPython smoke command rather than applying the CircuitPython checker to it.

**Gate:** supported firmware can be traced to source/configuration, and the
installed entrypoint/modules can be read back and identified after upload.
Verify the historical browser on reconnection before replacing it.

### 2. Complete and test the portrait drawing boundary

Use the proven native RAM framebuffer and presenter. Keep physical 800×480
panel transfer/waveform behavior unchanged while testing portrait coordinates.
Implement clipped rectangles, bitmap blits, text, and complete frame replacement
for the 480×800 application surface. Define polarity and rotation explicitly:
application bit 1 is black, native frame bit 0 is black; portrait (x,y) maps to
physical (y,479-x). Avoid per-pixel SD access. Measure Python/native call cost
before deciding which drawing operations need batching.

Add a desktop native-module fake that records the physical bitmap, then compare
its inverse-rotated output with the legacy simulator for asymmetric corner
markers, text, white erasure, and consecutive different pages. Test the actual
adapter, including required API methods, rather than duplicating its formulas.

**Gate:** identical logical images locally; on hardware, correct upright text
and all four corners, followed by black→white→text→different-text transitions.
Serial completion is not visual acceptance. Panel-driver experiments, if
needed, get a separate isolated diagnostic and rollback.

### 3. Build one responsive application loop

Share the portable controller/action logic with the simulator. Add a calibrated
physical-button → logical-action adapter with press/release, debounce, and
short/long Back behavior. Keep input polling active during panel BUSY. Update
application state immediately, coalesce pending display requests, and render
only when the native framebuffer is available for modification/RED-RAM sync.

Add deterministic timing tests for bounce, rapid repeated presses, held keys,
long Back, and independent ladders. Exercise the actual MicroPython storage
and boot ports under strict host fakes as part of validation. Log input,
dispatch, render, presentation, BUSY completion, and free heap so delays can
be attributed instead of guessed. Include a defined timeout/error path for a
display that never becomes ready.

**Gate:** several valid presses during one update produce the correct final
selection without lost actions, a stuck key, or mutation of an in-flight frame.
Proposed hardware target: input dispatch within 100 ms while BUSY; measure
render and panel times separately and investigate multi-second software stalls.

### 4. Deliver the offline reader vertical slice

Port/reuse existing library, XTC/XTH decoding, and bookmarks. Load files from
`/sd/xviewer-docs`; do not require a configured download URL. Start with text
tiles and defer synchronous thumbnail generation until the core path works.
Implement open, next/previous, Back to library, retained library focus, and
resume after restart. Keep all durable mutable state under `/sd`.

Use synthetic and representative real documents. Test truncated/unsupported
files, empty library, missing SD, first/last pages, and switching between books.
Profile on-device heap: current decoders can hold both a 48 KiB intermediate
and a 48 KiB result in addition to the native framebuffer. Stream or reuse
buffers where measurements show it is necessary.

**Gate:** cold boot → library → read many pages → switch books → restart →
resume succeeds repeatedly; a bad file returns to a usable library with an
error. Rapid navigation remains usable while rendering.

### 5. Close the device lifecycle, then expand features

Render a sleep screen, wait for initiating power-key release, persist position,
sleep, wake, and resume. Handle unavailable SD visibly without mutable writes
to internal flash. Verify logs remain bounded and memory does not trend down
across repeated reading sessions.

**MVP acceptance:** repeat the complete offline reading flow, a sustained
page-turn run (proposed 100 turns), and 10 sleep/wake cycles on the real X4
without blank/stale output, lost ordinary button presses, crashes, or lost
bookmarks. Fast refresh must be visually acceptable on both sparse text and
dense pages. These are proposed acceptance checks, not results already obtained.

Then restore settings/AP Wi-Fi, streamed downloads, OPDS, OTA, thumbnails,
chapter menus, and battery calibration incrementally. Current downloads buffer
the entire document in RAM, so a streaming-to-SD path should precede real book
download testing.

## Best next task while the X4 is disconnected

Prepare milestones 1–3 locally: preserve experiments, establish the supported
payload/build record, test the portrait adapter against the legacy framebuffer,
and connect the shared controller to a fake busy display and calibrated input.
Keep the current hardware browser available as a recovery payload. The next
device session should start with a short visual/interaction acceptance sequence,
not a speculative firmware rewrite.
