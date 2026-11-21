"""Shared layout for page-style views: a scrollable column with the standard margins."""
from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ..design import tokens as T
from ..views import View

S = T.SPACE


class PageView(View):
    """A view laid out as a column. Add widgets to ``self.column``."""

    scroll = False

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        self.column = QVBoxLayout(inner)
        self.column.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        self.column.setSpacing(S["lg"])
        if self.scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(inner)
            outer.addWidget(area)
        else:
            outer.addWidget(inner)
