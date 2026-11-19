"""The plugin API: the one module a plugin imports from the core.

A plugin folder's code may import ``honestbt.sdk``, numpy, pandas, a short list
of standard-library modules, and its own sibling files (``from . import rules``).
It never imports another part of ``honestbt`` or another plugin's files, so any
plugin folder can be removed and the rest keep working. ``honestbt.plugins``
checks this when a plugin is loaded or imported.

This API grows only by additions. ``API_VERSION`` goes up when something is
added; a plugin says the version it was written for in ``plugin.json``.
"""
from __future__ import annotations

import numpy as np

from .data.guard import GuardedView, LookAheadError
from .data.model import CLOSE_MIN, MINUTE, OPEN_MIN, DailyBars, MarketData, minutes_of_day, monday_week
from .engine import RunResult, Trade, summarize
from .evaluators import EvalContext, Verdict, period_sharpe
from .baseline import hold_everything
from .patchbay import get_path, with_overrides
from .pystrategy import knob
from .registry import Param, register
from .signals import EntryContext, Path, run_signal
from .strategies.base import Entry, Strategy

API_VERSION = 2  # 2: knob, hold_everything

NAN = float("nan")


def hhmm(s: str) -> np.timedelta64:
    """'09:45' -> 585 minutes, as a numpy timedelta (exchange clock time)."""
    h, m = (int(x) for x in str(s).split(":"))
    return np.timedelta64(h * 60 + m, "m")


__all__ = [
    "API_VERSION", "NAN", "hhmm",
    "register", "Param",
    "MarketData", "DailyBars", "GuardedView", "LookAheadError", "MINUTE", "OPEN_MIN", "CLOSE_MIN",
    "minutes_of_day", "monday_week",
    "Strategy", "Entry",
    "Path", "EntryContext", "run_signal",
    "Verdict", "EvalContext", "RunResult", "Trade", "summarize", "period_sharpe",
    "get_path", "with_overrides",
    "knob", "hold_everything",
]
