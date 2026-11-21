"""Strategies page: one tab per strategy, each with Patch bay, Code and Run views.

The three views are built out in Phases 1C, 2D and 2E; this is their frame.
"""
from __future__ import annotations

import itertools

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QMenu, QStackedWidget, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget

from ...core.strategy import StrategyGraph
from ..design import icons, theme
from ..design import tokens as T
from ..design.components import EmptyState, Segmented, badge, button, hbox, label
from ..views import View

S = T.SPACE
STRATEGY_VIEWS = (
    ("Patch bay", "strategies", "Modules on a canvas, linked by cables. Drag modules in from the Module library."),
    ("Code", "code", "The same strategy as one Python file. Put the cursor on a number and make it a knob."),
    ("Run", "graph", "Run the strategy, see its measurements on the graph, turn knobs, run backtests."),
)


class StrategyTab(QWidget):
    """One strategy: a switch between its three views."""

    def __init__(self, graph: StrategyGraph):
        super().__init__()
        self.graph = graph
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S["xl"], S["lg"], S["xl"], S["xl"])
        lay.setSpacing(S["lg"])
        self.switch = Segmented([name for name, _, _ in STRATEGY_VIEWS])
        self.run_btn = button("Run", "primary", "play", "Run this strategy (Ctrl+Enter)")
        lay.addLayout(hbox(self.switch, badge("Empty strategy"), None, self.run_btn))
        self.views = QStackedWidget()
        for name, icon, text in STRATEGY_VIEWS:
            self.views.addWidget(EmptyState(icon, name, text))
        lay.addWidget(self.views, 1)
        self.switch.changed.connect(self.views.setCurrentIndex)


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
        self.empty = EmptyState(
            "strategies", "No strategies open",
            "Start an empty strategy, pick one from the strategy library, or import a Python file.",
            [new_btn, button("Strategy library", icon="library"), button("Import Python file", icon="import")])
        el.addWidget(self.empty)
        self.pages.addWidget(empty_wrap)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
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
        m.addAction("Import a Python file…").setEnabled(False)
        return m

    def subtitle(self) -> str:
        return "Build strategies as modules or code, run them, and turn their knobs."

    def actions_bar(self):
        lib = button("Library", icon="library", tip="The strategy library (Phase 2)")
        lib.setEnabled(False)
        new = button("New strategy", "primary", "plus")
        new.clicked.connect(self.new_strategy)
        return [lib, new]

    def new_strategy(self) -> StrategyGraph:
        n = next(self._n)
        graph = StrategyGraph(id=f"S{n}", name=f"Strategy {n}")
        if self.ctx is not None:
            self.ctx.workspace.strategies.put(graph.id, graph)
        tab = StrategyTab(graph)
        i = self.tabs.addTab(tab, f"{graph.id}  {graph.name}")
        self.tabs.tabBar().setTabButton(i, QTabBar.RightSide, self._close_button(tab))
        self.tabs.setCurrentIndex(i)
        self.pages.setCurrentWidget(self.tabs)
        return graph

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
        self.tabs.removeTab(i)
        if self.ctx is not None and isinstance(tab, StrategyTab):
            self.ctx.workspace.strategies.remove(tab.graph.id)
        if self.tabs.count() == 0:
            self.pages.setCurrentIndex(0)
