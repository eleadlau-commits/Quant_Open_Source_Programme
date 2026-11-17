"""Local Parquet cache: ``<root>/minute/<SYMBOL>.parquet``.

Each file has a datetime index (or a ``timestamp`` column) in US/Eastern
exchange time and columns open, high, low, close, volume. Prices should be
split-adjusted, otherwise a 4:1 split shows up as a -75% "gap".
``scripts/download_polygon.py`` writes this layout.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..registry import Param, register
from .model import MarketData


@register("data", "parquet", params=[
    Param("root", "str", "data", "Cache directory"),
    Param("symbols", "json", None, "Optional list of symbols to load (default: all files)"),
    Param("start", "str", None, "Optional first date"),
    Param("end", "str", None, "Optional last date"),
], doc="Minute bars cached locally as one Parquet file per symbol.")
def parquet(root="data", symbols=None, start=None, end=None) -> MarketData:
    folder = Path(root) / "minute"
    files = sorted(folder.glob("*.parquet"))
    if symbols:
        wanted = set(symbols)
        files = [f for f in files if f.stem in wanted]
    if not files:
        raise FileNotFoundError(f"no parquet files under {folder}")
    minute = {}
    for f in files:
        df = pd.read_parquet(f)
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("America/New_York").tz_localize(None)
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index < pd.Timestamp(end) + pd.Timedelta(days=1)]
        if len(df):
            minute[f.stem] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return MarketData(minute, name=f"parquet({root})")
