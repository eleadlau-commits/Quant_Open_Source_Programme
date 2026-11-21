"""The default strategy: spread the money evenly across everything in the dataset and hold.

It is the yardstick every run is measured against. It goes through the same engine as
the strategy (same dataset, dates, capital, decision time and costs), so the comparison
is fair: whatever the strategy pays to trade, the default strategy pays too.

It is asked at every step of the strategy's schedule. At each rebalance (the first step of a
month by default) it targets equal weight in every instrument the
guarded view lists then, so names that list later join at the next rebalance and names
that stop trading are closed by the engine. Between rebalances it holds and the weights
drift, as holding does.
"""
from __future__ import annotations

from typing import Any

DEFAULT_ID = "default"
DEFAULT_NAME = "Default strategy"
# settings of a strategy run the default strategy shares, so both are measured on the same terms
SHARED = ("start", "end", "capital", "costs", "decide_at", "every", "extended_hours", "max_gross")


class HoldEverything:
    id = DEFAULT_ID
    name = DEFAULT_NAME
    doc = "Equal weight in everything in the dataset, rebalanced monthly."

    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = dict(settings or {})
        self._last: tuple | None = None

    def decide(self, view, portfolio):
        # it is asked at every step of the strategy's schedule (so both records line up step for
        # step) but only rebalances when the period changes
        day = view.today
        period = {"day": (day,), "week": tuple(day.isocalendar()[:2])}.get(self.settings.get("rebalance", "month"),
                                                                           (day.year, day.month))
        if period == self._last:
            return None
        names = list(view.universe())
        if not names:
            return None
        self._last = period
        w = min(1.0, float(self.settings.get("max_gross", 1.0))) / len(names)
        return {k: w for k in names}


def baseline_settings(run_settings: dict[str, Any], rebalance: str = "month") -> dict[str, Any]:
    """The default strategy's settings for a strategy run with ``run_settings``: the same schedule,
    rebalancing every ``rebalance`` (day, week or month)."""
    out = {k: run_settings[k] for k in SHARED if k in run_settings}
    out["rebalance"] = rebalance
    out["min_trade"] = 0.002  # don't pay to nudge a weight by a sliver
    return out
