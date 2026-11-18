"""Edits the desktop app makes to a settings dict when you build a strategy in the patch bay.

Pure functions on plain dicts (no Qt), so they are easy to test. Each returns a
new dict and leaves the one passed in untouched.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..patchbay import get_path, set_path
from ..registry import catalog

SECTION = {"feature": "features", "mapping": "mappings"}


def _info(kind: str, name: str) -> dict | None:
    return next((it for it in catalog().get(kind, []) if it["name"] == name), None)


def default_params(kind: str, name: str) -> dict:
    """A plugin's settings with their defaults (settings without a default are left out)."""
    info = _info(kind, name)
    return {p["name"]: copy.deepcopy(p["default"]) for p in (info or {}).get("params", []) if p["default"] is not None}


def _spec(kind: str, name: str) -> dict:
    params = default_params(kind, name)
    return {"plugin": name, "params": params} if params else {"plugin": name}


def _unique(existing, base: str) -> str:
    if base not in existing:
        return base
    i = 2
    while f"{base}{i}" in existing:
        i += 1
    return f"{base}{i}"


def add(cfg: dict, kind: str, name: str) -> tuple[dict, str]:
    """Add plugin ``name`` of ``kind`` to the settings. Returns (new settings, where it went)."""
    out = copy.deepcopy(cfg)
    if kind in SECTION:
        section = out.setdefault(SECTION[kind], {})
        key = _unique(set(out.get("features") or {}) | set(out.get("mappings") or {}), name)
        spec = _spec(kind, name)
        if kind == "mapping":
            feats = list(out.get("features") or {})
            spec = {"plugin": name, "input": feats[0] if feats else None, **{k: v for k, v in spec.items() if k != "plugin"}}
        section[key] = spec
        return out, f"{SECTION[kind]}.{key}"
    if kind == "signal":
        out.setdefault("strategy", {}).setdefault("params", {})["exit"] = _spec(kind, name)
        return out, "strategy.params.exit"
    if kind == "evaluator":
        evs = out.get("evaluators") or []
        out["evaluators"] = (evs if isinstance(evs, list) else [evs]) + [_spec(kind, name)]
        return out, "evaluators"
    if kind == "data":
        out["data"] = _spec(kind, name)
        return out, "data"
    if kind == "strategy":
        old = (out.get("strategy") or {}).get("params") or {}
        spec = _spec(kind, name)
        keep = {k: v for k, v in old.items() if k in spec.get("params", {})}  # same-named settings carry over
        spec.setdefault("params", {}).update(keep)
        out["strategy"] = spec
        out["sweep"] = {p: v for p, v in (out.get("sweep") or {}).items() if get_path(out, p, KeyError) is not KeyError}
        return out, "strategy"
    raise ValueError(f"can't add a {kind} plugin here")


def remove(cfg: dict, kind: str, key: str) -> dict:
    """Take a feature or mapping out of the settings."""
    out = copy.deepcopy(cfg)
    (out.get(SECTION[kind]) or {}).pop(key, None)
    (out.get(LAYOUT) or {}).pop(f"{kind[0]}:{key}", None)
    return out


def set_input(cfg: dict, mapping: str, source: str) -> dict:
    """Plug a feature (or another mapping) into a mapping's input."""
    out = copy.deepcopy(cfg)
    out["mappings"][mapping]["input"] = source
    return out


def wire(cfg: dict, path: str, value) -> dict:
    """Set one setting, e.g. wire("strategy.params.exit.params.k", {"$map": "k_from_vol"})."""
    out = copy.deepcopy(cfg)
    set_path(out, path, value)
    return out


def strategy_slots(cfg: dict) -> tuple[list[str], list[str]]:
    """Strategy (and exit) settings you can plug into: (feature-name slots, number slots), as dotted paths."""
    strat = cfg.get("strategy") or {}
    feat, num = [], []
    for base, kind, spec in (("strategy.params", "strategy", strat),
                             ("strategy.params.exit.params", "signal", (strat.get("params") or {}).get("exit") or {})):
        info = _info(kind, spec.get("plugin", "")) if isinstance(spec, dict) else None
        for p in (info or {}).get("params", []):
            if p["type"] == "str" and (p["name"] == "rank_by" or p["name"].endswith("_feature")):
                feat.append(f"{base}.{p['name']}")
            elif p["type"] in ("float", "int"):
                num.append(f"{base}.{p['name']}")
    return feat, num


def new_config(strategy: str, examples: list[Path] = ()) -> dict:
    """Starting settings for a new strategy: a copy of a shipped example that uses this strategy
    plugin if there is one (so it runs straight away), otherwise the plugin's defaults."""
    for path in examples:
        try:
            cfg = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        if (cfg.get("strategy") or {}).get("plugin") == strategy:
            cfg["name"] = f"My {strategy.replace('_', ' ')} strategy"
            return cfg
    data = next((it["name"] for it in catalog().get("data", []) if it["name"].startswith("synthetic")), "synthetic")
    return {"name": f"My {strategy.replace('_', ' ')} strategy", "data": _spec("data", data), "features": {},
            "mappings": {}, "strategy": _spec("strategy", strategy), "sweep": {},
            "evaluators": [{"plugin": "out_of_sample", "params": {"split": 0.6}}, {"plugin": "bootstrap"}]}


# ---- used by the interactive patch bay

LAYOUT = "patchbay_layout"  # box positions, saved in the settings file; the backtest ignores it


def slot_default(cfg: dict, path: str):
    """The plugin default for a strategy or exit setting (what unplugging puts back)."""
    if path.startswith("strategy.params.exit.params."):
        kind, spec = "signal", ((cfg.get("strategy") or {}).get("params") or {}).get("exit") or {}
    else:
        kind, spec = "strategy", cfg.get("strategy") or {}
    return copy.deepcopy(default_params(kind, spec.get("plugin", "")).get(path.split(".")[-1]))


def unplug(cfg: dict, path: str) -> dict:
    """Pull a cable out: a mapping's input becomes empty, a setting goes back to its default."""
    out = copy.deepcopy(cfg)
    if path.startswith("mappings.") and path.endswith(".input"):
        out["mappings"][path.split(".")[1]]["input"] = None
        return out
    default = slot_default(cfg, path)
    if default is None:
        parent = get_path(out, path.rsplit(".", 1)[0])
        if isinstance(parent, dict):
            parent.pop(path.split(".")[-1], None)
        return out
    set_path(out, path, default)
    return out


def feeds(cfg: dict, mapping: str) -> set[str]:
    """Every mapping upstream of ``mapping`` (itself included), to refuse loops."""
    seen, todo = set(), [mapping]
    maps = cfg.get("mappings") or {}
    while todo:
        m = todo.pop()
        if m in seen or m not in maps:
            continue
        seen.add(m)
        todo.append(maps[m].get("input"))
    return seen


def connect(cfg: dict, source: tuple[str, str], target: str) -> tuple[dict | None, str]:
    """Plug ``source`` = ("f"|"m", name) into input ``target`` (a dotted path).

    Returns (new settings, what happened) or (None, why it can't be plugged there).
    """
    kind, name = source
    if target.startswith("mappings.") and target.endswith(".input"):
        m = target.split(".")[1]
        if kind == "m" and m in feeds(cfg, name):
            return None, f"Can't plug '{name}' into '{m}': that would make a loop."
        return set_input(cfg, m, name), f"Mapping '{m}' now takes '{name}'."
    feat_slots, num_slots = strategy_slots(cfg)
    label = target.replace("strategy.params.", "").replace("exit.params.", "exit ")
    if target in feat_slots:
        if kind != "f":
            return None, f"'{label}' needs a feature (a blue box), not a mapping."
        return wire(cfg, target, name), f"{label} now uses feature '{name}'."
    if target in num_slots:
        ref = {"$map": name} if kind == "m" else {"$feature": name}
        return wire(cfg, target, ref), f"{label} now follows '{name}', worked out per symbol at decision time."
    return None, f"'{label}' can't take a cable."


def remove_evaluator(cfg: dict, index: int) -> dict:
    out = copy.deepcopy(cfg)
    evs = out.get("evaluators") or []
    if isinstance(evs, list) and 0 <= index < len(evs):
        evs.pop(index)
    return out


def add_sweep(cfg: dict, path: str) -> tuple[dict, str]:
    """Make a setting a sweep axis: half, the same and one and a half times its value."""
    out = copy.deepcopy(cfg)
    v = get_path(out, path)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return out, f"Only number settings can be swept from here; edit 'sweep' in the JSON for {path}."
    vals = [v * 0.5, v, v * 1.5]
    vals = sorted({max(1, round(x)) for x in vals}) if isinstance(v, int) else [round(x, 6) for x in vals]
    out.setdefault("sweep", {})[path] = vals
    return out, f"Sweeping {path} over {vals}."


def set_positions(cfg: dict, positions: dict[str, list[float]]) -> dict:
    out = copy.deepcopy(cfg)
    lay = dict(out.get(LAYOUT) or {})
    lay.update({k: [round(x), round(y)] for k, (x, y) in positions.items()})
    out[LAYOUT] = lay
    return out


def clear_layout(cfg: dict) -> dict:
    out = copy.deepcopy(cfg)
    out.pop(LAYOUT, None)
    return out
