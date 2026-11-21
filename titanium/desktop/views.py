"""Views: every panel in the app, hostable as a page or a dock.

A view is a self-contained widget that talks only to the app layer. Where it is
shown (a page in the main area, or a dock beside the current page) is layout,
chosen by the user and remembered in settings, never written into the view.

Docked views can belong to pages (``pages``): the Knobs dock only shows on the
Strategies page, for example. A view with no ``pages`` shows everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStackedWidget, QWidget

PAGE, DOCK = "page", "dock"
MODULE_MIME = "application/x-titanium-module"  # a module library entry name, dragged onto the patch bay


class PageStack(QStackedWidget):
    """A stack whose size needs are those of the page in front. A plain QStackedWidget
    asks for room for its largest page even while that page is hidden, which made the
    whole window wider than a small screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def sizeHint(self) -> QSize:
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()


class View(QWidget):
    """Base class for every panel. Subclasses set the class attributes below."""

    view_id: str = ""
    title: str = ""
    icon: str = "page"
    default_host: str = PAGE
    pages: tuple[str, ...] = ()  # when docked: the pages it belongs to (empty = all)
    nav: bool = True  # when a page: listed in the navigation rail
    order: int = 100  # position in the navigation rail
    starts_hidden: bool = False  # when docked: hidden until shown (a pop-out of something a page already has)

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(parent)
        self.ctx = app_ctx

    def actions_bar(self) -> list[QWidget]:
        """Widgets this view puts in the page header when shown as a page."""
        return []

    def subtitle(self) -> str:
        return ""


@dataclass
class ViewSpec:
    view_id: str
    factory: Callable[..., View]
    default_host: str
    title: str
    icon: str
    pages: tuple[str, ...] = ()
    nav: bool = True
    order: int = 100
    extra: dict = field(default_factory=dict)
    starts_hidden: bool = False


class ViewRegistry:
    """Which views exist. The shell asks it what to build; plugins may add views later."""

    def __init__(self) -> None:
        self._specs: dict[str, ViewSpec] = {}

    def add(self, cls: type[View]) -> type[View]:
        if not cls.view_id:
            raise ValueError(f"{cls.__name__} has no view_id")
        if cls.view_id in self._specs:
            raise ValueError(f"view {cls.view_id!r} registered twice")
        self._specs[cls.view_id] = ViewSpec(cls.view_id, cls, cls.default_host, cls.title, cls.icon,
                                            cls.pages, cls.nav, cls.order,
                                            starts_hidden=getattr(cls, "starts_hidden", False))
        return cls

    def specs(self) -> list[ViewSpec]:
        return sorted(self._specs.values(), key=lambda s: (s.order, s.title))

    def spec(self, view_id: str) -> ViewSpec:
        return self._specs[view_id]
