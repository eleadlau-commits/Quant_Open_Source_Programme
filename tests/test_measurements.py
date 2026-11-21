"""Measurements (Phase 2E): numbers and curves read from run records, and the default strategy."""
from datetime import datetime, timedelta, timezone

import pytest

from titanium.core import measurements as M
from titanium.core.baseline import DEFAULT_ID, HoldEverything, baseline_settings
from titanium.core.plugins import Library, Registry
from titanium.core.portfolio import PortfolioState, Position
from titanium.core.run import RunRecord, Trade

UTC = timezone.utc
T0 = datetime(2024, 1, 2, 20, 50, tzinfo=UTC)


def record(equities, positions=None, trades=(), probes=None, capital=100.0):
    states = []
    for i, e in enumerate(equities):
        pos = (positions or {}).get(i, {})
        states.append(PortfolioState(T0 + timedelta(days=i), cash=e - sum(p.exposure for p in pos.values()),
                                     positions=pos, equity=e, capital=capital))
    return RunRecord("r", "S", {}, "d", "v1", T0, capital=capital, states=states, trades=list(trades),
                     probes=probes or {})


def trade(pnl, flags=()):
    return Trade("xnas:A", T0, 10.0, T0, 11.0, 1, 1, pnl=pnl, flags=list(flags))


def test_profit_in_three_displays():
    r = record([100, 110, 99])
    assert [v for _, v in M.Profit().compute(r)] == pytest.approx([1.0, 1.1, 0.99])
    assert [v for _, v in M.Profit().compute(r, display="%")] == pytest.approx([0, 10, -1])
    assert [v for _, v in M.Profit().compute(r, display="currency")] == pytest.approx([0, 10, -1])
    assert M.TotalProfit().compute(r) == pytest.approx(-1)
    assert M.Profit.unit("currency", "USD") == "USD"


def test_drawdown_and_max_drawdown():
    r = record([100, 120, 90, 130, 117])
    assert [v for _, v in M.Drawdown().compute(r)] == pytest.approx([0, 0, -25, 0, -10])
    assert M.MaxDrawdown().compute(r) == pytest.approx(-25)
    assert M.MaxDrawdown.when(r) == T0 + timedelta(days=2)


def test_sharpe_is_annualised_from_the_runs_own_steps():
    r = record([100, 101, 100, 102, 101, 103])
    rets = M.period_returns(r)
    assert len(rets) == 5
    import statistics

    want = statistics.mean(rets) / statistics.stdev(rets) * (5 / (5 / 365.25)) ** 0.5
    assert M.Sharpe().compute(r) == pytest.approx(want)
    assert M.Sharpe().compute(record([100, 100, 100])) is None  # no spread
    assert M.Sharpe().compute(record([100])) is None


def test_hit_rate_counts_closed_trades_after_costs():
    r = record([100, 100], trades=[trade(5), trade(-1), trade(2), trade(9, ["open"])])
    assert M.HitRate().compute(r) == pytest.approx(200 / 3)
    assert M.HitRate().compute(record([100])) is None


def test_exposure_weights_positions_cash_equity():
    pos = {1: {"xnas:A": Position("xnas:A", 2, 10, 20, exposure=20.0), "xnas:B": Position("xnas:B", -1, 30, -30, exposure=-30.0)}}
    r = record([100, 100, 100], positions=pos)
    assert [v for _, v in M.Exposure().compute(r)] == pytest.approx([0, 50, 0])
    assert M.AverageExposure().compute(r) == pytest.approx(50 / 3)
    w = M.Weights().compute(r)
    assert set(w) == {"xnas:A", "xnas:B"} and [v for _, v in w["xnas:B"]] == pytest.approx([0, -30, 0])
    assert [v for _, v in M.Positions().compute(r)["xnas:A"]] == [0, 2, 0]
    assert [v for _, v in M.Cash().compute(r)["cash"]] == pytest.approx([100, 110, 100])
    assert [v for _, v in M.Equity().compute(r)["equity"]] == [100, 100, 100]


def test_probes_flatten_numbers_mappings_and_switches():
    t1, t2 = T0, T0 + timedelta(days=1)
    r = record([100, 100], probes={"m1": [(t1, {"A": 0.1, "B": "x"}), (t2, {"A": 0.2})],
                                   "m2": [(t1, 3), (t2, True)], "m3": [(t1, "text")]})
    out = M.Probes().compute(r)
    assert out == {"m1 · A": [(t1, 0.1), (t2, 0.2)], "m2": [(t1, 3.0), (t2, 1.0)]}
    assert list(M.Probes().compute(r, probe="m2")) == ["m2"]


def test_registered_in_the_library_and_plugins_can_add_more():
    reg = Registry()
    M.register_measurements(reg)
    M.register_measurements(reg)  # twice is fine
    names = {e.name for e in reg.entries(Library.MEASUREMENTS)}
    assert {"profit", "sharpe", "max_drawdown", "hit_rate", "avg_exposure", "positions", "weights", "cash",
            "equity", "probes"} <= names
    assert set(M.STAT_TILES) <= names

    class Turnover:
        info = M.MeasurementInfo("turnover", "Turnover", M.Scope.GLOBAL, "%", kind="number")

        def compute(self, run, **_):
            return 0.0

    reg.add(Library.MEASUREMENTS, "turnover", Turnover(), plugin="p")
    assert "turnover" in [m.info.id for m in M.measurements(reg, "number")]
    assert all(m.info.kind == "series" for m in M.measurements(reg, "series"))
    reg.remove_plugin("p")
    assert "turnover" not in [m.info.id for m in M.measurements(reg)]


def test_default_strategy_shares_the_terms_and_rebalances_monthly():
    cfg = baseline_settings({"capital": 5e4, "costs": {"stress": 2}, "decide_at": "10:00", "probes": ["m1"],
                             "datasets": ["x"], "start": "2024-01-01"})
    assert cfg["capital"] == 5e4 and cfg["costs"] == {"stress": 2} and cfg["start"] == "2024-01-01"
    assert "probes" not in cfg and "datasets" not in cfg and cfg["rebalance"] == "month"

    class View:
        def __init__(self, day, names):
            self.today, self._names = day, names

        def universe(self):
            return self._names

    s = HoldEverything(cfg)
    from datetime import date

    assert s.decide(View(date(2024, 1, 2), ["A", "B"]), None) == {"A": 0.5, "B": 0.5}
    assert s.decide(View(date(2024, 1, 3), ["A", "B", "C"]), None) is None  # same month: hold
    assert s.decide(View(date(2024, 2, 1), ["A", "B", "C", "D"]), None) == {k: 0.25 for k in "ABCD"}


def test_a_real_run_and_its_default_strategy_through_the_run_service():
    from titanium.app.workspace import Workspace
    from titanium.core.module_library import momentum_rotation

    ws = Workspace()
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 6, "n_days": 70, "seed": 3})
    g = momentum_rotation()
    g.settings["datasets"] = [info.id]
    g.knob_values["m2.days"] = 10
    ws.strategies.put(g.id, g)
    rec = ws.runs.run(g.id, {"probes": ["m1"], "capital": 50_000})
    assert rec.status == "done", rec.error
    assert ws.runs.baseline_for(rec) is None
    base = ws.runs.commit(ws.runs.prepare_baseline(rec).execute())
    assert base.status == "done" and base.strategy_id == DEFAULT_ID and base.capital == 50_000
    assert ws.runs.baseline_for(rec) is base
    assert [s.time for s in base.states] == [s.time for s in rec.states]  # same steps, line up on the chart
    # every built-in measurement reads both records
    for m in M.measurements(ws.registry):
        for r in (rec, base):
            m.compute(r)
    assert M.Probes().compute(rec)  # momentum scores per name
    assert 0 < M.AverageExposure().compute(base) <= 100
    # a different capital is a different yardstick
    other = ws.runs.run(g.id, {"capital": 10_000})
    assert ws.runs.baseline_for(other) is None
