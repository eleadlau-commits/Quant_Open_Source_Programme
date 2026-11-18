"""Top-level orchestration: config -> data -> sweep -> evaluators -> report."""
from __future__ import annotations

import json
import time
from typing import Any

from . import engine
from .evaluators import EvalContext, Verdict
from .patchbay import ConfigError, expand_sweep, validate
from .registry import get, load_plugins

_DATA_CACHE: dict[str, Any] = {}


def load_data(spec: dict):
    key = json.dumps(spec, sort_keys=True)
    if key not in _DATA_CACHE:
        if len(_DATA_CACHE) > 4:
            _DATA_CACHE.clear()
        _DATA_CACHE[key] = get("data", spec["plugin"])(**spec.get("params", {}))
    return _DATA_CACHE[key]


def run_config(cfg: dict, data=None, strict: bool = True) -> dict:
    load_plugins()
    problems = validate(cfg)
    if problems:
        raise ConfigError("; ".join(problems))
    t0 = time.time()
    data = data or load_data(cfg["data"])
    cache: dict[str, engine.RunResult] = {}

    def run_one(c: dict) -> engine.RunResult:
        key = json.dumps({k: v for k, v in c.items() if k not in ("sweep", "evaluators", "data")}, sort_keys=True)
        if key not in cache:
            cache[key] = engine.run(data, c, strict=strict)
        return cache[key]

    points = [(pt, c, run_one(c)) for pt, c in expand_sweep(cfg)]
    selected = max(range(len(points)), key=lambda i: points[i][2].metrics().get("sharpe", float("-inf")))
    # The rules as written in the config before any sweep: what you fixed in advance.
    pre_cfg = {k: v for k, v in cfg.items() if k != "sweep"}
    pre = run_one(pre_cfg).metrics()
    sharpes = sorted((res.metrics().get("sharpe", 0.0) for _, _, res in points), reverse=True)
    pre_rank = 1 + sum(s > pre.get("sharpe", 0.0) + 1e-12 for s in sharpes)
    ectx = EvalContext(data, cfg, points, selected, run_one)

    verdicts: list[Verdict] = []
    for ev in cfg.get("evaluators") or []:
        fn = get("evaluator", ev["plugin"])
        try:
            verdicts.append(fn(ectx, **ev.get("params", {})))
        except Exception as exc:  # an evaluator crashing must not look like a pass
            verdicts.append(Verdict(ev["plugin"], None, "Evaluator failed", repr(exc)))

    decided = [v for v in verdicts if v.passed is not None]
    n_pass = sum(v.passed for v in decided)
    return {
        "data": repr(data),
        "selected_point": points[selected][0],
        "selected": points[selected][2].to_json(),
        "sweep": [{"point": pt, "metrics": res.metrics()} for pt, _, res in points],
        "preregistered": {"metrics": pre, "rank": pre_rank, "of": len(points)},
        "verdicts": [v.__dict__ for v in verdicts],
        "summary": {
            "survived": n_pass, "evaluated": len(decided),
            "overall": "survived all tests" if decided and n_pass == len(decided) else "did not survive",
            "note": "Surviving these tests is not evidence the strategy will make money in future.",
        },
        "elapsed_s": round(time.time() - t0, 2),
    }
