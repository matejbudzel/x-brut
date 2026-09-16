#!/usr/bin/env bash
# One-shot X Brut installer for an Xteink X4 connected over USB JTAG serial.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/.tools/x4-install"
BACKUPS="$ROOT/backups"
FIRMWARE_URL="https://downloads.circuitpython.org/bin/xteink_x4/en_US/adafruit-circuitpython-xteink_x4-en_US-10.3.0.bin"
BOARD_ID="xteink_x4"
PORT=""
YES=0
FORCE_FLASH=0

usage() {
  cat <<'EOF'
Usage: tools/install-x4.sh --yes [--port /dev/ttyACM0] [--firmware-url URL] [--force-flash]

When CircuitPython is already running, this replaces only the X Brut app and
its libraries over serial. Otherwise it backs up the whole 16 MiB X4 flash,
erases it, and flashes official CircuitPython. --force-flash always takes the
full backup-and-flash path. --yes is required because app files may be erased.
EOF
}

while (($#)); do
  case "$1" in
    --yes) YES=1 ;;
    --port) PORT="${2:?missing port}"; shift ;;
    --firmware-url) FIRMWARE_URL="${2:?missing URL}"; shift ;;
    --force-flash) FORCE_FLASH=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if (( ! YES )); then
  echo "Refusing to replace X Brut without --yes." >&2
  usage >&2
  exit 2
fi

need_apt=0
for command in python3 curl; do command -v "$command" >/dev/null 2>&1 || need_apt=1; done
if (( need_apt )) || ! python3 -c 'import venv' 2>/dev/null; then
  command -v apt-get >/dev/null || { echo "apt-get is required to bootstrap this Debian-host installer." >&2; exit 1; }
  echo "Installing Debian prerequisites (python3-venv, pip, curl)..."
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip curl
fi

if [[ ! -x "$TOOLS/bin/python" ]]; then
  python3 -m venv "$TOOLS"
fi
"$TOOLS/bin/python" -m pip install --upgrade pip >/dev/null
"$TOOLS/bin/python" -m pip install --upgrade esptool pyserial circup

if [[ -z "$PORT" ]]; then
  PORT="$({ "$TOOLS/bin/python" - <<'PY'
from serial.tools import list_ports
ports = [p.device for p in list_ports.comports()
         if "USB JTAG" in (p.description or "") or "Espressif" in (p.description or "")]
print(ports[0] if len(ports) == 1 else "")
PY
  } )"
fi
if [[ -z "$PORT" || ! -e "$PORT" ]]; then
  echo "Could not uniquely find the X4 USB JTAG serial port. Re-run with --port /dev/ttyACM0." >&2
  exit 1
fi

STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

FLASHED=0
if (( ! FORCE_FLASH )) && "$TOOLS/bin/python" "$ROOT/tools/serial-upload.py" --port "$PORT" --check-circuitpython >/dev/null 2>&1; then
  echo "CircuitPython detected; replacing only X Brut files and libraries."
else
  mkdir -p "$BACKUPS"
  STAMP="$(date +%Y%m%d-%H%M%S)"
  BACKUP="$BACKUPS/x4-crosspoint-$STAMP.bin"
  FIRMWARE="$TOOLS/xteink-x4-circuitpython.bin"
  echo "Downloading official CircuitPython firmware..."
  curl --fail --location --retry 3 "$FIRMWARE_URL" -o "$FIRMWARE"
  echo "Backing up current 16 MiB flash to $BACKUP"
  "$TOOLS/bin/python" -m esptool --chip esp32c3 --port "$PORT" read-flash 0x0 0x1000000 "$BACKUP"
  [[ $(wc -c < "$BACKUP") -eq 16777216 ]] || { echo "Flash backup has an unexpected size; refusing to continue." >&2; exit 1; }
  echo "Erasing and flashing CircuitPython..."
  "$TOOLS/bin/python" -m esptool --chip esp32c3 --port "$PORT" erase-flash
  "$TOOLS/bin/python" -m esptool --chip esp32c3 --port "$PORT" write-flash 0x0 "$FIRMWARE"
  sleep 4
  FLASHED=1
fi

# circup resolves transitive bundle dependencies into a host staging directory.
cp -a "$ROOT/device/CIRCUITPY/." "$STAGE/"
mkdir -p "$STAGE/lib"
echo "Resolving CircuitPython libraries with circup..."
# The staging directory is not a mounted CIRCUITPY drive, so it has no
# boot_out.txt.  CircUp requires both overrides to skip that probe.
"$TOOLS/bin/circup" --path "$STAGE" --cpy-version 10.3.0 --board-id "$BOARD_ID" install --requirement "$ROOT/device/requirements.txt"

echo "Uploading X Brut and libraries over the CircuitPython serial REPL..."
"$TOOLS/bin/python" "$ROOT/tools/serial-upload.py" --port "$PORT" --source "$STAGE" --wipe
if (( FLASHED )); then
  echo "Installed X Brut. Flash backup: $BACKUP"
else
  echo "Installed X Brut without reflashing CircuitPython."
fi
