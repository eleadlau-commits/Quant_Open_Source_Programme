"""Evaluator: bootstrap.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import math

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, register


@register("evaluator", "bootstrap", params=[
    Param("n", "int", 2000, "Resamples"), Param("block", "int", 4, "Block length (periods)"),
    Param("alpha", "float", 0.05, "One-sided significance level"),
], doc="Block-bootstrap the period returns; pass if the lower confidence bound of the mean is above zero.")
def bootstrap(ectx: EvalContext, n=2000, block=4, alpha=0.05):
    r = ectx.sel_result.periods.to_numpy()
    if len(r) < 8:
        return Verdict("Bootstrap", None, "Not enough periods", "Need at least 8 periods.")
    rng = np.random.default_rng(0)
    T, b = len(r), max(1, min(block, len(r) // 2))
    k = math.ceil(T / b)
    starts = rng.integers(0, T - b + 1, size=(n, k))
    samples = r[(starts[:, :, None] + np.arange(b)).reshape(n, -1)[:, :T]]
    means = samples.mean(axis=1)
    lo = float(np.quantile(means, alpha))
    p = float(np.mean(means <= 0))
    return Verdict(
        "Bootstrap", lo > 0,
        f"{100 * (1 - alpha):.0f}% lower bound of mean return per period: {lo:+.3%}",
        "Resamples the strategy's own history (in blocks, to keep streaks) thousands of times. "
        "If many resampled histories lose money, the average you see could easily be luck.",
        {"lower_bound": lo, "share_of_resamples_losing": p, "mean": float(r.mean())},
    )

