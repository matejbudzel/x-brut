# X Brut

X Brut is a deliberately small CircuitPython base for the Xteink X4.  The base
owns recovery, power, splash, settings, Wi-Fi setup and OTA.  A separately
downloaded `project.py` owns the reader itself; the first project will be an
XTH-only viewer.

## Run the simulator

```sh
python3 run_simulator.py
```

The server binds to all interfaces by default; open `http://<devbox-ip>:8000`
from another device (or `http://127.0.0.1:8000` locally). Pass
`--host 127.0.0.1` to keep it local-only. The page displays the exact portrait 480×800 one-bit frame
buffer served by the portable UI. Button clicks call the same input methods as
the device adapter.

The default development server watches `xbrut/`, `device/`, and `web/`, then
restarts its worker and reloads connected browser tabs after a source change.
Use `--no-reload` to run a single non-watching worker.

Opening **AP MODE** in the simulator also starts the device-settings SPA on
`http://<devbox-hostname>:8001`. Its `base-conf.json` and `base.log` persist in
the ignored `.simulator/` directory, so the next simulator run uses them just
as the device uses its microSD configuration.

## Validate before deployment

Run the x64 validation suite after changing Python code, especially the device
adapter:

```sh
tools/validate.sh
```

On its first run this creates an ignored `.tools/x64-validation` environment.
The command syntax-checks the Python sources, runs Pyright against the X4 board
and CircuitPython APIs, verifies that the real and simulator adapters satisfy
their shared platform contract, and imports/exercises the real
`device/CIRCUITPY/base/hardware.py` with strict desktop hardware fakes.

The desktop checks cannot validate electrical behavior, actual e-paper refresh
timing, radio behavior, wake reliability, memory pressure, or compatibility
with the exact libraries installed on a device. Run the X4 smoke test below as
the final layer before deployment.

## Install on an X4

1. Install the current [Xteink X4 CircuitPython build](https://circuitpython.org/board/xteink_x4/).
2. Insert a FAT-formatted microSD card. X Brut requires it for all mutable data.
3. Copy `device/CIRCUITPY/` to the CIRCUITPY volume.
4. Install the libraries listed in `device/requirements.txt` into `lib/` (use
   `circup install adafruit_xteink_x4 adafruit_requests adafruit_httpserver`).
5. Enter **AP mode** from the base settings and visit the shown address to set
   Wi-Fi and the manifest URL (and optionally a `splash_url`). The system assigns
   the AP address (normally `192.168.4.1` on ESP32).

### One-command first install (Debian)

Plug in the X4 over USB, then run:

```sh
tools/install-x4.sh --yes
```

The script auto-detects its USB JTAG serial port (or accept `--port
/dev/ttyACM0`), installs missing host prerequisites with `apt`, creates an
isolated `.tools/` environment for `esptool`, `pyserial`, and `circup`,
checks for CircuitPython on the X4 first. When found, it replaces only the
managed X Brut application files and libraries over the serial REPL, retaining
CircuitPython and device configuration. Otherwise it downloads the official X4
CircuitPython binary and saves a complete 16 MiB backup under `backups/`
**before** erasing Crosspoint. Pass `--force-flash` to explicitly take that
backup-and-reflash path. This board does not provide a CIRCUITPY USB drive.

Internal flash contains application code and libraries. All X Brut mutable data
lives under `/sd`: `base-conf.json`, `project-conf.json`, logs, downloaded
documents, the splash cache, and the framebuffer scratch file. On the first
boot of base 0.1.2, existing root-level mutable files are copied to the SD card
and removed from flash only after each successful copy. An absent or invalid SD
card is a fatal startup error; X Brut never falls back to writing mutable data
to internal flash.

Verbose logging is enabled by default. AP mode's web settings expose the
overall `log_level`: `debug`, `info`, `error`, or `off`. Log lines include
monotonic time, severity, and subsystem. `/sd/base.log` rotates at 128 KiB,
keeping one older `/sd/base.log.1`; passwords and URL query strings are not logged.
Read the rotated file with:

```sh
tools/read-base-log.py --port /dev/ttyACM0 --path /sd/base.log.1
```

To read the device log without a mounted CIRCUITPY drive:

```sh
.tools/x4-install/bin/python tools/read-base-log.py --port /dev/ttyACM0
```

For a non-destructive hardware smoke test of the installed CircuitPython build,
display object, X4 input helper/button names, wake-alarm construction, and free
heap:

```sh
.tools/x4-install/bin/python tools/smoke-x4.py --port /dev/ttyACM0
```

## OTA manifest

The manifest is JSON. Every item is downloaded to a path relative to the
CIRCUITPY root. `sha256` is optional but strongly recommended.

```json
{
  "version": "2026.09.15",
  "files": [
    {"path": "project.py", "url": "https://example.invalid/project.py", "sha256": "..."},
    {"path": "base/ui.py", "url": "https://example.invalid/ui.py", "sha256": "..."}
  ]
}
```

For a simple home-network deployment, serve this repository directly and set
the device Manifest URL to `http://<host>/ota-manifest.json`. The tracked
manifest uses paths relative to itself, so it downloads the base files from
this repository without editing URLs.

Updates are staged as `.new`, verified, then rotated to `.bak` and installed.
`code.py` is deliberately not updatable: it is the stable recovery entrypoint.
`project.py` has its own `project.py.bak` fallback.

A splash download must be an uncompressed 1-bit BMP. X Brut validates it,
proportionally fits it into the physical 800×480 panel area with white padding,
then rotates and caches the resulting portrait framebuffer as `splash.bin`.
The prior cached splash is retained as `splash.bin.bak` for revert.
