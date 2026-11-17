"""Backtest engine: decisions -> fills -> trades -> period returns.

Fill rules (the honest part):

* An order decided at time ``t`` fills at the open of the first bar starting at
  or after ``t``. Deciding at 09:30 therefore buys the 09:30 opening print.
* An exit signal raised at the close of bar ``i`` fills at the open of bar
  ``i+1``. If the time stop is hit, the position sells at the last held bar's
  close (market-on-close).
* If a symbol stops trading (delisting, halt) the position is marked out at its
  last traded price and flagged ``delisted``; it is never silently dropped.
* Positions are only managed during the regular session: exit signals see
  regular-session bars and exits fill at regular-session prices.
* Every fill pays half the spread plus slippage. Spreads are wider in the first
  minutes after the open and never narrower than half a cent per share.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .data.guard import GuardedView
from .data.model import CLOSE_MIN, MINUTE, OPEN_MIN, MarketData, minutes_of_day
from .patchbay import Resolver
from .registry import get
from .signals import EntryContext, Path, check_causal, run_signal


@dataclass
class CostModel:
    half_spread_bps: float = 5.0
    slippage_bps: float = 3.0
    open_multiplier: float = 3.0  # spreads in the first `open_minutes` after 09:30
    open_minutes: int = 5
    min_half_spread: float = 0.005  # dollars per share
    multiplier: float = 1.0  # global stress factor

    def cost_frac(self, price: float, ts: np.datetime64) -> float:
        mod = int((ts - ts.astype("datetime64[D]")) // MINUTE)
        bps = self.half_spread_bps
        if mod < 9 * 60 + 30 + self.open_minutes:
            bps *= self.open_multiplier
        frac = max(bps / 1e4, self.min_half_spread / max(price, 1e-9)) + self.slippage_bps / 1e4
        return frac * self.multiplier


@dataclass
class Trade:
    decision_time: str
    symbol: str
    weight: float
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    reason: str
    minutes_held: int
    gross_return: float
    net_return: float
    score: float | None = None


@dataclass
class RunResult:
    trades: list[Trade]
    periods: pd.Series  # decision_time -> portfolio return for that period (net)
    periods_gross: pd.Series
    skipped: list[dict] = field(default_factory=list)
    periods_per_year: float = 52.0

    def metrics(self) -> dict:
        return summarize(self.periods, self.trades, self.periods_per_year)

    def to_json(self, max_trades: int = 500) -> dict:
        eq = (1 + self.periods).cumprod()
        return {
            "metrics": self.metrics(),
            "equity": {"t": [str(t) for t in eq.index], "v": eq.round(6).tolist()},
            "periods": {"t": [str(t) for t in self.periods.index], "v": self.periods.round(6).tolist()},
            "trades": [asdict(t) for t in self.trades[:max_trades]],
            "n_trades": len(self.trades),
            "skipped": self.skipped[:50],
        }


def summarize(periods: pd.Series, trades: list[Trade], ppy: float = 52.0) -> dict:
    r = periods.to_numpy(float)
    n = len(r)
    if n == 0:
        return {"n_periods": 0, "n_trades": 0}
    mean, sd = float(np.mean(r)), float(np.std(r, ddof=1)) if n > 1 else 0.0
    eq = np.cumprod(1 + r)
    dd = float(np.min(eq / np.maximum.accumulate(eq) - 1))
    tr = np.array([t.net_return for t in trades]) if trades else np.array([])
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {
        "n_periods": n,
        "n_trades": len(trades),
        "mean_period_return": mean,
        "sharpe": float(mean / sd * np.sqrt(ppy)) if sd > 0 else 0.0,
        "total_return": float(eq[-1] - 1),
        "max_drawdown": dd,
        "hit_rate_trades": float(np.mean(tr > 0)) if len(tr) else None,
        "avg_minutes_held": float(np.mean([t.minutes_held for t in trades])) if trades else None,
        "exit_reasons": reasons,
    }


def build_strategy(cfg: dict):
    spec = cfg["strategy"]
    cls = get("strategy", spec["plugin"])
    params = {p.name: p.default for p in cls.plugin_info.params}
    params.update(spec.get("params", {}))
    return cls(**params)


def run(data: MarketData, cfg: dict, strict: bool = True, decision_filter=None) -> RunResult:
    """Run one concrete (already sweep-expanded) config."""
    strat = build_strategy(cfg)
    cost = CostModel(**(cfg.get("costs") or {}))
    trades: list[Trade] = []
    skipped: list[dict] = []
    period_net: dict = {}
    period_gross: dict = {}
    checked: set[str] = set()

    times = strat.decision_times(data)
    if decision_filter is not None:
        times = [t for t in times if decision_filter(t)]
    for t in times:
        t_ns = np.datetime64(t, "ns")
        view = GuardedView(data, t_ns)
        R = Resolver(cfg, view, data.feature_cache)
        entries = strat.decide(view, R)
        net = gross = 0.0
        for e in entries:
            ts, arr = data.ts[e.symbol], data.arr[e.symbol]
            i0 = int(np.searchsorted(ts, t_ns, "left"))
            iend = int(np.searchsorted(ts, np.datetime64(e.max_exit_time, "ns"), "left"))
            if i0 >= iend or ts[i0].astype("datetime64[D]") != t_ns.astype("datetime64[D]"):
                skipped.append({"decision_time": str(t), "symbol": e.symbol, "reason": "no_fill_on_decision_day"})
                continue
            seg_ts, seg = ts[i0:iend], arr[i0:iend]
            mod = minutes_of_day(seg_ts)
            regular = (mod >= OPEN_MIN) & (mod < CLOSE_MIN)
            regular[0] = True  # the entry bar itself (may be pre-market if decided pre-market)
            path = Path.from_array(seg_ts[regular], seg[regular])
            ctx = EntryContext(e.symbol, ts[i0], float(path.open[0]),
                               feature=lambda name, s=e.symbol, R=R: R.feature(name, s))
            sig_key = repr(e.exit.get("plugin"))
            if strict and sig_key not in checked:
                check_causal(e.exit, path, ctx)
                checked.add(sig_key)
            sig = run_signal(e.exit, path, ctx)
            hits = np.flatnonzero(sig)
            if len(hits) and hits[0] + 1 < len(path):
                j = hits[0] + 1
                x_t, x_raw, reason = path.ts[j], float(path.open[j]), "signal"
            else:
                j = len(path) - 1
                x_t, x_raw = path.ts[j], float(path.close[j])
                expected_last = np.datetime64(e.max_exit_time, "ns") - MINUTE
                reason = "time_stop" if path.ts[-1] >= expected_last - 30 * MINUTE else "delisted_or_halted"
                x_t = x_t + MINUTE  # sold at that bar's close
            en_raw = float(path.open[0])
            en_px = en_raw * (1 + cost.cost_frac(en_raw, path.ts[0]))
            x_px = x_raw * (1 - cost.cost_frac(x_raw, x_t))
            g = x_raw / en_raw - 1
            n_ = x_px / en_px - 1
            net += e.weight * n_
            gross += e.weight * g
            trades.append(Trade(str(t), e.symbol, e.weight, str(path.ts[0]), en_px, str(x_t), x_px, reason,
                                int((x_t - path.ts[0]) // MINUTE), g, n_, e.info.get("score")))
        key = pd.Timestamp(t)
        period_net[key] = net
        period_gross[key] = gross
    return RunResult(trades, pd.Series(period_net, dtype=float), pd.Series(period_gross, dtype=float), skipped)
