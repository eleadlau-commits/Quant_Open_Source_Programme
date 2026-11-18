import numpy as np

from honestbt.data import GuardedView
from honestbt.plugins.testing import plugin


def _view():
    data = plugin("data", "synthetic")(n_symbols=5, n_days=40, seed=2)
    day = data.trading_days[30]
    return data, GuardedView(data, day.astype("datetime64[m]") + np.timedelta64(9 * 60 + 30, "m"))


def test_values_are_finite_and_sensible():
    data, view = _view()
    s = data.symbols[0]
    assert plugin("feature", "last_close")(view, s) > 0
    assert plugin("feature", "atr")(view, s, window=14) > 0
    assert 0 < plugin("feature", "realized_vol")(view, s, window=20) < 5
    assert np.isfinite(plugin("feature", "premarket_gap")(view, s))


def test_not_enough_history_is_nan():
    data, view = _view()
    assert np.isnan(plugin("feature", "realized_vol")(view, data.symbols[0], window=500))


def test_random_is_deterministic_and_in_unit_interval():
    data, view = _view()
    f = plugin("feature", "random")
    a, b = f(view, data.symbols[0], seed=1), f(view, data.symbols[0], seed=1)
    assert a == b and 0 <= a < 1 and a != f(view, data.symbols[0], seed=2)
