"""Where Titanium keeps the user's files: ``Documents/Titanium`` (``TITANIUM_HOME`` overrides it).

No Qt here, so every layer above can use it.
"""
from __future__ import annotations

import os
from pathlib import Path


def app_folder() -> Path:
    env = os.environ.get("TITANIUM_HOME")
    return Path(env) if env else Path.home() / "Documents" / "Titanium"


def plugins_folder() -> Path:
    return app_folder() / "plugins"


def skins_folder() -> Path:
    return app_folder() / "skins"
