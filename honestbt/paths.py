"""Where Titanium keeps your files: ~/Documents/Titanium.

The app used to be called Strategy Lab. If an old ~/Documents/Strategy Lab
folder exists and no Titanium folder does yet, it is renamed once, so saved
strategies, plugins and settings carry over.
"""
from pathlib import Path

APP_NAME = "Titanium"
_OLD_NAME = "Strategy Lab"


def app_dir() -> Path:
    docs = Path.home() / "Documents"
    new, old = docs / APP_NAME, docs / _OLD_NAME
    if old.is_dir() and not new.exists():
        try:
            old.rename(new)
        except OSError:
            return old  # in use or not allowed: keep using the old folder
    return new
