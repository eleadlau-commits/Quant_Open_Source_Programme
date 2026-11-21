"""Measurements turn a run into numbers and curves. They never run the engine.

* global: one curve or number for the whole strategy (profit, Sharpe, drawdown);
* local: a series per instrument or per step (position over time, exposure, a probe).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .run import RunRecord


class Scope(str, Enum):
    GLOBAL = "global"
    LOCAL = "local"


@dataclass
class MeasurementInfo:
    id: str
    name: str
    scope: Scope
    unit: str = ""  # "growth", "%", "USD", "shares", ...
    doc: str = ""


@runtime_checkable
class Measurement(Protocol):
    info: MeasurementInfo

    def compute(self, run: RunRecord, **params: Any) -> Any:
        """A number, a time series, or a series per instrument."""
        ...
