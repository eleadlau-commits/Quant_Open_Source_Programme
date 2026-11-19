from honestbt import engine
from honestbt.plugins.testing import plugin

CFG = {
    "instrument": {"symbol": "MNQ", "tick_size": 0.25, "point_value": 2.0, "capital": 10000},
    "strategy": {"plugin": "opening_range_breakout", "params": {"symbol": "MNQ", "box_end": "09:45",
                                                                "target_r": 2.0, "exit": {"plugin": "never"}}},
    "costs": {"commission_per_side": 0.85, "slippage_ticks": 1},
}


def test_at_most_one_trade_a_day_after_the_box():
    data = plugin("data", "synthetic_futures")(n_days=30, seed=2)
    res = engine.run(data, CFG)
    days = [t.entry_time[:10] for t in res.trades]
    assert res.trades and len(days) == len(set(days))
    assert all(t.entry_time[11:16] >= "09:45" for t in res.trades)
