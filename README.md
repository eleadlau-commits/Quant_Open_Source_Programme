<img src="packaging/assets/titanium-512.png" alt="Titanium logo" width="96" align="right">

# Titanium

A desktop workbench for building, running and honestly judging trading strategies.

> This is the rebuild, from the framework upwards. The first prototype (the
> `honestbt` package and its app) is kept on the
> [`prototype-v0`](../../tree/prototype-v0) branch.

![Strategies page](docs/screenshots/strategy-tab-light.png)

## Pages

| Page | Manages |
| --- | --- |
| Data | Datasets: where they come from, what they hold, where they are stored, who uses them. Core, complementary and generated data. |
| Strategies | One tab per strategy, each with three views: Patch bay, Code and Run. |
| Compare | Runs side by side, one tab per measurement. |
| Backtests | Tests that ask whether a result holds up. |
| Settings (corner) | Appearance, layout, libraries and plugins. |

Every panel is a view that can be shown as a page or as a dock (Settings → Layout,
or right-click a page in the rail).

## Status

Phase 0, the foundation: the layers, the core interfaces, the design system and the
window shell with empty pages. Sections are built next, one at a time.

## Run it

```bash
pip install -e ".[dev]"      # Python 3.11+
titanium                     # or: python -m titanium.desktop
python -m titanium.desktop.design.gallery   # every UI component, light (add --dark)
pytest -q
```

## Layout

```
titanium/core/      no UI: markets, instruments, data, strategy model, engine,
                    measurements, backtests, plugins (interfaces for now)
titanium/app/       the shared objects every page works on
titanium/desktop/   the Qt shell: design system, views, pages and docks
tools/              screenshots of every page, light and dark
```

Not financial advice. Surviving tests is never evidence a strategy will make money.
