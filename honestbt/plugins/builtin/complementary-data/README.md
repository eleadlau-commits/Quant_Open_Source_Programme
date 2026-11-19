# Complementary data

Series that sit next to the prices: news scores, events, income, C_j(t). Each value is indexed by
the time it became known, and strategies only see values known at decision time.

```json
"data": {"plugin": "synthetic", "params": {},
         "complementary": [{"plugin": "synthetic_events", "params": {"seed": 1}}]}
```

In a Python strategy: `F.series_last("earnings_surprise", symbol)`.

## What it adds

- complementary plugin: `csv_series` (your own CSV: time, value, optional symbol column)
- complementary plugin: `synthetic_events` (made-up quarterly earnings surprises, for testing)

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/complementary-data
```
