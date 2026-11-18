"""Build a single-file Strategy Lab executable with PyInstaller.

    pip install -e ".[desktop]" pyinstaller
    python packaging/build_exe.py          # -> dist/StrategyLab(.exe)

Builds for the OS it runs on: run it on Windows to get StrategyLab.exe.
GitHub Actions does this automatically (.github/workflows/desktop-build.yml).
"""
import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
sep = ";" if os.name == "nt" else ":"
args = [
    str(ROOT / "packaging" / "strategy_lab.py"),
    "--name", "StrategyLab",
    "--onefile",
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
PyInstaller.__main__.run(args + sys.argv[1:])
