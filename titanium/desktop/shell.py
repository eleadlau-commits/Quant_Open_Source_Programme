"""The main window: navigation rail, page header, pages in the middle, docks around them.

The shell knows nothing about what a view does. It asks the view registry what
exists, hosts each view as a page or a dock (as the saved layout says), and moves
views between the two on request.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDockWidget, QHBoxLayout, QMainWindow, QMenu, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from .context import AppContext
from .design import icons, theme
from .design import tokens as T
from .design.components import Logo, label, paint_nav_marker
from .views import DOCK, PAGE, PageStack, View, ViewRegistry

S = T.SPACE
_AREAS = {"left": Qt.LeftDockWidgetArea, "right": Qt.RightDockWidgetArea, "bottom": Qt.BottomDockWidgetArea}


class NavButton(QToolButton):
    def __init__(self, view_id: str, title: str, icon: str):
        super().__init__()
        self.view_id, self.icon_name = view_id, icon
        self.setText(title)
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(22, 22))
        self.setFixedSize(T.NAV_WIDTH - 2 * S["sm"], 60)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(title)
        self.retheme()
        theme.watch(self, NavButton.retheme)

    def retheme(self):
        p = theme.current()
        self.setIcon(icons.icon(self.icon_name, p.text_muted, p.text, size=22))

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_nav_marker(self)  # the skin's active-page marker, if it has one


class DockTitle(QWidget):
    """A dock's title bar: its name, and buttons to make it a page or close it."""

    def __init__(self, dock: "ViewDock"):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S["md"], S["xs"], S["xs"], S["xs"])
        lay.setSpacing(S["xxs"])
        self.name = label(dock.view.title.upper(), "overline")
        lay.addWidget(self.name)
        lay.addStretch()
        self.to_page = QToolButton()
        self.to_page.setToolTip("Show as a page")
        self.to_page.clicked.connect(lambda: dock.shell.move_view(dock.view.view_id, PAGE))
        self.close_btn = QToolButton()
        self.close_btn.setToolTip("Hide")
        self.close_btn.clicked.connect(dock.hide_by_user)
        for b in (self.to_page, self.close_btn):
            b.setIconSize(QSize(14, 14))
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        self.retheme()
        theme.watch(self, DockTitle.retheme)

    def retheme(self):
        p = theme.current()
        self.to_page.setIcon(icons.icon("page", p.text_muted, size=14))
        self.close_btn.setIcon(icons.icon("close", p.text_muted, size=14))


class ViewDock(QDockWidget):
    def __init__(self, shell: "MainWindow", view: View):
        super().__init__(view.title)
        self.shell, self.view = shell, view
        self.setObjectName(f"dock_{view.view_id}")
        self.setWidget(view)
        self.setTitleBarWidget(DockTitle(self))
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.user_hidden = False

    def hide_by_user(self):
        self.user_hidden = True
        self.hide()
        self.shell._save_hidden()
        self.shell._announce_panels()


class PageHeader(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("PageHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S["xl"], S["lg"], S["xl"], S["lg"])
        lay.setSpacing(S["sm"])
        col = QVBoxLayout()
        col.setSpacing(S["xxs"])
        self.title = label("", "heading")
        self.subtitle = label("", "muted", wrap=True)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        lay.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(S["sm"])
        lay.addLayout(self.actions)

    def show_view(self, view: View):
        self.title.setText(view.title)
        sub = view.subtitle()
        self.subtitle.setText(sub)
        self.subtitle.setVisible(bool(sub))
        while self.actions.count():
            w = self.actions.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
        for w in view.actions_bar():
            self.actions.addWidget(w)


class MainWindow(QMainWindow):
    @staticmethod
    def _first_size():
        """1440 x 900, or most of the screen when the screen is smaller than that."""
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QSize(1440, 900)
        room = screen.availableGeometry().size()
        return QSize(min(1440, int(room.width() * 0.92)), min(900, int(room.height() * 0.9)))

    def __init__(self, registry: ViewRegistry, ctx: AppContext):
        super().__init__()
        self.registry, self.ctx = registry, ctx
        self.setWindowTitle("Titanium")
        self.resize(self._first_size())
        self.views: dict[str, View] = {}
        self.hosts: dict[str, str] = {}
        self.docks: dict[str, ViewDock] = {}
        self.current: str | None = None

        saved = self._saved_hosts()
        for spec in registry.specs():
            self.views[spec.view_id] = spec.factory(ctx)
            host = saved.get(spec.view_id, spec.default_host)
            self.hosts[spec.view_id] = host if host in (PAGE, DOCK) else spec.default_host

        # ---- navigation rail
        self.rail = QWidget()
        self.rail.setObjectName("NavRail")
        self.rail.setAttribute(Qt.WA_StyledBackground, True)
        self.rail.setFixedWidth(T.NAV_WIDTH)
        self.rail_lay = QVBoxLayout(self.rail)
        self.rail_lay.setContentsMargins(S["sm"], S["lg"], S["sm"], S["lg"])
        self.rail_lay.setSpacing(S["xs"])
        self.rail_lay.addWidget(Logo(36), 0, Qt.AlignHCenter)
        self.rail_lay.addSpacing(S["lg"])
        self.nav_box = QVBoxLayout()
        self.nav_box.setSpacing(S["xs"])
        self.rail_lay.addLayout(self.nav_box)
        self.rail_lay.addStretch()
        self.corner_box = QVBoxLayout()
        self.rail_lay.addLayout(self.corner_box)
        self.panels_button = NavButton("panels", "Panels", "dock")
        self.panels_button.setCheckable(False)
        self.panels_button.setToolTip("Show or hide panels (docks), and choose where each view lives")
        self.panels_button.clicked.connect(self.show_panels_menu)
        self.corner_box.addWidget(self.panels_button, 0, Qt.AlignHCenter)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, NavButton] = {}

        # ---- centre: header over the page stack
        self.header = PageHeader()
        self.stack = PageStack()
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.header)
        cl.addWidget(self.stack, 1)

        # docks live in an inner main window, so they sit beside the pages, never beside the rail
        self.dock_host = QMainWindow()
        self.dock_host.setWindowFlags(Qt.Widget)
        self.dock_host.setDockNestingEnabled(True)
        self.dock_host.setCentralWidget(centre)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self.rail)
        bl.addWidget(self.dock_host, 1)
        self.setCentralWidget(body)

        self._hidden = set(self._saved_hidden())
        for spec in registry.specs():
            if self.hosts[spec.view_id] == PAGE:
                self._add_page(spec.view_id)
            else:
                self._add_dock(spec.view_id)
        self.statusBar().showMessage("Ready")
        self.statusBar().addPermanentWidget(label("Results that survive tests are not evidence of future profit.", "caption"))

        ctx.open_page.connect(self.show_page)
        first = next((s.view_id for s in registry.specs() if self.hosts[s.view_id] == PAGE and s.nav), None)
        if first:
            self.show_page(first)

    # ---- layout persistence
    def _saved_hosts(self) -> dict[str, str]:
        raw = self.ctx.settings.value("layout/hosts", "")
        try:
            return json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            return {}

    def _save_hosts(self) -> None:
        self.ctx.settings.setValue("layout/hosts", json.dumps(self.hosts, sort_keys=True))

    def _saved_hidden(self) -> list[str]:
        raw = self.ctx.settings.value("layout/hidden", "")
        if not raw:  # nothing saved yet: pop-outs start hidden
            return [s.view_id for s in self.registry.specs() if s.starts_hidden]
        try:
            out = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [v for v in out if isinstance(v, str)] if isinstance(out, list) else []

    def _save_hidden(self) -> None:
        self._hidden = {v for v, d in self.docks.items() if d.user_hidden}
        self.ctx.settings.setValue("layout/hidden", json.dumps(sorted(self._hidden)))

    # ---- the Panels menu: show and hide every dock
    def panels_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        docks = [s for s in self.registry.specs() if self.hosts[s.view_id] == DOCK]
        if docks:
            menu.addSection("Panels")
        for spec in docks:
            dock = self.docks[spec.view_id]
            where = ", ".join(self.registry.spec(p).title for p in spec.pages if p in self.views) or "every page"
            act = menu.addAction(spec.title)
            act.setCheckable(True)
            act.setChecked(not dock.user_hidden)
            act.setToolTip(f"Shows on {where}")
            act.setData(spec.view_id)
            act.toggled.connect(lambda on, v=spec.view_id: self.set_panel_shown(v, on))
        menu.addSeparator()
        menu.addAction("Where each view lives…", lambda: self.show_page("settings"))
        return menu

    def show_panels_menu(self) -> None:
        menu = self.panels_menu()
        menu.exec(self.panels_button.mapToGlobal(self.panels_button.rect().topRight()))

    def set_panel_shown(self, view_id: str, shown: bool) -> None:
        """Show a dock (going to a page it belongs on if this one isn't) or hide it, and remember."""
        dock = self.docks.get(view_id)
        if dock is None:
            return
        if not shown:
            dock.hide_by_user()
            return
        dock.user_hidden = False
        pages = [p for p in self.registry.spec(view_id).pages if self.hosts.get(p) == PAGE]
        if pages and self.current not in pages:
            self.show_page(pages[0])
        self._sync_docks()
        dock.raise_()
        self._save_hidden()

    # ---- pages
    def _add_page(self, view_id: str) -> None:
        spec, view = self.registry.spec(view_id), self.views[view_id]
        self.stack.addWidget(view)
        corner = view_id == "settings"
        if spec.nav or corner:
            btn = NavButton(view_id, spec.title, spec.icon)
            btn.clicked.connect(lambda _=False, v=view_id: self.show_page(v))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, b=btn: self._nav_menu(b, pos))
            self.nav_group.addButton(btn)
            self.nav_buttons[view_id] = btn
            (self.corner_box if corner else self.nav_box).addWidget(btn, 0, Qt.AlignHCenter)

    def _remove_page(self, view_id: str) -> None:
        self.stack.removeWidget(self.views[view_id])
        btn = self.nav_buttons.pop(view_id, None)
        if btn is not None:
            self.nav_group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()

    def _nav_menu(self, btn: NavButton, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Show as a dock", lambda: self.move_view(btn.view_id, DOCK))
        menu.exec(btn.mapToGlobal(pos))

    def show_page(self, view_id: str) -> None:
        if self.hosts.get(view_id) != PAGE:
            dock = self.docks.get(view_id)
            if dock:
                dock.user_hidden = False
                dock.show()
                dock.raise_()
                self._save_hidden()
                self._announce_panels()
            return
        view = self.views[view_id]
        self.current = view_id
        self.stack.setCurrentWidget(view)
        self.header.show_view(view)
        if view_id in self.nav_buttons:
            self.nav_buttons[view_id].setChecked(True)
        self._sync_docks()

    # ---- docks
    def _add_dock(self, view_id: str) -> None:
        view = self.views[view_id]
        dock = ViewDock(self, view)
        dock.user_hidden = view_id in getattr(self, "_hidden", set())
        area = _AREAS.get(getattr(view, "dock_area", "right"), Qt.RightDockWidgetArea)
        self.dock_host.addDockWidget(area, dock)
        self.docks[view_id] = dock
        self._sync_docks()

    def _remove_dock(self, view_id: str) -> None:
        dock = self.docks.pop(view_id)
        dock.setWidget(None)
        self.dock_host.removeDockWidget(dock)
        dock.deleteLater()

    def _sync_docks(self) -> None:
        """Show each dock only on the pages it belongs to (and not if the user hid it)."""
        for view_id, dock in self.docks.items():
            pages = self.registry.spec(view_id).pages
            wanted = (not pages or self.current in pages) and not dock.user_hidden
            dock.setVisible(wanted)
        self._announce_panels()

    def panel_open(self, view_id: str) -> bool:
        """Whether a view is out as a dock the person wants (or is a page): pages hide their copy then."""
        if self.hosts.get(view_id) == PAGE:
            return True
        dock = self.docks.get(view_id)
        return dock is not None and not dock.user_hidden

    def _announce_panels(self) -> None:
        for view_id in self.views:
            now = self.panel_open(view_id)
            if self.ctx.panels.get(view_id) != now:
                self.ctx.panels[view_id] = now
                self.ctx.panel_open.emit(view_id, now)

    # ---- moving a view between page and dock
    def move_view(self, view_id: str, host: str) -> None:
        if host not in (PAGE, DOCK) or self.hosts[view_id] == host:
            return
        view = self.views[view_id]
        if host == DOCK:
            if view_id == self.current:
                self._remove_page(view_id)
                fallback = next((v for v, h in self.hosts.items() if h == PAGE and v != view_id
                                 and self.registry.spec(v).nav), None)
                self.current = None
                self.hosts[view_id] = DOCK
                self._add_dock(view_id)
                if fallback:
                    self.show_page(fallback)
            else:
                self._remove_page(view_id)
                self.hosts[view_id] = DOCK
                self._add_dock(view_id)
            self.docks[view_id].user_hidden = False
            self.docks[view_id].show()
        else:
            self._remove_dock(view_id)
            self.hosts[view_id] = PAGE
            self._add_page(view_id)
            view.show()
            self.show_page(view_id)
        self._save_hosts()
        self._save_hidden()
        self.ctx.layout_changed.emit(view_id, host)
