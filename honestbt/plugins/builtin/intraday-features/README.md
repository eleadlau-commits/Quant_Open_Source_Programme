# Intraday features

The opening box (high, low or height between two clock times) and a higher-timeframe EMA trend spread.

## What it adds

- feature plugins: `htf_ema_spread`, `opening_range`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/intraday-features
```
