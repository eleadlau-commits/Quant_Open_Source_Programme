"""A strategy's knobs and trade log, as panels that belong to one strategy.

Each strategy tab's Run view holds its own (``strategy_id`` set). The Knobs and Trade log
docks are the pop-outs: the same panels following the strategy tab in front
(``strategy_id`` left ``None``), for more room or for knobs beside the code.
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...core.baseline import DEFAULT_ID
from ...core.markets import MARKETS
from ..design import tokens as T
from ..design.components import DataTable, KnobControl, button, hbox, label

S = T.SPACE


class _StrategyPanel(QWidget):
    def __init__(self, workspace=None, strategy_id: str | None = None, parent=None):
        super().__init__(parent)
        self.workspace, self.strategy_id = workspace, strategy_id
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(S["sm"])

    @property
    def target(self) -> str | None:
        """The strategy shown: this panel's own, or the tab in front."""
        ws = self.workspace
        if ws is None:
            return None
        return self.strategy_id if self.strategy_id is not None else ws.focused_strategy

    def _mine(self, sid) -> bool:
        return sid == self.target


class KnobsPanel(_StrategyPanel):
    """Sliders for number knobs, switches for true/false ones. Turning one changes the
    strategy's knob values through ``Workspace.strategies``."""

    def __init__(self, workspace=None, strategy_id: str | None = None, parent=None):
        super().__init__(workspace, strategy_id, parent)
        self.controls: dict[str, KnobControl] = {}
        self._shape: list | None = None
        self.heading = label("No strategy open", "muted")
        self.reset_btn = button("Reset", "ghost", tip="Put every knob back to its default")
        self.reset_btn.clicked.connect(self.reset)
        self.lay.addLayout(hbox(self.heading, None, self.reset_btn))
        self.rows = QVBoxLayout()
        self.rows.setSpacing(S["sm"])
        self.lay.addLayout(self.rows)
        ws = workspace
        if ws is not None:
            if strategy_id is None:
                ws.strategy_focused.connect(self._refresh_any)
            ws.strategies.changed.connect(self._changed)
            ws.strategies.removed.connect(self._refresh_any)
        self.refresh()

    def detach(self) -> None:
        ws = self.workspace
        if ws is not None:
            if self.strategy_id is None:
                ws.strategy_focused.disconnect(self._refresh_any)
            ws.strategies.changed.disconnect(self._changed)
            ws.strategies.removed.disconnect(self._refresh_any)

    def _refresh_any(self, *_):
        self.refresh()

    def _changed(self, sid, _graph):
        if self._mine(sid):
            self.refresh()

    def graph(self):
        ws, sid = self.workspace, self.target
        if ws is None or sid not in ws.strategies:
            return None
        return ws.strategies.get(sid)

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
        self.workspace.strategies.put(g.id, g)

    def reset(self) -> None:
        g = self.graph()
        if g is not None and g.knob_values:
            g.knob_values.clear()
            self.workspace.strategies.put(g.id, g)


class TradeLogPanel(_StrategyPanel):
    """The trades of the strategy's last run."""

    COLUMNS = ["Instrument", "Side", "Entry", "Entry price", "Exit", "Exit price", "Quantity", "Profit", "Costs", "Notes"]

    def __init__(self, workspace=None, strategy_id: str | None = None, parent=None):
        super().__init__(workspace, strategy_id, parent)
        self.heading = label("No run yet", "muted")
        self.lay.addLayout(hbox(self.heading, None))
        self.table = DataTable(self.COLUMNS, stretch=len(self.COLUMNS) - 1)
        self.table.setMinimumHeight(160)
        self.lay.addWidget(self.table, 1)
        self.record = None
        ws = workspace
        if ws is not None:
            if strategy_id is None:
                ws.strategy_focused.connect(self._refresh_any)
            ws.runs.added.connect(self._refresh_any)
            ws.runs.changed.connect(self._refresh_any)
        self.refresh()

    def detach(self) -> None:
        ws = self.workspace
        if ws is not None:
            if self.strategy_id is None:
                ws.strategy_focused.disconnect(self._refresh_any)
            ws.runs.added.disconnect(self._refresh_any)
            ws.runs.changed.disconnect(self._refresh_any)

    def _refresh_any(self, *_):
        self.refresh()

    def last_run(self):
        ws, sid = self.workspace, self.target
        if ws is None or not sid or sid == DEFAULT_ID:
            return None
        recs = [r for r in ws.runs.records(sid) if r.status != "failed"]
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
