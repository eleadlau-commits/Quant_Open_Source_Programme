"""Run settings of a strategy, in the Run view: what its runs use and where each value comes from.

Every value resolves in layers (``core/layers.py``): the app's defaults, then the traded
market's, then the strategy's own. Changing a value here saves it with the strategy (an
override); "Use default" drops the override so the market's or the app's value applies again.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTime, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QTimeEdit, QWidget

from ...app.settings import EVERY, RunDefaults
from ...core.layers import layer_of, merge_settings
from ...core.markets import NASDAQ, Market
from ..design import tokens as T
from ..design.components import Card, Segmented, Switch, button, hbox, label
from ..market_text import hours_text

S = T.SPACE
FIELD_WIDTH = 200


def _number(lo: float, hi: float, decimals: int, step: float, suffix: str, tip: str = "") -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setFixedWidth(FIELD_WIDTH)
    w.setDecimals(decimals)
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    w.setGroupSeparatorShown(True)
    if tip:
        w.setToolTip(tip)
    return w


def resolve(workspace, graph) -> tuple[Market, list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    """The strategy's market, its layers (app, market, strategy) and the merged result."""
    settings = dict(getattr(graph, "settings", None) or {})
    ids = settings.get("datasets") or []
    ds = settings.get("dataset") or (ids[0] if ids else None)
    market = NASDAQ
    if workspace is not None:
        markets = workspace.markets()
        if ds and ds in workspace.datasets:
            market = markets.get(workspace.datasets.get(ds).market, market)
        else:
            market = markets.get(market.id, market)
    app = (workspace.run_defaults if workspace is not None else RunDefaults()).engine_settings()
    layers = [("app", app), ("market", market.defaults.settings()), ("strategy", settings)]
    return market, layers, merge_settings(*[layer for _n, layer in layers])


def summary(market: Market, cfg: dict[str, Any]) -> str:
    """"Nasdaq, regular hours (09:30–16:00), decides 15:50"."""
    at = cfg.get("decide_at", market.defaults.decide_at)
    at = ", ".join(at) if isinstance(at, (list, tuple)) else at
    every = {"week": " weekly", "month": " monthly"}.get(cfg.get("every", "day"), "")
    return f"{market.short}, {hours_text(market, bool(cfg.get('extended_hours')))}, decides {at}{every}"


class RunSettings(Card):
    """Each setting a run of this strategy uses, its source, and an override."""

    changed = Signal()  # the strategy's settings were changed here

    def __init__(self, parent=None):
        super().__init__("Run settings", "What this strategy's runs use: the app's defaults, then the market's, "
                                         "then this strategy's own. Change one to set it for this strategy only.",
                         parent=parent)
        self.graph = None
        self.workspace = None
        self.market: Market = NASDAQ
        self.layers: list = []
        self.cfg: dict[str, Any] = {}
        self.every_keys = list(EVERY)
        self.editors: dict[str, QWidget] = {}
        self.sources: dict[str, Any] = {}
        self.resets: dict[str, Any] = {}
        self.rows: dict[str, list[QWidget]] = {}
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(S["lg"])
        self.grid.setVerticalSpacing(S["sm"])
        self.grid.setColumnStretch(3, 1)
        self.body.addLayout(self.grid)

        every = Segmented(["Day", "Week", "Month"])
        decide_at = QTimeEdit()
        decide_at.setDisplayFormat("HH:mm")
        decide_at.setFixedWidth(FIELD_WIDTH)
        specs = [
            ("capital", "Capital", _number(1, 1e12, 0, 10_000, "", "Notional starting cash, in the market's currency")),
            ("every", "Decides", every),
            ("decide_at", "At", decide_at),
            ("extended_hours", "All sessions", Switch(tip="Trade outside the regular session too")),
            ("max_gross", "Exposure cap", _number(1, 1000, 0, 10, " %", "Most it may hold, as a share of equity")),
            ("min_trade", "Smallest trade", _number(0, 99, 2, 0.1, " %", "Skip trades smaller than this share of equity")),
            ("costs.equity.half_spread_bps", "Stock half spread", _number(0, 1000, 2, 0.5, " bps")),
            ("costs.equity.slippage_bps", "Stock slippage", _number(0, 1000, 2, 0.5, " bps")),
            ("costs.equity.commission_per_share", "Stock commission", _number(0, 10, 4, 0.001, " per share")),
            ("costs.futures.commission_per_side", "Futures commission", _number(0, 100, 2, 0.05, " per side")),
            ("costs.futures.slippage_ticks", "Futures slippage", _number(0, 100, 1, 0.5, " ticks")),
        ]
        for r, (key, text, editor) in enumerate(specs):
            name = label(text, "label")
            source = label("", "caption")
            reset = button("Use default", "ghost", tip="Drop this strategy's own value")
            reset.clicked.connect(lambda _=False, k=key: self.use_default(k))
            self.grid.addWidget(name, r, 0)
            self.grid.addWidget(editor, r, 1)
            self.grid.addLayout(hbox(source, reset, None), r, 2, 1, 2)
            self.editors[key], self.sources[key], self.resets[key] = editor, source, reset
            self.rows[key] = [name, editor, source, reset]
            self._connect(key, editor)

    # ---- showing ---------------------------------------------------------------------
    def set_strategy(self, workspace, graph) -> None:
        self.workspace, self.graph = workspace, graph
        self.market, self.layers, self.cfg = resolve(workspace, graph)
        names = {"app": "App default", "market": f"{self.market.short} default", "strategy": "This strategy"}
        for key, editor in self.editors.items():
            kind = key.split(".")[1] if key.startswith("costs.") else None
            visible = kind is None or self.market.trades({"equity": "stock", "futures": "future"}[kind])
            for w in self.rows[key]:
                w.setVisible(visible)
            value = self.value(key)
            editor.blockSignals(True)
            self._show(key, editor, value)
            editor.blockSignals(False)
            where = layer_of(key, *self.layers)
            self.sources[key].setText(names.get(where, "Engine default"))
            self.resets[key].setVisible(where == "strategy")

    def value(self, key: str) -> Any:
        v: Any = self.cfg
        for part in key.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        return v

    def _show(self, key: str, editor, value) -> None:
        if key == "every":
            editor.group.button(self.every_keys.index(value if value in self.every_keys else "day")).setChecked(True)
        elif key == "decide_at":
            at = value[0] if isinstance(value, (list, tuple)) else (value or "15:50")
            editor.setTime(QTime.fromString(str(at), "HH:mm"))
        elif key == "extended_hours":
            editor.setChecked(bool(value))
            editor.update()
        elif key in ("max_gross", "min_trade"):
            editor.setValue(float(value if value is not None else (1.0 if key == "max_gross" else 0.0)) * 100)
        else:
            editor.setValue(float(value or 0))

    # ---- changing ----------------------------------------------------------------------
    def _connect(self, key: str, editor) -> None:
        if key == "every":
            editor.changed.connect(lambda i, k=key: self.set_value(k, self.every_keys[i]))
        elif key == "decide_at":
            editor.timeChanged.connect(lambda t, k=key: self.set_value(k, t.toString("HH:mm")))
        elif key == "extended_hours":
            editor.toggled.connect(lambda on, k=key: self.set_value(k, bool(on)))
        elif key in ("max_gross", "min_trade"):
            editor.valueChanged.connect(lambda v, k=key: self.set_value(k, round(v / 100, 6)))
        else:
            editor.valueChanged.connect(lambda v, k=key: self.set_value(k, v))

    def set_value(self, key: str, value: Any) -> None:
        """Save ``value`` as this strategy's own setting."""
        if self.graph is None:
            return
        parts = key.split(".")
        target = self.graph.settings
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
        self._save()

    def use_default(self, key: str) -> None:
        """Drop this strategy's own value of ``key``."""
        if self.graph is None:
            return
        parts = key.split(".")
        chain = [self.graph.settings]
        for part in parts[:-1]:
            nxt = chain[-1].get(part)
            if not isinstance(nxt, dict):
                return
            chain.append(nxt)
        chain[-1].pop(parts[-1], None)
        for depth in range(len(parts) - 1, 0, -1):  # drop costs dicts left empty
            if not chain[depth]:
                chain[depth - 1].pop(parts[depth - 1], None)
        self._save()

    def _save(self) -> None:
        if self.workspace is not None:
            self.workspace.strategies.put(self.graph.id, self.graph)
        else:
            self.set_strategy(None, self.graph)
        self.changed.emit()
