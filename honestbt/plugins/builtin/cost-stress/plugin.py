"""Evaluator: cost stress.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

from honestbt.sdk import EvalContext, Param, Verdict, register, summarize, with_overrides


@register("evaluator", "cost_stress", params=[
    Param("multiplier", "float", 2.0, "Multiply all trading costs by this"),
], doc="Re-run with trading costs multiplied; pass if still profitable.")
def cost_stress(ectx: EvalContext, multiplier=2.0):
    base = ectx.sel_result.metrics()
    cfg = with_overrides(ectx.sel_config, {"costs.multiplier": multiplier})
    m = ectx.run(cfg).metrics()
    gross = summarize(ectx.sel_result.periods_gross, ectx.sel_result.trades, ectx.sel_result.periods_per_year)
    return Verdict(
        "Cost stress", m.get("mean_period_return", 0) > 0,
        f"Mean return per period: gross {gross.get('mean_period_return', 0):+.3%}, "
        f"net {base.get('mean_period_return', 0):+.3%}, at {multiplier:g}x costs {m.get('mean_period_return', 0):+.3%}",
        "Opening-auction spreads and slippage are uncertain. If the edge disappears when costs "
        "double, a retail trader is unlikely to capture it.",
        {"gross": gross.get("mean_period_return"), "net": base.get("mean_period_return"),
         "stressed": m.get("mean_period_return"), "multiplier": multiplier},
    )

