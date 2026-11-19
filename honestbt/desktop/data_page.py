"""Data page: the datasets your strategies use, and the global data every strategy can draw on.

The time frame and trading-cost settings apply to every run, so they live on the Home page."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QPushButton, QSplitter, QTableWidget,
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
    hovered = Signal(str)

    def __init__(self):
        super().__init__()
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
        lay.addWidget(split)
        self.fill_tree()

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
        gen = group("Generated data", "Measured from the data above at decision time (Data → Data modules from packs).")
        for it in catalog().get("feature", []):
            if not it["name"].startswith("_"):
                child = QTreeWidgetItem(gen, [it["name"], it["doc"]])
                child.setToolTip(1, it["doc"])
        src = group("Data sources", "Where datasets come from (from packs).")
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
