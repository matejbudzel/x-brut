#!/bin/sh
# Rebuild the X Brut X4 MicroPython application image in the shared /build
# checkout.  Toolchains and generated build output deliberately stay outside
# this repository.
set -eu

BUILD_ROOT=/build/micropython-x4
BUILD_DIR="$BUILD_ROOT/ports/esp32/build-XBRUT_X4"
export PATH=/build/esp-idf-micropython/tools:/build/idf-python/bin:/build/idf-tools-micropython/tools/riscv32-esp-elf/esp-14.2.0_20260121/riscv32-esp-elf/bin:$PATH
export PYTHONPATH=/build/idf55-python
export IDF_PATH=/build/esp-idf-micropython
export IDF_TOOLS_PATH=/build/idf-tools-micropython
export IDF_PYTHON_ENV_PATH=/build/idf-python
export PYTHON=/build/idf-python/bin/python
export TMPDIR=/build/tmp

exec ninja -C "$BUILD_DIR" -j1
