"""Complementary data C_j(t): series that sit next to the prices.

A complementary plugin is ``f(market, **params) -> {name: Series or DataFrame}``.
Every value is indexed by the time it became **known** (published), not the
period it describes: quarterly income for Q1 is known when it is reported in
late April, not on 31 March. Strategies read it with ``F.series(name, symbol)``
or ``F.series_last(name, symbol)``, which only return values known at decision time.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from honestbt.sdk import Param, register


@register("complementary", "csv_series", params=[
    Param("path", "str", "data/series.csv", "CSV file to read"),
    Param("name", "str", "series", "Name strategies use to read it, e.g. 'news_sentiment'"),
    Param("time_column", "str", "time", "Column with the time each value became known (exchange time)"),
    Param("value_column", "str", "value", "Column with the value"),
    Param("symbol_column", "str", None, "Optional column with the symbol, for per-symbol data"),
], doc="Your own series from a CSV file (news scores, events, income...), indexed by when each value became known.")
def csv_series(market, path="data/series.csv", name="series", time_column="time", value_column="value",
               symbol_column=None):
    df = pd.read_csv(Path(path))
    df[time_column] = pd.to_datetime(df[time_column])
    if symbol_column:
        wide = df.pivot_table(index=time_column, columns=symbol_column, values=value_column, aggfunc="last")
        return {name: wide.sort_index()}
    return {name: df.set_index(time_column)[value_column].sort_index()}


@register("complementary", "synthetic_events", params=[
    Param("name", "str", "earnings_surprise", "Name strategies use to read it"),
    Param("every_days", "int", 63, "Roughly how often each company reports (trading days)"),
    Param("seed", "int", 0, "Random seed"),
], doc="Made-up quarterly earnings surprises per symbol, published at 08:00 on report days (for testing).")
def synthetic_events(market, name="earnings_surprise", every_days=63, seed=0):
    rng = np.random.default_rng(seed)
    days = market.trading_days
    rows = {}
    for s in market.symbols:
        first, last = market.first_date(s), market.last_date(s)
        if first is None:
            continue
        live = days[(days >= first) & (days <= last)]
        if len(live) == 0:
            continue
        start = int(rng.integers(0, max(1, min(every_days, len(live)))))
        for i in range(start, len(live), every_days):
            t = pd.Timestamp(live[i]) + pd.Timedelta(hours=8)  # before the open: known from 08:00
            rows.setdefault(t, {})[s] = float(np.round(rng.normal(0, 0.05), 4))
    wide = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    return {name: wide}
