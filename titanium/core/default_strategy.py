"""The default strategy as a strategy you can open and run: the pinned "Default" tab.

It does what the yardstick in ``core/baseline.py`` does (equal weight in everything in the
dataset, put back to equal each month), written as ordinary strategy code so it can be shown
in the patch bay and the code view and run like any other strategy. Its logic is read-only in
the app; duplicate it to change it. The yardstick that Compare and the backtests measure every
run against stays ``baseline.HoldEverything``, so turning this one's knobs never moves it.
"""
from __future__ import annotations

from .strategy import StrategyGraph
from .strategy_code import import_python

DEFAULT_STRATEGY_ID = "default-strategy"  # never a generated id (those are "s-…")
DEFAULT_STRATEGY_NAME = "Default strategy"
DEFAULT_STRATEGY_TAB = "Default"  # the short label on its tab
COPY_NAME = "Hold everything"  # what a duplicate of it is called

SOURCE = '''"""Equal weight in everything in the dataset, put back to equal each month."""

from titanium.sdk import knob, module


def new_month(view):
    """True on the first trading day of a month (the last finished day was in another month)."""
    for s in view.universe():
        days = view.bars(s, "1d")
        if len(days):
            return days["end"].iloc[-1].month != view.today.month
    return False


@module(id="hold", name="Hold everything", kind="decide")
def decide(view, portfolio):
    """Equal weight in every name at the start and each new month; hold in between."""
    rebalance_monthly = knob("rebalance_monthly", True)
    exposure = knob("exposure", 1.0, lo=0.1, hi=1.0)
    if portfolio.positions and not (rebalance_monthly and new_month(view)):
        return None  # hold what we have
    names = view.universe()
    return {s: exposure / len(names) for s in names} if names else {}
'''


def default_strategy() -> StrategyGraph:
    """A fresh copy of the default strategy, with no dataset picked yet."""
    g = import_python(SOURCE, DEFAULT_STRATEGY_ID, DEFAULT_STRATEGY_NAME)
    g.settings = {**g.settings, "datasets": []}
    return g


def is_default(strategy_id: str | None) -> bool:
    return strategy_id == DEFAULT_STRATEGY_ID
