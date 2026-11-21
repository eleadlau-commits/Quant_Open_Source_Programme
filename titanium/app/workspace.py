"""The workspace: datasets, strategies and runs open in this session.

Runs are kept in memory for the session only (Compare and Backtests read them here).
Datasets and strategies are saved by their own sections.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from ..core.data import DatasetInfo
from ..core.module_library import register_starters
from ..core.plugins import Registry
from ..core.run import RunRecord
from ..core.strategy import StrategyGraph
from .events import Event

T = TypeVar("T")


class Collection(Generic[T]):
    """Objects by id, with events the views listen to."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}
        self.added = Event()  # (id, obj)
        self.changed = Event()  # (id, obj)
        self.removed = Event()  # (id,)

    def put(self, id: str, obj: T) -> None:
        new = id not in self._items
        self._items[id] = obj
        (self.added if new else self.changed).emit(id, obj)

    def get(self, id: str) -> T:
        return self._items[id]

    def remove(self, id: str) -> None:
        if self._items.pop(id, None) is not None:
            self.removed.emit(id)

    def ids(self) -> list[str]:
        return list(self._items)

    def __contains__(self, id: object) -> bool:
        return id in self._items

    def __len__(self) -> int:
        return len(self._items)


class Workspace:
    def __init__(self, registry: Registry | None = None) -> None:
        if registry is None:
            registry = Registry()
            register_starters(registry)
        self.registry = registry
        self.datasets: Collection[DatasetInfo] = Collection()
        self.strategies: Collection[StrategyGraph] = Collection()
        self.runs: Collection[RunRecord] = Collection()
        self.focused_strategy: str | None = None  # the strategy whose tab is in front
        self.strategy_focused = Event()  # (id or None,)

    def focus_strategy(self, id: str | None) -> None:
        if id != self.focused_strategy:
            self.focused_strategy = id
            self.strategy_focused.emit(id)
