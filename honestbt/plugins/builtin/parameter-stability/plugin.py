"""Evaluator: parameter stability.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, register


@register("evaluator", "parameter_stability", params=[
    Param("min_share", "float", 0.7, "Share of sweep points that must be profitable"),
], doc="Is the whole neighbourhood of parameters profitable, or just one lucky point?")
def parameter_stability(ectx: EvalContext, min_share=0.7):
    if len(ectx.points) < 3:
        return Verdict("Parameter stability", None, "Sweep too small",
                       "Add a sweep with at least 3 points to test stability.")
    rows = [{**pt, "mean": float(res.periods.mean()), "sharpe": res.metrics().get("sharpe", 0.0)}
            for pt, _, res in ectx.points]
    share = float(np.mean([r["mean"] > 0 for r in rows]))
    return Verdict(
        "Parameter stability", share >= min_share,
        f"{share:.0%} of {len(rows)} parameter settings were profitable",
        "A real effect should work across nearby settings. If only a narrow island of the sweep "
        "makes money, it is probably a coincidence.",
        {"grid": rows, "share_profitable": share},
    )

