"""Honest tests: does a result hold up?

Each test reads the run record and may re-run the same simulator with changed costs,
knobs or a stand-in strategy (``ctx.rerun``). A pass means only that the result survived
that test. It is never a claim that the strategy will make money.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

from titanium.sdk import (BacktestInfo, Library, Param, RandomPicks, Verdict, aligned_returns, ingredients, mean,
                          sharpe, split_time, step_returns, steps_per_year, t_stat, total_growth, without)

N = NormalDist()
MIN_STEPS = 8


def _pct(x: float, digits: int = 1) -> str:
    return f"{100 * x:+.{digits}f}%"


def _date(t) -> str:
    return t.strftime("%Y-%m-%d") if t is not None else "?"


def _not_enough(name: str, need: str = f"at least {MIN_STEPS} steps") -> Verdict:
    return Verdict(name, None, "Not enough history", f"This test needs {need}. Run the strategy over a longer span.")


def _knobs_text(knobs: dict) -> str:
    return ", ".join(f"{k} = {v:g}" if isinstance(v, (int, float)) else f"{k} = {v}" for k, v in knobs.items()) \
        or "the knobs as run"


# ---------------------------------------------------------------------------------------------
class OutOfSample:
    order = 10
    info = BacktestInfo(
        "out_of_sample", "Out-of-sample",
        "Chooses the knobs using only the early part of history, then scores that choice on the later part it "
        "never saw.",
        [Param("split", "float", 0.6, "Early part", "Share of the run used to choose the knobs", minimum=0.3,
               maximum=0.9),
         Param("spread", "float", 0.25, "Knob step", "How far each knob is moved, as a share of its range",
               minimum=0.05, maximum=0.5)],
        "runs up to 9 variants")

    def evaluate(self, ctx, split=0.6, spread=0.25):
        name = self.info.name
        run, ppy = ctx.run, steps_per_year(ctx.run)
        cut = split_time(run, split)
        if cut is None or len(step_returns(run, end=cut)) < MIN_STEPS or len(step_returns(run, start=cut)) < MIN_STEPS:
            return _not_enough(name, f"at least {MIN_STEPS} steps on each side of the split")
        variants = ctx.variants(spread)
        best = max(variants, key=lambda v: sharpe(step_returns(v.record, end=cut), ppy))
        is_sharpe = sharpe(step_returns(best.record, end=cut), ppy)
        oos = step_returns(best.record, start=cut)
        oos_sharpe, oos_total = sharpe(oos, ppy), total_growth(oos)
        passed = oos_total > 0 and oos_sharpe > 0
        if len(variants) > 1:
            how = (f"The knobs were chosen among {len(variants)} versions ({_knobs_text(best.knobs)} won) using only "
                   f"data before {_date(cut)}, then tested on {len(oos)} later steps it never saw. ")
        else:
            how = (f"This strategy has no number knobs to choose, so the run is simply split at {_date(cut)}. The "
                   "later part is only unseen if the strategy wasn't shaped by looking at it. ")
        return Verdict(
            name, passed, f"In-sample Sharpe {is_sharpe:.2f}, out-of-sample {oos_sharpe:.2f} ({_pct(oos_total)})",
            how + "A large drop means the early result was mostly fitting noise.",
            {"cut": cut.isoformat(), "chosen": best.knobs, "variants": len(variants), "is_sharpe": is_sharpe,
             "oos_sharpe": oos_sharpe, "oos_total": oos_total, "oos_steps": len(oos),
             "figures": [("In-sample Sharpe", f"{is_sharpe:.2f}"), ("Out-of-sample Sharpe", f"{oos_sharpe:.2f}"),
                         ("Out-of-sample profit", _pct(oos_total)), ("Versions tried", str(len(variants)))]})


class WalkForward:
    order = 15
    info = BacktestInfo(
        "walk_forward", "Walk-forward",
        "Out-of-sample, again and again: at the start of each stretch, the knobs are chosen on everything before "
        "it, then that stretch is scored.",
        [Param("folds", "int", 4, "Stretches", "How many unseen stretches to score", minimum=2, maximum=10),
         Param("spread", "float", 0.25, "Knob step", "How far each knob is moved, as a share of its range",
               minimum=0.05, maximum=0.5)],
        "runs up to 9 variants (shared with out-of-sample)")

    def evaluate(self, ctx, folds=4, spread=0.25):
        name = self.info.name
        run, ppy = ctx.run, steps_per_year(ctx.run)
        folds = int(folds)
        n = len(run.states)
        if n < MIN_STEPS * (folds + 1):
            return _not_enough(name, f"at least {MIN_STEPS * (folds + 1)} steps for {folds} stretches")
        variants = ctx.variants(spread)
        if len(variants) < 2:
            return Verdict(name, None, "No knobs to choose",
                           "Walk-forward re-chooses the knobs before each stretch. This strategy has no number knobs "
                           "with a range, so there is nothing to choose. Out-of-sample still splits the run.")
        edges = [run.states[min(n - 1, round(n * i / (folds + 1)))].time for i in range(folds + 2)]
        edges[-1] = None
        stitched, wins, picks = [], 0, []
        for i in range(1, folds + 1):
            a, b = edges[i], edges[i + 1]
            best = max(variants, key=lambda v: sharpe(step_returns(v.record, end=a), ppy))
            part = step_returns(best.record, start=a, end=b)
            stitched += part
            wins += total_growth(part) > 0
            picks.append(best.label)
        s, total = sharpe(stitched, ppy), total_growth(stitched)
        passed = s > 0 and total > 0
        return Verdict(
            name, passed, f"Walk-forward Sharpe {s:.2f}, {_pct(total)} over {folds} unseen stretches "
                          f"({wins} of {folds} profitable)",
            f"Before each of {folds} stretches, the best of {len(variants)} versions was chosen on the history up to "
            "then, and only the stretch after it counts. It is how the strategy would have done if you had kept "
            "re-tuning it as time went on.",
            {"stretches": folds, "profitable": wins, "sharpe": s, "total": total, "picks": picks,
             "figures": [("Walk-forward Sharpe", f"{s:.2f}"), ("Profit", _pct(total)),
                         ("Profitable stretches", f"{wins} of {folds}")]})


class Bootstrap:
    order = 20
    info = BacktestInfo(
        "bootstrap", "Bootstrap",
        "Reshuffles the strategy's own history in blocks thousands of times. If many reshuffled histories lose "
        "money, the average could easily be luck.",
        [Param("n", "int", 2000, "Resamples", minimum=200, maximum=20000),
         Param("block", "int", 5, "Block length", "Steps kept together, to keep streaks", minimum=1, maximum=60),
         Param("alpha", "float", 0.05, "Significance", "One-sided", minimum=0.001, maximum=0.2)],
        "reads the run")

    def evaluate(self, ctx, n=2000, block=5, alpha=0.05):
        name = self.info.name
        r = np.asarray(step_returns(ctx.run), float)
        if len(r) < MIN_STEPS:
            return _not_enough(name)
        rng = np.random.default_rng(0)
        T, b, n = len(r), max(1, min(int(block), len(r) // 2)), int(n)
        k = math.ceil(T / b)
        starts = rng.integers(0, T - b + 1, size=(n, k))
        samples = r[(starts[:, :, None] + np.arange(b)).reshape(n, -1)[:, :T]]
        means = samples.mean(axis=1)
        lo = float(np.quantile(means, alpha))
        losing = float(np.mean(means <= 0))
        return Verdict(
            name, lo > 0, f"{100 * (1 - alpha):.0f}% lower bound of the return per step: {_pct(lo, 3)} "
                          f"({losing:.0%} of reshuffles lose)",
            "Resamples the strategy's own history (in blocks, to keep streaks) thousands of times. A pass needs "
            "the low end of the range to stay above zero.",
            {"lower_bound": lo, "share_losing": losing, "mean": float(r.mean()),
             "figures": [("Mean per step", _pct(float(r.mean()), 3)), ("Lower bound", _pct(lo, 3)),
                         ("Reshuffles losing", f"{losing:.0%}")]})


class DeflatedSharpe:
    order = 30
    info = BacktestInfo(
        "deflated_sharpe", "Deflated Sharpe",
        "Bailey and López de Prado: is the Sharpe ratio real once you allow for fat tails and for how many "
        "versions were tried before this one?",
        [Param("threshold", "float", 0.95, "Required probability", minimum=0.5, maximum=0.999),
         Param("trials", "int", 0, "Versions tried", "Leave at 0 to count the versions run this session; set it "
               "higher if you tried more elsewhere", minimum=0, maximum=100000)],
        "reads the run and this session's earlier runs")

    def evaluate(self, ctx, threshold=0.95, trials=0):
        name = self.info.name
        r = np.asarray(step_returns(ctx.run), float)
        T = len(r)
        if T < MIN_STEPS or float(np.std(r)) == 0:
            return _not_enough(name, f"at least {MIN_STEPS} steps that aren't all the same")
        sr = float(np.mean(r) / np.std(r, ddof=1))
        seen = ctx.trials()
        k = max(int(trials), seen)
        others = [np.asarray(step_returns(h), float) for h in ctx.history if h.status == "done"]
        srs = [float(np.mean(x) / np.std(x, ddof=1)) for x in others if len(x) > 2 and np.std(x) > 0] + [sr]
        var = float(np.var(srs, ddof=1)) if len(srs) > 2 else 1.0 / T  # without a spread to go on: the null's
        g = 0.5772156649
        sr0 = math.sqrt(var) * ((1 - g) * N.inv_cdf(1 - 1 / k) + g * N.inv_cdf(1 - 1 / (k * math.e))) if k > 1 else 0.0
        z = (r - r.mean()) / r.std()
        skew, kurt = float(np.mean(z ** 3)), float(np.mean(z ** 4))
        denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
        dsr = N.cdf((sr - sr0) * math.sqrt(T - 1) / denom)
        counted = (f"{seen} version{'s of this strategy were' if seen != 1 else ' of this strategy was'} run this "
                   "session"
                   + (f"; you said {int(trials)} were tried" if int(trials) > seen else ""))
        return Verdict(
            name, dsr >= threshold, f"Chance the edge is real after {k} version{'s' if k != 1 else ''}: {dsr:.0%}",
            f"The more versions you try, the better the best one looks by chance. {counted}, and the Sharpe ratio "
            f"is discounted for that and for the shape of the returns (skew {skew:.2f}, kurtosis {kurt:.1f}). "
            f"A pass needs {threshold:.0%}.",
            {"dsr": dsr, "trials": k, "sharpe_per_step": sr, "benchmark_sharpe_per_step": sr0, "skew": skew,
             "kurtosis": kurt,
             "figures": [("Probability", f"{dsr:.0%}"), ("Versions", str(k)),
                         ("Annual Sharpe", f"{sr * math.sqrt(steps_per_year(ctx.run)):.2f}")]})


class CostStress:
    order = 40
    info = BacktestInfo(
        "cost_stress", "Cost stress",
        "Runs the strategy again with every trading cost multiplied. If the edge disappears when costs double, "
        "it is unlikely to survive real trading.",
        [Param("multiplier", "float", 2.0, "Cost multiplier", minimum=1.0, maximum=10.0)],
        "runs 2 variants")

    def evaluate(self, ctx, multiplier=2.0):
        name = self.info.name
        stress = float(((ctx.run.settings or {}).get("costs") or {}).get("stress", 1.0))
        free = ctx.rerun(settings={"costs": {"stress": 0.0}})
        ctx.progress(0.5)
        hard = ctx.rerun(settings={"costs": {"stress": stress * float(multiplier)}})
        ctx.progress(1.0)
        g = lambda rec: rec.states[-1].growth - 1 if rec.states else 0.0  # noqa: E731
        gross, net, stressed = g(free), g(ctx.run), g(hard)
        return Verdict(
            name, stressed > 0, f"Profit before costs {_pct(gross)}, as run {_pct(net)}, at {multiplier:g}x costs "
                                f"{_pct(stressed)}",
            "Spreads and slippage are uncertain, especially near the open and in small names. A pass means the "
            f"strategy still made money with every cost {multiplier:g} times higher.",
            {"gross": gross, "net": net, "stressed": stressed, "multiplier": multiplier,
             "figures": [("Before costs", _pct(gross)), ("As run", _pct(net)), (f"At {multiplier:g}x", _pct(stressed))]})


class RandomBaseline:
    order = 50
    info = BacktestInfo(
        "random_baseline", "Random baseline",
        "Keeps the timing, the number of names, the weights and how long each is held, but picks the names at "
        "random. If chance does as well, the choice of names adds nothing.",
        [Param("n", "int", 20, "Random versions", minimum=5, maximum=500),
         Param("alpha", "float", 0.05, "Significance", minimum=0.001, maximum=0.2)],
        "runs n variants")

    def evaluate(self, ctx, n=20, alpha=0.05):
        name = self.info.name
        if ctx.strategy is None:
            return Verdict(name, None, "Can't be repeated", "This run didn't come from a strategy in the workspace.")
        n = int(n)
        actual = ctx.run.states[-1].growth - 1 if ctx.run.states else 0.0
        single = len({k for s in ctx.run.states for k in s.positions} | {f.instrument for f in ctx.run.fills}) <= 1
        totals = []
        for seed in range(n):
            rec = ctx.rerun(strategy=RandomPicks(ctx.strategy, seed, ctx.run.settings))
            totals.append(rec.states[-1].growth - 1 if rec.states else 0.0)
            ctx.progress((seed + 1) / n)
        arr = np.asarray(totals)
        p = float((1 + np.sum(arr >= actual)) / (n + 1))
        beat = float(np.mean(arr < actual))
        if single:
            what, why = "coin-flip directions", (
                "Keeps everything (the same trade times, exits and costs) but flips a coin for long or short. If "
                "coin flips do as well, the choice of direction adds nothing.")
        else:
            what, why = "random picks", (
                "Keeps everything (when it trades, how many names, their weights, how long each is held, costs) but "
                "picks the names at random from what was trading then. If random picks do as well, the result came "
                "from the market or the timing, not from choosing names.")
        floor = 1 / (n + 1)
        note = (f" With {n} versions the smallest possible p is {floor:.2f}, so it can't pass at {alpha:g}: "
                "use more versions.") if floor >= alpha else ""
        return Verdict(
            name, p < alpha, f"Beat {beat:.0%} of {n} {what} (p = {p:.2f})", why + note,
            {"p_value": p, "actual": actual, "random": arr.round(6).tolist(), "kind": what,
             "figures": [("Strategy profit", _pct(actual)), ("Random median", _pct(float(np.median(arr)))),
                         ("p", f"{p:.2f}")]})


class Benchmark:
    order = 60
    info = BacktestInfo(
        "benchmark", "Benchmark",
        "Compares each step with the default strategy (equal weight in everything in the dataset, same costs). "
        "Beating it by a clear margin is the bar.",
        [Param("t", "float", 1.65, "Required t", "How clear the margin must be", minimum=0.0, maximum=5.0)],
        "runs the default strategy once")

    def evaluate(self, ctx, t=1.65):
        name = self.info.name
        base = ctx.baseline()
        if base is None:
            return Verdict(name, None, "The default strategy couldn't run", "There is nothing to compare with.")
        a, b = aligned_returns(ctx.run, base)
        if len(a) < MIN_STEPS:
            return _not_enough(name)
        diff = [x - y for x, y in zip(a, b)]
        ts = t_stat(diff)
        sg, bg = ctx.run.states[-1].growth - 1, base.states[-1].growth - 1
        return Verdict(
            name, ts > t, f"Excess over the default strategy: {_pct(mean(diff), 3)} per step (t = {ts:.2f})",
            f"The strategy made {_pct(sg)}; the default strategy made {_pct(bg)} over the same steps, paying the same "
            f"costs. A pass needs the step-by-step difference to be clearly above zero (t above {t:g}).",
            {"excess_mean": mean(diff), "t_stat": ts, "strategy": sg, "default": bg, "baseline_run": base.id,
             "figures": [("Strategy", _pct(sg)), ("Default strategy", _pct(bg)), ("t", f"{ts:.2f}")]})


class ParameterStability:
    order = 70
    info = BacktestInfo(
        "parameter_stability", "Parameter stability",
        "Moves each knob a little either way. A real effect works across nearby settings; one lucky setting "
        "surrounded by losers is probably a coincidence.",
        [Param("spread", "float", 0.25, "Knob step", "How far each knob is moved, as a share of its range",
               minimum=0.05, maximum=0.5),
         Param("min_share", "float", 0.7, "Must be profitable", "Share of the versions that must make money",
               minimum=0.1, maximum=1.0)],
        "runs up to 9 variants (shared with out-of-sample)")

    def evaluate(self, ctx, spread=0.25, min_share=0.7):
        name = self.info.name
        variants = ctx.variants(spread)
        if len(variants) < 3:
            return Verdict(name, None, "No knobs to move",
                           "This test moves the strategy's number knobs. Give a knob a range (knob(..., lo, hi)) and "
                           "it can run.")
        ppy = steps_per_year(ctx.run)
        rows = [{"version": v.label, "profit": v.record.states[-1].growth - 1,
                 "sharpe": sharpe(step_returns(v.record), ppy)} for v in variants]
        share = mean([1.0 if r["profit"] > 0 else 0.0 for r in rows])
        good = sum(r["profit"] > 0 for r in rows)
        worst = min(rows, key=lambda r: r["profit"])
        return Verdict(
            name, share >= min_share, f"{good} of {len(rows)} nearby settings made money",
            f"Each number knob was moved {spread:.0%} of its range down and up, one at a time. The weakest was "
            f"{worst['version']} at {_pct(worst['profit'])}. A pass needs {min_share:.0%} of them to make money.",
            {"grid": rows, "share_profitable": share,
             "figures": [("Profitable", f"{good} of {len(rows)}"), ("Worst", _pct(worst["profit"]))]})


class Ablation:
    order = 80
    info = BacktestInfo(
        "ablation", "Ablation",
        "Takes one ingredient out (a switch knob, or a filter module) and keeps everything else. Does the strategy "
        "earn clearly more with it?",
        [Param("ingredient", "str", "", "Ingredient", "A module id or a switch knob (module.knob). Empty: the "
               "first one found")],
        "runs 1 variant")

    def evaluate(self, ctx, ingredient="", t=1.65):
        name = self.info.name
        if ctx.graph is None:
            return Verdict(name, None, "Nothing to take out", "Only strategies built from modules have ingredients.")
        options = ingredients(ctx.graph)
        if not options:
            return Verdict(name, None, "Nothing to take out",
                           "The strategy has no switch knobs and no filter module that can be skipped.")
        if ingredient:
            pick = next((o for o in options if o[0].split(":", 1)[1] == ingredient or o[0] == ingredient), None)
            if pick is None:
                listed = ", ".join(o[0].split(":", 1)[1] for o in options)
                return Verdict(name, None, f"No ingredient called {ingredient}", f"The ones it can take out: {listed}.")
        else:
            pick = options[0]
        graph, knobs = without(ctx.graph, pick[0])
        other = ctx.rerun(strategy=graph if graph is not ctx.graph else None, knobs=knobs or None)
        label = pick[1]
        a, b = aligned_returns(ctx.run, other)
        if len(a) < MIN_STEPS:
            return _not_enough(name)
        diff = [x - y for x, y in zip(a, b)]
        ts = t_stat(diff)
        ta, tb = len(ctx.run.trades), len(other.trades)
        pa, pb = ctx.run.states[-1].growth - 1, other.states[-1].growth - 1
        return Verdict(
            name, ts > t, f"With {label}: {ta} trades, {_pct(pa)}. Without: {tb} trades, {_pct(pb)} (t = {ts:.2f})",
            f"Takes out {label} and keeps everything else. Fewer trades for a similar total can make each trade "
            "look better, but that alone is not an improvement: the question is whether the version with it earns "
            "clearly more step by step, which is what t measures.",
            {"ingredient": pick[0], "with": pa, "without": pb, "t_stat": ts, "trades_with": ta, "trades_without": tb,
             "figures": [("With", _pct(pa)), ("Without", _pct(pb)), ("t", f"{ts:.2f}")]})


TESTS = (OutOfSample, WalkForward, Bootstrap, DeflatedSharpe, CostStress, RandomBaseline, Benchmark,
         ParameterStability, Ablation)


def setup(plugin):
    for cls in TESTS:
        plugin.add(Library.BACKTESTS, cls.info.id, cls(), doc=cls.info.doc)
