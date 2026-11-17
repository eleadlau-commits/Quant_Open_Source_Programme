"""Look-ahead guard.

A :class:`GuardedView` is the *only* window strategy, feature and mapping code
gets onto market data. It is pinned to a decision time ``as_of`` and refuses to
return anything that was not knowable at that instant:

* a minute bar starting at ``t`` is visible only if ``t + 1min <= as_of``;
* a daily bar for day ``d`` is visible only once day ``d`` has closed (16:00);
* the tradable universe is "listed and not yet known to be delisted", which
  keeps future delistings in the candidate set (no survivorship bias);
* explicitly asking for data past ``as_of`` raises :class:`LookAheadError`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .model import CLOSE_MIN, MINUTE, OPEN_MIN, DailyBars, MarketData


class LookAheadError(RuntimeError):
    """Raised when code asks for data that did not exist yet at decision time."""


class GuardedView:
    def __init__(self, data: MarketData, as_of):
        self._data = data
        self.as_of = np.datetime64(pd.Timestamp(as_of), "ns")
        self.today = self.as_of.astype("datetime64[D]")
        self._mod = int((self.as_of - self.today) // MINUTE)
        self._universe: list[str] | None = None

    @property
    def trading_days(self) -> np.ndarray:
        """Exchange calendar (published in advance, so not look-ahead)."""
        return self._data.trading_days

    # ---- universe -------------------------------------------------------
    def universe(self) -> list[str]:
        if self._universe is None:
            prev = self._data.previous_trading_day(self.today)
            out = []
            for s in self._data.symbols:
                first, last = self._data.first_date(s), self._data.last_date(s)
                if first is None or first >= self.today:
                    continue  # not listed yet (no completed session)
                if prev is not None and last < prev:
                    continue  # stopped trading before yesterday: known delisted
                out.append(s)
            self._universe = out
        return list(self._universe)

    # ---- daily ----------------------------------------------------------
    def daily(self, symbol: str) -> DailyBars:
        d = self._data.daily[symbol]
        last_visible = self.today if self._mod >= CLOSE_MIN else self.today - np.timedelta64(1, "D")
        n = int(np.searchsorted(d.date, last_visible, "right"))
        return d.head(n)

    # ---- minute ---------------------------------------------------------
    def minute(self, symbol: str, start=None, end=None) -> np.ndarray:
        """Minute bars (open, high, low, close, volume) whose bar *ends* by ``end``.

        ``end`` defaults to ``as_of``; asking for a later end raises.
        """
        end = self.as_of if end is None else np.datetime64(pd.Timestamp(end), "ns")
        if end > self.as_of:
            raise LookAheadError(f"requested minute bars up to {end}, but decision time is {self.as_of}")
        ts, arr = self._data.ts[symbol], self._data.arr[symbol]
        hi = int(np.searchsorted(ts, end - MINUTE, "right"))
        lo = 0 if start is None else int(np.searchsorted(ts, np.datetime64(pd.Timestamp(start), "ns"), "left"))
        return arr[lo:hi]

    def premarket_last(self, symbol: str) -> float:
        """Last pre-market trade price today that is visible at ``as_of``."""
        ts = self._data.ts[symbol]
        day_start = self.today.astype("datetime64[ns]")
        open_t = day_start + OPEN_MIN * MINUTE
        cutoff = min(self.as_of, open_t)
        lo = int(np.searchsorted(ts, day_start, "left"))
        hi = int(np.searchsorted(ts, cutoff - MINUTE, "right"))
        if hi <= lo:
            return float("nan")
        return float(self._data.arr[symbol][hi - 1, 3])
