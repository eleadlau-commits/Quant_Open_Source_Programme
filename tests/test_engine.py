"""The simulator (Phase 1B): clock, broker, costs, ledger, recorder, engine and run service."""
from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from titanium.core.bars import OHLCV, MarketData, daily_frame
from titanium.core.data import LookAheadError
from titanium.core.instruments import Instrument, InstrumentKind
from titanium.core.markets import NASDAQ
from titanium.core.orders import Fill, Order, OrderType, Side, bracket
from titanium.core.sim import (CostModel, DecisionClock, MemoryData, RunFailed, SimBroker, SimEngine, SimLedger)
from titanium.core.sources import SyntheticStocks
from titanium.core.strategy import Decision

NY = NASDAQ.tz
UTC = timezone.utc
DAYS = [date(2024, 3, 4) + timedelta(days=i) for i in range(5)]  # Mon..Fri, no holidays


def ny(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), NY)


def day_bars(day: date, base: float = 100.0, step: float = 0.01, overrides: dict | None = None) -> pd.DataFrame:
    """Regular-session minutes with open = base + i*step (so every bar's open is distinct)."""
    idx = pd.date_range(ny(day, "09:30"), periods=390, freq="1min").tz_convert("UTC")
    o = base + step * np.arange(390)
    c = o + step
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.001, "low": np.minimum(o, c) - 0.001,
                       "close": c, "volume": 1000.0}, index=idx)
    for hhmm, row in (overrides or {}).items():
        t = pd.Timestamp(ny(day, hhmm)).tz_convert("UTC")
        for k, v in row.items():
            df.loc[t, k] = v
    df.index.name = "start"
    return df[OHLCV]


def stock_data(n_days: int = 5, keys=("xnas:AAA",), last_day: dict | None = None, **kw) -> MarketData:
    minute = {}
    for k in keys:
        stop = (last_day or {}).get(k, n_days)
        minute[k] = pd.concat([day_bars(d, base=100.0 + i, **kw) for i, d in enumerate(DAYS[:stop])])
    return MarketData("xnas", minute, name="test")


class Fixed:
    """A strategy that returns a scripted decision at given local times (``"D2 10:00"``: day index, time)."""

    def __init__(self, script: dict[tuple[int, str], object], settings=None):
        self.script = script
        self.settings = settings or {}
        self.seen = []

    def decide(self, view, p):
        local = view.as_of.astimezone(NY)
        self.seen.append((local, p))
        key = (DAYS.index(local.date()), local.strftime("%H:%M"))
        return self.script.get(key)


def run(strategy, data, **settings):
    return SimEngine(MemoryData({"d": data})).run(strategy, "d", settings)


# ---- clock --------------------------------------------------------------------------
def test_clock_daily_weekly_and_early_close():
    c = DecisionClock(NASDAQ, date(2024, 11, 25), date(2024, 12, 6), {"decide_at": "15:50"})
    times = [t.astimezone(NY) for t in c.times()]
    assert date(2024, 11, 28) not in [t.date() for t in times]  # Thanksgiving
    fri = [t for t in times if t.date() == date(2024, 11, 29)][0]
    assert fri.time() == time(12, 50)  # early close at 13:00: same ten minutes before the close
    assert all(t.time() == time(15, 50) for t in times if t.date() != date(2024, 11, 29))
    weekly = [t.astimezone(NY).date() for t in
              DecisionClock(NASDAQ, date(2024, 11, 25), date(2024, 12, 6), {"every": "week"}).times()]
    assert weekly == [date(2024, 11, 25), date(2024, 12, 2)]
    two = list(DecisionClock(NASDAQ, DAYS[0], DAYS[0], {"decide_at": ["15:50", "09:45"]}).times())
    assert [t.astimezone(NY).strftime("%H:%M") for t in two] == ["09:45", "15:50"]
    with pytest.raises(ValueError):
        DecisionClock(NASDAQ, DAYS[0], DAYS[1], {"every": "hour"})


# ---- next-bar fills ----------------------------------------------------------------------
def test_market_order_fills_at_next_bar_open():
    data = stock_data()
    strat = Fixed({(1, "10:00"): [Order("xnas:AAA", Side.BUY, 10)]}, {"decide_at": "10:00"})
    rec = run(strat, data, costs={"stress": 0})
    f = rec.fills[0]
    bar = data.minute("xnas:AAA").loc[pd.Timestamp(ny(DAYS[1], "10:00")).tz_convert("UTC")]
    assert f.time == ny(DAYS[1], "10:00")  # the bar *starting* at the decision: the decision saw only earlier bars
    assert f.price == pytest.approx(bar["open"])
    assert rec.states[2].positions["xnas:AAA"].quantity == 10


def daily_only(n=10, keys=("xnas:AAA",)):
    days = pd.bdate_range("2024-03-04", periods=n)
    px = 100 + np.arange(float(n))
    df = pd.DataFrame({"open": px, "high": px + 1, "low": px - 1, "close": px + 0.5, "volume": 1e6}, index=days)
    return MarketData("xnas", daily={k: daily_frame(df, NASDAQ) for k in keys})


class AllIn:
    settings: dict = {}

    def decide(self, view, p):
        return {k: 1.0 for k in view.universe()}


def test_daily_fill_is_booked_before_the_next_decision():
    """A market order fills at the next day's open; that day's 15:50 decision must see it."""
    rec = run(AllIn(), daily_only(), costs={"stress": 0})
    held = [s for s in rec.states if s.positions]
    first = held[0].positions["xnas:AAA"].quantity
    assert first > 0
    for s in held:  # never doubled: about one equity's worth of stock, cash never deeply negative
        assert s.positions["xnas:AAA"].quantity <= first
        assert s.cash > -0.02 * s.equity
    assert all(f.side is Side.BUY for f in rec.fills[:1]) and sum(f.side is Side.BUY for f in rec.fills) == 1


def test_new_targets_replace_orders_still_waiting_to_fill():
    """Two decisions a day on daily bars: the 15:50 decision sees the 09:45 order still unfilled."""
    rec = run(AllIn(), daily_only(), costs={"stress": 0}, decide_at=["09:45", "15:50"])
    buy = rec.fills[0]
    assert buy.side is Side.BUY and buy.quantity * buy.price < 1.02 * rec.capital
    assert max(s.positions["xnas:AAA"].quantity for s in rec.states if s.positions) == buy.quantity  # not 2x
    assert sum(f.side is Side.BUY for f in rec.fills) == 1


def test_a_dropped_names_pending_buy_is_cancelled():
    """09:45 targets AAA, 15:50 switches to BBB before the AAA order could fill: only BBB is bought."""

    class Switch:
        settings: dict = {}

        def decide(self, view, p):
            if not view.universe():
                return None
            return {"xnas:AAA": 1.0} if view.as_of.astimezone(NY).hour < 12 else {"xnas:BBB": 1.0}

    rec = run(Switch(), daily_only(keys=("xnas:AAA", "xnas:BBB")), costs={"stress": 0},
              decide_at=["09:45", "15:50"])
    for s in rec.states:
        gross = sum(abs(pos.quantity) * pos.last_price for pos in s.positions.values())
        assert gross < 1.05 * s.equity and s.cash > -0.05 * s.equity
    assert {f.instrument for f in rec.fills} == {"xnas:BBB"}


def test_target_weights_sized_at_last_visible_close_in_whole_lots():
    data = stock_data()
    strat = Fixed({(1, "10:00"): {"xnas:AAA": 0.5}}, {"decide_at": "10:00"})
    rec = run(strat, data, costs={"stress": 0}, capital=10_000)
    f = rec.fills[0]
    seen = data.minute("xnas:AAA").loc[pd.Timestamp(ny(DAYS[1], "09:59")).tz_convert("UTC"), "close"]
    assert f.quantity == int(0.5 * 10_000 / seen)
    assert f.info["tag"] == "rebalance"


def test_overnight_gap_sizes_at_pre_gap_price_and_fills_at_gapped_open():
    data = stock_data()
    df = data.minute("xnas:AAA")
    gap_day = df.index.tz_convert(NY).date == DAYS[2]
    df.loc[gap_day, ["open", "high", "low", "close"]] *= 1.5  # opens 50% higher on day 3
    # decided at the close of day 2: the order lands on the gapped open of day 3
    strat = Fixed({(1, "16:00"): {"xnas:AAA": 1.0}}, {"decide_at": "16:00"})
    rec = run(strat, data, costs={"stress": 0}, capital=10_000)
    f = rec.fills[0]
    last_close = df.loc[pd.Timestamp(ny(DAYS[1], "15:59")).tz_convert("UTC"), "close"]
    gapped_open = df.loc[pd.Timestamp(ny(DAYS[2], "09:30")).tz_convert("UTC"), "open"]
    assert f.time == ny(DAYS[2], "09:30") and f.price == pytest.approx(gapped_open)
    assert f.quantity == int(10_000 / last_close)  # what the pre-gap price implied
    assert rec.states[2].cash < 0  # the gap cost more than the cash: allowed, and logged
    assert any("below zero" in line for line in rec.log)


def test_targets_scaled_to_max_gross_and_limited_by_cash():
    data = stock_data(keys=("xnas:AAA", "xnas:BBB"))
    strat = Fixed({(1, "10:00"): {"xnas:AAA": 1.0, "xnas:BBB": 1.0}}, {"decide_at": "10:00"})
    rec = run(strat, data, capital=10_000)
    s = rec.states[2]
    assert s.cash >= 0
    assert sum(abs(w) for w in s.weights().values()) <= 1.0 + 1e-9
    assert all(0.45 < w < 0.51 for w in s.weights().values())


# ---- costs ----------------------------------------------------------------------------------
def test_equity_costs_wider_after_open_with_minimum_per_share():
    cm = CostModel()
    aaa = Instrument("AAA", InstrumentKind.STOCK, "xnas")
    mid = cm.cost(aaa, NASDAQ, 100.0, 10, ny(DAYS[0], "11:00"))
    assert mid == pytest.approx(10 * (100 * 5e-4 + 100 * 3e-4))
    early = cm.cost(aaa, NASDAQ, 100.0, 10, ny(DAYS[0], "09:31"))
    assert early == pytest.approx(10 * (100 * 15e-4 + 100 * 3e-4))
    penny = cm.cost(aaa, NASDAQ, 2.0, 100, ny(DAYS[0], "11:00"))
    assert penny == pytest.approx(100 * (0.005 + 2 * 3e-4))  # half a cent minimum half-spread
    assert CostModel.from_settings({"stress": 2}).cost(aaa, NASDAQ, 100.0, 10, ny(DAYS[0], "11:00")) == pytest.approx(2 * mid)
    with pytest.raises(ValueError):
        CostModel.from_settings({"equity": {"spread": 1}})


def test_futures_costs_in_ticks_and_commission():
    cm = CostModel()
    mnq = Instrument("MNQ", InstrumentKind.FUTURE, "cme", tick_size=0.25, multiplier=2.0)
    assert cm.cost(mnq, NASDAQ, 18000, 3, ny(DAYS[0], "11:00"), "market") == pytest.approx(3 * (0.25 * 2 + 0.85))
    assert cm.cost(mnq, NASDAQ, 18000, 1, ny(DAYS[0], "11:00"), "limit") == pytest.approx(0.85)


def test_engine_charges_costs_into_cash():
    data = stock_data()
    strat = Fixed({(1, "11:00"): [Order("xnas:AAA", Side.BUY, 10)]}, {"decide_at": "11:00"})
    rec = run(strat, data)
    f = rec.fills[0]
    assert f.cost == pytest.approx(10 * f.price * 8e-4)
    assert rec.states[2].cash == pytest.approx(100_000 - 10 * f.price - f.cost)


# ---- ledger ---------------------------------------------------------------------------------
def _fill(key, side, qty, price, cost=0.0, t=None):
    return Fill("x", key, t or ny(DAYS[0], "10:00"), Side(side), qty, price, cost)


def test_ledger_stock_arithmetic():
    spec = lambda k: Instrument(k, InstrumentKind.STOCK, "xnas")  # noqa: E731
    led = SimLedger(10_000, spec)
    led.apply(_fill("A", 1, 100, 10.0, cost=1.0))
    led.apply(_fill("A", 1, 100, 12.0, cost=1.0))
    assert led.positions["A"].avg_price == pytest.approx(11.0)
    assert led.cash == pytest.approx(10_000 - 1000 - 1200 - 2)
    s = led.mark(ny(DAYS[0], "11:00"), {"A": 13.0})
    assert s.equity == pytest.approx(led.cash + 200 * 13.0)
    assert led.apply(_fill("A", -1, 150, 14.0)) == pytest.approx(150 * 3.0)  # realised
    led.apply(_fill("A", -1, 100, 14.0))  # flips short 50
    assert led.positions["A"].quantity == -50 and led.positions["A"].avg_price == 14.0
    s = led.mark(ny(DAYS[0], "12:00"), {"A": 15.0})
    assert s.equity == pytest.approx(10_000 - 2 + 200 * 3.0 - 50 * 1.0)
    assert s.weights()["A"] == pytest.approx(-750 / s.equity)


def test_ledger_futures_are_margined():
    spec = lambda k: Instrument(k, InstrumentKind.FUTURE, "cme", tick_size=0.25, multiplier=2.0)  # noqa: E731
    led = SimLedger(10_000, spec)
    led.apply(_fill("MNQ", 1, 2, 18000.0, cost=2.7))
    assert led.cash == pytest.approx(10_000 - 2.7)  # no cash for the contract itself
    s = led.mark(ny(DAYS[0], "11:00"), {"MNQ": 18010.0})
    assert s.equity == pytest.approx(10_000 - 2.7 + 2 * 10 * 2)
    assert s.positions["MNQ"].exposure == pytest.approx(2 * 18010 * 2)
    led.apply(_fill("MNQ", -1, 2, 18010.0, cost=2.7))
    assert led.cash == pytest.approx(10_000 - 5.4 + 40) and not led.positions


# ---- brackets ------------------------------------------------------------------------------
def _broker(overrides, extended=None):
    data = MarketData("xnas", {"xnas:AAA": day_bars(DAYS[0], step=0.0, overrides=overrides)})
    return SimBroker(data, CostModel(stress=0), extended)


def test_bracket_target_fills_and_cancels_stop():
    b = _broker({"10:05": {"high": 103.0}})
    for o in bracket("xnas:AAA", Side.BUY, 10, stop_offset=2.0, target_offset=2.5):
        b.submit(o, ny(DAYS[0], "10:00"))
    fills = b.fills(ny(DAYS[0], "16:00"))
    assert [f.info["reason"] for f in fills] == ["market", "target"]
    assert fills[1].price == pytest.approx(102.5) and fills[1].time == ny(DAYS[0], "10:05")
    assert b.open_orders() == [] and b.position("xnas:AAA") == 0


def test_bar_touching_both_takes_the_stop():
    b = _broker({"10:05": {"high": 103.0, "low": 97.0}})
    for o in bracket("xnas:AAA", Side.BUY, 10, stop=98.0, target=102.0):
        b.submit(o, ny(DAYS[0], "10:00"))
    fills = b.fills(ny(DAYS[0], "16:00"))
    assert fills[1].info["reason"] == "stop_both_touched" and fills[1].price == 98.0
    assert b.open_orders() == []


def test_gap_through_stop_fills_at_open():
    b = _broker({"10:05": {"open": 95.0, "low": 94.0, "high": 96.0}})
    for o in bracket("xnas:AAA", Side.BUY, 10, stop=98.0):
        b.submit(o, ny(DAYS[0], "10:00"))
    fills = b.fills(ny(DAYS[0], "16:00"))
    assert fills[1].info["reason"] == "stop_gap" and fills[1].price == 95.0


def test_short_bracket_and_exits_are_reduce_only():
    b = _broker({"10:05": {"low": 97.0}})
    orders = bracket("xnas:AAA", Side.SELL, 10, stop_offset=1.0, target_offset=2.0)
    for o in orders:
        b.submit(o, ny(DAYS[0], "10:00"))
    fills = b.fills(ny(DAYS[0], "16:00"))
    assert fills[0].side is Side.SELL and fills[1].side is Side.BUY
    assert fills[1].info["reason"] == "target" and fills[1].price == pytest.approx(98.0)
    # flat by another order: resting exits are cancelled, never open a new position
    b2 = _broker({"10:30": {"low": 90.0}})
    for o in bracket("xnas:AAA", Side.BUY, 10, stop=95.0):
        b2.submit(o, ny(DAYS[0], "10:00"))
    b2.fills(ny(DAYS[0], "10:10"))
    b2.submit(Order("xnas:AAA", Side.SELL, 10), ny(DAYS[0], "10:10"))
    fills = b2.fills(ny(DAYS[0], "16:00"))
    assert len(fills) == 1 and b2.position("xnas:AAA") == 0 and b2.open_orders() == []


def test_limit_entry_and_expiry():
    b = _broker({"11:00": {"low": 99.0}})
    b.submit(Order("xnas:AAA", Side.BUY, 5, OrderType.LIMIT, limit_price=99.5), ny(DAYS[0], "10:00"))
    b.submit(Order("xnas:AAA", Side.BUY, 5, OrderType.LIMIT, limit_price=90.0,
                   expires=ny(DAYS[0], "12:00")), ny(DAYS[0], "10:00"))
    fills = b.fills(ny(DAYS[0], "16:00"))
    assert len(fills) == 1 and fills[0].price == 99.5 and fills[0].time == ny(DAYS[0], "11:00")
    assert b.open_orders() == []


def test_regular_session_only_for_stocks():
    pre = day_bars(DAYS[0])
    pm = pd.DataFrame({c: 50.0 for c in OHLCV}, index=pd.date_range(ny(DAYS[0], "09:00"), periods=30,
                                                                      freq="1min").tz_convert("UTC"))
    data = MarketData("xnas", {"xnas:AAA": pd.concat([pm, pre]).sort_index()})
    b = SimBroker(data, CostModel(stress=0))
    b.submit(Order("xnas:AAA", Side.BUY, 1), ny(DAYS[0], "09:05"))
    assert b.fills(ny(DAYS[0], "16:00"))[0].time == ny(DAYS[0], "09:30")
    b = SimBroker(data, CostModel(stress=0), extended_hours=True)
    b.submit(Order("xnas:AAA", Side.BUY, 1), ny(DAYS[0], "09:05"))
    assert b.fills(ny(DAYS[0], "16:00"))[0].price == 50.0


# ---- look-ahead, delisting ------------------------------------------------------------------
class Peeker:
    settings = {"decide_at": "10:00"}

    def decide(self, view, p):
        view.bars("xnas:AAA", "1min", end=view.as_of + timedelta(days=1))


def test_look_ahead_attempt_raises():
    with pytest.raises(RunFailed) as ei:
        run(Peeker(), stock_data())
    assert isinstance(ei.value.__cause__, LookAheadError)
    assert ei.value.record.status == "failed" and "LookAheadError" in ei.value.record.error


def test_trading_a_name_before_it_lists_is_skipped_and_logged():
    """A strategy that names a ticker directly (hold AAA) used to fail the whole run on the data's first
    day, when nothing is listed yet. The order is skipped and logged instead."""
    data = MarketData("xnas", {"xnas:AAA": pd.concat([day_bars(d) for d in DAYS]),
                               "xnas:NEW": pd.concat([day_bars(d) for d in DAYS[3:]])})
    strat = Fixed({(1, "10:00"): {"xnas:NEW": 0.5}, (0, "10:00"): {"xnas:AAA": 0.5}}, {"decide_at": "10:00"})
    rec = run(strat, data)
    assert rec.status == "done" and not rec.fills
    assert any("xnas:NEW: it doesn't trade yet" in line for line in rec.log)
    assert any("xnas:AAA: it doesn't trade yet" in line for line in rec.log)


def test_trading_a_name_not_in_the_data_still_fails():
    strat = Fixed({(1, "10:00"): {"xnas:ZZZ": 0.5}}, {"decide_at": "10:00"})
    with pytest.raises(RunFailed) as ei:
        run(strat, stock_data())
    assert isinstance(ei.value.__cause__, LookAheadError)


def test_delisted_name_closes_at_last_price_flagged():
    data = stock_data(keys=("xnas:AAA", "xnas:DIE"), last_day={"xnas:DIE": 2})
    strat = Fixed({(1, "10:00"): {"xnas:DIE": 0.5}}, {"decide_at": "10:00"})
    rec = run(strat, data)
    out = [f for f in rec.fills if f.info.get("reason") == "delisted"]
    assert len(out) == 1
    last = data.minute("xnas:DIE").iloc[-1]
    assert out[0].price == pytest.approx(last["close"])
    assert out[0].time == data.minute("xnas:DIE").index[-1] + pd.Timedelta(minutes=1)
    trade = [t for t in rec.trades if t.instrument == "xnas:DIE"][0]
    assert "delisted" in trade.flags and trade.reason == "delisted"
    assert "xnas:DIE" not in rec.states[-1].positions
    assert any("stopped trading" in line for line in rec.log)


# ---- recorder and engine --------------------------------------------------------------------
def test_record_has_states_trades_and_log():
    data = stock_data()
    strat = Fixed({(1, "10:00"): {"xnas:AAA": 0.5}, (3, "10:00"): {}}, {"decide_at": "10:00"})
    rec = run(strat, data)
    assert len(rec.states) == 6  # five decisions and the end of the data
    assert [s.time for s in rec.states] == sorted(s.time for s in rec.states)
    assert len(rec.trades) == 1
    t = rec.trades[0]
    assert t.exit_time == ny(DAYS[3], "10:00") and t.reason == "rebalance"
    assert t.pnl == pytest.approx(rec.states[-1].equity - 100_000)
    assert rec.states[-1].growth == pytest.approx(rec.states[-1].equity / 100_000)
    assert strat.seen[2][1].positions["xnas:AAA"].quantity == t.quantity  # the strategy saw its position
    assert rec.log[0].startswith("2024-03-04 10:00") and "end: equity" in rec.log[-1]


def test_open_position_recorded_as_open_trade():
    rec = run(Fixed({(1, "10:00"): {"xnas:AAA": 0.5}}, {"decide_at": "10:00"}), stock_data())
    assert rec.trades[0].exit_time is None and "open" in rec.trades[0].flags


def test_cancel_stops_between_steps():
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 2

    rec = SimEngine(MemoryData({"d": stock_data()})).run(Fixed({}, {"decide_at": "10:00"}), "d", cancel=cancel)
    assert rec.status == "cancelled" and len(rec.states) == 2


def test_progress_reports_fractions():
    seen = []
    SimEngine(MemoryData({"d": stock_data()})).run(Fixed({}, {"decide_at": "10:00"}), "d", progress=seen.append)
    assert seen[-1] == 1.0 and len(seen) == 5


def test_decision_cancel_and_open_orders_visible():
    data = stock_data()
    strat = Fixed({(1, "10:00"): [Order("xnas:AAA", Side.BUY, 1, OrderType.LIMIT, limit_price=1.0, id="cheap")],
                   (2, "10:00"): Decision(cancel=["cheap"])}, {"decide_at": "10:00"})
    rec = run(strat, data)
    assert [o.id for o in strat.seen[2][1].orders] == ["cheap"]
    assert strat.seen[3][1].orders == [] and not rec.fills


# ---- edge versus no edge on synthetic data ------------------------------------------------
class GapLongs:
    """Buy the five biggest gap-ups shortly after the open, sell before the close."""

    settings = {"decide_at": ["09:35", "15:55"]}

    def decide(self, view, p):
        if view.as_of.astimezone(NY).hour >= 15:
            return {}
        gaps = {}
        for k in view.universe():
            d = view.daily(k)
            m = view.minute(k, start=view.as_of - timedelta(minutes=5))
            if len(d) and len(m):
                gaps[k] = m["close"].iloc[-1] / d["close"].iloc[-1] - 1
        top = sorted(gaps, key=gaps.get, reverse=True)[:5]
        return {k: 0.2 for k in top}


@pytest.mark.parametrize("seed", [2, 3])
def test_planted_edge_found_and_no_edge_not(seed):
    src = SyntheticStocks()
    out = {}
    for edge in (0.0, 0.3):  # same random draws; only the planted drift differs
        data = src.load(src.spec(n_symbols=30, n_days=60, seed=seed, gap_momentum=edge, delist_frac=0.0))
        out[edge] = run(GapLongs(), data).states[-1].growth
    assert out[0.3] > 1.2  # the planted edge shows up after costs
    assert out[0.0] < 1.0  # no edge: costs eat it
    assert out[0.3] - out[0.0] > 0.3


# ---- run service --------------------------------------------------------------------------
def test_run_service_runs_commits_and_cancels():
    from titanium.app.workspace import Workspace

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 4, "n_days": 10, "seed": 1})
    seen = []
    ws.runs.added.connect(lambda i, r: seen.append(i))

    class EW:
        id = "EW"
        settings = {"dataset": info.id, "decide_at": "10:00"}

        def decide(self, view, p):
            u = view.universe()
            return {k: 1 / len(u) for k in u}

    rec = ws.runs.run(EW())
    assert rec.status == "done" and seen == [rec.id] and rec.dataset_version == info.version
    assert rec.strategy_id == "EW" and ws.runs.records("EW") == [rec]

    failed = ws.runs.run(Peeker(), dataset_id=info.id)
    assert failed.status == "failed" and failed.id in ws.runs

    job = ws.runs.prepare(EW())
    assert job.id in ws.runs.active()
    assert ws.runs.cancel(job.id)
    rec = ws.runs.commit(job.execute())
    assert rec.status == "cancelled" and ws.runs.active() == []
    with pytest.raises(ValueError, match="dataset"):
        ws.runs.prepare(Fixed({}))


def test_run_on_a_worker_thread():
    from titanium.app.workspace import Workspace

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 3, "n_days": 8, "seed": 2})
    class Idle:
        def decide(self, view, p):
            return None

    job = ws.runs.prepare(Idle(), dataset_id=info.id)
    box = {}
    th = threading.Thread(target=lambda: box.setdefault("r", job.execute()))
    th.start()
    th.join(60)
    assert box["r"].status == "done" and job.fraction == 1.0


# ---- strategy graphs ------------------------------------------------------------------------
def test_strategy_graph_runs_with_probes():
    from titanium.app.workspace import Workspace
    from titanium.core.module_library import momentum_rotation

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 8, "n_days": 80, "seed": 4})
    g = momentum_rotation()
    g.settings["datasets"] = [info.id]
    ws.strategies.put(g.id, g)
    rec = ws.runs.run(g.id, {"probes": [g.modules[0].id]})
    assert rec.status == "done", rec.error
    assert rec.strategy_snapshot["id"] == g.id and rec.dataset_id == info.id
    assert rec.fills and rec.trades
    name = g.modules[0].id
    assert len(rec.probes[name]) == len(rec.states) - 1  # one per decision
    assert isinstance(rec.probes[name][-1][1], dict)


def test_clock_serves_graph_decision_times():
    from titanium.core.strategy import StrategyGraph
    from titanium.core.strategy_compile import GraphStrategy

    clock = DecisionClock(NASDAQ, DAYS[0], DAYS[-1])
    g = StrategyGraph("S", "s", settings={"decide_at": "10:00", "every": "week"})
    g.modules = []
    times = clock.decision_times(g.settings)
    assert [t.astimezone(NY) for t in times] == [ny(DAYS[0], "10:00")]
    assert len(clock.decision_times()) == 5


# ---- re-running fast: what one run works out is kept for the next -----------------------------
def test_combined_data_reuses_derived_daily_bars_and_sim_arrays(monkeypatch):
    from titanium.core import bars as B
    from titanium.core.sim import feed as F

    data = stock_data(n_days=5, keys=("xnas:AAA", "xnas:BBB"))
    calls = []
    real = B.daily_from_minutes
    monkeypatch.setattr(B, "daily_from_minutes", lambda m, mk: calls.append(1) or real(m, mk))
    provider = MemoryData({"d": data})
    first = F.combined(provider, ["d"])
    d1 = first.daily("xnas:AAA")
    second = F.combined(provider, ["d"])  # the next run
    assert second.daily("xnas:AAA") is d1 and len(calls) == 1
    b1 = SimBroker(first).bars("xnas:AAA")
    assert SimBroker(second).bars("xnas:AAA") is b1  # same market and hours: kept
    assert SimBroker(second, extended_hours=True).bars("xnas:AAA") is not b1  # different hours: its own


def test_guard_daily_bars_by_binary_search_match_the_row_filter():
    from titanium.core.guard import Guard

    data = stock_data(n_days=6)
    daily = data.daily("xnas:AAA")
    for end in list(daily["end"]) + [daily["end"].iloc[0] - timedelta(minutes=1)]:
        for as_of in (end, end + timedelta(minutes=1)):
            g = Guard(data, as_of)
            want = daily[daily["end"] <= as_of]
            assert g.daily("xnas:AAA").equals(want)
            start = daily["end"].iloc[1]
            if start <= as_of:
                assert g.daily("xnas:AAA", start=start).equals(want[want["end"] > start])


def test_engine_reruns_give_the_same_record_as_a_fresh_run():
    from titanium.app.workspace import Workspace
    from titanium.core.module_library import momentum_rotation

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 5, "n_days": 40, "seed": 7})
    g = momentum_rotation()
    g.knob_values["m2.days"] = 10
    g.settings["datasets"] = [info.id]
    ws.strategies.put(g.id, g)
    a = ws.runs.run(g.id)
    b = ws.runs.run(g.id)  # reuses the opened dataset's daily bars and arrays
    assert [s.equity for s in a.states] == [s.equity for s in b.states]
    assert [(t.instrument, t.quantity, t.entry_price) for t in a.trades] == \
           [(t.instrument, t.quantity, t.entry_price) for t in b.trades]



def _daily_data(n: int = 6, keys=("xnas:AAA",)) -> MarketData:
    days = pd.bdate_range("2024-03-04", periods=n)
    px = np.arange(n) * 1.0 + 100
    frame = pd.DataFrame({"open": px, "high": px + 0.5, "low": px - 0.5, "close": px, "volume": 1.0}, index=days)
    return MarketData("xnas", daily={k: daily_frame(frame, NASDAQ) for k in keys})


def test_daily_only_data_decides_at_the_close():
    """At 15:50 the day's bar isn't known: the decision used the day before's close and traded a day
    late. With daily bars only, decisions inside the session move to the close."""
    seen = []

    class Hold:
        settings = {}

        def decide(self, view, p):
            bars = view.daily("xnas:AAA")
            seen.append((view.as_of.astimezone(NY), bars.index[-1].date() if len(bars) else None))
            return {k: 1.0 for k in view.universe()}

    rec = run(Hold(), _daily_data())  # the market's default decision time, 15:50
    assert all(t.time() == time(16, 0) and last == t.date() for t, last in seen)
    first = rec.fills[0]
    assert first.time.astimezone(NY) == ny(date(2024, 3, 6), "09:30")  # decided Tue at the close
    assert any("made at the close" in line for line in rec.log)
    # a time before the open is kept: it already sees the day before's close
    c = DecisionClock(NASDAQ, date(2024, 3, 4), date(2024, 3, 8), {"decide_at": ["09:00", "15:50"]}, daily_only=True)
    assert sorted({t.astimezone(NY).time() for t in c.times()}) == [time(9, 0), time(16, 0)]


def test_daily_fills_pay_the_normal_spread():
    """Daily fills are stamped at the open only because that's the price a daily bar gives; they used to
    pay the opening spread (3x) every time."""
    rec = run(Fixed({(1, "16:30"): {"xnas:AAA": 1.0}}, {"decide_at": "16:30"}), _daily_data(5))
    f = rec.fills[0]
    assert f.cost / (f.quantity * f.price) * 1e4 == pytest.approx(8.0)  # 5 bps half spread + 3 bps slippage


def test_half_day_does_not_decide_twice_at_once():
    c = DecisionClock(NASDAQ, date(2024, 11, 25), date(2024, 12, 2), {"decide_at": ["12:50", "15:50"]})
    times = list(c.times())
    assert len(times) == len(set(times))
    assert [t.astimezone(NY).time() for t in times if t.astimezone(NY).date() == date(2024, 11, 29)] == [time(12, 50)]
