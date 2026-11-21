"""Measurements turn a run into numbers and curves. They never run the engine.

* global: one curve or number for the whole strategy (profit, Sharpe, drawdown);
* local: a series per instrument or per step (position over time, exposure, a probe).

The built-in ones are ``Library.MEASUREMENTS`` entries (``register_measurements``); plugins add
theirs the same way. The default strategy (``core.baseline``) is run through the same engine,
so every measurement can be shown for it too.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .plugins import Library, Registry
from .run import RunRecord


class Scope(str, Enum):
    GLOBAL = "global"
    LOCAL = "local"


@dataclass
class MeasurementInfo:
    id: str
    name: str
    scope: Scope
    unit: str = ""  # "growth", "%", "USD", "shares", ...
    doc: str = ""
    kind: str = "curve"  # addition (Phase 2E): number, curve or series; see below


@runtime_checkable
class Measurement(Protocol):
    info: MeasurementInfo

    def compute(self, run: RunRecord, **params: Any) -> Any:
        """A number, a time series, or a series per instrument."""
        ...


# ------------------------------------------------------------------------- implementations (Phase 2E)
# What compute() returns, by ``MeasurementInfo.kind``:
#   "number": a float (or None when it can't be measured, e.g. no closed trades);
#   "curve":  a list of (time, value), one per recorded state;
#   "series": {name: [(time, value), ...]}, one curve per instrument, probe or account line.
Curve = list  # list[tuple[datetime, float]]
PROFIT_DISPLAYS = ("growth", "%", "currency")
YEAR_SECONDS = 365.25 * 86400


def _info(id, name, scope, unit="", doc="", kind="curve") -> MeasurementInfo:
    return MeasurementInfo(id, name, scope, unit, doc, kind)


def _equity(run: RunRecord) -> list[tuple[datetime, float]]:
    return [(s.time, s.equity) for s in run.states]


def _capital(run: RunRecord) -> float:
    if run.capital:
        return run.capital
    return run.states[0].capital or run.states[0].equity if run.states else 0.0


def period_returns(run: RunRecord) -> list[float]:
    """Return from one recorded state to the next."""
    eq = [e for _, e in _equity(run)]
    return [b / a - 1 for a, b in zip(eq, eq[1:]) if a]


def periods_per_year(run: RunRecord) -> float:
    """How many recorded steps a year holds, from the run's own span (daily runs give about 252)."""
    if len(run.states) < 2:
        return 0.0
    span = (run.states[-1].time - run.states[0].time).total_seconds()
    return (len(run.states) - 1) / (span / YEAR_SECONDS) if span > 0 else 0.0


class Profit:
    """Equity over time. ``display``: growth (growth of 1), % (profit in percent) or currency."""

    info = _info("profit", "Profit", Scope.GLOBAL, "growth", "What the account made over time.")

    def compute(self, run: RunRecord, display: str = "growth", **_) -> Curve:
        cap = _capital(run)
        if display == "currency":
            return [(t, e - cap) for t, e in _equity(run)]
        if not cap:
            return []
        if display == "%":
            return [(t, (e / cap - 1) * 100) for t, e in _equity(run)]
        return [(t, e / cap) for t, e in _equity(run)]

    @staticmethod
    def unit(display: str, currency: str = "USD") -> str:
        return {"growth": "growth", "%": "%"}.get(display, currency)


class TotalProfit:
    info = _info("total_profit", "Total profit", Scope.GLOBAL, "%", "Profit over the whole run.", kind="number")

    def compute(self, run: RunRecord, display: str = "%", **_) -> float | None:
        curve = Profit().compute(run, display)
        return curve[-1][1] if curve else None


class Sharpe:
    info = _info("sharpe", "Sharpe", Scope.GLOBAL, "",
                 "Average return per step over its spread, scaled to a year (no risk-free rate).", kind="number")

    def compute(self, run: RunRecord, **_) -> float | None:
        r = period_returns(run)
        if len(r) < 2:
            return None
        mean = sum(r) / len(r)
        sd = math.sqrt(sum((x - mean) ** 2 for x in r) / (len(r) - 1))
        if sd == 0:
            return None
        return mean / sd * math.sqrt(periods_per_year(run))


class Drawdown:
    info = _info("drawdown", "Drawdown", Scope.GLOBAL, "%", "How far equity is below its best so far.")

    def compute(self, run: RunRecord, **_) -> Curve:
        out, peak = [], -math.inf
        for t, e in _equity(run):
            peak = max(peak, e)
            out.append((t, (e / peak - 1) * 100 if peak > 0 else 0.0))
        return out


class MaxDrawdown:
    info = _info("max_drawdown", "Max drawdown", Scope.GLOBAL, "%", "The deepest fall from a high.", kind="number")

    def compute(self, run: RunRecord, **_) -> float | None:
        dd = Drawdown().compute(run)
        return min(v for _, v in dd) if dd else None

    @staticmethod
    def when(run: RunRecord) -> datetime | None:
        dd = Drawdown().compute(run)
        return min(dd, key=lambda tv: tv[1])[0] if dd else None


class HitRate:
    info = _info("hit_rate", "Hit rate", Scope.GLOBAL, "%", "Share of closed trades that made money, after costs.",
                 kind="number")

    def compute(self, run: RunRecord, **_) -> float | None:
        closed = [t for t in run.trades if "open" not in t.flags and t.pnl is not None]
        if not closed:
            return None
        return 100.0 * sum(1 for t in closed if t.pnl > 0) / len(closed)


def _gross(state) -> float:
    if not state.equity:
        return 0.0
    return sum(abs(p.exposure or p.market_value) for p in state.positions.values()) / state.equity


class Exposure:
    info = _info("exposure", "Exposure", Scope.GLOBAL, "%", "Gross positions as a share of equity.")

    def compute(self, run: RunRecord, **_) -> Curve:
        return [(s.time, 100.0 * _gross(s)) for s in run.states]


class AverageExposure:
    info = _info("avg_exposure", "Exposure", Scope.GLOBAL, "%", "Average share of equity in the market.", kind="number")

    def compute(self, run: RunRecord, **_) -> float | None:
        if not run.states:
            return None
        return 100.0 * sum(_gross(s) for s in run.states) / len(run.states)


def _per_instrument(run: RunRecord, value) -> dict[str, Curve]:
    names = sorted({k for s in run.states for k in s.positions})
    return {k: [(s.time, value(s, k)) for s in run.states] for k in names}


class Positions:
    info = _info("positions", "Position", Scope.LOCAL, "shares", "Quantity held in each instrument.", kind="series")

    def compute(self, run: RunRecord, **_) -> dict[str, Curve]:
        return _per_instrument(run, lambda s, k: s.quantity(k))


class Weights:
    info = _info("weights", "Weights", Scope.LOCAL, "%", "Each instrument as a share of equity.", kind="series")

    def compute(self, run: RunRecord, **_) -> dict[str, Curve]:
        return _per_instrument(run, lambda s, k: 100.0 * s.weights().get(k, 0.0))


class Cash:
    info = _info("cash", "Cash", Scope.LOCAL, "currency", "Cash in the account.", kind="series")

    def compute(self, run: RunRecord, **_) -> dict[str, Curve]:
        return {"cash": [(s.time, s.cash) for s in run.states]}


class Equity:
    info = _info("equity", "Equity", Scope.LOCAL, "currency", "Cash plus positions at their last price.", kind="series")

    def compute(self, run: RunRecord, **_) -> dict[str, Curve]:
        return {"equity": _equity(run)}


class Probes:
    """Recorded module outputs. A number becomes one curve; a mapping (scores per
    instrument) one curve per key; true/false becomes 1/0; anything else is left out."""

    info = _info("probes", "Module outputs", Scope.LOCAL, "", "What the modules asked for as probes returned.",
                 kind="series")

    def compute(self, run: RunRecord, probe: str | None = None, **_) -> dict[str, Curve]:
        out: dict[str, Curve] = {}
        for name, values in run.probes.items():
            if probe is not None and name != probe:
                continue
            for t, v in values:
                items = v.items() if isinstance(v, dict) else [("", v)]
                for k, x in items:
                    if isinstance(x, bool):
                        x = float(x)
                    if isinstance(x, (int, float)) and math.isfinite(x):
                        out.setdefault(f"{name} · {k}" if k else name, []).append((t, float(x)))
        return out


MEASUREMENTS = (Profit, TotalProfit, Sharpe, Drawdown, MaxDrawdown, HitRate, Exposure, AverageExposure,
                Positions, Weights, Cash, Equity, Probes)
STAT_TILES = ("total_profit", "sharpe", "max_drawdown", "hit_rate", "avg_exposure")  # the run view's tiles


def register_measurements(registry: Registry) -> None:
    have = {e.name for e in registry.entries(Library.MEASUREMENTS)}
    for cls in MEASUREMENTS:
        if cls.info.id not in have:
            registry.add(Library.MEASUREMENTS, cls.info.id, cls(), doc=cls.info.doc)


def measurements(registry: Registry, kind: str | None = None, scope: Scope | None = None) -> list[Measurement]:
    """The registered measurements (plugins' too), optionally of one kind or scope."""
    out = []
    for e in registry.entries(Library.MEASUREMENTS):
        m = e.obj
        if kind is not None and m.info.kind != kind:
            continue
        if scope is not None and m.info.scope != scope:
            continue
        out.append(m)
    return out
