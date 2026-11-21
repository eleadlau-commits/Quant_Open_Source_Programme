"""Titanium: a desktop workbench for building, running and judging trading strategies.

Layers (each one only uses the layer below it):

* ``titanium.desktop``: the Qt window. Every panel is a view, shown as a page or a dock.
* ``titanium.app``: the shared objects every page works on (workspace, libraries, runs).
* ``titanium.core``: no UI. Markets, data, strategies, the engine, measurements, backtests, plugins.
"""

__version__ = "0.2.0.dev0"
