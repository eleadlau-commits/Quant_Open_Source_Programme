# Random baseline test

Swaps the ranking (or direction) for random picks and checks the strategy beats them.

## What it adds

- evaluator plugin: `random_baseline`

## What it needs

The plugin folders `daily-features`. If one is missing or off, this one stays off and says why.

## Check it

```
pytest honestbt/plugins/builtin/random-baseline
```
