"""The Run view of a strategy tab: run it, read its measurements, turn its knobs.

The view is a thin reader of run records. A run goes through ``Workspace.runs``
(prepare on the UI thread, execute on a worker, commit back on the UI thread); the
default strategy is run once on the same terms and kept as the yardstick. Turning a
knob in the Knobs dock (or through ``turn``) re-runs after a short pause and redraws.
"""
from __future__ import annotations

import time
from datetime import timezone

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QVBoxLayout, QWidget

from ...core import measurements as M
from ...core.baseline import DEFAULT_NAME
from ...core.markets import MARKETS
from ...core.measurements import Profit, Scope
from ...core.run import RunRecord
from ...core.strategy import StrategyGraph
from .. import tasks
from ..backtest_queue import BacktestQueue
from ..design import tokens as T
from ..design.chart import MAIN, RIGHT, SUB, ChartMarker, ChartSeries, TimeChart
from ..design.components import (
    Card, Segmented, StatTile, VerdictCard, button, hbox, label,
)

S = T.SPACE
PROFIT_DISPLAYS = ("growth", "%", "currency")
MAX_LOCAL = 8  # local series drawn at once (the largest ones)
RERUN_DELAY_MS = 350
# Phase 2F wires these up
# the quick tests in the backtest block: ids in Library.BACKTESTS (the honest-tests plugin)
BACKTESTS = (("out_of_sample", "Out-of-sample", "Choose the knobs on the early part, score the later part it never saw"),
             ("cost_stress", "Cost stress", "Run again with every cost doubled"),
             ("random_baseline", "Random baseline", "Same timing, weights and holding periods, names picked at random"),
             ("walk_forward", "Walk-forward", "Re-choose the knobs before each stretch and score only what follows"))


def _pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "–"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _num(v: float | None) -> str:
    return "–" if v is None else f"{v:.2f}"


def _money(v: float, currency: str) -> str:
    return f"{v:+,.0f} {currency}" if abs(v) >= 100 else f"{v:+,.2f} {currency}"


class RunView(QWidget):
    """``running_changed(running, progress_text)`` keeps the tab's Run button in step."""

    running_changed = Signal(bool, str)

    def __init__(self, graph: StrategyGraph, workspace=None, open_page=None, parent=None):
        super().__init__(parent)
        self.graph = graph
        self.workspace = workspace
        self.open_page = open_page  # an Event the shell listens to (to show the trade log dock)
        self.background = True  # tests run inline
        self.record: RunRecord | None = None
        self.baseline: RunRecord | None = None
        self.job = None
        self._pending = False  # a rerun asked for while one is running
        self._started = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S["lg"])

        # dataset and status
        self.dataset = QComboBox()
        self.dataset.setMinimumWidth(260)
        self.dataset.setToolTip("The dataset this strategy trades")
        self.dataset.activated.connect(self._pick_dataset)
        self.status = label("Not run yet. Press Run or Ctrl+Enter.", "caption")
        self.knobs_btn = button("Knobs", "ghost", "knob", "Show the Knobs panel: turn one and the strategy runs again")
        self.knobs_btn.clicked.connect(lambda: self._show("knobs"))
        self.log_btn = button("Trade log", "ghost", "list", "Show the trade log")
        self.log_btn.clicked.connect(lambda: self._show("trade_log"))
        lay.addLayout(hbox(label("DATASET", "overline"), self.dataset, self.status, None, self.knobs_btn,
                           self.log_btn, spacing=S["md"]))

        # stat tiles
        self.tiles: dict[str, StatTile] = {}
        tiles = hbox(spacing=S["md"])
        for mid, caption in (("total_profit", "Profit"), ("sharpe", "Sharpe"), ("max_drawdown", "Max drawdown"),
                             ("hit_rate", "Hit rate"), ("avg_exposure", "Exposure")):
            t = StatTile(caption, "–", " ")
            self.tiles[mid] = t
            tiles.addWidget(t, 1)
        lay.addLayout(tiles)

        # chart and its pickers
        body = QGridLayout()
        body.setHorizontalSpacing(S["lg"])
        body.setVerticalSpacing(S["lg"])
        chart_card = Card()
        chart_card.body.setSpacing(S["sm"])
        self.main_pick = QComboBox()
        self.main_pick.setToolTip("The measurement on the chart")
        self.display = Segmented(["Growth", "%", "USD"])
        self.display.setToolTip("Show profit as growth of 1, in percent, or in money")
        self.local_pick = QComboBox()
        self.local_pick.setToolTip("A measurement per instrument or per step, drawn below the chart or over it")
        self.overlay = Segmented(["Below", "Over"])
        self.overlay.setToolTip("Draw it in a panel below the chart, or over the chart on its own scale")
        self.show_default = QCheckBox(DEFAULT_NAME)
        self.show_default.setChecked(True)
        self.show_default.setToolTip("The yardstick: equal weight in everything in the dataset, on the same costs")
        chart_card.body.addLayout(hbox(self.main_pick, self.display, self.show_default, None,
                                       label("Add", "caption"), self.local_pick, self.overlay, spacing=S["sm"]))
        self.chart = TimeChart()
        self.chart.empty_text = "Run the strategy (Ctrl+Enter) to see it here"
        self.chart.setMinimumHeight(300)
        chart_card.body.addWidget(self.chart, 1)
        self.chart_note = label("", "caption")
        chart_card.body.addWidget(self.chart_note)
        body.addWidget(chart_card, 0, 0)

        # backtests: quick tests on the last run; every test is on the Backtests page
        self.backtest_card = Card()
        self.backtest_buttons = {}
        self.bt_status = label("Does the result hold up? Run the strategy, then test it.", "caption")
        row = hbox(label("BACKTESTS", "overline"), self.bt_status, None)
        for bid, name, tip in BACKTESTS:
            b = button(name, tip=tip)
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, bid=bid: self.run_backtests([bid]))
            self.backtest_buttons[bid] = b
            row.addWidget(b)
        self.all_tests = button("All tests", "ghost", "backtests", "Open the Backtests page: every test, run one or all")
        self.all_tests.clicked.connect(lambda: self._show("backtests"))
        row.addWidget(self.all_tests)
        self.backtest_card.body.addLayout(row)
        self.verdicts = QGridLayout()
        self.verdicts.setHorizontalSpacing(S["md"])
        self.verdicts.setVerticalSpacing(S["sm"])
        self.verdicts.setColumnStretch(0, 1)
        self.verdicts.setColumnStretch(1, 1)
        self.backtest_card.body.addLayout(self.verdicts)
        self._verdict_cards: list = []
        self.bt_queue = None
        if workspace is not None:
            self.bt_queue = BacktestQueue(workspace, self)
            self.bt_queue.started.connect(self._bt_started)
            self.bt_queue.progress.connect(self._bt_progress)
            self.bt_queue.result.connect(lambda _r: self._show_verdicts())
            self.bt_queue.idle.connect(self._bt_idle)
        body.addWidget(self.backtest_card, 1, 0)
        body.setRowStretch(0, 1)
        lay.addLayout(body, 1)

        self._timer = QTimer(self, singleShot=True, interval=RERUN_DELAY_MS)
        self._timer.timeout.connect(self.run)
        self._poll = QTimer(self, interval=100)
        self._poll.timeout.connect(self._show_progress)

        self._fill_pickers()
        self.main_pick.currentIndexChanged.connect(lambda _i: self.redraw())
        self.local_pick.currentIndexChanged.connect(lambda _i: self.redraw())
        self.display.changed.connect(lambda _i: self.redraw())
        self.overlay.changed.connect(lambda _i: self.redraw())
        self.show_default.toggled.connect(lambda _v: self.redraw())
        if workspace is not None:
            workspace.datasets.added.connect(self._datasets_changed)
            workspace.datasets.removed.connect(self._datasets_changed)
        self._fill_datasets()
        self.set_graph(graph)
        self.redraw()

    def _show(self, view_id: str) -> None:
        if self.open_page is not None:
            self.open_page.emit(view_id)

    def detach(self) -> None:
        """Stop following the workspace (the tab is closing)."""
        self._timer.stop()
        self.cancel()
        if self.workspace is not None:
            self.workspace.datasets.added.disconnect(self._datasets_changed)
            self.workspace.datasets.removed.disconnect(self._datasets_changed)

    # ---- pickers ----------------------------------------------------------------------
    def _measurements(self, kind: str, scope: Scope | None = None) -> list:
        if self.workspace is None:
            reg = M.Registry()
            M.register_measurements(reg)
        else:
            reg = self.workspace.registry
        return M.measurements(reg, kind, scope)

    def _fill_pickers(self) -> None:
        self.main_pick.clear()
        for m in self._measurements("curve", Scope.GLOBAL):
            self.main_pick.addItem(m.info.name, m)
        self.main_pick.setCurrentIndex(max(0, self.main_pick.findText(Profit.info.name)))
        self.local_pick.clear()
        self.local_pick.addItem("Nothing", None)
        for m in self._measurements("series"):
            self.local_pick.addItem(m.info.name, m)

    def _fill_datasets(self) -> None:
        self.dataset.clear()
        if self.workspace is None:
            return
        for info in self.workspace.datasets.infos("core"):
            self.dataset.addItem(info.name, info.id)
        if self.dataset.count() == 0:
            self.dataset.addItem("No datasets yet: add one on the Data page", None)
        self._show_dataset()

    def _datasets_changed(self, *_):
        self._fill_datasets()

    def _show_dataset(self) -> None:
        ids = (self.graph.settings or {}).get("datasets") or []
        ds = (self.graph.settings or {}).get("dataset") or (ids[0] if ids else None)
        i = self.dataset.findData(ds) if ds else -1
        if i < 0 and ds is None and self.dataset.count():
            self.dataset.setCurrentIndex(-1)
            self.dataset.setPlaceholderText("Pick a dataset")
        else:
            self.dataset.setCurrentIndex(i)

    def _pick_dataset(self, i: int) -> None:
        ds = self.dataset.itemData(i)
        if ds is None or self.workspace is None:
            return
        g = self.graph
        rest = [d for d in (g.settings.get("datasets") or []) if d != ds]
        g.settings["datasets"] = [ds] + rest
        g.settings.pop("dataset", None)
        self.workspace.strategies.put(g.id, g)

    # ---- the strategy -----------------------------------------------------------------
    def set_graph(self, graph: StrategyGraph) -> None:
        old = self.record.strategy_snapshot.get("knob_values") if self.record else None
        self.graph = graph
        self._show_dataset()
        if self.record is not None and old is not None and dict(graph.knob_values) != dict(old):
            self._timer.start()  # a knob was turned: run again once it settles

    def turn(self, key: str, value) -> None:
        """Set a knob (as the Knobs dock does): the change comes back through ``set_graph``."""
        g = self.graph
        if value == g.knobs()[key].default:
            g.knob_values.pop(key, None)
        else:
            g.knob_values[key] = value
        if self.workspace is not None:
            self.workspace.strategies.put(g.id, g)
        else:
            self.set_graph(g)

    # ---- running ----------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.job is not None

    def toggle(self) -> None:
        """The Run button: run, or cancel the run in progress."""
        if self.running:
            self.cancel()
        else:
            self.run()

    def run(self) -> bool:
        self._timer.stop()
        if self.workspace is None:
            return False
        if self.running:  # turned while running: stop it and go again when it ends
            self._pending = True
            self.workspace.runs.cancel(self.job.id)
            return False
        probes = [m.id for m in self.graph.modules if m.kind != "decide"]
        try:
            self.job = self.workspace.runs.prepare(self.graph.id, {"probes": probes})
        except (KeyError, ValueError) as e:
            msg = str(e).strip("'\"")
            if "which dataset" in msg:
                msg = "Pick a dataset for this strategy first."
            self._say(msg, error=True)
            return False
        self._started = time.monotonic()
        self.running_changed.emit(True, "0%")
        self._say("Running…")
        self._poll.start()
        job = self.job
        tasks.run(job.execute, lambda rec: self._done(job, rec), lambda e: self._failed(job, e), self.background)
        return True

    def cancel(self) -> None:
        self._pending = False
        if self.job is not None and self.workspace is not None:
            self.workspace.runs.cancel(self.job.id)

    def _show_progress(self) -> None:
        if self.job is not None:
            self.running_changed.emit(True, f"{int(self.job.fraction * 100)}%")

    def _end(self) -> None:
        self.job = None
        self._poll.stop()
        self.running_changed.emit(False, "")

    def _done(self, job, record: RunRecord) -> None:
        if self.workspace is None:
            return
        self.workspace.runs.commit(record)
        self._end()
        if self._pending:
            self._pending = False
            self.run()
            return
        took = time.monotonic() - self._started
        if record.status == "failed":
            self._say(f"The run failed: {record.error}", error=True)
            return
        if record.status == "cancelled":
            self._say("Cancelled.")
            return
        self.record = record
        self._show_verdicts()
        n = len(record.trades)
        self._say(f"{len(record.states)} steps, {n} trade{'s' * (n != 1)}, {took:.1f} s")
        self.baseline = self.workspace.runs.baseline_for(record)
        if self.baseline is None:
            bjob = self.workspace.runs.prepare_baseline(record)
            tasks.run(bjob.execute, self._baseline_done, lambda e: None, self.background)
        self.redraw()

    def _baseline_done(self, record: RunRecord) -> None:
        if self.workspace is None:
            return
        self.workspace.runs.commit(record)
        if self.record is not None and record.status == "done" and self.workspace.runs.baseline_for(self.record) is record:
            self.baseline = record
            self.redraw()

    def _failed(self, job, e: Exception) -> None:
        self._end()
        self._pending = False
        self._say(f"The run failed: {e}", error=True)

    # ---- backtests ----------------------------------------------------------------------
    def run_backtests(self, test_ids: list[str]) -> None:
        """Run tests on the last finished run (``workspace.backtests``), one after another off the UI thread."""
        if self.bt_queue is None or self.record is None:
            return
        self.bt_queue.background = self.background
        self.bt_queue.start(self.record.id, test_ids)
        self._show_verdicts()

    def _bt_started(self, _run_id: str, test_id: str, pos: int, total: int) -> None:
        name = dict((b, n) for b, n, _t in BACKTESTS).get(test_id, test_id)
        self.bt_status.setText(f"Running {name}" + (f" ({pos} of {total})" if total > 1 else ""))
        self._show_verdicts()

    def _bt_progress(self, _test_id: str, fraction: float) -> None:
        text = self.bt_status.text().split(" · ")[0]
        if text.startswith("Running"):
            self.bt_status.setText(f"{text} · {int(fraction * 100)}%")

    def _bt_idle(self) -> None:
        self.bt_status.setText("A pass means it survived that test, never that it will make money.")
        self._show_verdicts()

    def _show_verdicts(self) -> None:
        """The results of tests run on the last run (from here or from the Backtests page)."""
        for c in self._verdict_cards:
            c.hide()
            c.setParent(None)
            c.deleteLater()
        self._verdict_cards = []
        busy = self.bt_queue is not None and self.bt_queue.running
        for b in self.backtest_buttons.values():
            b.setEnabled(self.record is not None and not busy)
        if self.record is None or self.workspace is None:
            return
        results = self.workspace.backtests.results(self.record.id)
        order = [b for b, _n, _t in BACKTESTS] + sorted(set(results) - {b for b, _n, _t in BACKTESTS})
        n = 0
        for tid in order:
            r = results.get(tid)
            if r is None:
                continue
            card = VerdictCard(r.name, r.outcome, r.verdict.headline, r.verdict.explanation,
                               r.verdict.details.get("figures"))
            card.set_folded(True)
            self.verdicts.addWidget(card, n // 2, n % 2)
            self._verdict_cards.append(card)
            n += 1

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("role", "error" if error else "caption")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # ---- drawing ----------------------------------------------------------------------
    def currency(self) -> str:
        m = MARKETS.get(self.record.market) if self.record else None
        return m.currency if m else "USD"

    def tz(self):
        m = MARKETS.get(self.record.market) if self.record else None
        return m.tz if m else timezone.utc

    def redraw(self) -> None:
        main = self.main_pick.currentData()
        is_profit = isinstance(main, Profit)
        self.display.setVisible(is_profit)
        self.overlay.setVisible(self.local_pick.currentData() is not None)
        self._fill_tiles()
        rec = self.record
        if rec is None or main is None:
            self.chart.set_data([])
            self.chart_note.setText("")
            return
        cur = self.currency()
        disp = PROFIT_DISPLAYS[max(0, self.display.index())]
        params = {"display": disp} if is_profit else {}
        unit = Profit.unit(disp, cur) if is_profit else main.info.unit
        series = [ChartSeries(self.graph.name, main.compute(rec, **params))]
        base = self.baseline
        if base is not None and self.show_default.isChecked():
            series.append(ChartSeries(DEFAULT_NAME, main.compute(base, **params), dashed=True))
        local = self.local_pick.currentData()
        note = ""
        sub_unit = ""
        if local is not None:
            lines = local.compute(rec)
            if len(lines) > MAX_LOCAL:
                big = sorted(lines, key=lambda k: -max((abs(v) for _, v in lines[k]), default=0))[:MAX_LOCAL]
                note = f"{local.info.name}: the {MAX_LOCAL} largest of {len(lines)}."
                lines = {k: lines[k] for k in sorted(big)}
            over = self.overlay.index() == 1
            for i, (name, pts) in enumerate(lines.items()):
                series.append(ChartSeries(name.split(":")[-1] if local.info.id in ("positions", "weights") else name, pts, panel=MAIN if over else SUB, axis=RIGHT if over else "left",
                                          color=i + 1))
            sub_unit = cur if local.info.unit == "currency" else local.info.unit
            if not lines:
                note = f"{local.info.name}: nothing recorded in this run."
        markers = []
        for tr in rec.trades:
            q = f"{tr.quantity:g} {tr.instrument}"
            markers.append(ChartMarker(tr.entry_time, 1, f"{'Bought' if tr.side > 0 else 'Sold short'} {q} at {tr.entry_price:.4g}"))
            if tr.exit_time is not None and "open" not in tr.flags:
                pnl = f", {_money(tr.pnl, cur)}" if tr.pnl is not None else ""
                markers.append(ChartMarker(tr.exit_time, -1, f"Closed {q} at {tr.exit_price:.4g}{pnl}"))
        self.chart.set_timezone(self.tz())
        self.chart.set_data(series, markers, self._fmt(unit, cur), self._fmt(sub_unit, cur), self._fmt(sub_unit, cur))
        self.chart_note.setText(note or "Wheel to zoom in time, drag to move, double-click to see it all. "
                                        "Green dots are entries, red dots exits.")

    @staticmethod
    def _fmt(unit: str, currency: str):
        if unit == "%":
            return lambda v: f"{v:.1f}%"
        if unit == "growth":
            return lambda v: f"{v:.3f}"
        if unit in (currency, "currency"):
            return lambda v: f"{v:,.0f}"
        return lambda v: f"{v:,.4g}"

    def _fill_tiles(self) -> None:
        rec, base = self.record, self.baseline
        reg_get = (lambda mid: self.workspace.registry.get(M.Library.MEASUREMENTS, mid)) if self.workspace else None
        for mid, tile in self.tiles.items():
            if rec is None or reg_get is None:
                tile.set_value("–")
                tile.set_note(" ")
                continue
            m = reg_get(mid)
            v = m.compute(rec)
            b = m.compute(base) if base is not None else None
            if mid == "total_profit":
                tile.set_value(_pct(v))
                tile.set_note(f"vs {_pct(b)} default" if base is not None else "default strategy: running…")
            elif mid == "sharpe":
                tile.set_value(_num(v))
                tile.set_note(f"vs {_num(b)} default" if base is not None else f"{len(rec.states) - 1} steps")
            elif mid == "max_drawdown":
                tile.set_value(_pct(v))
                when = M.MaxDrawdown.when(rec)
                tile.set_note(f"lowest {when.astimezone(self.tz()):%d %b %Y}" if when and v else "no drawdown")
            elif mid == "hit_rate":
                closed = sum(1 for t in rec.trades if "open" not in t.flags)
                tile.set_value(_pct(v, signed=False))
                tile.set_note(f"of {closed} closed trade{'s' * (closed != 1)}")
            else:
                tile.set_value(_pct(v, signed=False))
                tile.set_note("average share of equity held")
