"""The strategy model: a graph of modules, with knobs.

The module graph is the single source of truth. The patch bay draws it; the code
view shows it as one Python file (one function per module, ``knob(...)`` calls
for knobs) and parses edits back module by module. A strategy imported in a
non-modular form is a graph with one module.

A strategy never knows whether it runs in a backtest or live: at each decision
time it sees a guarded view and its current portfolio, and returns a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .data import GuardedView
from .orders import Order
from .portfolio import PortfolioState


class KnobType(str, Enum):
    REAL = "real"
    INT = "int"
    BOOL = "bool"


@dataclass
class Knob:
    """A value you can turn without editing code: a slider or a switch."""

    name: str
    type: KnobType
    default: float | int | bool
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    doc: str = ""


@dataclass
class Port:
    name: str
    doc: str = ""


@dataclass
class Module:
    """One box in the patch bay, and one function in the code view."""

    id: str
    kind: str  # e.g. "data", "transform", "decide": where it sits in the module library
    name: str
    code: str = ""  # the module's own Python source
    inputs: list[Port] = field(default_factory=list)
    outputs: list[Port] = field(default_factory=list)
    knobs: list[Knob] = field(default_factory=list)
    source: str = ""  # library entry it came from, if any
    layout: tuple[float, float] | None = None  # position on the canvas (ignored by the engine)


@dataclass
class Link:
    """A cable from one module's output to another module's input."""

    src_module: str
    src_port: str
    dst_module: str
    dst_port: str


@dataclass
class StrategyGraph:
    id: str
    name: str
    modules: list[Module] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)  # dataset, decision schedule, costs, ...
    knob_values: dict[str, Any] = field(default_factory=dict)  # current settings of knobs, by "module.knob"

    def knobs(self) -> dict[str, Knob]:
        return {f"{m.id}.{k.name}": k for m in self.modules for k in m.knobs}


@dataclass
class Decision:
    """What a strategy wants at one decision time: target weights, orders, or both."""

    targets: dict[str, float] | None = None  # fraction of equity per instrument; missing = 0
    orders: list[Order] = field(default_factory=list)
    cancel: list[str] = field(default_factory=list)  # ids of open orders to cancel (addition, Phase 1B)


@runtime_checkable
class Strategy(Protocol):
    """What the engine (backtest or, later, live) drives."""

    def decision_times(self, view_factory: Any) -> Any: ...

    def decide(self, view: GuardedView, portfolio: PortfolioState) -> Decision | None: ...
