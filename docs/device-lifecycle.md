# Power and reload

The portrait app connects the power key and Settings lifecycle actions to the
device backend:

- **Power / Sleep:** close network services, show the sleeping splash, wait for
  the panel update to settle and all initiating buttons to be released, flush
  filesystems, then enter MCU deep sleep. The existing native X4 helper uses
  GPIO3 low as the power-key wake source. Wake starts the normal app again.
- **Soft reload:** close services, show a restarting screen, settle the panel,
  wait for button release, flush filesystems, then call `machine.soft_reset()`.
  This restarts the Python interpreter and application.
- **Hard reload:** use the same preparation, then call `machine.reset()` to
  restart the MCU. Neither reload erases firmware, app files, or SD settings.

A power key still held during wake/startup is suppressed until released, so
waking cannot immediately request sleep again. Other navigation events are
ignored while a lifecycle transition is pending. Stable release is required
for 50 ms after the debounced input state reports all keys released.

`xbrut_lifecycle.Lifecycle` queues these actions. `Runtime` only executes them
when the deferred UI has no pending paint and the native presenter reports
ready (including old-frame synchronization). The existing display transport,
waveforms, and firmware sleep function are unchanged. Filesystem sync and
shutdown failures show a recoverable device-action error rather than an
unavailable placeholder.

The desktop preview uses the same queue but simulates sleep and resets. It
keeps the sleeping screen until the next power click. Real deep sleep does
not retain Python state; the power button wakes a fresh app boot.

## Verification

`tools/validate.sh` covers the actual lifecycle queue, distinct reset API calls,
frame readiness, stable release, queued-input suppression, failure recovery,
network shutdown (including interfaces another feature owns), and a power key
held across startup. No firmware rebuild is needed for this Python change.

On 2026-11-02, the X4's actual Soft reload and Hard reload actions produced an
interpreter soft-reboot marker and an ESP32 hardware-reboot marker respectively,
followed by normal app startup without traceback. The power action reached
the existing native deep-sleep function without returning or raising an error.
Physical GPIO wake confirmation is recorded separately when available.

Test scripts/payloads are retained on gate under
`/home/matej/.local/share/xbrut-deploy/20261102-lifecycle/`. Serial diagnostics
must let active display updates settle or perform a normal hardware reset
before a new test; interrupting the application can leave a pending native
frame that intentionally times out if not serviced.
