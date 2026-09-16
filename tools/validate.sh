#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="$ROOT/.tools/x64-validation"
REQUIREMENTS="$ROOT/requirements-dev.txt"
STAMP="$ENVIRONMENT/.requirements"
EXPECTED="$(sha256sum "$REQUIREMENTS" | cut -d' ' -f1)"

if [[ ! -x "$ENVIRONMENT/bin/python" ]]; then
  python3 -m venv "$ENVIRONMENT"
fi
if [[ ! -f "$STAMP" ]] || [[ "$(<"$STAMP")" != "$EXPECTED" ]]; then
  "$ENVIRONMENT/bin/python" -m pip install --upgrade pip
  "$ENVIRONMENT/bin/python" -m pip install --requirement "$REQUIREMENTS"
  printf '%s\n' "$EXPECTED" > "$STAMP"
fi

# circuitpython-stubs ships all generated modules in one wheel as sibling
# ``*-stubs`` directories. Pyright expects conventional module directory names,
# so expose that installed, version-pinned content from an ignored search root.
STUB_ROOT="$ENVIRONMENT/circuitpython-typings"
SITE_PACKAGES="$("$ENVIRONMENT/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
mkdir -p "$STUB_ROOT"
for STUB_PACKAGE in "$SITE_PACKAGES"/*-stubs; do
  MODULE="$(basename "$STUB_PACKAGE" -stubs)"
  ln -sfn "$STUB_PACKAGE" "$STUB_ROOT/$MODULE"
done

cd "$ROOT"
"$ENVIRONMENT/bin/python" -m compileall -q device/CIRCUITPY xbrut tools tests
"$ENVIRONMENT/bin/pyright"
"$ENVIRONMENT/bin/python" -m unittest discover -s tests -v
