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
sys.path.insert(0, str(ROOT))
from honestbt.plugins import ALLOWED_IMPORTS  # noqa: E402

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
    # Plugin folders are read from disk at start-up, so ship them as files.
    "--add-data", f"{ROOT / 'honestbt' / 'plugins' / 'builtin'}{sep}honestbt/plugins/builtin",
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
# Plugins (built-in or added later) may import these; PyInstaller cannot see that.
for mod in sorted(ALLOWED_IMPORTS - {"__future__"}):
    args += ["--hidden-import", mod]
PyInstaller.__main__.run(args + extra)
