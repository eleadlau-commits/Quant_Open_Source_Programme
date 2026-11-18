"""Daily features ("variable constructors") built from completed daily bars.

A feature is ``f(view, symbol, **params) -> float``. It only ever sees a
guarded view, so whatever it computes was knowable at decision time.
Return ``nan`` when there is not enough history.
"""
from __future__ import annotations

import hashlib

import numpy as np

from honestbt.sdk import NAN, Param, register


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

