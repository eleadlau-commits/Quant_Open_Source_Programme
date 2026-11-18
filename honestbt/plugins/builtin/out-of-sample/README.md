# Out-of-sample test

Picks the best variant on early history and scores it on later history it never saw.

## What it adds

- evaluator plugin: `out_of_sample`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/out-of-sample
```
