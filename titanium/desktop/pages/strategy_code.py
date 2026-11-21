"""The Code view of a strategy tab: the strategy as one Python file.

Edits are read back into the graph a moment after you stop typing, and go
through ``Workspace.strategies`` like every other change, so the Knobs dock (and
later the patch bay) follow. Changes made elsewhere (turning a knob) rewrite only
the part of the file that changed.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from ...core.module_library import add_to_graph, folders
from ...core.strategy import StrategyGraph, graph_to_dict
from ...core.strategy_code import StrategyCodeError, generate, make_knob, update_from_code
from ..design import tokens as T
from ..design.components import CodeEditor, badge, button, hbox, label

S = T.SPACE
PARSE_DELAY_MS = 400


class CodeView(QWidget):
    """Editor for one strategy. ``workspace`` may be None (then changes stay local)."""

    graph_changed = Signal(object)  # the new StrategyGraph, after an edit was read back

    def __init__(self, graph: StrategyGraph, workspace=None, parent=None):
        super().__init__(parent)
        self.graph = graph
        self.workspace = workspace
        self._mine: dict | None = None  # the graph as this view last wrote it

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S["sm"])
        self.knob_btn = button("Make knob", "ghost", "knob", "Turn the number under the cursor into a knob (Ctrl+K)")
        self.knob_btn.clicked.connect(self.make_knob)
        self.add_btn = button("Add module", "ghost", "module", "Add a module from the module library")
        self.add_btn.setMenu(self._module_menu())
        self.status = label("", "caption")
        self.error = badge("", "danger")
        self.error.hide()
        lay.addLayout(hbox(self.knob_btn, self.add_btn, None, self.error, self.status))
        self.editor = CodeEditor()
        self.editor.setPlainText(generate(graph))
        self._mine = graph_to_dict(graph)
        lay.addWidget(self.editor, 1)

        self._timer = QTimer(self, singleShot=True, interval=PARSE_DELAY_MS)
        self._timer.timeout.connect(self.read_back)
        self.editor.textChanged.connect(self._timer.start)
        sc = QShortcut(QKeySequence("Ctrl+K"), self.editor)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self.make_knob)
        if workspace is not None:
            workspace.strategies.changed.connect(self._on_changed)
        self._say(self._summary())

    def detach(self) -> None:
        self._timer.stop()
        if self.workspace is not None:
            self.workspace.strategies.changed.disconnect(self._on_changed)

    # ---- messages
    def _summary(self) -> str:
        return "Edits apply as you type. Ctrl+K makes the number under the cursor a knob."

    def _say(self, text: str) -> None:
        self.error.hide()
        self.status.setText(text)

    def _fail(self, e: StrategyCodeError) -> None:
        self.error.setText(f"Line {e.line}" if e.line else "Can't read")
        self.error.show()
        self.status.setText(e.message)

    # ---- reading edits back
    def read_back(self) -> bool:
        """Parse the editor into the graph. Returns False (and shows why) if it can't be read."""
        self._timer.stop()
        try:
            new = update_from_code(self.graph, self.editor.toPlainText())
        except StrategyCodeError as e:
            self._fail(e)
            return False
        if graph_to_dict(new) != graph_to_dict(self.graph):
            self._commit(new)
        self._say(self._summary())
        return True

    def _commit(self, new: StrategyGraph) -> None:
        self.graph = new
        self._mine = graph_to_dict(new)
        if self.workspace is not None:
            self.workspace.strategies.put(new.id, new)
        self.graph_changed.emit(new)

    def _on_changed(self, id: str, graph: StrategyGraph) -> None:
        if id != self.graph.id:
            return
        if graph_to_dict(graph) == self._mine:
            self.graph = graph
            return
        # changed elsewhere (a knob turned, a module added): show it, keeping the cursor
        self.graph = graph
        self._mine = graph_to_dict(graph)
        self.editor.blockSignals(True)
        try:
            self.editor.set_text_preserving(generate(graph))
        finally:
            self.editor.blockSignals(False)
        self.editor.viewport().update()
        self._say(self._summary())

    def show_module(self, module_id: str) -> bool:
        """Put the cursor on a module's function and scroll it into view."""
        doc = self.editor.document()
        cur = doc.find(f'@module(id="{module_id}"')
        if cur.isNull():
            return False
        block = cur.block().next()
        while block.isValid() and not block.text().lstrip().startswith(("def ", "async def ")):
            block = block.next()
        cur.setPosition((block if block.isValid() else cur.block()).position())
        self.editor.setTextCursor(cur)
        self.editor.centerCursor()
        self.editor.setFocus()
        return True

    # ---- actions
    def make_knob(self) -> str | None:
        line, col = self.editor.cursor_line_col()
        try:
            src, name = make_knob(self.editor.toPlainText(), line, col)
        except StrategyCodeError as e:
            self._fail(e)
            return None
        self.editor.set_text_preserving(src)
        if self.read_back():
            self._say(f"Made the knob “{name}”. Turn it in the Knobs dock.")
        return name

    def _module_menu(self) -> QMenu:
        m = QMenu(self)
        m.aboutToShow.connect(lambda: self._fill_module_menu(m))
        return m

    def _fill_module_menu(self, m: QMenu) -> None:
        m.clear()
        reg = self.workspace.registry if self.workspace is not None else None
        groups = folders(reg) if reg is not None else {}
        if not groups:
            m.addAction("No modules in the library").setEnabled(False)
        for folder, entries in groups.items():
            sec = m.addSection(folder.capitalize())
            sec.setEnabled(False)
            for e in entries:
                m.addAction(e.name.rpartition("/")[2], lambda name=e.name: self.add_module(name)).setToolTip(e.doc)

    def add_module(self, entry_name: str) -> None:
        if not self.read_back() or self.workspace is None:
            return
        new = update_from_code(self.graph, generate(self.graph))  # a copy to change
        mod = add_to_graph(new, self.workspace.registry, entry_name)
        self.workspace.strategies.put(new.id, new)  # _on_changed shows it in the editor
        self._say(f"Added “{mod.name}” as {mod.id}. Link it on the patch bay, or in @module(links=...).")
