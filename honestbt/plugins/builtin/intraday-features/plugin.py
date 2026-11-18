"""Intraday features: the opening box and higher-timeframe EMA trend.

Both only see the guarded view, so asking for a box before it has closed
raises LookAheadError instead of quietly peeking.
"""
from __future__ import annotations

import numpy as np

from honestbt.sdk import NAN, Param, hhmm, register


@register("feature", "opening_range", params=[
    Param("start", "str", "09:30", "Box start (HH:MM, exchange time); first bar included"),
    Param("end", "str", "09:45", "Box end (HH:MM); bars starting before this are included"),
    Param("side", "str", "high", "high | low | height", choices=["high", "low", "height"]),
], doc="High, low or height of today's box between two clock times. Only knowable once the box has closed.")
def opening_range(view, symbol, start="09:30", end="09:45", side="high"):
    day = view.today.astype("datetime64[m]")
    t0, t1 = day + hhmm(start), day + hhmm(end)
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

