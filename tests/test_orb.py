"""Opening range breakout on synthetic Nasdaq futures."""
import json

import numpy as np
import pytest

from honestbt import engine
from honestbt.data import GuardedView, LookAheadError
from honestbt.engine import _bracket_exit
from honestbt.plugins import plugin_module
from honestbt.patchbay import validate, with_overrides
from honestbt.runner import run_config
from honestbt.signals import Path

synthetic_futures = plugin_module("synthetic-futures").synthetic_futures
_intraday = plugin_module("intraday-features")
htf_ema_spread, opening_range, resample_closes = _intraday.htf_ema_spread, _intraday.opening_range, _intraday.resample_closes

from pathlib import Path as _P

ROOT = _P(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def orb_config():
    return json.loads((ROOT / "configs" / "nq_orb_trend_filter.json").read_text())


@pytest.fixture(scope="module")
def fut_data():
    return synthetic_futures(n_days=120, seed=5)


@pytest.fixture(scope="module")
def runs(orb_config, fut_data):
    cfg = {k: v for k, v in orb_config.items() if k != "sweep"}
    return {f: engine.run(fut_data, with_overrides(cfg, {"strategy.params.trend_filter": f}))
            for f in (False, True)}


def _ts(s):
    return np.datetime64(s, "ns")


def test_config_is_valid(orb_config):
    assert validate(orb_config) == []


def test_globex_session_and_ticks(fut_data):
    ts, arr = fut_data.ts["MNQ"], fut_data.arr["MNQ"]
    assert len(ts) == 120 * 1380  # 18:00-17:00 with the 17:00 halt
    assert np.allclose(arr[:, :4] / 0.25, np.round(arr[:, :4] / 0.25))
    assert np.all(arr[:, 1] >= np.maximum(arr[:, 0], arr[:, 3])) and np.all(arr[:, 2] <= np.minimum(arr[:, 0], arr[:, 3]))


def test_box_is_not_visible_before_it_closes(fut_data):
    day = fut_data.trading_days[10]
    with pytest.raises(LookAheadError):
        opening_range(GuardedView(fut_data, f"{day} 09:40"), "MNQ", "09:30", "09:45", "high")
    v = GuardedView(fut_data, f"{day} 09:45")
    hi, lo = opening_range(v, "MNQ", side="high"), opening_range(v, "MNQ", side="low")
    ts, arr = fut_data.ts["MNQ"], fut_data.arr["MNQ"]
    m = (ts >= _ts(f"{day}T09:30")) & (ts < _ts(f"{day}T09:45"))
    assert hi == arr[m, 1].max() and lo == arr[m, 2].min()


def test_resample_drops_forming_candle():
    ts = (np.datetime64("2024-01-02T09:00") + np.arange(40).astype("timedelta64[m]")).astype("datetime64[ns]")
    c = np.arange(40, dtype=float)
    out = resample_closes(ts, c, 15, np.datetime64("2024-01-02T09:40"))
    assert out.tolist() == [14.0, 29.0]  # 09:00-09:15 and 09:15-09:30; 09:30-09:45 still forming


def test_ema_spread_ignores_the_future(fut_data):
    import pandas as pd
    from honestbt.data import MarketData
    day = fut_data.trading_days[60]
    a = htf_ema_spread(GuardedView(fut_data, f"{day} 10:20"), "MNQ")
    ts, arr = fut_data.ts["MNQ"], fut_data.arr["MNQ"].copy()
    arr[ts >= _ts(f"{day}T10:20"), :4] *= 1.5  # rewrite the future
    alt = MarketData({"MNQ": pd.DataFrame(arr, index=pd.DatetimeIndex(ts),
                                          columns=["open", "high", "low", "close", "volume"])})
    assert htf_ema_spread(GuardedView(alt, f"{day} 10:20"), "MNQ") == a


def test_entries_follow_a_5min_close_outside_the_box(runs, fut_data):
    ts, arr = fut_data.ts["MNQ"], fut_data.arr["MNQ"]
    for t in runs[False].trades:
        et = _ts(t.entry_time)
        day = str(et.astype("datetime64[D]"))
        mod = int((et - _ts(day)) // np.timedelta64(1, "m"))
        assert mod % 5 == 0 and mod >= 9 * 60 + 50
        box = (ts >= _ts(f"{day}T09:30")) & (ts < _ts(f"{day}T09:45"))
        hi, lo = arr[box, 1].max(), arr[box, 2].min()
        i = int(np.searchsorted(ts, et))
        close = arr[i - 1, 3]  # close of the 5-minute candle that just finished
        assert (close > hi and t.side == 1) or (close < lo and t.side == -1)
        # no earlier 5-minute close outside the box that day
        prev = (ts >= _ts(f"{day}T09:45")) & (ts < et - np.timedelta64(1, "m"))
        closes5 = arr[prev][4::5, 3]
        assert not np.any((closes5 > hi) | (closes5 < lo))
        assert t.exit_time[11:16] <= "16:00"


def test_r_accounting_and_costs(runs):
    trades = runs[False].trades
    reasons = {t.reason for t in trades}
    assert "stop" in reasons and "time_stop" in reasons
    for t in trades:
        assert t.net_return < t.gross_return  # commission + slippage always bite
        if t.reason == "stop":
            assert -1.5 < t.r_multiple < -1.0
        if t.reason == "target":
            assert 2.5 < t.r_multiple < 3.0


def test_trend_filter_trades_with_the_trend(runs, fut_data):
    assert 0 < len(runs[True].trades) < 0.7 * len(runs[False].trades)
    for t in runs[True].trades:
        spread = htf_ema_spread(GuardedView(fut_data, t.entry_time), "MNQ", 15, 50, 200)
        assert np.sign(spread) == t.side


def test_futures_cost_multiplier(orb_config, fut_data):
    cfg = {k: v for k, v in orb_config.items() if k != "sweep"}
    cfg = with_overrides(cfg, {"strategy.params.trend_filter": False})
    a = engine.run(fut_data, cfg).metrics()["total_pnl_usd"]
    b = engine.run(fut_data, with_overrides(cfg, {"costs.multiplier": 3})).metrics()["total_pnl_usd"]
    assert b < a


def test_bracket_assumes_stop_when_both_touched():
    ts = np.array(["2024-01-02T10:00", "2024-01-02T10:01"], dtype="datetime64[ns]")
    arr = np.array([[100, 101, 99.5, 100, 1], [100, 104, 97, 100, 1]], dtype=float)
    p = Path.from_array(ts, arr)
    assert _bracket_exit(p, 1, 98.0, 103.0) == (1, 98.0, "stop_both_touched")
    gap = np.array([[100, 101, 99.5, 100, 1], [96, 97, 95, 96, 1]], dtype=float)
    assert _bracket_exit(Path.from_array(ts, gap), 1, 98.0, 103.0) == (1, 96.0, "stop_gap")
    assert _bracket_exit(Path.from_array(ts, gap), -1, 102.0, 97.0) == (1, 96.0, "target")


def _small(cfg, **data):
    cfg = with_overrides(cfg, {f"data.params.{k}": v for k, v in data.items()})
    cfg["data"]["params"]["n_days"] = 300
    cfg["sweep"] = {"strategy.params.box_end": ["09:35", "09:45", "10:00"],
                    "strategy.params.target_r": [2.0, 3.0, 4.0]}
    cfg["evaluators"] = [e for e in cfg["evaluators"] if e["plugin"] != "random_baseline"] + [
        {"plugin": "random_baseline", "params": {"n": 39, "rank_path": "strategy.params.direction_feature"}}]
    return run_config(cfg)


def test_orb_no_edge_does_not_survive(orb_config):
    out = _small(orb_config, orb_momentum=0.0)
    assert out["summary"]["overall"] == "did not survive"
    assert out["preregistered"]["of"] == 9


def test_orb_planted_edge_survives_but_filter_adds_nothing(orb_config):
    out = _small(orb_config, orb_momentum=1.0)
    v = {x["name"]: x["passed"] for x in out["verdicts"]}
    assert v.pop("Ablation: trend filter") is False  # the planted edge has no trend component
    assert all(v.values()), out["verdicts"]


def test_databento_back_adjust_removes_roll_gap():
    import importlib.util

    import pandas as pd
    spec = importlib.util.spec_from_file_location("dl", ROOT / "scripts" / "download_databento.py")
    dl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dl)
    idx = pd.date_range("2024-03-14 13:00", periods=6, freq="min", tz="UTC")
    front = pd.DataFrame({"open": [100, 101, 102, 150, 151, 152.0], "high": [100, 101, 102, 150, 151, 152.0],
                          "low": [100, 101, 102, 150, 151, 152.0], "close": [100, 101, 102, 150, 151, 152.0],
                          "volume": 1, "instrument_id": [1, 1, 1, 2, 2, 2]}, index=idx)
    second = pd.DataFrame({"close": [148, 149, 150.0, 200, 201, 202], "instrument_id": [2, 2, 2, 3, 3, 3]}, index=idx)
    adj, rolls = dl.back_adjust(front, second)
    assert rolls[0]["gap"] == 48.0  # 150 (new contract) - 102 (old) at the last minute before the roll
    assert adj["close"].tolist() == [148, 149, 150, 150, 151, 152]
