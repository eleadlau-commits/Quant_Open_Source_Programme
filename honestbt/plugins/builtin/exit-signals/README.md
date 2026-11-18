# Exit signals

When to leave a trade early: never, an ATR trailing stop, an EMA cross, Heikin-Ashi reversal, a time stop, or any of several.

## What it adds

- signal plugins: `any_of`, `atr_trailing`, `ema_cross`, `heikin_ashi`, `never`, `time_stop`

## What it needs

Nothing beyond the core.

## Check it

```
pytest honestbt/plugins/builtin/exit-signals
```
