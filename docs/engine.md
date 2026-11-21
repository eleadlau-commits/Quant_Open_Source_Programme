# The simulator

One engine runs every strategy (`titanium/core/sim/`). Measurements, backtests and the run
view only read the `RunRecord` it produces. A live engine later swaps the feed and the broker.

```python
from titanium.core.sim import SimEngine
record = SimEngine(workspace.datasets).run(graph, dataset_id, {"capital": 50_000})
# or, in the app: workspace.runs.run(strategy_id)  /  prepare -> execute (worker) -> commit
```

## Each step, at decision time t

1. The broker works open orders through the bars that ended by `t`; fills go to the ledger.
2. Names that missed a whole session (known delisted) are closed at their last price, flagged.
3. Positions are marked at the latest visible closes; the portfolio state is recorded.
4. The strategy sees a guarded view pinned to `t` and that state, and decides.
5. The decision becomes orders. Target weights are sized from what is known at `t`: the
   latest visible close and the equity marked with it, in whole lots, sells first, buys
   limited to the cash there is at those prices. The orders fill at the next bar's open.

Because the fill price can differ from the sizing price (an overnight gap), a stock buy can
cost a little more than the cash there was. The simulator lets cash go slightly negative
rather than resizing at the fill (which would use the fill price to size), and logs the first
step where it happens.

## Fills

- Market orders fill at the open of the first bar starting at or after the decision.
- Limit and stop orders are checked bar by bar; a bar opening through the level fills at its open.
- Brackets (`orders.bracket(...)`): exits work once the entry fills, cancel each other, are
  reduce-only, and if one bar touches both the stop is taken.
- Stocks trade in the regular session unless `extended_hours`; futures in every session.

## Settings

| Key | Default | Meaning |
| --- | --- | --- |
| `decide_at` | `"15:50"` | Exchange time, or a list of times |
| `every` | `"day"` | `day`, `week` or `month` |
| `start`, `end` | data span | `YYYY-MM-DD` |
| `capital` | 100,000 | Notional capital in account currency |
| `costs` | see below | `{"equity": {...}, "futures": {...}, "stress": 1}` |
| `max_gross` | 1.0 | Cap on the sum of absolute target weights |
| `min_trade` | 0 | Skip target trades smaller than this share of equity |
| `extended_hours` | stocks off, futures on | Work orders outside the regular session |
| `datasets` | | Datasets the strategy reads; the first is traded |
| `probes` | | Module ids (or `module.port`) whose outputs are recorded each step |

Stock costs: half-spread 5 bps (3x in the first 5 minutes after the open, at least half a cent
a share) plus 3 bps slippage. Futures: 1 tick slippage on market and stop orders, none on
limits, plus 0.85 commission per contract per side.

## The record

`states` (one per step plus the end), `fills`, `trades` (flat to flat, net of costs, open ones
flagged `open`), `probes`, `log`, `status` (`done`, `cancelled`, `failed`) and `error`.
