"""Evaluator: benchmark.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import math

import numpy as np

import pandas as pd

from honestbt.sdk import EvalContext, Param, Verdict, get_path, hold_everything, register, summarize, with_overrides


@register("evaluator", "benchmark", params=[
    Param("top_n_path", "str", "strategy.params.top_n"),
    Param("exit_path", "str", "strategy.params.exit"),
], doc="Compare against holding the whole filtered universe for the same period.")
def benchmark(ectx: EvalContext, top_n_path="strategy.params.top_n", exit_path="strategy.params.exit"):
    if get_path(ectx.sel_config, "strategy.plugin") == "python":
        return _vs_default(ectx)
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



def _vs_default(ectx: EvalContext) -> Verdict:
    """Strategies written as a Python file: compare each period with the default strategy
    (hold everything in the dataset) over the same period."""
    s = ectx.sel_result.periods
    eq = hold_everything(ectx.data)
    if len(s) < 2 or eq.empty:
        return Verdict("Benchmark", None, "Not enough periods", "Need at least 2 periods.")
    days = s.index.normalize()
    at = eq.reindex(eq.index.union(days)).ffill()
    # the default's return from one decision day's close to the next one's
    starts = at.loc[days].to_numpy()
    ends = np.r_[starts[1:], eq.iloc[-1]]
    bm = pd.Series(ends / starts - 1, index=s.index)
    diff = (s - bm).to_numpy()
    se = np.std(diff, ddof=1) / math.sqrt(len(diff)) if len(diff) > 1 else float("inf")
    t = float(np.mean(diff) / se) if se > 0 else 0.0
    return Verdict(
        "Benchmark", t > 1.65,
        f"Excess over the default strategy: {np.mean(diff):+.3%} per period (t = {t:.2f})",
        "Compares with the default strategy: spreading the money evenly across every stock in the "
        "dataset and holding it, over the same periods. Beating it by a statistically clear margin is the bar.",
        {"excess_mean": float(np.mean(diff)), "t_stat": t,
         "benchmark_equity": {"t": [str(x) for x in bm.index], "v": (1 + bm).cumprod().round(6).tolist()}},
    )
