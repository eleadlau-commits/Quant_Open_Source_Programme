# Synthetic data

Random-walk stock and futures minute bars, for trying strategies and testing the testers.

## What it adds

- data_sources: `synthetic_stocks`, `synthetic_futures`

## What it needs

Nothing beyond the core. Switch it off in Settings > Plugins; the rest of the app carries on.

## Check it

```
python -m titanium.plugins check titanium/plugins/builtin/synthetic-data
```
