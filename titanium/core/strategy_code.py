"""The code bridge: a strategy graph as one Python file, and back.

The graph is the source of truth. :func:`generate` writes it as a file::

    '''Hold the strongest names.'''
    from titanium.sdk import knob, module

    SETTINGS = {"decide_at": "15:50"}
    KNOBS = {"m1.days": 30}            # knobs turned away from their defaults

    @module(id="m1", name="Momentum", kind="transform", outputs=["scores"])
    def momentum(view):
        days = knob("days", 20, lo=5, hi=120)
        ...

    @module(id="m2", name="Top N", kind="decide", links={"scores": "m1.scores"})
    def top_n(scores):
        ...

One function per module. Its parameters are its input ports (``view`` and
``portfolio``, or ``F`` and ``p``, are the decision-time context, not ports);
``links`` says which output feeds each input. ``knob(...)`` calls are the knobs.
Anything else at the top of the file (imports, helper functions, constants) is
shared code that every module can use.

:func:`parse` reads an edited file back module by module. A plain Python file
with no ``@module`` (a ``decide(F, p)`` file from the prototype, say) imports as
a graph with one module: its ``decide`` function, with the rest as shared code.
"""
from __future__ import annotations

import ast
import io
import json
import keyword
import re
import tokenize
from contextvars import ContextVar
from dataclasses import replace
from typing import Any, Callable

from .strategy import Knob, KnobType, Link, Module, Port, StrategyGraph

SDK_MODULES = ("titanium.sdk", "honestbt.sdk")
SDK_IMPORT = "from titanium.sdk import knob, module"
VIEW_ARGS = ("view", "F")
PORTFOLIO_ARGS = ("portfolio", "p")
CONTEXT_ARGS = VIEW_ARGS + PORTFOLIO_ARGS
DEFAULT_OUTPUT = "out"


class StrategyCodeError(ValueError):
    """The file can't be read as a strategy. ``line`` is 1-based (0 = not tied to a line)."""

    def __init__(self, message: str, line: int = 0):
        super().__init__(f"line {line}: {message}" if line else message)
        self.message = message
        self.line = line


# ---------------------------------------------------------------- the SDK strategy code calls
# (module id, knob values of the strategy) while a module runs; None outside a run.
_RUNNING: ContextVar[tuple[str, dict[str, Any]] | None] = ContextVar("titanium_running_module", default=None)


def _coerce(value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, int):
        return int(round(value))
    if isinstance(default, float):
        return float(value)
    return value


def knob(name: str, default: Any, lo: float | None = None, hi: float | None = None,
         step: float | None = None, doc: str = "") -> Any:
    """A value you can turn without editing the code. Returns the current setting, or ``default``."""
    running = _RUNNING.get()
    if running is not None:
        module_id, values = running
        key = f"{module_id}.{name}"
        if key in values:
            return _coerce(values[key], default)
    return default


def module(id: str | None = None, name: str | None = None, kind: str = "transform",
           outputs: list[str] | None = None, links: dict[str, str] | None = None,
           source: str = "", layout: tuple[float, float] | None = None, **_: Any) -> Callable:
    """Marks a function as a module. Only read by :func:`parse`; at run time it changes nothing."""
    def wrap(fn: Callable) -> Callable:
        return fn
    return wrap


# ---------------------------------------------------------------- knobs found in code
def _literal(node: ast.AST) -> Any:
    return ast.literal_eval(node)


def _is_knob_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "knob"


def knob_type(default: Any) -> KnobType:
    if isinstance(default, bool):
        return KnobType.BOOL
    if isinstance(default, int):
        return KnobType.INT
    return KnobType.REAL


def default_range(value: float) -> tuple[float, float]:
    """A sensible slider range around a number that has no ``lo``/``hi`` yet."""
    if isinstance(value, int):
        if value == 0:
            return 0, 10
        lo, hi = sorted((value // 4 if value > 0 else value * 4, value * 4 if value > 0 else value // 4))
        return (max(lo, 1) if value > 0 else lo), hi
    if value == 0:
        return -1.0, 1.0
    lo, hi = sorted((value / 4, value * 4))
    return lo, hi


def knobs_in(code: str) -> list[Knob]:
    """Every ``knob("name", default, lo=, hi=, step=, doc=)`` call with literal arguments, in order."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    found: list[tuple[int, int, Knob]] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not _is_knob_call(node):
            continue
        try:
            args = [_literal(a) for a in node.args]
            kw = {k.arg: _literal(k.value) for k in node.keywords if k.arg}
        except (ValueError, SyntaxError):
            continue
        names = ("name", "default", "lo", "hi", "step", "doc")
        vals = dict(zip(names, args)) | kw
        name, default = vals.get("name"), vals.get("default")
        if not isinstance(name, str) or name in seen or not isinstance(default, (bool, int, float)):
            continue
        seen.add(name)
        t = knob_type(default)
        lo, hi, step = vals.get("lo"), vals.get("hi"), vals.get("step")
        if t is not KnobType.BOOL:
            dlo, dhi = default_range(default)
            lo = dlo if lo is None else lo
            hi = dhi if hi is None else hi
            if step is None and t is KnobType.INT:
                step = 1
        found.append((node.lineno, node.col_offset, Knob(name, t, default, lo, hi, step, str(vals.get("doc", "")))))
    return [k for _, _, k in sorted(found, key=lambda f: (f[0], f[1]))]


# ---------------------------------------------------------------- functions and ports
def _function(code: str) -> ast.FunctionDef:
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node  # type: ignore[return-value]
    raise StrategyCodeError("a module's code must define a function")


def function_name(code: str) -> str:
    return _function(code).name


def input_names(fn: ast.FunctionDef) -> list[str]:
    args = [a.arg for a in fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs]
    return [a for a in args if a not in CONTEXT_ARGS]


def module_from_code(code: str, id: str, kind: str = "transform", name: str | None = None,
                     outputs: list[str] | None = None, source: str = "") -> Module:
    """A module whose ports and knobs are read from its function."""
    fn = _function(code)
    if outputs is None:
        outputs = [] if kind == "decide" else [DEFAULT_OUTPUT]
    return Module(id=id, kind=kind, name=name or fn.name, code=code.strip("\n") + "\n",
                  inputs=[Port(a) for a in input_names(fn)], outputs=[Port(o) for o in outputs],
                  knobs=knobs_in(code), source=source)


def refresh(m: Module) -> Module:
    """Re-read a module's input ports and knobs from its code (port docs are kept)."""
    fn = _function(m.code)
    docs = {p.name: p.doc for p in m.inputs}
    return replace(m, inputs=[Port(a, docs.get(a, "")) for a in input_names(fn)], knobs=knobs_in(m.code))


# ---------------------------------------------------------------- graph -> file
def _py(value: Any, indent: int = 0) -> str:
    """A plain value as Python, strings in double quotes; long dicts and lists one item per line."""
    def flat(v: Any) -> str:
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, dict):
            return "{" + ", ".join(f"{flat(k)}: {flat(x)}" for k, x in v.items()) + "}"
        if isinstance(v, list):
            return "[" + ", ".join(flat(x) for x in v) + "]"
        if isinstance(v, tuple):
            return "(" + ", ".join(flat(x) for x in v) + ("," if len(v) == 1 else "") + ")"
        return repr(v)

    one = flat(value)
    if len(one) + indent <= 88 or not isinstance(value, (dict, list)) or not value:
        return one
    pad = " " * (indent + 4)
    if isinstance(value, dict):
        items = [f"{pad}{flat(k)}: {_py(v, indent + 4)}," for k, v in value.items()]
        return "{\n" + "\n".join(items) + "\n" + " " * indent + "}"
    return "[\n" + "\n".join(f"{pad}{_py(v, indent + 4)}," for v in value) + "\n" + " " * indent + "]"


def _identifier(text: str) -> str:
    out = re.sub(r"\W+", "_", text.strip().lower()).strip("_") or "module"
    if out[0].isdigit() or keyword.iskeyword(out):
        out = "m_" + out
    return out


def _unique_function_names(graph: StrategyGraph) -> dict[str, str]:
    """Module id -> function name, renaming clashes (two copies of one library module, say)."""
    taken: set[str] = set()
    try:
        taken |= {n.name for n in ast.parse(graph.preamble).body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    except SyntaxError:
        pass
    out = {}
    for m in graph.modules:
        base = function_name(m.code)
        name, n = base, 2
        while name in taken:
            name, n = f"{base}_{n}", n + 1
        taken.add(name)
        out[m.id] = name
    return out


def _rename_def(code: str, old: str, new: str) -> str:
    return re.sub(rf"^(\s*(?:async\s+)?def\s+){re.escape(old)}\b", rf"\g<1>{new}", code, count=1, flags=re.M)


def _q(value: Any) -> str:
    """Text, and lists or dicts of text, in double quotes (as the rest of the file is written)."""
    return json.dumps(value, ensure_ascii=False)


def decorator(m: Module, links: list[Link], fn_name: str) -> str:
    args = [f"id={_q(m.id)}"]
    if m.name != fn_name:
        args.append(f"name={_q(m.name)}")
    args.append(f"kind={_q(m.kind)}")
    outs = [p.name for p in m.outputs]
    if outs != ([] if m.kind == "decide" else [DEFAULT_OUTPUT]):
        args.append(f"outputs={_q(outs)}")
    mine = {ln.dst_port: f"{ln.src_module}.{ln.src_port}" for ln in links if ln.dst_module == m.id}
    if mine:
        args.append(f"links={_q(mine)}")
    # where it came from in the library and where it sits on the canvas are kept in the
    # graph, not written here (parse reads them if a file has them)
    one = f"@module({', '.join(args)})"
    if len(one) <= 100:
        return one
    return "@module(\n" + "".join(f"    {a},\n" for a in args) + ")"


def changed_knobs(graph: StrategyGraph) -> dict[str, Any]:
    knobs = graph.knobs()
    return {k: v for k, v in graph.knob_values.items() if k in knobs and v != knobs[k].default}


def generate(graph: StrategyGraph) -> str:
    """The graph as one Python file."""
    parts = [f'"""{(graph.doc or graph.name).replace(chr(34) * 3, "")}"""', SDK_IMPORT]
    if graph.preamble.strip():
        parts.append(graph.preamble.strip("\n"))
    parts.append(f"SETTINGS = {_py(graph.settings)}")
    knobs = changed_knobs(graph)
    if knobs:
        parts.append(f"KNOBS = {_py(knobs)}")
    head = "\n\n".join(parts) + "\n"
    names = _unique_function_names(graph)
    blocks = []
    for m in graph.modules:
        code = m.code.strip("\n")
        old = function_name(m.code)
        if names[m.id] != old:
            code = _rename_def(code, old, names[m.id])
        blocks.append(decorator(m, graph.links, names[m.id]) + "\n" + code + "\n")
    return head + "".join("\n\n" + b for b in blocks)


# ---------------------------------------------------------------- file -> graph
def _segment(lines: list[str], node: ast.stmt, lo_limit: int) -> tuple[int, int]:
    """1-based line span of a statement, its decorators, and the comment lines right above it."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    while start - 1 > lo_limit and lines[start - 2].lstrip().startswith("#"):
        start -= 1
    return start, node.end_lineno or node.lineno


def _module_decorator(node: ast.stmt) -> ast.Call | None:
    for d in getattr(node, "decorator_list", []):
        f = d.func if isinstance(d, ast.Call) else d
        if getattr(f, "id", getattr(f, "attr", None)) == "module":
            return d if isinstance(d, ast.Call) else ast.Call(func=d, args=[], keywords=[])
    return None


def _is_sdk_import(node: ast.stmt) -> bool:
    return isinstance(node, ast.ImportFrom) and node.module in SDK_MODULES


def _assigns(node: ast.stmt, name: str) -> bool:
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


def _literal_dict(node: ast.Assign, name: str) -> dict:
    try:
        out = ast.literal_eval(node.value)
    except (ValueError, SyntaxError):
        raise StrategyCodeError(f"{name} must hold plain values (numbers, text, lists, dicts)", node.lineno) from None
    if not isinstance(out, dict):
        raise StrategyCodeError(f"{name} must be a dict", node.lineno)
    return out


def _join(pieces: list[tuple[int, int, str, bool]], lines: list[str]) -> str:
    """Shared code: functions and classes set apart by two blank lines; simple statements keep
    the gap they had (none or one blank line)."""
    out = ""
    prev: tuple[int, int, str, bool] | None = None
    for piece in pieces:
        start, _, text, compound = piece
        if prev is not None:
            if compound or prev[3]:
                out += "\n\n\n"
            else:
                gap = lines[prev[1]:start - 1]
                out += "\n\n" if gap and all(not ln.strip() for ln in gap) else "\n" if not gap else "\n\n"
        out += text
        prev = piece
    return out


def parse(src: str, previous: StrategyGraph | None = None, id: str | None = None,
          name: str | None = None) -> StrategyGraph:
    """Read a strategy file into a graph.

    ``previous`` is the graph the file was generated from: the strategy's id and
    name, and what the file does not hold (port docs) are kept from it.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise StrategyCodeError(e.msg or "invalid Python", e.lineno or 0) from None
    lines = src.splitlines()
    body = list(tree.body)
    doc = ""
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        doc = body[0].value.value.strip()
        body = body[1:]

    settings: dict = {}
    knob_values: dict = {}
    funcs: list[tuple[ast.stmt, str]] = []  # module candidates with their source (decorator removed)
    shared: list[tuple[ast.stmt, str, bool]] = []
    spans: dict[ast.stmt, tuple[int, int]] = {}
    prev_end = 0
    for node in body:
        start, end = _segment(lines, node, prev_end)
        text = "\n".join(lines[start - 1:end])
        prev_end = end
        spans[node] = (start, end)
        if _is_sdk_import(node):
            continue
        if _assigns(node, "SETTINGS"):
            settings = _literal_dict(node, "SETTINGS")
        elif _assigns(node, "KNOBS"):
            knob_values = _literal_dict(node, "KNOBS")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            dec = _module_decorator(node)
            if dec is not None:
                drop = set(range(dec.lineno, (dec.end_lineno or dec.lineno) + 1))
                text = "\n".join(ln for i, ln in enumerate(lines[start - 1:end], start) if i not in drop)
            funcs.append((node, text))
        else:
            shared.append((node, text, isinstance(node, (ast.ClassDef, ast.If, ast.For, ast.While, ast.With, ast.Try))))

    decorated = [(n, t) for n, t in funcs if _module_decorator(n) is not None]
    if decorated:
        mods_src = decorated
        helpers = [(n, t) for n, t in funcs if _module_decorator(n) is None]
    elif funcs:  # a plain file: its decide() (or its last function) is the one module
        entry = next(((n, t) for n, t in funcs if n.name == "decide"), funcs[-1])
        mods_src = [entry]
        helpers = [(n, t) for n, t in funcs if n is not entry[0]]
    else:
        mods_src, helpers = [], []
    pieces = sorted([(n, t, c) for n, t, c in shared] + [(n, t, True) for n, t in helpers],
                    key=lambda x: x[0].lineno)
    preamble = _join([(*spans[n], t, c) for n, t, c in pieces], lines)
    # the import lines the app writes itself are not part of the user's shared code
    preamble = "\n".join(ln for ln in preamble.splitlines()
                         if not re.match(r"\s*from\s+(titanium|honestbt)\.sdk\s+import\b", ln)).strip("\n")

    prev_mods = {m.id: m for m in previous.modules} if previous else {}
    modules: list[Module] = []
    links: list[Link] = []
    for node, text in mods_src:
        dec = _module_decorator(node)
        kw: dict[str, Any] = {}
        if dec is not None:
            for k in dec.keywords:
                try:
                    kw[k.arg] = ast.literal_eval(k.value)
                except (ValueError, SyntaxError):
                    raise StrategyCodeError(f"@module({k.arg}=...) must be a plain value", k.value.lineno) from None
            if dec.args:
                try:
                    kw.setdefault("id", ast.literal_eval(dec.args[0]))
                except (ValueError, SyntaxError):
                    pass
        plain = dec is None
        mid = str(kw.get("id") or node.name)
        if any(m.id == mid for m in modules):
            raise StrategyCodeError(f"two modules have the id {mid!r}", node.lineno)
        kind = str(kw.get("kind") or ("decide" if plain or node.name == "decide" else "transform"))
        outs = kw.get("outputs")
        m = module_from_code(text, mid, kind, kw.get("name") or node.name,
                             list(outs) if outs is not None else None, str(kw.get("source", "")))
        old = prev_mods.get(mid)
        if old is not None:
            idocs = {p.name: p.doc for p in old.inputs}
            odocs = {p.name: p.doc for p in old.outputs}
            m.inputs = [Port(p.name, idocs.get(p.name, "")) for p in m.inputs]
            m.outputs = [Port(p.name, odocs.get(p.name, "")) for p in m.outputs]
            m.source = m.source or old.source
            m.layout = old.layout
            m.knobs = [replace(k, doc=k.doc or next((o.doc for o in old.knobs if o.name == k.name), ""))
                       for k in m.knobs]
        lay = kw.get("layout")
        if lay is not None:
            m.layout = (float(lay[0]), float(lay[1]))
        modules.append(m)
        for port, ref in (kw.get("links") or {}).items():
            src_mod, _, src_port = str(ref).rpartition(".")
            if not src_mod:
                src_mod, src_port = src_port, DEFAULT_OUTPUT
            links.append(Link(src_mod, src_port, mid, str(port)))

    _check_links(modules, links)
    graph = StrategyGraph(id=id or (previous.id if previous else "S1"),
                          name=name or (previous.name if previous else (doc.splitlines()[0] if doc else "Strategy")),
                          modules=modules, links=links, settings=settings, doc=doc, preamble=preamble)
    knobs = graph.knobs()
    graph.knob_values = {k: _coerce(v, knobs[k].default) for k, v in knob_values.items() if k in knobs}
    return graph


def _check_links(modules: list[Module], links: list[Link]) -> None:
    by_id = {m.id: m for m in modules}
    for ln in links:
        dst = by_id[ln.dst_module]
        if ln.dst_port not in {p.name for p in dst.inputs}:
            raise StrategyCodeError(f"module {dst.id!r} links {ln.dst_port!r}, which is not one of its inputs")
        src = by_id.get(ln.src_module)
        if src is None:
            raise StrategyCodeError(f"module {dst.id!r} links to {ln.src_module!r}, which is not a module")
        if ln.src_port not in {p.name for p in src.outputs}:
            raise StrategyCodeError(f"module {src.id!r} has no output {ln.src_port!r}")


def import_python(src: str, id: str, name: str | None = None) -> StrategyGraph:
    """A Python strategy file as a graph (a plain ``decide(F, p)`` file becomes one module)."""
    return parse(src, id=id, name=name)


def update_from_code(graph: StrategyGraph, src: str) -> StrategyGraph:
    """The graph after an edit in the code view: same id and name, everything else from the file."""
    return parse(src, previous=graph, id=graph.id, name=graph.name)


# ---------------------------------------------------------------- "Make knob"
def _offset(lines: list[str], line: int, col: int) -> int:
    return sum(len(ln) for ln in lines[:line - 1]) + col


def make_knob(src: str, line: int, col: int, name: str | None = None) -> tuple[str, str]:
    """Turn the number (or True/False) at ``line``/``col`` (1-based line, 0-based column) into a knob.

    Returns the new source and the knob's name. Raises :class:`StrategyCodeError`
    when there is no number there, or it is not inside a module's function.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as e:
        raise StrategyCodeError(f"fix the code first ({e})") from None
    hit = None
    for i, tok in enumerate(tokens):
        (sl, sc), (el, ec) = tok.start, tok.end
        is_value = tok.type == tokenize.NUMBER or (tok.type == tokenize.NAME and tok.string in ("True", "False"))
        if is_value and sl == line and sc <= col <= ec:
            hit = i
            break
    if hit is None:
        raise StrategyCodeError("put the cursor on a number, True or False", line)
    tok = tokens[hit]
    value = ast.literal_eval(tok.string)
    if isinstance(value, complex):
        raise StrategyCodeError("complex numbers can't be knobs", line)
    prev = tokens[hit - 1] if hit > 0 else None
    before = tokens[hit - 2] if hit > 1 else None
    neg = prev is not None and prev.string == "-" and (
        before is None or before.string in ("=", "(", ",", "[", "{", ":", "return")
        or before.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT))
    start = tokens[hit - 1].start if neg else tok.start
    if neg:
        value = -value

    graph = parse(src)
    tree = ast.parse(src)
    fn_node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.lineno <= line <= (n.end_lineno or n.lineno)), None)
    if fn_node is None:
        raise StrategyCodeError("knobs live inside a module's function", line)
    owner = next((m for m in graph.modules if function_name(m.code) == fn_node.name), None)
    if owner is None:
        raise StrategyCodeError(f"{fn_node.name}() is shared code, not a module; knobs go inside modules", line)
    for node in ast.walk(fn_node):
        if _is_knob_call(node) and node.lineno <= line <= (node.end_lineno or node.lineno) \
                and node.col_offset <= col <= (node.end_col_offset or 0):
            raise StrategyCodeError("that number is already part of a knob", line)

    if name is None:
        j = (hit - 2) if neg else (hit - 1)
        if j >= 1 and tokens[j].string == "=" and tokens[j - 1].type == tokenize.NAME:
            name = tokens[j - 1].string
        else:
            name = "value" if not isinstance(value, bool) else "switch"
    taken = {k.name for k in owner.knobs}
    base, n = name, 2
    while name in taken:
        name, n = f"{base}_{n}", n + 1

    if isinstance(value, bool):
        call = f'knob("{name}", {value})'
    else:
        lo, hi = default_range(value)
        call = f'knob("{name}", {value!r}, lo={lo!r}, hi={hi!r})'
    lines = src.splitlines(keepends=True)
    a = _offset(lines, start[0], start[1])
    b = _offset(lines, tok.end[0], tok.end[1])
    return src[:a] + call + src[b:], name
