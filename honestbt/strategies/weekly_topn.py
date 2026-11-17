"""Guiding strategy family: weekly top-N movers, held until a proper reversal.

Every week, on the first trading day (Monday unless it is a holiday), at the
decision time (default 09:30, i.e. using only pre-market information):

1. take the listed universe (delisted names included until they delist);
2. filter: last close >= ``min_price`` and 20-day dollar volume >= ``min_dollar_volume``;
3. rank by ``rank_by`` (default: pre-market gap %) and take the top ``top_n``;
4. buy each at the next bar's open, equal weight;
5. exit on the first ``exit`` signal (default: smoothed price falls k x ATR
   from its peak), or at the time stop (default: the week's last close).

Every word in "top 5 fastest growing" and "proper reversal" is a parameter,
so the patch bay can sweep and map them.
"""
from __future__ import annotations

import numpy as np

from ..registry import Param, register
from ..data.model import monday_week
from .base import Entry, Strategy

DAY = np.timedelta64(1, "D")


@register("strategy", "weekly_topn", params=[
    Param("decision_time", "str", "09:30", "HH:MM; only data that finished before this is visible"),
    Param("top_n", "int", 5, "How many names to buy"),
    Param("rank_by", "str", "gap", "Feature used to rank candidates (descending)"),
    Param("min_price", "float", 5.0, "Universe filter: last close at least this"),
    Param("price_feature", "str", "price", "Feature giving the price used by the filter"),
    Param("min_dollar_volume", "float", 5e6, "Universe filter: average daily dollar volume at least this"),
    Param("liquidity_feature", "str", "adv20", "Feature giving dollar volume for the filter"),
    Param("min_score", "float", None, "Optional: only buy if rank score is at least this (e.g. gap >= 2%)"),
    Param("hold_until", "str", "week_close", "Time stop: week_close | day_close"),
    Param("exit", "json", {"plugin": "atr_trailing", "params": {"k": 1.0, "smooth": 10}}, "Exit signal spec"),
], doc="Each week buy the top-N ranked names at the open and hold until the exit signal or time stop.")
class WeeklyTopN(Strategy):
    def decision_times(self, data):
        days = data.trading_days
        if len(days) == 0:
            return []
        week = monday_week(days)
        first_of_week = np.concatenate([[True], week[1:] != week[:-1]])
        h, m = (int(x) for x in self.params.get("decision_time", "09:30").split(":"))
        offset = np.timedelta64(h * 60 + m, "m")
        return [d.astype("datetime64[m]") + offset for d in days[first_of_week]]

    def max_exit_time(self, days, t) -> np.datetime64:
        day = np.datetime64(t, "D")
        if self.params.get("hold_until", "week_close") == "day_close":
            last = day
        else:
            same_week = days[(monday_week(days) == monday_week(np.array([day]))[0]) & (days >= day)]
            last = same_week[-1] if len(same_week) else day
        return last.astype("datetime64[m]") + np.timedelta64(16 * 60, "m")

    def decide(self, view, R):
        p = self.params
        cands = []
        for s in view.universe():
            price = R.feature(p.get("price_feature", "price"), s)
            if not (price >= p.get("min_price", 5.0)):
                continue
            liq = R.feature(p.get("liquidity_feature", "adv20"), s)
            if not (liq >= p.get("min_dollar_volume", 5e6)):
                continue
            score = R.feature(p.get("rank_by", "gap"), s)
            if not np.isfinite(score):
                continue
            if p.get("min_score") is not None and score < p["min_score"]:
                continue
            cands.append((score, s))
        cands.sort(reverse=True)
        top = cands[: int(p.get("top_n", 5))]
        if not top:
            return []
        t_end = self.max_exit_time(view.trading_days, view.as_of)
        exit_spec = p.get("exit") or {"plugin": "never"}
        return [Entry(symbol=s, weight=1.0 / len(top), exit=R.resolve(exit_spec, s),
                      max_exit_time=t_end, info={"score": score, "candidates": len(cands)})
                for score, s in top]
