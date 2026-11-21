"""Markets own their sessions, holidays and run defaults; runs resolve settings in layers."""
from datetime import date, time

import pytest

from titanium.app.settings import migrate_run_settings
from titanium.app.workspace import Workspace
from titanium.core.calendars import CmeEquityCalendar, NasdaqCalendar
from titanium.core.layers import layer_of, merge_settings
from titanium.core.markets import CME_GLOBEX, MARKETS, NASDAQ, Market, MarketDefaults
from titanium.core.plugins import Library


def test_each_market_has_its_own_defaults():
    assert NASDAQ.defaults.extended_hours is False and CME_GLOBEX.defaults.extended_hours is True
    s = NASDAQ.defaults.settings()
    assert s["decide_at"] == "15:50" and s["costs"]["equity"]["half_spread_bps"] == 5.0
    assert s["costs"]["futures"] == {"commission_per_side": 0.85, "slippage_ticks": 1.0}
    from titanium.core.sim.costs import CostModel
    assert CostModel.from_settings(s["costs"]).equity.slippage_bps == 3.0  # the engine reads them as they are
    for bad in ({"slippage_bps": -1}, {"decide_at": "25:00"}, {"decide_at": "soon"}):
        with pytest.raises(ValueError):
            MarketDefaults(**bad)


def test_market_defaults_read_back_from_saved_text():
    d = MarketDefaults.from_dict({"extended_hours": "true", "decide_at": "10:00", "slippage_bps": "x",
                                  "futures_commission": "1.5", "unknown": 3})
    assert d == MarketDefaults(extended_hours=True, decide_at="10:00", futures_commission=1.5)
    assert MarketDefaults.from_dict({"extended_hours": "false"}, CME_GLOBEX.defaults).extended_hours is False
    assert MarketDefaults.from_dict(d.to_dict()) == d


def test_settings_merge_in_layers_and_say_where_a_value_came_from():
    app, market = {"capital": 1e5}, {"decide_at": "15:50", "costs": {"equity": {"slippage_bps": 3, "half_spread_bps": 5}}}
    strategy, run = {"costs": {"equity": {"slippage_bps": 4}}}, {"costs": {"stress": 2}}
    out = merge_settings(app, market, strategy, run)
    assert out["costs"] == {"equity": {"slippage_bps": 4, "half_spread_bps": 5}, "stress": 2}
    layers = [("app", app), ("market", market), ("strategy", strategy), ("run", run)]
    assert layer_of("capital", *layers) == "app"
    assert layer_of("decide_at", *layers) == "market"
    assert layer_of("costs.equity.slippage_bps", *layers) == "strategy"
    assert layer_of("costs.equity.half_spread_bps", *layers) == "market"
    assert layer_of("costs.stress", *layers) == "run"
    assert layer_of("every", *layers) is None


def test_cme_has_its_own_holidays_and_early_closes():
    cme, nas = CmeEquityCalendar(), NasdaqCalendar()
    # CME settles on the same days, so daily bars line up with stocks
    assert cme.trading_days(date(2024, 1, 1), date(2024, 12, 31)) == nas.trading_days(date(2024, 1, 1),
                                                                                      date(2024, 12, 31))
    assert nas.early_close(date(2024, 11, 29)) == time(13, 0)
    assert cme.early_close(date(2024, 11, 29)) == time(13, 15)  # the day after Thanksgiving
    assert cme.early_close(date(2024, 11, 27)) is None
    h = CME_GLOBEX.holidays(2024)
    assert h[date(2024, 12, 25)] == "Christmas Day: closed"
    assert h[date(2024, 1, 15)].startswith("Martin Luther King Jr. Day: halts at 13:00")
    assert NASDAQ.holidays(2024)[date(2024, 3, 29)] == "Good Friday"
    assert all(d.weekday() < 5 for d in h)


def test_the_workspace_lists_markets_and_their_edited_defaults():
    ws = Workspace()
    assert set(ws.markets()) >= set(MARKETS)
    heard = []
    ws.market_defaults_changed.connect(lambda mid, d: heard.append((mid, d)))
    ws.set_market_defaults("cme", MarketDefaults(extended_hours=False))
    ws.set_market_defaults("cme", MarketDefaults(extended_hours=False))
    assert heard == [("cme", MarketDefaults(extended_hours=False))]
    assert ws.market("cme").defaults.extended_hours is False and CME_GLOBEX.defaults.extended_hours is True
    assert ws.run_settings(market="cme")["extended_hours"] is False
    ws.set_market_defaults("cme", None)
    assert ws.market("cme").defaults == CME_GLOBEX.defaults
    with pytest.raises(KeyError):
        ws.market("nowhere")
    # a plugin can add a market
    lse = Market("xlon", "London", "Europe/London", "GBP", NASDAQ.sessions, calendar=NasdaqCalendar())
    ws.registry.add(Library.MARKETS, "xlon", lse, plugin="test")
    assert ws.market("xlon").currency == "GBP" and ws.run_settings(market="xlon")["decide_at"] == "15:50"


def test_futures_runs_trade_round_the_clock_by_the_market_default():
    ws = Workspace()
    fut = ws.datasets.add("synthetic_futures", {"n_days": 10})
    assert ws.run_settings(dataset_id=fut.id)["extended_hours"] is True
    stocks = ws.datasets.add("synthetic_stocks", {"n_symbols": 3, "n_days": 10})
    assert ws.run_settings(dataset_id=stocks.id)["extended_hours"] is False


def test_old_run_costs_move_into_the_markets():
    moved = migrate_run_settings({"decide_at": "10:00", "half_spread_bps": "5.0", "futures_commission": 2})
    assert moved["xnas"].decide_at == "10:00" and moved["cme"].futures_commission == 2
    assert moved["cme"].extended_hours is True  # the market's own default is kept
    assert migrate_run_settings({"half_spread_bps": 5.0}) == {}  # unchanged values move nothing
