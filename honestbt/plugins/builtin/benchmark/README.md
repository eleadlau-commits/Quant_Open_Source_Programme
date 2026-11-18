# Benchmark test

Compares with buying the whole filtered universe for the same period.

## What it adds

- evaluator plugin: `benchmark`

## What it needs

The plugin folders `exit-signals`. If one is missing or off, this one stays off and says why.

## Check it

```
pytest honestbt/plugins/builtin/benchmark
```
