from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Entry:
    """An instruction to open a long position at the next available bar."""

    symbol: str
    weight: float
    exit: dict  # resolved signal spec {"plugin": ..., "params": {...}}
    max_exit_time: np.datetime64  # time stop (bar starting before this is the last one held)
    info: dict[str, Any] = field(default_factory=dict)  # e.g. rank score, for the UI


class Strategy:
    """Base class. Subclasses are registered with ``@register("strategy", ...)``.

    ``decide`` receives a GuardedView pinned to the decision time and a
    Resolver bound to it; it never sees MarketData directly.
    """

    def __init__(self, **params):
        self.params = params

    def decision_times(self, data) -> list[np.datetime64]:
        raise NotImplementedError

    def decide(self, view, resolver) -> list[Entry]:
        raise NotImplementedError
