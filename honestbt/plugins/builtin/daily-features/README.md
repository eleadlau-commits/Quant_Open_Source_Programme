# Daily features

Values built from completed daily bars: pre-market gap, last close, dollar volume, volatility, ATR, trailing return and a random score for baselines.

## What it adds

- feature plugins: `atr`, `atr_pct`, `avg_dollar_volume`, `last_close`, `premarket_gap`, `random`, `realized_vol`, `trailing_return`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/daily-features
```
