#!/usr/bin/env python3
"""Stage an explicit MicroPython application payload without flashing anything."""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def stage(output, app, mpy_cross=None):
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
        for name in ("__init__.py", "ui.py", "framebuffer.py", "sweet16mono.f8", "SWEET16-LICENSE.txt"):
            shutil.copy2(ROOT / "device" / "CIRCUITPY" / "base" / name, base / name)
        # One canonical page source, but no large Python literal is compiled
        # or retained on the MicroPython heap when an HTTP request arrives.
        page_source = ROOT / "device" / "CIRCUITPY" / "base" / "ap_page.py"
        page_module = ast.parse(page_source.read_text())
        page = next(node for node in page_module.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "HTML" for target in node.targets))
        (base / "settings.html").write_bytes(ast.literal_eval(page.value))
    if mpy_cross:
        # Avoid compiler peak allocations growing the ESP32's GC heap at the
        # expense of Wi-Fi/lwIP memory. Keep the boot entrypoint as main.py.
        for source in sorted(output.rglob("*.py")):
            if source == output / "main.py":
                continue
            subprocess.run([str(mpy_cross), "-s", source.relative_to(output).as_posix(),
                            "-o", str(source.with_suffix(".mpy")), str(source)], check=True)
            source.unlink()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=("browser", "portrait"), default="browser")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mpy-cross", type=Path, help="matching MicroPython cross compiler; recommended for X4")
    args = parser.parse_args()
    print(stage(args.output, args.app, args.mpy_cross))


if __name__ == "__main__":
    main()
