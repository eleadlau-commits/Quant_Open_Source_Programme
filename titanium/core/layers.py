"""Run settings in layers: each layer overrides the one before.

A run's settings resolve as app defaults, then the market's defaults, then the
strategy's own settings, then the run's (a backtest's changes). ``costs`` merge part by
part (``equity``, ``futures``, ``stress``), so a layer can change one cost and keep the rest.
"""
from __future__ import annotations

from typing import Any


def merge_settings(base: dict[str, Any] | None, *layers: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(base or {})
    for layer in layers:
        for k, v in (layer or {}).items():
            if k == "costs" and isinstance(v, dict) and isinstance(out.get(k), dict):
                costs = {**out[k]}
                for part, value in v.items():
                    costs[part] = ({**costs[part], **value} if isinstance(value, dict)
                                   and isinstance(costs.get(part), dict) else value)
                out[k] = costs
            else:
                out[k] = v
    return out


def layer_of(key: str, *layers: tuple[str, dict[str, Any] | None]) -> str | None:
    """The name of the last layer that sets ``key`` (``"costs.equity.slippage_bps"`` reaches inside)."""
    found = None
    for name, layer in layers:
        value: Any = layer or {}
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                value = _MISSING
                break
            value = value[part]
        if value is not _MISSING:
            found = name
    return found


_MISSING = object()
