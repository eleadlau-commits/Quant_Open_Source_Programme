"""Evaluator plugins: does the strategy survive honest scrutiny?

Each evaluator is ``f(ectx, **params) -> Verdict``. A "pass" means only that
the result survived that particular test. It is never a claim that the
strategy will make money.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any, Callable

import numpy as np
import pandas as pd

from .engine import RunResult, summarize
from .patchbay import get_path, with_overrides
from .registry import Param, register

N = NormalDist()


@dataclass
class Verdict:
    name: str
    passed: bool | None  # None = could not be evaluated
    headline: str
    explanation: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalContext:
    data: Any
    config: dict  # base config, including sweep
    points: list[tuple[dict, dict, RunResult]]  # (sweep point, concrete config, result)
    selected: int  # index of the configuration a naive user would pick (best Sharpe)
    run: Callable[[dict], RunResult]

    @property
    def sel_result(self) -> RunResult:
        return self.points[self.selected][2]

    @property
    def sel_config(self) -> dict:
        return self.points[self.selected][1]


def _sharpe(r: np.ndarray, ppy=52.0) -> float:
    if len(r) < 2 or np.std(r, ddof=1) == 0:
        return 0.0
    return float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(ppy))


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
        s = _sharpe(res.periods[res.periods.index < cut].to_numpy(), ppy)
        if s > best_is:
            best, best_is = i, s
    res = ectx.points[best][2]
    oos = res.periods[res.periods.index >= cut].to_numpy()
    oos_sharpe, oos_mean = _sharpe(oos, ppy), float(np.mean(oos))
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
