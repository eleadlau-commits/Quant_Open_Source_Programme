"""The views that ship with the app. Each one is a page or a dock, as the user chooses."""
from __future__ import annotations

from ..views import ViewRegistry
from .backtests import BacktestsView
from .compare import CompareView
from .data import DataView
from .docks import KnobsView, ModuleLibraryView, TradeLogView
from .settings import SettingsView
from .strategies import StrategiesView

ALL = (DataView, StrategiesView, CompareView, BacktestsView, SettingsView,
       ModuleLibraryView, KnobsView, TradeLogView)


def default_registry() -> ViewRegistry:
    reg = ViewRegistry()
    for cls in ALL:
        reg.add(cls)
    return reg
