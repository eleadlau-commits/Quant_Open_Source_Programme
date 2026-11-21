"""Backtests ask whether a result holds up. A pass means only that it survived that test."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from .run import RunRecord


@dataclass
class Verdict:
    test: str
    passed: bool | None  # None: could not be evaluated
    headline: str
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestContext:
    run: RunRecord  # the run being judged
    rerun: Callable[..., RunRecord]  # re-runs the same simulator with changed settings


@runtime_checkable
class Backtest(Protocol):
    id: str
    name: str

    def evaluate(self, ctx: BacktestContext, **params: Any) -> Verdict: ...
