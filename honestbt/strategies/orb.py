"""Opening range breakout (ORB) on an index future, with an optional trend filter.

The rules, fixed in advance (every number is a patch-bay setting so the
evaluators can show how much the result depends on it):

1. Each trading day, the **box** is the high and low of the bars between
   ``box_start`` and ``box_end`` (default 09:30-09:45 New York time).
2. After the box closes, watch ``signal_minutes`` candles (default 5-minute,
   clock-aligned). The first one that **closes** above the box high is a long
   breakout, below the box low a short breakout.
3. Enter at the **open of the next candle** (the engine fills at the first
   bar starting at the decision time, which is that candle's open).
4. **1R** is ``risk_r`` x box height measured from the fill (``stop_at`` =
   ``box_height``), or the distance to the opposite side of the box
   (``stop_at`` = ``opposite_edge``). Stop 1R away, target ``target_r`` R away.
5. If neither is hit, **flat at** ``flat_time`` (default 16:00, the cash close).
6. At most one trade per day. No new entries after ``last_entry``.
7. **Trend filter** (optional): take a long only if the ``trend_timeframe``
   EMA``ema_fast`` is above EMA``ema_slow`` (default 15-minute 50/200) at the
   breakout, a short only if it is below. ``filtered_breakout`` decides what
   happens when the first breakout points the wrong way: ``skip_day``
   (default: only the day's first breakout counts, so no trade) or
   ``keep_watching`` (a later breakout in the allowed direction may trade).

For the random-direction baseline, set ``direction_feature`` to a feature
name: the trade then happens at exactly the same times as with the real rules
(filter included), but its direction is long if the feature is >= 0.5 and
short otherwise. If that does as well, the breakout direction adds nothing.
"""
from __future__ import annotations

import numpy as np

from ..features import _hhmm
from ..registry import Param, register
from .base import Entry, Strategy

MIN = np.timedelta64(1, "m")


@register("strategy", "opening_range_breakout", params=[
    Param("symbol", "str", "MNQ", "Contract to trade"),
    Param("contracts", "int", 1, "Contracts per trade"),
    Param("box_start", "str", "09:30", "Box window start (HH:MM, New York time)"),
    Param("box_end", "str", "09:45", "Box window end (HH:MM); the box is known from this time"),
    Param("signal_minutes", "int", 5, "Candle size whose close outside the box triggers entry"),
    Param("risk_r", "float", 1.0, "1R as a multiple of the box height (stop_at = box_height)"),
    Param("stop_at", "str", "box_height", "box_height | opposite_edge", choices=["box_height", "opposite_edge"]),
    Param("target_r", "float", 3.0, "Profit target in R"),
    Param("min_box_points", "float", 0.0, "Skip days whose box is smaller than this (index points)"),
    Param("last_entry", "str", "15:30", "No new entries from this time"),
    Param("flat_time", "str", "16:00", "Close any open trade at this time"),
    Param("trend_filter", "bool", False, "Only trade in the direction of the higher-timeframe EMA trend"),
    Param("trend_timeframe", "int", 15, "Trend filter candle size (minutes)"),
    Param("ema_fast", "int", 50, "Trend filter fast EMA length"),
    Param("ema_slow", "int", 200, "Trend filter slow EMA length"),
    Param("filtered_breakout", "str", "skip_day", "skip_day | keep_watching",
          choices=["keep_watching", "skip_day"]),
    Param("direction_feature", "str", "breakout", "breakout, or a feature name for a random-direction baseline"),
    Param("exit", "json", {"plugin": "never"}, "Extra exit signal on top of stop/target/flat"),
], doc="Trade the first 5-minute close outside the opening box; stop 1R, target 3R, flat at close; "
       "optional 15-minute EMA50/EMA200 trend filter.")
class OpeningRangeBreakout(Strategy):
    periods_per_year = 252.0

    def _p(self, k):
        return self.params[k]

    def decision_times(self, data):
        days = data.trading_days
        return [d.astype("datetime64[m]") + _hhmm(self._p("box_end")) for d in days]

    def poll_schedule(self, t):
        day = np.datetime64(t, "D").astype("datetime64[m]")
        tf = int(self._p("signal_minutes"))
        t = np.datetime64(t, "m")
        m = int((t - day) // MIN)
        first = (m // tf + 1) * tf  # first candle close strictly after the box end
        last = int((_hhmm(self._p("last_entry")) // MIN))
        return [day + np.timedelta64(x, "m") for x in range(first, last + 1, tf)]

    def decide(self, view, R):
        p, s = self.params, self._p("symbol")
        if s not in view.universe():
            return None
        box = {"start": p["box_start"], "end": p["box_end"]}
        # The box is fixed once it has closed, so compute it once per day (at
        # the first poll, through the guarded view) and reuse it later that day.
        key = (str(view.today), p["box_start"], p["box_end"], s)
        cache = self.__dict__.setdefault("_box", {})
        if key not in cache:
            cache[key] = (R.feature({"plugin": "opening_range", "params": {**box, "side": "high"}}, s),
                          R.feature({"plugin": "opening_range", "params": {**box, "side": "low"}}, s))
        hi, lo = cache[key]
        if not (np.isfinite(hi) and np.isfinite(lo)) or hi - lo < float(p["min_box_points"]) or hi <= lo:
            return None
        tf = int(p["signal_minutes"])
        candle = view.minute(s, start=view.as_of - tf * MIN)
        if len(candle) == 0:
            return []
        close = float(candle[-1, 3])
        side = 1 if close > hi else -1 if close < lo else 0
        if side == 0:
            return []
        info = {"score": close, "box_high": hi, "box_low": lo}
        if p["trend_filter"]:
            spread = R.feature({"plugin": "htf_ema_spread", "params": {
                "timeframe": int(p["trend_timeframe"]), "fast": int(p["ema_fast"]), "slow": int(p["ema_slow"])}}, s)
            if not np.isfinite(spread):
                return None  # not enough history for the EMAs yet: no trade
            if spread * side <= 0:
                return None if p["filtered_breakout"] == "skip_day" else []
            info["ema_spread"] = spread
        if p["direction_feature"] not in (None, "", "breakout"):
            # Random baseline: same trade times as the real rules, coin-flip direction.
            side = 1 if R.feature(p["direction_feature"], s) >= 0.5 else -1
        day = view.today.astype("datetime64[m]")
        e = Entry(symbol=s, weight=float(p["contracts"]), exit=R.resolve(p["exit"] or {"plugin": "never"}, s),
                  max_exit_time=day + _hhmm(p["flat_time"]), info=info, side=side,
                  target_r=float(p["target_r"]))
        if p["stop_at"] == "opposite_edge":
            e.stop_price = lo if side > 0 else hi
        else:
            e.stop_dist = float(p["risk_r"]) * (hi - lo)
        return [e]
