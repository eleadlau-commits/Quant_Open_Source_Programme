"""Strategies page: one tab per strategy, each with Patch bay, Code and Run views.

The patch bay (Phase 2D) and the Code view (Phase 1C) both edit the one strategy
graph through ``Workspace.strategies``; the Run view (Phase 2E) runs it and reads its records.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QInputDialog, QMenu, QMessageBox, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ...app.paths import app_folder
from ...core.default_strategy import COPY_NAME, DEFAULT_STRATEGY_TAB, default_strategy, is_default
from ...core.strategy import StrategyGraph, graph_to_dict, load_strategy, save_strategy
from ...core.strategy_code import import_python
from ..design import icons, theme
from ..design import tokens as T
from ..design.components import RunButton, Segmented, badge, button, hbox
from ..views import PageStack, View
from .patchbay import PatchBay
from .run_view import RunView
from .strategy_code import CodeView

S = T.SPACE
STRATEGY_VIEWS = (
    ("Patch bay", "strategies", "Modules on a canvas, linked by cables. Drag modules in from the Module library."),
    ("Code", "code", "The same strategy as one Python file. Put the cursor on a number and make it a knob."),
    ("Run", "graph", "Run the strategy, see its measurements on the graph, turn knobs, run backtests."),
)


class StrategyTab(QWidget):
    """One strategy: a switch between its three views. ``locked``: its logic is read-only (the
    default strategy); knobs and run settings still change, and it can be duplicated."""

    duplicate_requested = Signal()

    def __init__(self, graph: StrategyGraph, workspace=None, open_page=None, app_ctx=None, locked: bool = False):
        super().__init__()
        self.graph = graph
        self.workspace = workspace
        self.locked = locked
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S["xl"], S["lg"], S["xl"], S["xl"])
        lay.setSpacing(S["lg"])
        self.switch = Segmented([name for name, _, _ in STRATEGY_VIEWS])
        self.run_btn = RunButton("Run", "Ctrl ↵", "Run this strategy (Ctrl+Enter)")
        self.badge = badge("")
        self.duplicate_btn = button("Duplicate to edit", "ghost", "plus", "Open an editable copy in a new tab")
        self.duplicate_btn.clicked.connect(self.duplicate_requested.emit)
        self.duplicate_btn.setVisible(locked)
        lay.addLayout(hbox(self.switch, self.badge, self.duplicate_btn, None, self.run_btn))
        self.views = PageStack()
        for i, (name, icon, text) in enumerate(STRATEGY_VIEWS):
            if i == 0:
                self.patch = PatchBay(graph, workspace)
                self.views.addWidget(self.patch)
            elif i == 1:
                self.code = CodeView(graph, workspace)
                self.views.addWidget(self.code)
            else:
                self.run_view = RunView(graph, workspace, open_page, app_ctx=app_ctx)
                self.views.addWidget(self.run_view)
        lay.addWidget(self.views, 1)
        self.run_btn.clicked.connect(self.run)
        self.run_view.running_changed.connect(self.run_btn.set_running)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self.run)
        self.switch.changed.connect(self._switch_to)
        self.code.graph_changed.connect(self._set_graph)
        self.patch.graph_changed.connect(self._set_graph)
        self.patch.show_code.connect(self.show_code)
        if workspace is None:  # no workspace to carry changes: hand them over directly
            self.code.graph_changed.connect(self.patch.set_graph)
            self.patch.graph_changed.connect(lambda g: self.code._on_changed(g.id, g))
        if workspace is not None:
            workspace.strategies.changed.connect(self._on_changed)
        if locked:
            self.patch.set_locked(True)
            self.code.set_locked(True)
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
        self.patch.detach()
        self.run_view.detach()

    def _switch_to(self, i: int) -> None:
        if i != 1 and self.views.currentIndex() == 1:
            self.code.read_back()  # carry over what was typed a moment ago
        self.views.setCurrentIndex(i)

    def show_code(self, module_id: str) -> None:
        """Switch to the Code view with the cursor on a module's function."""
        if self.code.read_back():
            self.switch.set_index(1)
            self.code.show_module(module_id)

    def _set_graph(self, graph: StrategyGraph) -> None:
        self.graph = graph
        n = len(graph.modules)
        if self.locked:
            self.badge.setText("Read-only")
        else:
            self.badge.setText(f"{n} module{'s' * (n != 1)}" if n else "Empty strategy")
        self.run_view.set_graph(graph)


class StrategiesView(View):
    view_id = "strategies"
    title = "Strategies"
    icon = "strategies"
    order = 20

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        # per strategy id: the graph as last saved or opened (to tell whether closing loses edits),
        # and the file it was saved to or opened from
        self._clean: dict[str, dict] = {}
        self._paths: dict[str, Path] = {}
        self._fixing_order = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._focus)
        bar = self.tabs.tabBar()
        bar.tabMoved.connect(self._keep_default_first)
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._show_tab_menu)
        save = QShortcut(QKeySequence.Save, self)
        save.setContext(Qt.WidgetWithChildrenShortcut)
        save.activated.connect(self.save_current)
        lay.addWidget(self.tabs)
        if self.ctx is not None:
            self.ctx.workspace.strategies.changed.connect(self._renamed)
        self.default_tab = self._open_default()

    # ---- the header: one way to add a strategy
    def subtitle(self) -> str:
        return "Build strategies as modules or code, run them, and turn their knobs."

    def actions_bar(self):
        lib = button("Library", icon="library", tip="The strategy library (Phase 2)")
        lib.setEnabled(False)
        new = button("New strategy", "primary", "plus", "Start, import or open a strategy")
        new.setMenu(self.add_menu())
        return [lib, new]

    def add_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("New empty strategy", self.new_strategy)
        m.addAction("From the strategy library…").setEnabled(False)
        m.addAction("Import a Python file…", self.ask_import_python)
        m.addAction("Open a strategy file…", self.ask_open_file)
        return m

    # ---- opening
    def _new_id(self) -> str:
        if self.ctx is not None:
            return self.ctx.workspace.new_strategy_id()
        import uuid

        return f"s-{uuid.uuid4().hex[:8]}"

    def _new_name(self) -> str:
        return self.ctx.workspace.new_strategy_name() if self.ctx is not None else "Strategy 1"

    def new_strategy(self) -> StrategyGraph:
        return self.open_graph(StrategyGraph(id=self._new_id(), name=self._new_name(), settings={"datasets": []}))

    def _open_default(self) -> "StrategyTab":
        """The default strategy: always open, first, read-only, and never closed."""
        graph = default_strategy()
        self.open_graph(graph)
        i = self.tabs.count() - 1
        self.tabs.setTabText(i, DEFAULT_STRATEGY_TAB)
        self.tabs.setTabToolTip(i, f"{graph.name}: {graph.doc} Read-only; duplicate it to change it.")
        return self.tabs.widget(i)

    def open_graph(self, graph: StrategyGraph, view: int = 0) -> StrategyGraph:
        """Open a strategy in a new tab (and the workspace), showing view ``view`` (0 patch bay, 1 code)."""
        ws = self.ctx.workspace if self.ctx is not None else None
        if ws is not None:
            ws.strategies.put(graph.id, graph)
        locked = is_default(graph.id)
        tab = StrategyTab(graph, ws, self.ctx.open_page if self.ctx is not None else None, self.ctx, locked=locked)
        tab.duplicate_requested.connect(lambda t=tab: self.duplicate(t.graph.id))
        i = self.tabs.addTab(tab, graph.name)
        if not locked:
            self.tabs.tabBar().setTabButton(i, QTabBar.RightSide, self._close_button(tab))
        tab.code.read_back()  # the code view tidies the graph (its doc line); count that as opened
        self._clean[graph.id] = graph_to_dict(tab.graph)
        self.tabs.setCurrentIndex(i)
        tab.switch.set_index(view)
        self._focus(i)
        return graph

    def _focus(self, i: int) -> None:
        if self.ctx is not None:
            tab = self.tabs.widget(i)
            self.ctx.workspace.focus_strategy(tab.graph.id if isinstance(tab, StrategyTab) else None)

    def _keep_default_first(self, *_):
        """Tabs move, but the default strategy stays on the left."""
        if self._fixing_order:
            return
        i = self.tabs.indexOf(self.default_tab) if hasattr(self, "default_tab") else 0
        if i > 0:
            self._fixing_order = True
            QTimer.singleShot(0, self._move_default_back)

    def _move_default_back(self) -> None:
        i = self.tabs.indexOf(self.default_tab)
        if i > 0:
            self.tabs.tabBar().moveTab(i, 0)
        self._fixing_order = False

    def tab_of(self, strategy_id: str) -> "StrategyTab | None":
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, StrategyTab) and tab.graph.id == strategy_id:
                return tab
        return None

    def _renamed(self, sid: str, graph: StrategyGraph) -> None:
        tab = self.tab_of(sid)
        if tab is not None and not tab.locked:
            self.tabs.setTabText(self.tabs.indexOf(tab), graph.name)

    # ---- the tab menu (right-click a tab)
    def _show_tab_menu(self, pt) -> None:
        bar = self.tabs.tabBar()
        menu = self._tab_menu(bar.tabAt(pt))
        if not menu.isEmpty():
            menu.exec(bar.mapToGlobal(pt))
        menu.deleteLater()

    def _tab_menu(self, i: int) -> QMenu:
        m = QMenu(self)
        tab = self.tabs.widget(i) if i >= 0 else None
        if not isinstance(tab, StrategyTab):
            return m
        sid = tab.graph.id
        if tab.locked:
            m.addAction("Duplicate to edit", lambda: self.duplicate(sid))
            return m
        m.addAction("Save", lambda: self.save_current(tab=tab)).setShortcut(QKeySequence.Save)
        m.addAction("Rename…", lambda: self.ask_rename(sid))
        m.addAction("Duplicate", lambda: self.duplicate(sid))
        m.addSeparator()
        m.addAction("Close", lambda: self.close_tab(self.tabs.indexOf(tab)))
        m.addAction("Delete…", lambda: self.ask_delete(sid))
        return m

    def rename(self, strategy_id: str, name: str) -> bool:
        tab = self.tab_of(strategy_id)
        name = name.strip()
        if tab is None or tab.locked or not name:
            return False
        graph = copy.deepcopy(tab.graph)
        graph.name = name
        if self.ctx is not None:
            self.ctx.workspace.strategies.put(strategy_id, graph)
        else:
            tab._set_graph(graph)
            self.tabs.setTabText(self.tabs.indexOf(tab), name)
        return True

    def ask_rename(self, strategy_id: str) -> None:
        tab = self.tab_of(strategy_id)
        if tab is None:
            return
        name, ok = QInputDialog.getText(self, "Rename strategy", "Name", text=tab.graph.name)
        if ok:
            self.rename(strategy_id, name)

    def duplicate(self, strategy_id: str) -> StrategyGraph | None:
        """Open an editable copy of a strategy (a new strategy with its own runs)."""
        tab = self.tab_of(strategy_id)
        if tab is None or not tab.code.read_back():
            return None
        graph = copy.deepcopy(tab.graph)
        graph.id = self._new_id()
        graph.name = COPY_NAME if tab.locked else f"{tab.graph.name} copy"
        return self.open_graph(graph, view=min(tab.views.currentIndex(), 1))

    # ---- files
    def import_python(self, path: str | Path) -> StrategyGraph:
        """Import a Python strategy file into a new tab, opened on its code."""
        path = Path(path)
        name = path.stem.replace("_", " ").strip().capitalize() or "Imported strategy"
        graph = import_python(path.read_text(encoding="utf-8"), self._new_id(), name)
        return self.open_graph(graph, view=1)

    def open_file(self, path: str | Path) -> StrategyGraph:
        path = Path(path)
        graph = load_strategy(path)
        ws = self.ctx.workspace if self.ctx is not None else None
        if is_default(graph.id) or (ws is not None and (graph.id in ws.strategies or graph.id in ws.runs.deleted)):
            graph.id = self._new_id()  # already open, deleted, or the default: open it as a new strategy
        self.open_graph(graph, view=1)
        self._paths[graph.id] = path
        return graph

    def save_current(self, folder: str | Path | None = None, tab: "StrategyTab | None" = None) -> Path | None:
        """Save the strategy in front (or ``tab``) to the file it came from, else to
        ``<app folder>/strategies/<name>.json`` (``folder`` instead of that folder)."""
        tab = tab if tab is not None else self.tabs.currentWidget()
        if not isinstance(tab, StrategyTab) or tab.locked or not tab.code.read_back():
            return None
        sid = tab.graph.id
        path = self._paths.get(sid) if folder is None else None
        if path is None:
            folder = Path(folder) if folder is not None else app_folder() / "strategies"
            folder.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r"[^\w\- ]+", "", tab.graph.name).strip() or "Strategy"
            path = folder / f"{stem}.json"
            n = 2
            while path.exists() and not self._same_strategy(path, sid):
                path = folder / f"{stem} ({n}).json"
                n += 1
        save_strategy(tab.graph, path)
        self._paths[sid] = path
        self._clean[sid] = graph_to_dict(tab.graph)
        return path

    @staticmethod
    def _same_strategy(path: Path, sid: str) -> bool:
        try:
            return load_strategy(path).id == sid
        except (OSError, ValueError):
            return False

    def unsaved(self, tab: "StrategyTab") -> bool:
        """Has the strategy changed since it was opened or last saved?"""
        tab.code.read_back()
        return not tab.locked and graph_to_dict(tab.graph) != self._clean.get(tab.graph.id)

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

    # ---- closing and deleting
    def _close_button(self, tab: QWidget) -> QToolButton:
        b = QToolButton()
        b.setToolTip("Close (its runs are kept; right-click the tab to delete it)")
        b.setCursor(Qt.PointingHandCursor)
        b.setIconSize(QSize(12, 12))
        paint = lambda w: w.setIcon(icons.icon("close", theme.current().text_faint, size=12))  # noqa: E731
        paint(b)
        theme.watch(b, paint)
        b.clicked.connect(lambda: self.close_tab(self.tabs.indexOf(tab)))
        return b

    def ask_save(self, tab: "StrategyTab") -> str:
        """Closing a strategy with unsaved changes: "save", "discard" or "cancel"."""
        box = QMessageBox(QMessageBox.Question, "Close strategy",
                          f"Save the changes to {tab.graph.name} before closing?",
                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.Save)
        box.setInformativeText("Its runs stay until you quit, and come back if you open it again.")
        return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(box.exec(), "cancel")

    def close_tab(self, i: int, ask: bool = True) -> bool:
        """Close a strategy's tab. Its runs are kept (open it again and they're back). Unsaved
        changes are asked about first. The default strategy never closes. Returns True if closed."""
        tab = self.tabs.widget(i)
        if not isinstance(tab, StrategyTab) or tab.locked:
            return False
        if ask and self.unsaved(tab):
            answer = self.ask_save(tab)
            if answer == "cancel" or (answer == "save" and self.save_current(tab=tab) is None):
                return False
        self._remove_tab(tab)
        if self.ctx is not None:
            self.ctx.workspace.strategies.remove(tab.graph.id)
        return True

    def _remove_tab(self, tab: "StrategyTab") -> None:
        tab.detach()
        self.tabs.removeTab(self.tabs.indexOf(tab))
        self._clean.pop(tab.graph.id, None)
        tab.deleteLater()

    def confirm_delete(self, tab: "StrategyTab", footprint) -> tuple[bool, bool]:
        """Ask before deleting. Returns (delete it, also delete its saved file)."""
        bits = []
        if footprint is not None:
            if footprint.runs:
                bits.append(f"{footprint.runs} run{'s' * (footprint.runs != 1)}")
            if footprint.backtests:
                bits.append(f"{footprint.backtests} backtest result{'s' * (footprint.backtests != 1)}")
        also = f" This also removes {' and '.join(bits)}." if bits else ""
        if footprint is not None and footprint.running:
            also += " Anything of it still running is stopped."
        box = QMessageBox(QMessageBox.Warning, "Delete strategy", f"Delete {tab.graph.name}?{also}",
                          QMessageBox.Cancel, self)
        box.setInformativeText("This can't be undone.")
        delete = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.setDefaultButton(QMessageBox.Cancel)
        path = self._paths.get(tab.graph.id)
        also_file = None
        if path is not None and path.exists():
            also_file = QCheckBox(f"Also delete the saved file ({path.name})")  # kept: the box doesn't own it
            box.setCheckBox(also_file)
        box.exec()
        return box.clickedButton() is delete, also_file is not None and also_file.isChecked()

    def ask_delete(self, strategy_id: str) -> bool:
        tab = self.tab_of(strategy_id)
        if tab is None or tab.locked:
            return False
        ws = self.ctx.workspace if self.ctx is not None else None
        ok, delete_file = self.confirm_delete(tab, ws.strategy_footprint(strategy_id) if ws is not None else None)
        if not ok:
            return False
        self.delete(strategy_id, delete_file)
        return True

    def delete(self, strategy_id: str, delete_file: bool = False) -> None:
        """Delete a strategy for good: its tab, its runs and their backtest results, and (if
        ``delete_file``) the file it was saved to."""
        tab = self.tab_of(strategy_id)
        if tab is None or tab.locked:
            return
        self._remove_tab(tab)
        if self.ctx is not None:
            self.ctx.workspace.delete_strategy(strategy_id)
        path = self._paths.pop(strategy_id, None)
        if delete_file and path is not None:
            path.unlink(missing_ok=True)
