"""Build a single-file Strategy Lab executable with PyInstaller.

    pip install -e ".[desktop]" pyinstaller
    python packaging/build_exe.py            # -> dist/StrategyLab(.exe), one portable file
    python packaging/build_exe.py --onedir   # -> dist/StrategyLab/ folder (used by the installer)

Builds for the OS it runs on: run it on Windows to get StrategyLab.exe.
GitHub Actions does this automatically (.github/workflows/desktop-build.yml).
"""
import os
import sys
from pathlib import Path

import PyInstaller.__main__

onedir = "--onedir" in sys.argv
extra = [a for a in sys.argv[1:] if a != "--onedir"]

ROOT = Path(__file__).resolve().parent.parent
sep = ";" if os.name == "nt" else ":"
args = [
    str(ROOT / "packaging" / "strategy_lab.py"),
    "--name", "StrategyLab",
    "--onedir" if onedir else "--onefile",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--add-data", f"{ROOT / 'configs'}{sep}configs",
    "--paths", str(ROOT),
    "--collect-submodules", "honestbt",
    # not needed by the desktop app; keeps the file smaller
    "--exclude-module", "pyarrow",
    "--exclude-module", "fastapi",
    "--exclude-module", "uvicorn",
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
    "--exclude-module", "tkinter",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]
PyInstaller.__main__.run(args + extra)
