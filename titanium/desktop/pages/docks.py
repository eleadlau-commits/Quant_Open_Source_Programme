"""Panels that start as docks on the Strategies page. Filled in by Phases 2D and 2E."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QInputDialog, QMenu, QMessageBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ...app.module_folders import USER, ModuleFolderError
from ...core.module_library import STARTER, folders
from ..design import icons, theme
from ..design import tokens as T
from ...core.baseline import DEFAULT_ID
from ...core.markets import MARKETS
from ..design.components import DataTable, KnobControl, SearchField, button, hbox, label
from ..views import DOCK, MODULE_MIME, View

S = T.SPACE


class _DockPanel(View):
    default_host = DOCK
    pages = ("strategies",)
    text = ""

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(S["md"], S["md"], S["md"], S["md"])
        self.lay.setSpacing(S["sm"])
        self.build()
        self.note = label(self.text, "caption", wrap=True)
        self.note.setVisible(bool(self.text))
        self.lay.addWidget(self.note)
        if self.text:
            self.lay.addStretch()

    def build(self) -> None:
        pass


class ModuleTree(QTreeWidget):
    """The module library as folders of modules. Modules drag out onto the patch bay
    (and onto another of your folders to move them there)."""

    def __init__(self, panel: "ModuleLibraryView"):
        super().__init__()
        self.panel = panel
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(S["lg"])
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def mimeTypes(self) -> list[str]:
        return [MODULE_MIME]

    def mimeData(self, items) -> QMimeData:
        data = QMimeData()
        entry = next((it.data(0, ROLE)[1] for it in items if it.data(0, ROLE)[0] == "module"), None)
        if entry is not None:
            data.setData(MODULE_MIME, QByteArray(entry.encode("utf-8")))
            data.setText(entry)
        return data

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def _target_folder(self, pos) -> str | None:
        item = self.itemAt(pos)
        while item is not None and item.data(0, ROLE)[0] != "folder":
            item = item.parent()
        if item is None:
            return None
        _, name, kind = item.data(0, ROLE)
        return name if kind == USER_FOLDER else None

    def dragMoveEvent(self, e) -> None:
        if e.source() is self and e.mimeData().hasFormat(MODULE_MIME) and self._target_folder(e.position().toPoint()):
            e.setDropAction(Qt.MoveAction)
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e) -> None:
        folder = self._target_folder(e.position().toPoint())
        if e.source() is self and folder and e.mimeData().hasFormat(MODULE_MIME):
            entry = bytes(e.mimeData().data(MODULE_MIME)).decode("utf-8")
            QTimer.singleShot(0, lambda: self.panel.file_module(entry, folder))
            e.setDropAction(Qt.CopyAction)
            e.accept()  # the panel rebuilds the tree; Qt must not move the item itself
        else:
            e.ignore()


ROLE = Qt.UserRole
STARTER_FOLDER, USER_FOLDER, PLUGIN_FOLDER = "starter", "user", "plugin"


class ModuleLibraryView(_DockPanel):
    """The module library: the starter folder, your own folders and plugins' folders, with search.

    Your folders live in the module library folder (set in Settings; ``Workspace.modules``): make,
    rename and delete them, and rename, move or delete the modules in them. Starter and
    plugin modules can be copied into your folders. Drag a module onto the patch bay, or
    double-click it, to add it to the strategy in front.
    """

    view_id = "module_library"
    title = "Module library"
    icon = "library"
    dock_area = "left"
    order = 110
    text = "Drag a module onto the patch bay, or double-click it. Right-click for folders."

    def build(self) -> None:
        self.search = SearchField("Search modules")
        self.search.textChanged.connect(self.set_filter)
        self.new_btn = button("", "ghost", "folder", "New folder")
        self.new_btn.clicked.connect(self.ask_new_folder)
        self.lay.addLayout(hbox(self.search, self.new_btn))
        self.tree = ModuleTree(self)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.lay.addWidget(self.tree, 1)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        self.lay.addWidget(self.error)
        self._open: set[str] = {STARTER}
        ws = self.workspace()
        if ws is not None:
            ws.library_changed.connect(self.refresh)
        theme.watch(self, lambda v: v.refresh())  # the folder and module icons
        self.refresh()

    def workspace(self):
        return self.ctx.workspace if self.ctx is not None else None

    # ---- the tree
    def refresh(self) -> None:
        ws = self.workspace()
        if self.tree.topLevelItemCount():
            self._open = {it.data(0, ROLE)[1] for it in self._folder_items() if it.isExpanded()}
        self.tree.clear()
        if ws is None:
            return
        groups = folders(ws.registry)
        mine = ws.modules.folders()
        for f in mine:
            groups.setdefault(f, [])
        order = sorted(groups, key=lambda f: (f != STARTER, f not in mine, f.lower()))
        pal = theme.current()
        for f in order:
            kind = STARTER_FOLDER if f == STARTER else USER_FOLDER if f in mine else PLUGIN_FOLDER
            item = QTreeWidgetItem([f.capitalize() if kind == STARTER_FOLDER else f])
            item.setData(0, ROLE, ("folder", f, kind))
            item.setIcon(0, icons.icon("folder", pal.text_muted, size=16))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled if kind == USER_FOLDER else Qt.ItemIsEnabled)
            item.setToolTip(0, {STARTER_FOLDER: "The app’s own modules. Copy one into your folders to change it.",
                                USER_FOLDER: "Your folder. Drop modules here to move them in.",
                                PLUGIN_FOLDER: "Added by a plugin."}[kind])
            self.tree.addTopLevelItem(item)
            for e in groups[f]:
                name = e.name.rpartition("/")[2]
                child = QTreeWidgetItem([name])
                child.setData(0, ROLE, ("module", e.name, e.plugin == USER))
                child.setIcon(0, icons.icon("module", pal.text_faint, size=16))
                child.setToolTip(0, e.doc or name)
                child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                item.addChild(child)
            item.setExpanded(f in self._open or f in mine)
        self.set_filter(self.search.text())

    def _folder_items(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def set_filter(self, text: str) -> None:
        """Show only modules whose name or description has ``text`` in it."""
        q = text.strip().lower()
        for folder in self._folder_items():
            shown = 0
            for i in range(folder.childCount()):
                child = folder.child(i)
                hit = not q or q in child.text(0).lower() or q in child.toolTip(0).lower()
                child.setHidden(not hit)
                shown += hit
            folder.setHidden(bool(q) and shown == 0)
            if q and shown:
                folder.setExpanded(True)

    def visible_modules(self) -> list[str]:
        return [f.child(i).data(0, ROLE)[1] for f in self._folder_items() if not f.isHidden()
                for i in range(f.childCount()) if not f.child(i).isHidden()]

    # ---- actions (each refreshes through Workspace.library_changed)
    def _try(self, fn) -> object:
        try:
            out = fn()
        except (ModuleFolderError, OSError, KeyError) as e:
            msg = e.args[0] if isinstance(e, (ModuleFolderError, KeyError)) and e.args else str(e)
            self.error.setText(str(msg)[:1].upper() + str(msg)[1:] + ".")
            self.error.show()
            return None
        self.error.hide()
        return True if out is None else out

    def new_folder(self, name: str):
        return self._try(lambda: self.workspace().modules.create_folder(name))

    def rename_folder(self, old: str, new: str):
        return self._try(lambda: self.workspace().modules.rename_folder(old, new))

    def delete_folder(self, name: str):
        return self._try(lambda: self.workspace().modules.delete_folder(name))

    def rename_module(self, entry: str, new: str):
        return self._try(lambda: self.workspace().modules.rename(entry, new))

    def move_module(self, entry: str, folder: str):
        return self._try(lambda: self.workspace().modules.move(entry, folder))

    def copy_module(self, entry: str, folder: str):
        return self._try(lambda: self.workspace().modules.copy_to(entry, folder))

    def file_module(self, entry: str, folder: str):
        """Put a module in one of your folders: yours move there, others are copied."""
        if self.workspace().modules.is_mine(entry):
            return self.move_module(entry, folder)
        return self.copy_module(entry, folder)

    def delete_module(self, entry: str):
        return self._try(lambda: self.workspace().modules.delete(entry))

    def add_to_strategy(self, entry: str) -> str | None:
        """Add a module to the strategy in front (the patch bay places it beside the others)."""
        ws = self.workspace()
        if ws is None or ws.focused_strategy not in ws.strategies:
            self.error.setText("Open a strategy first.")
            self.error.show()
            return None
        from ...core.patchbay import add_from_library

        new, m = add_from_library(ws.strategies.get(ws.focused_strategy), ws.registry, entry)
        ws.strategies.put(new.id, new)
        self.error.hide()
        return m.id

    # ---- asking
    def _ask(self, title: str, text: str = "") -> str | None:
        name, ok = QInputDialog.getText(self, title, "Name", text=text)
        return name.strip() if ok and name.strip() else None

    def ask_new_folder(self) -> None:
        name = self._ask("New folder")
        if name:
            self.new_folder(name)

    def _double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        kind, name, _ = item.data(0, ROLE)
        if kind == "module":
            self.add_to_strategy(name)

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        m = self.build_menu(item)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def build_menu(self, item: QTreeWidgetItem | None) -> QMenu:
        m = QMenu(self)
        mine = self.workspace().modules.folders() if self.workspace() is not None else []
        data = item.data(0, ROLE) if item is not None else None
        if data and data[0] == "module":
            entry, is_mine = data[1], data[2]
            folder = entry.rpartition("/")[0]
            m.addAction("Add to strategy", lambda: self.add_to_strategy(entry))
            m.addSeparator()
            others = [f for f in mine if f != folder]
            target = m.addMenu("Move to" if is_mine else "Copy to")
            for f in others:
                target.addAction(f, lambda f=f: self.file_module(entry, f))
            if others:
                target.addSeparator()
            target.addAction("New folder…", lambda: self._file_in_new_folder(entry))
            if is_mine:
                m.addAction("Copy to this folder", lambda: self.copy_module(entry, folder))
                m.addAction("Rename…", lambda: self._ask_rename_module(entry))
                m.addSeparator()
                m.addAction("Delete", lambda: self._confirm_delete_module(entry))
        elif data and data[0] == "folder" and data[2] == USER_FOLDER:
            name = data[1]
            m.addAction("Rename…", lambda: self._ask_rename_folder(name))
            d = m.addAction("Delete folder", lambda: self.delete_folder(name))
            d.setEnabled(not self.workspace().modules.modules(name))
            if not d.isEnabled():
                d.setToolTip("Move or delete its modules first")
            m.addSeparator()
            m.addAction("New folder…", self.ask_new_folder)
        else:
            m.addAction("New folder…", self.ask_new_folder)
        return m

    def _file_in_new_folder(self, entry: str) -> None:
        name = self._ask("New folder")
        if name and self.new_folder(name):
            self.file_module(entry, name)

    def _ask_rename_module(self, entry: str) -> None:
        name = self._ask("Rename module", entry.rpartition("/")[2])
        if name:
            self.rename_module(entry, name)

    def _ask_rename_folder(self, folder: str) -> None:
        name = self._ask("Rename folder", folder)
        if name:
            self.rename_folder(folder, name)

    def _confirm_delete_module(self, entry: str) -> None:
        name = entry.rpartition("/")[2]
        if QMessageBox.question(self, "Delete module", f"Delete “{name}” from your module library? "
                                "Strategies that use it keep their copy.") == QMessageBox.Yes:
            self.delete_module(entry)


class KnobsView(_DockPanel):
    """The knobs of the strategy in front: sliders for numbers, switches for true/false.

    Turning one changes the strategy's knob values through ``Workspace.strategies``.
    """

    view_id = "knobs"
    title = "Knobs"
    icon = "knob"
    dock_area = "right"
    order = 120
    text = "Put the cursor on a number in the code and press Ctrl+K to make it a knob."

    def build(self) -> None:
        self.controls: dict[str, KnobControl] = {}
        self._shape: list | None = None
        self.heading = label("No strategy open", "muted")
        self.reset_btn = button("Reset", "ghost", tip="Put every knob back to its default")
        self.reset_btn.clicked.connect(self.reset)
        self.lay.addLayout(hbox(self.heading, None, self.reset_btn))
        self.rows = QVBoxLayout()
        self.rows.setSpacing(S["sm"])
        self.lay.addLayout(self.rows)
        ws = self.ctx.workspace if self.ctx is not None else None
        if ws is not None:
            ws.strategy_focused.connect(lambda _id: self.refresh())
            ws.strategies.changed.connect(lambda id, _g: id == ws.focused_strategy and self.refresh())
            ws.strategies.removed.connect(lambda _id: self.refresh())
        self.refresh()

    def graph(self):
        ws = self.ctx.workspace if self.ctx is not None else None
        if ws is None or ws.focused_strategy not in ws.strategies:
            return None
        return ws.strategies.get(ws.focused_strategy)

    def refresh(self) -> None:
        g = self.graph()
        knobs = g.knobs() if g is not None else {}
        shape = [(g.id if g else None)] + [(k, kn.type, kn.lo, kn.hi, kn.step) for k, kn in knobs.items()]
        if shape != self._shape:  # rebuild only when the set of knobs changes, not while one is turned
            self._shape = shape
            while self.rows.count():
                w = self.rows.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            self.controls = {}
            names = {m.id: m.name for m in g.modules} if g is not None else {}
            for key, kn in knobs.items():
                mid, _, kname = key.partition(".")
                c = KnobControl(kname, kn.type.value, g.knob_value(key), kn.lo, kn.hi, kn.step, names.get(mid, mid))
                c.setToolTip(kn.doc or f"{key} (default {KnobControl.show(kn.default)})")
                c.changed.connect(lambda v, key=key: self.turn(key, v))
                self.controls[key] = c
                self.rows.addWidget(c)
        else:
            for key, c in self.controls.items():
                c.set_value(g.knob_value(key))
        if g is None:
            self.heading.setText("No strategy open")
        else:
            n = len(knobs)
            self.heading.setText(f"{g.name}: {n} knob{'s' * (n != 1)}" if n else f"{g.name}: no knobs yet")
        self.reset_btn.setEnabled(bool(g is not None and g.knob_values))

    def turn(self, key: str, value) -> None:
        g = self.graph()
        if g is None:
            return
        if value == g.knobs()[key].default:
            g.knob_values.pop(key, None)
        else:
            g.knob_values[key] = value
        self.ctx.workspace.strategies.put(g.id, g)

    def reset(self) -> None:
        g = self.graph()
        if g is not None and g.knob_values:
            g.knob_values.clear()
            self.ctx.workspace.strategies.put(g.id, g)


class TradeLogView(_DockPanel):
    """The trades of the last run of the strategy in front, newest run first. Close the
    dock to hide it; the Run view's Trade log button brings it back."""

    view_id = "trade_log"
    title = "Trade log"
    icon = "list"
    dock_area = "bottom"
    order = 130
    text = ""
    COLUMNS = ["Instrument", "Side", "Entry", "Entry price", "Exit", "Exit price", "Quantity", "Profit", "Costs", "Notes"]

    def build(self) -> None:
        self.heading = label("No run yet", "muted")
        self.lay.addLayout(hbox(self.heading, None))
        self.table = DataTable(self.COLUMNS, stretch=len(self.COLUMNS) - 1)
        self.table.setMinimumHeight(120)
        self.lay.addWidget(self.table, 1)
        self.record = None
        ws = self.ctx.workspace if self.ctx is not None else None
        if ws is not None:
            ws.strategy_focused.connect(lambda _id: self.refresh())
            ws.runs.added.connect(lambda _id, _r: self.refresh())
            ws.runs.changed.connect(lambda _id, _r: self.refresh())
        self.refresh()

    def last_run(self):
        ws = self.ctx.workspace if self.ctx is not None else None
        if ws is None or not ws.focused_strategy or ws.focused_strategy == DEFAULT_ID:
            return None
        recs = [r for r in ws.runs.records(ws.focused_strategy) if r.status != "failed"]
        return recs[-1] if recs else None

    def refresh(self) -> None:
        rec = self.last_run()
        if rec is self.record and rec is not None:
            return
        self.record = rec
        if rec is None:
            self.heading.setText("No run yet. Run the strategy to see its trades here.")
            self.table.set_rows([], [])
            return
        m = MARKETS.get(rec.market)
        local = (lambda t: t.astimezone(m.tz)) if m else (lambda t: t)
        cur = m.currency if m else ""
        rows, keys = [], []
        for i, t in enumerate(rec.trades):
            rows.append((t.instrument.split(":")[-1], "Long" if t.side > 0 else "Short",
                         f"{local(t.entry_time):%Y-%m-%d %H:%M}", f"{t.entry_price:.4g}",
                         f"{local(t.exit_time):%Y-%m-%d %H:%M}" if t.exit_time else "",
                         f"{t.exit_price:.4g}" if t.exit_price is not None else "",
                         f"{t.quantity:g}", f"{t.pnl:+,.2f}" if t.pnl is not None else "",
                         f"{t.cost:,.2f}", ", ".join(t.flags + ([t.reason] if t.reason else []))))
            keys.append(str(i))
        self.table.set_rows(rows, keys)
        n = len(rec.trades)
        status = "" if rec.status == "done" else f" ({rec.status})"
        self.heading.setText(f"{n} trade{'s' * (n != 1)} in the last run{status}, profits in {cur} after costs")
