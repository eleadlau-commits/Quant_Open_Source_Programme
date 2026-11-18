# Cost stress test

Re-runs with trading costs multiplied; passes if still profitable.

## What it adds

- evaluator plugin: `cost_stress`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/cost-stress
```
