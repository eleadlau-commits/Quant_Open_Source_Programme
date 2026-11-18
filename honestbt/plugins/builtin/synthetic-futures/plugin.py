"""Synthetic index-futures minute bars (Nasdaq-100 style: NQ / MNQ).

Futures trade almost around the clock, so unlike the equity generator this one
produces the full CME Globex session: 18:00 the evening before to 17:00, with
the one-hour daily halt. Higher-timeframe indicators such as a 15-minute
EMA200 need those overnight bars; a chart of NQ shows them too.

By default there is **no edge**: a random walk with a realistic intraday
volatility profile (quiet overnight, a burst at the 09:30 New York open) and
volatility clustering across days. Two planted edges exist only to test the
testers:

* ``orb_momentum``: after the opening box closes, the rest of the regular
  session drifts in the direction of the box's net move, by ``orb_momentum``
  times that move. An opening range breakout strategy should then show an edge.
* ``trend_strength``: a slowly varying (persistent) daily drift, so that a
  trend filter has something real to find.

Prices are rounded to the 0.25-point tick.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from honestbt.sdk import MarketData, Param, register


TICK = 0.25


def _profile(mins: np.ndarray) -> np.ndarray:
    """Relative per-minute volatility by minute of day (ET)."""
    v = np.full(len(mins), 0.35)  # Asia overnight
    v[(mins >= 3 * 60) & (mins < 9 * 60 + 30)] = 0.6  # London
    v[(mins >= 8 * 60 + 30) & (mins < 8 * 60 + 35)] = 1.5  # 08:30 data releases
    rth = (mins >= 9 * 60 + 30) & (mins < 16 * 60)
    t = (mins[rth] - (9 * 60 + 30)) / 390.0
    v[rth] = 1.0 + 1.6 * np.exp(-t / 0.08) + 0.4 * t**4
    v[(mins >= 16 * 60) & (mins < 17 * 60)] = 0.5
    return v


@register("data", "synthetic_futures", params=[
    Param("symbol", "str", "MNQ", "Contract name (prices identical for NQ and MNQ)"),
    Param("n_days", "int", 250, "Number of trading days"),
    Param("start", "str", "2024-01-02", "First trading day"),
    Param("seed", "int", 11, "Random seed"),
    Param("price", "float", 18000.0, "Starting index level"),
    Param("ann_vol", "float", 0.22, "Average annualised volatility"),
    Param("orb_momentum", "float", 0.0, "Planted edge: post-box drift per unit of box move (0 = no edge)"),
    Param("box_end", "str", "09:45", "Box end used by the planted orb_momentum edge"),
    Param("trend_strength", "float", 0.0, "Planted edge: std of a persistent daily drift, in daily vols"),
], doc="Random-walk Globex-session minute bars for a Nasdaq futures contract.")
def synthetic_futures(symbol="MNQ", n_days=250, start="2024-01-02", seed=11, price=18000.0, ann_vol=0.22,
                      orb_momentum=0.0, box_end="09:45", trend_strength=0.0) -> MarketData:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days).values.astype("datetime64[D]")
    mins = np.r_[np.arange(18 * 60, 24 * 60), np.arange(0, 17 * 60)]  # 18:00 prev day .. 16:59
    offs = np.r_[np.arange(18 * 60, 24 * 60) - 24 * 60, np.arange(0, 17 * 60)].astype("timedelta64[m]")
    prof = _profile(mins)
    prof = prof / np.sqrt(np.sum(prof**2))  # unit daily variance
    d_vol = ann_vol / np.sqrt(252)
    bh, bm = (int(x) for x in box_end.split(":"))
    i_open = int(np.flatnonzero(mins == 9 * 60 + 30)[0])
    i_box = int(np.flatnonzero(mins == bh * 60 + bm)[0])
    i_close = int(np.flatnonzero(mins == 16 * 60)[0])

    log_v, drift = 0.0, 0.0
    ts_parts, rows = [], []
    p = float(price)
    for d in days:
        log_v = 0.9 * log_v + rng.normal(0, 0.25)  # volatility clustering
        dv = d_vol * np.exp(log_v - 0.25**2 / (2 * (1 - 0.81)))
        drift = 0.98 * drift + rng.normal(0, trend_strength * np.sqrt(1 - 0.98**2))
        sig = dv * prof
        r = rng.standard_t(5, len(mins)) * sig * np.sqrt(3 / 5) + drift * dv / len(mins)
        if orb_momentum:
            box_move = float(np.sum(r[i_open:i_box]))
            n = i_close - i_box
            r[i_box:i_close] += orb_momentum * box_move / n
        closes = p * np.exp(np.cumsum(r))
        opens = np.r_[p, closes[:-1]]
        wick = np.abs(rng.normal(0, 1, len(mins))) * sig * closes * 0.6
        highs = np.maximum(opens, closes) + wick
        lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 1, len(mins))) * sig * closes * 0.6
        o, h, l, c = (np.round(x / TICK) * TICK for x in (opens, highs, lows, closes))
        h, l = np.maximum.reduce([h, o, c]), np.minimum.reduce([l, o, c])
        vol = np.round(200 * prof / prof.mean() * rng.lognormal(0, 0.4, len(mins)))
        p = float(c[-1])
        ts_parts.append(d.astype("datetime64[m]") + offs)
        rows.append(np.column_stack([o, h, l, c, vol]))
    idx = pd.DatetimeIndex(np.concatenate(ts_parts).astype("datetime64[ns]"))
    df = pd.DataFrame(np.vstack(rows), index=idx, columns=["open", "high", "low", "close", "volume"])
    return MarketData({symbol: df}, name=f"synthetic_futures({symbol}, seed={seed}, orb_momentum={orb_momentum})")
