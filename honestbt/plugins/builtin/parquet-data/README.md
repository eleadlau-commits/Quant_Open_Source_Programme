# Parquet data

Reads real minute bars from a local Parquet cache, one file per symbol.

## What it adds

- data plugin: `parquet`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/parquet-data
```
