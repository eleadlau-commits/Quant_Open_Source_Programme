# Parameter stability test

Checks that most nearby parameter settings are profitable, not just one lucky point.

## What it adds

- evaluator plugin: `parameter_stability`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/parameter-stability
```
