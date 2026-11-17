"""In-memory market data: minute bars per symbol plus derived daily bars.

Conventions (kept deliberately simple and explicit):

* Timestamps are naive ``datetime64[ns]`` in US/Eastern exchange time.
* A minute bar is labelled by its **start** time. The 09:30 bar covers
  09:30:00-09:30:59 and is only *known* at 09:31.
* Regular session is 09:30-16:00. Bars before 09:30 are pre-market.
* A symbol's data simply stops when it is delisted. Delisted symbols must stay
  in the dataset, otherwise every "top gainers" result is survivorship-biased.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

MINUTE = np.timedelta64(1, "m")
COLUMNS = ("open", "high", "low", "close", "volume")
OPEN_MIN = 9 * 60 + 30
CLOSE_MIN = 16 * 60


@dataclass(frozen=True)
class DailyBars:
    """Regular-session daily bars as numpy arrays (one row per trading day)."""

    date: np.ndarray  # datetime64[D]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    dollar_volume: np.ndarray

    def __len__(self) -> int:
        return len(self.date)

    def head(self, n: int) -> "DailyBars":
        return DailyBars(*(getattr(self, f)[:n] for f in self.__dataclass_fields__))


def monday_week(days: np.ndarray) -> np.ndarray:
    """Week number with weeks starting on Monday.

    (numpy's ``datetime64[W]`` weeks start on Thursday, the 1970 epoch weekday.)
    """
    return (days.astype("datetime64[D]").astype(np.int64) + 3) // 7


def minutes_of_day(ts: np.ndarray) -> np.ndarray:
    return _minutes_of_day(ts)


def _minutes_of_day(ts: np.ndarray) -> np.ndarray:
    day = ts.astype("datetime64[D]")
    return ((ts - day) // MINUTE).astype(np.int64)


def build_daily(ts: np.ndarray, arr: np.ndarray) -> DailyBars:
    mod = _minutes_of_day(ts)
    reg = (mod >= OPEN_MIN) & (mod < CLOSE_MIN)
    if not reg.any():
        empty = np.array([], dtype=float)
        return DailyBars(np.array([], dtype="datetime64[D]"), *(empty,) * 6)
    df = pd.DataFrame(arr[reg], columns=COLUMNS)
    df["date"] = ts[reg].astype("datetime64[D]")
    df["dv"] = df["close"] * df["volume"]
    g = df.groupby("date", sort=True)
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum"), dv=("dv", "sum"))
    return DailyBars(
        out.index.values.astype("datetime64[D]"),
        out["open"].to_numpy(float), out["high"].to_numpy(float), out["low"].to_numpy(float),
        out["close"].to_numpy(float), out["volume"].to_numpy(float), out["dv"].to_numpy(float),
    )


class MarketData:
    """Container the engine and guarded views read from.

    Never hand this object to strategy/feature code directly; wrap it in a
    :class:`~honestbt.data.guard.GuardedView` pinned to the decision time.
    """

    def __init__(self, minute: dict[str, pd.DataFrame], name: str = ""):
        self.name = name
        self.symbols: list[str] = sorted(minute)
        self.ts: dict[str, np.ndarray] = {}
        self.arr: dict[str, np.ndarray] = {}
        self.daily: dict[str, DailyBars] = {}
        days: set = set()
        for s in self.symbols:
            df = minute[s].sort_index()
            ts = df.index.values.astype("datetime64[ns]")
            arr = df[list(COLUMNS)].to_numpy(dtype=float)
            self.ts[s], self.arr[s] = ts, arr
            self.daily[s] = build_daily(ts, arr)
            days.update(self.daily[s].date.tolist())
        self.trading_days = np.array(sorted(days), dtype="datetime64[D]")
        # Shared cache for feature values; keys include the decision time, so it
        # can never leak information across time.
        self.feature_cache: dict = {}

    def first_date(self, symbol: str):
        d = self.daily[symbol].date
        return d[0] if len(d) else None

    def last_date(self, symbol: str):
        d = self.daily[symbol].date
        return d[-1] if len(d) else None

    def previous_trading_day(self, day: np.datetime64):
        i = np.searchsorted(self.trading_days, day, "left")
        return self.trading_days[i - 1] if i > 0 else None

    def __repr__(self) -> str:
        n = sum(len(t) for t in self.ts.values())
        return f"MarketData({self.name!r}, {len(self.symbols)} symbols, {n:,} minute bars)"
