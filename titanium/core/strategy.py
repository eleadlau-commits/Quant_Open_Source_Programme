"""The strategy model: a graph of modules, with knobs.

The module graph is the single source of truth. The patch bay draws it; the code
view shows it as one Python file (one function per module, ``knob(...)`` calls
for knobs) and parses edits back module by module. A strategy imported in a
non-modular form is a graph with one module.

A strategy never knows whether it runs in a backtest or live: at each decision
time it sees a guarded view and its current portfolio, and returns a decision.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
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
    doc: str = ""  # one line on what the strategy does (the code file's docstring)
    preamble: str = ""  # shared code above the modules in the code view: imports, helpers, constants

    def knobs(self) -> dict[str, Knob]:
        return {f"{m.id}.{k.name}": k for m in self.modules for k in m.knobs}

    def module(self, module_id: str) -> Module:
        for m in self.modules:
            if m.id == module_id:
                return m
        raise KeyError(f"no module {module_id!r} in strategy {self.id!r}")

    def knob_value(self, key: str) -> Any:
        """The current setting of knob ``"module.knob"`` (its default until it is turned)."""
        return self.knob_values.get(key, self.knobs()[key].default)

    def new_module_id(self, stem: str = "m") -> str:
        taken = {m.id for m in self.modules}
        n = 1
        while f"{stem}{n}" in taken:
            n += 1
        return f"{stem}{n}"


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


# ---------------------------------------------------------------- strategy files (JSON)
FILE_FORMAT = "titanium.strategy"
FILE_VERSION = 1


def _knob_from(d: dict) -> Knob:
    return Knob(d["name"], KnobType(d["type"]), d["default"], d.get("lo"), d.get("hi"), d.get("step"), d.get("doc", ""))


def graph_to_dict(graph: StrategyGraph) -> dict[str, Any]:
    """The graph as plain JSON values: what a strategy file holds."""
    def knob(k: Knob) -> dict:
        return {"name": k.name, "type": k.type.value, "default": k.default, "lo": k.lo, "hi": k.hi,
                "step": k.step, "doc": k.doc}

    def port(p: Port) -> dict:
        return {"name": p.name, "doc": p.doc}

    return {
        "format": FILE_FORMAT, "version": FILE_VERSION,
        "id": graph.id, "name": graph.name, "doc": graph.doc, "preamble": graph.preamble,
        "settings": copy.deepcopy(graph.settings), "knob_values": copy.deepcopy(graph.knob_values),
        "modules": [{"id": m.id, "kind": m.kind, "name": m.name, "code": m.code,
                     "inputs": [port(p) for p in m.inputs], "outputs": [port(p) for p in m.outputs],
                     "knobs": [knob(k) for k in m.knobs], "source": m.source,
                     "layout": list(m.layout) if m.layout is not None else None} for m in graph.modules],
        "links": [{"src_module": ln.src_module, "src_port": ln.src_port,
                   "dst_module": ln.dst_module, "dst_port": ln.dst_port} for ln in graph.links],
    }


def graph_from_dict(data: dict[str, Any]) -> StrategyGraph:
    if data.get("format") != FILE_FORMAT:
        raise ValueError("not a Titanium strategy file")
    if int(data.get("version", 0)) > FILE_VERSION:
        raise ValueError(f"strategy file version {data['version']} is newer than this app understands")
    modules = [Module(id=m["id"], kind=m["kind"], name=m["name"], code=m.get("code", ""),
                      inputs=[Port(p["name"], p.get("doc", "")) for p in m.get("inputs", [])],
                      outputs=[Port(p["name"], p.get("doc", "")) for p in m.get("outputs", [])],
                      knobs=[_knob_from(k) for k in m.get("knobs", [])], source=m.get("source", ""),
                      layout=tuple(m["layout"]) if m.get("layout") is not None else None)
               for m in data.get("modules", [])]
    links = [Link(**ln) for ln in data.get("links", [])]
    return StrategyGraph(id=data["id"], name=data["name"], modules=modules, links=links,
                         settings=dict(data.get("settings", {})), knob_values=dict(data.get("knob_values", {})),
                         doc=data.get("doc", ""), preamble=data.get("preamble", ""))


def save_strategy(graph: StrategyGraph, path: str | Path) -> None:
    Path(path).write_text(json.dumps(graph_to_dict(graph), indent=2) + "\n", encoding="utf-8")


def load_strategy(path: str | Path) -> StrategyGraph:
    return graph_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
