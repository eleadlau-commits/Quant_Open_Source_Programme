"""Backtests ask whether a result holds up. A pass means only that it survived that test.

A backtest reads a :class:`RunRecord` and may re-run the one simulator with changed
settings, changed knobs or a changed strategy (``ctx.rerun``). The tests themselves are
``Library.BACKTESTS`` entries; the ones the app ships with are the ``honest-tests``
built-in plugin. A test is an object with ``info`` (:class:`BacktestInfo`) and
``evaluate(ctx, **params) -> Verdict``.

Because the simulator is causal (a step only sees what was known by then), the returns of
a run up to a date are exactly what a run stopped at that date would give. So a test that
needs "the strategy fitted on the early part" runs each variant once over the whole span
and slices it, rather than running it again for every split.
"""
from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol, runtime_checkable

from .run import RunRecord


@dataclass
class Verdict:
    test: str
    passed: bool | None  # None: could not be evaluated
    headline: str
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        """pass, fail or na (could not judge): how the pages group results."""
        return "pass" if self.passed is True else "fail" if self.passed is False else "na"


@dataclass
class BacktestContext:
    run: RunRecord  # the run being judged
    rerun: Callable[..., RunRecord]  # re-runs the same simulator with changed settings
    # additions (Phase 2F) --------------------------------------------------------------
    # rerun(settings=None, knobs=None, strategy=None) -> RunRecord. ``settings`` go on top of the
    # run's settings, ``knobs`` on top of its knob values ("module.knob": value), ``strategy``
    # replaces the strategy (a StrategyGraph or an object with decide). Reruns are cached for the
    # run, so tests run one after another share them.
    baseline: Callable[[], RunRecord | None] = lambda: None  # the default strategy on the same terms
    history: list[RunRecord] = field(default_factory=list)  # earlier runs of the same strategy this session
    progress: Callable[[float], None] = lambda fraction: None
    cancelled: Callable[[], bool] = lambda: False
    graph: Any = None  # the StrategyGraph exactly as run, when the run came from one
    strategy: Any = None  # the strategy as run (the graph, or an object with decide); None if it can't be rerun

    def variants(self, spread: float = 0.25, max_knobs: int = 4) -> list["Variant"]:
        """The run itself plus its knob neighbours (see :func:`knob_variants`), each run once."""
        out = [Variant({}, "as run", self.run, True)]
        if self.graph is None:
            return out
        todo = knob_variants(self.graph, spread, max_knobs)
        for i, (knobs, label) in enumerate(todo):
            if self.cancelled():
                break
            out.append(Variant(knobs, label, self.rerun(knobs=knobs)))
            self.progress((i + 1) / max(1, len(todo)))
        return out

    def trials(self) -> int:
        """How many versions of this strategy were tried this session (distinct knobs and settings),
        the run included. Used to discount the best-looking result."""
        seen = {_config_key(r) for r in self.history if r.status == "done"}
        seen.add(_config_key(self.run))
        return len(seen)


@dataclass
class Variant:
    knobs: dict[str, Any]  # the knobs changed from the run ("module.knob": value)
    label: str
    record: RunRecord
    is_run: bool = False


@dataclass
class BacktestInfo:
    """What a test is, for the Backtests page and the backtest library."""

    id: str
    name: str
    doc: str = ""  # one or two sentences: what it checks
    params: list = field(default_factory=list)  # core.data.Param: settings shown in the test's form
    cost: str = ""  # how much work it does, in words: "reads the run", "runs 9 variants", ...


@runtime_checkable
class Backtest(Protocol):
    id: str
    name: str

    def evaluate(self, ctx: BacktestContext, **params: Any) -> Verdict: ...


# ------------------------------------------------------------------------- helpers for tests
YEAR_SECONDS = 365.25 * 86400


def step_returns(run: RunRecord, start: datetime | None = None, end: datetime | None = None) -> list[float]:
    """Return from one recorded state to the next, for steps ending in [start, end)."""
    s = run.states
    out = []
    for a, b in zip(s, s[1:]):
        if (start is not None and b.time < start) or (end is not None and b.time >= end):
            continue
        out.append(b.equity / a.equity - 1 if a.equity else 0.0)
    return out


def steps_per_year(run: RunRecord) -> float:
    if len(run.states) < 2:
        return 0.0
    span = (run.states[-1].time - run.states[0].time).total_seconds()
    return (len(run.states) - 1) / (span / YEAR_SECONDS) if span > 0 else 0.0


def mean(x: list[float]) -> float:
    return sum(x) / len(x) if x else 0.0


def stdev(x: list[float]) -> float:
    if len(x) < 2:
        return 0.0
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def sharpe(x: list[float], per_year: float = 1.0) -> float:
    """Mean over spread, scaled by sqrt(per_year). 0 when it can't be measured."""
    sd = stdev(x)
    return mean(x) / sd * math.sqrt(per_year) if sd > 0 else 0.0


def t_stat(x: list[float]) -> float:
    sd = stdev(x)
    return mean(x) / (sd / math.sqrt(len(x))) if sd > 0 else 0.0


def aligned_returns(a: RunRecord, b: RunRecord) -> tuple[list[float], list[float]]:
    """Step returns of two runs over the steps both have (by time)."""
    ra = dict(zip([s.time for s in a.states[1:]], step_returns(a)))
    rb = dict(zip([s.time for s in b.states[1:]], step_returns(b)))
    common = sorted(set(ra) & set(rb))
    return [ra[t] for t in common], [rb[t] for t in common]


def split_time(run: RunRecord, fraction: float) -> datetime | None:
    """The time of the step a ``fraction`` of the way through the run."""
    if len(run.states) < 3:
        return None
    i = min(len(run.states) - 1, max(1, int(len(run.states) * fraction)))
    return run.states[i].time


def total_growth(x: list[float]) -> float:
    g = 1.0
    for r in x:
        g *= 1 + r
    return g - 1


def _config_key(run: RunRecord) -> str:
    snap = run.strategy_snapshot or {}
    settings = {k: v for k, v in (run.settings or {}).items() if k != "probes"}
    return repr((sorted((snap.get("knob_values") or {}).items()), sorted((k, repr(v)) for k, v in settings.items())))


# ------------------------------------------------------------------------- strategy changes
def knob_variants(graph: Any, spread: float = 0.25, max_knobs: int = 4) -> list[tuple[dict[str, Any], str]]:
    """Neighbours of a graph's knob setting: each number knob (that has a range) moved down and up
    by ``spread`` of its range, one knob at a time. Switches are left alone (that is ablation)."""
    out = []
    knobs = [(k, kn) for k, kn in graph.knobs().items()
             if getattr(kn.type, "value", kn.type) in ("real", "int") and kn.lo is not None and kn.hi is not None
             and kn.hi > kn.lo]
    for key, kn in knobs[:max_knobs]:
        now = graph.knob_value(key)
        step = (kn.hi - kn.lo) * spread
        for v in (now - step, now + step):
            v = min(kn.hi, max(kn.lo, v))
            if getattr(kn.type, "value", kn.type) == "int":
                v = int(round(v))
            else:
                v = round(float(v), 10)
            if v != now and all(o[0] != {key: v} for o in out):
                out.append(({key: v}, f"{key} = {v:g}"))
    return out


def ingredients(graph: Any) -> list[tuple[str, str]]:
    """Things a strategy can do without, for ablation: (id, label). Switch knobs ("knob:m.k") and
    modules whose output can be skipped because an input of the same name can stand in ("module:m").
    Modules come first: a filter is the usual thing to question."""
    out = []
    for m in graph.modules:
        if m.kind == "decide":
            continue
        ins = {p.name for p in m.inputs}
        if any(o.name in ins for o in m.outputs) and any(ln.src_module == m.id for ln in graph.links):
            out.append((f"module:{m.id}", m.name or m.id))
    for key, kn in graph.knobs().items():
        if getattr(kn.type, "value", kn.type) == "bool":
            out.append((f"knob:{key}", f"switch {key}"))
    return out


def without(graph: Any, ingredient: str) -> tuple[Any, dict[str, Any]]:
    """The graph without one ingredient (see :func:`ingredients`): (graph, knob changes).
    A skipped module's readers are wired to what fed its input of the same name."""
    kind, _, ref = ingredient.partition(":")
    if kind == "knob":
        return graph, {ref: not bool(graph.knob_value(ref))}
    if kind != "module":
        raise ValueError(f"unknown ingredient {ingredient!r}")
    g = copy.deepcopy(graph)
    m = g.module(ref)
    feeds = {ln.dst_port: (ln.src_module, ln.src_port) for ln in g.links if ln.dst_module == ref}
    links = []
    for ln in g.links:
        if ln.dst_module == ref:
            continue
        if ln.src_module == ref:
            if ln.src_port not in feeds:
                raise ValueError(f"{m.name or ref} can't be skipped: nothing feeds an input called {ln.src_port}")
            src = feeds[ln.src_port]
            ln = type(ln)(src[0], src[1], ln.dst_module, ln.dst_port)
        links.append(ln)
    g.links = links
    g.modules = [x for x in g.modules if x.id != ref]
    g.knob_values = {k: v for k, v in g.knob_values.items() if not k.startswith(f"{ref}.")}
    return g, {}


class RandomPicks:
    """The strategy with its choice of names replaced by chance: the same decision times, the
    same number of names, the same weights and the same holding periods, but the names are drawn
    at random from what is trading then. A name keeps its stand-in for as long as the strategy
    holds it, so the random version trades as often as the real one. With one instrument (a
    futures strategy) it flips a coin for the direction of each new position instead.

    ``inner``: a StrategyGraph, or an object with ``decide``."""

    def __init__(self, inner: Any, seed: int, settings: dict[str, Any] | None = None):
        from .strategy import StrategyGraph
        from .strategy_compile import compile_graph

        if isinstance(inner, StrategyGraph):
            inner = compile_graph(inner)
        self.inner = inner
        self.rng = random.Random(seed)
        self.settings = dict(settings if settings is not None else getattr(inner, "settings", {}) or {})
        self.graph = getattr(inner, "graph", None)
        self.entry = getattr(inner, "entry", None)
        self.id = getattr(inner, "id", "") or getattr(self.graph, "id", "")
        self.stand_in: dict[str, str] = {}
        self.flip: dict[str, int] = {}

    def run_modules(self, view, portfolio):  # the engine records probes through this when it exists
        return self.inner.run_modules(view, portfolio)

    def decide(self, view, portfolio):
        from .strategy_compile import to_decision

        if hasattr(self.inner, "run_modules") and self.entry is not None:
            d = to_decision(self.inner.run_modules(view, portfolio)[self.entry]["result"])
        else:
            d = to_decision(self.inner.decide(view, portfolio))
        if d is None:
            return None
        universe = sorted(view.universe())
        if len(universe) <= 1:
            return self._coin(d, portfolio)
        wanted = set(d.targets or {}) | {o.instrument for o in d.orders}
        for k in [k for k in self.stand_in if k not in wanted]:
            del self.stand_in[k]  # let go when the strategy lets go
        free = [u for u in universe if u not in self.stand_in.values()]
        for k in sorted(wanted):
            if k not in self.stand_in or self.stand_in[k] not in universe:
                if not free:
                    free = list(universe)
                pick = self.rng.choice(free)
                free.remove(pick)
                self.stand_in[k] = pick
        if d.targets is not None:
            new: dict[str, float] = {}
            for k, w in d.targets.items():
                new[self.stand_in[k]] = new.get(self.stand_in[k], 0.0) + w
            d.targets = new
        for o in d.orders:
            o.instrument = self.stand_in.get(o.instrument, o.instrument)
        return d

    def _coin(self, d, portfolio):
        wanted = set(d.targets or {}) | {o.instrument for o in d.orders}
        held = {k for k, w in (d.targets or {}).items() if w}
        busy = {o.instrument for o in getattr(portfolio, "orders", None) or []}
        for k in list(self.flip):
            flat = not (portfolio.quantity(k) if portfolio is not None else 0)
            if k not in held and k not in {o.instrument for o in d.orders} and flat and k not in busy:
                del self.flip[k]  # a new position gets a new coin
        for k in wanted:
            self.flip.setdefault(k, self.rng.choice((1, -1)))
        if d.targets is not None:
            d.targets = {k: w * self.flip[k] for k, w in d.targets.items()}
        for o in d.orders:
            if self.flip[o.instrument] < 0:
                if o.limit_price is not None or o.stop_price is not None:
                    raise ValueError("orders at fixed price levels can't be flipped to the other side; "
                                     "give bracket exits as distances (stop_offset, target_offset)")
                from .orders import Side

                o.side = Side(-int(o.side))
        return d
