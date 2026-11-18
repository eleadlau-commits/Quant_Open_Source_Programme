"""Plugin registry.

Every extension point in the core is a *plugin kind*. A plugin is a plain
function or class registered under a name, with a declared parameter list so
the web UI can render a form for it and the patch bay can validate configs.

Kinds
-----
data       -> callable(**params) -> MarketData
feature    -> callable(view, symbol, **params) -> float      (known at view.as_of)
mapping    -> callable(x, **params) -> float                  (pure function, a "patch cable")
signal     -> callable(path, ctx, **params) -> np.ndarray[bool]  (must be causal)
strategy   -> class with decision_times / max_exit_time / decide
evaluator  -> callable(ectx, **params) -> Verdict

Third-party packages can add plugins via the ``honestbt.plugins`` entry-point
group; each entry point is imported and its decorators register themselves.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable

KINDS = ("data", "feature", "mapping", "signal", "strategy", "evaluator")
_REGISTRY: dict[str, dict[str, Any]] = {k: {} for k in KINDS}


@dataclass
class Param:
    name: str
    type: str = "float"  # float | int | str | bool | json
    default: Any = None
    doc: str = ""
    choices: list[Any] | None = None


@dataclass
class PluginInfo:
    kind: str
    name: str
    doc: str
    params: list[Param] = field(default_factory=list)


def register(kind: str, name: str, params: list[Param] | tuple = (), doc: str = "") -> Callable:
    if kind not in KINDS:
        raise ValueError(f"unknown plugin kind {kind!r}; expected one of {KINDS}")

    def deco(obj):
        if name in _REGISTRY[kind]:
            raise ValueError(f"{kind} plugin {name!r} registered twice")
        obj.plugin_info = PluginInfo(kind, name, doc or (obj.__doc__ or "").strip(), list(params))
        _REGISTRY[kind][name] = obj
        return obj

    return deco


def get(kind: str, name: str):
    try:
        return _REGISTRY[kind][name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY[kind])) or "none"
        raise KeyError(f"no {kind} plugin named {name!r} (known: {known})") from None


def has(kind: str, name: str) -> bool:
    return name in _REGISTRY[kind]


def defaults(kind: str, name: str) -> dict[str, Any]:
    return {p.name: p.default for p in get(kind, name).plugin_info.params}


def catalog() -> dict[str, list[dict]]:
    """JSON-friendly listing of every registered plugin, for the UI."""
    return {
        kind: [asdict(obj.plugin_info) for _, obj in sorted(items.items())]
        for kind, items in _REGISTRY.items()
    }


_loaded = False


def load_plugins() -> None:
    """Import built-in plugins and any installed third-party plugin packages."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import evaluators, features, mappings, signals  # noqa: F401
    from .data import parquet_source, synthetic, synthetic_futures  # noqa: F401
    from .strategies import orb, weekly_topn  # noqa: F401

    for ep in entry_points(group="honestbt.plugins"):
        ep.load()
