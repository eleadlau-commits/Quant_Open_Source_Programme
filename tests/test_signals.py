import numpy as np
import pytest

from honestbt.registry import register
from honestbt.signals import CausalityError, EntryContext, Path, check_causal


def make_path(n=300, seed=0):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    ts = np.datetime64("2024-01-08T09:30", "ns") + np.arange(n) * np.timedelta64(1, "m")
    return Path(ts, np.r_[100, c[:-1]], c * 1.001, c * 0.999, c, np.ones(n))


CTX = EntryContext("X", np.datetime64("2024-01-08T09:30"), 100.0, feature=lambda name: 1.0)


@pytest.mark.parametrize("spec", [
    {"plugin": "atr_trailing", "params": {"k": 0.5, "smooth": 10}},
    {"plugin": "ema_cross", "params": {"fast": 5, "slow": 20}},
    {"plugin": "heikin_ashi", "params": {"n_red": 3, "bar_minutes": 5}},
    {"plugin": "time_stop", "params": {"minutes": 5}},
    {"plugin": "any_of", "params": {"signals": [{"plugin": "time_stop", "params": {"minutes": 90}},
                                                {"plugin": "ema_cross", "params": {}}]}},
])
def test_builtin_signals_are_causal(spec):
    for seed in range(3):
        check_causal(spec, make_path(seed=seed), CTX, trials=5, seed=seed)


@register("signal", "_cheat_peek", doc="test only: exits if the next close is lower")
def _cheat(path, ctx):
    out = np.zeros(len(path), dtype=bool)
    out[:-1] = path.close[1:] < path.close[:-1]
    return out


def test_checker_catches_peeking_signal():
    with pytest.raises(CausalityError):
        check_causal({"plugin": "_cheat_peek"}, make_path(), CTX, trials=5)


def test_time_stop_five_minutes_fills_at_0935():
    p = make_path()
    from honestbt.signals import run_signal
    sig = run_signal({"plugin": "time_stop", "params": {"minutes": 5}}, p, CTX)
    first = np.flatnonzero(sig)[0]
    assert str(p.ts[first + 1]).startswith("2024-01-08T09:35")  # engine fills at next bar open
