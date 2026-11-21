"""Helpers for a plugin's own tests: ``from titanium.plugins.testing import loaded``."""
from __future__ import annotations

import inspect
from pathlib import Path

from ..app.plugins import PluginManager
from ..core.plugins import Registry
from . import BUILTIN_DIR


def loaded(plugin_id: str, folder: str | Path | None = None) -> Registry:
    """A fresh registry with the built-in plugins and the plugin under test loaded.

    ``folder``: the folder holding the plugin's folder (default: found from the calling
    test file, ``<plugins>/<id>/tests/test_x.py``). Fails if the plugin does not load.
    """
    if folder is None:
        caller = Path(inspect.stack()[1].filename).resolve()
        folder = next(p.parent for p in caller.parents if p.name == plugin_id)
    folder = Path(folder)
    reg = Registry()
    mgr = PluginManager(reg, user_folder=None if folder == BUILTIN_DIR else folder, state_file=None)
    mgr.load()
    st = mgr.status(plugin_id)
    assert st.on, f"{plugin_id} did not load: {st.reason}"
    return reg
