"""Panels that start as docks on the Strategies page. Filled in by Phases 2D and 2E."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from ..design import tokens as T
from ...core.baseline import DEFAULT_ID
from ...core.markets import MARKETS
from ..design.components import DataTable, KnobControl, SearchField, button, hbox, label
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
        if self.text:
            self.lay.addWidget(label(self.text, "caption", wrap=True))
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
