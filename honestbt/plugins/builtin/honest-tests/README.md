# Honest test suites

Named sets of evaluators to use in one line: "evaluators": [{"$suite": "honest-stocks"}].

## What it adds

- test suites: `{"$suite": "honest-futures"}`, `{"$suite": "honest-stocks"}`, `{"$suite": "quick"}`

## What it needs

The plugin folders `out-of-sample`, `bootstrap`, `deflated-sharpe`, `cost-stress`, `random-baseline`, `benchmark`, `parameter-stability`, `ablation`. If one is missing or off, this one stays off and says why.

## Check it

```
pytest honestbt/plugins/builtin/honest-tests
```
