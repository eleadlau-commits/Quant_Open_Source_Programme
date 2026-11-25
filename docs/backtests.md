# Backtests and Compare

Honest evaluation is what Titanium is for. A backtest asks whether a result holds up; a pass
means only that it survived that test, never that the strategy will make money.

## The library

Tests are `Library.BACKTESTS` entries. The ones the app ships with are the built-in plugin
`honest-tests` (`titanium/plugins/builtin/honest-tests`). A test is an object with:

```python
from titanium.sdk import BacktestInfo, Param, Verdict

class MyTest:
    order = 90                       # where it sits in the list
    info = BacktestInfo("my_test", "My test", "One or two sentences: what it checks.",
                        [Param("n", "int", 20, "Versions", minimum=5)], "runs n variants")

    def evaluate(self, ctx, n=20):
        rec = ctx.run                           # the RunRecord being judged
        other = ctx.rerun(settings={"costs": {"stress": 2}})   # same engine, changed settings
        tuned = ctx.rerun(knobs={"m1.days": 30})                # changed knobs
        base = ctx.baseline()                                   # the default strategy, same terms
        return Verdict("My test", True, "The headline, in plain words",
                       "Why it matters.", {"figures": [("Label", "+1.2%")]})
```

`ctx` (`core.backtests.BacktestContext`) also has `variants(spread)` (the run plus each number
knob moved down and up, run once and shared by every test on the run), `trials()` (versions of the
strategy run this session), `history`, `graph`, `strategy`, `progress(fraction)` and `cancelled()`.
Helpers in `titanium.sdk`: `step_returns`, `steps_per_year`, `sharpe`, `t_stat`, `aligned_returns`,
`split_time`, `total_growth`, `knob_variants`, `ingredients`, `without`, `RandomPicks`.

Reruns go through the one simulator. Because it is causal, a variant's returns before a date are
what a run stopped there would give, so out-of-sample and walk-forward slice one run per variant.

| Test | What it does | Extra runs |
| --- | --- | --- |
| Out-of-sample | Chooses the knobs on the early part, scores the later part | up to 9 variants |
| Walk-forward | Re-chooses the knobs before each stretch, scores only what follows | the same variants |
| Bootstrap | Block-resamples the step returns; the lower bound must stay above zero | none |
| Deflated Sharpe | Discounts the Sharpe ratio for versions tried this session and for fat tails | none |
| Cost stress | Runs with costs off and multiplied; must still make money | 2 |
| Random baseline | Same timing, weights and holding periods, random names (one instrument: coin-flip direction) | n |
| Benchmark | Step by step against the default strategy, same costs | 1 |
| Parameter stability | Share of nearby knob settings that make money | the same variants |
| Ablation | Takes out a filter module or switch knob; does it earn clearly more with it? | 1 |

## The service: `workspace.backtests`

```python
job = workspace.backtests.prepare(run_id, "cost_stress", params=None)  # UI thread; params: the strategy's
tasks.run(job.execute, workspace.backtests.commit, on_error)           # worker, then UI thread
workspace.backtests.cancel(job.id)
workspace.backtests.run(run_id, "bootstrap")         # both at once (tests, scripts)
workspace.backtests.results(run_id)                  # {test_id: BacktestResult}, the latest of each
workspace.backtests.tests()                          # [BacktestInfo], in list order
workspace.backtests.used(graph) / set_used(id, {test_id: params})   # settings["backtests"]
```

A test that raises is a result (`status == "failed"`, could not judge, with the error), never a
crash. Reruns are not added to `workspace.runs`; the default strategy's run is, so Compare shows it.

In the desktop app, `desktop/backtest_queue.BacktestQueue` runs tests one after another off the UI
thread and announces each result as it arrives. The Backtests page and the Run view's backtest
block both use it.

## The pages

- **Backtests**: pick a strategy and one of its runs (the latest by default). The list has every
  test; the Uses switch says which ones Run all runs, and the panel beside it holds the selected
  test's settings. Both are saved in the strategy. Verdicts arrive one by one, grouped into Failed,
  Passed and Could not judge; folding a verdict is remembered. If the strategy changed since the
  run, the page says so.
- **Compare**: tick strategies (their latest run) or earlier runs. One tab per curve in the
  measurement library (profit, drawdown, exposure). The default strategy is drawn dashed. Profit and
  drawdown are measured from the start of the visible window, and the table reads that window.
- **Run view**: the backtest block runs out-of-sample, cost stress, random baseline and walk-forward
  on the last run and shows their verdicts; All tests opens the Backtests page.

Writing tests and measurements inside the app comes later; the library dialogs on both pages are
where those editors will open.

## Where backtests run

In the desktop app every backtest runs in one worker process (`app/backtest_worker.py`,
`Workspace.backtest_worker()`), started a moment after the app opens and kept for the
session. Python runs one thread's Python code at a time, so a backtest on a thread took
turns with the window's drawing; in its own process it doesn't, and the window stays
smooth while a long test runs. While tests run, only the backtest section freezes
(`BusyOverlay(section, live=True)`).

- The worker opens datasets from the data folder itself and keeps them open (closed after
  10 idle minutes); each job sends only the run, the strategy's earlier runs, the default
  strategy's run if there is one, the dataset infos and which plugins are off
  (`BacktestService.payload`). It runs the same `BacktestService` and simulator; the result
  and any default-strategy run it made come back and are committed on the UI thread.
- Cancel sets a flag the simulator checks every step. A worker that hasn't stopped 5 s
  after Cancel, or that dies, is ended: the test shows as stopped or failed, and the next
  test starts a fresh worker.
- If the worker can't be started (some machines don't let an app start a copy of itself),
  tests run on a thread as before. `BacktestQueue.use_worker = False` does the same.
- Frozen builds call `multiprocessing.freeze_support()` first thing
  (`packaging/titanium_main.py`); the build's `--self-test` runs one backtest through the
  worker. A windowed exe's worker writes errors to `titanium-worker.log` beside the app's log.
