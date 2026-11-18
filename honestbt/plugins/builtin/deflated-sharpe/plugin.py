"""Evaluator: deflated sharpe.

An evaluator is ``f(ectx, **params) -> Verdict``. A pass means only that the
result survived this test; it is never a claim that the strategy will make money.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

from honestbt.sdk import EvalContext, Param, Verdict, register


N = NormalDist()

@register("evaluator", "deflated_sharpe", params=[
    Param("threshold", "float", 0.95, "Required probability that the true Sharpe is above zero"),
], doc="Bailey & López de Prado's deflated Sharpe ratio: corrects for the number of variants tried.")
def deflated_sharpe(ectx: EvalContext, threshold=0.95):
    r = ectx.sel_result.periods.to_numpy()
    T = len(r)
    if T < 8 or np.std(r) == 0:
        return Verdict("Deflated Sharpe", None, "Not enough data", "Need at least 8 periods with variation.")
    sr = float(np.mean(r) / np.std(r, ddof=1))  # per-period Sharpe
    trials = [res.periods.to_numpy() for _, _, res in ectx.points]
    srs = np.array([np.mean(x) / np.std(x, ddof=1) if np.std(x) > 0 else 0.0 for x in trials])
    k = len(srs)
    if k > 1 and np.var(srs, ddof=1) > 0:
        g = 0.5772156649
        sr0 = math.sqrt(np.var(srs, ddof=1)) * ((1 - g) * N.inv_cdf(1 - 1 / k) + g * N.inv_cdf(1 - 1 / (k * math.e)))
    else:
        sr0 = 0.0
    z = (r - r.mean()) / r.std()
    skew, kurt = float(np.mean(z**3)), float(np.mean(z**4))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    dsr = N.cdf((sr - sr0) * math.sqrt(T - 1) / denom)
    return Verdict(
        "Deflated Sharpe", dsr >= threshold,
        f"Probability the edge is real after {k} variant(s): {dsr:.0%}",
        "The more variants you try, the better the best one looks by chance. This discounts the "
        "best Sharpe by how many sweep points were tested and by fat tails in the returns.",
        {"dsr": dsr, "trials": k, "sharpe_per_period": sr, "benchmark_sharpe_per_period": sr0,
         "skew": skew, "kurtosis": kurt},
    )

