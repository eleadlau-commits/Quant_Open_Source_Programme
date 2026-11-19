"""The Packs window: see every pack (a folder of modules), switch them on or off, import a .tiplug."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .. import plugins
from ..plugins import pack as tiplug

ON, OFF = QColor("#1f8a4c"), QColor("#c0392b")


class PluginsDialog(QDialog):
    changed = Signal()  # plugins were reloaded; refresh anything built from the catalogue

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Packs")
        self.resize(1000, 560)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["On", "Pack", "Version", "From", "Adds", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._toggled)
        self.table.itemSelectionChanged.connect(self._selected)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)

        import_btn = QPushButton("Import a pack…")
        import_btn.clicked.connect(self.import_file)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_selected)
        folder_btn = QPushButton("Open packs folder")
        folder_btn.clicked.connect(self.open_folder)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for b in (import_btn, self.remove_btn, folder_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(close_btn)

        note = QLabel("Each pack is a folder of modules (data sources, Data → Data, Data → Buy/Sell, backtests). "
                      "Built-in ones can be switched off; the ones you install live in "
                      f"<code>{plugins.user_dir()}</code>. Only import packs from people you trust: "
                      "their code runs on your computer.")
        note.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.details)
        lay.addLayout(buttons)
        self.fill()

    # ---- table
    def fill(self):
        self.table.blockSignals(True)
        self.rows = plugins.statuses()
        self.table.setRowCount(len(self.rows))
        off = plugins.switched_off()
        for r, s in enumerate(self.rows):
            check = QTableWidgetItem()
            if s.source == "pip":
                check.setFlags(Qt.ItemIsEnabled)
            else:
                check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Unchecked if s.id in off else Qt.Checked)
            adds = [f"{len(v)} {k}" for k, v in s.provides.items()]
            adds += [f"{len(s.suites)} suite(s)"] if s.suites else []
            adds += [f"{len(s.presets)} preset(s)"] if s.presets else []
            state = "on" if s.state == "on" else f"off: {s.reason}"
            cells = [check, QTableWidgetItem(s.name or s.id), QTableWidgetItem(s.version),
                     QTableWidgetItem({"builtin": "built in", "user": "yours"}.get(s.source, s.source)),
                     QTableWidgetItem(", ".join(adds)), QTableWidgetItem(state)]
            cells[5].setForeground(ON if s.state == "on" else OFF)
            cells[5].setToolTip(state)
            for c, item in enumerate(cells):
                if c:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.blockSignals(False)
        self._selected()

    def _current(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.rows[rows[0].row()] if rows else None

    def _selected(self):
        s = self._current()
        self.remove_btn.setEnabled(bool(s and s.source == "user"))
        if s is None:
            self.details.setPlainText("")
            return
        lines = [f"{s.name}  ({s.id} {s.version}, {s.source})", s.description]
        lines += [f"{k}: {', '.join(v)}" for k, v in s.provides.items()]
        if s.suites:
            lines.append("test suites: " + ", ".join(s.suites) + '   (use as {"$suite": "name"} in evaluators)')
        if s.presets:
            lines.append("presets: " + ", ".join(s.presets))
        if s.requires:
            lines.append("needs: " + ", ".join(s.requires))
        if s.reason:
            lines.append("off: " + s.reason)
        lines.append(s.folder)
        self.details.setPlainText("\n".join(x for x in lines if x))

    def _toggled(self, item):
        if item.column() != 0:
            return
        s = self.rows[item.row()]
        plugins.set_enabled(s.id, item.checkState() == Qt.Checked)
        self.reload()

    def reload(self):
        plugins.reload()
        self.fill()
        self.changed.emit()

    # ---- buttons
    def import_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import a pack", str(plugins.user_dir().parent),
                                            f"Packs (*{tiplug.SUFFIX});;Pack folder manifest (plugin.json)")
        if not fn:
            return
        path = os.path.dirname(fn) if fn.endswith("plugin.json") else fn
        rep = tiplug.install(path)
        if not rep.ok and any("already installed" in f for f in rep.failed):
            if QMessageBox.question(self, "Replace pack?", rep.failed[-1] + "\n\nReplace it?") == QMessageBox.Yes:
                rep = tiplug.install(path, replace=True)
        (QMessageBox.information if rep.ok else QMessageBox.warning)(
            self, "Pack imported" if rep.ok else "Pack not imported", rep.text())
        if rep.ok:
            self.reload()

    def remove_selected(self):
        s = self._current()
        if not s or s.source != "user":
            return
        if QMessageBox.question(self, "Remove pack?", f"Delete the folder {s.folder}?") != QMessageBox.Yes:
            return
        try:
            tiplug.remove(s.id)
        except plugins.PluginProblem as exc:
            QMessageBox.warning(self, "Not removed", str(exc))
        self.reload()

    def open_folder(self):
        folder = plugins.user_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
