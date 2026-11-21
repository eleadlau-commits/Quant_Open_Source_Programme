"""The module library: modules you can add to a strategy, grouped into folders.

Entries live in the plugin registry under :attr:`Library.MODULES`, named
``"folder/module"``. The app's own starters are in the ``starter`` folder;
plugins add theirs the same way (their own folder, or an existing one).
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass
from pathlib import Path

from .plugins import Entry, Library, Registry
from .strategy import Module, StrategyGraph
from .strategy_code import module_from_code

STARTER = "starter"


@dataclass
class ModuleTemplate:
    """A library entry: a module ready to be copied into a strategy."""

    name: str  # shown in the library and on the module
    kind: str  # "transform" or "decide"
    code: str
    outputs: list[str]
    doc: str = ""

    def module(self, id: str, source: str = "") -> Module:
        return module_from_code(self.code, id, self.kind, self.name, list(self.outputs), source)


def add_module(registry: Registry, folder: str, template: ModuleTemplate, plugin: str = "") -> Entry:
    return registry.add(Library.MODULES, f"{folder}/{template.name}", template, plugin, template.doc)


def folders(registry: Registry) -> dict[str, list[Entry]]:
    """Library entries by folder, starters first, then folders by name."""
    out: dict[str, list[Entry]] = {}
    for e in registry.entries(Library.MODULES):
        folder, _, _ = e.name.rpartition("/")
        out.setdefault(folder or "other", []).append(e)
    return dict(sorted(out.items(), key=lambda kv: (kv[0] != STARTER, kv[0])))


def add_to_graph(graph: StrategyGraph, registry: Registry, entry_name: str) -> Module:
    """Copy a library module into the strategy (with a fresh id) and return it."""
    template: ModuleTemplate = registry.get(Library.MODULES, entry_name)
    m = template.module(graph.new_module_id(), source=entry_name)
    graph.modules.append(m)
    return m


# ---------------------------------------------------------------- the starter folder
MOMENTUM = ModuleTemplate("Momentum", "transform", outputs=["scores"], doc="Each instrument's return over recent days.",
                          code='''def momentum(view):
    """Return over the last `days` completed days, for every instrument in the universe."""
    days = knob("days", 20, lo=5, hi=120)
    scores = {}
    for s in view.universe():
        close = list(view.bars(s, "1d")["close"])
        if len(close) > days:
            scores[s] = close[-1] / close[-days - 1] - 1
    return scores
''')

MOVING_AVERAGE = ModuleTemplate("Above moving average", "transform", outputs=["scores"],
                                doc="Keeps instruments whose price is above their moving average.",
                                code='''def above_moving_average(view, scores):
    """Keep only instruments closing above their `days`-day moving average (all of the universe if no scores come in)."""
    days = knob("days", 50, lo=5, hi=200)
    names = scores if scores is not None else {s: 0.0 for s in view.universe()}
    kept = {}
    for s, score in names.items():
        close = list(view.bars(s, "1d")["close"])
        if len(close) >= days and close[-1] > sum(close[-days:]) / days:
            kept[s] = score
    return kept
''')

TOP_N = ModuleTemplate("Top N equal weight", "decide", outputs=[], doc="Holds the N best-scored instruments, equal weight.",
                       code='''def top_n_equal_weight(scores):
    """Hold the `top` highest scores in equal weight (only positive ones, if the switch is on)."""
    top = knob("top", 5, lo=1, hi=20)
    positive_only = knob("positive_only", True)
    ranked = sorted(scores or {}, key=lambda s: scores[s], reverse=True)
    best = [s for s in ranked if scores[s] > 0 or not positive_only][:top]
    return {s: 1 / len(best) for s in best}
''')

STARTERS = (MOMENTUM, MOVING_AVERAGE, TOP_N)


def register_starters(registry: Registry) -> None:
    """Add the starter folder (skipping entries already there, e.g. from the starter-modules plugin)."""
    have = {e.name for e in registry.entries(Library.MODULES)}
    for t in STARTERS:
        if f"{STARTER}/{t.name}" not in have:
            add_module(registry, STARTER, copy.deepcopy(t))


# ---------------------------------------------------------------- the library folder on disk
LIBRARY_PLUGIN = "library-folder"  # the plugin id entries from the library folder carry


def template_from_file(path: Path) -> ModuleTemplate:
    """A library entry from a ``.py`` file holding one module function.

    ``@module(kind="decide", outputs=[...], name="...")`` above the function sets what
    it is; without it the module is a transform with one output. The docstring's first
    line is its description.
    """
    code = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(code)
    fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if fn is None:
        raise ValueError("it has no function")
    opts: dict = {}
    for d in fn.decorator_list:
        f = d.func if isinstance(d, ast.Call) else d
        if getattr(f, "id", getattr(f, "attr", None)) == "module" and isinstance(d, ast.Call):
            opts = {k.arg: ast.literal_eval(k.value) for k in d.keywords if k.arg in ("kind", "outputs", "name")}
    kind = opts.get("kind", "transform")
    if kind not in ("transform", "decide"):
        raise ValueError(f"kind must be transform or decide, not {kind!r}")
    outputs = list(opts.get("outputs") or ([] if kind == "decide" else ["out"]))
    body = "\n".join(code.splitlines()[fn.lineno - 1:fn.end_lineno])  # the function only, no decorators
    doc = (ast.get_docstring(fn) or "").strip().splitlines()
    name = opts.get("name") or fn.name.replace("_", " ").capitalize()
    return ModuleTemplate(name, kind, body.strip("\n") + "\n", outputs, doc[0] if doc else "")


def load_library_folder(registry: Registry, root: Path | str | None) -> tuple[int, list[str]]:
    """Add every module in the library folder: ``<root>/<folder>/<module>.py``.

    Each sub-folder is a folder of the module library. Entries from an earlier load are
    replaced. Returns (how many were added, problems). A missing folder adds nothing.
    """
    registry.remove_plugin(LIBRARY_PLUGIN)
    if root is None or not Path(root).is_dir():
        return 0, []
    added, problems = 0, []
    for folder in sorted(p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        for path in sorted(folder.glob("*.py")):
            try:
                template = template_from_file(path)
                registry.add(Library.MODULES, f"{folder.name}/{template.name}", template, LIBRARY_PLUGIN,
                             template.doc)
                added += 1
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
                problems.append(f"Skipped {folder.name}/{path.name}: {exc}")
    return added, problems


def momentum_rotation(id: str = "S1", name: str = "Momentum rotation") -> StrategyGraph:
    """An example built from the starters: momentum, filtered by trend, top 5 equal weight."""
    g = StrategyGraph(id=id, name=name, doc="Hold the strongest names that are above their moving average.",
                      settings={"datasets": [], "decide_at": "15:50", "every": "day"})
    reg = Registry()
    register_starters(reg)
    a = add_to_graph(g, reg, f"{STARTER}/Momentum")
    b = add_to_graph(g, reg, f"{STARTER}/Above moving average")
    c = add_to_graph(g, reg, f"{STARTER}/Top N equal weight")
    from .strategy import Link

    g.links += [Link(a.id, "scores", b.id, "scores"), Link(b.id, "scores", c.id, "scores")]
    a.layout, b.layout, c.layout = (40.0, 60.0), (336.0, 60.0), (632.0, 60.0)
    return g
