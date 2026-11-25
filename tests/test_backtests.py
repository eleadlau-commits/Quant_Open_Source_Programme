"""Phase 2F: the backtest library and service, the honest tests, and the Compare and Backtests pages."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from titanium.app.workspace import Workspace
from titanium.core.backtests import (RandomPicks, Verdict, aligned_returns, ingredients, knob_variants, sharpe,
                                     split_time, step_returns, t_stat, without)
from titanium.core.baseline import DEFAULT_ID
from titanium.core.module_library import momentum_rotation
from titanium.core.portfolio import PortfolioState
from titanium.core.run import RunRecord
from titanium.core.strategy import Decision

UTC = timezone.utc
IDS = ["out_of_sample", "walk_forward", "bootstrap", "deflated_sharpe", "cost_stress", "random_baseline",
       "benchmark", "parameter_stability", "ablation"]


def record(equities, start=datetime(2024, 1, 2, 21, tzinfo=UTC), **kw) -> RunRecord:
    states = [PortfolioState(start + timedelta(days=i), e, {}, e, equities[0]) for i, e in enumerate(equities)]
    return RunRecord("r", "S", {}, "d", "", start, states=states, capital=equities[0], **kw)


@pytest.fixture(scope="module")
def ws():
    w = Workspace()
    info = w.datasets.add("synthetic_stocks", {"n_symbols": 5, "n_days": 45, "seed": 3})
    g = momentum_rotation(id="S1")
    g.settings["datasets"] = [info.id]
    g.knob_values = {"m1.days": 10, "m2.days": 15}
    w.strategies.put("S1", g)
    w.rec = w.runs.run("S1")
    assert w.rec.status == "done", w.rec.error
    return w


# ---- helpers --------------------------------------------------------------------------
def test_step_returns_split_and_stats():
    rec = record([100, 110, 99, 99, 108.9])
    assert step_returns(rec) == pytest.approx([0.1, -0.1, 0.0, 0.1])
    cut = split_time(rec, 0.5)
    assert cut == rec.states[2].time
    assert step_returns(rec, end=cut) == pytest.approx([0.1])  # the step ending at the cut is in the later part
    assert step_returns(rec, start=cut) == pytest.approx([-0.1, 0.0, 0.1])
    assert sharpe([0.01, 0.01]) == 0.0 and t_stat([0.0]) == 0.0
    assert sharpe([0.02, 0.0, 0.01]) > 0
    a, b = aligned_returns(rec, record([100, 100, 100, 100, 100]))
    assert len(a) == len(b) == 4 and b == [0.0] * 4


def test_knob_variants_move_number_knobs_within_their_range():
    g = momentum_rotation()
    vs = knob_variants(g, spread=0.25)
    keys = [next(iter(k)) for k, _ in vs]
    assert "m3.positive_only" not in keys  # switches are ablation's
    for knobs, label_ in vs:
        (key, v), = knobs.items()
        kn = g.knobs()[key]
        assert kn.lo <= v <= kn.hi and isinstance(v, int) and v != g.knob_value(key) and key in label_
    assert len(vs) <= 2 * 4


def test_ingredients_and_without_skip_a_filter_module():
    g = momentum_rotation()
    opts = dict(ingredients(g))
    trend = next(m.id for m in g.modules if m.name == "Above moving average")
    assert f"module:{trend}" in opts and "knob:m3.positive_only" in opts
    assert list(opts)[0] == f"module:{trend}"  # modules first
    g2, knobs = without(g, f"module:{trend}")
    assert knobs == {} and trend not in {m.id for m in g2.modules} and trend in {m.id for m in g.modules}
    mom = next(m.id for m in g.modules if m.name == "Momentum")
    top = next(m.id for m in g.modules if m.kind == "decide" or m.name.startswith("Top"))
    assert any(ln.src_module == mom and ln.dst_module == top for ln in g2.links)
    _, knobs = without(g, "knob:m3.positive_only")
    assert knobs == {"m3.positive_only": False}


class _View:
    def __init__(self, names, day):
        self.names, self.today = names, day

    def universe(self):
        return list(self.names)


class _Inner:
    def __init__(self, script):
        self.script, self.i = script, 0

    def decide(self, view, p):
        d = self.script[self.i]
        self.i += 1
        return d


def test_random_picks_keep_count_weights_and_holding():
    script = [{"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.5}, {"A": 0.5, "C": 0.5}, {}]
    rp = RandomPicks(_Inner(script), seed=1, settings={})
    names = list("ABCDEFGH")
    p = PortfolioState(datetime(2024, 1, 2, tzinfo=UTC), 100.0)
    out = [rp.decide(_View(names, None), p) for _ in script]
    assert all(isinstance(d, Decision) for d in out)
    assert [sorted(d.targets.values()) for d in out[:3]] == [[0.5, 0.5]] * 3
    assert out[0].targets == out[1].targets  # held names keep their stand-ins
    kept = set(out[1].targets) & set(out[2].targets)
    assert len(kept) == 1  # A kept its stand-in, B's went with B
    assert out[3].targets == {}


def test_random_picks_flip_a_coin_with_one_instrument():
    script = [{"X": 1.0}] * 3
    flips = set()
    for seed in range(12):
        rp = RandomPicks(_Inner(list(script)), seed=seed, settings={})
        p = PortfolioState(datetime(2024, 1, 2, tzinfo=UTC), 100.0)
        ds = [rp.decide(_View(["X"], None), p).targets["X"] for _ in script]
        assert len(set(ds)) == 1  # the position keeps its direction while held
        flips.add(ds[0])
    assert flips == {1.0, -1.0}


# ---- the service and the tests --------------------------------------------------------
def test_library_lists_the_honest_tests_in_order(ws):
    assert [t.id for t in ws.backtests.tests()] == IDS
    assert all(t.doc and t.name for t in ws.backtests.tests())
    assert ws.backtests.plugin_of("bootstrap") == "honest-tests"


def test_every_test_gives_a_verdict_on_a_real_run(ws):
    params = {"random_baseline": {"n": 4}, "bootstrap": {"n": 300}, "out_of_sample": {"split": 0.5},
              "walk_forward": {"folds": 2}}
    for tid in IDS:
        res = ws.backtests.run(ws.rec.id, tid, params.get(tid, {}))
        assert res.status == "done", (tid, res.verdict.explanation)
        assert res.verdict.headline and res.outcome in ("pass", "fail", "na")
        assert ws.backtests.results(ws.rec.id)[tid] is res
    rs = ws.backtests.results(ws.rec.id)
    assert rs["random_baseline"].reruns == 4
    assert rs["cost_stress"].verdict.details["stressed"] < rs["cost_stress"].verdict.details["net"] \
        < rs["cost_stress"].verdict.details["gross"]
    # the knob variants are shared: parameter stability needed no new runs after out-of-sample
    assert rs["parameter_stability"].reruns == 0 and rs["out_of_sample"].reruns >= 2
    assert rs["ablation"].verdict.details["ingredient"].startswith("module:")
    # the benchmark's default-strategy run joins the session's runs, for Compare
    assert any(ws.runs.get(i).strategy_id == DEFAULT_ID for i in ws.runs.ids())
    # nothing else (variants, random versions) was added to the runs
    assert [ws.runs.get(i).strategy_id for i in ws.runs.ids()].count("S1") == 1


def test_deflated_sharpe_counts_versions_run_this_session(ws):
    one = ws.backtests.run(ws.rec.id, "deflated_sharpe").verdict.details["trials"]
    g = copy.deepcopy(ws.strategies.get("S1"))
    g.knob_values["m3.top"] = 2
    ws.strategies.put("S1", g)
    other = ws.runs.run("S1")
    try:
        assert ws.backtests.run(other.id, "deflated_sharpe").verdict.details["trials"] == one + 1
        assert ws.backtests.run(other.id, "deflated_sharpe", {"trials": 50}).verdict.details["trials"] == 50
    finally:
        ws.runs.remove(other.id)
        g.knob_values.pop("m3.top")
        ws.strategies.put("S1", g)


def test_used_tests_and_params_live_in_the_strategy(ws):
    g = ws.strategies.get("S1")
    assert set(ws.backtests.used(g)) == set(IDS)  # says nothing: every test
    ws.backtests.set_used("S1", {"bootstrap": {"n": 250, "block": 3}, "cost_stress": {}})
    g = ws.strategies.get("S1")
    assert ws.backtests.used(g) == {"bootstrap": {"n": 250, "block": 3}, "cost_stress": {}}
    job = ws.backtests.prepare(ws.rec.id, "bootstrap")
    assert job.params == {"n": 250, "block": 3}
    ws.backtests.commit(job.execute())
    g.settings.pop("backtests")
    ws.strategies.put("S1", g)


def test_a_broken_test_is_a_result_not_a_crash(ws):
    from titanium.core.backtests import BacktestInfo
    from titanium.core.plugins import Library

    class Broken:
        info = BacktestInfo("broken", "Broken", "Always raises")

        def evaluate(self, ctx, **_):
            raise ZeroDivisionError("oops")

    ws.registry.add(Library.BACKTESTS, "broken", Broken())
    try:
        res = ws.backtests.run(ws.rec.id, "broken")
        assert res.status == "failed" and res.outcome == "na" and "oops" in res.verdict.explanation
    finally:
        ws.registry._entries[Library.BACKTESTS].pop("broken")
        ws.backtests.forget(ws.rec.id)


def test_cancel_stops_a_test_between_reruns(ws):
    job = ws.backtests.prepare(ws.rec.id, "random_baseline", {"n": 50})
    assert job.id in ws.backtests.active()
    ws.backtests.cancel(job.id)
    res = job.execute()
    assert res.status == "cancelled" and res.verdict.passed is None and ws.backtests.active() == []


def test_only_finished_runs_can_be_tested(ws):
    rec = copy.copy(ws.rec)
    rec.status = "failed"
    with pytest.raises(ValueError, match="finished"):
        ws.backtests.prepare(rec, "bootstrap")
    with pytest.raises(KeyError, match="no backtest"):
        ws.backtests.prepare(ws.rec.id, "nope")


def test_verdict_outcome():
    assert Verdict("t", True, "").outcome == "pass"
    assert Verdict("t", False, "").outcome == "fail"
    assert Verdict("t", None, "").outcome == "na"


# ---- the pages --------------------------------------------------------------------------
@pytest.fixture
def page_ctx(qapp, tmp_path, ws):
    from PySide6.QtCore import QSettings

    from titanium.desktop.context import AppContext

    return AppContext(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat), ws)


def test_backtests_page_runs_tests_and_groups_verdicts(page_ctx, ws):
    from titanium.desktop.pages.backtests import BacktestsView

    ws.backtests.forget(ws.rec.id)
    v = BacktestsView(page_ctx)
    v.background = False
    v.queue.background = False
    assert v.strategy_id() == "S1" and v.record() is ws.rec
    assert v.table.keys() == IDS
    v.run_tests(["bootstrap", "deflated_sharpe", "parameter_stability"])
    assert set(v.cards) == {"bootstrap", "deflated_sharpe", "parameter_stability"}
    shown = {k: c.outcome for k, c in v.cards.items()}
    assert shown == {k: r.outcome for k, r in ws.backtests.results(ws.rec.id).items() if k in shown}
    counts = {k: sum(1 for o in shown.values() if o == k) for k in ("pass", "fail", "na")}
    assert {k: v.tiles[k].value.text() for k in counts} == {k: str(n) for k, n in counts.items()}
    assert v.status.text().startswith("Done") and not v.queue.running
    # folding is remembered by test
    v.cards["bootstrap"].set_folded(True, emit=True)
    v.refresh()
    assert v.cards["bootstrap"].folded and not v.cards["deflated_sharpe"].folded


def test_backtests_page_uses_switch_writes_the_strategy(page_ctx, ws, qapp):
    from PySide6.QtCore import Qt

    from titanium.desktop.pages.backtests import BacktestsView

    v = BacktestsView(page_ctx)
    item = v.table.item(v.table.keys().index("ablation"), 1)
    item.setCheckState(Qt.Unchecked)
    for _ in range(5):
        qapp.processEvents()
    assert "ablation" not in ws.backtests.used(ws.strategies.get("S1"))
    assert "bootstrap" in ws.backtests.used(ws.strategies.get("S1"))
    g = ws.strategies.get("S1")
    g.settings.pop("backtests", None)
    ws.strategies.put("S1", g)


def test_backtests_page_says_when_the_strategy_changed(page_ctx, ws):
    from titanium.desktop.pages.backtests import BacktestsView

    v = BacktestsView(page_ctx)
    v.show()  # a hidden page catches up when it is next shown, not on every change
    assert v.stale.isHidden()
    g = copy.deepcopy(ws.strategies.get("S1"))
    g.knob_values["m1.days"] = 12
    ws.strategies.put("S1", g)
    assert not v.stale.isHidden() and "changed" in v.stale.text()
    g.knob_values["m1.days"] = 10
    ws.strategies.put("S1", g)
    assert v.stale.isHidden()
    v.close()


def test_compare_page_ticks_runs_and_measures_the_window(page_ctx, ws):
    from titanium.desktop.pages.compare import CompareView, window_stats

    v = CompareView(page_ctx)
    v.background = False
    assert [r.id for _n, r in v.shown()] == [ws.rec.id]
    v.redraw()  # the default strategy now exists (the benchmark ran it, or redraw did)
    assert any(r.strategy_id == DEFAULT_ID for _n, r in v._bases)
    names = [s.name for s in v.chart.series]
    assert names[0] == ws.strategies.get("S1").name and any(s.dashed for s in v.chart.series)
    assert [m.info.id for m in v._curves][0] == "profit"
    # profit is measured from the window start
    full = v.chart.full_range()
    mid = (full[0] + full[1]) / 2
    v.chart.set_view((mid, full[1]))
    first = v.chart.series[0]
    assert first.at(mid + 1) == pytest.approx(0.0, abs=1e-9) or first.v[0] != 0.0
    st = window_stats(ws.rec, mid, full[1])
    i0 = max(i for i, s in enumerate(ws.rec.states) if s.time.timestamp() <= mid)
    assert st["profit"] == pytest.approx(ws.rec.states[-1].equity / ws.rec.states[i0].equity - 1)
    assert v.table.rowCount() == len(v._shown) + len(v._bases)
    # untick the strategy: nothing to draw
    top = v.tree.topLevelItem(0)
    from PySide6.QtCore import Qt

    top.setCheckState(0, Qt.Unchecked)
    assert v.shown() == [] and v.chart.series == []
    top.setCheckState(0, Qt.Checked)
    v.show_measurement("drawdown")
    assert v.measurement().info.id == "drawdown" and max(s.v.max() for s in v.chart.series) <= 0


def test_compare_page_empty_without_runs(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from titanium.desktop.context import AppContext
    from titanium.desktop.pages.compare import CompareView

    v = CompareView(AppContext(QSettings(str(tmp_path / "e.ini"), QSettings.IniFormat)))
    assert not v.empty.isHidden() and v.body.isHidden()


def test_run_view_backtest_buttons_run_tests(page_ctx, ws):
    from titanium.desktop.pages.run_view import BACKTESTS, RunView

    view = RunView(ws.strategies.get("S1"), ws)
    view.background = False
    assert not any(b.isEnabled() for b in view.backtest_buttons.values())
    view.run()
    assert view.record is not None and all(b.isEnabled() for b in view.backtest_buttons.values())
    assert {b for b, _n, _t in BACKTESTS} <= set(IDS)
    view.backtest_buttons["cost_stress"].click()
    assert "cost_stress" in ws.backtests.results(view.record.id)
    assert [c.name for c in view._verdict_cards] == ["Cost stress"]
    ws.runs.remove(view.record.id)
