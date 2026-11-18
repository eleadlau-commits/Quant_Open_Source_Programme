from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class Entry:
    """An instruction to open a position at the next available bar.

    ``weight`` is the fraction of capital for percentage-return instruments
    (stocks), or the number of contracts when the config has an ``instrument``
    (futures). Optional bracket: ``stop_price`` (absolute) or ``stop_dist``
    (price units from the actual fill) sets 1R; ``target_r`` puts a limit
    order that many R from the fill.
    """

    symbol: str
    weight: float
    exit: dict  # resolved signal spec {"plugin": ..., "params": {...}}
    max_exit_time: np.datetime64  # time stop (bar starting before this is the last one held)
    info: dict[str, Any] = field(default_factory=dict)  # e.g. rank score, for the UI
    side: int = 1  # +1 long, -1 short
    stop_price: float | None = None
    stop_dist: float | None = None
    target_r: float | None = None


class Strategy:
    """Base class. Subclasses are registered with ``@register("strategy", ...)``.

    ``decide`` receives a GuardedView pinned to the decision time and a
    Resolver bound to it; it never sees MarketData directly.
    """

    periods_per_year: float = 52.0  # one period per decision time

    def __init__(self, **params):
        self.params = params

    def poll_schedule(self, t) -> list[np.datetime64]:
        """Times at which to (re)ask ``decide`` for the period starting at ``t``.

        The default asks once, at ``t``. Event-driven strategies (e.g. "enter
        after the first 5-minute close outside the box") return a list; the
        engine calls ``decide`` at each time with a view pinned to it, until it
        returns entries (filled from that time) or ``None`` (done for the period).
        """
        return [t]

    def decision_times(self, data) -> list[np.datetime64]:
        raise NotImplementedError

    def decide(self, view, resolver) -> list[Entry]:
        raise NotImplementedError
