"""Strategies page: one tab per strategy, each with Patch bay, Code and Run views.

The Code view is built (Phase 1C) and the Run view (Phase 2E); the patch bay follows in Phase 2D.
"""
from __future__ import annotations

import itertools
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QMenu, QMessageBox, QStackedWidget, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ...app.paths import app_folder
from ...core.strategy import StrategyGraph, load_strategy, save_strategy
from ...core.strategy_code import import_python
from ..design import icons, theme
from ..design import tokens as T
from ..design.components import Canvas, EmptyState, RunButton, Segmented, badge, button, hbox, label
from ..views import View
from .run_view import RunView
from .strategy_code import CodeView

S = T.SPACE
STRATEGY_VIEWS = (
    ("Patch bay", "strategies", "Modules on a canvas, linked by cables. Drag modules in from the Module library."),
    ("Code", "code", "The same strategy as one Python file. Put the cursor on a number and make it a knob."),
    ("Run", "graph", "Run the strategy, see its measurements on the graph, turn knobs, run backtests."),
)


class StrategyTab(QWidget):
    """One strategy: a switch between its three views."""

    def __init__(self, graph: StrategyGraph, workspace=None, open_page=None):
        super().__init__()
        self.graph = graph
        self.workspace = workspace
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S["xl"], S["lg"], S["xl"], S["xl"])
        lay.setSpacing(S["lg"])
        self.switch = Segmented([name for name, _, _ in STRATEGY_VIEWS])
        self.run_btn = RunButton("Run", "Ctrl ↵", "Run this strategy (Ctrl+Enter)")
        self.badge = badge("")
        lay.addLayout(hbox(self.switch, self.badge, None, self.run_btn))
        self.views = QStackedWidget()
        for i, (name, icon, text) in enumerate(STRATEGY_VIEWS):
            if i == 0:  # the patch bay is a canvas
                canvas = Canvas()
                canvas.body.addWidget(EmptyState(icon, name, text))
                self.views.addWidget(canvas)
            elif i == 1:
                self.code = CodeView(graph, workspace)
                self.views.addWidget(self.code)
            else:
                self.run_view = RunView(graph, workspace, open_page)
                self.views.addWidget(self.run_view)
        lay.addWidget(self.views, 1)
        self.run_btn.clicked.connect(self.run)
        self.run_view.running_changed.connect(self.run_btn.set_running)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self.run)
        self.switch.changed.connect(self.views.setCurrentIndex)
        self.code.graph_changed.connect(self._set_graph)
        if workspace is not None:
            workspace.strategies.changed.connect(self._on_changed)
        self._set_graph(graph)

    def run(self) -> None:
        """Run (or, while running, cancel). Reads the code back first so edits are included."""
        if self.run_view.running:
            self.run_view.cancel()
            return
        if not self.code.read_back():
            self.switch.set_index(1)  # the code view shows what's wrong
            return
        self.switch.set_index(2)
        self.run_view.run()

    def _on_changed(self, id: str, graph: StrategyGraph) -> None:
        if id == self.graph.id:
            self._set_graph(graph)

    def detach(self) -> None:
        """Stop following the workspace (the tab is closing)."""
        if self.workspace is not None:
            self.workspace.strategies.changed.disconnect(self._on_changed)
            self.code.detach()
            self.run_view.detach()

    def _set_graph(self, graph: StrategyGraph) -> None:
        self.graph = graph
        n = len(graph.modules)
        self.badge.setText(f"{n} module{'s' * (n != 1)}" if n else "Empty strategy")
        self.run_view.set_graph(graph)


class StrategiesView(View):
    view_id = "strategies"
    title = "Strategies"
    icon = "strategies"
    order = 20

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self._n = itertools.count(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        lay.addWidget(self.pages)

        empty_wrap = QWidget()
        el = QVBoxLayout(empty_wrap)
        el.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        new_btn = button("New empty strategy", "primary", "plus")
        new_btn.clicked.connect(self.new_strategy)
        import_btn = button("Import Python file", icon="import")
        import_btn.clicked.connect(self.ask_import_python)
        lib_btn = button("Strategy library", icon="library", tip="The strategy library (Phase 2)")
        lib_btn.setEnabled(False)
        self.empty = EmptyState(
            "strategies", "No strategies open",
            "Start an empty strategy, pick one from the strategy library, or import a Python file.",
            [new_btn, lib_btn, import_btn])
        el.addWidget(self.empty)
        self.pages.addWidget(empty_wrap)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._focus)
        save = QShortcut(QKeySequence.Save, self)
        save.setContext(Qt.WidgetWithChildrenShortcut)
        save.activated.connect(self.save_current)
        self.plus = QToolButton()
        self.plus.setToolTip("Add a strategy")
        self.plus.setPopupMode(QToolButton.InstantPopup)
        self.plus.setCursor(Qt.PointingHandCursor)
        self.plus.setMenu(self._add_menu())
        self.plus.setIcon(icons.icon("plus", theme.current().text_muted, size=16))
        theme.watch(self.plus, lambda b: b.setIcon(icons.icon("plus", theme.current().text_muted, size=16)))
        self.tabs.setCornerWidget(self.plus, Qt.TopRightCorner)
        self.pages.addWidget(self.tabs)

    def _add_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("New empty strategy", self.new_strategy)
        m.addAction("From the strategy library…").setEnabled(False)
        m.addAction("Import a Python file…", self.ask_import_python)
        m.addAction("Open a strategy file…", self.ask_open_file)
        m.addSeparator()
        m.addAction("Save this strategy", self.save_current)
        return m

    def subtitle(self) -> str:
        return "Build strategies as modules or code, run them, and turn their knobs."

    def actions_bar(self):
        lib = button("Library", icon="library", tip="The strategy library (Phase 2)")
        lib.setEnabled(False)
        new = button("New strategy", "primary", "plus")
        new.clicked.connect(self.new_strategy)
        return [lib, new]

    def _next_id(self) -> str:
        taken = set(self.ctx.workspace.strategies.ids()) if self.ctx is not None else set()
        while True:
            sid = f"S{next(self._n)}"
            if sid not in taken:
                return sid

    def new_strategy(self) -> StrategyGraph:
        sid = self._next_id()
        return self.open_graph(StrategyGraph(id=sid, name=f"Strategy {sid[1:]}", settings={"datasets": []}))

    def open_graph(self, graph: StrategyGraph, view: int = 0) -> StrategyGraph:
        """Open a strategy in a new tab (and the workspace), showing view ``view`` (0 patch bay, 1 code)."""
        ws = self.ctx.workspace if self.ctx is not None else None
        if ws is not None:
            ws.strategies.put(graph.id, graph)
        tab = StrategyTab(graph, ws, self.ctx.open_page if self.ctx is not None else None)
        i = self.tabs.addTab(tab, f"{graph.id}  {graph.name}")
        self.tabs.tabBar().setTabButton(i, QTabBar.RightSide, self._close_button(tab))
        self.tabs.setCurrentIndex(i)
        self.pages.setCurrentWidget(self.tabs)
        tab.switch.set_index(view)
        self._focus(i)
        return graph

    def _focus(self, i: int) -> None:
        if self.ctx is not None:
            tab = self.tabs.widget(i)
            self.ctx.workspace.focus_strategy(tab.graph.id if isinstance(tab, StrategyTab) else None)

    # ---- files
    def import_python(self, path: str | Path) -> StrategyGraph:
        """Import a Python strategy file into a new tab, opened on its code."""
        path = Path(path)
        name = path.stem.replace("_", " ").strip().capitalize() or "Imported strategy"
        graph = import_python(path.read_text(encoding="utf-8"), self._next_id(), name)
        return self.open_graph(graph, view=1)

    def open_file(self, path: str | Path) -> StrategyGraph:
        graph = load_strategy(path)
        if self.ctx is not None and graph.id in self.ctx.workspace.strategies:
            graph.id = self._next_id()
        return self.open_graph(graph, view=1)

    def save_current(self, folder: str | Path | None = None) -> Path | None:
        """Save the strategy in front to ``<app folder>/strategies/<id> <name>.json``."""
        tab = self.tabs.currentWidget()
        if not isinstance(tab, StrategyTab) or not tab.code.read_back():
            return None
        folder = Path(folder) if folder is not None else app_folder() / "strategies"
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\- ]+", "", f"{tab.graph.id} {tab.graph.name}").strip()
        path = folder / f"{safe}.json"
        save_strategy(tab.graph, path)
        return path

    def _start_folder(self) -> str:
        folder = app_folder() / "strategies"
        return str(folder if folder.exists() else Path.home())

    def ask_import_python(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import a Python strategy", self._start_folder(),
                                              "Python files (*.py)")
        if path:
            self._try(lambda: self.import_python(path), "Couldn't import that file")

    def ask_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open a strategy file", self._start_folder(),
                                              "Strategy files (*.json)")
        if path:
            self._try(lambda: self.open_file(path), "Couldn't open that file")

    def _try(self, fn, title: str) -> None:
        try:
            fn()
        except (OSError, ValueError, UnicodeDecodeError) as e:
            QMessageBox.warning(self, title, str(e))

    def _close_button(self, tab: QWidget) -> QToolButton:
        b = QToolButton()
        b.setToolTip("Close")
        b.setCursor(Qt.PointingHandCursor)
        b.setIconSize(QSize(12, 12))
        paint = lambda w: w.setIcon(icons.icon("close", theme.current().text_faint, size=12))  # noqa: E731
        paint(b)
        theme.watch(b, paint)
        b.clicked.connect(lambda: self.close_tab(self.tabs.indexOf(tab)))
        return b

    def close_tab(self, i: int) -> None:
        tab = self.tabs.widget(i)
        if isinstance(tab, StrategyTab):
            tab.detach()
        self.tabs.removeTab(i)
        if self.ctx is not None and isinstance(tab, StrategyTab):
            self.ctx.workspace.strategies.remove(tab.graph.id)
        if tab is not None:
            tab.deleteLater()
        if self.tabs.count() == 0:
            self.pages.setCurrentIndex(0)
