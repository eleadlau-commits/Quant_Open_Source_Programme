"""Backtests page: one global list of tests that every strategy can use.

Nothing runs by itself. Double-click a test to run it, select a few and press
Run selected, or press Run all to run every test this strategy uses. Tests run
one at a time and each result appears as soon as it is ready, grouped into
Failed, Passed and Could not judge, each of which folds away.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QScrollArea, QSplitter, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..patchbay import ConfigError, expand_evaluators
from ..plugins import suites as plugin_suites
from ..registry import catalog
from .verdicts import VerdictCard

PASS, FAIL, NA = QColor("#1f8a4c"), QColor("#c0392b"), QColor("#8a8a84")
GROUPS = (("fail", "Failed", FAIL), ("pass", "Passed", PASS), ("na", "Could not judge", NA))


def _group(v: dict) -> str:
    return "pass" if v["passed"] is True else "fail" if v["passed"] is False else "na"


class ResultGroups(QScrollArea):
    """Test results in three foldable groups. Each block also folds on its own."""

    hovered = Signal(str)

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("Titanium", "Titanium")
        self.setWidgetResizable(True)
        inner = QWidget()
        self.outer = QVBoxLayout(inner)
        self.sections: dict[str, tuple[QToolButton, QWidget, QVBoxLayout]] = {}
        self.cards: dict[str, list[VerdictCard]] = {g: [] for g, _, _ in GROUPS}
        self.hint = QLabel("<span style='color:gray'>No results yet. Double-click a test, or select some and "
                           "press Run selected, or press Run all.</span>")
        self.outer.addWidget(self.hint)
        for key, label, color in GROUPS:
            head = QToolButton()
            head.setToolButtonStyle(Qt.ToolButtonTextOnly)
            head.setAutoRaise(True)
            head.setStyleSheet(f"QToolButton {{ font-weight: 700; color: {color.name()}; text-align: left; }}")
            body = QWidget()
            bl = QVBoxLayout(body)
            bl.setContentsMargins(14, 0, 0, 6)
            head.clicked.connect(lambda _=False, k=key: self.set_open(k, self.sections[k][1].isHidden()))
            self.sections[key] = (head, body, bl)
            self.outer.addWidget(head)
            self.outer.addWidget(body)
        self.outer.addStretch()
        self.setWidget(inner)
        self.set_results([])

    # the interface VerdictCard expects from its board
    def is_folded(self, name: str) -> bool:
        return name in self._list("backtests/folded")

    def remember_fold(self, name: str, folded: bool):
        names = set(self._list("backtests/folded"))
        names.add(name) if folded else names.discard(name)
        self.settings.setValue("backtests/folded", sorted(names))

    def move(self, src: str, target: str, after: bool = False):
        for key, cards in self.cards.items():
            names = [c.name for c in cards]
            if src in names and target in names and src != target:
                card = cards.pop(names.index(src))
                cards.insert([c.name for c in cards].index(target) + (1 if after else 0), card)
                self._relayout(key)

    def _list(self, key) -> list[str]:
        v = self.settings.value(key, [])
        return [v] if isinstance(v, str) else list(v or [])

    # ---- content
    def set_open(self, key: str, open_: bool):
        head, body, _ = self.sections[key]
        body.setVisible(open_)
        self.settings.setValue(f"backtests/closed/{key}", not open_)
        self._label(key)

    def _label(self, key: str):
        head, body, _ = self.sections[key]
        label = dict((k, l) for k, l, _ in GROUPS)[key]
        head.setText(f"{'▸' if body.isHidden() else '▾'} {label} ({len(self.cards[key])})")

    def _relayout(self, key: str):
        _, _, bl = self.sections[key]
        while bl.count():
            bl.takeAt(0)
        for c in self.cards[key]:
            bl.addWidget(c)

    def set_results(self, results: list[tuple[dict, str]]):
        """results: [(verdict dict, what the test checks)] in list order."""
        for cards in self.cards.values():
            for c in cards:
                c.setParent(None)
                c.deleteLater()
        self.cards = {g: [] for g, _, _ in GROUPS}
        for v, about in results:
            card = VerdictCard(v, self, about)
            card.hovered.connect(self.hovered)
            self.cards[_group(v)].append(card)
        for key, _, _ in GROUPS:
            head, body, _ = self.sections[key]
            self._relayout(key)
            has = bool(self.cards[key])
            head.setVisible(has)
            body.setVisible(has and not self.settings.value(f"backtests/closed/{key}", False, type=bool))
            self._label(key)
        self.hint.setVisible(not results)

    def names(self, key: str) -> list[str]:
        return [c.name for c in self.cards[key]]


class BacktestsPage(QWidget):
    run_requested = Signal(object, list)   # strategy tab, [evaluator specs]
    use_changed = Signal(object, dict)     # strategy tab, its new settings
    hovered = Signal(str)

    COLS = ("Test", "Used by this strategy", "Last result", "What it checks", "Settings")

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.tabs: list = []
        self.running: set[str] = set()
        self.strategy = QComboBox()
        self.strategy.setToolTip("Which strategy the tests run on.")
        self.strategy.currentIndexChanged.connect(self.refresh_rows)
        self.run_sel = QPushButton("Run selected")
        self.run_sel.setToolTip("Run the tests you have selected in the list (Ctrl- or Shift-click to pick several).")
        self.run_sel.clicked.connect(self.run_selected)
        self.run_all = QPushButton("Run all")
        self.run_all.setToolTip("Run every test ticked as used by this strategy, one after another.")
        self.run_all.clicked.connect(self.run_used)
        self.load_btn = QPushButton("Load backtests +")
        self.load_btn.setToolTip("Tick a ready-made group of tests (a test suite) for this strategy.")
        self.load_btn.clicked.connect(self.load_menu)
        self.stale = QLabel()
        self.stale.setStyleSheet(f"color: {FAIL.name()};")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Strategy:"))
        bar.addWidget(self.strategy, 1)
        bar.addWidget(self.load_btn)
        bar.addWidget(self.run_sel)
        bar.addWidget(self.run_all)

        self.list = QTreeWidget()
        self.list.setHeaderLabels(list(self.COLS))
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda it, _c: self.request([it.data(0, Qt.UserRole)]))
        self.list.itemChanged.connect(self._ticked)
        self.list.setMouseTracking(True)
        self.list.itemEntered.connect(lambda it, _c: self.hovered.emit(
            f"Test '{it.text(0)}': {it.text(3)} Double-click to run it on this strategy."))
        self.results = ResultGroups(settings)
        self.results.hovered.connect(self.hovered)

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addLayout(bar)
        tl.addWidget(QLabel("<b>All backtests</b> <span style='color:gray'>one list for every strategy · tick the "
                            "ones a strategy uses · nothing runs until you ask</span>"))
        tl.addWidget(self.list, 1)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("<b>Results</b>"))
        bl.addWidget(self.stale)
        bl.addWidget(self.results, 1)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(bottom)
        split.setSizes([380, 460])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.fill_list()

    # ---- the global list
    def fill_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        for it in catalog().get("evaluator", []):
            if it["name"].startswith("_"):
                continue
            row = QTreeWidgetItem([it["name"], "", "", it["doc"], ""])
            row.setData(0, Qt.UserRole, it["name"])
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(1, Qt.Unchecked)
            row.setToolTip(3, it["doc"])
            self.list.addTopLevelItem(row)
        self.list.blockSignals(False)
        self.list.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.list.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.list.setColumnWidth(2, 220)
        self.list.setColumnWidth(3, 420)
        self.refresh_rows()

    def rows(self) -> list[QTreeWidgetItem]:
        return [self.list.topLevelItem(i) for i in range(self.list.topLevelItemCount())]

    def set_tabs(self, tabs: list, current=None):
        """The open strategies; ``current`` is selected if given."""
        keep = current or self.current()
        self.tabs = list(tabs)
        self.strategy.blockSignals(True)
        self.strategy.clear()
        for t in self.tabs:
            self.strategy.addItem(t.title(), t.key)
        if keep in self.tabs:
            self.strategy.setCurrentIndex(self.tabs.index(keep))
        self.strategy.blockSignals(False)
        self.refresh_rows()

    def current(self):
        i = self.strategy.currentIndex()
        return self.tabs[i] if 0 <= i < len(self.tabs) else None

    def used_specs(self, tab) -> dict[str, dict]:
        """The tests a strategy's settings list, by plugin name (suites expanded)."""
        try:
            evs = expand_evaluators(tab.config() or {})
        except ConfigError:
            evs = []
        return {e["plugin"]: e for e in evs if isinstance(e, dict) and "plugin" in e}

    def spec(self, tab, name: str) -> dict:
        return dict(self.used_specs(tab).get(name) or {"plugin": name})

    def refresh_rows(self):
        tab = self.current()
        used = self.used_specs(tab) if tab else {}
        self.list.blockSignals(True)
        for row in self.rows():
            name = row.data(0, Qt.UserRole)
            row.setCheckState(1, Qt.Checked if name in used else Qt.Unchecked)
            params = (used.get(name) or {}).get("params") or {}
            row.setText(4, ", ".join(f"{k}={v!r}" for k, v in params.items()) or "defaults")
            v = tab.results.get(name) if tab else None
            if name in self.running:
                row.setText(2, "running…")
                row.setForeground(2, NA)
            elif v:
                g = _group(v)
                row.setText(2, ("PASS" if g == "pass" else "FAIL" if g == "fail" else "N/A") + f": {v['headline']}")
                row.setForeground(2, PASS if g == "pass" else FAIL if g == "fail" else NA)
                row.setToolTip(2, v["headline"])
            else:
                row.setText(2, "")
        self.list.blockSignals(False)
        self.show_results()

    def show_results(self):
        tab = self.current()
        docs = {r.data(0, Qt.UserRole): r.text(3) for r in self.rows()}
        res = [(tab.results[n], docs.get(n, "")) for n in docs if tab and n in tab.results]
        self.results.set_results(res)
        self.stale.setText("Settings changed since these results. Run the tests again to update them."
                           if tab and tab.stale and tab.results else "")

    def _ticked(self, row, col):
        tab = self.current()
        cfg = tab.config() if tab else None
        if col != 1 or cfg is None:
            return
        name = row.data(0, Qt.UserRole)
        evs = list(self.used_specs(tab).values())  # suites expanded, so single tests can be untucked
        if row.checkState(1) == Qt.Checked:
            evs.append({"plugin": name})
        else:
            evs = [e for e in evs if e["plugin"] != name]
        self.use_changed.emit(tab, {**cfg, "evaluators": evs})

    def load_menu(self):
        menu = QMenu(self)
        for name, specs in plugin_suites().items():
            tests = ", ".join(s["plugin"] for s in specs)
            act = menu.addAction(f"{name}  ({tests})")
            act.triggered.connect(lambda _=False, s=specs: self._load_suite(s))
        if menu.isEmpty():
            menu.addAction("No test suites installed").setEnabled(False)
        menu.exec(self.load_btn.mapToGlobal(self.load_btn.rect().bottomLeft()))

    def _load_suite(self, specs: list[dict]):
        tab = self.current()
        cfg = tab.config() if tab else None
        if cfg is None:
            return
        used = self.used_specs(tab)
        for s in specs:
            used.setdefault(s["plugin"], dict(s))
        self.use_changed.emit(tab, {**cfg, "evaluators": list(used.values())})

    # ---- running
    def request(self, names: list[str]):
        tab = self.current()
        names = [n for n in names if n]
        if tab is None or not names:
            return
        self.run_requested.emit(tab, [self.spec(tab, n) for n in names])

    def run_selected(self):
        self.request([r.data(0, Qt.UserRole) for r in self.list.selectedItems()])

    def run_used(self):
        tab = self.current()
        if tab:
            self.request([r.data(0, Qt.UserRole) for r in self.rows() if r.checkState(1) == Qt.Checked])

    def set_running(self, names: set[str]):
        self.running = set(names)
        self.refresh_rows()
