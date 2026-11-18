"""Exit signals: "when has the trend properly reversed?"

A signal is ``f(path, ctx, **params) -> bool array`` over the minute bars of a
position, starting at the entry bar. ``out[i]`` means "at the close of bar i,
exit"; the engine fills at the next bar's open. ``out[i]`` may depend only on
``path[:i+1]`` and ``ctx``; the engine checks this by changing the future.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from honestbt.sdk import Param, register, run_signal


def _ema(x: np.ndarray, span: float) -> np.ndarray:
    if span <= 1:
        return x
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


@register("signal", "never", doc="Never exit early; hold until the strategy's time stop.")
def never(path, ctx):
    return np.zeros(len(path), dtype=bool)


@register("signal", "atr_trailing", params=[
    Param("k", "float", 1.0, "Exit when smoothed price falls k x ATR below its running peak"),
    Param("smooth", "float", 10, "EMA span (minutes) used to smooth out minute-level noise"),
    Param("atr_feature", "str", "atr14", "Feature name giving ATR in price units (known at entry)"),
], doc="Volatility-scaled trailing stop on a smoothed price: the default 'proper reversal'.")
def atr_trailing(path, ctx, k=1.0, smooth=10, atr_feature="atr14"):
    a = ctx.feature(atr_feature)
    if not np.isfinite(a) or a <= 0:
        a = 0.02 * ctx.entry_price
    s = _ema(path.close, smooth)
    peak = np.maximum.accumulate(s)
    return s < peak - k * a


@register("signal", "ema_cross", params=[
    Param("fast", "float", 10, "Fast EMA span (minutes)"),
    Param("slow", "float", 40, "Slow EMA span (minutes)"),
    Param("warmup", "int", 15, "Ignore the first N bars"),
], doc="Exit when the fast EMA crosses below the slow EMA.")
def ema_cross(path, ctx, fast=10, slow=40, warmup=15):
    f, s = _ema(path.close, fast), _ema(path.close, slow)
    out = f < s
    out[: int(warmup)] = False
    return out


@register("signal", "heikin_ashi", params=[
    Param("n_red", "int", 5, "Consecutive bearish Heikin-Ashi candles"),
    Param("bar_minutes", "int", 5, "Resample to N-minute candles first (noise reduction)"),
], doc="Exit after N consecutive bearish Heikin-Ashi candles.")
def heikin_ashi(path, ctx, n_red=5, bar_minutes=5):
    n = len(path)
    m = max(1, int(bar_minutes))
    # causal resample: candle j closes at bar (j+1)*m - 1
    ends = np.arange(m - 1, n, m)
    if len(ends) == 0:
        return np.zeros(n, dtype=bool)
    starts = ends - (m - 1)
    o = path.open[starts]
    c = path.close[ends]
    full = ends[-1] + 1  # drop the trailing partial candle so it cannot leak
    h = np.maximum.reduceat(path.high[:full], starts)
    l = np.minimum.reduceat(path.low[:full], starts)
    ha_c = (o + h + l + c) / 4
    ha_o = np.empty_like(ha_c)
    ha_o[0] = (o[0] + c[0]) / 2
    for j in range(1, len(ha_c)):
        ha_o[j] = (ha_o[j - 1] + ha_c[j - 1]) / 2
    red = (ha_c < ha_o).astype(int)
    run = np.zeros(len(red), dtype=int)
    for j in range(len(red)):
        run[j] = run[j - 1] + 1 if red[j] and j > 0 else red[j]
    out = np.zeros(n, dtype=bool)
    out[ends[run >= int(n_red)]] = True
    return out


@register("signal", "time_stop", params=[
    Param("minutes", "float", 60, "Exit after holding this many minutes (map it from volatility!)"),
], doc="Exit after a fixed holding time, e.g. 'sell 5 minutes after the open'.")
def time_stop(path, ctx, minutes=60):
    return path.minutes_held >= minutes - 1  # signal at close of bar -> fill at next open


@register("signal", "any_of", params=[
    Param("signals", "json", [], "List of {plugin, params} specs; exit on the first that fires"),
], doc="Combine signals: exit when any of them fires.")
def any_of(path, ctx, signals=()):
    out = np.zeros(len(path), dtype=bool)
    for spec in signals:
        out |= run_signal(spec, path, ctx)
    return out

