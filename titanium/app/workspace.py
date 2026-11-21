"""The workspace: datasets, strategies and runs open in this session.

Runs are kept in memory for the session only (Compare and Backtests read them here).
Datasets and strategies are saved by their own sections.
"""
from __future__ import annotations

from pathlib import Path

from ..core.measurements import register_measurements
from ..core.module_library import register_starters
from ..core.plugins import Registry
from ..core.strategy import StrategyGraph
from .collection import Collection
from .events import Event
from .datasets import DatasetService
from .runs import RunJob, RunService

__all__ = ["Collection", "DatasetService", "RunJob", "RunService", "Workspace"]


class Workspace:
    """``data_root``: the folder datasets are saved in. Without one (tests, scripts) they
    live in a temporary folder for the session. The app passes ``paths.app_folder() / "data"``.
    """

    def __init__(self, registry: Registry | None = None, data_root: Path | str | None = None) -> None:
        if registry is None:
            registry = Registry()
            register_starters(registry)
        self.registry = registry
        register_measurements(registry)  # the built-in ones, unless already there
        self.datasets = DatasetService(self.registry, data_root)
        self.strategies: Collection[StrategyGraph] = Collection()
        self.runs = RunService(self.datasets, self.strategies)
        self.strategies.added.connect(self._strategy_changed)
        self.strategies.changed.connect(self._strategy_changed)
        self.focused_strategy: str | None = None  # the strategy whose tab is in front
        self.strategy_focused = Event()  # (id or None,)

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
