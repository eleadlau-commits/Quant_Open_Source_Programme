"""Compiling a strategy graph into something the engine can drive.

:func:`compile_graph` turns a :class:`StrategyGraph` into a :class:`GraphStrategy`.
At each decision time it runs the modules the decision depends on, in link
order, each against the guarded view and the current portfolio, and turns the
decide module's result into a :class:`Decision`:

* a dict ``{instrument: weight}``: target weights (fraction of equity, missing = 0);
* a list of :class:`Order`: orders;
* a :class:`Decision`: as it is;
* ``None``: no change.
"""
from __future__ import annotations

import inspect
from typing import Any

from .data import GuardedView
from .orders import Order
from .portfolio import PortfolioState
from .strategy import Decision, StrategyGraph
from .strategy_code import _RUNNING, PORTFOLIO_ARGS, VIEW_ARGS, StrategyCodeError, function_name, knob, module


class StrategyRunError(RuntimeError):
    """A module raised, or returned something the next step can't use."""

    def __init__(self, module_id: str, message: str):
        super().__init__(f"module {module_id!r}: {message}")
        self.module_id = module_id


def _order(graph: StrategyGraph) -> list[str]:
    """Module ids in an order where every module runs after the ones feeding it."""
    ids = [m.id for m in graph.modules]
    deps = {i: [] for i in ids}
    for ln in graph.links:
        if ln.dst_module in deps and ln.src_module in deps:
            deps[ln.dst_module].append(ln.src_module)
    out, state = [], {}

    def visit(i: str) -> None:
        if state.get(i) == 1:
            raise StrategyCodeError(f"the links make a loop through module {i!r}")
        if state.get(i) == 2:
            return
        state[i] = 1
        for d in deps[i]:
            visit(d)
        state[i] = 2
        out.append(i)

    for i in ids:
        visit(i)
    return out


def entry_module(graph: StrategyGraph) -> str:
    """The module whose result is the decision: the ``decide`` module, else the last one nothing reads."""
    decide = [m.id for m in graph.modules if m.kind == "decide"]
    if len(decide) > 1:
        raise StrategyCodeError(f"a strategy has one decide module, this one has {len(decide)}: {', '.join(decide)}")
    if decide:
        return decide[0]
    read = {ln.src_module for ln in graph.links}
    ends = [m.id for m in graph.modules if m.id not in read]
    if not ends:
        raise StrategyCodeError("the strategy has no modules")
    return ends[-1]


def to_decision(result: Any) -> Decision | None:
    if result is None or isinstance(result, Decision):
        return result
    if isinstance(result, dict):
        return Decision(targets={str(k): float(v) for k, v in result.items()})
    if isinstance(result, Order):
        return Decision(orders=[result])
    if isinstance(result, (list, tuple)) and all(isinstance(o, Order) for o in result):
        return Decision(orders=list(result))
    raise TypeError(f"a decision is target weights (a dict), orders, or a Decision, not {type(result).__name__}")


class GraphStrategy:
    """A strategy graph, compiled. Satisfies :class:`titanium.core.strategy.Strategy`."""

    def __init__(self, graph: StrategyGraph):
        self.graph = graph
        # the knobs are read once, here: a knob turned while a run goes on doesn't reach it
        self.knob_values = dict(graph.knob_values)
        self.entry = entry_module(graph)
        order = _order(graph)
        needed = self._upstream(self.entry)
        self.order = [i for i in order if i in needed]
        base: dict[str, Any] = {"knob": knob, "module": module, "__name__": f"titanium_strategy_{graph.id}"}
        try:
            exec(compile(graph.preamble or "", f"<{graph.id} shared code>", "exec"), base)
        except Exception as e:  # noqa: BLE001 - user code
            raise StrategyCodeError(f"shared code: {type(e).__name__}: {e}") from e
        self._fns = {}
        self._params = {}
        for mid in self.order:
            m = graph.module(mid)
            ns = dict(base)
            try:
                exec(compile(m.code, f"<{graph.id}.{mid}>", "exec"), ns)
            except Exception as e:  # noqa: BLE001 - user code
                raise StrategyCodeError(f"module {mid!r}: {type(e).__name__}: {e}") from e
            fn = ns[function_name(m.code)]
            self._fns[mid] = fn
            self._params[mid] = list(inspect.signature(fn).parameters)
        self._inputs = {mid: {ln.dst_port: (ln.src_module, ln.src_port) for ln in graph.links if ln.dst_module == mid}
                        for mid in self.order}

    def _upstream(self, mid: str) -> set[str]:
        seen, todo = set(), [mid]
        while todo:
            i = todo.pop()
            if i in seen:
                continue
            seen.add(i)
            todo += [ln.src_module for ln in self.graph.links if ln.dst_module == i]
        return seen

    def decision_times(self, view_factory: Any) -> Any:
        """When to decide is the engine's job, from ``graph.settings`` (decision schedule)."""
        return view_factory.decision_times(self.graph.settings)

    def run_modules(self, view: GuardedView, portfolio: PortfolioState | None) -> dict[str, dict[str, Any]]:
        """Run the modules once; each module's outputs, by port name."""
        values = self.knob_values
        outputs: dict[str, dict[str, Any]] = {}
        for mid in self.order:
            m = self.graph.module(mid)
            kwargs = {}
            for p in self._params[mid]:
                if p in VIEW_ARGS:
                    kwargs[p] = view
                elif p in PORTFOLIO_ARGS:
                    kwargs[p] = portfolio
                elif p in self._inputs[mid]:
                    src, port = self._inputs[mid][p]
                    kwargs[p] = outputs[src].get(port)
                else:
                    kwargs[p] = None  # an input with no cable
            token = _RUNNING.set((mid, values))
            try:
                result = self._fns[mid](**kwargs)
            except Exception as e:  # noqa: BLE001 - user code
                raise StrategyRunError(mid, f"{type(e).__name__}: {e}") from e
            finally:
                _RUNNING.reset(token)
            ports = [p.name for p in m.outputs]
            if len(ports) <= 1:
                outputs[mid] = {ports[0] if ports else "result": result}
            elif isinstance(result, dict) and set(ports) <= set(result):
                outputs[mid] = {p: result[p] for p in ports}
            elif isinstance(result, tuple) and len(result) == len(ports):
                outputs[mid] = dict(zip(ports, result))
            else:
                raise StrategyRunError(mid, f"has outputs {ports}; return a dict with those keys or a tuple")
            outputs[mid]["result"] = result
        return outputs

    def decide(self, view: GuardedView, portfolio: PortfolioState | None) -> Decision | None:
        result = self.run_modules(view, portfolio)[self.entry]["result"]
        try:
            return to_decision(result)
        except TypeError as e:
            raise StrategyRunError(self.entry, str(e)) from e


def compile_graph(graph: StrategyGraph) -> GraphStrategy:
    return GraphStrategy(graph)
