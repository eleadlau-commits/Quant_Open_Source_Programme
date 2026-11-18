import numpy as np
import pytest

from honestbt.data import GuardedView, LookAheadError


def test_minute_bars_end_by_as_of(small_data):
    s = small_data.symbols[0]
    day = small_data.trading_days[10]
    v = GuardedView(small_data, f"{day} 09:30")
    bars = v.minute(s)
    ts = small_data.ts[s][: len(bars)]
    assert ts[-1] + np.timedelta64(1, "m") <= v.as_of  # the 09:29 bar is the last visible one
    assert str(ts[-1]).endswith("09:29:00.000000000")


def test_asking_for_future_raises(small_data):
    v = GuardedView(small_data, f"{small_data.trading_days[10]} 09:30")
    with pytest.raises(LookAheadError):
        v.minute(small_data.symbols[0], end=f"{small_data.trading_days[10]} 09:31")


def test_daily_excludes_today_until_close(small_data):
    s = small_data.symbols[0]
    day = small_data.trading_days[10]
    assert GuardedView(small_data, f"{day} 15:59").daily(s).date[-1] < day
    assert GuardedView(small_data, f"{day} 16:00").daily(s).date[-1] == day


def test_premarket_last_uses_only_premarket(small_data):
    s = small_data.symbols[0]
    day = small_data.trading_days[10]
    v_open = GuardedView(small_data, f"{day} 09:30")
    v_late = GuardedView(small_data, f"{day} 11:00")
    assert v_open.premarket_last(s) == v_late.premarket_last(s)
    v_early = GuardedView(small_data, f"{day} 09:10")
    assert v_early.premarket_last(s) != v_open.premarket_last(s)


def test_delisted_names_stay_in_universe_until_they_stop_trading(small_data):
    from honestbt.registry import get
    synthetic = get("data", "synthetic")
    d = synthetic(n_symbols=30, n_days=120, seed=1, delist_frac=0.5)
    gone = [s for s in d.symbols if d.last_date(s) < d.trading_days[-1]]
    assert gone, "fixture should contain delisted names"
    s = gone[0]
    last = d.last_date(s)
    assert s in GuardedView(d, f"{last} 09:30").universe()
    later = d.trading_days[np.searchsorted(d.trading_days, last) + 2]
    assert s not in GuardedView(d, f"{later} 09:30").universe()
