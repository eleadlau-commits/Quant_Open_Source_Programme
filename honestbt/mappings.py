"""Mapping plugins: the patch cables.

A mapping is a pure function ``f(x, **params) -> float`` that turns a feature
value into a strategy parameter, e.g. ``exit k = linear(realized_vol)`` or
``holding minutes = piecewise(atr_pct)``. Because they are pure, sweeping a
mapping's own parameters sweeps a whole *family* of strategies.
"""
from __future__ import annotations

import numpy as np

from .registry import Param, register


@register("mapping", "identity", doc="Pass the feature through unchanged.")
def identity(x):
    return x


@register("mapping", "constant", params=[Param("value", "float", 1.0)], doc="Ignore the input.")
def constant(x, value=1.0):
    return value


@register("mapping", "linear", params=[
    Param("slope", "float", 1.0), Param("intercept", "float", 0.0),
    Param("lo", "float", None, "Clip below"), Param("hi", "float", None, "Clip above"),
], doc="intercept + slope * x, optionally clipped.")
def linear(x, slope=1.0, intercept=0.0, lo=None, hi=None):
    y = intercept + slope * x
    if lo is not None:
        y = max(lo, y)
    if hi is not None:
        y = min(hi, y)
    return y


@register("mapping", "piecewise", params=[
    Param("points", "json", [[0, 0], [1, 1]], "[[x, y], ...] knots; linear between, flat outside"),
], doc="Piecewise-linear lookup table.")
def piecewise(x, points=((0, 0), (1, 1))):
    pts = np.asarray(points, dtype=float)
    return float(np.interp(x, pts[:, 0], pts[:, 1]))


@register("mapping", "step", params=[
    Param("thresholds", "json", [0.3, 0.6]), Param("values", "json", [1, 2, 3]),
], doc="Bucket x by thresholds and return the matching value (len(values) = len(thresholds) + 1).")
def step(x, thresholds=(0.3, 0.6), values=(1, 2, 3)):
    return values[int(np.searchsorted(np.asarray(thresholds), x, "right"))]
