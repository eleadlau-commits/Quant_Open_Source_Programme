"""The chart component and the Run view (Phase 2E)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from titanium.desktop.app import build_window
from titanium.desktop.design.chart import (
    MAIN, RIGHT, SUB, ChartMarker, ChartSeries, TimeChart, nice_ticks, time_ticks,
)

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
T0 = datetime(2024, 1, 2, 20, 50, tzinfo=UTC)


def pts(n, f=lambda i: 1 + i / 100):
    return [(T0 + timedelta(days=i), f(i)) for i in range(n)]


# ---- chart --------------------------------------------------------------------------
def test_nice_ticks_and_time_ticks():
    assert nice_ticks(0.93, 1.21) == pytest.approx([1.0, 1.1, 1.2]) or nice_ticks(0.93, 1.21)[0] >= 0.93
    assert all(0.93 <= v <= 1.21 for v in nice_ticks(0.93, 1.21))
    a, b = T0.timestamp(), (T0 + timedelta(days=200)).timestamp()
    ticks = time_ticks(a, b, NY, 8)
    assert 2 <= len(ticks) <= 8 and all(a <= t <= b for t, _ in ticks)
    assert all(datetime.fromtimestamp(t, NY).day == 1 for t, _ in ticks)  # month starts, local time
    intraday = time_ticks(a, a + 6 * 3600, NY, 8)
    assert all(":" in text for _, text in intraday)


def test_chart_draws_series_panels_markers_and_reads_the_crosshair(qapp):
    c = TimeChart()
    c.resize(800, 400)
    c.set_data([ChartSeries("S", pts(100)), ChartSeries("Default", pts(100, lambda i: 1), dashed=True),
                ChartSeries("w", pts(100, lambda i: i), panel=SUB),
                ChartSeries("over", pts(100, lambda i: -i), axis=RIGHT)],
               [ChartMarker(T0 + timedelta(days=10), 1, "Bought 5 A"), ChartMarker(T0 + timedelta(days=20), -1, "Closed")])
    c.show()
    qapp.processEvents()
    assert set(c._panels()) == {MAIN, SUB}
    assert c._right_pad() > c.R_PAD  # room for the overlay's axis
    assert len(c._marker_points()) == 2
    pt, m = c._marker_points()[0]
    assert c._marker_near(pt) is m
    assert c.series[0].at((T0 + timedelta(days=5, hours=3)).timestamp()) == pytest.approx(1.05)
    assert c.series[0].at((T0 - timedelta(days=1)).timestamp()) is None
    QTest.mouseMove(c, QPoint(400, 150))
    qapp.processEvents()
    assert c._hover is not None
    assert not c.grab().isNull()
    # empty chart says what goes there
    c.set_data([])
    c.empty_text = "Run it"
    assert not c.grab().isNull() and c.full_range() is None


def test_chart_zooms_pans_and_resets(qapp):
    c = TimeChart()
    c.resize(800, 400)
    c.set_data([ChartSeries("S", pts(100))])
    full = c.full_range()
    c.zoom(0.5)
    a, b = c.window()
    assert b - a == pytest.approx((full[1] - full[0]) / 2)
    c.set_view((full[0] - 1e9, full[0] + (b - a) - 1e9))  # pans past the start: clamped
    assert c.window()[0] == pytest.approx(full[0])
    ev = QWheelEvent(QPointF(400, 200), QPointF(400, 200), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    c.wheelEvent(ev)  # zoom out
    QTest.mouseDClick(c, Qt.LeftButton, pos=QPoint(400, 200))
    assert c.view is None and c.window() == full
    c.set_data([ChartSeries("S", pts(100))], keep_view=False)
    assert c.view is None


def test_chart_in_the_gallery(qapp):
    from titanium.desktop.design.gallery import build, sample_chart

    assert sample_chart().series
    g = build()
    assert g.widget().findChildren(TimeChart)


# ---- run view -----------------------------------------------------------------------
@pytest.fixture
def win(qapp, ctx):
    w = build_window(ctx)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


@pytest.fixture(scope="module")
def dataset_root(tmp_path_factory):
    """One small synthetic dataset, built once for the module's tests."""
    from titanium.app.workspace import Workspace

    root = tmp_path_factory.mktemp("data")
    Workspace(data_root=root).datasets.add("synthetic_stocks", {"n_symbols": 6, "n_days": 70, "seed": 3})
    return root


@pytest.fixture
def run_tab(qapp, tmp_path, dataset_root):
    from PySide6.QtCore import QSettings

    from titanium.app.workspace import Workspace
    from titanium.core.module_library import momentum_rotation
    from titanium.desktop.context import AppContext

    ws = Workspace(data_root=dataset_root)
    ctx = AppContext(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat), ws)
    w = build_window(ctx)
    w.show()
    w.show_page("strategies")
    g = momentum_rotation(id="S1")
    g.knob_values["m2.days"] = 10  # so it trades within 70 days
    w.views["strategies"].open_graph(g)
    tab = w.views["strategies"].tabs.currentWidget()
    tab.run_view.background = False
    qapp.processEvents()
    yield w, ws, tab
    w.close()


def use_dataset(ws):
    g = ws.strategies.get("S1")
    g.settings["datasets"] = [ws.datasets.infos("core")[0].id]
    ws.strategies.put(g.id, g)  # announced, as the Data section and the dataset picker do


def test_run_needs_a_dataset_then_runs_and_fills_everything(run_tab, qapp):
    w, ws, tab = run_tab
    rv = tab.run_view
    assert rv.chart.series == [] and rv.tiles["sharpe"].value.text() == "–"
    tab.run()
    assert "dataset" in rv.status.text() and rv.record is None
    info = ws.datasets.infos("core")[0]
    rv.dataset.setCurrentIndex(rv.dataset.findData(info.id))
    rv._pick_dataset(rv.dataset.currentIndex())
    assert ws.strategies.get("S1").settings["datasets"] == [info.id]
    states = []
    rv.running_changed.connect(lambda r, t: states.append(r))
    tab.run()
    assert tab.switch.index() == 2  # shows the Run view
    assert states[0] is True and states[-1] is False and not tab.run_btn.running
    rec = rv.record
    assert rec is not None and rec.status == "done" and rec.trades
    assert rv.baseline is not None and rv.baseline.strategy_id == "default"
    assert "m1" in rec.probes  # transform modules are probed
    assert rv.tiles["total_profit"].value.text().endswith("%")
    assert "default" in rv.tiles["total_profit"].note.text()
    assert [s.name for s in rv.chart.series] == ["Momentum rotation", "Default strategy"]
    assert rv.chart.markers
    # the trade log dock shows the run's trades
    log = w.views["trade_log"]
    assert log.table.rowCount() == len(rec.trades)
    # profit as money, then a local series below and over
    rv.display.set_index(2)
    assert rv.chart.series[0].v[-1] == pytest.approx(rec.states[-1].equity - rec.capital)
    rv.local_pick.setCurrentIndex(rv.local_pick.findText("Weights"))
    assert any(s.panel == SUB for s in rv.chart.series)
    rv.overlay.set_index(1)
    assert any(s.axis == RIGHT for s in rv.chart.series) and not any(s.panel == SUB for s in rv.chart.series)
    rv.local_pick.setCurrentIndex(rv.local_pick.findText("Module outputs"))
    assert len([s for s in rv.chart.series if s.axis == RIGHT]) <= 8
    rv.show_default.setChecked(False)
    assert "Default strategy" not in [s.name for s in rv.chart.series]
    rv.main_pick.setCurrentIndex(rv.main_pick.findText("Drawdown"))
    assert not rv.display.isVisible()
    assert max(rv.chart.series[0].v) <= 0


def test_turning_a_knob_reruns_after_a_pause(run_tab, qapp):
    w, ws, tab = run_tab
    rv = tab.run_view
    use_dataset(ws)
    tab.run()
    first = rv.record
    assert first is not None, rv.status.text()
    assert not rv._timer.isActive()
    knobs = w.views["knobs"]
    knobs.controls["m3.top"].set_value(2)
    knobs.turn("m3.top", 2)  # as if the slider moved
    assert rv._timer.isActive()  # debounced
    rv._timer.timeout.emit()
    assert rv.record is not first and rv.record.strategy_snapshot["knob_values"]["m3.top"] == 2
    assert rv.baseline is not None  # same terms: the default strategy is reused
    assert len(ws.runs.records("default")) == 1
    # the Knobs and Trade log buttons bring their docks back
    w.docks["trade_log"].hide_by_user()
    rv.log_btn.click()
    qapp.processEvents()
    assert w.docks["trade_log"].isVisible()


def test_cancel_and_failed_runs(run_tab, qapp):
    w, ws, tab = run_tab
    rv = tab.run_view
    use_dataset(ws)
    rv.background = True
    tab.run()
    assert rv.running and tab.run_btn.running
    tab.run()  # pressing Run again cancels
    for _ in range(400):
        qapp.processEvents()
        if not rv.running:
            break
        QTest.qWait(10)
    assert not rv.running and not tab.run_btn.running
    assert rv.status.text() in ("Cancelled.",) or rv.record is not None
    # broken code: the run stops at the code view
    rv.background = False
    tab.code.editor.setPlainText("def broken(:\n")
    tab.run()
    assert tab.switch.index() == 1


def test_run_on_a_worker_thread_reports_progress(run_tab, qapp):
    w, ws, tab = run_tab
    rv = tab.run_view
    use_dataset(ws)
    rv.background = True
    seen = []
    rv.running_changed.connect(lambda r, t: seen.append((r, t)))
    assert rv.run()
    for _ in range(3000):
        qapp.processEvents()
        if rv.record is not None and rv.baseline is not None:
            break
        QTest.qWait(10)
    assert rv.record is not None and rv.record.status == "done" and rv.baseline is not None
    assert seen[-1] == (False, "")


def test_run_settings_show_where_each_value_comes_from_and_override_it(run_tab, qapp):
    from titanium.core.markets import MarketDefaults

    w, ws, tab = run_tab
    rv = tab.run_view
    use_dataset(ws)
    card = rv.settings_card
    assert rv.market_line.text().startswith("Next run: Nasdaq, regular hours (09:30–16:00), decides")
    assert card.sources["capital"].text() == "App default"
    assert card.sources["decide_at"].text() in ("Nasdaq default", "This strategy")
    assert card.sources["costs.equity.slippage_bps"].text() == "Nasdaq default"
    assert not card.editors["costs.futures.slippage_ticks"].isVisibleTo(card)  # Nasdaq lists stocks
    assert not card.resets["costs.equity.slippage_bps"].isVisibleTo(card)
    # a market edit reaches the panel
    ws.set_market_defaults("xnas", MarketDefaults(slippage_bps=6))
    assert card.editors["costs.equity.slippage_bps"].value() == 6
    # override for this strategy only, then back to the default
    card.editors["costs.equity.slippage_bps"].setValue(9)
    g = ws.strategies.get("S1")
    assert g.settings["costs"]["equity"]["slippage_bps"] == 9
    assert card.sources["costs.equity.slippage_bps"].text() == "This strategy"
    card.editors["extended_hours"].setChecked(True)
    assert g.settings["extended_hours"] is True and "all sessions" in rv.market_line.text()
    assert ws.runs.prepare("S1").settings["costs"]["equity"]["slippage_bps"] == 9
    card.use_default("costs.equity.slippage_bps")
    card.use_default("extended_hours")
    assert "costs" not in g.settings and "extended_hours" not in g.settings
    assert card.sources["costs.equity.slippage_bps"].text() == "Nasdaq default"
    # the status line says which market and hours the run used
    tab.run()
    assert rv.status.text().startswith("Last run: Nasdaq, regular hours")
