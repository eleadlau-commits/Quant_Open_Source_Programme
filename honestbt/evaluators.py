"""What evaluator plugins receive and return: does the strategy survive honest scrutiny?

Each evaluator is ``f(ectx, **params) -> Verdict``; the evaluators themselves
are plugin folders under ``honestbt/plugins/builtin``. A "pass" means only that
the result survived that particular test. It is never a claim that the
strategy will make money.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any, Callable

import numpy as np

from .engine import RunResult

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


def period_sharpe(r: np.ndarray, ppy=52.0) -> float:
    if len(r) < 2 or np.std(r, ddof=1) == 0:
        return 0.0
    return float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(ppy))


