"""The workspace: datasets, strategies and runs open in this session.

Runs are kept in memory for the session only (Compare and Backtests read them here).
Datasets and strategies are saved by their own sections.
"""
from __future__ import annotations

from pathlib import Path

from ..core.measurements import register_measurements
from ..core.module_library import load_library_folder
from ..core.plugins import Registry
from ..core.strategy import StrategyGraph
from .backtests import BacktestResult, BacktestService
from .collection import Collection
from .events import Event
from .datasets import DatasetService
from .plugins import PluginManager
from .runs import RunJob, RunService
from .settings import RunDefaults
from .module_folders import ModuleFolders

__all__ = ["BacktestResult", "BacktestService", "Collection", "DatasetService", "ModuleFolders", "RunDefaults", "RunJob",
           "RunService", "Workspace"]


class Workspace:
    """``data_root``: the folder datasets are saved in. Without one (tests, scripts) they
    live in a temporary folder for the session. The app passes ``paths.app_folder() / "data"``.

    ``plugins_folder``: the user's plugins (and where on/off is remembered). Without one,
    only the built-in plugins load, and on/off lasts for the session. ``library_folder``:
    the module library folder on disk (``<folder>/<module>.py``); None adds nothing.
    """

    def __init__(self, registry: Registry | None = None, data_root: Path | str | None = None,
                 plugins_folder: Path | str | None = None, library_folder: Path | str | None = None,
                 run_defaults: RunDefaults | None = None) -> None:
        self.registry = registry if registry is not None else Registry()
        register_measurements(self.registry)  # part of the app, not a plugin; plugins add more
        self.plugins = PluginManager(self.registry, user_folder=plugins_folder)
        self.plugins.load()
        self.library_folder: Path | None = Path(library_folder) if library_folder is not None else None
        self.library_problems: list[str] = []
        self.library_changed = Event()  # ()
        self.reload_library()
        self.modules = ModuleFolders(self)  # make and change folders and modules in the library folder
        self.run_defaults = run_defaults or RunDefaults()
        self.run_defaults_changed = Event()  # (RunDefaults,)
        self.datasets = DatasetService(self.registry, data_root)
        self.strategies: Collection[StrategyGraph] = Collection()
        self.runs = RunService(self.datasets, self.strategies)
        self.runs.defaults = lambda: self.run_defaults.engine_settings()
        self.backtests = BacktestService(self.registry, self.runs, self.strategies)
        self.strategies.added.connect(self._strategy_changed)
        self.strategies.changed.connect(self._strategy_changed)
        self.focused_strategy: str | None = None  # the strategy whose tab is in front
        self.strategy_focused = Event()  # (id or None,)

    # ---- settings the engine and the library read ------------------------------------
    def set_run_defaults(self, defaults: RunDefaults) -> None:
        if defaults != self.run_defaults:
            self.run_defaults = defaults
            self.run_defaults_changed.emit(defaults)

    def run_settings(self, *layers: dict | None) -> dict:
        """The settings a run starts with: the run defaults, then each layer (strategy, run)."""
        return self.run_defaults.apply(*layers)

    def set_library_folder(self, folder: Path | str | None) -> None:
        self.library_folder = Path(folder) if folder else None
        self.reload_library()

    def reload_library(self) -> int:
        """Read the module library folder again. Returns how many modules it holds."""
        n, self.library_problems = load_library_folder(self.registry, self.library_folder)
        self.library_changed.emit()
        return n

    def focus_strategy(self, id: str | None) -> None:
        if id != self.focused_strategy:
            self.focused_strategy = id
            self.strategy_focused.emit(id)

    def _strategy_changed(self, strategy_id: str, graph: StrategyGraph) -> None:
        """A strategy lists the datasets it uses in ``settings["datasets"]``; keep ``used_by`` in step."""
        settings = getattr(graph, "settings", None) or {}
        ids = settings.get("datasets")
        if ids is None and settings.get("dataset"):
            ids = [settings["dataset"]]
        if ids is not None:
            self.datasets.sync_strategy(strategy_id, ids)
