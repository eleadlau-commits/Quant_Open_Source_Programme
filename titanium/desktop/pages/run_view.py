"""The Run view of a strategy tab: run it, read its measurements, turn its knobs.

The view is a thin reader of run records. A run goes through ``Workspace.runs``
(prepare on the UI thread, execute on a worker, commit back on the UI thread); the
default strategy is run once on the same terms and kept as the yardstick. Turning a
knob in the Knobs dock (or through ``turn``) re-runs once it is let go and redraws.

While a run (and the default strategy's, when it needs one) is computing, the window is
clearly busy: ``BusyOverlay`` blocks every click and key press and, after a short grace,
shows a spinner and progress. When the window takes input again, the work is done.
"""
from __future__ import annotations

import time
from datetime import timezone

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QScrollArea, QSlider, QSplitter, QVBoxLayout,
    QWidget,
)

from ...core import measurements as M
from ...core.baseline import DEFAULT_NAME
from ...core.markets import MARKETS
from ...core.measurements import Profit, Scope
from ...core.run import RunRecord
from ...core.strategy import StrategyGraph
from .. import tasks
from .run_settings import RunSettings, resolve, summary
from .strategy_panels import KnobsPanel, TradeLogPanel
from ..backtest_queue import BacktestQueue
from ..design import tokens as T
from ..design.chart import MAIN, RIGHT, SUB, ChartMarker, ChartSeries, TimeChart
from ..design.components import (
    flow, scrolling,
    BusyOverlay, Card, Segmented, StatTile, VerdictCard, button, hbox, label,
)

S = T.SPACE
PROFIT_DISPLAYS = ("growth", "%", "currency")
MAX_LOCAL = 8  # local series drawn at once (the largest ones)
RERUN_DELAY_MS = 120  # after the last knob change, once no slider is held
# the chart and the block below it (backtests, trade log) share the view through a splitter.
# The chart keeps the height it was last dragged to (one for every tab) and the block below
# takes the rest; the view scrolls only when the window is shorter than that and the block's
# least height.
CHART_KEY = "run_view/chart_height"
CHART_MIN = 100  # the plot itself, at its smallest; the card adds its pickers and note
CHART_EASY = 220  # the plot before any drag, at least (more when the window has room)
CHART_SHARE = 0.6  # of the space for the chart and the block below, before any drag
# Phase 2F wires these up
# the quick tests in the backtest block: ids in Library.BACKTESTS (the honest-tests plugin)
BACKTESTS = (("out_of_sample", "Out-of-sample", "Choose the knobs on the early part, score the later part it never saw"),
             ("cost_stress", "Cost stress", "Run again with every cost doubled"),
             ("random_baseline", "Random baseline", "Same timing, weights and holding periods, names picked at random"),
             ("walk_forward", "Walk-forward", "Re-choose the knobs before each stretch and score only what follows"))


class _Fitted(QWidget):
    """The scrolling content of the view. Its height follows its width (the stat tiles and
    pickers wrap), so the scroll area sizes it by that instead of by the worst case at its
    narrowest, which made the view much taller than the window and stretched the chart."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.least: dict = {}  # widget -> callable giving its least height, where the layout's is wrong

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt name)
        return QSize(super().minimumSizeHint().width(), 0)

    def _item_least(self, it, width: int) -> int:
        w = it.widget()
        if w is not None and w in self.least:
            return self.least[w]()
        return it.heightForWidth(width) if it.hasHeightForWidth() else it.minimumSize().height()

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt name)
        """The least height at ``width``, so the view scrolls only when it truly cannot fit;
        the splitter's panes then share whatever the window gives."""
        lay = self.layout()
        items = [lay.itemAt(i) for i in range(lay.count())]
        items = [it for it in items if not it.isEmpty()]
        m = lay.contentsMargins()
        inner = width - m.left() - m.right()
        need = sum(self._item_least(it, inner) for it in items)
        return need + lay.spacing() * max(0, len(items) - 1) + m.top() + m.bottom()


class _Pane(QWidget):
    """One side of the chart splitter. Its minimum height is worked out at its current width
    (``least``), since the cards in it wrap; asking the layout would give the height at its
    narrowest and stop the splitter well short."""

    def __init__(self, least, parent=None):
        super().__init__(parent)
        self.least = least

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt name)
        return QSize(super().minimumSizeHint().width(), self.least())

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()  # wrapping changed, so may the minimum


def _least(widget: QWidget) -> int:
    """The least height ``widget`` needs at its current width (0 while it is hidden)."""
    if widget.isHidden():
        return 0
    if widget.hasHeightForWidth() and widget.width() > 0:
        return max(widget.heightForWidth(widget.width()), widget.minimumHeight())
    return widget.minimumSizeHint().height()


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

    def __init__(self, graph: StrategyGraph, workspace=None, open_page=None, parent=None, app_ctx=None):
        super().__init__(parent)
        self.app_ctx = app_ctx  # to hide the in-tab knobs and trade log while they are popped out
        self.graph = graph
        self.workspace = workspace
        self.open_page = open_page  # an Event the shell listens to (to show the trade log dock)
        self.background = True  # tests run inline
        self.record: RunRecord | None = None
        self.baseline: RunRecord | None = None
        self.job = None
        self._bjob = None  # the default strategy's run, while it is part of the busy period
        self._pending = False  # a rerun asked for while one is running
        self._started = 0.0

        # everything scrolls up and down, so a short window never cuts the view off
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = _Fitted()
        self._area, self._inner = area, inner
        area.setWidget(inner)
        outer.addWidget(area)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S["lg"])

        # dataset and status
        self.dataset = QComboBox()
        self.dataset.setMinimumWidth(200)
        self.dataset.setToolTip("The dataset this strategy trades")
        self.dataset.activated.connect(self._pick_dataset)
        self.status = label("Not run yet. Press Run or Ctrl+Enter.", "caption", wrap=True)
        self.settings_btn = button("Run settings", "ghost", "settings",
                                   "Market, trading hours, decision time, capital and costs for this strategy")
        self.settings_btn.setCheckable(True)
        self.market_line = label("", "caption", wrap=True)
        self.market_line.setToolTip("The market this strategy trades, the hours it trades and when it decides")
        lay.addLayout(flow(label("DATASET", "overline"), self.dataset, None, self.settings_btn, spacing=S["md"]))
        lines = QVBoxLayout()
        lines.setSpacing(S["xxs"])
        lines.addWidget(self.market_line)
        lines.addWidget(self.status)
        lay.addLayout(lines)
        self.settings_card = RunSettings()
        self.settings_card.hide()
        self.settings_btn.toggled.connect(self.settings_card.setVisible)
        self.settings_card.changed.connect(self._settings_changed)
        lay.addWidget(self.settings_card)

        # stat tiles
        self.tiles: dict[str, StatTile] = {}
        tiles = flow(spacing=S["md"], fill=True)
        for mid, caption in (("total_profit", "Profit"), ("sharpe", "Sharpe"), ("max_drawdown", "Max drawdown"),
                             ("hit_rate", "Hit rate"), ("avg_exposure", "Exposure")):
            t = StatTile(caption, "–", " ")
            self.tiles[mid] = t
            tiles.addWidget(t)
        lay.addLayout(tiles)

        # chart and its pickers, with the knobs beside it; drag the bar under them to resize the chart
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(S["lg"])
        upper = _Pane(lambda: _least(chart_card))  # the knobs scroll, so the chart card decides
        top = QHBoxLayout(upper)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(S["lg"])
        lower = _Pane(lambda: _least(self.backtest_card) + S["lg"] + _least(self.log_card))
        bottom = QVBoxLayout(lower)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(S["lg"])
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
        chart_card.body.addLayout(flow(self.main_pick, self.display, self.show_default, None,
                                       hbox(label("Add", "caption"), self.local_pick, self.overlay), spacing=S["sm"]))
        self.chart = TimeChart()
        self.chart.empty_text = "Run the strategy (Ctrl+Enter) to see it here"
        self.chart.setMinimumHeight(CHART_MIN)
        chart_card.body.addWidget(self.chart, 1)
        self.chart_note = label("", "caption")
        chart_card.body.addWidget(self.chart_note)
        top.addWidget(chart_card, 1)

        # backtests: quick tests on the last run; every test is on the Backtests page
        self.backtest_card = Card()
        self.backtest_buttons = {}
        self.bt_status = label("Does the result hold up? Run the strategy, then test it.", "caption")
        self.bt_status.setWordWrap(True)
        self.backtest_card.body.addLayout(hbox(label("BACKTESTS", "overline"), self.bt_status))
        row = flow()
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
        bottom.addWidget(self.backtest_card)

        # this strategy's knobs and trade log; each can pop out as a dock that follows the tab in front
        self.knobs_card = Card("Knobs", "Turn one and the strategy runs again.")
        self.knobs = KnobsPanel(workspace, graph.id)
        knobs_area = scrolling(self.knobs)  # a short chart scrolls the knobs instead of holding it tall
        knobs_area.setMinimumWidth(self.knobs.minimumSizeHint().width() + S["md"])  # room for the scroll bar
        self.knobs_card.body.addWidget(knobs_area, 1)
        self.knobs_card.setMinimumWidth(260)
        self.knobs_card.setMaximumWidth(340)
        self.knobs_card.add_action(self._pop_button("knobs"))
        top.addWidget(self.knobs_card)
        self.log_card = Card("Trade log")
        self.trade_log = TradeLogPanel(workspace, graph.id)
        self.log_card.body.addWidget(self.trade_log, 1)
        self.log_card.add_action(self._pop_button("trade_log"))
        self.trade_log.table.setMinimumHeight(1)  # a taller chart can fold the trade log to its title
        bottom.addWidget(self.log_card, 1)
        self.split.addWidget(upper)
        self.split.addWidget(lower)
        self.split.setStretchFactor(0, 0)  # the chart keeps its height; a taller window goes below
        self.split.setStretchFactor(1, 1)
        inner.least = {self.split: self._split_least}
        self.split.handle(1).setToolTip("Drag to resize the chart")
        self.split.splitterMoved.connect(self._split_moved)
        self._chart_h: int | None = self._saved_chart_height()  # the chart pane's height; None: not set
        self.split.installEventFilter(self)
        lay.addWidget(self.split, 1)

        self._timer = QTimer(self, singleShot=True, interval=RERUN_DELAY_MS)
        self._timer.timeout.connect(self._rerun)
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
            workspace.run_defaults_changed.connect(self._defaults_changed)
            workspace.market_defaults_changed.connect(self._defaults_changed)
        if app_ctx is not None:
            for vid in ("knobs", "trade_log"):
                self._panel_open(vid, bool(app_ctx.panels.get(vid)))
            app_ctx.panel_open.connect(self._panel_open)
        self._fill_datasets()
        self.set_graph(graph)
        self.redraw()

    def _pop_button(self, view_id: str):
        b = button("Pop out", "ghost", "dock", "Show it in its own panel, following the strategy tab in front")
        b.clicked.connect(lambda: self._show(view_id))
        return b

    def _panel_open(self, view_id: str, is_open: bool) -> None:
        card = {"knobs": self.knobs_card, "trade_log": self.log_card}.get(view_id)
        if card is not None:
            card.setVisible(not is_open)
        if view_id == "trade_log":
            self._refit()
            QTimer.singleShot(0, self._place_split)

    # ---- chart height -----------------------------------------------------------------
    def _saved_chart_height(self) -> int | None:
        try:
            return int(self.app_ctx.settings.value(CHART_KEY)) if self.app_ctx is not None else None
        except (TypeError, ValueError):
            return None

    def _chart_target(self, room: int | None = None) -> int:
        """The height of the chart pane: as last dragged, else a comfortable share of ``room``
        (the space the chart and the block below have), never under its least."""
        least = self.split.widget(0).minimumSizeHint().height()
        if self._chart_h is not None:
            return max(least, self._chart_h)
        easy = least + CHART_EASY - CHART_MIN
        return max(easy, int((room or 0) * CHART_SHARE))

    def _split_least(self) -> int:
        """How tall the splitter must be: the chart at its height, the handle, and the least
        the block below needs. The scroll area gives it more when the window has it."""
        room = self._area.viewport().height() - max(0, self.split.y())
        lower = self.split.widget(1).minimumSizeHint().height()
        return self._chart_target(room) + self.split.handleWidth() + lower

    def _place_split(self) -> None:
        """Put the chart at its height and give the block below the rest; with the trade log
        popped out the block needs little, so the chart takes the spare room."""
        total = sum(self.split.sizes())
        if total <= 0:
            return
        lower_least = self.split.widget(1).minimumSizeHint().height()
        chart = self._chart_target(total + self.split.handleWidth())
        if self.log_card.isHidden():
            chart = max(chart, total - lower_least)
        chart = min(chart, total - lower_least)
        if self.split.sizes()[0] != chart:
            self.split.setSizes([chart, total - chart])

    def _split_moved(self, _pos: int, _index: int) -> None:
        """Dragged: remember the chart's height and let the view fit it again."""
        self._chart_h = self.split.sizes()[0]
        if self.app_ctx is not None:
            self.app_ctx.settings.setValue(CHART_KEY, self._chart_h)
        self._refit()

    def _refit(self) -> None:
        """The least height changed: let the scroll area size the content again."""
        self._inner.updateGeometry()
        QApplication.postEvent(self._area, QEvent(QEvent.LayoutRequest))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt name)
        if obj is self.split and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place_split)  # after the splitter has shared out its new height
        return super().eventFilter(obj, event)

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
            self.workspace.run_defaults_changed.disconnect(self._defaults_changed)
            self.workspace.market_defaults_changed.disconnect(self._defaults_changed)
        self.knobs.detach()
        self.trade_log.detach()
        if self.app_ctx is not None:
            self.app_ctx.panel_open.disconnect(self._panel_open)

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
        self._show_settings()
        if self.record is not None and old is not None and dict(graph.knob_values) != dict(old):
            self._timer.start()  # a knob was turned: run again once it settles

    def _show_settings(self) -> None:
        """The market line and the Run settings panel, for the settings the next run will use."""
        self.settings_card.set_strategy(self.workspace, self.graph)
        market, _layers, cfg = resolve(self.workspace, self.graph)
        self.market_line.setText(f"Next run: {summary(market, cfg)}")

    def _defaults_changed(self, *_):
        self._show_settings()

    def _settings_changed(self) -> None:
        if self.workspace is None:
            self._show_settings()
        if self.record is not None and not self.running:
            self._say("Settings changed. Run again (Ctrl+Enter) to see the result.")

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

    def _rerun(self) -> None:
        """A knob settled: run again, but not while a slider is still held (the busy state
        would take the mouse from it mid-drag)."""
        if any(sl.isSliderDown() for sl in self.window().findChildren(QSlider)):
            self._timer.start()
            return
        self.run()

    def _overlay(self) -> BusyOverlay | None:
        return BusyOverlay.of(self) if self.workspace is not None else None

    def _busy(self, text: str) -> None:
        ov = self._overlay()
        if ov is not None:
            ov.start(f"Running {self.graph.name}\n{text}", self.cancel)

    def _idle(self) -> None:
        ov = self._overlay()
        if ov is not None:
            ov.stop()

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
        self._busy("0%")
        self.running_changed.emit(True, "0%")
        self._say("Running…")
        self._poll.start()
        job = self.job
        tasks.run(job.execute, lambda rec: self._done(job, rec), lambda e: self._failed(job, e), self.background)
        return True

    def cancel(self) -> None:
        self._pending = False
        if self.workspace is None:
            return
        if self.job is not None:
            self.workspace.runs.cancel(self.job.id)
        if self._bjob is not None:
            self.workspace.runs.cancel(self._bjob.id)

    def _show_progress(self) -> None:
        if self.job is not None:
            pct = f"{int(self.job.fraction * 100)}%"
            self.running_changed.emit(True, pct)
            ov = self._overlay()
            if ov is not None and ov.active:
                ov.set_text(f"Running {self.graph.name}\n{pct}")

    def _end(self, idle: bool = True) -> None:
        self.job = None
        self._poll.stop()
        self.running_changed.emit(False, "")
        if idle:
            self._idle()

    def _done(self, job, record: RunRecord) -> None:
        if self.workspace is None:
            return
        self.workspace.runs.commit(record)
        self._end(idle=False)  # stays busy until the result is drawn
        try:
            self._show_run(record)
        finally:
            if self.job is None and self._bjob is None:
                self._idle()

    def _show_run(self, record: RunRecord) -> None:
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
        market = (self.workspace.markets().get(record.market) if self.workspace is not None else None) \
            or MARKETS.get(record.market)
        where = f"{summary(market, record.settings)} · " if market is not None else ""
        self._say(f"Last run: {where}{len(record.states)} steps, {n} trade{'s' * (n != 1)}, {took:.1f} s")
        self.baseline = self.workspace.runs.baseline_for(record)
        if self.baseline is None:
            # the yardstick is part of the same busy period: the window comes back when it is drawn
            self._busy("Default strategy")
            bjob = self.workspace.runs.prepare_baseline(record)
            self._bjob = bjob
            tasks.run(bjob.execute, self._baseline_done, self._baseline_failed, self.background)
            return
        self.redraw()

    def _baseline_done(self, record: RunRecord) -> None:
        self._bjob = None
        if self.workspace is None:
            return
        self.workspace.runs.commit(record)
        if self.record is not None and record.status == "done" and self.workspace.runs.baseline_for(self.record) is record:
            self.baseline = record
        self.redraw()
        if self.job is None:
            self._idle()

    def _baseline_failed(self, _e: Exception) -> None:
        self._bjob = None
        self.redraw()
        if self.job is None:
            self._idle()

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
