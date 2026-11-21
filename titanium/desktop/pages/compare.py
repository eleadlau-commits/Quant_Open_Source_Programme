"""Compare page: runs side by side, one tab per measurement. Built out in Phase 2F."""
from __future__ import annotations

from PySide6.QtWidgets import QTabWidget

from ..design.components import EmptyState, button
from ._base import PageView


class CompareView(PageView):
    view_id = "compare"
    title = "Compare"
    icon = "compare"
    order = 30

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(EmptyState("compare", "Nothing to compare yet",
                                    "Run a strategy and it appears here. Tick strategies to compare them, "
                                    "show the default strategy, and zoom in time."), "Profit")
        self.column.addWidget(self.tabs, 1)

    def subtitle(self) -> str:
        return "Strategies side by side, one tab per measurement from the measurement library."

    def actions_bar(self):
        b = button("Measurement library", icon="library")
        b.setEnabled(False)
        return [b]
