"""Evaluator: out of sample.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, period_sharpe, register


@register("evaluator", "out_of_sample", params=[
    Param("split", "float", 0.6, "Fraction of periods used to pick parameters"),
], doc="Pick the best sweep point on the first part of history, then score it on the rest.")
def out_of_sample(ectx: EvalContext, split=0.6):
    idx = ectx.points[0][2].periods.index
    if len(idx) < 8:
        return Verdict("Out-of-sample", None, "Not enough periods", "Need at least 8 periods.")
    cut = idx[int(len(idx) * split)]
    best, best_is = None, -np.inf
    ppy = ectx.sel_result.periods_per_year
    for i, (_, _, res) in enumerate(ectx.points):
        s = period_sharpe(res.periods[res.periods.index < cut].to_numpy(), ppy)
        if s > best_is:
            best, best_is = i, s
    res = ectx.points[best][2]
    oos = res.periods[res.periods.index >= cut].to_numpy()
    oos_sharpe, oos_mean = period_sharpe(oos, ppy), float(np.mean(oos))
    passed = oos_mean > 0 and oos_sharpe > 0
    return Verdict(
        "Out-of-sample", passed,
        f"In-sample Sharpe {best_is:.2f} → out-of-sample {oos_sharpe:.2f}",
        "Parameters were chosen using only data before "
        f"{cut.date()}, then tested on {len(oos)} later periods it never saw. "
        "A large drop means the in-sample result was mostly fitting noise.",
        {"cut": str(cut), "chosen_point": ectx.points[best][0], "is_sharpe": best_is,
         "oos_sharpe": oos_sharpe, "oos_mean": oos_mean, "oos_periods": len(oos)},
    )

