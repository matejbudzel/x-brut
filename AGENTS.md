# Repository validation

Run `tools/validate.sh` before deployment after changing Python code. Changes
under `device/CIRCUITPY`, especially `base/hardware.py`, must pass the Pyright
CircuitPython API check and the strict x64 hardware-adapter tests in that command.

`tools/smoke-x4.py` is the final, non-destructive check on a connected X4; it
does not replace local validation.

Agents may commit directly to `main` and push `origin main` after validation.
When an X4 is available on `/dev/ttyACM0`, agents may deploy the requested
device-code change and run the smoke test without asking again. Prefer the
app-only serial deployment path; never erase or reflash firmware unless the
user explicitly requests it. If host `/tmp` is full, create an ignored
workspace temporary directory and invoke validation with `TMPDIR` set there.

## X4 firmware builds

The host root filesystem and `/tmp` are intentionally space-constrained. Use
the `/build` virtual disk for all CircuitPython firmware builds: it has the
working ESP-IDF toolchain in `/build/idf-tools`, its Python environment in
`/build/idf-python`, and the reusable X4 build directory in
`/build/circuitpython-x4`. Build with `PATH=/build/idf-tools/tools/riscv32-esp-elf/esp-15.2.0_20251204/riscv32-esp-elf/bin:/home/matej/.local/bin:$PATH`,
`IDF_TOOLS_PATH=/build/idf-tools`, `PYTHON=/build/idf-python/bin/python`,
`TMPDIR=/build/tmp`, and `BUILD=/build/circuitpython-x4`. Do not put ESP-IDF
downloads, toolchains, or firmware build artefacts under the repository or
`/tmp`.

Internal CircuitPython flash is for application code and libraries. Keep all
X Brut-managed mutable state under the microSD `/sd` mount via
`device/CIRCUITPY/base/xbrut_paths.py`; never add a fallback that writes logs,
configuration, downloads, splash data, or framebuffer scratch files to `/`.
