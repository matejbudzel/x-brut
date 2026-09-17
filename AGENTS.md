# Repository validation

Run `tools/validate.sh` before deployment after changing Python code. Changes
under `device/CIRCUITPY`, especially `base/hardware.py`, must pass the Pyright
CircuitPython API check and the strict x64 hardware-adapter tests in that command.

`tools/smoke-x4.py` is the final, non-destructive check on a connected X4; it
does not replace local validation.

Internal CircuitPython flash is for application code and libraries. Keep all
X Brut-managed mutable state under the microSD `/sd` mount via
`device/CIRCUITPY/base/xbrut_paths.py`; never add a fallback that writes logs,
configuration, downloads, splash data, or framebuffer scratch files to `/`.
