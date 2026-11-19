"""Strategies written as a Python file: the position engine, knobs and the file format."""
import numpy as np
import pytest

from honestbt import pystrategy as ps
from honestbt.data.guard import LookAheadError
from honestbt.engine import run
from honestbt.patchbay import validate
from honestbt.runner import load_data

DATA = {"plugin": "synthetic", "params": {"n_symbols": 8, "n_days": 40, "seed": 5}}


def _cfg(decide_body: str, every="day", costs=None, **extra):
    src = f'''"""Test strategy"""
from honestbt.sdk import knob

SETTINGS = {{"data": {DATA!r}, "decide_at": "10:00", "every": "{every}"}}


def decide(F, p):
{decide_body}
'''
    cfg = ps.to_config(src)
    cfg["costs"] = costs or {"half_spread_bps": 0, "slippage_bps": 0, "min_half_spread": 0}
    cfg["strategy"]["params"].update(extra)
    return cfg


def test_buy_and_hold_one_name_earns_its_price_move():
    data = load_data(DATA)
    sym = next(s for s in data.symbols if data.first_date(s) == data.trading_days[0]
               and data.last_date(s) == data.trading_days[-1])
    res = run(data, _cfg(f"    return {{'{sym}': 1.0}} if '{sym}' in F.universe() else {{}}"))
    eq = float(np.prod(1 + res.periods.to_numpy()))
    ts, arr = data.ts[sym], data.arr[sym]
    first_day = data.trading_days[1]  # day 0 has no completed session, so nothing is listed yet
    i0 = int(np.searchsorted(ts, np.datetime64(f"{first_day}T10:00", "ns")))
    expected = arr[-1, 3] / arr[i0, 0]
    assert eq == pytest.approx(expected, rel=1e-9)
    assert len(res.trades) == 1 and res.trades[0].reason == "end_of_data"


def test_costs_are_paid_on_what_changes():
    data = load_data(DATA)
    sym = data.symbols[0]
    free = run(data, _cfg(f"    return {{'{sym}': 1.0}} if '{sym}' in F.universe() else {{}}"))
    paid = run(data, _cfg(f"    return {{'{sym}': 1.0}} if '{sym}' in F.universe() else {{}}",
                          costs={"half_spread_bps": 10, "slippage_bps": 0, "min_half_spread": 0}))
    assert (free.periods - paid.periods).sum() > 0
    assert (free.periods - paid.periods).sum() < 0.01  # one buy, held: costs once, not every day


def test_strategy_cannot_see_the_future():
    data = load_data(DATA)
    body = "    if not F.universe():\n        return {}\n    s = F.universe()[0]\n    F.minute(s, end=F.as_of + np.timedelta64(1, 'h'))\n    return {}"
    cfg = _cfg(body)
    cfg["strategy"]["params"]["code"] = "import numpy as np\n" + cfg["strategy"]["params"]["code"]
    with pytest.raises(LookAheadError):
        run(data, cfg)


def test_cannot_buy_a_name_before_it_lists():
    data = load_data({"plugin": "synthetic", "params": {"n_symbols": 30, "n_days": 60, "seed": 1}})
    late = next(s for s in data.symbols if data.first_date(s) > data.trading_days[5])
    with pytest.raises(ps.StrategyFileError, match="not listed"):
        run(data, _cfg(f"    return {{'{late}': 1.0}}"))


def test_exposure_is_capped():
    data = load_data(DATA)
    res = run(data, _cfg("    u = F.universe()\n    return {s: 1.0 for s in u}"))
    assert res.periods.abs().max() < 0.5  # 100% spread across names, not 100% each


def test_knobs_change_the_run_without_editing_code():
    data = load_data(DATA)
    body = "    n = knob('n', 1, lo=1, hi=8)\n    return {s: 1 / n for s in F.universe()[:n]}"
    a = run(data, _cfg(body))
    b = run(data, _cfg(body, knobs={"n": 4}))
    assert not a.periods.equals(b.periods)


def test_file_format_knobs_modules_and_settings():
    src = ps.new_file("My idea")
    assert not ps.check(src) and not validate(ps.to_config(src))
    assert [k["name"] for k in ps.knobs(src)] == ["days", "top"]
    mods = {m["name"]: m for m in ps.modules(src)}
    assert mods["momentum"]["kind"] == "Data → Data" and mods["decide"]["kind"] == "Data → Buy/Sell"
    assert mods["decide"]["knobs"] == ["days", "top"] and "momentum" in mods["decide"]["calls"]
    # rewrite SETTINGS and read it back
    st = ps.settings(src)
    st["evaluators"] = [{"plugin": "bootstrap"}]
    src2 = ps.set_settings(src, st)
    assert ps.settings(src2)["evaluators"] == [{"plugin": "bootstrap"}] and [k['name'] for k in ps.knobs(src2)] == ['days', 'top']
    assert ps.to_config(src2)["name"] == "My idea"


def test_make_a_number_a_knob():
    src = "def decide(F, p):\n    window = 30\n    return {}\n"
    out, name = ps.make_knob(src, 2, 14)
    assert name == "window" and 'window = knob("window", 30, lo=0, hi=120)' in out
    assert out.startswith("from honestbt.sdk import knob")
    with pytest.raises(ps.StrategyFileError):
        ps.make_knob(out, 2, 20)  # already a knob
    assert 'knob("window", 45' in ps.set_knob_default(out, "window", 45)


def test_bad_files_are_explained():
    assert "decide" in ps.check("SETTINGS = {'data': {}}\n")[0]
    assert "line" in ps.check("def decide(F, p)\n")[0]
    assert any("every" in p for p in ps.check("SETTINGS={'data':{}, 'every':'month'}\ndef decide(F,p): pass\n"))
