"""Top-level orchestration: config -> data -> sweep -> evaluators -> report."""
from __future__ import annotations

import json
import time
from typing import Any

from . import engine
from .evaluators import EvalContext, Verdict
from .patchbay import ConfigError, expand_evaluators, expand_sweep, validate
from .registry import get, load_plugins

_DATA_CACHE: dict[str, Any] = {}


def load_data(spec: dict):
    key = json.dumps(spec, sort_keys=True)
    if key not in _DATA_CACHE:
        if len(_DATA_CACHE) > 4:
            _DATA_CACHE.clear()
        _DATA_CACHE[key] = get("data", spec["plugin"])(**spec.get("params", {}))
    return _DATA_CACHE[key]


class StrategyRun:
    """One strategy backtested; tests can then be run on it one at a time, on demand.

    ``sweep=False`` runs the settings exactly as written (the desktop app's way);
    ``sweep=True`` backtests every variant in ``sweep`` and selects the best Sharpe.
    """

    def __init__(self, cfg: dict, data=None, strict: bool = True, sweep: bool = True):
        load_plugins()
        if not sweep:
            cfg = {k: v for k, v in cfg.items() if k != "sweep"}
        problems = validate(cfg)
        if problems:
            raise ConfigError("; ".join(problems))
        t0 = time.time()
        self.cfg = cfg
        self.strict = strict
        self.data = data or load_data(cfg["data"])
        self._cache: dict[str, engine.RunResult] = {}
        self.points = [(pt, c, self.run_one(c)) for pt, c in expand_sweep(cfg)]
        pts = self.points
        self.selected = max(range(len(pts)), key=lambda i: pts[i][2].metrics().get("sharpe", float("-inf")))
        self.elapsed_s = round(time.time() - t0, 2)

    def run_one(self, c: dict) -> engine.RunResult:
        key = json.dumps({k: v for k, v in c.items() if k not in ("sweep", "evaluators", "data")}, sort_keys=True)
        if key not in self._cache:
            self._cache[key] = engine.run(self.data, c, strict=self.strict)
        return self._cache[key]

    @property
    def result(self) -> engine.RunResult:
        return self.points[self.selected][2]

    def context(self) -> EvalContext:
        return EvalContext(self.data, self.cfg, self.points, self.selected, self.run_one)

    def run_test(self, ev: dict) -> Verdict:
        """Run one test (evaluator spec ``{"plugin", "params"}``); a crash is reported, never a pass."""
        try:
            return get("evaluator", ev["plugin"])(self.context(), **ev.get("params", {}))
        except Exception as exc:
            return Verdict(ev.get("plugin", "?"), None, "Evaluator failed", repr(exc))

    def report(self) -> dict:
        """The strategy's own results, without tests."""
        return {
            "data": repr(self.data),
            "selected_point": self.points[self.selected][0],
            "selected": self.result.to_json(),
            "elapsed_s": self.elapsed_s,
        }


def run_config(cfg: dict, data=None, strict: bool = True) -> dict:
    t0 = time.time()
    sr = StrategyRun(cfg, data=data, strict=strict)
    # The rules as written in the config before any sweep: what you fixed in advance.
    pre_cfg = {k: v for k, v in cfg.items() if k != "sweep"}
    pre = sr.run_one(pre_cfg).metrics()
    sharpes = sorted((res.metrics().get("sharpe", 0.0) for _, _, res in sr.points), reverse=True)
    pre_rank = 1 + sum(s > pre.get("sharpe", 0.0) + 1e-12 for s in sharpes)
    verdicts = [sr.run_test(ev) for ev in expand_evaluators(cfg)]
    decided = [v for v in verdicts if v.passed is not None]
    n_pass = sum(v.passed for v in decided)
    return {
        **sr.report(),
        "sweep": [{"point": pt, "metrics": res.metrics()} for pt, _, res in sr.points],
        "preregistered": {"metrics": pre, "rank": pre_rank, "of": len(sr.points)},
        "verdicts": [v.__dict__ for v in verdicts],
        "summary": {
            "survived": n_pass, "evaluated": len(decided),
            "overall": "survived all tests" if decided and n_pass == len(decided) else "did not survive",
            "note": "Surviving these tests is not evidence the strategy will make money in future.",
        },
        "elapsed_s": round(time.time() - t0, 2),
    }
