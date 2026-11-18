"""Entry script for the PyInstaller build (absolute import, no package context).

A windowed exe has no console, so any startup error would vanish silently.
Here every crash is written to Documents/Strategy Lab/strategy_lab.log and
shown in a plain Windows message box (via ctypes, so it works even if Qt
itself failed to load).
"""
import faulthandler
import os
import sys
import traceback
from pathlib import Path

LOG_DIR = Path.home() / "Documents" / "Strategy Lab"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG = LOG_DIR / "strategy_lab.log"
_log = open(LOG, "w", encoding="utf-8", buffering=1)
faulthandler.enable(_log)  # hard crashes (segfaults in Qt) land here too
if sys.stdout is None:
    sys.stdout = _log
if sys.stderr is None:
    sys.stderr = _log


def _close_splash():
    try:
        import pyi_splash  # only present in the portable build
        pyi_splash.close()
    except Exception:
        pass


def _fatal(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    _log.write(text)
    _log.flush()
    _close_splash()
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, f"Strategy Lab could not start.\n\n{exc}\n\nDetails were saved to:\n{LOG}", "Strategy Lab", 0x10)


sys.excepthook = _fatal

if __name__ == "__main__":
    try:
        _log.write(f"Starting Strategy Lab, Python {sys.version}, frozen={getattr(sys, 'frozen', False)}\n")
        from honestbt.desktop.app import main
        code = main(on_shown=_close_splash)
    except SystemExit:
        raise
    except BaseException:
        _fatal(*sys.exc_info())
        code = 1
    sys.exit(code)
