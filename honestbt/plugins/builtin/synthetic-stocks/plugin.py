"""Synthetic minute-bar market for development and for testing the evaluators.

By default the generator has **no edge**: overnight gaps carry no information
about the rest of the week, so an honest evaluator suite should fail any gap
strategy run on it. Setting ``gap_momentum`` > 0 plants a known edge (stocks
that gap up keep drifting up during the session), which the suite should then
detect. That pair of checks is how we test the testers.

The generator also includes things real data has and naive backtests ignore:
penny stocks, illiquid names, IPOs part-way through, and delistings after a
crash.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from honestbt.sdk import MarketData, Param, register


PRE_START = 9 * 60  # first pre-market bar at 09:00 (keeps data small)
OPEN = 9 * 60 + 30
CLOSE = 16 * 60


@register("data", "synthetic", params=[
    Param("n_symbols", "int", 40, "Number of tickers"),
    Param("n_days", "int", 130, "Number of trading days"),
    Param("start", "str", "2024-01-01", "First calendar day"),
    Param("seed", "int", 7, "Random seed"),
    Param("gap_momentum", "float", 0.0, "Planted edge: intraday drift per unit of overnight gap (0 = no edge)"),
    Param("delist_frac", "float", 0.1, "Fraction of names that crash and delist"),
], doc="Random-walk minute bars with pre-market, gaps, penny stocks and delistings.")
def synthetic(n_symbols=40, n_days=130, start="2024-01-01", seed=7, gap_momentum=0.0, delist_frac=0.1) -> MarketData:
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days).values.astype("datetime64[D]")
    pre = np.arange(PRE_START, OPEN)
    reg = np.arange(OPEN, CLOSE)
    mins = np.concatenate([pre, reg])
    n_pre, n_reg = len(pre), len(reg)
    u_shape = 1.0 + 2.0 * ((np.linspace(-1, 1, n_reg)) ** 2)  # intraday volume smile

    minute: dict[str, pd.DataFrame] = {}
    for k in range(n_symbols):
        sym = f"SYN{k:03d}"
        price = float(np.exp(rng.uniform(np.log(1.5), np.log(250))))
        ann_vol = float(np.exp(rng.normal(np.log(0.45), 0.4)))
        base_shares = float(np.exp(rng.normal(np.log(3e5), 1.2)))
        d_vol = ann_vol / np.sqrt(252)
        m_vol = d_vol * 0.8 / np.sqrt(n_reg)
        gap_vol = d_vol * 0.6
        first = int(rng.integers(0, n_days // 3)) if rng.random() < 0.2 else 0  # some IPO later
        last = n_days
        crash = rng.random() < delist_frac
        if crash:
            last = int(rng.integers(first + 30, n_days)) if first + 30 < n_days else n_days

        ts_parts, rows = [], []
        for di in range(first, last):
            # overnight gap (fat-tailed), revealed gradually in pre-market
            gap = gap_vol * rng.standard_t(3)
            if crash and di > last - 10:
                gap -= 0.08
            prev = price
            pm_target = prev * np.exp(gap)
            pm_path = prev * np.exp(np.linspace(0, gap, n_pre) + rng.normal(0, gap_vol * 0.15, n_pre))
            pm_path[-1] = pm_target
            # regular session; optional planted edge: drift proportional to gap
            drift = gap_momentum * gap / n_reg
            r = rng.normal(drift, m_vol, n_reg)
            closes = pm_target * np.exp(np.cumsum(r))
            closes_all = np.concatenate([pm_path, closes])
            opens_all = np.concatenate([[prev], closes_all[:-1]])
            spread = np.abs(rng.normal(0, m_vol, len(mins))) * closes_all
            highs = np.maximum(opens_all, closes_all) + spread
            lows = np.minimum(opens_all, closes_all) - spread
            vol = np.concatenate([
                base_shares * 0.002 * rng.random(n_pre),
                base_shares / n_reg * u_shape * rng.lognormal(0, 0.5, n_reg),
            ])
            price = float(closes_all[-1])
            ts_parts.append(days[di].astype("datetime64[m]") + mins.astype("timedelta64[m]"))
            rows.append(np.column_stack([opens_all, highs, lows, closes_all, vol]))
        if not rows:
            continue
        idx = pd.DatetimeIndex(np.concatenate(ts_parts).astype("datetime64[ns]"))
        minute[sym] = pd.DataFrame(np.vstack(rows), index=idx, columns=["open", "high", "low", "close", "volume"])
    return MarketData(minute, name=f"synthetic(seed={seed}, gap_momentum={gap_momentum})")
