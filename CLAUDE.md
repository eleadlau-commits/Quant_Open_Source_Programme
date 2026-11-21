# Titanium: conventions

Titanium is being rebuilt from the framework upwards. The prototype lives on the
`prototype-v0` branch. The plan (pages, layers, engine, build order) is the
"Titanium rebuild: framework plan" doc; the owner (E) leads the design.

## Layers (each only uses the one below)

- `titanium/desktop/`: the Qt shell. Every panel is a `View` that can be hosted as a page
  or a dock; where it lives is layout (saved in settings), never code.
- `titanium/app/`: shared objects every page works on (`Workspace`). No Qt here.
- `titanium/core/`: no UI. Interfaces first; sections implement them. Interfaces only
  grow by additions.

Pages never import each other and never reach into the engine.

## Design system (mandatory for UI code)

- Looks come from skin packs: `desktop/design/packs/*.toml` (Graphite is the default,
  Classic is the original), loaded by `design/skins.py`. Type sizes, spacing and control
  sizes are in `design/tokens.py`. Read colours with `theme.current()`, radii with
  `theme.radius()`, effects with `theme.effects()`. No hex colours or `setStyleSheet`
  outside `desktop/design/` (a test enforces this). `theme.stylesheet` is the only
  place styling is generated.
- Follow `docs/design-language.md`: no blue fills, red means live, one signal-gradient
  edge per area, glow only on the Run button, mono numbers.
- Build UI from `desktop/design/components.py` (Card, StatTile, EmptyState, Segmented,
  RunButton, Canvas, button variants, badge, label roles). Need something new? Add it to the kit and the
  gallery first, then use it.
- Icons: `desktop/design/icons.py`, recoloured through `theme.watch` on theme change.
- One primary button per area. Sentence case. Plain words in labels and help.
- Every UI change: run `python tools/screenshots.py` (it shoots every skin) and attach
  light and dark images of the pages it changes to the PR. Changing a component? Check it
  under Classic too. Compare with the gallery
  (`python -m titanium.desktop.design.gallery`).

## Core rules carried over from the prototype

- Timestamps are timezone-aware, stored in UTC, shown in the market's local time.
- Strategy code only sees a guarded view pinned to the decision time (`core/guard.py`,
  get one with `workspace.datasets.view(ids, as_of)`). Minute bars are indexed by their
  start and visible once ended; daily bars come from regular-session minutes and are
  visible from their session close; series are indexed by the time each value became known.
- Calendars are rule-based (`core/calendars.py`), never inferred from data.
- Datasets live in `paths.app_folder() / "data"` as Parquet plus `catalogue.json`.
- One simulation engine. Measurements and backtests read run records; backtests may
  re-run the same engine with changed settings.
- Cash is real currency in the ledger (notional capital); results are shown normalised.
- Plugins add entries to libraries via a manifest; removing one never breaks others.
  The loader is `app/plugins.py` (`workspace.plugins`); built-ins live in
  `titanium/plugins/builtin`; plugin code imports only `titanium.sdk`. See `docs/plugins.md`.
- Run defaults (capital, costs, time frame) come from `workspace.run_defaults`; don't hard-code them.

## Working

- `pip install -e ".[dev]"`, then `pytest -q` (Qt tests run offscreen).
- One section per branch and PR. Keep PRs to one section.
