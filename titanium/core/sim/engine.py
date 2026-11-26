"""The simulator: the one engine every run, measurement and backtest goes through.

Each step at decision time ``t``:

1. the broker works open orders through the bars that ended by ``t``; fills go to the
   ledger and the recorder;
2. positions in names that are known to have stopped trading are closed at their last
   price and flagged ``delisted``;
3. the ledger is marked at the latest closes visible at ``t`` and the portfolio state
   is recorded;
4. the strategy gets a guarded view pinned to ``t`` and that state, and decides;
5. the decision becomes orders. Target weights are sized from what is known at ``t``:
   the latest visible close and the equity marked with it, in whole lots, sells before
   buys, buys limited to the cash there is (no leverage beyond ``max_gross``). New targets
   replace rebalance orders still waiting for a bar; market orders the strategy sent itself
   and that are still waiting count as already done. They fill
   at the next bar's open; if that gaps up, cash may dip slightly below zero, which is
   allowed and logged.

Settings (the traded market's defaults, then the strategy's ``graph.settings``, then the run's
``settings``; see :mod:`titanium.core.layers`):
``decide_at``, ``every``, ``start``, ``end`` (see :mod:`.clock`), ``capital``
(100,000), ``costs`` (see :mod:`.costs`), ``max_gross`` (1.0), ``min_trade`` (skip target trades smaller than this
fraction of equity, 0), ``extended_hours``
(the market's default: Nasdaq regular session only, CME round the clock), ``datasets`` (extra datasets the strategy
reads, e.g. news or features) and ``probes`` (module ids, or ``"module.port"``, whose
outputs are recorded every step).

The run can be cancelled between steps: pass ``cancel`` (a ``threading.Event`` or any
callable returning True to stop). A cancelled run returns what it recorded so far
with ``status == "cancelled"``.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from ..data import LookAheadError
from ..instruments import InstrumentKind
from ..layers import merge_settings
from ..orders import Order, OrderType, Side
from ..portfolio import PortfolioState
from ..run import RunRecord
from ..strategy import Decision, StrategyGraph, graph_to_dict
from ..strategy_compile import compile_graph, to_decision
from .broker import SimBroker
from .clock import DecisionClock
from .costs import CostModel
from .feed import DataProvider, DatasetFeed
from .ledger import SimLedger
from .recorder import Recorder

UTC = timezone.utc
DEFAULT_CAPITAL = 100_000.0


class RunFailed(RuntimeError):
    """The strategy (or its settings) failed. ``record`` holds what was recorded up to then."""

    def __init__(self, message: str, record: RunRecord):
        super().__init__(message)
        self.record = record


as_decision = to_decision  # dict of weights, orders, a Decision or None


def _compile(strategy: Any):
    if isinstance(strategy, StrategyGraph):
        return compile_graph(strategy)
    if not hasattr(strategy, "decide"):
        raise TypeError("a strategy is a StrategyGraph or an object with decide(view, portfolio)")
    return strategy


def _snapshot(strategy: Any) -> dict[str, Any]:
    graph = strategy if isinstance(strategy, StrategyGraph) else getattr(strategy, "graph", None)
    if isinstance(graph, StrategyGraph):
        return graph_to_dict(graph)
    return {"name": getattr(strategy, "name", type(strategy).__name__)}


def _cancelled(cancel: Any) -> bool:
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return bool(cancel.is_set())
    return bool(cancel())


class SimEngine:
    """Implements :class:`titanium.core.engine.Engine`."""

    def __init__(self, provider: DataProvider):
        self.provider = provider

    def run(self, strategy: Any, dataset_id: str, settings: dict[str, Any] | None = None, *,
            cancel: Any = None, progress: Callable[[float], None] | None = None,
            run_id: str | None = None) -> RunRecord:
        graph_settings = dict(getattr(strategy, "settings", None) or getattr(getattr(strategy, "graph", None),
                                                                              "settings", None) or {})
        cfg = {**graph_settings, **(settings or {})}
        extra = [d for d in (cfg.get("datasets") or []) if d != dataset_id]
        ids = [dataset_id] + extra
        version = getattr(self.provider, "version", None)
        if version is None and hasattr(self.provider, "get"):
            version = lambda i: getattr(self.provider.get(i), "version", "")  # noqa: E731
        feed = DatasetFeed(self.provider, ids)
        data = feed.data
        # the market's defaults sit under the strategy's settings and the run's
        cfg = merge_settings(data.market.defaults.settings(), graph_settings, settings)
        capital = float(cfg.get("capital", DEFAULT_CAPITAL))
        record = RunRecord(
            id=run_id or f"run-{uuid.uuid4().hex[:8]}",
            strategy_id=str(getattr(strategy, "id", "") or getattr(getattr(strategy, "graph", None), "id", "")),
            strategy_snapshot=_snapshot(strategy), dataset_id=dataset_id,
            dataset_version=version(dataset_id) if version else "", created=datetime.now(UTC),
            settings=cfg, capital=capital, market=data.market.id)
        broker = SimBroker(data, CostModel.from_settings(cfg.get("costs")), cfg.get("extended_hours"))
        rec = Recorder(record, data.market, broker.spec)
        try:
            self._run(strategy, cfg, data, feed, broker, rec, capital, cancel, progress)
        except Exception as e:  # noqa: BLE001 - recorded, then raised for the caller
            record.status, record.error = "failed", f"{type(e).__name__}: {e}"
            rec.log(None, f"run failed: {record.error}")
            record.finished = datetime.now(UTC)
            raise RunFailed(record.error, record) from e
        record.finished = datetime.now(UTC)
        return record

    # ------------------------------------------------------------------------------------
    def _run(self, strategy, cfg, data, feed, broker: SimBroker, rec: Recorder, capital, cancel, progress):
        record = rec.record
        spans = [s for s in (data.span(k) for k in data.instruments) if s is not None]
        if not spans:
            raise ValueError("the dataset has no bars to trade")
        clock = DecisionClock(data.market, min(s[0] for s in spans), max(s[1] for s in spans), cfg)
        times = list(clock.times())
        strat = _compile(strategy)
        probes = list(cfg.get("probes") or [])
        max_gross = float(cfg.get("max_gross", 1.0))
        min_trade = float(cfg.get("min_trade", 0.0))
        cal = data.market.calendar
        ledger = SimLedger(capital, broker.spec)
        rec.log(times[0] if times else None,
                f"start: {len(times)} decisions, capital {capital:,.0f} {data.market.currency}")

        overdrawn = False
        for n, t in enumerate(times):
            if _cancelled(cancel):
                record.status = "cancelled"
                rec.log(t, "cancelled")
                break
            self._book(broker.fills(t), ledger, rec)
            if ledger.cash < 0 and not overdrawn:
                rec.log(t, f"cash went below zero ({ledger.cash:,.2f}): fills cost more than the prices "
                           "orders were sized at (allowed, and shown here)")
            overdrawn = ledger.cash < 0
            view = feed.view(t)
            # names that missed a whole session are known to be delisted: close at the last price
            prev = cal.previous_trading_day(view.today) if hasattr(cal, "previous_trading_day") else None
            for key in list(ledger.positions):
                span = data.span(key)
                if prev is not None and span is not None and span[1] < prev:
                    last = broker.last_bar(key)
                    fill = broker.force_fill(key, last[0], last[1], "delisted")
                    if fill is not None:
                        self._book([fill], ledger, rec)
                        rec.log(t, f"{key} stopped trading on {span[1]}: closed at its last price {last[1]:.4g}")
            state = ledger.mark(t, {k: broker.mark(k, t) for k in ledger.positions})
            state.orders = broker.open_orders()
            rec.state(state)

            decision = self._decide(strat, view, state, probes, rec, t)
            if decision is not None:
                self._act(decision, view, data, state, ledger, broker, rec, t, max_gross, min_trade)
            if progress is not None:
                progress((n + 1) / len(times))

        end = clock.end_time()
        if record.status != "cancelled":
            self._book(broker.fills(end), ledger, rec)
            last_t = record.states[-1].time if record.states else end
            data_end = max((b[0] for b in map(broker.last_bar, data.instruments) if b), default=end)
            final_t = max(min(end, data_end), last_t)
            final = ledger.mark(final_t, {k: broker.mark(k, final_t) for k in ledger.positions})
            final.orders = broker.open_orders()
            if not record.states or final.time > record.states[-1].time:
                rec.state(final)
            for key, p in ledger.positions.items():
                rec.log(final.time, f"still holding {p.quantity:g} {key} at the end")
        marks = {k: p.last_price for k, p in ledger.positions.items()}
        rec.finish(marks)
        for at, msg in broker.log:
            rec.log(at, msg)
        if record.states:
            s = record.states[-1]
            rec.log(s.time, f"end: equity {s.equity:,.2f} ({(s.growth - 1) * 100:+.2f}%), "
                            f"{len(record.trades)} trades, costs {ledger.costs:,.2f}")

    @staticmethod
    def _book(fills, ledger: SimLedger, rec: Recorder) -> None:
        for f in fills:
            ledger.apply(f)
            rec.fill(f)

    @staticmethod
    def _decide(strat, view, state: PortfolioState, probes: list[str], rec: Recorder, t: datetime):
        if probes and hasattr(strat, "run_modules"):
            outputs = strat.run_modules(view, state)
            for name in probes:
                mid, _, port = name.partition(".")
                if mid not in outputs:
                    continue
                if port:
                    rec.probe(t, name, outputs[mid].get(port))
                else:
                    ports = [p for p in outputs[mid] if p != "result"] or ["result"]
                    for p in ports:
                        rec.probe(t, mid if p == "result" or len(ports) == 1 else f"{mid}.{p}", outputs[mid][p])
            return as_decision(outputs[strat.entry]["result"])
        return as_decision(strat.decide(view, state))

    def _act(self, decision: Decision, view, data, state, ledger: SimLedger, broker: SimBroker, rec: Recorder,
             t: datetime, max_gross: float, min_trade: float = 0.0) -> None:
        universe = set(view.universe())

        def check(key: str) -> bool:
            if key in universe or ledger.quantity(key):
                return True
            span = data.span(key) if key in data.instruments else None
            if span is None or span[0] >= view.today:
                raise LookAheadError(f"{key} is not listed at {t:%Y-%m-%d %H:%M} UTC: the strategy can't know it yet")
            rec.log(t, f"ignored an order for {key}: it no longer trades")
            return False

        for oid in decision.cancel:
            broker.cancel(oid)
        for o in decision.orders:
            if check(o.instrument):
                broker.submit(o, t)
        if decision.targets is None:
            return
        targets = {}
        for key, w in decision.targets.items():
            if not math.isfinite(w):
                raise ValueError(f"target weight for {key} is not a number")
            if w and check(key):
                targets[key] = w
        gross = sum(abs(w) for w in targets.values())
        if gross > max_gross + 1e-12:
            targets = {k: w * max_gross / gross for k, w in targets.items()}
        # a new set of targets replaces the last one: rebalance orders still waiting for a bar
        # (two decisions before the next open) are cancelled and the trades worked out afresh,
        # so an old target can't fill on top of the new one
        for o in broker.open_orders():
            if o.tag == "rebalance" and o.type is OrderType.MARKET and o.parent is None:
                broker.cancel(o.id)
        # market orders the strategy sent itself and that are still waiting count as done
        pending: dict[str, float] = {}
        for o in broker.open_orders():
            if o.type is OrderType.MARKET and o.parent is None:
                pending[o.instrument] = pending.get(o.instrument, 0.0) + int(o.side) * o.quantity
        keys = sorted(set(targets) | set(ledger.positions) | set(pending))
        # sized from what is known at t: the latest visible close and the equity marked with it.
        # The order still fills at the next bar's open, which may differ (a gap): see docs/engine.md.
        prices, skip = {}, set()
        for k in keys:
            mark = broker.mark(k, t)
            if broker.next_open(k, t) is None or not mark == mark or mark <= 0:
                skip.add(k)
            else:
                prices[k] = mark
        equity = ledger.equity_at(prices)
        deltas: list[tuple[str, float]] = []
        for k in keys:
            if k in skip:
                rec.log(t, f"no price yet, or no bar left, to trade {k}: left as it is")
                continue
            spec = broker.spec(k)
            unit = prices[k] * spec.multiplier
            raw = targets.get(k, 0.0) * equity / unit if unit > 0 else 0.0
            lot = spec.lot_size or 1.0
            want = math.trunc(raw / lot + 1e-9) * lot
            delta = want - ledger.quantity(k) - pending.get(k, 0.0)
            if abs(delta) >= lot - 1e-12 and (want == 0 or abs(delta) * unit >= min_trade * equity):
                deltas.append((k, delta))
        # sells first so their cash pays for the buys; stock buys limited to the cash there is
        deltas.sort(key=lambda kd: kd[1] > 0)
        cash = ledger.cash - sum(q * prices[k] * broker.spec(k).multiplier for k, q in pending.items()
                                 if k in prices and broker.spec(k).kind is not InstrumentKind.FUTURE)
        for k, delta in deltas:
            spec = broker.spec(k)
            price = prices[k]
            qty = abs(delta)
            at = t
            cost = broker.costs.cost(spec, data.market, price, qty, at)
            if spec.kind is not InstrumentKind.FUTURE:
                if delta > 0:
                    lot = spec.lot_size or 1.0
                    each = price * spec.multiplier + cost / qty
                    afford = math.trunc(max(cash, 0.0) / each / lot + 1e-9) * lot
                    if afford < qty:
                        if afford <= 0:
                            rec.log(t, f"not enough cash to buy {k}")
                            continue
                        qty = afford
                        cost = broker.costs.cost(spec, data.market, price, qty, at)
                cash -= (1 if delta > 0 else -1) * qty * price * spec.multiplier + cost
            broker.submit(Order(k, Side.BUY if delta > 0 else Side.SELL, qty, OrderType.MARKET, tag="rebalance"), t)
