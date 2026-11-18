"""Built-in feature plugins ("variable constructors").

A feature is ``f(view, symbol, **params) -> float``. It only ever sees a
:class:`GuardedView`, so whatever it computes was knowable at decision time.
Return ``nan`` when there is not enough history.
"""
from __future__ import annotations

import hashlib

import numpy as np

from .registry import Param, register

NAN = float("nan")


@register("feature", "premarket_gap", doc="Last pre-market price today vs yesterday's close, as a fraction.")
def premarket_gap(view, symbol):
    d = view.daily(symbol)
    pm = view.premarket_last(symbol)
    if len(d) == 0 or not np.isfinite(pm):
        return NAN
    return pm / d.close[-1] - 1.0


@register("feature", "last_close", doc="Most recent completed daily close.")
def last_close(view, symbol):
    d = view.daily(symbol)
    return float(d.close[-1]) if len(d) else NAN


@register("feature", "avg_dollar_volume", params=[Param("window", "int", 20, "Days")],
          doc="Average regular-session dollar volume over the last N completed days.")
def avg_dollar_volume(view, symbol, window=20):
    d = view.daily(symbol)
    if len(d) < max(3, window // 2):
        return NAN
    return float(np.mean(d.dollar_volume[-window:]))


@register("feature", "realized_vol", params=[Param("window", "int", 20, "Days")],
          doc="Annualised standard deviation of daily close-to-close log returns.")
def realized_vol(view, symbol, window=20):
    d = view.daily(symbol)
    if len(d) < window + 1:
        return NAN
    r = np.diff(np.log(d.close[-(window + 1):]))
    return float(np.std(r, ddof=1) * np.sqrt(252))


@register("feature", "atr", params=[Param("window", "int", 14, "Days")],
          doc="Average true range in price units over the last N completed days.")
def atr(view, symbol, window=14):
    d = view.daily(symbol)
    if len(d) < window + 1:
        return NAN
    h, l, c = d.high[-window:], d.low[-window:], d.close[-(window + 1):-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - c), np.abs(l - c)))
    return float(np.mean(tr))


@register("feature", "atr_pct", params=[Param("window", "int", 14, "Days")],
          doc="ATR divided by last close.")
def atr_pct(view, symbol, window=14):
    a, c = atr(view, symbol, window), last_close(view, symbol)
    return a / c if np.isfinite(a) and c > 0 else NAN


@register("feature", "trailing_return", params=[Param("window", "int", 5, "Days")],
          doc="Close-to-close return over the last N completed days.")
def trailing_return(view, symbol, window=5):
    d = view.daily(symbol)
    if len(d) < window + 1:
        return NAN
    return float(d.close[-1] / d.close[-(window + 1)] - 1)


@register("feature", "random", params=[Param("seed", "int", 0, "Seed")],
          doc="Deterministic noise in [0,1). Rank by this to get a random-selection baseline.")
def random_score(view, symbol, seed=0):
    h = hashlib.blake2b(f"{seed}|{symbol}|{view.as_of}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2**64


# ---- intraday features (opening range breakout family) -------------------

MIN = np.timedelta64(1, "m")


def _hhmm(s: str) -> np.timedelta64:
    h, m = (int(x) for x in str(s).split(":"))
    return np.timedelta64(h * 60 + m, "m")


@register("feature", "opening_range", params=[
    Param("start", "str", "09:30", "Box start (HH:MM, exchange time); first bar included"),
    Param("end", "str", "09:45", "Box end (HH:MM); bars starting before this are included"),
    Param("side", "str", "high", "high | low | height", choices=["high", "low", "height"]),
], doc="High, low or height of today's box between two clock times. Only knowable once the box has closed.")
def opening_range(view, symbol, start="09:30", end="09:45", side="high"):
    day = view.today.astype("datetime64[m]")
    t0, t1 = day + _hhmm(start), day + _hhmm(end)
    # Asking for bars up to t1 before t1 has passed raises LookAheadError.
    ts, bars = view.minute(symbol, start=t0, end=t1, with_ts=True)
    if len(bars) == 0:
        return NAN
    hi, lo = float(np.max(bars[:, 1])), float(np.min(bars[:, 2]))
    return {"high": hi, "low": lo, "height": hi - lo}[side]


def resample_closes(ts: np.ndarray, closes: np.ndarray, minutes: int, as_of) -> np.ndarray:
    """Closes of completed N-minute candles (clock-aligned) ending by ``as_of``."""
    if len(ts) == 0:
        return closes[:0]
    m = ts.astype("datetime64[m]").astype(np.int64)
    bucket = m // minutes
    last = np.r_[bucket[1:] != bucket[:-1], True]
    out_b, out_c = bucket[last], closes[last]
    as_of_m = np.datetime64(as_of, "m").astype(np.int64)
    done = (out_b + 1) * minutes <= as_of_m  # drop the candle still forming
    return out_c[done]


def ema_last(x: np.ndarray, span: float) -> float:
    a = 2.0 / (span + 1.0)
    e = float(x[0])
    for v in x[1:]:
        e += a * (float(v) - e)
    return e


@register("feature", "htf_ema_spread", params=[
    Param("timeframe", "int", 15, "Candle size in minutes for the EMAs"),
    Param("fast", "int", 50, "Fast EMA length (candles)"),
    Param("slow", "int", 200, "Slow EMA length (candles)"),
    Param("warmup", "float", 3.0, "History used = warmup x slow candles (EMAs converge)"),
], doc="Fast EMA minus slow EMA on completed higher-timeframe candles: > 0 is an uptrend, < 0 a downtrend.")
def htf_ema_spread(view, symbol, timeframe=15, fast=50, slow=200, warmup=3.0):
    ts, bars = view.minute(symbol, with_ts=True)
    n = int(slow * warmup * timeframe * 1.2) + timeframe
    c = resample_closes(ts[-n:], bars[-n:, 3], int(timeframe), view.as_of)
    if len(c) < slow:
        return NAN
    c = c[-int(slow * warmup):]
    return ema_last(c, fast) - ema_last(c, slow)
