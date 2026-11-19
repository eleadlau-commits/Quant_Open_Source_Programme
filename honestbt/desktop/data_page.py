"""Data page: the datasets your strategies use, and the global data every strategy can draw on."""
from __future__ import annotations

import json

from PySide6.QtCore import QDate, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..registry import catalog


def data_key(spec: dict) -> str:
    return json.dumps(spec or {}, sort_keys=True)


def dataset_stats(data) -> dict:
    days = data.trading_days
    return {"symbols": len(data.symbols), "bars": sum(len(t) for t in data.ts.values()),
            "from": str(days[0]) if len(days) else "–", "to": str(days[-1]) if len(days) else "–",
            "series": sorted(getattr(data, "series", {}))}


def describe(spec: dict) -> str:
    params = ", ".join(f"{k}={v}" for k, v in (spec.get("params") or {}).items())
    return f"{spec.get('plugin', '?')}" + (f" ({params})" if params else "")


class DataPage(QWidget):
    load_requested = Signal(dict)            # a data spec to load and measure
    add_complementary = Signal(dict, dict)   # dataset spec, complementary spec to add to it
    time_frame_changed = Signal()
    hovered = Signal(str)

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("Titanium", "Titanium")
        # ---- time frame: applies to every strategy run
        self.whole = QCheckBox("Whole dataset")
        self.whole.setToolTip("Untick to run every strategy only over the dates below.")
        self.start, self.end = QDateEdit(), QDateEdit()
        for w in (self.start, self.end):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
            w.setToolTip("Strategies only decide on days inside the time frame.")
        s = self.settings.value("data/time_frame", None)
        self.whole.setChecked(not s)
        self.start.setDate(QDate.fromString((s or {}).get("start", "2024-01-01") if isinstance(s, dict) else "2024-01-01", "yyyy-MM-dd"))
        self.end.setDate(QDate.fromString((s or {}).get("end", "2024-12-31") if isinstance(s, dict) else "2024-12-31", "yyyy-MM-dd"))
        self.whole.toggled.connect(self._tf_changed)
        self.start.dateChanged.connect(self._tf_changed)
        self.end.dateChanged.connect(self._tf_changed)
        tf = QHBoxLayout()
        tf.addWidget(QLabel("<b>Time frame</b>"))
        tf.addWidget(self.whole)
        tf.addWidget(QLabel("from"))
        tf.addWidget(self.start)
        tf.addWidget(QLabel("to"))
        tf.addWidget(self.end)
        tf.addSpacing(24)
        self.no_costs = QCheckBox("Last-traded price only (no spread or slippage cost)")
        self.no_costs.setToolTip("On: fills at the last traded price with no trading cost. Off (default): every fill "
                                 "pays an assumed half-spread plus slippage, about 8 basis points (5 + 3), more "
                                 "right after the open. The Cost stress test always uses real costs.")
        self.no_costs.setChecked(self.settings.value("data/no_costs", False, type=bool))
        self.no_costs.toggled.connect(self._costs_changed)
        tf.addWidget(self.no_costs)
        tf.addStretch()
        self._sync_tf()
        self.stats: dict[str, dict] = {}   # data key -> dataset_stats
        self.specs: dict[str, dict] = {}   # data key -> spec
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.itemDoubleClicked.connect(lambda it: self._load_row(it.row()))
        load = QPushButton("Load selected")
        load.setToolTip("Load the selected dataset to see how many symbols and days it has. "
                        "Running a strategy loads its dataset too.")
        load.clicked.connect(lambda: self._load_row(self.table.currentRow()))
        comp = QPushButton("Add complementary data…")
        comp.setToolTip("Attach complementary data (news, events, income) to the selected dataset, for every "
                        "strategy that uses it.")
        comp.clicked.connect(self._add_comp)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Datasets</b> <span style='color:gray'>the data each open strategy runs on</span>"))
        bar.addStretch()
        bar.addWidget(comp)
        bar.addWidget(load)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(bar)
        ll.addWidget(self.table, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Global data", "What it is"])
        self.tree.setMouseTracking(True)
        self.tree.itemEntered.connect(lambda it, _c: self.hovered.emit(it.toolTip(1) or it.text(1)))
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("<b>Global data</b> <span style='color:gray'>what every strategy can use; a strategy "
                            "only ever sees data up to the moment it decides</span>"))
        rl.addWidget(self.tree, 1)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([620, 620])
        lay = QVBoxLayout(self)
        lay.addLayout(tf)
        lay.addWidget(split)
        self.fill_tree()

    # ---- time frame
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
        self.time_frame_changed.emit()

    def _costs_changed(self, on: bool):
        self.settings.setValue("data/no_costs", bool(on))
        self.time_frame_changed.emit()  # same effect: results need a re-run

    def _add_comp(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None:
            self.hovered.emit("Select a dataset first.")
            return
        items = [it for it in catalog().get("complementary", []) if not it["name"].startswith("_")]
        if not items:
            return
        labels = [f"{it['name']}: {it['doc'][:80]}" for it in items]
        choice, ok = QInputDialog.getItem(self, "Complementary data", "Add to this dataset:", labels, 0, False)
        if ok:
            self.add_complementary.emit(self.specs[item.data(Qt.UserRole)], {"plugin": items[labels.index(choice)]["name"]})

    def fill_tree(self):
        t = self.tree
        t.clear()

        def group(title, doc):
            g = QTreeWidgetItem([title, doc])
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            t.addTopLevelItem(g)
            return g

        core = group("Core data", "The instrument's last traded price, S(t).")
        QTreeWidgetItem(core, ["Last traded price", "Minute bars (open, high, low, close, volume) and daily bars "
                                                    "built from them. For now strategies use the last traded price; "
                                                    "bid and ask are ignored."])
        comp = group("Complementary data", "News, events, income and similar series, C(t), indexed by when each "
                                           "value became known. Add them to a dataset with Add complementary data….")
        for it in catalog().get("complementary", []):
            if not it["name"].startswith("_"):
                child = QTreeWidgetItem(comp, [it["name"], it["doc"]])
                child.setToolTip(1, it["doc"])
        gen = group("Generated data", "Measured from the data above at decision time (feature plugins).")
        for it in catalog().get("feature", []):
            if not it["name"].startswith("_"):
                child = QTreeWidgetItem(gen, [it["name"], it["doc"]])
                child.setToolTip(1, it["doc"])
        src = group("Data sources", "Where datasets come from (data plugins).")
        for it in catalog().get("data", []):
            if not it["name"].startswith("_"):
                child = QTreeWidgetItem(src, [it["name"], it["doc"]])
                child.setToolTip(1, it["doc"])
        t.expandAll()
        t.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)

    def set_tabs(self, tabs: list):
        used: dict[str, list[str]] = {}
        self.specs = {}
        for tab in tabs:
            spec = (tab.config() or {}).get("data")
            if isinstance(spec, dict):
                k = data_key(spec)
                self.specs[k] = spec
                used.setdefault(k, []).append(tab.key)
        heads = ["Dataset", "Used by", "Symbols", "From", "To", "Minute bars", "Complementary"]
        t = self.table
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(used))
        for r, (k, keys) in enumerate(used.items()):
            st = self.stats.get(k) or {}
            vals = [describe(self.specs[k]), ", ".join(keys), str(st.get("symbols", "")), st.get("from", ""),
                    st.get("to", ""), f"{st['bars']:,}" if "bars" in st else "not loaded",
                    ", ".join(st.get("series") or [c.get("plugin", "?") for c in self.specs[k].get("complementary") or []])]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, k)
                t.setItem(r, c, item)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def set_stats(self, spec: dict, data):
        self.stats[data_key(spec)] = dataset_stats(data)

    def _load_row(self, row: int):
        item = self.table.item(row, 0) if row >= 0 else None
        if item is not None:
            self.load_requested.emit(self.specs[item.data(Qt.UserRole)])
