"""Titanium desktop app.

    python -m honestbt.desktop        (or the `titanium` command after pip install)

Everything runs locally: the window calls the honestbt engine directly, no
server and no browser.

The window has four pages:

* **Data**: the datasets your strategies use and the global data they can draw on.
* **Strategies**: one tab per strategy (plus the default strategy), each with
  its own patch bay and settings, and the module library beside them.
* **Measurements**: one tab per measure of success. For now, Profit.
* **Backtests**: one list of tests for every strategy. Tests only run when you
  ask: one (double-click), a few (Run selected) or all a strategy uses (Run all).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMainWindow,
    QMenu, QMessageBox, QPushButton, QSplitter, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import baseline
from ..patchbay import validate
from ..paths import app_dir
from ..plugins import presets as plugin_presets
from ..plugins import statuses as plugin_statuses
from ..registry import catalog, load_plugins
from ..runner import StrategyRun, load_data
from . import builder
from .backtests_page import BacktestsPage
from .data_page import DataPage
from .help import KIND_WORDS, UI, plugin_doc
from .measurements import MeasurementsPage
from .patchbay_view import MIME as PLUGIN_MIME
from .plugins_dialog import PluginsDialog
from .strategy_tab import DefaultTab, StrategyTab


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
ICON_DIR = Path(__file__).resolve().parent / "assets"
APP_ID = "QuantOpenSource.Titanium"  # Windows taskbar grouping; matches the installer shortcuts
DISCLAIMER = "Passing these tests means a result survived them. It is not evidence a strategy will make money. Not financial advice."
HELP_IDLE = "Hover over anything to see what it does."


def app_icon() -> QIcon:
    """The Titanium logo at every size it was drawn for, so the title bar (16 px)
    and taskbar (24-48 px) get sharp pixels instead of a scaled-down 256 px image."""
    icon = QIcon()
    for f in sorted(ICON_DIR.glob("titanium-*.png")):
        icon.addFile(str(f))
    return icon


def _set_windows_app_id() -> None:
    """Without this, Windows groups the window under python(w).exe and shows the
    Python logo in the taskbar when running from source or the use-my-Python install."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


class Job(QObject):
    """Runs ``fn(progress)`` on a worker thread. ``progress(x)`` sends x back to the window."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.finished.emit(self.fn(self.progress.emit))
        except Exception as exc:  # shown to the user, never swallowed
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=3)}")


def strategy_report(run: StrategyRun) -> dict:
    rep = run.report()
    rep["selected"] = run.result.to_json(max_trades=5000)
    rep["default_equity"] = baseline.to_json(baseline.hold_everything(run.data))
    return rep


def tip(widget, text: str):
    """Same text as a tooltip and on the help line at the bottom of the window."""
    widget.setToolTip(text)
    widget.setStatusTip(text)
    return widget


class CatalogueTree(QTreeWidget):
    """Module library whose entries can be dragged onto the patch bay."""

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
            mime.setData(PLUGIN_MIME, f"{it.data(0, Qt.UserRole)}:{it.text(0)}".encode())
        return mime


# What each kind of module does, in the words of the Data→Data / Data→Buy-Sell picture.
LIBRARY_GROUPS = (
    ("Data → Data", ("feature", "mapping"), "Turn data into new data: measurements and formulas."),
    ("Data → Buy/Sell", ("strategy", "signal"), "Decide what to hold: entries and exits."),
    ("Data sources", ("data",), "Where datasets come from."),
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        load_plugins()
        self.setWindowTitle("Titanium")
        self.resize(1400, 900)
        self._thread: QThread | None = None
        self.strategies: list[StrategyTab] = []

        # ---- toolbar row
        self.preset = QComboBox()
        self.fill_presets()
        self.preset.activated.connect(self.load_preset)
        self.run_btn = QPushButton("Run strategy")
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
        top.addWidget(QLabel("<b style='font-size:16px'>Titanium</b>  <span style='color:gray'>honest backtests</span>"))
        top.addStretch()
        for w, key in ((QLabel("Preset:"), "preset"), (self.preset, "preset"), (new_btn, "new"), (open_btn, "open"),
                       (save_btn, "save"), (plugins_btn, "plugins"), (self.run_btn, "run")):
            tip(w, UI[key])
            top.addWidget(w)

        # ---- Strategies page: strategy tabs + module library
        self.strategy_tabs = QTabWidget()
        self.strategy_tabs.setTabsClosable(True)
        self.strategy_tabs.setMovable(False)
        self.strategy_tabs.tabCloseRequested.connect(self.close_strategy)
        self.strategy_tabs.currentChanged.connect(lambda _i: self.strategies_changed())
        add = QToolButton()
        add.setText("+")
        add.setAutoRaise(True)
        tip(add, "Add a strategy tab")
        add.clicked.connect(self.new_strategy)
        self.strategy_tabs.setCornerWidget(add, Qt.TopRightCorner)
        self.strategy_tabs.addTab(DefaultTab(), "Default")
        self.strategy_tabs.tabBar().setTabButton(0, self.strategy_tabs.tabBar().ButtonPosition.RightSide, None)
        self.strategy_tabs.setTabToolTip(0, UI["Default"])

        self.catalogue = CatalogueTree()
        self.catalogue.setHeaderLabels(["Module", "What it does", "Settings"])
        self.catalogue.setMouseTracking(True)
        self.catalogue.itemEntered.connect(self.catalogue_hover)
        self.catalogue.itemDoubleClicked.connect(self.catalogue_add)
        self.catalogue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.catalogue.customContextMenuRequested.connect(self.catalogue_menu)
        self.fill_catalogue()
        lib = QWidget()
        libl = QVBoxLayout(lib)
        libl.setContentsMargins(0, 0, 0, 0)
        libl.addWidget(tip(QLabel("<b>Module library</b> <span style='color:gray'>drag onto the patch bay or "
                                  "double-click</span>"), UI["catalogue"]))
        libl.addWidget(self.catalogue, 1)
        strat_page = QSplitter(Qt.Horizontal)
        strat_page.addWidget(self.strategy_tabs)
        strat_page.addWidget(lib)
        strat_page.setSizes([960, 420])

        # ---- the other pages
        self.data_page = DataPage()
        self.data_page.hovered.connect(self.show_help)
        self.data_page.load_requested.connect(self.load_dataset)
        self.measurements = MeasurementsPage()
        self.backtests = BacktestsPage()
        self.backtests.hovered.connect(self.show_help)
        self.backtests.run_requested.connect(self.run_tests)
        self.backtests.use_changed.connect(lambda tab, cfg: tab.apply_config(cfg, "Updated the tests this strategy uses"))

        self.pages = QTabWidget()
        self.pages.setDocumentMode(True)
        for w, name in ((self.data_page, "Data"), (strat_page, "Strategies"), (self.measurements, "Measurements"),
                        (self.backtests, "Backtests")):
            self.pages.addTab(w, name)
        self._tab_help(self.pages)
        self.pages.setCurrentIndex(1)

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
        cl.addWidget(self.pages, 1)
        cl.addWidget(self.help_line)
        cl.addWidget(foot)
        self.setCentralWidget(central)

        run_act = QAction("Run strategy", self)
        run_act.setShortcut(QKeySequence("Ctrl+Return"))
        run_act.triggered.connect(self.run)
        self.addAction(run_act)
        self.statusBar().showMessage("Ready. Ctrl+Enter runs the current strategy.")
        if self.preset.count():
            self.add_strategy(json.loads(Path(self.preset.itemData(0)).read_text()), Path(self.preset.itemData(0)))

    # ---- strategies
    @property
    def tab(self) -> StrategyTab | None:
        """The strategy in front, or the last one looked at when the Default tab is in front."""
        w = self.strategy_tabs.currentWidget()
        if isinstance(w, StrategyTab):
            self._last_tab = w
            return w
        last = getattr(self, "_last_tab", None)
        return last if last in self.strategies else (self.strategies[0] if self.strategies else None)

    # the current strategy's widgets, by their old names
    editor = property(lambda self: self.tab.editor)
    graph = property(lambda self: self.tab.graph)
    summary = property(lambda self: self.tab.summary)
    trades_table = property(lambda self: self.tab.trades_table)

    def add_strategy(self, cfg: dict, path: Path | None = None) -> StrategyTab:
        used = {t.number for t in self.strategies}
        number = next(n for n in range(1, len(used) + 2) if n not in used)
        tab = StrategyTab(cfg, path, number)
        tab.hovered.connect(self.show_help)
        tab.status.connect(lambda m: self.statusBar().showMessage(m, 8000))
        tab.edited.connect(lambda t=tab: self.strategy_edited(t))
        self.strategies.append(tab)
        self.strategies.sort(key=lambda t: t.number)
        i = self.strategy_tabs.addTab(tab, tab.tab_text())
        self.strategy_tabs.setTabToolTip(i, tab.title())
        self.strategy_tabs.setCurrentWidget(tab)
        self.strategies_changed()
        return tab

    def close_strategy(self, index: int):
        w = self.strategy_tabs.widget(index)
        if not isinstance(w, StrategyTab):
            return
        if len(self.strategies) == 1:
            self.statusBar().showMessage("Keep at least one strategy open.", 5000)
            return
        self.strategies.remove(w)
        self.strategy_tabs.removeTab(index)
        w.deleteLater()
        self.strategies_changed()

    def strategy_edited(self, tab: StrategyTab):
        i = self.strategy_tabs.indexOf(tab)
        self.strategy_tabs.setTabText(i, tab.tab_text())
        self.strategy_tabs.setTabToolTip(i, tab.title())
        self.strategies_changed()

    def strategies_changed(self):
        if not hasattr(self, "backtests"):  # still building the window
            return
        cur = self.tab
        self.backtests.set_tabs(self.strategies, cur)
        self.data_page.set_tabs(self.strategies)
        self.measurements.refresh(self.strategies)

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

    # ---- the module library
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
        examples = sorted(CONFIGS.glob("*.json")) + [Path(p["path"]) for p in plugin_presets()]
        self.add_strategy(builder.new_config(name, examples))
        self.pages.setCurrentIndex(1)
        self.statusBar().showMessage(f"New {name} strategy. Add modules in the patch bay, then Save as… to keep it.", 8000)

    def _catalogue_entry(self, item):
        parent = item.parent() if item else None
        if not parent:
            return None
        return item.data(0, Qt.UserRole), item.text(0)

    def catalogue_hover(self, item, _col):
        entry = self._catalogue_entry(item)
        if entry:
            kind, name = entry
            self.show_help(f"{KIND_WORDS[kind]} '{name}': {plugin_doc(kind, name)} Double-click to add it.")
        else:
            self.show_help(UI["catalogue"])

    def catalogue_add(self, item, _col=0):
        entry = self._catalogue_entry(item)
        tab = self.tab
        cfg = tab.config() if tab else None
        if not entry or cfg is None:
            return
        kind, name = entry
        new, where = builder.add(cfg, kind, name)
        tab.apply_config(new, f"Added {KIND_WORDS[kind].lower()} '{name}' at {where}")
        tab.reveal(where.split(".")[-1] if kind in ("feature", "mapping") else where.split(".")[0])

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

    def fill_catalogue(self):
        self.catalogue.clear()
        cat = catalog()
        for title, kinds, doc in LIBRARY_GROUPS:
            parent = QTreeWidgetItem([title, doc, ""])
            f = parent.font(0)
            f.setBold(True)
            parent.setFont(0, f)
            for kind in kinds:
                for it in cat.get(kind, []):
                    if it["name"].startswith("_"):
                        continue
                    params = ", ".join(f"{p['name']}={p['default']!r}" for p in it["params"])
                    child = QTreeWidgetItem([it["name"], it["doc"], params])
                    child.setData(0, Qt.UserRole, kind)
                    child.setToolTip(0, KIND_WORDS[kind])
                    child.setToolTip(1, it["doc"])
                    child.setToolTip(2, "\n".join(f"{p['name']}: {p['doc']}" for p in it["params"]))
                    parent.addChild(child)
            parent.setData(0, Qt.UserRole, kinds[0])
            self.catalogue.addTopLevelItem(parent)
        self.catalogue.expandAll()
        self.catalogue.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.catalogue.setColumnWidth(1, 260)

    # ---- files
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

    def load_preset(self, idx):
        """Load a preset into the strategy in front."""
        path = Path(self.preset.itemData(idx))
        if self.tab is None:
            self.add_strategy(json.loads(path.read_text()), path)
        else:
            self.tab.set_config(json.loads(path.read_text()), path)
        self.pages.setCurrentIndex(1)

    def show_plugins(self):
        dlg = PluginsDialog(self)
        dlg.changed.connect(self.plugins_changed)
        dlg.exec()

    def plugins_changed(self):
        self.fill_presets()
        self.fill_catalogue()
        self.backtests.fill_list()
        self.data_page.fill_tree()
        for t in self.strategies:
            t.on_edit(initial=True)
        self.statusBar().showMessage("Plugins reloaded.", 5000)

    def open_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open strategy", str(USER_DIR if USER_DIR.exists() else CONFIGS), "JSON (*.json)")
        if fn:
            self.add_strategy(json.loads(Path(fn).read_text()), Path(fn))
            self.pages.setCurrentIndex(1)

    def save_file(self):
        tab = self.tab
        cfg = tab.config() if tab else None
        if cfg is None:
            return
        USER_DIR.mkdir(parents=True, exist_ok=True)
        fn, _ = QFileDialog.getSaveFileName(self, "Save strategy", str(USER_DIR / "my_strategy.json"), "JSON (*.json)")
        if fn:
            Path(fn).write_text(json.dumps(cfg, indent=2))
            tab.path = Path(fn)
            self.statusBar().showMessage(f"Saved {fn}", 5000)

    # ---- running (one job at a time, on a worker thread)
    def start_job(self, fn, done, progress=None, label="Running…") -> bool:
        if self._thread is not None:
            self.statusBar().showMessage("Still running the last job. Try again when it finishes.", 5000)
            return False
        self.run_btn.setEnabled(False)
        self.backtests.run_sel.setEnabled(False)
        self.backtests.run_all.setEnabled(False)
        self.statusBar().showMessage(label)
        self._thread = QThread()
        self._job = Job(fn)
        self._job.moveToThread(self._thread)
        self._thread.started.connect(self._job.run)
        # Connect to this window's own methods: a plain function or lambda would be called on the
        # worker thread, and touching widgets from there crashes Qt.
        self._on_progress, self._on_done = progress, done
        self._job.progress.connect(self._job_progress)
        self._job.finished.connect(self._job_finished)
        self._job.failed.connect(self.show_error)
        self._job.finished.connect(self._thread.quit)
        self._job.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._done)
        self._thread.start()
        return True

    def _job_progress(self, msg):
        if self._on_progress:
            self._on_progress(msg)

    def _job_finished(self, out):
        self._on_done(out)

    def _done(self):
        self._thread.deleteLater()
        self._thread = None
        self.run_btn.setEnabled(True)
        self.backtests.run_sel.setEnabled(True)
        self.backtests.run_all.setEnabled(True)
        self.backtests.set_running(set())

    def show_error(self, msg: str):
        self.statusBar().showMessage("Run failed")
        QMessageBox.critical(self, "Run failed", msg)

    def _checked_config(self, tab: StrategyTab) -> dict | None:
        cfg = tab.config()
        if cfg is None:
            return None
        probs = validate(cfg)
        if probs:
            QMessageBox.warning(self, "Settings problem", f"{tab.title()}:\n" + "\n".join(probs))
            return None
        return cfg

    def run(self):
        """Backtest the strategy in front, exactly as written. Tests are run from the Backtests page."""
        tab = self.tab
        cfg = self._checked_config(tab) if tab else None
        if cfg is None:
            return

        def work(_progress):
            sr = StrategyRun(cfg, sweep=False)
            return sr, strategy_report(sr)

        if self.start_job(work, lambda out, t=tab: self._strategy_done(t, *out), label=f"Running {tab.title()}…"):
            self.run_btn.setText("Running…")

    def _strategy_done(self, tab: StrategyTab, run, report):
        self.run_btn.setText("Run strategy")
        if tab not in self.strategies:
            return
        tab.set_result(run, report)
        self.data_page.set_stats(run.cfg["data"], run.data)
        self.strategies_changed()
        self.statusBar().showMessage(f"{tab.title()} done in {report['elapsed_s']} s", 8000)

    def run_tests(self, tab: StrategyTab, specs: list[dict]):
        """Run tests on a strategy one at a time; each result shows as soon as it is ready.
        The strategy is (re)run first if it has no result or its settings changed."""
        cfg = self._checked_config(tab)
        if cfg is None or not specs:
            return
        need_run = tab.run is None or tab.stale
        prev_run = tab.run

        def work(progress):
            run = prev_run
            if need_run:
                run = StrategyRun(cfg, sweep=False)
                progress(("strategy", run, strategy_report(run)))
            for spec in specs:
                progress(("test", spec["plugin"], run.run_test(spec).__dict__))
            return len(specs)

        def on_progress(msg, t=tab):
            if t not in self.strategies:
                return
            if msg[0] == "strategy":
                _, run, report = msg
                self._strategy_done(t, run, report)
            else:
                _, name, verdict = msg
                t.results[name] = verdict
                self.backtests.running.discard(name)
                self.backtests.refresh_rows()

        names = [s["plugin"] for s in specs]
        if self.start_job(work, lambda n: self.statusBar().showMessage(f"Ran {n} test(s) on {tab.title()}.", 8000),
                          on_progress, label=f"Running {len(specs)} test(s) on {tab.title()}…"):
            self.backtests.set_running(set(names))

    def load_dataset(self, spec: dict):
        def work(_progress):
            return load_data(spec)

        def done(data):
            self.data_page.set_stats(spec, data)
            self.data_page.set_tabs(self.strategies)

        self.start_job(work, done, label="Loading dataset…")

    def wait(self, limit: float = 300) -> None:
        """Process events until the running job ends (for tests and the self-test)."""
        app = QApplication.instance()
        t0 = time.time()
        while self._thread is not None and time.time() - t0 < limit:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()


def self_test(app: QApplication, win: MainWindow) -> int:
    """Run the first strategy and every test it uses headlessly; exit 0 if results appear
    (used by CI on the built exe)."""
    win.run()
    win.wait()
    win.backtests.run_used()
    win.wait()
    tab = win.tab
    off = [f"{s.id}: {s.reason}" for s in plugin_statuses() if s.source == "builtin" and s.state != "on"]
    # the window icon must load in every build (frozen exe, installer, source)
    sizes = sorted(s.width() for s in app.windowIcon().availableSizes())
    icon_ok = 16 in sizes and 256 in sizes and not win.windowIcon().isNull()
    ok = bool(tab and tab.report and tab.results) and not off and icon_ok
    out = Path(os.environ.get("TITANIUM_SELFTEST_OUT", "titanium_selftest.txt"))
    summary = tab.summary.text() if tab else "no strategy"
    out.write_text(("OK " if ok else "FAIL ") + summary + f"\ntests run: {len(tab.results) if tab else 0}"
                   + f"\nwindow icon sizes: {sizes or 'MISSING'}" + "".join(f"\nplugin off: {x}" for x in off))
    return 0 if ok else 1


def main(argv=None, on_shown=None):
    argv = sys.argv if argv is None else argv
    _set_windows_app_id()
    app = QApplication(argv)
    app.setApplicationName("Titanium")
    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.show()  # shown in self-test too, so CI exercises the real window system
    if on_shown:
        on_shown()
    if "--self-test" in argv:
        return self_test(app, win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
