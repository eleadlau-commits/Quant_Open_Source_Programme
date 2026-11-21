"""Data page: the datasets strategies run on. Built out in Phase 1A."""
from __future__ import annotations

from ..design.components import Card, EmptyState, Segmented, badge, button, hbox, label
from ..design import tokens as T
from ._base import PageView

KINDS = (
    ("Core", "Prices of the instruments strategies trade.", "brand"),
    ("Complementary", "Data known over time: news, events, fundamentals.", "primary"),
    ("Generated", "Made from other data by generators: features, indicators.", "neutral"),
)


class DataView(PageView):
    view_id = "data"
    title = "Data"
    icon = "data"
    order = 10

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        row = hbox(spacing=T.SPACE["lg"])
        self.kind_cards = []
        for name, text, kind in KINDS:
            card = Card()
            card.body.setSpacing(T.SPACE["xs"])
            card.body.addLayout(hbox(label(name, "title"), None, badge("0 datasets", kind)))
            card.body.addWidget(label(text, "muted", wrap=True))
            row.addWidget(card, 1)
            self.kind_cards.append(card)
        self.column.addLayout(row)
        self.filter = Segmented(["All", "Core", "Complementary", "Generated"])
        self.column.addLayout(hbox(self.filter, None))
        self.empty = EmptyState(
            "data", "No datasets yet",
            "A dataset records where its data comes from, what it holds, where it is stored, "
            "and which strategies use it.",
            [button("Add dataset", "primary", "plus"), button("Import files", icon="import")])
        self.column.addWidget(self.empty, 1)

    def subtitle(self) -> str:
        return "Where data comes from, what it holds, where it is stored, and who uses it."

    def actions_bar(self):
        return [button("Import files", icon="import"), button("Add dataset", "primary", "plus")]
