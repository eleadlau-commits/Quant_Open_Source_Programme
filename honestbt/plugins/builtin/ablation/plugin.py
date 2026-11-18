"""Evaluator: ablation.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import math

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, get_path, register, with_overrides


@register("evaluator", "ablation", params=[
    Param("path", "str", "strategy.params.trend_filter", "Config path of the ingredient to switch"),
    Param("value", "json", False, "Value that removes the ingredient"),
    Param("label", "str", "trend filter", "Name of the ingredient, for the report"),
], doc="Does one ingredient (e.g. a trend filter) actually help? Re-run without it and compare day by day.")
def ablation(ectx: EvalContext, path="strategy.params.trend_filter", value=False, label="trend filter"):
    if get_path(ectx.sel_config, path, default=KeyError) is KeyError:
        return Verdict(f"Ablation: {label}", None, "Ingredient not in config", f"{path} not found.")
    with_it = ectx.sel_result
    without = ectx.run(with_overrides(ectx.sel_config, {path: value}))
    if get_path(ectx.sel_config, path) == value:
        with_it, without = without, with_it  # the selected variant is the one without it
        note = "The best-looking variant already left it out, so it is compared with the version that keeps it. "
    else:
        note = ""
    a, b = with_it.metrics(), without.metrics()
    idx = with_it.periods.index.union(without.periods.index)
    diff = (with_it.periods.reindex(idx).fillna(0) - without.periods.reindex(idx).fillna(0)).to_numpy()
    se = np.std(diff, ddof=1) / math.sqrt(len(diff)) if len(diff) > 1 else float("inf")
    t = float(np.mean(diff) / se) if se > 0 else 0.0

    def per_trade(res):
        r = np.array([x.net_return for x in res.trades])
        return float(r.mean()) if len(r) else 0.0

    pa, pb = per_trade(with_it), per_trade(without)
    unit = "$" if "total_pnl_usd" in a else ""
    tot = (lambda m: f"${m.get('total_pnl_usd', 0):,.0f}") if unit else (lambda m: f"{m.get('total_return', 0):+.1%}")
    return Verdict(
        f"Ablation: {label}", t > 1.65,
        f"With {label}: {a['n_trades']} trades, total {tot(a)}. Without: {b['n_trades']} trades, total {tot(b)} "
        f"(daily difference t = {t:.2f})",
        note + f"Removes the {label} and keeps everything else. Fewer trades with a similar total makes each trade "
        "look better, but that alone is not an improvement: the question is whether the version with it earns "
        "clearly more per day, which is what the t-statistic tests.",
        {"with": a, "without": b, "t_stat": t, "mean_daily_diff": float(np.mean(diff)),
         "per_trade_with": pa, "per_trade_without": pb,
         "without_equity": {"t": [str(x) for x in without.periods.index],
                            "v": (1 + without.periods).cumprod().round(6).tolist()}},
    )

