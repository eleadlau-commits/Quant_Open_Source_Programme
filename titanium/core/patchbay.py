"""Edits the patch bay makes to a strategy graph. No UI here.

Every function takes a graph and returns a *new* graph (the one passed in is
left alone), so the caller can keep the old one for undo and put the new one
through ``Workspace.strategies``. Links that can't be made are refused with a
plain reason (:class:`LinkRefused`), never half made.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .plugins import Registry
from .strategy import Link, Module, StrategyGraph, graph_from_dict, graph_to_dict


class LinkRefused(ValueError):
    """A cable that can't go there. ``str(e)`` says why, in plain words."""


def copy_graph(graph: StrategyGraph) -> StrategyGraph:
    return graph_from_dict(graph_to_dict(graph))


# ---------------------------------------------------------------- links
def feeds(graph: StrategyGraph, src: str, dst: str) -> bool:
    """True if module ``src`` already feeds ``dst`` through some chain of links (or is ``dst``)."""
    seen, todo = set(), [src]
    while todo:
        cur = todo.pop()
        if cur == dst:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        todo += [ln.dst_module for ln in graph.links if ln.src_module == cur]
    return False


def link_problem(graph: StrategyGraph, link: Link) -> str | None:
    """Why ``link`` can't be made, or None if it can."""
    ids = {m.id: m for m in graph.modules}
    src, dst = ids.get(link.src_module), ids.get(link.dst_module)
    if src is None or dst is None:
        return "that module is no longer in the strategy"
    if link.src_port not in {p.name for p in src.outputs}:
        return f"{src.name} has no output called “{link.src_port}”"
    if link.dst_port not in {p.name for p in dst.inputs}:
        return f"{dst.name} has no input called “{link.dst_port}”"
    if src.id == dst.id:
        return "a module can't feed itself"
    taken = next((ln for ln in graph.links if ln.dst_module == dst.id and ln.dst_port == link.dst_port), None)
    if taken is not None:
        if taken == link:
            return "those two are already linked"
        by = ids[taken.src_module].name if taken.src_module in ids else taken.src_module
        return f"{dst.name}’s “{link.dst_port}” input is already taken by {by}. Unplug it first"
    if feeds(graph, dst.id, src.id):
        return f"that would make a loop: {dst.name} already feeds {src.name}"
    return None


def add_link(graph: StrategyGraph, link: Link) -> StrategyGraph:
    problem = link_problem(graph, link)
    if problem:
        raise LinkRefused(problem)
    g = copy_graph(graph)
    g.links.append(Link(link.src_module, link.src_port, link.dst_module, link.dst_port))
    return g


def remove_links(graph: StrategyGraph, links: Iterable[Link]) -> StrategyGraph:
    drop = list(links)
    g = copy_graph(graph)
    g.links = [ln for ln in g.links if ln not in drop]
    return g


def link_into(graph: StrategyGraph, module_id: str, port: str) -> Link | None:
    """The cable plugged into an input, if any."""
    return next((ln for ln in graph.links if ln.dst_module == module_id and ln.dst_port == port), None)


# ---------------------------------------------------------------- modules
def remove_modules(graph: StrategyGraph, ids: Iterable[str]) -> StrategyGraph:
    """Take modules out, with every cable into or out of them (and their turned knob values)."""
    drop = set(ids)
    g = copy_graph(graph)
    g.modules = [m for m in g.modules if m.id not in drop]
    g.links = [ln for ln in g.links if ln.src_module not in drop and ln.dst_module not in drop]
    g.knob_values = {k: v for k, v in g.knob_values.items() if k.partition(".")[0] not in drop}
    return g


def add_from_library(graph: StrategyGraph, registry: Registry, entry_name: str,
                     at: tuple[float, float] | None = None) -> tuple[StrategyGraph, Module]:
    """Copy a library module into the strategy at ``at`` (a fresh id). Returns the new graph and module."""
    from .module_library import add_to_graph

    g = copy_graph(graph)
    m = add_to_graph(g, registry, entry_name)
    m.layout = (float(at[0]), float(at[1])) if at is not None else None
    return g, m


def duplicate(graph: StrategyGraph, ids: Iterable[str], offset: float = 32.0) -> tuple[StrategyGraph, list[str]]:
    """Copies of modules (cables between the copies are copied too; cables from outside are not)."""
    g = copy_graph(graph)
    mapping: dict[str, str] = {}
    for mid in ids:
        old = g.module(mid)
        new_id = g.new_module_id()
        mapping[mid] = new_id
        x, y = old.layout or (0.0, 0.0)
        g.modules.append(replace(old, id=new_id, name=f"{old.name} copy", layout=(x + offset, y + offset),
                                 inputs=list(old.inputs), outputs=list(old.outputs), knobs=list(old.knobs)))
        for k, v in graph.knob_values.items():
            if k.partition(".")[0] == mid:
                g.knob_values[f"{new_id}.{k.partition('.')[2]}"] = v
    for ln in list(graph.links):
        if ln.src_module in mapping and ln.dst_module in mapping:
            g.links.append(Link(mapping[ln.src_module], ln.src_port, mapping[ln.dst_module], ln.dst_port))
    return g, list(mapping.values())


def rename(graph: StrategyGraph, module_id: str, name: str) -> StrategyGraph:
    name = " ".join(name.split())
    if not name:
        raise ValueError("a module needs a name")
    g = copy_graph(graph)
    g.module(module_id).name = name
    return g


def move(graph: StrategyGraph, positions: dict[str, tuple[float, float]]) -> StrategyGraph:
    g = copy_graph(graph)
    for m in g.modules:
        if m.id in positions:
            x, y = positions[m.id]
            m.layout = (round(float(x), 1), round(float(y), 1))
    return g


def set_knob(graph: StrategyGraph, key: str, value) -> StrategyGraph:
    """Turn knob ``"module.knob"`` (back to its default removes the setting)."""
    g = copy_graph(graph)
    if value == g.knobs()[key].default:
        g.knob_values.pop(key, None)
    else:
        g.knob_values[key] = value
    return g


# ---------------------------------------------------------------- layout
def columns(graph: StrategyGraph) -> dict[str, int]:
    """Each module's column: 0 for modules nothing feeds, else one right of its furthest feeder."""
    col: dict[str, int] = {}
    ids = [m.id for m in graph.modules]
    feeders = {i: [ln.src_module for ln in graph.links if ln.dst_module == i and ln.src_module in ids] for i in ids}

    def depth(i: str, stack: frozenset = frozenset()) -> int:
        if i in col:
            return col[i]
        if i in stack:  # a loop (only possible in a hand-written file): stop here
            return 0
        d = max((depth(f, stack | {i}) + 1 for f in feeders[i]), default=0)
        col[i] = d
        return d

    for i in ids:
        depth(i)
    return col


def tidy(graph: StrategyGraph, sizes: dict[str, tuple[float, float]] | None = None,
         origin: tuple[float, float] = (40.0, 40.0), gap: tuple[float, float] = (72.0, 32.0)) -> StrategyGraph:
    """Lay modules out left to right in link order, one column per step, keeping each column's order."""
    sizes = sizes or {}
    w_default, h_default = 220.0, 120.0
    cols = columns(graph)
    by_col: dict[int, list[Module]] = {}
    for m in graph.modules:
        by_col.setdefault(cols[m.id], []).append(m)
    positions: dict[str, tuple[float, float]] = {}
    x = origin[0]
    for c in sorted(by_col):
        mods = sorted(by_col[c], key=lambda m: (m.layout[1] if m.layout else 1e9, graph.modules.index(m)))
        y = origin[1]
        width = 0.0
        for m in mods:
            w, h = sizes.get(m.id, (w_default, h_default))
            positions[m.id] = (x, y)
            y += h + gap[1]
            width = max(width, w)
        x += width + gap[0]
    return move(graph, positions)


def place_new(graph: StrategyGraph, sizes: dict[str, tuple[float, float]] | None = None) -> dict[str, tuple[float, float]]:
    """Where to show modules that have no saved position: to the right of the placed ones, by column."""
    sizes = sizes or {}
    placed = [m for m in graph.modules if m.layout is not None]
    loose = [m for m in graph.modules if m.layout is None]
    if not loose:
        return {}
    if not placed:
        laid = tidy(graph, sizes)
        return {m.id: m.layout for m in laid.modules}
    right = max(m.layout[0] + sizes.get(m.id, (220.0, 0.0))[0] for m in placed) + 72.0
    top = min(m.layout[1] for m in placed)
    out, y = {}, top
    for m in loose:
        out[m.id] = (right, y)
        y += sizes.get(m.id, (0.0, 120.0))[1] + 32.0
    return out
