"""The simulation engine: one simulator for everything.

The engine steps a clock through decision times, gives the strategy a guarded view
and its portfolio, sends orders to a broker, books fills in the ledger and records
every step into a :class:`~titanium.core.run.RunRecord`. A live engine later swaps
only the data feed and the broker.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator, Protocol, runtime_checkable

from .data import GuardedView
from .orders import Fill, Order
from .run import RunRecord
from .strategy import StrategyGraph


@runtime_checkable
class Clock(Protocol):
    def times(self) -> Iterator[datetime]: ...


@runtime_checkable
class Feed(Protocol):
    def view(self, as_of: datetime) -> GuardedView: ...


@runtime_checkable
class Broker(Protocol):
    """Simulated in backtests; a real broker connection later. Same interface."""

    def submit(self, order: Order, at: datetime) -> str: ...

    def fills(self, until: datetime) -> list[Fill]: ...

    def cancel(self, order_id: str) -> None: ...


@runtime_checkable
class Engine(Protocol):
    def run(self, strategy: StrategyGraph, dataset_id: str, settings: dict[str, Any]) -> RunRecord: ...
