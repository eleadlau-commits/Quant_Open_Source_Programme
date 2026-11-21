# Honest tests

The backtests Titanium ships with. Each one reads a run and may run the same simulator again
with changed costs, knobs or a stand-in strategy. A pass means only that the result survived
that test, never that the strategy will make money.

| Test | What it does | Extra runs |
| --- | --- | --- |
| Out-of-sample | Chooses the knobs on the early part, scores the later part | up to 9 variants |
| Walk-forward | Re-chooses the knobs before each of several stretches | the same variants |
| Bootstrap | Reshuffles the run's step returns in blocks | none |
| Deflated Sharpe | Discounts the Sharpe ratio for versions tried this session and fat tails | none |
| Cost stress | Runs again with costs off and with costs multiplied | 2 |
| Random baseline | Same timing, weights and holding periods, random names (or coin-flip directions) | n |
| Benchmark | Step by step against the default strategy on the same costs | 1 (the default strategy) |
| Parameter stability | Moves each number knob a little either way | the same variants |
| Ablation | Takes out one switch knob or filter module | 1 |

The variants are the run plus each number knob (with a range) moved down and up by a share of
its range, one at a time. Because the simulator is causal, a variant's returns before a date are
what a run stopped there would give, so out-of-sample and walk-forward run each variant once.
