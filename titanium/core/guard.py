"""The look-ahead guard: the only window strategy, feature and module code gets onto data.

A :class:`Guard` is pinned to a decision time ``as_of`` and refuses to return
anything that was not knowable at that instant:

* a minute bar starting at ``t`` is visible only once it has ended (``t + 1min <= as_of``);
* a daily bar is visible only once its session has closed (16:00 New York, or 13:00
  on early-close days);
* complementary and generated values are visible from the time they became known;
* the universe is "listed and not yet known to be delisted", so names that delist
  later stay in it (no survivorship bias);
* explicitly asking for data after ``as_of`` raises :class:`LookAheadError`.

Ported from the prototype's ``honestbt.data.guard``, with UTC timestamps and a real calendar.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from .bars import MarketData
from .data import Frequency, LookAheadError

ONE_MINUTE = pd.Timedelta(minutes=1)


def _ts(value, name: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (Titanium stores UTC), got {value!r}")
    return ts.tz_convert("UTC")


class Guard:
    """Implements :class:`~titanium.core.data.GuardedView` over :class:`MarketData`."""

    def __init__(self, data: MarketData, as_of: datetime | pd.Timestamp | str) -> None:
        self._data = data
        self._as_of = _ts(as_of, "as_of")
        self.market = data.market
        self.today: date = self._as_of.tz_convert(self.market.tz).date()
        self._universe: list[str] | None = None

    @property
    def as_of(self) -> datetime:
        return self._as_of.to_pydatetime()

    @property
    def calendar(self):
        """The exchange calendar (published in advance, so not look-ahead)."""
        return self.market.calendar

    def _previous_trading_day(self) -> date | None:
        cal = self.market.calendar
        if cal is None:
            return None
        if hasattr(cal, "previous_trading_day"):
            return cal.previous_trading_day(self.today)
        days = cal.trading_days(date(self.today.year - 1, 1, 1), self.today)
        days = [d for d in days if d < self.today]
        return days[-1] if days else None

    # ---- universe ------------------------------------------------------------
    def universe(self) -> list[str]:
        if self._universe is None:
            prev = self._previous_trading_day()
            out = []
            for key in self._data.instruments:
                span = self._data.span(key)
                if span is None:
                    continue
                first, last = span
                if first >= self.today:
                    continue  # not listed yet (no completed session before today)
                if prev is not None and last < prev:
                    continue  # missed a whole session already: known to be delisted
                out.append(key)
            self._universe = out
        return list(self._universe)

    # ---- bars ------------------------------------------------------------------
    def bars(self, instrument: str, frequency: Frequency | str = Frequency.MINUTE,
             start=None, end=None) -> pd.DataFrame:
        frequency = Frequency(frequency)
        end_ts = self._as_of if end is None else _ts(end, "end")
        if end_ts > self._as_of:
            raise LookAheadError(f"asked for bars up to {end_ts}, but the decision time is {self._as_of}")
        start_ts = None if start is None else _ts(start, "start")
        if start_ts is not None and start_ts > self._as_of:
            raise LookAheadError(f"asked for bars from {start_ts}, after the decision time {self._as_of}")
        if frequency is Frequency.MINUTE:
            df = self._data.minute(instrument)
            hi = int(df.index.searchsorted(end_ts - ONE_MINUTE, "right"))
            lo = 0 if start_ts is None else int(df.index.searchsorted(start_ts, "left"))
            return df.iloc[lo:hi]
        df = self._data.daily(instrument)
        visible = df[df["end"] <= end_ts]
        if start_ts is not None:
            visible = visible[visible["end"] > start_ts]
        return visible

    def minute(self, instrument: str, start=None, end=None) -> pd.DataFrame:
        return self.bars(instrument, Frequency.MINUTE, start, end)

    def daily(self, instrument: str, start=None, end=None) -> pd.DataFrame:
        return self.bars(instrument, Frequency.DAILY, start, end)

    def last_price(self, instrument: str) -> float:
        """Close of the latest bar that has ended (any session)."""
        df = self.minute(instrument)
        return float(df["close"].iloc[-1]) if len(df) else float("nan")

    def premarket_last(self, instrument: str) -> float:
        """Last pre-market price today visible at ``as_of`` (frozen once the regular session opens)."""
        df = self._data.minute(instrument)
        tz = self.market.tz
        day_start = pd.Timestamp(datetime.combine(self.today, datetime.min.time()), tz=tz).tz_convert("UTC")
        reg = self.market.session()
        open_t = pd.Timestamp(datetime.combine(self.today, reg.start), tz=tz).tz_convert("UTC")
        cutoff = min(self._as_of, open_t)
        lo = int(df.index.searchsorted(day_start, "left"))
        hi = int(df.index.searchsorted(cutoff - ONE_MINUTE, "right"))
        return float(df["close"].iloc[hi - 1]) if hi > lo else float("nan")

    # ---- complementary and generated data --------------------------------------------
    def series_names(self) -> list[str]:
        return self._data.series_names

    def series(self, name: str, instrument: str | None = None) -> pd.Series | pd.DataFrame:
        """Values known by ``as_of``, indexed by the time each became known.

        Per-instrument data needs ``instrument``; market-wide data (a ``value``
        column) comes back as a Series.
        """
        df = self._data.series(name)
        known = df.loc[: self._as_of]
        if list(known.columns) == ["value"]:
            return known["value"]
        if instrument is None:
            raise ValueError(f"{name!r} is per instrument: pass instrument=")
        if instrument not in known.columns:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC", name="known"))
        return known[instrument].dropna()

    def series_last(self, name: str, instrument: str | None = None, default=None):
        s = self.series(name, instrument)
        return s.iloc[-1] if len(s) else default

