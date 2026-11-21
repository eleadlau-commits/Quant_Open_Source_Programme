"""The ledger: cash and positions in real currency against a notional capital.

* Stocks exchange cash for shares: buying 100 shares at 20 takes 2,000 from cash.
* Futures are margined: no cash changes hands for the contract itself; open profit is
  the position's market value, and profit is moved into cash when the position shrinks.
* Every fill's costs come out of cash.
* ``mark`` values each position at a price and returns a :class:`PortfolioState`.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Callable

from ..instruments import Instrument, InstrumentKind
from ..orders import Fill
from ..portfolio import PortfolioState, Position


class SimLedger:
    """Implements :class:`titanium.core.portfolio.Ledger`."""

    def __init__(self, capital: float, spec: Callable[[str], Instrument], start: datetime | None = None):
        self.capital = float(capital)
        self.cash = float(capital)
        self.spec = spec
        self.positions: dict[str, Position] = {}
        self.realised = 0.0
        self.costs = 0.0
        self._state = PortfolioState(start, self.cash, {}, self.cash, self.capital) if start else None

    def apply(self, fill: Fill) -> float:
        """Book a fill; returns the profit it realised (before costs)."""
        spec = self.spec(fill.instrument)
        mult = spec.multiplier
        q = int(fill.side) * float(fill.quantity)
        pos = self.positions.get(fill.instrument)
        old = pos.quantity if pos else 0.0
        avg = pos.avg_price if pos else 0.0
        new = old + q
        realised = 0.0
        if old and old * q < 0:  # reducing (or flipping)
            closed = min(abs(q), abs(old))
            realised = (fill.price - avg) * closed * (1 if old > 0 else -1) * mult
        if new == 0:
            new_avg = 0.0
        elif old == 0 or old * new < 0:  # opened, or flipped through zero
            new_avg = fill.price
        elif abs(new) > abs(old):  # added
            new_avg = (avg * abs(old) + fill.price * abs(q)) / abs(new)
        else:  # reduced
            new_avg = avg
        if spec.kind is InstrumentKind.FUTURE:
            self.cash += realised
        else:
            self.cash -= q * fill.price * mult
        self.cash -= fill.cost
        self.costs += fill.cost
        self.realised += realised
        if new == 0:
            self.positions.pop(fill.instrument, None)
        else:
            p = pos or Position(fill.instrument, 0.0, 0.0)
            p.quantity, p.avg_price = new, new_avg
            p.last_price = p.last_price or fill.price
            self._value(p, spec, p.last_price)
            self.positions[fill.instrument] = p
        return realised

    @staticmethod
    def _value(p: Position, spec: Instrument, price: float) -> None:
        p.last_price = price
        p.exposure = p.quantity * price * spec.multiplier
        if spec.kind is InstrumentKind.FUTURE:
            p.market_value = p.quantity * (price - p.avg_price) * spec.multiplier
        else:
            p.market_value = p.exposure

    def equity_at(self, prices: dict[str, float]) -> float:
        """Equity if every position were valued at ``prices`` (missing: its last mark)."""
        total = self.cash
        for k, p in self.positions.items():
            spec = self.spec(k)
            price = prices.get(k, p.last_price)
            if spec.kind is InstrumentKind.FUTURE:
                total += p.quantity * (price - p.avg_price) * spec.multiplier
            else:
                total += p.quantity * price * spec.multiplier
        return total

    def mark(self, time: datetime, prices: dict[str, float]) -> PortfolioState:
        for k, p in self.positions.items():
            price = prices.get(k)
            if price is None or price != price:  # missing or NaN: keep the last mark
                price = p.last_price or p.avg_price
            self._value(p, self.spec(k), price)
        equity = self.cash + sum(p.market_value for p in self.positions.values())
        self._state = PortfolioState(time, self.cash, copy.deepcopy(self.positions), equity, self.capital)
        return self._state

    def state(self) -> PortfolioState:
        if self._state is None:
            raise RuntimeError("the ledger has not been marked yet")
        return self._state

    def quantity(self, key: str) -> float:
        p = self.positions.get(key)
        return p.quantity if p else 0.0
