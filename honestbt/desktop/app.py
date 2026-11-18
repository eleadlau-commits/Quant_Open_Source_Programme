"""Titanium desktop app.

    python -m honestbt.desktop        (or the `titanium` command after pip install)

Everything runs locally: the window calls the honestbt engine directly, no
server and no browser.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..patchbay import expand_evaluators, validate
from ..paths import app_dir
from ..plugins import presets as plugin_presets
from ..plugins import statuses as plugin_statuses
from ..registry import catalog, load_plugins
from ..runner import run_config
from . import builder
from .help import KIND_WORDS, UI, plugin_doc
from .plugins_dialog import PluginsDialog
from .verdicts import VerdictBoard
from .patchbay_view import MIME as PLUGIN_MIME
from .patchbay_view import PatchBayView
from .widgets import EquityChart, HoverEditor

def _find_root() -> Path:
    """Folder holding configs/: the PyInstaller bundle, the source checkout, or the
    installer's app folder (parent of its .venv)."""
    candidates = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).resolve().parents[2],
                  Path(sys.prefix).parent]
    for c in candidates:
        if str(c) and (c / "configs").is_dir():
            return c
    return Path(__file__).resolve().parents[2]


ROOT = _find_root()
CONFIGS = ROOT / "configs"
USER_DIR = app_dir()  # ~/Documents/Titanium: where your own strategy files are saved
ICON = Path(__file__).resolve().parent / "assets" / "titanium.png"
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


def tip(widget, text: str):
    """Same text as a tooltip and on the help line at the bottom of the window."""
    widget.setToolTip(text)
    widget.setStatusTip(text)
    return widget


HELP_IDLE = "Hover over anything to see what it does."


class CatalogueTree(QTreeWidget):
    """Plugin catalogue whose entries can be dragged onto the patch bay."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragOnly)

    def mimeTypes(self):
        return [PLUGIN_MIME]

    def mimeData(self, items):
        mime = QMimeData()
        it = items[0] if items else None
        if it is not None and it.parent() is not None:
            mime.setData(PLUGIN_MIME, f"{it.parent().data(0, Qt.UserRole)}:{it.text(0)}".encode())
        return mime


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        load_plugins()
        self.setWindowTitle("Titanium")
        self.resize(1400, 900)
        self.current_path: Path | None = None
        self._thread: QThread | None = None

        # ---- toolbar row
        self.preset = QComboBox()
        self.fill_presets()
        self.preset.currentIndexChanged.connect(self.load_preset)
        self.run_btn = QPushButton("Run")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self.run)
        new_btn = QPushButton("New…")
        new_btn.clicked.connect(self.new_strategy)
        open_btn = QPushButton("Open…")
        open_btn.clicked.connect(self.open_file)
        save_btn = QPushButton("Save as…")
        save_btn.clicked.connect(self.save_file)
        plugins_btn = QPushButton("Plugins…")
        plugins_btn.clicked.connect(self.show_plugins)
        top = QHBoxLayout()
        title = QLabel("<b style='font-size:16px'>Titanium</b>  <span style='color:gray'>honest backtests for strategy families</span>")
        top.addWidget(title)
        top.addStretch()
        preset_lbl = QLabel("Preset:")
        for w, key in ((preset_lbl, "preset"), (self.preset, "preset"), (new_btn, "new"), (open_btn, "open"),
                       (save_btn, "save"), (plugins_btn, "plugins"), (self.run_btn, "run")):
            tip(w, UI[key])
            top.addWidget(w)

        # ---- left: patch bay
        self.graph = PatchBayView()
        tip(self.graph, UI["patchbay"])
        self.graph.setToolTip("")  # the graph shows its own per-box tooltips
        self.graph.hovered.connect(self.show_help)
        self.graph.clicked.connect(self.reveal)
        self.graph.edited.connect(self.apply_config)
        self.graph.message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        graph_scroll = QScrollArea()
        graph_scroll.setWidgetResizable(True)
        graph_scroll.setWidget(self.graph)
        self.editor = HoverEditor()
        self.editor.hovered.connect(self.show_help)
        self.editor.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        self.editor.textChanged.connect(self.on_edit)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet(f"color: {FAIL.name()};")
        self.catalogue = CatalogueTree()
        self.catalogue.setHeaderLabels(["Plugin", "What it does", "Settings"])
        self.catalogue.setMouseTracking(True)
        self.catalogue.itemEntered.connect(self.catalogue_hover)
        self.catalogue.itemDoubleClicked.connect(self.catalogue_add)
        self.catalogue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.catalogue.customContextMenuRequested.connect(self.catalogue_menu)
        self.fill_catalogue()
        left_tabs = QTabWidget()
        self.left_tabs = left_tabs
        edit_page = QWidget()
        el = QVBoxLayout(edit_page)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.editor)
        el.addWidget(self.problems)
        left_tabs.addTab(edit_page, "Settings (JSON)")
        left_tabs.addTab(self.catalogue, "Plugin catalogue")
        self._tab_help(left_tabs)
        left = QSplitter(Qt.Vertical)
        gbox = QWidget()
        gl = QVBoxLayout(gbox)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.addWidget(tip(QLabel("<b>Patch bay</b> <span style='color:gray'>features → mappings (cables) → strategy"
                                " · drag ● outputs onto settings to wire · right-click for more</span>"), UI["patchbay"]))
        gl.addWidget(graph_scroll)
        left.addWidget(gbox)
        left.addWidget(left_tabs)
        left.setSizes([480, 420])

        # ---- right: results
        self.summary = QLabel("Run a configuration to see results.")
        self.summary.setWordWrap(True)
        self.summary.setFrameShape(QFrame.StyledPanel)
        self.summary.setMargin(8)
        tip(self.summary, UI["summary"])
        self.verdicts = VerdictBoard()
        self.verdicts.hovered.connect(self.show_help)
        self.chart = EquityChart()
        self.sweep_table = QTableWidget()
        self.trades_table = QTableWidget()
        for t in (self.sweep_table, self.trades_table):
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.setSortingEnabled(True)
            t.verticalHeader().setVisible(False)
        res_tabs = QTabWidget()
        res_tabs.addTab(self.verdicts, "Verdicts")
        res_tabs.addTab(self.chart, "Equity")
        res_tabs.addTab(self.sweep_table, "Sweep")
        res_tabs.addTab(self.trades_table, "Trades")
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.summary)
        rl.addWidget(res_tabs, 1)
        self.res_tabs = res_tabs
        self._tab_help(res_tabs)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([680, 720])
        self.help_line = QLabel(HELP_IDLE)
        self.help_line.setWordWrap(True)
        self.help_line.setMinimumHeight(38)
        self.help_line.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.help_line.setFrameShape(QFrame.StyledPanel)
        self.help_line.setMargin(6)
        self.help_line.setStyleSheet("QLabel { background: palette(alternate-base); }")
        foot = QLabel(DISCLAIMER)
        foot.setStyleSheet("color: gray; font-size: 11px;")
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.addLayout(top)
        cl.addWidget(split, 1)
        cl.addWidget(self.help_line)
        cl.addWidget(foot)
        self.setCentralWidget(central)

        run_act = QAction("Run", self)
        run_act.setShortcut(QKeySequence("Ctrl+Return"))
        run_act.triggered.connect(self.run)
        self.addAction(run_act)
        self.statusBar().showMessage("Ready. Ctrl+Enter runs.")
        if self.preset.count():
            self.load_preset(0)

    # ---- hover help (the line above the disclaimer)
    def show_help(self, text: str):
        self.help_line.setText(text or HELP_IDLE)

    def event(self, e):
        if e.type() == QEvent.StatusTip:  # widgets with a status tip report it here on hover
            self.show_help(e.tip())
            return True
        return super().event(e)

    def _tab_help(self, tabs: QTabWidget):
        bar = tabs.tabBar()
        bar.setMouseTracking(True)
        bar.installEventFilter(self)
        for i in range(tabs.count()):
            tabs.setTabToolTip(i, UI.get(tabs.tabText(i), ""))

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseMove and hasattr(obj, "tabAt"):
            i = obj.tabAt(e.position().toPoint())
            self.show_help(UI.get(obj.tabText(i), "") if i >= 0 else "")
        elif e.type() == QEvent.Leave and hasattr(obj, "tabAt"):
            self.show_help("")
        return super().eventFilter(obj, e)

    # ---- building in the patch bay and the catalogue
    def apply_config(self, cfg: dict, what: str = ""):
        """Write new settings into the editor as one undoable step (Ctrl+Z in the editor undoes it)."""
        bar = self.editor.verticalScrollBar()
        keep = bar.value()
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        cur.select(cur.SelectionType.Document)
        cur.insertText(json.dumps(cfg, indent=2))
        cur.endEditBlock()
        bar.setValue(keep)
        if what:
            self.statusBar().showMessage(what, 6000)

    def reveal(self, key: str):
        self.left_tabs.setCurrentIndex(0)
        self.editor.select_key(key)

    def new_strategy(self):
        names = [it["name"] for it in catalog().get("strategy", []) if not it["name"].startswith("_")]
        if not names:
            QMessageBox.warning(self, "No strategies", "No strategy plugin is switched on. See Plugins….")
            return
        labels = [f"{n}: {plugin_doc('strategy', n)[:90]}" for n in names]
        choice, ok = QInputDialog.getItem(self, "New strategy", "Trading rules to start from:", labels, 0, False)
        if not ok:
            return
        name = names[labels.index(choice)]
        self.current_path = None
        examples = sorted(CONFIGS.glob("*.json")) + [Path(p["path"]) for p in plugin_presets()]
        self.apply_config(builder.new_config(name, examples),
                          f"New {name} strategy. Add pieces in the patch bay, then Save as… to keep it.")

    def _catalogue_entry(self, item):
        parent = item.parent() if item else None
        return (parent.data(0, Qt.UserRole), item.text(0)) if parent else None

    def catalogue_hover(self, item, _col):
        entry = self._catalogue_entry(item)
        if entry:
            kind, name = entry
            self.show_help(f"{KIND_WORDS[kind]} '{name}': {plugin_doc(kind, name)} Double-click to add it.")
        else:
            self.show_help(UI["catalogue"])

    def catalogue_add(self, item, _col=0):
        entry = self._catalogue_entry(item)
        cfg = self.config()
        if not entry or cfg is None:
            return
        kind, name = entry
        new, where = builder.add(cfg, kind, name)
        self.apply_config(new, f"Added {KIND_WORDS[kind].lower()} '{name}' at {where}")
        self.reveal(where.split(".")[-1] if kind in ("feature", "mapping") else where.split(".")[0])

    def catalogue_menu(self, pos):
        item = self.catalogue.itemAt(pos)
        entry = self._catalogue_entry(item)
        if not entry:
            return
        kind, name = entry
        verb = {"signal": "Use as exit signal", "data": "Use as data source", "strategy": "Switch strategy to this"}
        menu = QMenu(self)
        menu.addAction(f"{verb.get(kind, 'Add to strategy')}: {name}").triggered.connect(lambda: self.catalogue_add(item))
        menu.exec(self.catalogue.viewport().mapToGlobal(pos))

    # ---- config handling
    def fill_presets(self):
        self.preset.blockSignals(True)
        self.preset.clear()
        for p in sorted(CONFIGS.glob("*.json")):
            self.preset.addItem(p.stem, str(p))
        for p in plugin_presets():  # strategy families shipped in plugin folders
            self.preset.addItem(f"{p['name']} ({p['plugin']})", p["path"])
        for p in sorted(USER_DIR.glob("*.json")) if USER_DIR.exists() else []:
            self.preset.addItem(f"{p.stem} (mine)", str(p))
        self.preset.blockSignals(False)

    def show_plugins(self):
        dlg = PluginsDialog(self)
        dlg.changed.connect(self.plugins_changed)
        dlg.exec()

    def plugins_changed(self):
        self.fill_presets()
        self.fill_catalogue()
        self.on_edit()
        self.statusBar().showMessage("Plugins reloaded.", 5000)

    def fill_catalogue(self):
        self.catalogue.clear()
        for kind, items in catalog().items():
            if not items:
                continue
            parent = QTreeWidgetItem([kind, "", ""])
            parent.setData(0, Qt.UserRole, kind)
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
        self.editor.cfg = cfg

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
        self._run_cfg = cfg
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
            f"{out['elapsed_s']} s. {s['note']}</span>" + self._prereg_line(out))
        self.verdicts.set_verdicts(out["verdicts"], self._test_docs(len(out["verdicts"])))

        series = [("strategy", out["selected"]["equity"]["v"], QColor("#2f5bd3"))]
        bm = next((v for v in out["verdicts"] if v["name"] == "Benchmark"), None)
        if bm and bm["details"].get("benchmark_equity"):
            series.append(("buy the filtered universe", bm["details"]["benchmark_equity"]["v"], QColor("#8a8a84")))
        ab = next((v for v in out["verdicts"] if v["name"].startswith("Ablation")), None)
        if ab and ab["details"].get("without_equity"):
            series.append((ab["name"].replace("Ablation: ", "without "), ab["details"]["without_equity"]["v"],
                           QColor("#c0841a")))
        self.chart.set_series(series)
        self.fill_sweep(out["sweep"])
        self.fill_trades(out["selected"]["trades"])
        self.statusBar().showMessage(f"Done in {out['elapsed_s']} s", 8000)

    def _test_docs(self, n: int) -> list[str]:
        """What each test checks, from its plugin's description (verdicts come back in evaluator order)."""
        try:
            evs = expand_evaluators(getattr(self, "_run_cfg", None) or {})
        except ValueError:  # ConfigError; the run itself already reported it
            evs = []
        docs = [plugin_doc("evaluator", e.get("plugin", "")) for e in evs if isinstance(e, dict)]
        return (docs + [""] * n)[:n]

    @staticmethod
    def _prereg_line(out: dict) -> str:
        pre = out.get("preregistered")
        if not pre or pre.get("of", 1) < 2:
            return ""
        m = pre["metrics"]
        money = f", total ${m['total_pnl_usd']:,.0f}" if "total_pnl_usd" in m else ""
        return (f"<br><span style='color:gray'>Your rules as fixed in advance (no sweep): Sharpe {m.get('sharpe', 0):.2f}"
                f"{money}, ranked {pre['rank']} of {pre['of']} variants. The tests judge the best-looking variant, "
                f"the one a seller would show.</span>")

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
        futures = bool(trades) and trades[0].get("pnl_usd") is not None
        heads = ["symbol", "entry", "exit", "held (min)", "reason", "side" if futures else "score",
                 "net $" if futures else "net"] + (["R"] if futures else [])
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(trades))
        for r, tr in enumerate(trades):
            vals = [tr["symbol"], tr["entry_time"][:16].replace("T", " "), tr["exit_time"][:16].replace("T", " "),
                    str(tr["minutes_held"]), tr["reason"]]
            if futures:
                rm = tr.get("r_multiple")
                vals += ["long" if tr.get("side", 1) > 0 else "short", f"{tr['pnl_usd']:+,.2f}",
                         "–" if rm is None else f"{rm:+.2f}"]
            else:
                vals += [pct(tr.get("score")), pct(tr["net_return"])]
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
    off = [f"{s.id}: {s.reason}" for s in plugin_statuses() if s.source == "builtin" and s.state != "on"]
    ok = win.sweep_table.rowCount() > 0 and "tests" in win.summary.text() and not off
    out = Path(os.environ.get("TITANIUM_SELFTEST_OUT", "titanium_selftest.txt"))
    out.write_text(("OK " if ok else "FAIL ") + win.summary.text() + "".join(f"\nplugin off: {x}" for x in off))
    return 0 if ok else 1


def main(argv=None, on_shown=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("Titanium")
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    win = MainWindow()
    win.show()  # shown in self-test too, so CI exercises the real window system
    if on_shown:
        on_shown()
    if "--self-test" in argv:
        return self_test(app, win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
