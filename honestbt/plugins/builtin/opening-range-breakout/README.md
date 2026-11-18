# Opening range breakout

Trade the first close outside the opening box with a stop, a target and an optional higher-timeframe trend filter.

## What it adds

- strategy plugin: `opening_range_breakout`

## What it needs

The plugin folders `intraday-features`, `exit-signals`. If one is missing or off, this one stays off and says why.

## Check it

```
pytest honestbt/plugins/builtin/opening-range-breakout
```
