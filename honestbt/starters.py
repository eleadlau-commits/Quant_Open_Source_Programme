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


# ---------------------------------------------------------------- back to an empty app
KEEP_ON = ("synthetic-stocks",)  # one data source, so a new strategy can still run


def builtin_ids() -> list[str]:
    return sorted(p.name for p in plugins.BUILTIN_DIR.iterdir() if (p / "plugin.json").exists())


def switch_on_builtins() -> None:
    """Undo a reset: switch every built-in pack back on."""
    off = plugins.switched_off()
    for pid in builtin_ids():
        if pid in off:
            plugins.set_enabled(pid, True)


def reset_to_empty(home: Path | None = None) -> Path:
    """Back up Documents/Titanium to a zip, then remove your strategy files, code modules and installed packs,
    and switch off every built-in pack except one data source. Returns the backup file.

    The engine, the look-ahead guard and the synthetic stock data stay: without them nothing can run.
    Import starters (or switch packs back on in Manage packs) to undo."""
    import time
    import zipfile

    home = home or app_dir()
    backups = home / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    zpath = backups / f"before-reset-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    pdir = plugins.user_dir()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in home.rglob("*"):
            if f.is_file() and backups not in f.parents:
                z.write(f, f.relative_to(home))
        if pdir.exists() and home not in pdir.parents:
            for f in pdir.rglob("*"):
                if f.is_file():
                    z.write(f, Path("plugins") / f.relative_to(pdir))
    for f in home.iterdir():
        if f.is_file() and f.suffix in (".json", ".py"):
            f.unlink()
    shutil.rmtree(modules_dir(home), ignore_errors=True)
    if pdir.exists():
        for d in pdir.iterdir():
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
            elif d.suffix in (".tiplug", ".zip"):
                d.unlink()
    for pid in builtin_ids():
        plugins.set_enabled(pid, pid in KEEP_ON)
    plugins.reload()
    return zpath
