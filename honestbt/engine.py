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
* Futures (config has an ``instrument``): P&L is in dollars per contract
  (points x point value), market orders and stops pay slippage in ticks,
  target limits fill at their price, and every side pays commission.
* Brackets (stop / target) are checked bar by bar from the entry bar on. A bar
  that opens through the stop fills at its open. If one minute bar touches
  both stop and target we cannot know which came first, so we assume the stop
  (and count it as ``stop_both_touched``).
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
class FuturesCostModel:
    """Costs for a futures contract, in ticks and dollars."""

    commission_per_side: float = 0.85  # dollars per contract, all-in (broker + exchange + NFA)
    slippage_ticks: float = 1.0  # market orders (entry, flat-at-close)
    stop_slippage_ticks: float = 1.0  # stop orders become market orders when hit
    target_slippage_ticks: float = 0.0  # resting limit: fills at its price (optimistic, see README)
    multiplier: float = 1.0  # global stress factor (cost_stress)


@dataclass
class Instrument:
    symbol: str = "MNQ"
    tick_size: float = 0.25
    point_value: float = 2.0  # dollars per index point (MNQ 2, NQ 20)
    capital: float = 10000.0  # account size used to turn dollars into returns


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
    side: int = 1
    pnl_usd: float | None = None  # futures only, for `weight` contracts
    r_multiple: float | None = None  # net result in units of the initial risk


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
    out = _summarize(periods, trades, ppy)
    if trades and trades[0].pnl_usd is not None:
        pnl = np.array([t.pnl_usd for t in trades])
        rr = np.array([t.r_multiple for t in trades if t.r_multiple is not None])
        out.update(total_pnl_usd=float(pnl.sum()), avg_pnl_usd_per_trade=float(pnl.mean()),
                   avg_r_per_trade=float(rr.mean()) if len(rr) else None,
                   long_trades=sum(t.side > 0 for t in trades), short_trades=sum(t.side < 0 for t in trades))
    return out


def _summarize(periods: pd.Series, trades: list[Trade], ppy: float = 52.0) -> dict:
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


def in_time_frame(cfg: dict, times: list) -> list:
    """Keep decision times inside ``cfg["time_frame"]`` ({"start": "YYYY-MM-DD", "end": ...}, both optional)."""
    tf = cfg.get("time_frame") or {}
    lo = np.datetime64(tf["start"], "D") if tf.get("start") else None
    hi = np.datetime64(tf["end"], "D") if tf.get("end") else None
    if lo is None and hi is None:
        return list(times)
    days = lambda t: np.datetime64(t, "D")
    return [t for t in times if (lo is None or days(t) >= lo) and (hi is None or days(t) <= hi)]


def build_strategy(cfg: dict):
    spec = cfg["strategy"]
    cls = get("strategy", spec["plugin"])
    params = {p.name: p.default for p in cls.plugin_info.params}
    params.update(spec.get("params", {}))
    return cls(**params)


def _bracket_exit(path, side: int, stop: float | None, target: float | None):
    """First bar index where the stop or target is hit, with fill price and reason."""
    n = len(path)
    for j in range(n):
        o, h, l = path.open[j], path.high[j], path.low[j]
        if stop is not None:
            if j > 0 and (o - stop) * side <= 0:
                return j, float(o), "stop_gap"
            stop_hit = (l <= stop) if side > 0 else (h >= stop)
        else:
            stop_hit = False
        tgt_hit = target is not None and ((h >= target) if side > 0 else (l <= target))
        if stop_hit and tgt_hit:
            return j, float(stop), "stop_both_touched"
        if stop_hit:
            return j, float(stop), "stop"
        if tgt_hit:
            if j > 0 and (o - target) * side >= 0:
                return j, float(o), "target"  # gapped through the limit: filled at the (better) open
            return j, float(target), "target"
    return None


def run(data: MarketData, cfg: dict, strict: bool = True, decision_filter=None) -> RunResult:
    """Run one concrete (already sweep-expanded) config."""
    if (cfg.get("strategy") or {}).get("plugin") == "python":  # a strategy written as a Python file
        from .positions import run as run_positions
        return run_positions(data, cfg, decision_filter)
    strat = build_strategy(cfg)
    futures = cfg.get("instrument") is not None
    if futures:
        inst = Instrument(**cfg["instrument"])
        fcost = FuturesCostModel(**(cfg.get("costs") or {}))
    else:
        cost = CostModel(**(cfg.get("costs") or {}))
    trades: list[Trade] = []
    skipped: list[dict] = []
    period_net: dict = {}
    period_gross: dict = {}
    checked: set[str] = set()

    times = in_time_frame(cfg, strat.decision_times(data))
    if decision_filter is not None:
        times = [t for t in times if decision_filter(t)]
    for t in times:
        entries, t_ns, R = [], np.datetime64(t, "ns"), None
        for tp in strat.poll_schedule(t):
            tp_ns = np.datetime64(tp, "ns")
            view = GuardedView(data, tp_ns)
            R = Resolver(cfg, view, data.feature_cache)
            got = strat.decide(view, R)
            if got is None:
                break
            if got:
                entries, t_ns = got, tp_ns
                break
        net = gross = 0.0
        for e in entries:
            side = int(e.side)
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
            en_raw = float(path.open[0])

            # bracket, priced from the actual fill
            stop = target = risk = None
            if e.stop_price is not None:
                stop = float(e.stop_price)
            elif e.stop_dist is not None:
                stop = en_raw - side * float(e.stop_dist)
            if stop is not None:
                risk = (en_raw - stop) * side
                if risk <= 0:  # filled beyond the stop already: exit at once
                    risk = None
                elif e.target_r is not None:
                    target = en_raw + side * float(e.target_r) * risk
            br = _bracket_exit(path, side, stop if risk else None, target) if risk else None
            j_sig = hits[0] + 1 if len(hits) and hits[0] + 1 < len(path) else None

            if stop is not None and risk is None:
                j, x_t, x_raw, reason = 0, path.ts[0] + MINUTE, float(path.close[0]), "stop"
            elif br is not None and (j_sig is None or br[0] < j_sig):
                j, x_raw, reason = br
                x_t = path.ts[j]  # filled during bar j
            elif j_sig is not None:
                j = j_sig
                x_t, x_raw, reason = path.ts[j], float(path.open[j]), "signal"
            else:
                j = len(path) - 1
                x_t, x_raw = path.ts[j], float(path.close[j])
                expected_last = np.datetime64(e.max_exit_time, "ns") - MINUTE
                reason = "time_stop" if path.ts[-1] >= expected_last - 30 * MINUTE else "delisted_or_halted"
                x_t = x_t + MINUTE  # sold at that bar's close

            pnl_usd = r_mult = None
            if futures:
                tick, m = inst.tick_size, fcost.multiplier
                slip_x = {"target": fcost.target_slippage_ticks, "stop": fcost.stop_slippage_ticks,
                          "stop_gap": fcost.stop_slippage_ticks, "stop_both_touched": fcost.stop_slippage_ticks}
                en_px = en_raw + side * fcost.slippage_ticks * tick * m
                x_px = x_raw - side * slip_x.get(reason, fcost.slippage_ticks) * tick * m
                gross_usd = side * (x_raw - en_raw) * inst.point_value
                per_contract = side * (x_px - en_px) * inst.point_value - 2 * fcost.commission_per_side * m
                g, n_ = gross_usd / inst.capital, per_contract / inst.capital
                pnl_usd = per_contract * e.weight
                if risk:
                    r_mult = per_contract / (risk * inst.point_value)
            else:
                en_px = en_raw * (1 + side * cost.cost_frac(en_raw, path.ts[0]))
                x_px = x_raw * (1 - side * cost.cost_frac(x_raw, x_t))
                g = side * (x_raw / en_raw - 1)
                n_ = side * (x_px / en_px - 1)
                if risk:
                    r_mult = n_ * en_raw / risk
            net += e.weight * n_
            gross += e.weight * g
            trades.append(Trade(str(t), e.symbol, e.weight, str(path.ts[0]), en_px, str(x_t), x_px, reason,
                                int((x_t - path.ts[0]) // MINUTE), g, n_, e.info.get("score"),
                                side, pnl_usd, r_mult))
        key = pd.Timestamp(t)
        period_net[key] = net
        period_gross[key] = gross
    ppy = float(getattr(strat, "periods_per_year", 52.0))
    return RunResult(trades, pd.Series(period_net, dtype=float), pd.Series(period_gross, dtype=float), skipped,
                     periods_per_year=ppy)
