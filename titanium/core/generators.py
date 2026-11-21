"""Generated-data generators that ship with the app (``Library.GENERATORS`` entries).

A generator reads a core dataset and makes series. Every value is stamped with the
time it could first have been computed (for daily features: the session close), so
the guard treats generated data exactly like complementary data.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .bars import MarketData
from .data import Param
from .plugins import Library, Registry


class RealisedVolatility:
    """Daily realised volatility from regular-session minute returns, averaged over a window.

    The value for day ``d`` uses minutes of day ``d`` and earlier, and becomes known at
    day ``d``'s close.
    """

    name = "realised_vol"
    title = "Realised volatility"
    doc = "Volatility measured from each day's minute returns, averaged over a window of days."
    params = [
        Param("window", "int", 20, "Window (days)", "How many days to average over.", minimum=1, maximum=500),
        Param("annualise", "bool", True, "Yearly figure", "Scale to a yearly volatility (x sqrt 252)."),
    ]

    def series_name(self, params: dict[str, Any]) -> str:
        return f"realised_vol_{int(params['window'])}d"

    def generate(self, data: MarketData, params: dict[str, Any]) -> dict[str, pd.DataFrame]:
        p = {q.name: params.get(q.name, q.default) for q in self.params}
        window = int(p["window"])
        cols = {}
        for key in data.instruments:
            if not data.has_minutes(key):
                continue
            daily = data.daily(key)
            if daily.empty:
                continue
            m = data.minute(key)
            local_day = m.index.tz_convert(data.market.tz).normalize().tz_localize(None)
            # regular-session minutes only: those inside a session that made a daily bar
            ends = daily["end"].reindex(local_day).to_numpy()
            starts = pd.DatetimeIndex(local_day).tz_localize(data.market.tz)
            reg = data.market.session()
            open_t = starts + pd.Timedelta(hours=reg.start.hour, minutes=reg.start.minute)
            mask = (~pd.isna(ends)) & np.asarray(m.index >= open_t.tz_convert("UTC")) \
                & np.asarray(m.index + pd.Timedelta(minutes=1) <= pd.DatetimeIndex(ends))
            closes = m["close"][mask]
            day = local_day[mask]
            r = np.log(closes).groupby(day).diff()
            var = (r ** 2).groupby(day).sum(min_count=1)
            vol = np.sqrt(var.rolling(window, min_periods=window).mean())
            if p["annualise"]:
                vol = vol * np.sqrt(252)
            vol.index = pd.DatetimeIndex(daily["end"].reindex(vol.index))
            cols[key] = vol
        frame = pd.DataFrame(cols).dropna(how="all")
        frame.index = pd.DatetimeIndex(frame.index, name="known").tz_convert("UTC")
        return {self.series_name(p): frame.sort_index()}


BUILTIN_GENERATORS = (RealisedVolatility,)


def register_generators(registry: Registry) -> None:
    have = {e.name for e in registry.entries(Library.GENERATORS)}
    for cls in BUILTIN_GENERATORS:
        if cls.name not in have:
            registry.add(Library.GENERATORS, cls.name, cls(), doc=cls.doc)
