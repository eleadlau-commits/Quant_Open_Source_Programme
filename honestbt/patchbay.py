"""The patch bay: a JSON config that wires plugins into a strategy family.

    features   named feature nodes   {"vol20": {"plugin": "realized_vol", "params": {"window": 20}}}
    mappings   named patch cables    {"k_vol": {"plugin": "linear", "input": "vol20", "params": {...}}}
    strategy   one strategy node     {"plugin": "weekly_topn", "params": {...}}
    sweep      family axes           {"strategy.params.exit.params.k": [0.5, 1, 2]}

Anywhere inside strategy params you can write ``{"$map": "k_vol"}`` or
``{"$feature": "vol20"}``; it is resolved *per symbol at decision time* through
the guarded view. A mapping's ``input`` may name a feature or another mapping.
Sweep axes are dotted paths into the config, so you can sweep any number,
including a mapping's own parameters.
"""
from __future__ import annotations

import copy
import itertools
import json
from typing import Any

import numpy as np

from .data.guard import GuardedView
from .registry import get, has


class ConfigError(ValueError):
    pass


class Resolver:
    """Evaluates features/mappings for one decision time (one guarded view)."""

    def __init__(self, config: dict, view: GuardedView, cache: dict | None = None):
        self.features = config.get("features", {})
        self.mappings = config.get("mappings", {})
        self.view = view
        self._cache = cache if cache is not None else {}

    def feature(self, name: str, symbol: str) -> float:
        spec = self.features.get(name)
        if spec is None:
            if not has("feature", name):
                raise ConfigError(f"unknown feature {name!r}: define it under 'features' or use a plugin name")
            spec = {"plugin": name}
        key = ("f", json.dumps(spec, sort_keys=True), symbol, int(self.view.as_of.astype(np.int64)))
        if key not in self._cache:
            fn = get("feature", spec["plugin"])
            self._cache[key] = float(fn(self.view, symbol, **spec.get("params", {})))
        return self._cache[key]

    def mapping(self, name: str, symbol: str, _depth: int = 0) -> float:
        if _depth > 20:
            raise ConfigError("mapping chain too deep (cycle?)")
        spec = self.mappings.get(name)
        if spec is None:
            raise ConfigError(f"unknown mapping {name!r}")
        src = spec.get("input")
        if src is None:
            x = float("nan")
        elif src in self.mappings:
            x = self.mapping(src, symbol, _depth + 1)
        else:
            x = self.feature(src, symbol)
        fn = get("mapping", spec["plugin"])
        return fn(x, **spec.get("params", {}))

    def resolve(self, obj: Any, symbol: str) -> Any:
        """Replace $map / $feature references with concrete values for ``symbol``."""
        if isinstance(obj, dict):
            if set(obj) == {"$map"}:
                return self.mapping(obj["$map"], symbol)
            if set(obj) == {"$feature"}:
                return self.feature(obj["$feature"], symbol)
            return {k: self.resolve(v, symbol) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.resolve(v, symbol) for v in obj]
        return obj


def set_path(cfg: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    node = cfg
    for k in keys[:-1]:
        if isinstance(node, list):
            node = node[int(k)]
        else:
            node = node.setdefault(k, {})
    if isinstance(node, list):
        node[int(keys[-1])] = value
    else:
        node[keys[-1]] = value


def get_path(cfg: dict, dotted: str, default=None):
    node = cfg
    for k in dotted.split("."):
        try:
            node = node[int(k)] if isinstance(node, list) else node[k]
        except (KeyError, IndexError, ValueError, TypeError):
            return default
    return node


def with_overrides(cfg: dict, overrides: dict[str, Any]) -> dict:
    out = copy.deepcopy(cfg)
    for k, v in overrides.items():
        set_path(out, k, v)
    return out


def expand_sweep(cfg: dict) -> list[tuple[dict, dict]]:
    """Cartesian product of sweep axes -> [(point, concrete_config), ...]."""
    axes = cfg.get("sweep") or {}
    if not axes:
        return [({}, copy.deepcopy(cfg))]
    names = list(axes)
    out = []
    for combo in itertools.product(*(axes[n] for n in names)):
        point = dict(zip(names, combo))
        out.append((point, with_overrides(cfg, point)))
    return out


def validate(cfg: dict) -> list[str]:
    """Cheap static checks; returns a list of problems (empty = fine)."""
    problems = []
    for section, kind in (("features", "feature"), ("mappings", "mapping")):
        for name, spec in (cfg.get(section) or {}).items():
            if not has(kind, spec.get("plugin", "")):
                problems.append(f"{section}.{name}: unknown {kind} plugin {spec.get('plugin')!r}")
    for name, spec in (cfg.get("mappings") or {}).items():
        src = spec.get("input")
        if src and src not in (cfg.get("mappings") or {}) and src not in (cfg.get("features") or {}) and not has("feature", src):
            problems.append(f"mappings.{name}: input {src!r} is not a feature or mapping")
    strat = cfg.get("strategy") or {}
    if not has("strategy", strat.get("plugin", "")):
        problems.append(f"strategy: unknown plugin {strat.get('plugin')!r}")
    for ev in cfg.get("evaluators") or []:
        if not has("evaluator", ev.get("plugin", "")):
            problems.append(f"evaluators: unknown plugin {ev.get('plugin')!r}")
    for path in cfg.get("sweep") or {}:
        if get_path(cfg, path, default=KeyError) is KeyError:
            problems.append(f"sweep: path {path!r} does not exist in the config")
    return problems
