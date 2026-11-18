"""Evaluator: benchmark.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import math

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, get_path, register, summarize, with_overrides


@register("evaluator", "benchmark", params=[
    Param("top_n_path", "str", "strategy.params.top_n"),
    Param("exit_path", "str", "strategy.params.exit"),
], doc="Compare against holding the whole filtered universe for the same period.")
def benchmark(ectx: EvalContext, top_n_path="strategy.params.top_n", exit_path="strategy.params.exit"):
    cfg = with_overrides(ectx.sel_config, {top_n_path: 10**9, exit_path: {"plugin": "never"}})
    for k in ("strategy.params.min_score",):
        if get_path(cfg, k) is not None:
            cfg = with_overrides(cfg, {k: None})
    b = ectx.run(cfg)
    s, bm = ectx.sel_result.periods, b.periods.reindex(ectx.sel_result.periods.index).fillna(0)
    diff = (s - bm).to_numpy()
    se = np.std(diff, ddof=1) / math.sqrt(len(diff)) if len(diff) > 1 else float("inf")
    t = float(np.mean(diff) / se) if se > 0 else 0.0
    return Verdict(
        "Benchmark", t > 1.65,
        f"Excess over buy-the-universe: {np.mean(diff):+.3%} per period (t = {t:.2f})",
        "Compares with simply buying every stock that passes the filter at the same time and "
        "holding to the same time stop. Beating it by a statistically clear margin is the bar.",
        {"excess_mean": float(np.mean(diff)), "t_stat": t, "benchmark": summarize(b.periods, b.trades),
         "benchmark_equity": {"t": [str(x) for x in bm.index], "v": (1 + bm).cumprod().round(6).tolist()}},
    )

