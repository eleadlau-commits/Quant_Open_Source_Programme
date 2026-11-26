# Measurements and the Run view

Measurements turn a run record into numbers and curves. They never run the engine; they read
`RunRecord.states`, `trades` and `probes` (see `docs/engine.md`). The built-in ones are
`Library.MEASUREMENTS` entries, registered by `Workspace` (`core.measurements.register_measurements`).
A plugin adds its own the same way, and the Run view lists it.

```python
from titanium.core import measurements as M
M.Sharpe().compute(record)                       # a number
M.Profit().compute(record, display="%")          # a curve: [(time, value), ...]
M.Weights().compute(record)                      # a series per instrument: {name: curve}
M.measurements(workspace.registry, kind="curve") # what the chart's picker offers
```

`MeasurementInfo.kind` says what `compute` returns: `number`, `curve` or `series`.

| Id | Kind | Scope | What it is |
| --- | --- | --- | --- |
| `profit` | curve | global | Equity as growth of 1, `%` or `currency` (`display=`) |
| `total_profit` | number | global | Profit over the whole run, in % |
| `sharpe` | number | global | Mean step return over its spread, annualised from the run's own step count; no risk-free rate |
| `drawdown`, `max_drawdown` | curve, number | global | Distance below the best equity so far, in % |
| `hit_rate` | number | global | Share of closed trades with profit after costs |
| `exposure`, `avg_exposure` | curve, number | global | Gross positions as a share of equity |
| `positions`, `weights` | series | local | Quantity and weight per instrument |
| `cash`, `equity` | series | local | The account lines |
| `probes` | series | local | Module outputs recorded as probes: numbers, mappings (one line per key) and switches |

## The default strategy

`core.baseline.HoldEverything` puts equal weight in every instrument the guarded view lists,
rebalancing on the first step of each month and holding in between. It is the yardstick for
every run, and it goes through the same engine on the same terms as the strategy run (dataset,
dates, capital, costs, decision time; see `baseline_settings`). So it pays the same costs, and
its states line up step for step with the strategy's. `Workspace.runs.prepare_baseline(record)`
runs it, and `Workspace.runs.baseline_for(record)` finds one already run on the same terms.

## The Run view

Run (the button or Ctrl+Enter) reads the code back, then goes through `Workspace.runs`:
prepare on the UI thread, execute on a worker (`desktop/tasks.run`), commit on the UI thread.
Pressing Run again cancels. Every module that is not the decide module is recorded as a probe.

- Tiles: profit, Sharpe, max drawdown, hit rate and exposure, against the default strategy.
- Chart (`design/chart.py`, `TimeChart`): a global curve, the default strategy dashed, trade dots, and a local
  measurement in a panel below or over the chart on its own scale.
- Knobs: turning one in the Knobs dock re-runs after 350 ms and redraws.
- The Trade log dock lists the trades of the last run of the strategy in front.
- The backtest block runs four quick tests on the last run and shows their verdicts (see
  [backtests.md](backtests.md)).
