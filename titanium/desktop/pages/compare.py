"""Compare page: runs side by side, one tab per measurement from the measurement library.

Tick strategies (their latest run) or any earlier run of them. Every curve is drawn on a
real time axis, so runs with different trading days line up, together with the default
strategy each run is measured against (dashed). Zoom with the wheel, the time-frame
buttons or + and −. Profit is normalised: it is measured from the start of the visible
window, so "profit" always means profit over what you are looking at, and the table
below reads the same window.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHeaderView, QTabBar, QTreeWidget, QTreeWidgetItem, QWidget

from ...core.baseline import DEFAULT_ID, DEFAULT_NAME
from ...core.markets import MARKETS
from ...core.measurements import Scope, measurements
from .. import tasks
from ..design import tokens as T
from ..design.chart import ChartSeries, TimeChart
from ..design.components import Card, DataTable, Dialog, EmptyState, Segmented, button, hbox, label
from ._base import PageView

S = T.SPACE
DAY = 86400.0
FRAMES = (("All", None), ("5Y", 5 * 365), ("1Y", 365), ("6M", 182), ("3M", 91), ("1M", 30))
UTC = timezone.utc


def run_label(rec) -> str:
    when = (rec.finished or rec.created).astimezone().strftime("%H:%M:%S")
    profit = f"{100 * (rec.states[-1].growth - 1):+.1f}%" if rec.states else "–"
    return f"{when} · {profit}"


def _profit(rec) -> str:
    return f"{100 * (rec.states[-1].growth - 1):+.1f}%" if rec.states else "–"


def window_stats(rec, a: float | None, b: float | None) -> dict:
    """Profit, max drawdown, Sharpe, trades and exposure of a run between times a and b (seconds),
    measured from its equity at a (the last state at or before a)."""
    st = rec.states
    if not st:
        return {}
    ts = [s.time.timestamp() for s in st]
    i0 = 0
    if a is not None:
        i0 = max(0, max((i for i, t in enumerate(ts) if t <= a), default=0))
    i1 = len(st) if b is None else max(i0 + 1, sum(1 for t in ts if t <= b))
    seg = st[i0:i1]
    eq = [s.equity for s in seg]
    if not eq or not eq[0]:
        return {}
    peak, dd = -math.inf, 0.0
    for e in eq:
        peak = max(peak, e)
        dd = min(dd, e / peak - 1 if peak > 0 else 0.0)
    rets = [y / x - 1 for x, y in zip(eq, eq[1:]) if x]
    sharpe = None
    if len(rets) > 1:
        m = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        span = (seg[-1].time - seg[0].time).total_seconds()
        if sd > 0 and span > 0:
            sharpe = m / sd * math.sqrt(len(rets) / (span / (365.25 * DAY)))
    lo, hi = (a if a is not None else -math.inf), (b if b is not None else math.inf)
    trades = sum(1 for t in rec.trades if lo <= t.entry_time.timestamp() <= hi)
    gross = []
    for s in seg:
        if s.equity:
            gross.append(sum(abs(p.exposure or p.market_value) for p in s.positions.values()) / s.equity)
    return {"profit": eq[-1] / eq[0] - 1, "drawdown": dd, "sharpe": sharpe, "trades": trades,
            "exposure": sum(gross) / len(gross) if gross else None}


def normalised(measurement, rec, a: float | None) -> list[tuple[datetime, float]]:
    """A run's curve for the chart. Profit (in %) and drawdown are measured from the window start ``a``;
    other curves are drawn as they are."""
    mid = measurement.info.id
    if mid not in ("profit", "drawdown"):
        return measurement.compute(rec)
    st = rec.states
    if not st:
        return []
    i0 = 0
    if a is not None:
        i0 = max((i for i, s in enumerate(st) if s.time.timestamp() <= a), default=0)
    base = st[i0].equity or 1.0
    if mid == "profit":
        return [(s.time, (s.equity / base - 1) * 100) for s in st]
    out, peak = [], -math.inf
    for i, s in enumerate(st):
        if i >= i0:
            peak = max(peak, s.equity)
        out.append((s.time, (s.equity / peak - 1) * 100 if i >= i0 and peak > 0 else 0.0))
    return out


class CompareView(PageView):
    view_id = "compare"
    title = "Compare"
    icon = "compare"
    order = 30
    background = True  # run missing default strategies on a worker thread (tests turn this off)

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.ws = self.ctx.workspace if self.ctx is not None else None
        self.hidden: set[str] = set()  # strategies unticked
        self.extra: set[str] = set()  # earlier runs ticked
        self._busy_baselines: set[str] = set()
        self._rebasing = False

        self.library_btn = button("Measurement library", icon="library",
                                  tip="Every measurement, what it shows and where it comes from")
        self.library_btn.clicked.connect(self.show_library)

        grid = QGridLayout()
        grid.setHorizontalSpacing(S["lg"])
        grid.setVerticalSpacing(S["lg"])

        # what is compared
        pick = Card("Runs", "Tick a strategy for its latest run, or open it for earlier ones.")
        pick.setMinimumWidth(260)
        pick.setMaximumWidth(340)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(S["lg"])
        self.tree.itemChanged.connect(self._ticked)
        pick.body.addWidget(self.tree, 1)
        self.show_default = QCheckBox(DEFAULT_NAME)
        self.show_default.setChecked(True)
        self.show_default.setToolTip("The yardstick each run is measured against: equal weight in everything in the "
                                     "dataset, on the same costs. Drawn dashed.")
        self.show_default.toggled.connect(lambda _v: self.redraw())
        pick.body.addWidget(self.show_default)
        grid.addWidget(pick, 0, 0, 2, 1)

        # the chart
        chart_card = Card()
        chart_card.body.setSpacing(S["sm"])
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.currentChanged.connect(lambda _i: self.redraw())
        self.frame = Segmented([f for f, _ in FRAMES])
        self.frame.setToolTip("How far back from the end to look")
        self.frame.changed.connect(self._frame)
        zin = button("+", "ghost", tip="Zoom in on time")
        zout = button("−", "ghost", tip="Zoom out")
        zin.clicked.connect(lambda: self.chart.zoom(0.5))
        zout.clicked.connect(lambda: self.chart.zoom(2.0))
        chart_card.body.addLayout(hbox(self.tabs, None, self.frame, zin, zout, spacing=S["sm"]))
        self.chart = TimeChart()
        self.chart.empty_text = "Run a strategy and tick it to compare it here"
        self.chart.setMinimumHeight(320)
        self.chart.view_changed.connect(self._view_changed)
        chart_card.body.addWidget(self.chart, 1)
        self.window_note = label("", "caption")
        chart_card.body.addWidget(self.window_note)
        grid.addWidget(chart_card, 0, 1)

        # the numbers over the window
        table_card = Card()
        self.table = DataTable(["Strategy", "Run", "Profit", "Max drawdown", "Sharpe", "Trades", "Exposure"],
                               stretch=0)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(230)
        table_card.body.addWidget(self.table)
        grid.addWidget(table_card, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)

        self.empty = EmptyState("compare", "Nothing to compare yet",
                                "Run a strategy on the Strategies page and it appears here. Tick strategies or runs "
                                "to compare them with each other and with the default strategy, and zoom in time.")
        self.body = QWidget()
        self.body.setLayout(grid)
        self.column.addWidget(self.empty, 1)
        self.column.addWidget(self.body, 1)

        self._fill_tabs()
        if self.ws is not None:
            for ev in (self.ws.runs.added, self.ws.runs.removed):
                ev.connect(lambda *_: self.refresh())
            self.ws.strategies.changed.connect(lambda *_: self.refresh())
        self.refresh()

    # ---- header ---------------------------------------------------------------------
    def subtitle(self) -> str:
        return "Strategies side by side, one tab per measurement. Profit is measured from the start of what you see."

    def actions_bar(self):
        return [self.library_btn]

    # ---- the measurements -------------------------------------------------------------
    def curves(self) -> list:
        if self.ws is None:
            return []
        return measurements(self.ws.registry, kind="curve", scope=Scope.GLOBAL)

    def _fill_tabs(self) -> None:
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self._curves = self.curves()
        first = [m for m in self._curves if m.info.id == "profit"]
        self._curves = first + [m for m in self._curves if m.info.id != "profit"]
        for i, m in enumerate(self._curves):
            self.tabs.addTab(m.info.name)
            self.tabs.setTabToolTip(i, m.info.doc)
        self.tabs.blockSignals(False)

    def measurement(self):
        i = self.tabs.currentIndex()
        return self._curves[i] if 0 <= i < len(self._curves) else None

    def show_measurement(self, mid: str) -> None:
        for i, m in enumerate(self._curves):
            if m.info.id == mid:
                self.tabs.setCurrentIndex(i)

    # ---- the runs ---------------------------------------------------------------------
    def strategy_runs(self) -> list[tuple[str, list]]:
        """[(strategy id, its finished runs newest first)], newest strategy first; the default strategy aside."""
        if self.ws is None:
            return []
        out: dict[str, list] = {}
        for rec in reversed([self.ws.runs.get(i) for i in self.ws.runs.ids()]):
            if rec.status == "done" and rec.strategy_id != DEFAULT_ID:
                out.setdefault(rec.strategy_id, []).append(rec)
        return list(out.items())

    def _name(self, sid: str) -> str:
        if self.ws is not None and sid in self.ws.strategies:
            return self.ws.strategies.get(sid).name or sid
        return sid or "Unnamed strategy"

    def refresh(self) -> None:
        groups = self.strategy_runs()
        self.empty.setVisible(not groups)
        self.body.setVisible(bool(groups))
        open_ = {self.tree.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tree.topLevelItemCount())
                 if self.tree.topLevelItem(i).isExpanded()}
        self.tree.blockSignals(True)
        self.tree.clear()
        for sid, recs in groups:
            top = QTreeWidgetItem([self._name(sid), _profit(recs[0])])
            top.setData(0, Qt.UserRole, sid)
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
            top.setCheckState(0, Qt.Unchecked if sid in self.hidden else Qt.Checked)
            top.setToolTip(0, f"Its latest run ({run_label(recs[0])}). Open it to tick earlier runs too.")
            for rec in recs[1:]:
                child = QTreeWidgetItem([(rec.finished or rec.created).astimezone().strftime("Run at %H:%M:%S"),
                                         _profit(rec)])
                child.setData(0, Qt.UserRole, rec.id)
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if rec.id in self.extra else Qt.Unchecked)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(sid in open_)
        self.tree.blockSignals(False)
        self.redraw()

    def _ticked(self, item: QTreeWidgetItem, _col: int) -> None:
        key = item.data(0, Qt.UserRole)
        on = item.checkState(0) == Qt.Checked
        if item.parent() is None:
            self.hidden.discard(key) if on else self.hidden.add(key)
        else:
            self.extra.add(key) if on else self.extra.discard(key)
        self.redraw()

    def shown(self) -> list[tuple[str, object]]:
        """[(label, run record)] ticked, in list order."""
        out = []
        for sid, recs in self.strategy_runs():
            name = self._name(sid)
            if sid not in self.hidden:
                out.append((name, recs[0]))
            for rec in recs[1:]:
                if rec.id in self.extra:
                    out.append((f"{name} ({run_label(rec)})", rec))
        return out

    def baselines(self, shown) -> list[tuple[str, object]]:
        """One default-strategy run per set of terms among the shown runs. Missing ones are run in the background."""
        if self.ws is None or not self.show_default.isChecked():
            return []
        out, seen = [], set()
        for _name, rec in shown:
            base = self.ws.runs.baseline_for(rec)
            if base is None:
                self._run_baseline(rec)
                continue
            if base.id not in seen:
                seen.add(base.id)
                out.append((DEFAULT_NAME if not out else f"{DEFAULT_NAME} ({base.dataset_id})", base))
        return out

    def _run_baseline(self, rec) -> None:
        if rec.id in self._busy_baselines:
            return
        self._busy_baselines.add(rec.id)
        try:
            job = self.ws.runs.prepare_baseline(rec)
        except (KeyError, ValueError):
            return

        def done(r, rid=rec.id):
            self._busy_baselines.discard(rid)
            if r.status == "done":
                self.ws.runs.commit(r)

        tasks.run(job.execute, done, lambda e, rid=rec.id: self._busy_baselines.discard(rid), self.background)

    # ---- drawing --------------------------------------------------------------------
    def _tz(self, shown):
        for _n, rec in shown:
            m = MARKETS.get(rec.market)
            if m is not None:
                return m.tz
        return UTC

    def redraw(self) -> None:
        m = self.measurement()
        shown = self.shown()
        bases = self.baselines(shown) if shown else []
        self._shown, self._bases = shown, bases
        if m is None or not shown:
            self.chart.set_data([])
            self.table.set_rows([], [])
            self.window_note.setText("")
            return
        self.chart.set_timezone(self._tz(shown))
        win = self.chart.view
        a = win[0] if win else None
        series = [ChartSeries(name, normalised(m, rec, a), color=i) for i, (name, rec) in enumerate(shown)]
        series += [ChartSeries(name, normalised(m, rec, a), dashed=True) for name, rec in bases]
        unit = "%" if m.info.id in ("profit", "drawdown") else m.info.unit
        fmt = (lambda v: f"{v:+.1f}%") if m.info.id == "profit" else (lambda v: f"{v:.1f}%") if unit == "%" else None
        self._rebasing = True
        self.chart.set_data(series, fmt=fmt, keep_view=True)
        self._rebasing = False
        self._fill_table()

    def _frame(self, i: int) -> None:
        days = FRAMES[i][1]
        full = self.chart.full_range()
        if not full or days is None:
            self.chart.set_view(None)
        else:
            self.chart.set_view((full[1] - days * DAY, full[1]))

    def _view_changed(self) -> None:
        if self._rebasing:
            return
        m = self.measurement()
        if m is not None and m.info.id in ("profit", "drawdown") and getattr(self, "_shown", None):
            self.redraw()  # re-measure from the new window start
        else:
            self._fill_table()

    def _fill_table(self) -> None:
        win = self.chart.window()
        a, b = (win if self.chart.view else (None, None)) if win else (None, None)
        tz = self.chart.tz
        if win:
            fmt = lambda x: datetime.fromtimestamp(x, tz).strftime("%Y-%m-%d")  # noqa: E731
            self.window_note.setText(f"{fmt(win[0])} to {fmt(win[1])} · profit and drawdown measured from the start "
                                     "of this window · wheel to zoom, drag to move, double-click for all")
        rows, keys = [], []
        for name, rec in self._shown + self._bases:
            st = window_stats(rec, a, b)
            pct = lambda v, signed=True: "–" if v is None else (f"{100 * v:+.2f}%" if signed else f"{100 * v:.1f}%")  # noqa: E731
            rows.append((name, run_label(rec), pct(st.get("profit")), pct(st.get("drawdown"), False),
                         "–" if st.get("sharpe") is None else f"{st['sharpe']:.2f}",
                         "–" if rec.strategy_id == DEFAULT_ID else str(st.get("trades", 0)),
                         pct(st.get("exposure"), False)))
            keys.append(rec.id)
        self.table.set_rows(rows, keys)

    # ---- the library ----------------------------------------------------------------
    def show_library(self) -> None:
        if self.ws is None:
            return
        from ...core.plugins import Library

        dlg = Dialog("Measurement library", "Every measurement in the app. Curves get a tab here; numbers and series "
                                            "show in the Run view. Plugins add more; writing your own here comes later.",
                     "Close", self)
        dlg.cancel.hide()
        dlg.ok.clicked.connect(dlg.accept)
        table = DataTable(["Measurement", "Shows", "Kind", "Unit", "Added by"], stretch=1)
        entries = self.ws.registry.entries(Library.MEASUREMENTS)
        kinds = {"number": "a number", "curve": "a curve", "series": "a line per item"}
        table.set_rows([(e.obj.info.name, e.obj.info.doc, kinds.get(getattr(e.obj.info, "kind", ""), ""),
                         e.obj.info.unit or "–", e.plugin or "Titanium") for e in entries], [e.name for e in entries])
        table.setMinimumSize(820, 380)
        dlg.body.addWidget(table)
        self._library = dlg
        dlg.open()
