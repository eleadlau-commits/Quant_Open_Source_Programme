import numpy as np

from honestbt import engine
from honestbt.plugins.testing import plugin

CFG = {
    "features": {"gap": {"plugin": "premarket_gap"}, "price": {"plugin": "last_close"},
                 "adv20": {"plugin": "avg_dollar_volume"}},
    "strategy": {"plugin": "weekly_topn", "params": {"top_n": 3, "rank_by": "gap", "min_price": 1,
                                                     "min_dollar_volume": 0, "exit": {"plugin": "never"}}},
}


def test_buys_at_most_top_n_on_mondays():
    data = plugin("data", "synthetic")(n_symbols=10, n_days=40, seed=5)
    res = engine.run(data, CFG)
    assert res.trades
    per_week = {}
    for t in res.trades:
        assert np.datetime64(t.entry_time[:10]).astype("datetime64[D]").item().weekday() == 0
        per_week[t.decision_time] = per_week.get(t.decision_time, 0) + 1
    assert max(per_week.values()) <= 3
