"""Shared layout for page-style views: a scrollable column with the standard margins."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject
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


class WhenShown(QObject):
    """``fn`` now if ``widget`` is on screen, otherwise once it is next shown.

    For pages that follow the workspace: a page nobody is looking at needn't redraw on
    every change (a knob dragged on the Strategies page changes the strategy many times a
    second); it catches up, once, just before it appears. Call it like ``fn``; arguments
    are dropped.
    """

    def __init__(self, widget: QWidget, fn: Callable[[], None]):
        super().__init__(widget)
        self.widget, self.fn = widget, fn
        self.dirty = False
        widget.installEventFilter(self)

    def __call__(self, *_args) -> None:
        if self.widget.isVisible():
            self.dirty = False
            self.fn()
        else:
            self.dirty = True

    def eventFilter(self, obj, event) -> bool:
        if obj is self.widget and event.type() == QEvent.Show and self.dirty:
            self.dirty = False
            self.fn()
        return False
