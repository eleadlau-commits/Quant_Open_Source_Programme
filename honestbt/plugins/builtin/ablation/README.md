# Ablation test

Removes one ingredient (e.g. a trend filter) and checks the version with it earns clearly more.

## What it adds

- evaluator plugin: `ablation`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/ablation
```
