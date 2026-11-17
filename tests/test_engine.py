import numpy as np

from honestbt import engine
from honestbt.patchbay import Resolver, expand_sweep, validate, with_overrides
from honestbt.data import GuardedView


def test_config_is_valid(base_config):
    assert validate(base_config) == []


def test_sweep_expands_cartesian(base_config):
    pts = expand_sweep(base_config)
    assert len(pts) == 12
    pt, cfg = pts[-1]
    assert cfg["strategy"]["params"]["exit"]["params"]["k"] == pt["strategy.params.exit.params.k"]


def test_map_resolution_uses_feature(base_config, small_data):
    day = small_data.trading_days[30]
    R = Resolver(base_config, GuardedView(small_data, f"{day} 09:30"))
    s = small_data.symbols[0]
    vol = R.feature("vol20", s)
    out = R.resolve({"x": {"$map": "smooth_from_vol"}}, s)
    assert out["x"] == min(30, max(3, 2 + 20 * vol))


def test_entries_on_mondays_at_open_and_costs_applied(base_config, small_data):
    cfg = with_overrides(base_config, {"strategy.params.min_dollar_volume": 0, "strategy.params.min_price": 0})
    res = engine.run(small_data, cfg)
    assert res.trades
    for t in res.trades:
        assert t.entry_time.endswith("09:30:00.000000000")
        assert np.datetime64(t.entry_time, "D").astype("datetime64[D]").item().weekday() in (0, 1)  # Monday, or Tuesday after a holiday
        assert t.net_return < t.gross_return  # costs always bite
        mod = int(t.exit_time[11:13]) * 60 + int(t.exit_time[14:16])
        assert 9 * 60 + 30 <= mod <= 16 * 60  # only regular-session exits


def test_cost_multiplier_reduces_returns(base_config, small_data):
    cfg = with_overrides(base_config, {"strategy.params.min_dollar_volume": 0})
    a = engine.run(small_data, cfg).periods.sum()
    b = engine.run(small_data, with_overrides(cfg, {"costs.multiplier": 3})).periods.sum()
    assert b < a
