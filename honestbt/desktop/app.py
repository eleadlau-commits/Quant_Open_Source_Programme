"""Strategy Lab desktop app.

    python -m honestbt.desktop        (or the `strategy-lab` command after pip install)

Everything runs locally: the window calls the honestbt engine directly, no
server and no browser.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..patchbay import validate
from ..registry import catalog, load_plugins
from ..runner import run_config
from .widgets import EquityChart, PatchBayView

# In a PyInstaller build, bundled files live under sys._MEIPASS.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
CONFIGS = ROOT / "configs"
USER_DIR = Path.home() / "Documents" / "Strategy Lab"  # where your own strategy files are saved
PASS, FAIL, NA = QColor("#1f8a4c"), QColor("#c0392b"), QColor("#8a8a84")
DISCLAIMER = "Passing these tests means a result survived them. It is not evidence a strategy will make money. Not financial advice."


def pct(x, d=2):
    return "–" if x is None else f"{100 * x:.{d}f}%"


class RunWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            self.finished.emit(run_config(self.cfg))
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")


class VerdictCard(QFrame):
    def __init__(self, v: dict):
        super().__init__()
        color = PASS if v["passed"] is True else FAIL if v["passed"] is False else NA
        tag = "PASS" if v["passed"] is True else "FAIL" if v["passed"] is False else "N/A"
        self.setStyleSheet(f"VerdictCard {{ border-left: 4px solid {color.name()}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 4, 4)
        head = QLabel(f"<span style='color:{color.name()}; font-weight:600'>{tag}</span>&nbsp; "
                      f"<b>{v['name']}:</b> {v['headline']}")
        head.setWordWrap(True)
        body = QLabel(v["explanation"])
        body.setWordWrap(True)
        body.setStyleSheet("color: gray;")
        lay.addWidget(head)
        lay.addWidget(body)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        load_plugins()
        self.setWindowTitle("Strategy Lab")
        self.resize(1400, 900)
        self.current_path: Path | None = None
        self._thread: QThread | None = None

        # ---- toolbar row
        self.preset = QComboBox()
        for p in sorted(CONFIGS.glob("*.json")):
            self.preset.addItem(p.stem, str(p))
        for p in sorted(USER_DIR.glob("*.json")) if USER_DIR.exists() else []:
            self.preset.addItem(f"{p.stem} (mine)", str(p))
        self.preset.currentIndexChanged.connect(self.load_preset)
        self.run_btn = QPushButton("Run")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self.run)
        open_btn = QPushButton("Open…")
        open_btn.clicked.connect(self.open_file)
        save_btn = QPushButton("Save as…")
        save_btn.clicked.connect(self.save_file)
        top = QHBoxLayout()
        title = QLabel("<b style='font-size:16px'>Strategy Lab</b>  <span style='color:gray'>honest backtests for strategy families</span>")
        top.addWidget(title)
        top.addStretch()
        for w in (QLabel("Preset:"), self.preset, open_btn, save_btn, self.run_btn):
            top.addWidget(w)

        # ---- left: patch bay
        self.graph = PatchBayView()
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        self.editor.textChanged.connect(self.on_edit)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet(f"color: {FAIL.name()};")
        self.catalogue = QTreeWidget()
        self.catalogue.setHeaderLabels(["Plugin", "What it does", "Settings"])
        self.fill_catalogue()
        left_tabs = QTabWidget()
        edit_page = QWidget()
        el = QVBoxLayout(edit_page)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.editor)
        el.addWidget(self.problems)
        left_tabs.addTab(edit_page, "Settings (JSON)")
        left_tabs.addTab(self.catalogue, "Plugin catalogue")
        left = QSplitter(Qt.Vertical)
        gbox = QWidget()
        gl = QVBoxLayout(gbox)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(QLabel("<b>Patch bay</b> <span style='color:gray'>features → mappings (cables) → strategy</span>"))
        gl.addWidget(self.graph)
        left.addWidget(gbox)
        left.addWidget(left_tabs)
        left.setSizes([300, 600])

        # ---- right: results
        self.summary = QLabel("Run a configuration to see results.")
        self.summary.setWordWrap(True)
        self.summary.setFrameShape(QFrame.StyledPanel)
        self.summary.setMargin(8)
        self.verdict_box = QVBoxLayout()
        self.verdict_box.addStretch()
        vwrap = QWidget()
        vwrap.setLayout(self.verdict_box)
        vscroll = QScrollArea()
        vscroll.setWidgetResizable(True)
        vscroll.setWidget(vwrap)
        self.chart = EquityChart()
        self.sweep_table = QTableWidget()
        self.trades_table = QTableWidget()
        for t in (self.sweep_table, self.trades_table):
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.setSortingEnabled(True)
            t.verticalHeader().setVisible(False)
        res_tabs = QTabWidget()
        res_tabs.addTab(vscroll, "Verdicts")
        res_tabs.addTab(self.chart, "Equity")
        res_tabs.addTab(self.sweep_table, "Sweep")
        res_tabs.addTab(self.trades_table, "Trades")
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.summary)
        rl.addWidget(res_tabs, 1)
        self.res_tabs = res_tabs

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([600, 800])
        foot = QLabel(DISCLAIMER)
        foot.setStyleSheet("color: gray; font-size: 11px;")
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.addLayout(top)
        cl.addWidget(split, 1)
        cl.addWidget(foot)
        self.setCentralWidget(central)

        run_act = QAction("Run", self)
        run_act.setShortcut(QKeySequence("Ctrl+Return"))
        run_act.triggered.connect(self.run)
        self.addAction(run_act)
        self.statusBar().showMessage("Ready. Ctrl+Enter runs.")
        if self.preset.count():
            self.load_preset(0)

    # ---- config handling
    def fill_catalogue(self):
        for kind, items in catalog().items():
            if not items:
                continue
            parent = QTreeWidgetItem([kind, "", ""])
            parent.setFirstColumnSpanned(True)
            f = parent.font(0)
            f.setBold(True)
            parent.setFont(0, f)
            for it in items:
                if it["name"].startswith("_"):
                    continue
                params = ", ".join(f"{p['name']}={p['default']!r}" for p in it["params"])
                child = QTreeWidgetItem([it["name"], it["doc"], params])
                child.setToolTip(1, it["doc"])
                child.setToolTip(2, "\n".join(f"{p['name']}: {p['doc']}" for p in it["params"]))
                parent.addChild(child)
            self.catalogue.addTopLevelItem(parent)
        self.catalogue.expandAll()
        self.catalogue.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.catalogue.setColumnWidth(1, 320)

    def load_preset(self, idx):
        path = Path(self.preset.itemData(idx))
        self.load_path(path)

    def load_path(self, path: Path):
        self.current_path = path
        self.editor.setPlainText(json.dumps(json.loads(path.read_text()), indent=2))

    def config(self) -> dict | None:
        try:
            return json.loads(self.editor.toPlainText())
        except json.JSONDecodeError as e:
            self.problems.setText(f"JSON error, line {e.lineno}: {e.msg}")
            return None

    def on_edit(self):
        cfg = self.config()
        if cfg is None:
            return
        probs = validate(cfg)
        self.problems.setText("\n".join(probs))
        self.graph.set_config(cfg)

    def open_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open settings", str(USER_DIR if USER_DIR.exists() else CONFIGS), "JSON (*.json)")
        if fn:
            self.load_path(Path(fn))

    def save_file(self):
        cfg = self.config()
        if cfg is None:
            return
        USER_DIR.mkdir(parents=True, exist_ok=True)
        fn, _ = QFileDialog.getSaveFileName(self, "Save settings", str(USER_DIR / "my_strategy.json"), "JSON (*.json)")
        if fn:
            Path(fn).write_text(json.dumps(cfg, indent=2))
            self.statusBar().showMessage(f"Saved {fn}", 5000)

    # ---- running
    def run(self):
        cfg = self.config()
        if cfg is None or self._thread is not None:
            return
        probs = validate(cfg)
        if probs:
            QMessageBox.warning(self, "Settings problem", "\n".join(probs))
            return
        self.run_btn.setEnabled(False)
        self.run_btn.setText("Running…")
        self.statusBar().showMessage("Running backtest, sweep and tests…")
        self._thread = QThread()
        self._worker = RunWorker(cfg)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.show_results)
        self._worker.failed.connect(self.show_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._done)
        self._thread.start()

    def _done(self):
        self._thread.deleteLater()
        self._thread = None
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Run")

    def show_error(self, msg: str):
        self.statusBar().showMessage("Run failed")
        QMessageBox.critical(self, "Run failed", msg)

    def show_results(self, out: dict):
        self.last_result = out
        s = out["summary"]
        ok = s["evaluated"] and s["survived"] == s["evaluated"]
        color = PASS if ok else FAIL
        self.summary.setText(
            f"<b style='color:{color.name()}'>Survived {s['survived']} of {s['evaluated']} tests: {s['overall']}.</b><br>"
            f"<span style='color:gray'>Selected variant {json.dumps(out['selected_point'])} · {out['data']} · "
            f"{out['elapsed_s']} s. {s['note']}</span>")
        while self.verdict_box.count() > 1:
            w = self.verdict_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, v in enumerate(out["verdicts"]):
            self.verdict_box.insertWidget(i, VerdictCard(v))

        series = [("strategy", out["selected"]["equity"]["v"], QColor("#2f5bd3"))]
        bm = next((v for v in out["verdicts"] if v["name"] == "Benchmark"), None)
        if bm and bm["details"].get("benchmark_equity"):
            series.append(("buy the filtered universe", bm["details"]["benchmark_equity"]["v"], QColor("#8a8a84")))
        self.chart.set_series(series)
        self.fill_sweep(out["sweep"])
        self.fill_trades(out["selected"]["trades"])
        self.statusBar().showMessage(f"Done in {out['elapsed_s']} s", 8000)

    def fill_sweep(self, sweep):
        t = self.sweep_table
        t.setSortingEnabled(False)
        axes = list(sweep[0]["point"]) if sweep else []
        heads = [a.split(".")[-1] if a.count(".") else a for a in axes] + ["mean / period", "Sharpe", "max drawdown", "trades"]
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(sweep))
        for r, row in enumerate(sweep):
            m = row["metrics"]
            for c, a in enumerate(axes):
                t.setItem(r, c, QTableWidgetItem(str(row["point"][a])))
            mean = m.get("mean_period_return", 0.0)
            t.setItem(r, len(axes), QTableWidgetItem(pct(mean, 3)))
            t.item(r, len(axes)).setForeground(PASS if mean > 0 else FAIL)
            t.setItem(r, len(axes) + 1, QTableWidgetItem(f"{m.get('sharpe', 0):.2f}"))
            t.setItem(r, len(axes) + 2, QTableWidgetItem(pct(m.get("max_drawdown"), 1)))
            t.setItem(r, len(axes) + 3, QTableWidgetItem(str(m.get("n_trades", 0))))
        t.resizeColumnsToContents()
        t.setSortingEnabled(True)

    def fill_trades(self, trades):
        t = self.trades_table
        t.setSortingEnabled(False)
        heads = ["symbol", "entry", "exit", "held (min)", "reason", "score", "net"]
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(trades))
        for r, tr in enumerate(trades):
            vals = [tr["symbol"], tr["entry_time"][:16].replace("T", " "), tr["exit_time"][:16].replace("T", " "),
                    str(tr["minutes_held"]), tr["reason"], pct(tr.get("score")), pct(tr["net_return"])]
            for c, v in enumerate(vals):
                t.setItem(r, c, QTableWidgetItem(v))
            t.item(r, 6).setForeground(PASS if tr["net_return"] > 0 else FAIL)
        t.resizeColumnsToContents()
        t.setSortingEnabled(True)


def self_test(app: QApplication, win: MainWindow) -> int:
    """Run the first preset headlessly and exit 0 if results appear (used by CI on the built exe)."""
    import time
    win.run()
    t0 = time.time()
    while win._thread is not None and time.time() - t0 < 300:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    ok = win.sweep_table.rowCount() > 0 and "tests" in win.summary.text()
    out = Path(os.environ.get("STRATEGY_LAB_SELFTEST_OUT", "strategy_lab_selftest.txt"))
    out.write_text(("OK " if ok else "FAIL ") + win.summary.text())
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Strategy Lab")
    win = MainWindow()
    if "--self-test" in argv:
        return self_test(app, win)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
