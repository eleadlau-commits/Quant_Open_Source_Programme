import numpy as np
import pytest

from honestbt.plugins.testing import plugin
from honestbt.signals import EntryContext, Path, check_causal

CTX = EntryContext("X", np.datetime64("2024-01-08T09:30"), 100.0, feature=lambda name: 1.0)


def _path(n=200, seed=0):
    c = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.002, n)))
    ts = np.datetime64("2024-01-08T09:30", "ns") + np.arange(n) * np.timedelta64(1, "m")
    return Path(ts, np.r_[100, c[:-1]], c * 1.001, c * 0.999, c, np.ones(n))


@pytest.mark.parametrize("name", ["never", "atr_trailing", "ema_cross", "heikin_ashi", "time_stop"])
def test_every_signal_is_causal(name):
    check_causal({"plugin": name}, _path(), CTX, trials=5)


def test_never_and_time_stop():
    p = _path(30)
    assert not plugin("signal", "never")(p, CTX).any()
    assert np.argmax(plugin("signal", "time_stop")(p, CTX, minutes=5)) == 4
