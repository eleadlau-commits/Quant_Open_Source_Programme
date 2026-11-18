import numpy as np
import pytest

from honestbt.data import GuardedView, LookAheadError
from honestbt.plugins.testing import module, plugin


def test_resample_drops_the_candle_still_forming():
    m = module("intraday-features")
    ts = np.datetime64("2024-01-08T09:30") + np.arange(12) * np.timedelta64(1, "m")
    out = m.resample_closes(ts, np.arange(12.0), 5, np.datetime64("2024-01-08T09:41"))
    assert out.tolist() == [4.0, 9.0]


def test_box_cannot_be_read_before_it_closes():
    data = plugin("data", "synthetic_futures")(n_days=5, seed=1)
    day = data.trading_days[-1].astype("datetime64[m]")
    early = GuardedView(data, day + np.timedelta64(9 * 60 + 40, "m"))
    with pytest.raises(LookAheadError):
        plugin("feature", "opening_range")(early, data.symbols[0], start="09:30", end="09:45")
    late = GuardedView(data, day + np.timedelta64(9 * 60 + 45, "m"))
    assert plugin("feature", "opening_range")(late, data.symbols[0], side="height") >= 0
