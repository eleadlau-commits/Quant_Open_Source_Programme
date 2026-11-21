"""The recorder: writes everything a run produced into a :class:`RunRecord`.

A portfolio state every step, every fill, round-trip trades built from the fills,
module outputs asked for as probes, and a readable log. Measurements, backtests and
the run view read only this record.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from ..instruments import Instrument
from ..markets import Market
from ..orders import Fill
from ..portfolio import PortfolioState
from ..run import RunRecord, Trade


@dataclass
class _Open:
    instrument: str
    side: int
    entry_time: datetime
    tag: str
    qty: float = 0.0  # currently held (absolute)
    entered: float = 0.0
    entry_value: float = 0.0
    exited: float = 0.0
    exit_value: float = 0.0
    pnl: float = 0.0  # realised, before costs
    cost: float = 0.0
    flags: list[str] = field(default_factory=list)


class Recorder:
    def __init__(self, record: RunRecord, market: Market, spec: Callable[[str], Instrument]):
        self.record = record
        self.market = market
        self.spec = spec
        self._open: dict[str, _Open] = {}

    # ---- writing ------------------------------------------------------------------
    def log(self, at: datetime | None, message: str) -> None:
        stamp = self.market.local(at).strftime("%Y-%m-%d %H:%M") if at is not None else "-"
        self.record.log.append(f"{stamp}  {message}")

    def state(self, state: PortfolioState) -> None:
        self.record.states.append(state)

    def probe(self, at: datetime, name: str, value: Any) -> None:
        self.record.probes.setdefault(name, []).append((at, value))

    def fill(self, fill: Fill) -> None:
        self.record.fills.append(fill)
        verb = "bought" if int(fill.side) > 0 else "sold"
        why = fill.info.get("reason", "")
        tag = fill.info.get("tag") or ""
        note = f" ({why}{', ' + tag if tag and tag != why else ''})" if why else ""
        self.log(fill.time, f"{verb} {fill.quantity:g} {fill.instrument} at {fill.price:.4g}, cost {fill.cost:.2f}{note}")
        self._trade(fill)

    # ---- round trips ----------------------------------------------------------------
    def _trade(self, fill: Fill) -> None:
        mult = self.spec(fill.instrument).multiplier
        side, qty = int(fill.side), float(fill.quantity)
        reason = fill.info.get("reason", "")
        tr = self._open.get(fill.instrument)
        if tr is not None and tr.side != side:  # closing part (or all) of the open trade
            closed = min(qty, tr.qty)
            share = closed / qty
            avg = tr.entry_value / tr.entered
            tr.pnl += (fill.price - avg) * closed * tr.side * mult
            tr.cost += fill.cost * share
            tr.exited += closed
            tr.exit_value += closed * fill.price
            tr.qty -= closed
            if reason == "delisted":
                tr.flags.append("delisted")
            if tr.qty <= 1e-12:
                why = reason if reason not in ("market", "") else (fill.info.get("tag") or "market")
                self._close(tr, fill.time, why)
            qty -= closed
            if qty <= 1e-12:
                return
            fill_cost = fill.cost * (1 - share)
        else:
            fill_cost = fill.cost
        if tr is None or tr.instrument not in self._open:
            tr = _Open(fill.instrument, side, fill.time, fill.info.get("tag") or "")
            self._open[fill.instrument] = tr
        tr.qty += qty
        tr.entered += qty
        tr.entry_value += qty * fill.price
        tr.cost += fill_cost

    def _close(self, tr: _Open, at: datetime, reason: str) -> None:
        self._open.pop(tr.instrument, None)
        self.record.trades.append(Trade(
            instrument=tr.instrument, entry_time=tr.entry_time, entry_price=tr.entry_value / tr.entered,
            exit_time=at, exit_price=tr.exit_value / tr.exited, quantity=tr.entered, side=tr.side,
            pnl=tr.pnl - tr.cost, reason=reason, cost=tr.cost, flags=tr.flags, tag=tr.tag))

    def finish(self, marks: dict[str, float]) -> None:
        """Positions still held: recorded as open trades, valued at their last mark."""
        for key, tr in list(self._open.items()):
            mult = self.spec(key).multiplier
            avg = tr.entry_value / tr.entered
            price = marks.get(key, avg)
            pnl = tr.pnl + (price - avg) * tr.qty * tr.side * mult - tr.cost
            self.record.trades.append(Trade(
                instrument=key, entry_time=tr.entry_time, entry_price=avg, exit_time=None, exit_price=None,
                quantity=tr.entered, side=tr.side, pnl=pnl, reason="open", cost=tr.cost,
                flags=tr.flags + ["open"], tag=tr.tag))
        self._open.clear()
        self.record.trades.sort(key=lambda t: t.entry_time)
