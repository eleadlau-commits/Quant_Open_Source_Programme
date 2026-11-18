# Weekly top N

Each week buy the top N names ranked by a feature at the open and hold until an exit signal or the week's close.

## What it adds

- strategy plugin: `weekly_topn`

## What it needs

The plugin folders `exit-signals`. If one is missing or off, this one stays off and says why.

## Check it

```
pytest honestbt/plugins/builtin/weekly-topn
```
