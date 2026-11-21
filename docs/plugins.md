# Plugins

A plugin is a folder that adds entries to the app's libraries: data sources, generated
data, modules, skins, measurements, backtests (and later brokers, views). Removing one
never breaks the others.

## Where they come from

- `titanium/plugins/builtin/`: the ones that ship with the app. `synthetic-data`,
  `market-downloads`, `realised-volatility`, `starter-modules` and `honest-tests` (the
  backtests, see `docs/backtests.md`). Each can be switched off.
  File import and the Graphite and Classic skins are part of the app, not plugins.
- `Documents/Titanium/plugins/` (or `$TITANIUM_HOME/plugins`): yours, and the ones you
  import as `.tiplug` packs. On/off is remembered in `plugins.json` there.

Settings > Plugins lists every plugin, on or off and why, with a switch and Import pack….

## A plugin folder

```
my-source/
  plugin.json   what it is, what it adds, what it needs
  plugin.py     defines setup(plugin); imports only titanium.sdk (optional)
  skins/        optional: skin .toml files
  tests/        its own tests, run by `check`, not when the app loads it
  README.md
```

```json
{"id": "my-source", "name": "My source", "version": "1.0.0", "api": 1,
 "description": "One sentence a person reads in Plugins.", "author": "E",
 "main": "plugin.py",
 "provides": {"data_sources": ["my_source"]},
 "requires": []}
```

```python
from titanium.sdk import Library, Source

class MySource(Source):
    name = "my_source"
    ...

def setup(plugin):
    plugin.add(Library.DATA_SOURCES, MySource.name, MySource())
    # plugin.add_module("my folder", ModuleTemplate(...)); plugin.add_skin("skins/neon.toml")
```

## The rules the loader enforces

- A plugin whose `requires` are missing or off stays off, with the reason.
- A plugin whose code fails, or adds something other than its `provides`, is switched
  off and everything it added is taken out again.
- Plugin code may import only `titanium.sdk`, numpy, pandas, a short list of the
  standard library and its own sibling files. This is checked with `ast` before the code runs.
- It's hygiene, not a sandbox: only add plugins from people you trust.

## The command line

```
python -m titanium.plugins new my-source --adds data_sources   # modules, generators, backtests, skins
python -m titanium.plugins check my-source
python -m titanium.plugins pack my-source
python -m titanium.plugins install my-source-0.1.0.tiplug
python -m titanium.plugins list
python -m titanium.plugins remove my-source
```

## The module library folder

Settings > Module library sets a folder (default `Documents/Titanium/library`). Each
sub-folder is a library folder and each `.py` file in it is one module: a function, with
`@module(kind="decide", outputs=[...], name="...")` above it if it isn't a plain transform.

## Defaults for every run

A run's settings resolve in four layers, each overriding the one before
(`core/layers.py`):

1. **App defaults** (Settings > Defaults for every run, `workspace.run_defaults`): capital,
   how often the strategy decides (`every`), the exposure cap (`max_gross`) and the smallest
   trade (`min_trade`).
2. **Market defaults** (`Market.defaults` in `core/markets.py`, edited by the app with
   `workspace.set_market_defaults`): whether to trade outside the regular session
   (`extended_hours`: Nasdaq off, CME on), the decision time (`decide_at`) and costs (stock
   half spread, slippage and commission; futures commission and slippage). The market is
   the traded dataset's.
3. **Strategy settings**, saved with the strategy.
4. **Run settings**: what a backtest changes.

`workspace.runs` does this; `workspace.run_settings(strategy, run, dataset_id=...)` shows the
result, and `layer_of` says which layer a value came from. A plugin can add a market to
`Library.MARKETS`; `workspace.markets()` lists them all.
