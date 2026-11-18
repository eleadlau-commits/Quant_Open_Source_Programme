"""Build a single-file Titanium executable with PyInstaller.

    pip install -e ".[desktop]" pyinstaller
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
sys.path.insert(0, str(ROOT))
from honestbt.plugins import ALLOWED_IMPORTS  # noqa: E402

sep = ";" if os.name == "nt" else ":"
args = [
    str(ROOT / "packaging" / "titanium_main.py"),
    "--name", "Titanium",
    "--icon", str(ROOT / "packaging" / "assets" / "titanium.ico"),
    "--onedir" if onedir else "--onefile",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--add-data", f"{ROOT / 'configs'}{sep}configs",
    "--paths", str(ROOT),
    "--collect-submodules", "honestbt",
    # Plugin folders are read from disk at start-up, so ship them as files.
    "--add-data", f"{ROOT / 'honestbt' / 'plugins' / 'builtin'}{sep}honestbt/plugins/builtin",
    # window icon
    "--add-data", f"{ROOT / 'honestbt' / 'desktop' / 'assets'}{sep}honestbt/desktop/assets",
    # not needed by the desktop app; keeps the file smaller
    "--exclude-module", "pyarrow",
    "--exclude-module", "fastapi",
    "--exclude-module", "uvicorn",
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]
# Plugins (built-in or added later) may import these; PyInstaller cannot see that.
for mod in sorted(ALLOWED_IMPORTS - {"__future__"}):
    args += ["--hidden-import", mod]
# Portable single-file build: show a splash while it unpacks (Windows/macOS;
# needs Tcl/Tk in the building Python, which the python.org builds include).
if not onedir and sys.platform in ("win32", "darwin"):
    args += ["--splash", str(ROOT / "packaging" / "assets" / "splash.png")]
PyInstaller.__main__.run(args + extra)
