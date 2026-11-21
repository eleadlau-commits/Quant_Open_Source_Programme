"""Panels that start as docks on the Strategies page. Filled in by Phases 2D and 2E."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from ..design import tokens as T
from ..design.components import SearchField, label
from ..views import DOCK, View

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
        note = label(self.text, "caption", wrap=True)
        self.lay.addWidget(note)
        self.lay.addStretch()

    def build(self) -> None:
        pass


class ModuleLibraryView(_DockPanel):
    view_id = "module_library"
    title = "Module library"
    icon = "library"
    dock_area = "left"
    order = 110
    text = "Starter modules in their own folder, and your modules grouped into folders. Drag one onto the patch bay."

    def build(self) -> None:
        self.lay.addWidget(SearchField("Search modules"))


class KnobsView(_DockPanel):
    view_id = "knobs"
    title = "Knobs"
    icon = "knob"
    dock_area = "right"
    order = 120
    text = "Real, whole-number and true/false values made into knobs. Turning one reruns and redraws the graph."


class TradeLogView(_DockPanel):
    view_id = "trade_log"
    title = "Trade log"
    icon = "list"
    dock_area = "bottom"
    order = 130
    text = "Every entry and exit of the last run. Hide it when you need the room."
