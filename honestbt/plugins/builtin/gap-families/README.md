# Gap strategy families

Ready-made families of weekly gap strategies (presets with sweeps), tested with the honest-stocks suite.

## What it adds

- presets (strategy families, shown in the preset list): `monday-gap-exit-family`, `monday-ranking-family`

## What it needs

The plugin folders `weekly-topn`, `synthetic-stocks`, `daily-features`, `basic-mappings`, `exit-signals`, `honest-tests`. If one is missing or off, this one stays off and says why.

## Check it

```
pytest honestbt/plugins/builtin/gap-families
```
