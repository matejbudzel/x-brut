# Web settings on the X4

Wi-Fi stays off at normal boot. Start a settings session from Settings:

- **AP MODE** creates the configured WPA2 hotspot (default SSID `x-brut`).
  The screen shows its password and gateway URL, normally
  `http://192.168.4.1/`. Connect a phone/computer to that hotspot and open the
  displayed URL.
- **WEB SETTINGS** connects to the saved Wi-Fi network and displays the X4's
  assigned URL. Open it from another device on that network. If no SSID is
  saved, use AP mode to enter the Wi-Fi credentials first.

Both modes serve exactly the same page and API on port 80. **Back** ends the
session and returns to the selected Settings action. Long Back ends it and
returns Home. Neither mode connects automatically at boot.

The page retains the existing Wi-Fi/AP fields, manifest and splash URLs,
logging level, document URLs, and OPDS feeds. Save persists base configuration
in `/sd/base-conf.json` and project configuration in `/sd/project-conf.json`.
The generated AP password is persisted on SD too. If SD is unavailable, the
AP can use temporary credentials to expose the read-only page; saving remains
disabled. Network/SSID/password edits take effect on the next settings session,
so saving a form does not disconnect the request that submitted it.

## Shared service and lifecycle

`xbrut_web.WebSettings` owns a `SettingsStore`, a lazily initialized
`xbrut_network.Radio`, and a single `xbrut_http.Server`. The server binds all
local interfaces; AP and station addresses use the same routes:

- `GET /`: the shared settings page, staged from `ap_page.HTML` into the
  read-only application asset `/base/settings.html`.
- `GET /api/settings`: settings plus `storage_available`.
- `POST /api/settings`: validate JSON and persist owned configuration keys.

An existing station connection on the shared Radio is reused. Closing a
settings session switches off only interfaces that session started; a
connection owned by another feature can remain active, with the same HTTP
listener. Future OTA/download callers should share this Radio/service rather
than creating separate networking/server implementations. Those callers are
not implemented by this change.

Station connection is asynchronous, with a 20-second deadline. The app polls
the radio and HTTP listener alongside input and display readiness. HTTP reads
and short writes are nonblocking, with two concurrent clients, 512-byte
transfer steps, 2 KiB headers, an 8 KiB request body limit, and a 10-second
client deadline. Invalid/oversized requests and non-JSON settings posts return
an error; passwords and request bodies are not logged. Interfaces and sockets
are released on Back and on exit to the serial REPL.

The page is read from flash in 512-byte chunks. It is never imported as a
large Python literal on the device. Response files close on completion,
disconnect, timeout, and session shutdown. A request allocation failure returns
503 when possible and releases that client; it does not shut down Wi-Fi or
the listener. Request diagnostics record exception types, without contents.

The existing synchronous e-paper rendering and SD configuration writes remain
small blocking operations. The server does not add a thread or an independent
blocking request loop.

## Development and verification

```sh
tools/validate.sh
python3 run_simulator.py --portrait
```

In the portrait simulator, selecting either mode starts the same HTTP service
on port 8001 (configurable with `--ap-host`/`--ap-port`). Wi-Fi interfaces are
simulated, and settings persist under `.simulator/`. The original simulator
remains available without `--portrait`.

Local tests cover strict WLAN signatures, generated credentials, SD-only
persistence, schema validation before writes, missing credentials, connection
failure/timeout, reuse of another feature's connection, session cleanup,
fragmented HTTP, short writes, slow clients, limits, and navigation. Transport
fakes also reproduce MicroPython's errno values and lack of bytearray slice
deletion, fragmented-heap allocation failures, and streamed-file cleanup.
A host HTTP smoke test exercises the real socket stack and shared
controller/page/API.

This feature uses Python files only and requires no new firmware build.
The portrait staging command includes the shared page and all server/radio
modules. On gate, deployment artifacts are retained under
`/home/matej/.local/share/xbrut-deploy/20261102-web-settings/`.

On 2026-11-02, 93 local tests and Pyright passed. The X4 smoke test verified
WPA2 AP startup at `192.168.4.1`, the 3,974-byte settings page, GET and POST on
the real HTTP/socket stack, SD persistence, and Back shutting down the AP and
listener. It used a TCP client on the X4 against its own AP address; this does
not replace testing from a phone or testing DHCP/authentication on a home
network. Free MicroPython heap was about 57 KB with the AP active and 53 KB
after the complete page/API sequence. The normal app was restarted afterwards.

## Save feedback and browser checks

The form disables Save while loading or saving. It shows validation/network
failures explicitly and reads `/api/settings` back before displaying
**Saved and verified**. Reload the page after an app update to get the new
form. Keep the settings session open until this confirmation appears, then
Back out and reopen the desired network mode to apply SSID/password changes.
Home Wi-Fi credentials and hotspot credentials are separate fields; the
hotspot password must contain at least eight characters.

An optional real-browser regression test is available with Playwright and
Chromium installed in a development environment:

```sh
python3 tools/smoke-web-settings-browser.py
# Or select an existing Chromium executable:
python3 tools/smoke-web-settings-browser.py --executable /path/to/chromium
```

It uses temporary data, disables Object.fromEntries to emulate older WebViews,
checks save/readback and reload persistence, and forces a network failure to
verify visible errors and a usable retry button. It prints no credentials.
The X4 full-form smoke also verified SD persistence and actual hotspot rename;
the original device settings were restored after that temporary test.

## Full-application memory checks — 2026-11-02

The full portrait application reproduced a first-request failure while
compiling `ap_page.py`: about 55 KB of free GC heap could not satisfy a
3.6 KB contiguous allocation. Earlier isolated server checks did not reproduce
that application heap. The staged HTML asset removes this allocation.

`main.create_runtime()` constructs the normal application for hardware probes,
so checks can exercise its actual imports, display, controls, and settings
service together. Module precompilation is available through the staging
tool's `--mpy-cross` option to avoid source-compiler peak allocations consuming
native memory needed by Wi-Fi/lwIP. Use a compiler matching the installed
MicroPython version. No firmware flash is involved.

External page-transfer tests also exposed very little native free memory
(roughly 8 KB before a request, less during it) and weak station signal
around -82 dBm. Transfers remained intermittent even with TCP_NODELAY or
station power saving disabled; neither workaround is included. The bytecode
payload is built but its deployment and full-app verification are pending
because SSH to gate became unreachable. Local validation passed 107 tests,
Pyright, and the Chromium form regression.
