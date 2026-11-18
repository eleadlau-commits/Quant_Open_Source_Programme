# Bootstrap test

Resamples the strategy's own returns in blocks; passes if the lower bound of the mean is above zero.

## What it adds

- evaluator plugin: `bootstrap`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/bootstrap
```
