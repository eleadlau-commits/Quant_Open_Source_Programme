import numpy as np

from honestbt.plugins.testing import plugin


def test_prices_sit_on_the_tick():
    d = plugin("data", "synthetic_futures")(n_days=5, seed=3)
    close = d.arr[d.symbols[0]][:, 3]
    assert np.allclose(close / 0.25, np.round(close / 0.25))
