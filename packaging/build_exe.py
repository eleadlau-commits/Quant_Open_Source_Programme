"""Build Titanium with PyInstaller.

    pip install -e . pyinstaller
    python packaging/build_exe.py            # -> dist/Titanium(.exe), one portable file
    python packaging/build_exe.py --onedir   # -> dist/Titanium/ folder (used by the installer)

Builds for the OS it runs on: run it on Windows to get Titanium.exe.
GitHub Actions does this automatically (.github/workflows/desktop-build.yml).
"""
import os
import sys
from pathlib import Path

import PyInstaller.__main__

onedir = "--onedir" in sys.argv
extra = [a for a in sys.argv[1:] if a != "--onedir"]

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "titanium"
sep = ";" if os.name == "nt" else ":"


def data(src: Path, dest: str) -> list[str]:
    return ["--add-data", f"{src}{sep}{dest}"]


icon = ROOT / "packaging" / "assets" / ("titanium.ico" if os.name == "nt" else "titanium-512.png")
args = [
    str(ROOT / "packaging" / "titanium_main.py"),
    "--name", "Titanium",
    "--icon", str(icon),
    "--onedir" if onedir else "--onefile",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--paths", str(ROOT),
    "--collect-submodules", "titanium",
    # read from disk at start-up, so they ship as files
    *data(PKG / "plugins" / "builtin", "titanium/plugins/builtin"),
    *data(PKG / "desktop" / "design" / "packs", "titanium/desktop/design/packs"),
    *data(PKG / "desktop" / "assets", "titanium/desktop/assets"),
    # Parquet storage
    "--collect-submodules", "pyarrow",
    # not needed by the app; keeps the build smaller
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]
# Plugin code (built-in or added later) imports titanium.sdk plus numpy and pandas;
# PyInstaller can't see imports made from files read at run time.
for mod in ("titanium.sdk", "numpy", "pandas"):
    args += ["--hidden-import", mod]
# Portable single-file build: show a splash while it unpacks (needs Tcl/Tk in the
# building Python, which the python.org Windows builds include).
if not onedir and sys.platform in ("win32", "darwin"):
    args += ["--splash", str(ROOT / "packaging" / "assets" / "splash.png")]
PyInstaller.__main__.run(args + extra)
