"""Small helpers for a plugin folder's own tests (``<id>/tests/test_*.py``).

    from honestbt.plugins.testing import fake_context, fake_result, plugin

Tests may import anything; only a plugin's code is limited to ``honestbt.sdk``.
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pandas as pd

from ..engine import RunResult
from ..evaluators import EvalContext
from ..registry import get, load_plugins
from . import plugin_module


def plugin(kind: str, name: str):
    """A registered plugin by kind and name (loads the plugin folders first)."""
    load_plugins()
    return get(kind, name)


def module(plugin_id: str):
    """The loaded main module of a plugin folder, to test its helper functions."""
    return plugin_module(plugin_id)


def fake_result(returns: Sequence[float], ppy: float = 52.0, start: str = "2024-01-01", freq: str = "7D") -> RunResult:
    """A RunResult whose period returns are ``returns`` (no trades)."""
    r = pd.Series(np.asarray(returns, dtype=float), index=pd.date_range(start, periods=len(returns), freq=freq))
    return RunResult(trades=[], periods=r, periods_gross=r.copy(), periods_per_year=ppy)


def fake_context(points: Sequence[Sequence[float]], selected: int | None = None, config: dict | None = None,
                 run: Callable[[dict], RunResult] | None = None, sweep_key: str = "x") -> EvalContext:
    """An evaluator context with one sweep point per list of returns.

    ``selected`` defaults to the point with the best mean, as the runner would
    pick by Sharpe. ``run`` answers re-runs (cost stress, baselines, ablation).
    """
    config = config or {"strategy": {"plugin": "fake", "params": {}}}
    pts = [({sweep_key: i}, config, fake_result(r)) for i, r in enumerate(points)]
    if selected is None:
        selected = max(range(len(pts)), key=lambda i: float(np.mean(points[i])))
    return EvalContext(data=None, config=config, points=pts, selected=selected,
                       run=run or (lambda cfg: pts[selected][2]))


def noise(n: int = 80, mean: float = 0.0, sd: float = 0.02, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(mean, sd, n)
