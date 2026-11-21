"""Backtests page: every test for every strategy. Built out in Phase 2F."""
from __future__ import annotations

from ..design.components import EmptyState, button
from ._base import PageView


class BacktestsView(PageView):
    view_id = "backtests"
    title = "Backtests"
    icon = "backtests"
    order = 40

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.column.addWidget(EmptyState(
            "backtests", "No backtests run yet",
            "Tests ask whether a result holds up: out-of-sample, bootstrap, cost stress and more. "
            "Nothing runs by itself: run one, a selection, or all of them."), 1)

    def subtitle(self) -> str:
        return "Does the result hold up? A pass means it survived that test, never that it will make money."

    def actions_bar(self):
        sel, all_ = button("Run selected"), button("Run all", "primary", "play")
        sel.setEnabled(False)
        all_.setEnabled(False)
        return [button("Backtest library", icon="library"), sel, all_]
