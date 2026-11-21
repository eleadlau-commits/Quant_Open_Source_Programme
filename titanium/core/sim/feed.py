"""Where the engine gets data: anything that can open a dataset and give a guarded view.

``Workspace.datasets`` (:class:`titanium.app.datasets.DatasetService`) is the provider
in the app. :class:`MemoryData` serves datasets held in memory (tests, scripts).
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol, runtime_checkable

from ..bars import MarketData
from ..guard import Guard


@runtime_checkable
class DataProvider(Protocol):
    def open(self, dataset_id: str) -> MarketData: ...

    def view(self, dataset_ids: str | Iterable[str], as_of) -> Guard: ...


class MemoryData:
    """A :class:`DataProvider` over datasets already in memory, by id."""

    def __init__(self, datasets: dict[str, MarketData]):
        self.datasets = dict(datasets)

    def open(self, dataset_id: str) -> MarketData:
        return self.datasets[dataset_id]

    def view(self, dataset_ids, as_of) -> Guard:
        ids = [dataset_ids] if isinstance(dataset_ids, str) else list(dataset_ids)
        return Guard(self.open(ids[0]).combine(*(self.open(i) for i in ids[1:])), as_of)

    def version(self, dataset_id: str) -> str:
        return ""


def combined(provider: DataProvider, dataset_ids: list[str]) -> MarketData:
    """The datasets as one :class:`MarketData` (the first sets the market), as ``provider.view`` does."""
    first, *rest = dataset_ids
    return provider.open(first).combine(*(provider.open(i) for i in rest))


class DatasetFeed:
    """Implements :class:`titanium.core.engine.Feed`: guarded views over fixed datasets.

    The same view ``provider.view(ids, as_of)`` gives, but the datasets are combined once
    for the whole run so derived daily bars and listing spans are worked out only once.
    """

    def __init__(self, provider: DataProvider, dataset_ids: list[str]):
        self.ids = list(dataset_ids)
        self.data = combined(provider, self.ids)

    def view(self, as_of: datetime) -> Guard:
        return Guard(self.data, as_of)
