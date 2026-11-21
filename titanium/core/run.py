"""A run: everything one strategy run produced, as a self-contained bundle.

Measurements and backtests only read runs. Runs live in memory for the session;
because a bundle is self-contained, saving one to a file later needs no engine change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .orders import Fill
from .portfolio import PortfolioState


@dataclass
class Trade:
    instrument: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None
    exit_price: float | None
    quantity: float
    side: int
    pnl: float | None = None
    reason: str = ""
    # additions (Phase 1B)
    cost: float = 0.0  # spread, slippage and commission paid on the way in and out (already in pnl)
    flags: list[str] = field(default_factory=list)  # e.g. "delisted", "open" (still held when the run ended)
    tag: str = ""  # the entry order's tag


@dataclass
class RunRecord:
    id: str
    strategy_id: str
    strategy_snapshot: dict[str, Any]  # the graph and knob values exactly as run
    dataset_id: str
    dataset_version: str
    created: datetime
    settings: dict[str, Any] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    states: list[PortfolioState] = field(default_factory=list)  # one per step: positions, cash, equity
    probes: dict[str, list[tuple[datetime, Any]]] = field(default_factory=dict)  # recorded module outputs
    log: list[str] = field(default_factory=list)
    # additions (Phase 1B)
    status: str = "done"  # done, cancelled or failed
    error: str = ""
    capital: float = 0.0
    market: str = ""
    finished: datetime | None = None

    def equity(self) -> list[tuple[datetime, float]]:
        return [(s.time, s.equity) for s in self.states]

    def growth(self) -> list[tuple[datetime, float]]:
        """Equity as growth of 1 (how results are shown)."""
        return [(s.time, s.growth) for s in self.states]
