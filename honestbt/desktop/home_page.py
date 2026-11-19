"""Home: the one page with things shared by every page.

Your strategies (open one to give it its own tab), the profit of everything that
has run, the settings that apply to every run, how the app looks, and the
library of packs (install, switch off, import starters, reset to empty).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import theme
from .measurements import TimeChart, series_for

PASS, FAIL = QColor("#1f8a4c"), QColor("#c0392b")


def panel(title: str, note: str = "") -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(box)
    lay.addWidget(QLabel(f"<b>{title}</b>" + (f" <span style='color:gray'>{note}</span>" if note else "")))
    return box, lay


def pct(x, d=1):
    return "" if x is None else f"{100 * x:+.{d}f}%"


class HomePage(QWidget):
    open_requested = Signal(str)       # a strategy file, or "S<n>" for an open strategy without a file
    new_requested = Signal(str)        # "python" or "patchbay"
    open_file_requested = Signal()
    settings_changed = Signal()        # time frame or costs: results need a re-run
    show_default_changed = Signal(bool)
    theme_changed = Signal(str)
    packs_requested = Signal()
    import_pack_requested = Signal()
    starters_requested = Signal()
    reset_requested = Signal()
    hovered = Signal(str)

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("Titanium", "Titanium")

        # ---- my strategies
        strat, sl = panel("My strategies", "files in Documents/Titanium · double-click to open one in its own tab")
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.itemDoubleClicked.connect(lambda it: self._open_row(it.row()))
        self.table.setToolTip("Double-click a strategy to open it. Profit, the comparison with the default strategy "
                              "and backtests show once it has run in this session.")
        buttons = QHBoxLayout()
        for text, tip, slot in (
                ("New Python strategy", "A strategy written as decide(F, p) in Python, with knobs.",
                 lambda: self.new_requested.emit("python")),
                ("New patch-bay strategy", "A strategy wired from modules in the patch bay.",
                 lambda: self.new_requested.emit("patchbay")),
                ("Open file…", "Open a strategy file (.py or .json) from anywhere.", self.open_file_requested.emit)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch()
        sl.addLayout(buttons)
        sl.addWidget(self.table, 3)
        sl.addWidget(QLabel("<b>Profit so far</b> <span style='color:gray'>every strategy that has run, and the "
                            "default strategy (dashed)</span>"))
        self.chart = TimeChart()
        self.chart.setMinimumHeight(200)
        sl.addWidget(self.chart, 2)

        # ---- settings for every run
        runs, rl = panel("Settings for every run")
        self.whole = QCheckBox("Whole dataset")
        self.whole.setToolTip("Untick to run every strategy only over the dates below.")
        self.start, self.end = QDateEdit(), QDateEdit()
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setToolTip("Strategies only decide on days inside the time frame.")
        s = self.settings.value("data/time_frame", None)
        tf = s if isinstance(s, dict) else {}
        self.whole.setChecked(not tf)
        self.start.setDate(QDate.fromString(tf.get("start", "2024-01-01"), "yyyy-MM-dd"))
        self.end.setDate(QDate.fromString(tf.get("end", "2024-12-31"), "yyyy-MM-dd"))
        self.whole.toggled.connect(self._tf_changed)
        self.start.dateChanged.connect(self._tf_changed)
        self.end.dateChanged.connect(self._tf_changed)
        tf_row = QHBoxLayout()
        for w in (self.whole, QLabel("from"), self.start, QLabel("to"), self.end):
            tf_row.addWidget(w)
        tf_row.addStretch()
        self.no_costs = QCheckBox("Last-traded price only (no spread or slippage cost)")
        self.no_costs.setToolTip("On: fills at the last traded price with no trading cost. Off (default): every "
                                 "fill pays an assumed half-spread plus slippage, about 8 basis points (5 + 3), more "
                                 "right after the open. The Cost stress test always uses real costs.")
        self.no_costs.setChecked(self.settings.value("data/no_costs", False, type=bool))
        self.no_costs.toggled.connect(self._costs_changed)
        self.show_default = QCheckBox("Show the default strategy (hold everything) next to every strategy")
        self.show_default.setToolTip("The default strategy spreads the money evenly across every stock in the "
                                     "dataset and holds it, with no costs. It runs automatically on the dataset of "
                                     "every strategy you run. It is the yardstick to beat.")
        self.show_default.setChecked(self.settings.value("view/show_default", True, type=bool))
        self.show_default.toggled.connect(self._default_toggled)
        self.theme = QComboBox()
        for m in theme.MODES:
            self.theme.addItem(theme.LABELS[m], m)
        self.theme.setCurrentIndex(max(0, theme.MODES.index(self.theme_mode())))
        self.theme.setToolTip("Light or dark. 'Same as the system' follows your computer's setting.")
        self.theme.currentIndexChanged.connect(self._theme_changed)
        form = QFormLayout()
        form.addRow("Time frame", tf_row)
        form.addRow("Trading costs", self.no_costs)
        form.addRow("Default strategy", self.show_default)
        form.addRow("Appearance", self.theme)
        rl.addLayout(form)
        self._sync_tf()

        # ---- library
        lib, ll = panel("Library", "what strategies can use · it comes in packs")
        self.library = QTableWidget()
        self.library.setEditTriggers(QTableWidget.NoEditTriggers)
        self.library.verticalHeader().setVisible(False)
        self.library.setShowGrid(False)
        self.library.setWordWrap(False)
        self.library.setSelectionMode(QTableWidget.NoSelection)
        ll.addWidget(self.library, 1)
        lb = QHBoxLayout()
        for text, tip, sig in (
                ("Manage packs…", "Every installed pack: switch built-in ones off, remove your own.",
                 self.packs_requested),
                ("Import a pack…", "Install a .tiplug pack file someone gave you.", self.import_pack_requested),
                ("Import starters…", "Copy the starter strategies and code modules into Documents/Titanium.",
                 self.starters_requested)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(sig.emit)
            lb.addWidget(b)
        self.reset_btn = QPushButton("Reset to empty…")
        self.reset_btn.setToolTip("Remove your strategies, code modules and installed packs (backed up to a zip "
                                  "first) and switch off every optional built-in pack.")
        self.reset_btn.setStyleSheet(f"QPushButton {{ color: {FAIL.name()}; }}")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        lb.addWidget(self.reset_btn)
        lb.addStretch()
        ll.addLayout(lb)

        grid = QGridLayout(self)
        grid.addWidget(strat, 0, 0, 2, 1)
        grid.addWidget(runs, 0, 1)
        grid.addWidget(lib, 1, 1)
        grid.setColumnStretch(0, 5)
        grid.setColumnStretch(1, 4)
        grid.setRowStretch(1, 1)
        self.rows: list[dict] = []

    # ---- settings
    def theme_mode(self) -> str:
        m = self.settings.value("view/theme", "system")
        return m if m in theme.MODES else "system"

    def _theme_changed(self, i: int):
        mode = self.theme.itemData(i)
        self.settings.setValue("view/theme", mode)
        self.theme_changed.emit(mode)

    def time_frame(self) -> dict | None:
        if self.whole.isChecked():
            return None
        return {"start": self.start.date().toString("yyyy-MM-dd"), "end": self.end.date().toString("yyyy-MM-dd")}

    def set_time_frame(self, tf: dict | None):
        self.whole.setChecked(tf is None)
        if tf:
            self.start.setDate(QDate.fromString(tf["start"], "yyyy-MM-dd"))
            self.end.setDate(QDate.fromString(tf["end"], "yyyy-MM-dd"))

    def _sync_tf(self):
        for w in (self.start, self.end):
            w.setEnabled(not self.whole.isChecked())

    def _tf_changed(self, *_):
        self._sync_tf()
        self.settings.setValue("data/time_frame", self.time_frame() or "")
        self.settings_changed.emit()

    def _costs_changed(self, on: bool):
        self.settings.setValue("data/no_costs", bool(on))
        self.settings_changed.emit()

    def _default_toggled(self, on: bool):
        self.settings.setValue("view/show_default", bool(on))
        self.show_default_changed.emit(bool(on))

    # ---- strategies
    def set_strategies(self, rows: list[dict]):
        """rows: {"name", "kind", "dataset", "profit", "vs_default", "tests", "status", "key", "example"}.
        ``key`` is what opening the row asks for: a file path or an open strategy's S-number."""
        self.rows = rows
        heads = ["Strategy", "Kind", "Dataset", "Profit", "vs default", "Backtests passed", ""]
        t = self.table
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vs = row.get("vs_default")
            vals = [row["name"], row["kind"], row.get("dataset", ""), pct(row.get("profit")),
                    "" if vs is None else f"{100 * vs:+.1f} pts", row.get("tests", ""), row.get("status", "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setToolTip(row.get("tip", ""))
                if c == 0 and not row.get("example"):
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                if row.get("example") and c != 0:
                    item.setForeground(QColor("#8a8a84"))
                t.setItem(r, c, item)
            for c, x in ((3, row.get("profit")), (4, vs)):
                if x is not None:
                    t.item(r, c).setForeground(PASS if x > 0 else FAIL)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def find(self, name: str) -> dict | None:
        return next((r for r in self.rows if r["name"] == name or Path(str(r["key"])).stem == name), None)

    def _open_row(self, r: int):
        if 0 <= r < len(self.rows):
            self.open_requested.emit(str(self.rows[r]["key"]))

    def set_curves(self, entries: list[dict]):
        shown = [e for e in entries if self.show_default.isChecked() or not e.get("default")]
        self.chart.set_series(series_for(shown))

    # ---- library
    def set_library(self, rows: list[tuple[str, str]]):
        t = self.library
        t.setColumnCount(2)
        t.setHorizontalHeaderLabels(["Part", "Installed"])
        t.setRowCount(len(rows))
        for r, (part, what) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(part))
            item = QTableWidgetItem(what)
            item.setToolTip(what)
            t.setItem(r, 1, item)
        t.resizeColumnToContents(0)
        t.horizontalHeader().setStretchLastSection(True)
