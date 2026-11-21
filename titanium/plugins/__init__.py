"""Plugins: folders that add entries to the app's libraries.

* ``builtin/``: the plugins that ship with the app (synthetic data, downloads,
  realised volatility, the starter modules). Each can be switched off.
* the user's plugins folder (``Documents/Titanium/plugins``): your own, or ones you
  imported as ``.tiplug`` files.

The loader is :mod:`titanium.app.plugins`; packing, checking and installing ``.tiplug``
files is :mod:`titanium.plugins.pack`; the command line is ``python -m titanium.plugins``.
This package imports nothing, so every layer can find the built-in folder.
"""
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
