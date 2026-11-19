"""Starter packs: the example strategies and code modules, kept out of the app until you import them.

* Starter strategies: the strategy plugin folders (weekly top-N, Nasdaq opening
  range breakout, the gap families) go into your plugins folder, and the
  example strategy files (.json, .py) into Documents/Titanium.
* Starter modules: small code modules (.py, one function each) go into
  Documents/Titanium/modules, where the module library finds them.

Nothing you already have is overwritten.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from . import plugins
from .paths import app_dir

STARTER = Path(plugins.__file__).resolve().parent / "starter"


def strategy_packs() -> list[Path]:
    return sorted(p for p in STARTER.iterdir() if (p / "plugin.json").exists())


def strategy_files() -> list[Path]:
    return sorted(p for p in (STARTER / "strategies").iterdir() if p.suffix in (".json", ".py"))


def module_files() -> list[Path]:
    return sorted((STARTER / "modules").glob("*.py"))


def modules_dir(home: Path | None = None) -> Path:
    return (home or app_dir()) / "modules"


def import_strategies(home: Path | None = None) -> list[str]:
    """Copy the starter strategy packs and files in; returns what was added."""
    home = home or app_dir()
    added = []
    pdir = plugins.user_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    loaded = {st.id for st in plugins.statuses()}
    for pack in strategy_packs():
        if pack.name not in loaded and not (pdir / pack.name).exists():  # already installed: leave it
            shutil.copytree(pack, pdir / pack.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            added.append(pack.name)
    home.mkdir(parents=True, exist_ok=True)
    for f in strategy_files():
        if not (home / f.name).exists():
            shutil.copy2(f, home / f.name)
            added.append(f.name)
    if added:
        plugins.reload()
    return added


def import_modules(home: Path | None = None) -> list[str]:
    target = modules_dir(home)
    target.mkdir(parents=True, exist_ok=True)
    added = []
    for f in module_files():
        if not (target / f.name).exists():
            shutil.copy2(f, target / f.name)
            added.append(f.name)
    return added


def have_strategies(home: Path | None = None) -> bool:
    home = home or app_dir()
    return home.is_dir() and any(p.suffix in (".json", ".py") for p in home.iterdir())
