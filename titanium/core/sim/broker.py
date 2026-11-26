"""The simulated broker: works orders against the bars that come *after* the decision.

Fill rules (ported from the prototype's ``honestbt.engine``):

* A market order decided at ``t`` fills at the open of the first bar starting at or
  after ``t``: the next bar, never the one the decision already saw. The fill is known
  (and booked) once that bar has opened, so with daily bars it is in the portfolio by the
  next day's decision.
* Limit and stop orders are checked bar by bar. A bar that opens through the level
  fills at its open (worse for stops, better for limits); otherwise at the level.
* Bracket exits (see :func:`titanium.core.orders.bracket`) start working once their
  entry fills: from the entry bar itself when the entry filled at that bar's open,
  otherwise from the next bar. When one exit fills, the other is cancelled. If one bar
  touches both the stop and the target we cannot know which came first, so we take the
  stop (``stop_both_touched``).
* Exits are reduce-only: they never open or flip a position, and they are cancelled
  once the position is flat.
* Stocks are worked in the regular session only unless ``extended_hours`` is set;
  futures in every session. Instruments with only daily bars fill at the session open.

The broker reads the full data (it has to know the next bar), but never hands any of
it to strategy code: strategies only see the guarded view.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..bars import MarketData
from ..instruments import Instrument, InstrumentKind
from ..orders import Fill, Order, OrderType, Side
from .costs import CostModel

UTC = timezone.utc
MINUTE_NS = 60 * 10**9
_PRIORITY = {OrderType.MARKET: 0, OrderType.STOP: 1, OrderType.LIMIT: 2}


def _ns(t) -> int:
    ts = pd.Timestamp(t)
    if ts.tzinfo is None:
        raise ValueError(f"times must be timezone-aware, got {t!r}")
    return int(ts.tz_convert("UTC").as_unit("ns").value)


def _dt(ns: int) -> datetime:
    return pd.Timestamp(int(ns), tz="UTC").to_pydatetime()


def instrument_spec(data: MarketData, key: str) -> Instrument:
    spec = data.instrument_specs.get(key)
    if spec is not None:
        return spec
    market, _, symbol = key.partition(":")
    return Instrument(symbol or key, InstrumentKind.STOCK, market if symbol else data.market.id)


@dataclass
class _Bars:
    """One instrument's bars as arrays: ``start``/``end`` in UTC nanoseconds."""

    start: np.ndarray
    end: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    mark_end: np.ndarray  # every bar (any session), for marking positions
    mark_close: np.ndarray


def _regular_mask(index: pd.DatetimeIndex, data: MarketData) -> np.ndarray:
    """Bars inside the regular session of a trading day (early closes respected)."""
    market, cal = data.market, data.market.calendar
    codes, days = pd.factorize(index.tz_convert(market.tz).normalize().tz_localize(None))
    big, small = np.iinfo(np.int64).max, np.iinfo(np.int64).min
    opens, closes = np.full(len(days), big, np.int64), np.full(len(days), small, np.int64)
    for i, d in enumerate(pd.DatetimeIndex(days)):
        day = d.date()
        if cal is not None and not cal.is_trading_day(day):
            continue
        if cal is not None and hasattr(cal, "session_open"):
            o, c = cal.session_open(day), cal.session_close(day)
        else:
            reg = market.session()
            o, c = datetime.combine(day, reg.start, market.tz), datetime.combine(day, reg.end, market.tz)
        opens[i], closes[i] = _ns(o), _ns(c)
    start = index.as_unit("ns").asi8
    return (start >= opens[codes]) & (start + MINUTE_NS <= closes[codes])


@dataclass
class _Working:
    order: Order
    seq: int
    decided: int  # ns
    active_from: int | None  # ns; None while a bracket exit waits for its entry


class SimBroker:
    """Implements :class:`titanium.core.engine.Broker` over :class:`MarketData`."""

    def __init__(self, data: MarketData, costs: CostModel | None = None, extended_hours: bool | None = None):
        self.data = data
        self.market = data.market
        self.costs = costs or CostModel()
        self.extended_hours = extended_hours
        self._bars: dict[str, _Bars] = {}
        self._working: dict[str, _Working] = {}
        self._children: dict[str, list[str]] = {}
        self._positions: dict[str, float] = {}
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)
        self.log: list[tuple[datetime, str]] = []

    # ---- data --------------------------------------------------------------------
    def spec(self, key: str) -> Instrument:
        return instrument_spec(self.data, key)

    def bars(self, key: str) -> _Bars:
        if key not in self._bars:
            # the arrays only depend on the data, the market and the hours traded: kept with the
            # dataset (MarketData.memo) so the next run over it starts with them
            memo = getattr(self.data, "memo", None)
            tag = ("sim-bars", self.market.id, self.extended_hours)
            self._bars[key] = memo(key, tag, lambda: self._load(key)) if memo else self._load(key)
        return self._bars[key]

    def _load(self, key: str) -> _Bars:
        spec = self.spec(key)
        if self.data.has_minutes(key):
            df = self.data.minute(key)
            idx = pd.DatetimeIndex(df.index)
            start = idx.as_unit("ns").asi8
            arr = df[["open", "high", "low", "close"]].to_numpy(float)
            extended = self.extended_hours if self.extended_hours is not None else spec.kind is InstrumentKind.FUTURE
            mask = np.ones(len(df), bool) if extended else _regular_mask(idx, self.data)
            return _Bars(start[mask], start[mask] + MINUTE_NS, *arr[mask].T, start + MINUTE_NS, arr[:, 3])
        df = self.data.daily(key)
        ends = pd.DatetimeIndex(df["end"]).as_unit("ns").asi8
        cal, market = self.market.calendar, self.market
        starts = []
        for d in df.index:
            day = pd.Timestamp(d).date()
            if cal is not None and hasattr(cal, "session_open"):
                starts.append(_ns(cal.session_open(day)))
            else:
                starts.append(_ns(datetime.combine(day, market.session().start, market.tz)))
        arr = df[["open", "high", "low", "close"]].to_numpy(float)
        return _Bars(np.array(starts, dtype=np.int64), ends, *arr.T, ends, arr[:, 3])

    def next_open(self, key: str, at: datetime) -> tuple[datetime, float] | None:
        """Time and price a market order sent at ``at`` would fill at (the sizing price for targets)."""
        b = self.bars(key)
        i = int(np.searchsorted(b.start, _ns(at), "left"))
        return (_dt(b.start[i]), float(b.open[i])) if i < len(b.start) else None

    def mark(self, key: str, at: datetime) -> float:
        """Close of the latest bar of ``key`` that has ended by ``at`` (NaN if none)."""
        b = self.bars(key)
        i = int(np.searchsorted(b.mark_end, _ns(at), "right")) - 1
        return float(b.mark_close[i]) if i >= 0 else float("nan")

    def last_bar(self, key: str) -> tuple[datetime, float] | None:
        b = self.bars(key)
        return (_dt(b.mark_end[-1]), float(b.mark_close[-1])) if len(b.mark_end) else None

    # ---- the Broker protocol --------------------------------------------------------
    def submit(self, order: Order, at: datetime) -> str:
        if order.quantity <= 0:
            raise ValueError(f"order quantity must be positive, got {order.quantity} (use side for direction)")
        order = replace(order, side=Side(order.side), type=OrderType(order.type))
        if not order.id:
            order.id = f"o{next(self._ids)}"
        if order.id in self._working:
            raise ValueError(f"an open order already has id {order.id!r}")
        if order.type is OrderType.LIMIT and order.limit_price is None and order.offset is None:
            raise ValueError("a limit order needs limit_price")
        if order.type is OrderType.STOP and order.stop_price is None and order.offset is None:
            raise ValueError("a stop order needs stop_price")
        child = order.parent is not None
        if child:
            if order.parent not in self._working:
                raise ValueError(f"order {order.id!r}: its entry {order.parent!r} is not open")
            order.reduce_only = True
            self._children.setdefault(order.parent, []).append(order.id)
        elif order.offset is not None:
            raise ValueError("offset is only for bracket exits (orders with a parent)")
        t = _ns(at)
        self._working[order.id] = _Working(order, next(self._seq), t, None if child else t)
        return order.id

    def cancel(self, order_id: str) -> None:
        w = self._working.pop(order_id, None)
        if w is None:
            return
        for c in self._children.pop(order_id, []):
            self._working.pop(c, None)

    def cancel_instrument(self, key: str) -> list[str]:
        ids = [i for i, w in self._working.items() if w.order.instrument == key]
        for i in ids:
            self.cancel(i)
        return ids

    def open_orders(self) -> list[Order]:
        return [replace(w.order) for w in sorted(self._working.values(), key=lambda w: w.seq)]

    def position(self, key: str) -> float:
        return self._positions.get(key, 0.0)

    def fills(self, until: datetime) -> list[Fill]:
        """Work every open order through the bars known by ``until``: market orders through the
        bars that have opened, limits and stops through the bars that have ended."""
        until_ns = _ns(until)
        out: list[Fill] = []
        for key in sorted({w.order.instrument for w in self._working.values()}):
            out += self._work(key, until_ns)
        out.sort(key=lambda f: f.time)
        return out

    def force_fill(self, key: str, at: datetime, price: float, reason: str) -> Fill | None:
        """Close the whole position in ``key`` at ``price`` (used for delistings). Cancels its orders."""
        self.cancel_instrument(key)
        pos = self.position(key)
        if not pos:
            return None
        side = Side.SELL if pos > 0 else Side.BUY
        cost = self.costs.cost(self.spec(key), self.market, price, abs(pos), at, "market")
        self._positions[key] = 0.0
        return Fill(f"{reason}-{next(self._ids)}", key, at, side, abs(pos), float(price), cost,
                    {"reason": reason, "tag": reason, "how": "market"})

    # ---- working orders --------------------------------------------------------------
    def _event(self, w: _Working, b: _Bars, until_ns: int):
        """(bar index, price, reason) of the first bar where ``w`` fills, or None."""
        o = w.order
        i0 = int(np.searchsorted(b.start, w.active_from, "left"))
        i1 = int(np.searchsorted(b.end, until_ns, "right"))
        if o.type is OrderType.MARKET:
            # a market order fills at a bar's open, which is known once the bar has opened: with
            # daily bars the morning's fill is booked before that afternoon's decision
            i1 = int(np.searchsorted(b.start, until_ns, "right"))
        if o.expires is not None:
            i1 = min(i1, int(np.searchsorted(b.start, _ns(o.expires), "left")))
        if i0 >= i1:
            return None
        if o.type is OrderType.MARKET:
            return i0, float(b.open[i0]), "market"
        op, hi, lo = b.open[i0:i1], b.high[i0:i1], b.low[i0:i1]
        buy = o.side is Side.BUY
        if o.type is OrderType.STOP:
            s = float(o.stop_price)
            hit = (hi >= s) if buy else (lo <= s)
            if not hit.any():
                return None
            j = int(np.argmax(hit))
            gapped = (op[j] >= s) if buy else (op[j] <= s)
            return i0 + j, float(op[j]) if gapped else s, "stop_gap" if gapped and j > 0 else "stop"
        lim = float(o.limit_price)
        hit = (lo <= lim) if buy else (hi >= lim)
        if not hit.any():
            return None
        j = int(np.argmax(hit))
        better = (op[j] <= lim) if buy else (op[j] >= lim)
        return i0 + j, float(op[j]) if better else lim, "target" if o.parent else "limit"

    def _work(self, key: str, until_ns: int) -> list[Fill]:
        b = self.bars(key)
        spec = self.spec(key)
        out: list[Fill] = []
        while True:
            events = []
            for w in list(self._working.values()):
                if w.order.instrument != key or w.active_from is None:
                    continue
                ev = self._event(w, b, until_ns)
                if ev is not None:
                    events.append((ev[0], _PRIORITY[w.order.type], w.seq, ev, w))
                elif w.order.expires is not None and until_ns >= _ns(w.order.expires):
                    self.cancel(w.order.id)
                    self.log.append((w.order.expires, f"order {w.order.id} on {key} expired unfilled"))
            if not events:
                return out
            events.sort(key=lambda e: e[:3])
            idx, _, _, (_, price, reason), w = events[0]
            o = w.order
            # one bar touching a stop and its sibling target: the stop is taken
            if reason in ("stop", "stop_gap") and o.parent is not None:
                for sid in self._children.get(o.parent, []):
                    sib = self._working.get(sid)
                    if sib is not None and sib is not w and sib.active_from is not None:
                        ev = self._event(sib, b, until_ns)
                        if ev is not None and ev[0] == idx:
                            reason = "stop_both_touched"
            qty = o.quantity
            pos = self.position(key)
            if o.reduce_only:
                closing = pos * int(o.side) < 0
                qty = min(qty, abs(pos)) if closing else 0.0
            self._working.pop(o.id, None)
            if qty <= 0:
                continue
            at = _dt(b.start[idx])
            how = {"market": "market", "limit": "limit", "target": "limit"}.get(reason, "stop")
            cost = self.costs.cost(spec, self.market, price, qty, at, how)
            fill = Fill(o.id, key, at, o.side, qty, price, cost,
                        {"reason": reason, "tag": o.tag, "how": how, "decided": _dt(w.decided)})
            out.append(fill)
            new_pos = pos + int(o.side) * qty
            self._positions[key] = new_pos
            # bracket bookkeeping
            if o.parent is not None:  # an exit filled: cancel its sibling
                for sid in self._children.pop(o.parent, []):
                    self._working.pop(sid, None)
            for cid in self._children.get(o.id, []):
                c = self._working.get(cid)
                if c is None:
                    continue
                c.order.quantity = qty
                if c.order.offset is not None:
                    level = price + int(c.order.side) * c.order.offset  # stop: beyond the entry, against you
                    if c.order.type is OrderType.LIMIT:
                        c.order.limit_price = price - int(c.order.side) * c.order.offset
                    else:
                        c.order.stop_price = level
                c.active_from = int(b.start[idx]) if reason == "market" else int(b.end[idx])
            if o.id in self._children and o.parent is None:
                self._children[o.id] = [c for c in self._children[o.id] if c in self._working]
            if new_pos == 0:  # flat: resting exits have nothing left to protect
                for wid, ww in list(self._working.items()):
                    if ww.order.instrument == key and ww.order.reduce_only and ww.active_from is not None:
                        self._working.pop(wid, None)
