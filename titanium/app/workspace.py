"""The workspace: datasets, strategies and runs open in this session.

Runs are kept in memory for the session only (Compare and Backtests read them here).
Datasets and strategies are saved by their own sections.
"""
from __future__ import annotations

from pathlib import Path

from ..core.plugins import Registry
from ..core.run import RunRecord
from ..core.strategy import StrategyGraph
from .collection import Collection
from .datasets import DatasetService

__all__ = ["Collection", "DatasetService", "Workspace"]


class Workspace:
    """``data_root``: the folder datasets are saved in. Without one (tests, scripts) they
    live in a temporary folder for the session. The app passes ``paths.app_folder() / "data"``.
    """

    def __init__(self, registry: Registry | None = None, data_root: Path | str | None = None) -> None:
        self.registry = registry or Registry()
        self.datasets = DatasetService(self.registry, data_root)
        self.strategies: Collection[StrategyGraph] = Collection()
        self.runs: Collection[RunRecord] = Collection()
        self.strategies.added.connect(self._strategy_changed)
        self.strategies.changed.connect(self._strategy_changed)

    def _strategy_changed(self, strategy_id: str, graph: StrategyGraph) -> None:
        """A strategy lists the datasets it uses in ``settings["datasets"]``; keep ``used_by`` in step."""
        settings = getattr(graph, "settings", None) or {}
        ids = settings.get("datasets")
        if ids is None and settings.get("dataset"):
            ids = [settings["dataset"]]
        if ids is not None:
            self.datasets.sync_strategy(strategy_id, ids)
