"""Position engine for strategies written as a Python file (see ``pystrategy``).

The strategy says what to hold, p_i(t): a step function that only changes at
decision times. At each decision time t_j:

1. ``decide(F, p)`` gets F, a GuardedView pinned to t_j (it cannot see anything
   later), and p, the positions it holds now ({symbol: fraction of the account}).
2. It returns the positions it wants. Symbols it leaves out go to zero.
3. Changes fill at the open of the first bar starting at or after t_j, paying
   half the spread plus slippage on the traded amount (the same cost model as
   the trade engine).
4. Between decisions the account holds those fractions; the period's return is
   the move from this fill to the next decision's fill price.

Honesty rules: you can only buy names that are listed at t_j (no future
listings); a name that stops trading is sold at its last traded price and
flagged ``delisted``; total exposure (sum of |weights|) is capped at
``max_gross`` (default 1, no leverage), scaled down proportionally if exceeded.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .data.guard import GuardedView
from .data.model import MINUTE, MarketData, monday_week
from .pystrategy import _KNOBS, StrategyFileError, load


def decision_times(data: MarketData, decide_at: str = "15:50", every: str = "day",
                   start: str | None = None, end: str | None = None) -> list[np.datetime64]:
    days = data.trading_days
    if start:
        days = days[days >= np.datetime64(start, "D")]
    if end:
        days = days[days <= np.datetime64(end, "D")]
    if len(days) == 0:
        return []
    if every == "week":
        wk = monday_week(days)
        days = days[np.concatenate([[True], wk[1:] != wk[:-1]])]
    h, m = (int(x) for x in str(decide_at).split(":"))
    off = np.timedelta64(h * 60 + m, "m")
    return [np.datetime64(d.astype("datetime64[m]") + off, "ns") for d in days]


def _fill(data: MarketData, sym: str, t: np.datetime64):
    """(time, open price) of the first bar starting at or after t on t's day, else None."""
    ts = data.ts[sym]
    i = int(np.searchsorted(ts, t, "left"))
    if i < len(ts) and ts[i].astype("datetime64[D]") == t.astype("datetime64[D]"):
        return ts[i], float(data.arr[sym][i, 0])
    return None


def _last(data: MarketData, sym: str, t: np.datetime64):
    """(time, close) of the last bar that ended by t, else None."""
    ts = data.ts[sym]
    i = int(np.searchsorted(ts, t - MINUTE, "right")) - 1
    return (ts[i] + MINUTE, float(data.arr[sym][i, 3])) if i >= 0 else None


def run(data: MarketData, cfg: dict, decision_filter=None):
    from .engine import CostModel, RunResult, Trade  # engine imports this module lazily

    p = cfg["strategy"]["params"]
    cost = CostModel(**(cfg.get("costs") or {}))
    max_gross = float(p.get("max_gross", 1.0))
    every = p.get("every", "day")
    from .engine import in_time_frame
    times = in_time_frame(cfg, decision_times(data, p.get("decide_at", "15:50"), every, p.get("start"), p.get("end")))
    if decision_filter is not None:
        times = [t for t in times if decision_filter(t)]

    token = _KNOBS.set(dict(p.get("knobs") or {}))
    try:
        ns = load(p["code"])
        decide = ns["decide"]
        held: dict[str, float] = {}
        mark: dict[str, float] = {}       # price each held position was last valued at
        opened: dict[str, dict] = {}      # open trade per symbol
        trades: list = []
        skipped: list[dict] = []
        net: dict = {}
        gross_r: dict = {}
        prev_key = None

        def close_trade(sym, x_t, x_raw, x_cost, reason):
            o = opened.pop(sym)
            side = 1 if o["w"] > 0 else -1
            en_px = o["px"] * (1 + side * o["cf"])
            x_px = x_raw * (1 - side * x_cost)
            trades.append(Trade(o["t"], sym, abs(o["w"]), str(o["ft"]), en_px, str(x_t), x_px, reason,
                                int((x_t - o["ft"]) // MINUTE), side * (x_raw / o["px"] - 1),
                                side * (x_px / en_px - 1), None, side))

        for t in times:
            view = GuardedView(data, t)
            today = t.astype("datetime64[D]")
            # 1. value the period that just ended, at this decision's fill prices
            px_now: dict[str, tuple] = {}
            move = 0.0
            for sym, w in list(held.items()):
                f = _fill(data, sym, t)
                if f is None:  # no bar left today: halted or delisted -> last traded price
                    lt = _last(data, sym, t)
                    f = lt if lt else (t, mark[sym])
                    if data.last_date(sym) is not None and data.last_date(sym) < today:
                        move += w * (f[1] / mark[sym] - 1)
                        close_trade(sym, f[0], f[1], cost.cost_frac(f[1], f[0]), "delisted")
                        del held[sym], mark[sym]
                        continue
                px_now[sym] = f
                move += w * (f[1] / mark[sym] - 1)
            if prev_key is not None:
                net[prev_key] += move
                gross_r[prev_key] += move

            # 2. ask the strategy what to hold now
            want = decide(view, dict(held))
            if want is None:
                want = dict(held)
            if not isinstance(want, dict):
                raise StrategyFileError(f"decide() must return a dict of {{symbol: weight}}, got {type(want).__name__}")
            listed = set(view.universe())
            target: dict[str, float] = {}
            for sym, w in want.items():
                w = float(w)
                if not math.isfinite(w):
                    raise StrategyFileError(f"decide() returned a weight that is not a number for {sym!r}")
                if w == 0:
                    continue
                if sym not in listed and sym not in held:
                    raise StrategyFileError(f"decide() at {t} asked for {sym!r}, which is not listed (or not "
                                            f"tradable) at that time")
                target[sym] = w
            g = sum(abs(w) for w in target.values())
            if g > max_gross + 1e-9:
                target = {s: w * max_gross / g for s, w in target.items()}

            # 3. trade the differences at the next bar's open
            key = pd.Timestamp(t)
            net[key] = gross_r[key] = 0.0
            for sym in sorted(set(held) | set(target)):
                old, new = held.get(sym, 0.0), target.get(sym, 0.0)
                if abs(new - old) < 1e-12:
                    continue
                f = px_now.get(sym) or _fill(data, sym, t)
                if f is None:
                    skipped.append({"decision_time": str(t), "symbol": sym, "reason": "no_fill_on_decision_day"})
                    continue
                ft, px = f
                cf = cost.cost_frac(px, ft)
                net[key] -= abs(new - old) * cf
                if sym in opened and (new == 0 or (new > 0) != (old > 0)):
                    close_trade(sym, ft, px, cf, "rebalance")
                if new != 0 and sym not in opened:
                    opened[sym] = {"t": str(t), "ft": ft, "px": px, "cf": cf, "w": new}
                if new == 0:
                    held.pop(sym, None)
                    mark.pop(sym, None)
                else:
                    held[sym] = new
                    mark[sym] = px
            for sym in held:  # positions kept as they were are valued from this decision's price on
                if sym in px_now:
                    mark[sym] = px_now[sym][1]
            prev_key = key

        # 4. value what is still held at the last close, and close the books
        if prev_key is not None:
            move = 0.0
            for sym, w in held.items():
                lt = _last(data, sym, np.datetime64(data.ts[sym][-1] + MINUTE, "ns")) if len(data.ts[sym]) else None
                if lt:
                    move += w * (lt[1] / mark[sym] - 1)
                    close_trade(sym, lt[0], lt[1], 0.0, "end_of_data")
            net[prev_key] += move
            gross_r[prev_key] += move
    finally:
        _KNOBS.reset(token)
    ppy = 52.0 if every == "week" else 252.0
    return RunResult(trades, pd.Series(net, dtype=float), pd.Series(gross_r, dtype=float), skipped,
                     periods_per_year=ppy)
