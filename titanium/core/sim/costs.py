"""Trading costs, ported from the prototype (``honestbt.engine.CostModel`` / ``FuturesCostModel``).

Every fill pays costs in account currency, kept apart from the fill price so the
trade log shows both the print and what it cost:

* **stocks**: half the spread plus slippage, in basis points of the price, per share.
  The spread is wider in the first minutes after the regular open, and never less than
  a minimum per share (half a cent by default). An optional commission per share.
* **futures**: slippage in ticks (market and stop orders; resting limits fill at their
  price by default) plus a commission per contract per side, in currency, using the
  contract's tick size and multiplier.

``stress`` scales every cost (a backtest can re-run at 2x costs to see if an edge survives).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, time
from typing import Any

from ..instruments import Instrument, InstrumentKind
from ..markets import Market


@dataclass
class EquityCosts:
    half_spread_bps: float = 5.0
    slippage_bps: float = 3.0
    open_multiplier: float = 3.0  # spread multiplier in the first ``open_minutes`` after the regular open
    open_minutes: int = 5
    min_half_spread: float = 0.005  # currency per share
    commission_per_share: float = 0.0

    def per_share(self, price: float, after_open: float | None) -> float:
        """Cost per share at ``price``; ``after_open`` is minutes since the regular open (None: outside it)."""
        bps = self.half_spread_bps
        if after_open is not None and 0 <= after_open < self.open_minutes:
            bps *= self.open_multiplier
        half_spread = max(bps / 1e4 * price, self.min_half_spread)
        return half_spread + self.slippage_bps / 1e4 * price + self.commission_per_share


@dataclass
class FuturesCosts:
    commission_per_side: float = 0.85  # currency per contract (broker + exchange + regulatory)
    slippage_ticks: float = 1.0  # market orders
    stop_slippage_ticks: float = 1.0  # a stop becomes a market order when hit
    limit_slippage_ticks: float = 0.0  # a resting limit fills at its price (optimistic)

    def per_contract(self, how: str, tick_size: float, multiplier: float) -> float:
        ticks = {"limit": self.limit_slippage_ticks, "stop": self.stop_slippage_ticks}.get(how, self.slippage_ticks)
        return ticks * tick_size * multiplier + self.commission_per_side


def _build(cls, values: dict[str, Any] | None):
    names = {f.name for f in fields(cls)}
    values = dict(values or {})
    unknown = set(values) - names
    if unknown:
        raise ValueError(f"unknown {cls.__name__} settings: {', '.join(sorted(unknown))}")
    return cls(**values)


@dataclass
class CostModel:
    equity: EquityCosts = field(default_factory=EquityCosts)
    futures: FuturesCosts = field(default_factory=FuturesCosts)
    stress: float = 1.0

    @classmethod
    def from_settings(cls, costs: dict[str, Any] | None) -> "CostModel":
        """``{"equity": {...}, "futures": {...}, "stress": 1.0}``; every key is optional."""
        costs = dict(costs or {})
        out = cls(_build(EquityCosts, costs.pop("equity", None)), _build(FuturesCosts, costs.pop("futures", None)),
                  float(costs.pop("stress", 1.0)))
        if costs:
            raise ValueError(f"unknown cost settings: {', '.join(sorted(costs))}")
        return out

    def cost(self, instrument: Instrument, market: Market, price: float, quantity: float, at: datetime,
             how: str = "market") -> float:
        """Cost in account currency of filling ``quantity`` at ``price`` at ``at``.

        ``how`` is market, stop or limit (futures slippage depends on it).
        """
        quantity = abs(quantity)
        if instrument.kind is InstrumentKind.FUTURE:
            each = self.futures.per_contract(how, instrument.tick_size, instrument.multiplier)
        else:
            each = self.equity.per_share(price, _minutes_after_open(market, at)) * instrument.multiplier
        return each * quantity * self.stress


def _minutes_after_open(market: Market, at: datetime) -> float | None:
    local = market.local(at)
    start: time = market.session().start
    after = (local.hour * 60 + local.minute + local.second / 60) - (start.hour * 60 + start.minute)
    end = market.session().end
    if after < 0 or local.time() >= end:
        return None
    return after
