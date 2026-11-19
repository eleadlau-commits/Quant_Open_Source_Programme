"""The default strategy: spread the money evenly across everything in the dataset and hold.

Each day the account is split equally across every symbol that traded the day
before and today (so names that list later join, and delisted names stay in
until their last trading day). The day's return is the average close-to-close
return of those symbols. No trading costs: it is a yardstick, not a strategy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def hold_everything(data) -> pd.Series:
    """Growth of 1, indexed by trading day (as Timestamps)."""
    closes = {}
    for s in data.symbols:
        d = data.daily[s]
        if len(d):
            closes[s] = pd.Series(d.close, index=pd.to_datetime(d.date))
    if not closes:
        return pd.Series(dtype=float)
    px = pd.DataFrame(closes).sort_index()
    rets = px / px.shift(1) - 1  # NaN where a symbol didn't trade on either day
    daily = rets.mean(axis=1, skipna=True).fillna(0.0)
    eq = (1 + daily).cumprod()
    eq.iloc[0] = 1.0
    return eq.astype(float)


def to_json(eq: pd.Series) -> dict:
    return {"t": [str(t) for t in eq.index], "v": np.round(eq.to_numpy(float), 6).tolist()}
