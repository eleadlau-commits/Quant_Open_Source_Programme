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
