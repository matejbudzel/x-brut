#!/usr/bin/env python3
"""Stage an explicit MicroPython application payload without flashing anything."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def stage(output, app):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty")
    native = ROOT / "native" / "micropython"
    shutil.copy2(native / ("app" if app == "browser" else "portrait") / "main.py", output / "main.py")
    shutil.copy2(native / "app" / "xbrut_input.py", output / "xbrut_input.py")
    if app == "portrait":
        base = output / "base"
        base.mkdir()
        for source in (native / "base").glob("*.py"):
            shutil.copy2(source, base / source.name)
        for name in ("__init__.py", "ui.py", "framebuffer.py", "ap_page.py", "sweet16mono.f8", "SWEET16-LICENSE.txt"):
            shutil.copy2(ROOT / "device" / "CIRCUITPY" / "base" / name, base / name)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=("browser", "portrait"), default="browser")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(stage(args.output, args.app))


if __name__ == "__main__":
    main()
