"""Evaluator: random baseline.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, get_path, register, with_overrides


@register("evaluator", "random_baseline", params=[
    Param("n", "int", 40, "Number of random portfolios"),
    Param("rank_path", "str", "strategy.params.rank_by", "Config path of the ranking feature to randomise"),
    Param("alpha", "float", 0.05, "Significance level"),
], doc="Replace the ranking with random picks from the same filtered universe (same exits, same costs).")
def random_baseline(ectx: EvalContext, n=40, rank_path="strategy.params.rank_by", alpha=0.05):
    if get_path(ectx.sel_config, rank_path) is None:
        return Verdict("Random baseline", None, "No ranking parameter", f"{rank_path} not found in config.")
    actual = float(ectx.sel_result.periods.mean())
    means = []
    for seed in range(n):
        cfg = with_overrides(ectx.sel_config, {
            "features.__random__": {"plugin": "random", "params": {"seed": seed}},
            rank_path: "__random__",
        })
        means.append(float(ectx.run(cfg).periods.mean()))
    means = np.array(means)
    p = float((1 + np.sum(means >= actual)) / (n + 1))
    if "direction" in rank_path:
        what, why = "coin-flip directions", (
            "Keeps everything (same trade times, stop, target, costs) but flips a coin for long or short. "
            "If coin flips do as well, the breakout direction adds nothing and the result came from the "
            "stop/target shape or from luck.")
    else:
        what, why = "random picks", (
            "Keeps everything (filter, exit rule, costs) but picks names at random. If random picks do "
            "as well, the ranking adds nothing and the result came from the market or the exit rule.")
    return Verdict(
        "Random baseline", p < alpha,
        f"Beat {np.mean(means < actual):.0%} of {n} {what} (p = {p:.2f})",
        why,
        {"p_value": p, "actual_mean": actual, "random_means": means.round(6).tolist()},
    )

