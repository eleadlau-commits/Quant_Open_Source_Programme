import numpy as np
import pandas as pd
import pytest

from honestbt.sdk import GuardedView
from honestbt.runner import load_data


def test_events_are_only_visible_once_published(tmp_path):
    spec = {"plugin": "synthetic", "params": {"n_symbols": 6, "n_days": 80, "seed": 2},
            "complementary": [{"plugin": "synthetic_events", "params": {"every_days": 20, "seed": 3}}]}
    data = load_data(spec)
    ev = data.series["earnings_surprise"]
    t, sym = ev.index[2], ev.iloc[2].dropna().index[0]
    before = GuardedView(data, np.datetime64(t - pd.Timedelta(minutes=1), "ns"))
    after = GuardedView(data, np.datetime64(t, "ns"))
    assert t not in before.series("earnings_surprise", sym).index
    assert after.series_last("earnings_surprise", sym) == ev.loc[t, sym]


def test_csv_series(tmp_path):
    f = tmp_path / "news.csv"
    f.write_text("time,symbol,value\n2024-01-03 08:00,SYN000,0.5\n2024-01-04 08:00,SYN000,-0.2\n")
    spec = {"plugin": "synthetic", "params": {"n_symbols": 3, "n_days": 10, "seed": 1},
            "complementary": [{"plugin": "csv_series", "params": {"path": str(f), "name": "news",
                                                                   "symbol_column": "symbol"}}]}
    data = load_data(spec)
    v = GuardedView(data, np.datetime64("2024-01-03T12:00", "ns"))
    assert v.series_last("news", "SYN000") == 0.5
    with pytest.raises(ValueError):
        v.series("news")  # per-symbol data needs a symbol
