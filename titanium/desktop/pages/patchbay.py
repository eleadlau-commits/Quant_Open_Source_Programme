"""The Patch bay view of a strategy tab: its modules on a canvas, linked by cables.

The strategy graph is the only source of truth. Every edit here makes a new
graph (``core.patchbay``) and puts it through ``Workspace.strategies``, so the
Code view and the Knobs dock follow; changes made elsewhere (typing in the Code
view, turning a knob in the dock) redraw the canvas.

Undo and redo cover the edits made on this canvas. A change made in another
view clears the redo list, and undo then steps back from the strategy as it is now.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QInputDialog, QMenu, QVBoxLayout, QWidget

from ...core import patchbay as pb
from ...core.module_library import folders
from ...core.strategy import Link, StrategyGraph, graph_from_dict, graph_to_dict
from ..design import tokens as T
from ..design.components import (
    flow,
    Canvas, CableEnds, KnobSpec, NodeCanvasScene, NodeCanvasView, NodeSpec, badge, button, hbox, label,
)
from ..design.node_canvas import CableItem, NodeItem, node_size
from ..views import MODULE_MIME

S = T.SPACE
UNDO_LIMIT = 100
HINT = "Drag a module in from the Module library, or right-click to add one."


def _name(entry: str) -> str:
    return entry.rpartition("/")[2]


class PatchBay(QWidget):
    """The canvas for one strategy. ``workspace`` may be None (then changes stay local)."""

    graph_changed = Signal(object)  # the new StrategyGraph, after an edit made here
    show_code = Signal(str)  # a module id: show it in the Code view

    def __init__(self, graph: StrategyGraph, workspace=None, parent=None):
        super().__init__(parent)
        self.graph = graph
        self.workspace = workspace
        self._mine: dict = graph_to_dict(graph)
        self._undo: list[dict] = []
        self._redo: list[dict] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S["sm"])
        self.add_btn = button("Add module", "ghost", "module", "Add a module from the module library")
        self.add_menu = QMenu(self)
        self.add_menu.aboutToShow.connect(lambda: self._fill_add_menu(self.add_menu, None))
        self.add_btn.setMenu(self.add_menu)
        self.tidy_btn = button("Tidy", "ghost", tip="Lay the modules out left to right in link order")
        self.tidy_btn.clicked.connect(self.tidy)
        self.undo_btn = button("Undo", "ghost", tip="Undo the last change on the canvas (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = button("Redo", "ghost", tip="Redo (Ctrl+Shift+Z)")
        self.redo_btn.clicked.connect(self.redo)
        self.zoom_out_btn = button("−", "ghost", tip="Zoom out (Ctrl+−)")
        self.zoom_label = label("100%", "caption")
        self.zoom_in_btn = button("+", "ghost", tip="Zoom in (Ctrl+=)")
        self.fit_btn = button("Fit", "ghost", tip="Show every module (Ctrl+0)")
        self.error = badge("", "danger")
        self.error.hide()
        self.status = label("", "caption", wrap=True)
        lay.addLayout(flow(self.add_btn, self.tidy_btn, self.undo_btn, self.redo_btn, None, self.error, self.status,
                           hbox(self.zoom_out_btn, self.zoom_label, self.zoom_in_btn, self.fit_btn)))

        self.canvas = Canvas(backdrop=False)
        self.scene = NodeCanvasScene(self)
        self.scene.check = self._check
        self.view = NodeCanvasView(self.scene)
        self.view.accept_mime = MODULE_MIME
        self.view.empty_text = HINT
        self.canvas.body.addWidget(self.view)
        lay.addWidget(self.canvas, 1)

        # queued: these arrive from inside a mouse event on an item that the redraw replaces
        q = Qt.QueuedConnection
        self.scene.wire_dropped.connect(self._wire_dropped, q)
        self.scene.unplugged.connect(self._unplugged, q)
        self.scene.nodes_moved.connect(self.move_modules, q)
        self.scene.knob_changed.connect(self._knob_changed, q)
        self.scene.node_activated.connect(self.show_code.emit)
        self.scene.message.connect(self._hint)
        self.view.context_menu.connect(self._context_menu)
        self.view.dropped.connect(lambda entry, pt: self.add_module(entry, pt))
        self.view.zoomed.connect(lambda z: self.zoom_label.setText(f"{round(z * 100)}%"))
        self.zoom_in_btn.clicked.connect(lambda: self.view.zoom_by(1.2))
        self.zoom_out_btn.clicked.connect(lambda: self.view.zoom_by(1 / 1.2))
        self.fit_btn.clicked.connect(self.view.fit)

        for keys, fn in ((QKeySequence.Delete, self.delete_selection), (QKeySequence("Backspace"), self.delete_selection),
                         (QKeySequence.Undo, self.undo), (QKeySequence.Redo, self.redo),
                         (QKeySequence("Ctrl+Y"), self.redo), (QKeySequence("Ctrl+D"), self.duplicate_selection),
                         (QKeySequence.SelectAll, self.select_all), (QKeySequence("Ctrl+0"), self.view.fit),
                         (QKeySequence("Ctrl+="), lambda: self.view.zoom_by(1.2)),
                         (QKeySequence("Ctrl+-"), lambda: self.view.zoom_by(1 / 1.2))):
            sc = QShortcut(keys, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

        self._first_fit = True
        if workspace is not None:
            workspace.strategies.changed.connect(self._on_changed)
        self.redraw()
        self._say(self._summary())

    def detach(self) -> None:
        if self.workspace is not None:
            self.workspace.strategies.changed.disconnect(self._on_changed)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._first_fit:
            self._first_fit = False
            self.view.fit()

    # ---- messages
    def _summary(self) -> str:
        return "Drag from an output to an input to link. Right-click for more."

    def _say(self, text: str) -> None:
        self.error.hide()
        self.status.setText(text)

    def _refuse(self, reason: str, what: str = "Can't link") -> None:
        self.error.setText(what)
        self.error.show()
        self.status.setText(reason[:1].upper() + reason[1:] + ".")

    def _hint(self, text: str) -> None:
        if text:
            self.status.setText(text[:1].upper() + text[1:])
        else:
            self._say(self._summary())

    # ---- drawing
    def specs(self) -> list[NodeSpec]:
        g = self.graph
        plugged: dict[str, set[str]] = {}
        for ln in g.links:
            plugged.setdefault(ln.dst_module, set()).add(ln.dst_port)
        specs = []
        for m in g.modules:
            knobs = [KnobSpec(f"{m.id}.{k.name}", k.name, k.type.value, g.knob_value(f"{m.id}.{k.name}"),
                              k.lo, k.hi, k.step, k.doc) for k in m.knobs]
            note = _name(m.source) if m.source and _name(m.source) != m.name else ""
            tip = f"{m.name} ({m.id}). Double-click the title to see its code."
            specs.append(NodeSpec(m.id, m.name, f"{m.kind} · {m.id}", [p.name for p in m.inputs],
                                  [p.name for p in m.outputs], plugged.get(m.id, set()), knobs,
                                  m.layout or (0.0, 0.0), tip, note))
        loose = pb.place_new(g, {s.id: node_size(s) for s in specs})
        for s in specs:
            if s.id in loose:
                s.pos = loose[s.id]
        return specs

    def redraw(self) -> None:
        links = [CableEnds(ln.src_module, ln.src_port, ln.dst_module, ln.dst_port) for ln in self.graph.links]
        self.scene.set_nodes(self.specs(), links)
        self.view.viewport().update()
        self.undo_btn.setEnabled(bool(self._undo))
        self.redo_btn.setEnabled(bool(self._redo))
        self.tidy_btn.setEnabled(bool(self.graph.modules))

    def sizes(self) -> dict[str, tuple[float, float]]:
        return {i: node_size(n.spec) for i, n in self.scene.nodes.items()}

    # ---- the one way the graph changes
    def commit(self, new: StrategyGraph, message: str = "") -> None:
        """Make ``new`` the strategy (undoably) and tell everyone through the workspace."""
        if graph_to_dict(new) == graph_to_dict(self.graph):
            return
        self._undo.append(graph_to_dict(self.graph))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._apply(new)
        self._say(message or self._summary())

    def _apply(self, new: StrategyGraph) -> None:
        self.graph = new
        self._mine = graph_to_dict(new)
        self.redraw()
        if self.workspace is not None:
            self.workspace.strategies.put(new.id, new)
        self.graph_changed.emit(new)

    def set_graph(self, graph: StrategyGraph) -> None:
        """Show a graph changed elsewhere (it is not an undo step here)."""
        if graph_to_dict(graph) == self._mine:
            self.graph = graph
            return
        self.graph = graph
        self._mine = graph_to_dict(graph)
        self._redo.clear()
        self.redraw()

    def _on_changed(self, id: str, graph: StrategyGraph) -> None:
        if id == self.graph.id:
            self.set_graph(graph)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(graph_to_dict(self.graph))
        self._apply(graph_from_dict(self._undo.pop()))
        self._say("Undone.")
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(graph_to_dict(self.graph))
        self._apply(graph_from_dict(self._redo.pop()))
        self._say("Redone.")
        return True

    # ---- edits
    def _check(self, ends: CableEnds) -> str | None:
        return pb.link_problem(self.graph, Link(ends.src, ends.src_port, ends.dst, ends.dst_port))

    def _names(self, *ids: str) -> list[str]:
        mods = {m.id: m.name for m in self.graph.modules}
        return [mods.get(i, i) for i in ids]

    def link(self, src: str, src_port: str, dst: str, dst_port: str, replacing: Link | None = None) -> bool:
        """Plug ``src.src_port`` into ``dst.dst_port``. Refused links leave the strategy as it was."""
        base = pb.remove_links(self.graph, [replacing]) if replacing is not None else self.graph
        try:
            new = pb.add_link(base, Link(src, src_port, dst, dst_port))
        except pb.LinkRefused as e:
            self._refuse(str(e))
            self.redraw()
            return False
        a, b = self._names(src, dst)
        self.commit(new, f"Linked {a}’s {src_port} to {b}’s {dst_port}.")
        return True

    def _wire_dropped(self, new: CableEnds, picked: CableEnds | None) -> None:
        old = Link(picked.src, picked.src_port, picked.dst, picked.dst_port) if picked is not None else None
        self.link(new.src, new.src_port, new.dst, new.dst_port, old)

    def _unplugged(self, ends: CableEnds) -> None:
        self.unplug([ends])

    def _knob_changed(self, _id: str, key: str, value) -> None:
        self.turn_knob(key, value)

    def unplug(self, cables: list) -> None:
        links = [c if isinstance(c, Link) else Link(c.src, c.src_port, c.dst, c.dst_port) for c in cables]
        if not links:
            return
        new = pb.remove_links(self.graph, links)
        what = f"Unplugged {self._names(links[0].dst_module)[0]}’s {links[0].dst_port}." if len(links) == 1 \
            else f"Unplugged {len(links)} cables."
        self.commit(new, what)

    def add_module(self, entry_name: str, at: QPointF | tuple[float, float] | None = None) -> str | None:
        """Add a module from the library (at a canvas point; else beside the others). Returns its id."""
        if self.workspace is None:
            return None
        if isinstance(at, QPointF):
            at = (at.x() - 24.0, at.y() - 16.0)
        try:
            new, m = pb.add_from_library(self.graph, self.workspace.registry, entry_name, at)
        except KeyError:
            self._refuse("that module is no longer in the library", "Can't add")
            return None
        if at is None:
            w, h = node_size(NodeSpec(m.id, m.name, inputs=[p.name for p in m.inputs],
                                      outputs=[p.name for p in m.outputs], knobs=[None] * len(m.knobs)))
            m.layout = pb.place_new(new, {**self.sizes(), m.id: (w, h)}).get(m.id)
        self.commit(new, f"Added {m.name} as {m.id}.")
        self.scene.clearSelection()
        if m.id in self.scene.nodes:
            self.scene.nodes[m.id].setSelected(True)
        return m.id

    def remove_modules(self, ids: list[str]) -> None:
        if not ids:
            return
        names = self._names(*ids)
        self.commit(pb.remove_modules(self.graph, ids),
                    f"Removed {names[0]}." if len(ids) == 1 else f"Removed {len(ids)} modules.")

    def delete_selection(self) -> None:
        mods = self.scene.selected_nodes()
        cables = [c for c in self.scene.selected_cables() if c.src not in mods and c.dst not in mods]
        if mods and cables:
            new = pb.remove_modules(pb.remove_links(self.graph, [Link(c.src, c.src_port, c.dst, c.dst_port)
                                                                 for c in cables]), mods)
            self.commit(new, f"Removed {len(mods)} module{'s' * (len(mods) != 1)} and {len(cables)} "
                             f"cable{'s' * (len(cables) != 1)}.")
        elif mods:
            self.remove_modules(mods)
        elif cables:
            self.unplug(cables)

    def duplicate_selection(self) -> None:
        ids = self.scene.selected_nodes()
        if not ids:
            return
        new, made = pb.duplicate(self.graph, ids)
        self.commit(new, f"Duplicated {len(ids)} module{'s' * (len(ids) != 1)}.")
        self.scene.clearSelection()
        for i in made:
            if i in self.scene.nodes:
                self.scene.nodes[i].setSelected(True)

    def select_all(self) -> None:
        for n in self.scene.nodes.values():
            n.setSelected(True)

    def move_modules(self, positions: dict) -> None:
        self.commit(pb.move(self.graph, positions), "")

    def turn_knob(self, key: str, value) -> None:
        if key not in self.graph.knobs():
            return
        mid, _, name = key.partition(".")
        from ..design.node_canvas import show_value

        self.commit(pb.set_knob(self.graph, key, value), f"{self._names(mid)[0]}: {name} is {show_value(value)}.")

    def rename_module(self, module_id: str, name: str) -> bool:
        try:
            new = pb.rename(self.graph, module_id, name)
        except ValueError as e:
            self._refuse(str(e), "Can't rename")
            return False
        self.commit(new, f"Renamed {module_id} to {new.module(module_id).name}.")
        return True

    def ask_rename(self, module_id: str) -> None:
        old = self.graph.module(module_id).name
        name, ok = QInputDialog.getText(self, "Rename module", "Name", text=old)
        if ok and name.strip() and name.strip() != old:
            self.rename_module(module_id, name)

    def tidy(self) -> None:
        self.commit(pb.tidy(self.graph, self.sizes()), "Tidied the layout.")
        self.view.fit()

    def save_to_folder(self, module_id: str, folder: str) -> str | None:
        """Save a module into one of your module library folders. Returns the library entry name."""
        if self.workspace is None:
            return None
        from ...app.module_folders import ModuleFolderError, template_from_module

        m = self.graph.module(module_id)
        lib = self.workspace.modules
        name, n = m.name, 1
        while name in lib.modules(folder):
            n += 1
            name = f"{m.name} {n}"
        try:
            entry = lib.save(folder, template_from_module(m, name))
        except ModuleFolderError as e:
            self._refuse(str(e), "Can't save")
            return None
        self._say(f"Saved {m.name} to “{folder}” in the module library.")
        return entry

    def _ask_new_folder(self, module_id: str) -> None:
        folder, ok = QInputDialog.getText(self, "New folder", "Folder name")
        if ok and folder.strip():
            self.save_to_folder(module_id, folder.strip())

    # ---- menus
    def _fill_add_menu(self, m: QMenu, at: QPointF | None) -> None:
        m.clear()
        reg = self.workspace.registry if self.workspace is not None else None
        groups = folders(reg) if reg is not None else {}
        if not groups:
            m.addAction("No modules in the library").setEnabled(False)
        for folder, entries in groups.items():
            sec = m.addSection(folder.capitalize())
            sec.setEnabled(False)
            for e in entries:
                m.addAction(_name(e.name), lambda name=e.name: self.add_module(name, at)).setToolTip(e.doc)

    def _context_menu(self, item, pt: QPointF, global_pos) -> None:
        menu = self.build_menu(item, pt)
        menu.exec(global_pos)

    def build_menu(self, item, pt: QPointF) -> QMenu:
        menu = QMenu(self)
        if isinstance(item, NodeItem):
            ids = self.scene.selected_nodes() or [item.spec.id]
            mid = item.spec.id
            if len(ids) == 1:
                menu.addAction("Rename…", lambda: self.ask_rename(mid))
                menu.addAction("Show code", lambda: self.show_code.emit(mid))
                plugged = [ln for ln in self.graph.links if ln.dst_module == mid]
                if plugged:
                    unplug = menu.addMenu("Unplug")
                    for ln in plugged:
                        src = self._names(ln.src_module)[0]
                        unplug.addAction(f"{ln.dst_port}  ←  {src}.{ln.src_port}",
                                         lambda ln=ln: self.unplug([ln]))
                    if len(plugged) > 1:
                        unplug.addSeparator()
                        unplug.addAction("All inputs", lambda: self.unplug(plugged))
                if self.workspace is not None:
                    save = menu.addMenu("Save to module library")
                    for folder in self.workspace.modules.folders():
                        save.addAction(folder, lambda f=folder: self.save_to_folder(mid, f))
                    if self.workspace.modules.folders():
                        save.addSeparator()
                    save.addAction("New folder…", lambda: self._ask_new_folder(mid))
            menu.addAction("Duplicate", self.duplicate_selection).setShortcut(QKeySequence("Ctrl+D"))
            menu.addSeparator()
            n = len(ids)
            menu.addAction("Remove" if n == 1 else f"Remove {n} modules",
                           lambda: self.remove_modules(ids)).setShortcut(QKeySequence.Delete)
        elif isinstance(item, CableItem):
            e = item.ends
            menu.addAction("Unplug", lambda: self.unplug([e])).setShortcut(QKeySequence.Delete)
            menu.addAction(f"Show code of {self._names(e.dst)[0]}", lambda: self.show_code.emit(e.dst))
        else:
            add = menu.addMenu("Add module here")
            self._fill_add_menu(add, pt)
            menu.addSeparator()
            menu.addAction("Tidy layout", self.tidy).setEnabled(bool(self.graph.modules))
            menu.addAction("Fit to view", self.view.fit).setShortcut(QKeySequence("Ctrl+0"))
            menu.addAction("Select all", self.select_all).setShortcut(QKeySequence.SelectAll)
            menu.addSeparator()
            menu.addAction("Undo", self.undo).setEnabled(bool(self._undo))
            menu.addAction("Redo", self.redo).setEnabled(bool(self._redo))
        return menu
