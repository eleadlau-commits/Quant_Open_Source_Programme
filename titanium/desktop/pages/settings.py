"""Settings, tucked in the corner of the navigation rail.

Appearance works now. The Layout card shows where every view lives (page or dock)
and moves it. Libraries and plugins arrive in Phase 2G.
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QGridLayout

from ..design import theme
from ..design import tokens as T
from ..design.components import Card, badge, button, hbox, label
from ..views import DOCK, PAGE
from ._base import PageView

S = T.SPACE


class SettingsView(PageView):
    view_id = "settings"
    title = "Settings"
    icon = "settings"
    nav = False  # shown in the corner of the rail, not with the pages
    order = 900
    scroll = True

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.column.setSpacing(S["lg"])

        look = Card("Appearance", "Light, dark, or the same as the system.")
        form = QFormLayout()
        form.setHorizontalSpacing(S["xl"])
        self.theme_box = QComboBox()
        self.theme_box.setFixedWidth(260)
        for mode in theme.MODES:
            self.theme_box.addItem(theme.LABELS[mode], mode)
        if self.ctx is not None:
            saved = self.ctx.settings.value("view/theme", "system")
            self.theme_box.setCurrentIndex(max(0, list(theme.MODES).index(saved) if saved in theme.MODES else 0))
        self.theme_box.currentIndexChanged.connect(self._theme)
        form.addRow(label("Theme", "label"), self.theme_box)
        look.body.addLayout(form)
        self.column.addWidget(look)

        self.layout_card = Card("Layout", "Every panel can be a page or a dock. Pages fill the main area; "
                                          "docks sit beside the current page.")
        self.layout_grid = QGridLayout()
        self.layout_grid.setHorizontalSpacing(S["xl"])
        self.layout_grid.setVerticalSpacing(S["sm"])
        self.layout_card.body.addLayout(self.layout_grid)
        self.host_boxes: dict[str, QComboBox] = {}
        self.column.addWidget(self.layout_card)

        libs = Card("Libraries and plugins", "Module library folders, plugin manager, defaults for every run.")
        libs.add_action(badge("Phase 2", "neutral"))
        b1, b2 = button("Manage plugins", icon="library"), button("Module library folders", icon="folder")
        b1.setEnabled(False)
        b2.setEnabled(False)
        libs.body.addLayout(hbox(b1, b2, None))
        self.column.addWidget(libs)
        self.column.addStretch()

    def subtitle(self) -> str:
        return "Appearance, layout, libraries and plugins."

    def _theme(self, _i: int) -> None:
        mode = self.theme_box.currentData()
        if self.ctx is not None:
            self.ctx.settings.setValue("view/theme", mode)
            self.ctx.theme_changed.emit(mode)

    def show_layout(self, shell) -> None:
        """Fill the Layout card from the shell (called once the window exists, and on every move)."""
        while self.layout_grid.count():
            w = self.layout_grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.host_boxes.clear()
        for r, spec in enumerate(shell.registry.specs()):
            self.layout_grid.addWidget(label(spec.title), r, 0)
            box = QComboBox()
            box.addItem("Page", PAGE)
            box.addItem("Dock", DOCK)
            box.setCurrentIndex(0 if shell.hosts[spec.view_id] == PAGE else 1)
            box.setFixedWidth(140)
            box.currentIndexChanged.connect(lambda _i, v=spec.view_id, b=box: shell.move_view(v, b.currentData()))
            self.layout_grid.addWidget(box, r, 1)
            where = ", ".join(p.title() for p in spec.pages) if spec.pages else "every page"
            self.layout_grid.addWidget(label(f"as a dock, shows on {where}", "caption"), r, 2)
            self.host_boxes[spec.view_id] = box
        self.layout_grid.setColumnStretch(2, 1)
