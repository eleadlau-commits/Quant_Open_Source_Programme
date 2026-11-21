"""The portfolio ledger: cash and positions in real currency.

Results are *shown* normalised (growth of 1, or %), but the ledger keeps real
currency against a notional capital, because whole contracts, per-share fees,
lot sizes and margin only make sense in real units.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from .orders import Fill


@dataclass
class Position:
    instrument: str
    quantity: float
    avg_price: float
    market_value: float = 0.0  # at the last mark, in account currency


@dataclass
class PortfolioState:
    """A snapshot at one time: what the strategy sees as ``p`` and what the recorder stores each step."""

    time: datetime
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    equity: float = 0.0  # cash + marked value of positions
    capital: float = 0.0  # the notional starting capital, for normalising

    def weights(self) -> dict[str, float]:
        """Positions as fractions of equity (what a target-based strategy works in)."""
        if not self.equity:
            return {}
        return {k: p.market_value / self.equity for k, p in self.positions.items()}

    @property
    def growth(self) -> float:
        return self.equity / self.capital if self.capital else 1.0


@runtime_checkable
class Ledger(Protocol):
    def apply(self, fill: Fill) -> None: ...

    def mark(self, time: datetime, prices: dict[str, float]) -> PortfolioState: ...

    def state(self) -> PortfolioState: ...
