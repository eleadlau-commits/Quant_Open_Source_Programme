"""Backtests page: one list of tests every strategy can use, and their verdicts.

Nothing runs by itself. Pick a strategy and one of its runs, then run one test (double-click
it, or Run this test), the selected ones, or all the tests the strategy uses. Tests run one
after another off the UI thread and each verdict appears as soon as it is ready, grouped
into Failed, Passed and Could not judge. A pass means only that the result survived that
test, never that the strategy will make money.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QScrollArea, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.baseline import DEFAULT_ID
from ...core.strategy import graph_to_dict
from ..backtest_queue import BacktestQueue
from ..design import tokens as T
from ..design.components import (
    flow,
    BusyOverlay, Card, DataTable, Details, Dialog, EmptyState, ParamForm, StatTile, Switch, VerdictCard, button, hbox, label,
)
from ._base import PageView, WhenShown

S = T.SPACE
GROUPS = (("fail", "Failed"), ("pass", "Passed"), ("na", "Could not judge"))
WORD = {"pass": "Passed", "fail": "Failed", "na": "Could not judge"}
FOLD_KEY = "backtests/folded"  # tests whose explanation is folded, remembered between sessions


def run_label(rec) -> str:
    """How a run is named in pickers: when it finished, its profit and its length."""
    when = (rec.finished or rec.created).astimezone().strftime("%H:%M:%S")
    profit = f"{100 * (rec.states[-1].growth - 1):+.1f}%" if rec.states else "–"
    return f"{when} · {profit} · {max(0, len(rec.states) - 1)} steps"


def _same_strategy(snapshot: dict, graph) -> bool:
    """Is the graph still the one that was run (code, links and knobs; layout and test choices aside)?"""
    if not snapshot or not snapshot.get("modules"):
        return True
    now = graph_to_dict(graph)

    def core(d):
        mods = [{k: v for k, v in m.items() if k != "layout"} for m in d.get("modules", [])]
        return mods, d.get("links"), d.get("knob_values"), d.get("preamble")

    return core(now) == core(snapshot)


class BacktestsView(PageView):
    view_id = "backtests"
    title = "Backtests"
    icon = "backtests"
    order = 40
    scroll = True  # a short window scrolls the page rather than cutting it off
    background = True  # run tests on a worker thread (tests turn this off)

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.ws = self.ctx.workspace if self.ctx is not None else None
        self.queue = BacktestQueue(self.ws, self) if self.ws is not None else None
        self.cards: dict[str, VerdictCard] = {}

        # header actions
        self.library_btn = button("Backtest library", icon="library", tip="Every test, what it checks and where it "
                                                                         "comes from")
        self.library_btn.clicked.connect(self.show_library)
        self.run_sel = button("Run selected", tip="Run the tests selected in the list (Ctrl- or Shift-click for more)")
        self.run_sel.clicked.connect(self.run_selected)
        self.run_all = button("Run all", "primary", "play", "Run every test this strategy uses, one after another")
        self.run_all.clicked.connect(self.run_all_or_stop)

        # what is being tested
        self.strategy = QComboBox()
        self.strategy.setMinimumWidth(220)
        self.strategy.setToolTip("The strategy whose run is tested")
        self.strategy.currentIndexChanged.connect(lambda _i: self._fill_runs())
        self.run = QComboBox()
        self.run.setMinimumWidth(240)
        self.run.setToolTip("Which run of it: the latest by default")
        self.run.currentIndexChanged.connect(lambda _i: self.refresh())
        self.status = label("", "caption", wrap=True)
        self.column.addLayout(flow(hbox(label("STRATEGY", "overline"), self.strategy, spacing=S["md"]),
                                   hbox(label("RUN", "overline"), self.run, spacing=S["md"]),
                                   self.status, spacing=S["md"]))

        # a summary of the verdicts
        self.tiles = {}
        tiles = flow(spacing=S["md"], fill=True)
        for key, caption in (("pass", "Passed"), ("fail", "Failed"), ("na", "Could not judge"), ("todo", "Not run")):
            t = StatTile(caption, "–")
            self.tiles[key] = t
            tiles.addWidget(t)
        self.column.addLayout(tiles)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)

        # the list of tests, and the settings of the one selected
        top = QWidget()
        tl = QGridLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setHorizontalSpacing(S["lg"])
        lst = Card("All backtests", "One list for every strategy. Switch on the ones a strategy uses; nothing runs "
                                    "until you ask.")
        self.table = DataTable(["Test", "Uses", "Last result"], stretch=2)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemDoubleClicked.connect(lambda it: self.run_tests([it.data(Qt.UserRole)]))
        self.table.selected.connect(self._show_test)
        self.table.itemChanged.connect(self._ticked)
        self.table.setMinimumHeight(220)
        lst.body.addWidget(self.table, 1)
        tl.addWidget(lst, 0, 0)
        self.detail = Card()
        self.detail.setMinimumWidth(320)
        self._shown: tuple | None = None
        self.form = None
        self.use_switch = None
        self.detail_body = QVBoxLayout()
        self.detail_body.setSpacing(S["md"])
        self.detail.body.addLayout(self.detail_body, 1)
        tl.addWidget(self.detail, 0, 1)
        tl.setColumnStretch(0, 3)
        tl.setColumnStretch(1, 1)
        split.addWidget(top)
        # while tests run, the list and its settings freeze; the verdicts below stay live
        self.busy = BusyOverlay(top, live=True)

        # the verdicts
        res = QWidget()
        rl = QVBoxLayout(res)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(S["sm"])
        self.stale = label("", "error", wrap=True)
        self.stale.hide()
        self.fold_all = button("Fold all", "ghost", tip="Fold every verdict down to its headline, or unfold them all")
        self.fold_all.clicked.connect(self.toggle_folds)
        rl.addLayout(hbox(label("Verdicts", "title"), self.stale, None, self.fold_all))
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self.groups_box = QVBoxLayout(inner)
        self.groups_box.setContentsMargins(0, 0, S["sm"], 0)
        self.groups_box.setSpacing(S["md"])
        self.empty = EmptyState(
            "backtests", "No verdicts yet",
            "Double-click a test to run it on this run, select a few and press Run selected, or press Run all. "
            "A pass means the result survived that test, never that it will make money.")
        self.groups_box.addWidget(self.empty)
        self.group_heads: dict[str, object] = {}
        self.group_grids: dict[str, QGridLayout] = {}
        self.group_open = {k: True for k, _ in GROUPS}
        for key, name in GROUPS:
            head = button(name, "ghost")
            head.clicked.connect(lambda _=False, k=key: self._toggle_group(k))
            box = QWidget()
            grid = QGridLayout(box)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(S["md"])
            grid.setVerticalSpacing(S["md"])
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            self.group_heads[key] = (head, box)
            self.group_grids[key] = grid
            self.groups_box.addLayout(hbox(head, None))
            self.groups_box.addWidget(box)
        self.groups_box.addStretch()
        self.area.setWidget(inner)
        rl.addWidget(self.area, 1)
        split.addWidget(res)
        split.setSizes([330, 520])
        self.column.addWidget(split, 1)

        if self.ws is not None:
            self.queue.background = self.background
            self.queue.started.connect(self._started)
            self.queue.progress.connect(self._progress)
            self.queue.result.connect(lambda _r: self.refresh())
            self.queue.idle.connect(self._idle)
            later = WhenShown(self, self._fill_strategies)  # no redraw while hidden: catches up when shown
            for ev in (self.ws.runs.added, self.ws.runs.removed, self.ws.strategies.added,
                       self.ws.strategies.changed, self.ws.strategies.removed):
                ev.connect(later)
            self.ws.backtests.added.connect(lambda *_: self.refresh())
            self.ws.backtests.changed.connect(lambda *_: self.refresh())
        self._fill_strategies()

    # ---- header ---------------------------------------------------------------------
    def subtitle(self) -> str:
        return "Does the result hold up? A pass means it survived that test, never that it will make money."

    def actions_bar(self):
        return [self.library_btn, self.run_sel, self.run_all]

    # ---- what is picked -------------------------------------------------------------
    def strategy_ids(self) -> list[str]:
        """Strategies that have a finished run, newest run first."""
        if self.ws is None:
            return []
        seen: list[str] = []
        for rec in reversed([self.ws.runs.get(i) for i in self.ws.runs.ids()]):
            if rec.status == "done" and rec.strategy_id != DEFAULT_ID and rec.strategy_id not in seen:
                seen.append(rec.strategy_id)
        return seen

    def _name(self, sid: str) -> str:
        if self.ws is not None and sid in self.ws.strategies:
            return self.ws.strategies.get(sid).name or sid
        return sid or "Unnamed strategy"

    def _fill_strategies(self) -> None:
        keep = self.strategy_id()
        ids = self.strategy_ids()
        self.strategy.blockSignals(True)
        self.strategy.clear()
        for sid in ids:
            self.strategy.addItem(self._name(sid), sid)
        if keep in ids:
            self.strategy.setCurrentIndex(ids.index(keep))
        self.strategy.blockSignals(False)
        self._fill_runs()

    def select_strategy(self, sid: str) -> None:
        i = self.strategy.findData(sid)
        if i >= 0:
            self.strategy.setCurrentIndex(i)

    def strategy_id(self) -> str | None:
        return self.strategy.currentData()

    def graph(self):
        sid = self.strategy_id()
        return self.ws.strategies.get(sid) if self.ws is not None and sid in self.ws.strategies else None

    def _fill_runs(self) -> None:
        keep = self.run.currentData()
        newest = self.run.itemData(0) if self.run.count() else None
        sid = self.strategy_id()
        recs = [r for r in reversed(self.ws.runs.records(sid)) if r.status == "done"] if sid and self.ws else []
        self.run.blockSignals(True)
        self.run.clear()
        for i, r in enumerate(recs):
            self.run.addItem(("Latest · " if i == 0 else "") + run_label(r), r.id)
        ids = [r.id for r in recs]
        # follow the newest run unless an older one was picked on purpose
        if keep in ids and keep != newest:
            self.run.setCurrentIndex(ids.index(keep))
        self.run.blockSignals(False)
        self.refresh()

    def record(self):
        rid = self.run.currentData()
        return self.ws.runs.get(rid) if rid and self.ws is not None and rid in self.ws.runs else None

    def used(self) -> dict[str, dict]:
        g = self.graph()
        if self.ws is None:
            return {}
        if g is None:
            return {t.id: {} for t in self.ws.backtests.tests()}
        return self.ws.backtests.used(g)

    # ---- the list -------------------------------------------------------------------
    def refresh(self) -> None:
        if self.ws is None:
            return
        tests = self.ws.backtests.tests()
        rec = self.record()
        results = self.ws.backtests.results(rec.id) if rec is not None else {}
        used = self.used()
        running = self.queue.current()
        waiting = set(self.queue.pending())
        rows, keys = [], []
        for t in tests:
            if t.id == running:
                last = "Running…"
            elif t.id in waiting:
                last = "Waiting"
            elif t.id in results:
                r = results[t.id]
                last = f"{WORD[r.outcome]}: {r.verdict.headline}"
            else:
                last = ""
            rows.append((t.name, "", last))
            keys.append(t.id)
        self.table.set_rows(rows, keys)
        self.table.blockSignals(True)  # ticking the Uses boxes below isn't the person ticking them
        for r, t in enumerate(tests):
            item = self.table.item(r, 1)
            item.setText("")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if t.id in used else Qt.Unchecked)
            item.setToolTip("Used by this strategy: Run all runs it")
            self.table.item(r, 0).setToolTip(t.doc)
        self.table.blockSignals(False)
        self.table.setColumnWidth(1, 56)
        has_run = rec is not None
        busy = self.queue.running
        self.run_sel.setEnabled(has_run and not busy)
        self.run_all.setEnabled(has_run or busy)
        self.run_all.setText("Stop" if busy else "Run all")
        self.library_btn.setEnabled(True)
        if not has_run:
            self.status.setText("Run a strategy on the Strategies page, then test it here.")
        elif not busy and self.status.text().startswith("Run a strategy"):
            self.status.setText("")
        self._show_test(self.table.selected_key() or (keys[0] if keys else None))
        self._fill_results(results, tests, used)
        self._stale(rec)

    def _ticked(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        g = self.graph()
        if g is None:
            return
        tid, on = item.data(Qt.UserRole), item.checkState() == Qt.Checked
        QTimer.singleShot(0, lambda: self._use(tid, on))  # not while the table is handing out this signal

    def _show_test(self, test_id: str | None, force: bool = False) -> None:
        shown = (test_id, self.strategy_id(), self.record() is not None, self.queue.running if self.queue else False)
        if shown == self._shown and not force:
            if self.use_switch is not None and test_id:
                self.use_switch.blockSignals(True)
                self.use_switch.setChecked(test_id in self.used())
                self.use_switch.blockSignals(False)
            return
        self._shown = shown
        while self.detail_body.count():
            it = self.detail_body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif it.layout() is not None:
                _clear(it.layout())
        if not test_id or self.ws is None:
            return
        info = next((t for t in self.ws.backtests.tests() if t.id == test_id), None)
        if info is None:
            return
        used = self.used()
        self.detail_body.addWidget(label(info.name, "title"))
        self.detail_body.addWidget(label(info.doc, "caption", wrap=True))
        facts = Details()
        plugin = self.ws.backtests.plugin_of(test_id)
        facts.set_rows([("Work", info.cost or "reads the run"), ("Added by", _plugin_name(self.ws, plugin))])
        self.detail_body.addWidget(facts)
        self.form = None
        self.use_switch = None
        if info.params:
            self.form = ParamForm(info.params, used.get(test_id) or {})
            self.form.setEnabled(self.graph() is not None)
            self.form.changed.connect(lambda tid=test_id: self._params_changed(tid))
            self.detail_body.addWidget(self.form)
        sw = Switch(test_id in used, "Use this test for this strategy (Run all runs it)")
        sw.setEnabled(self.graph() is not None)
        sw.toggled.connect(lambda on, tid=test_id: self._use(tid, on))
        self.use_switch = sw
        go = button("Run this test", tip="Run just this test on the picked run")
        go.setEnabled(self.record() is not None and not self.queue.running)
        go.clicked.connect(lambda _=False, tid=test_id: self.run_tests([tid]))
        self.detail_body.addLayout(hbox(sw, label("Used by this strategy", "caption"), None, go))
        self.detail_body.addStretch()

    def _use(self, test_id: str, on: bool) -> None:
        g = self.graph()
        if g is None:
            return
        used = self.used()
        if on == (test_id in used):
            return
        if on:
            form = self.form if self._shown and self._shown[0] == test_id else None
            used.setdefault(test_id, form.values() if form is not None else {})
        else:
            used.pop(test_id, None)
        self.ws.backtests.set_used(g.id, used)

    def _params_changed(self, test_id: str) -> None:
        g = self.graph()
        if g is None or self.form is None:
            return
        used = self.used()
        used[test_id] = self.form.values()
        self.ws.backtests.set_used(g.id, used)

    # ---- the verdicts ---------------------------------------------------------------
    def _folded(self) -> set[str]:
        if self.ctx is None:
            return set()
        v = self.ctx.settings.value(FOLD_KEY, [])
        return {v} if isinstance(v, str) else set(v or [])

    def _remember_fold(self, test_id: str, folded: bool) -> None:
        if self.ctx is None:
            return
        names = self._folded()
        names.add(test_id) if folded else names.discard(test_id)
        self.ctx.settings.setValue(FOLD_KEY, sorted(names))

    def _fill_results(self, results: dict, tests: list, used: dict) -> None:
        for card in self.cards.values():
            card.hide()
            card.setParent(None)
            card.deleteLater()
        self.cards = {}
        folded = self._folded()
        counts = {"pass": 0, "fail": 0, "na": 0}
        for key, _ in GROUPS:
            grid = self.group_grids[key]
            n = 0
            for t in tests:
                r = results.get(t.id)
                if r is None or r.outcome != key:
                    continue
                v = r.verdict
                card = VerdictCard(t.name, key, v.headline, v.explanation, v.details.get("figures"), t.doc)
                card.set_folded(t.id in folded)
                card.fold_changed.connect(lambda f, tid=t.id: self._remember_fold(tid, f))
                again = button("Run again", "ghost", tip="Run this test again on the same run")
                again.clicked.connect(lambda _=False, tid=t.id: self.run_tests([tid]))
                card.add_action(again)
                card.add_action(label(f"{r.seconds:.1f}s", "caption"))
                grid.addWidget(card, n // 2, n % 2)
                self.cards[t.id] = card
                n += 1
            counts[key] = n
            head, box = self.group_heads[key]
            head.setText(f"{'▾' if self.group_open[key] else '▸'}  {dict(GROUPS)[key]} ({n})")
            head.setVisible(n > 0)
            box.setVisible(n > 0 and self.group_open[key])
        self.empty.setVisible(not self.cards)
        self.fold_all.setVisible(bool(self.cards))
        for key in ("pass", "fail", "na"):
            self.tiles[key].set_value(str(counts[key]) if results else "–")
        todo = len([t for t in tests if t.id in used and t.id not in results])
        self.tiles["todo"].set_value(str(todo))

    def _toggle_group(self, key: str) -> None:
        self.group_open[key] = not self.group_open[key]
        self.refresh()

    def toggle_folds(self) -> None:
        fold = any(not c.folded for c in self.cards.values())
        for tid, c in self.cards.items():
            c.set_folded(fold)
            self._remember_fold(tid, fold)

    def _stale(self, rec) -> None:
        g = self.graph()
        stale = rec is not None and g is not None and not _same_strategy(rec.strategy_snapshot, g)
        self.stale.setText("The strategy has changed since this run. Run it again on the Strategies page to test "
                           "the new version." if stale else "")
        self.stale.setVisible(stale)

    # ---- running --------------------------------------------------------------------
    def run_tests(self, test_ids: list[str]) -> None:
        rec = self.record()
        if rec is None or self.queue is None or not test_ids:
            return
        used = self.used()
        self.queue.start(rec.id, test_ids, {t: used[t] for t in test_ids if t in used})
        self.refresh()

    def run_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        self.run_tests([self.table.item(r, 0).data(Qt.UserRole) for r in rows])

    def run_all_or_stop(self) -> None:
        if self.queue is not None and self.queue.running:
            self.queue.stop()
            return
        used = self.used()
        self.run_tests([t.id for t in self.ws.backtests.tests() if t.id in used])

    def _started(self, run_id: str, test_id: str, pos: int, total: int) -> None:
        name = next((t.name for t in self.ws.backtests.tests() if t.id == test_id), test_id)
        self.status.setText(f"Running {name} ({pos} of {total})")
        self.refresh()
        self.busy.start(f"Running {name} ({pos} of {total})\n0%", self.queue.stop)
        self.strategy.setEnabled(False)
        self.run.setEnabled(False)

    def _progress(self, test_id: str, fraction: float) -> None:
        text = self.status.text().split(" · ")[0]
        if text.startswith("Running"):
            self.status.setText(f"{text} · {int(fraction * 100)}%")
            self.busy.set_text(f"{text}\n{int(fraction * 100)}%")

    def _idle(self) -> None:
        self.busy.stop()
        self.strategy.setEnabled(True)
        self.run.setEnabled(True)
        self.status.setText("Done. A pass means the result survived that test.")
        self.refresh()

    # ---- the library ----------------------------------------------------------------
    def show_library(self) -> None:
        if self.ws is None:
            return
        dlg = Dialog("Backtest library", "Every test in the app. Plugins add more (Settings > Plugins). Writing your "
                                         "own tests here comes later.", "Close", self)
        dlg.cancel.hide()
        dlg.ok.clicked.connect(dlg.accept)
        table = DataTable(["Test", "What it checks", "Work", "Added by"], stretch=1)
        tests = self.ws.backtests.tests()
        table.set_rows([(t.name, t.doc, t.cost or "reads the run",
                         _plugin_name(self.ws, self.ws.backtests.plugin_of(t.id))) for t in tests],
                       [t.id for t in tests])
        table.setMinimumSize(820, 360)
        dlg.body.addWidget(table)
        self._library = dlg
        dlg.open()


def _plugin_name(ws, plugin_id: str) -> str:
    if not plugin_id:
        return "Titanium"
    try:
        return ws.plugins.status(plugin_id).name or plugin_id
    except (KeyError, AttributeError):
        return plugin_id


def _clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        if it.widget() is not None:
            it.widget().hide()
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


