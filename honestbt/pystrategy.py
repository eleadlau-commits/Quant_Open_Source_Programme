"""Strategies written as one Python file.

A strategy file says what to hold, as a step function of time: at each decision
time t_j it sees F(t_j) (all data up to t_j, through a look-ahead-guarded view)
and its current positions p, and returns the positions it wants::

    '''Hold stocks above their moving average.'''
    from honestbt.sdk import knob

    SETTINGS = {
        "data": {"plugin": "synthetic", "params": {"n_symbols": 40, "n_days": 130}},
        "decide_at": "15:50",          # each trading day at this time (exchange clock)
        "every": "day",                # "day" or "week" (first trading day of the week)
        "evaluators": [{"plugin": "bootstrap"}],
    }

    def average(F, symbol, n):         # Data -> Data module
        c = F.daily(symbol).close
        return c[-n:].mean() if len(c) >= n else None

    def decide(F, p):                  # Data -> Buy/Sell module: returns target positions
        n = knob("n", 50, lo=5, hi=200)
        ...
        return {"AAA": 0.5, "BBB": 0.5}   # fraction of the account per symbol, negative = short

Modules are plain functions taking ``F`` (and ``p`` if they need it). ``knob(name,
default, lo, hi)`` marks a value you can turn on the Measurements page without
editing the code. ``SETTINGS`` is read without running the file.
"""
from __future__ import annotations

import ast
import math
import re
from contextvars import ContextVar
from typing import Any

_KNOBS: ContextVar[dict | None] = ContextVar("titanium_knobs", default=None)

KNOWN = {"data", "decide_at", "every", "costs", "evaluators", "name", "max_gross", "start", "end"}
TEMPLATE = '''"""{name}"""
from honestbt.sdk import knob

SETTINGS = {settings}


def momentum(F, symbol, days):
    """Data -> Data: return over the last `days` completed days."""
    c = F.daily(symbol).close
    return c[-1] / c[-days - 1] - 1 if len(c) > days else None


def decide(F, p):
    """Data -> Buy/Sell: hold the strongest names, equal weight."""
    days = knob("days", 20, lo=5, hi=120)
    top = knob("top", 5, lo=1, hi=20)
    scores = {{}}
    for s in F.universe():
        m = momentum(F, s, days)
        if m is not None and m > 0:
            scores[s] = m
    best = sorted(scores, key=scores.get, reverse=True)[:top]
    return {{s: 1 / len(best) for s in best}}
'''


class StrategyFileError(ValueError):
    pass


def knob(name: str, default, lo=None, hi=None):
    """A value you can turn without editing the code. Returns the current setting (or ``default``)."""
    vals = _KNOBS.get()
    if vals is not None and name in vals:
        v = vals[name]
        return type(default)(v) if isinstance(default, (int, float)) and not isinstance(default, bool) else v
    return default


# ---------------------------------------------------------------- reading the file
def settings(src: str) -> dict:
    """The ``SETTINGS = {...}`` dict, read without running the file."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise StrategyFileError(f"Python error on line {e.lineno}: {e.msg}") from None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SETTINGS" for t in node.targets):
            try:
                out = ast.literal_eval(node.value)
            except ValueError:
                raise StrategyFileError("SETTINGS must be plain values (numbers, text, lists, dicts)") from None
            if not isinstance(out, dict):
                raise StrategyFileError("SETTINGS must be a dict")
            return out
    return {}


def docstring(src: str) -> str:
    try:
        return (ast.get_docstring(ast.parse(src)) or "").strip().splitlines()[0] if src.strip() else ""
    except (SyntaxError, IndexError):
        return ""


def knobs(src: str) -> list[dict]:
    """Every ``knob("name", default, lo=..., hi=...)`` call with literal arguments, in file order."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out, seen = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "knob":
            try:
                args = [ast.literal_eval(a) for a in node.args]
                kw = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
            except ValueError:
                continue
            name = args[0] if args else kw.get("name")
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            default = args[1] if len(args) > 1 else kw.get("default")
            lo = args[2] if len(args) > 2 else kw.get("lo")
            hi = args[3] if len(args) > 3 else kw.get("hi")
            if isinstance(default, (int, float)) and not isinstance(default, bool):
                lo = default / 4 if lo is None else lo
                hi = default * 4 if hi is None and default else (1 if hi is None else hi)
            out.append({"name": name, "default": default, "lo": lo, "hi": hi, "line": node.lineno,
                        "int": isinstance(default, int) and not isinstance(default, bool)})
    return sorted(out, key=lambda k: k["line"])


def modules(src: str) -> list[dict]:
    """The file's modules for the patch bay: top-level functions, their kind and the knobs inside."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names = [k["name"] for k in knobs(ast.unparse(node))]
            calls = sorted({c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)})
            out.append({"name": node.name, "kind": "Data → Buy/Sell" if node.name == "decide" else "Data → Data",
                        "args": [a.arg for a in node.args.args], "knobs": names, "calls": calls,
                        "doc": (ast.get_docstring(node) or "").strip().split("\n")[0], "line": node.lineno})
    return out


def check(src: str) -> list[str]:
    problems = []
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"Python error on line {e.lineno}: {e.msg}"]
    if not any(isinstance(n, ast.FunctionDef) and n.name == "decide" for n in tree.body):
        problems.append("the file needs a function decide(F, p) that returns the positions to hold")
    try:
        st = settings(src)
    except StrategyFileError as e:
        return problems + [str(e)]
    if "data" not in st:
        problems.append("SETTINGS needs a 'data' entry (which dataset to run on)")
    unknown = sorted(set(st) - KNOWN)
    if unknown:
        problems.append(f"SETTINGS: unknown entries {unknown} (known: {sorted(KNOWN)})")
    every = st.get("every", "day")
    if every not in ("day", "week"):
        problems.append("SETTINGS 'every' must be 'day' or 'week'")
    if not re.fullmatch(r"\d{1,2}:\d{2}", str(st.get("decide_at", "15:50"))):
        problems.append("SETTINGS 'decide_at' must be HH:MM")
    return problems


def load(src: str) -> dict[str, Any]:
    """Run the file and return its namespace (its own code, like a plugin)."""
    ns: dict[str, Any] = {"__name__": "titanium_strategy"}
    exec(compile(src, "<strategy>", "exec"), ns)
    if not callable(ns.get("decide")):
        raise StrategyFileError("the file needs a function decide(F, p)")
    return ns


# ---------------------------------------------------------------- the file as settings
def to_config(src: str) -> dict:
    """The settings the engine and tests use: SETTINGS, plus the code itself as the strategy."""
    st = settings(src)
    cfg = {k: v for k, v in st.items() if k in ("data", "costs", "evaluators", "name")}
    cfg.setdefault("name", docstring(src) or "Python strategy")
    params = {k: st[k] for k in ("decide_at", "every", "max_gross", "start", "end") if k in st}
    cfg["strategy"] = {"plugin": "python", "params": {**params, "code": src, "knobs": {}}}
    return cfg


def set_settings(src: str, new: dict) -> str:
    """Rewrite the ``SETTINGS = {...}`` block (or add one after the imports)."""
    text = "SETTINGS = " + _pretty(new)
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SETTINGS" for t in node.targets):
            a, b = node.lineno - 1, node.end_lineno
            return "".join(lines[:a]) + text + "\n" + "".join(lines[b:])
    after = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            after = node.end_lineno
        else:
            break
    return "".join(lines[:after]) + "\n" + text + "\n" + "".join(lines[after:])


def _pretty(obj, indent=0) -> str:
    pad = "    " * (indent + 1)
    if isinstance(obj, dict) and obj:
        inner = ",\n".join(f"{pad}{k!r}: {_pretty(v, indent + 1)}" for k, v in obj.items())
        return "{\n" + inner + ",\n" + "    " * indent + "}"
    if isinstance(obj, list) and obj and any(isinstance(x, (dict, list)) for x in obj):
        inner = ",\n".join(f"{pad}{_pretty(v, indent + 1)}" for v in obj)
        return "[\n" + inner + ",\n" + "    " * indent + "]"
    return repr(obj)


def new_file(name: str, data: dict | None = None) -> str:
    st = {"data": data or {"plugin": "synthetic", "params": {"n_symbols": 40, "n_days": 130, "seed": 7}},
          "decide_at": "15:50", "every": "week",
          "evaluators": [{"plugin": "bootstrap"}, {"plugin": "cost_stress", "params": {"multiplier": 2}}]}
    return TEMPLATE.format(name=name, settings=_pretty(st))


# ---------------------------------------------------------------- making a value a knob
def make_knob(src: str, line: int, col: int, name: str | None = None) -> tuple[str, str]:
    """Turn the number at (line, col) (1-based line, 0-based column) into ``knob("name", value)``.

    The name comes from the variable it is assigned to, else ``name``, else ``k<line>``.
    Returns (new source, knob name). Raises StrategyFileError if there is no plain number there.
    """
    tree = ast.parse(src)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    hit = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
                and node.lineno == line and node.col_offset <= col <= node.end_col_offset):
            hit = node
            break
    if hit is None:
        raise StrategyFileError("put the cursor on a number to make it a knob")
    par = parents.get(hit)
    if isinstance(par, ast.UnaryOp) and isinstance(par.op, ast.USub):  # -0.5 -> the whole negative number
        hit, value = par, -hit.value
        par = parents.get(par)
    else:
        value = hit.value
    if isinstance(par, ast.Call) and getattr(par.func, "id", None) == "knob":
        raise StrategyFileError("that number is already a knob")
    if name is None:
        if isinstance(par, ast.Assign) and len(par.targets) == 1 and isinstance(par.targets[0], ast.Name):
            name = par.targets[0].id
        elif isinstance(par, ast.keyword) and par.arg:
            name = par.arg
        else:
            name = f"k{line}"
    taken = {k["name"] for k in knobs(src)}
    base, i = name, 2
    while name in taken:
        name, i = f"{base}{i}", i + 1
    if isinstance(value, int):
        lo, hi = (0, max(1, value * 4)) if value >= 0 else (value * 4, 0)
    else:
        lo, hi = sorted((value / 4, value * 4)) if value else (-1.0, 1.0)
        lo, hi = _nice(lo), _nice(hi)
    call = f'knob("{name}", {value!r}, lo={lo!r}, hi={hi!r})'
    lines = src.splitlines(keepends=True)
    row = lines[hit.lineno - 1]
    lines[hit.lineno - 1] = row[:hit.col_offset] + call + row[hit.end_col_offset:]
    out = "".join(lines)
    if not re.search(r"^\s*from honestbt\.sdk import .*\bknob\b", out, re.M):
        out = "from honestbt.sdk import knob\n" + out if not out.startswith('"""') else _after_doc(out)
    return out, name


def _after_doc(src: str) -> str:
    tree = ast.parse(src)
    end = tree.body[0].end_lineno
    lines = src.splitlines(keepends=True)
    return "".join(lines[:end]) + "from honestbt.sdk import knob\n" + "".join(lines[end:])


def _nice(x: float) -> float:
    if x == 0:
        return 0.0
    mag = 10 ** math.floor(math.log10(abs(x)))
    return round(x / mag, 1) * mag


def set_knob_default(src: str, name: str, value) -> str:
    """Write a knob's current value back into the code as its default."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "knob" and len(node.args) > 1
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == name):
            arg = node.args[1]
            lines = src.splitlines(keepends=True)
            if arg.lineno != arg.end_lineno:
                break
            row = lines[arg.lineno - 1]
            lines[arg.lineno - 1] = row[:arg.col_offset] + repr(value) + row[arg.end_col_offset:]
            return "".join(lines)
    return src
