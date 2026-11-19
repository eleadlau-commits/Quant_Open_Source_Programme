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
complementary -> callable(market, **params) -> {name: pandas Series or DataFrame}
              complementary data C_j(t) (news, events, income...), indexed by the time each
              value became known; a DataFrame has one column per symbol

Plugins live in folders, one per plugin (see ``honestbt.plugins``): the
built-in ones under ``honestbt/plugins/builtin/`` and your own in the user
plugin folder. Every registration remembers which folder it came from, so a
plugin that fails while loading can be taken out cleanly. Pip packages can
still add plugins through the ``honestbt.plugins`` entry-point group.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable

KINDS = ("data", "feature", "mapping", "signal", "strategy", "evaluator", "complementary")
_REGISTRY: dict[str, dict[str, Any]] = {k: {} for k in KINDS}
_owner = ""  # set by the loader while a plugin's code runs


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
    plugin: str = ""  # id of the plugin folder (or pip package) that registered it


def register(kind: str, name: str, params: list[Param] | tuple = (), doc: str = "") -> Callable:
    if kind not in KINDS:
        raise ValueError(f"unknown plugin kind {kind!r}; expected one of {KINDS}")

    def deco(obj):
        if name in _REGISTRY[kind]:
            raise ValueError(f"{kind} plugin {name!r} registered twice")
        obj.plugin_info = PluginInfo(kind, name, doc or (obj.__doc__ or "").strip(), list(params), _owner)
        _REGISTRY[kind][name] = obj
        return obj

    return deco


def get(kind: str, name: str):
    try:
        return _REGISTRY[kind][name]
    except KeyError:
        from .plugins import why_missing

        why = why_missing(kind, name)
        known = ", ".join(sorted(_REGISTRY[kind])) or "none"
        raise KeyError(f"no {kind} plugin named {name!r}" + (f" ({why})" if why else f" (known: {known})")) from None


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


def owned_by(owner: str) -> dict[str, list[str]]:
    """What one plugin folder registered, by kind."""
    out: dict[str, list[str]] = {}
    for kind, items in _REGISTRY.items():
        names = sorted(n for n, obj in items.items() if obj.plugin_info.plugin == owner)
        if names:
            out[kind] = names
    return out


def unregister_owner(owner: str) -> None:
    for items in _REGISTRY.values():
        for name in [n for n, obj in items.items() if obj.plugin_info.plugin == owner]:
            del items[name]


def set_owner(owner: str) -> str:
    global _owner
    previous, _owner = _owner, owner
    return previous


def reset() -> None:
    """Forget every plugin (tests use this to load a different set of folders)."""
    global _loaded
    for items in _REGISTRY.values():
        items.clear()
    _loaded = False


_loaded = False


def load_plugins() -> None:
    """Load every plugin folder (built-in and your own), then pip-installed plugin packages."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import plugins

    plugins.load_all()
