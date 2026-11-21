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

- Colours, type sizes, spacing and radii come only from `desktop/design/tokens.py`.
  No hex colours or `setStyleSheet` outside `desktop/design/` (a test enforces this).
- Build UI from `desktop/design/components.py` (Card, StatTile, EmptyState, Segmented,
  button variants, badge, label roles). Need something new? Add it to the kit and the
  gallery first, then use it.
- Icons: `desktop/design/icons.py`, recoloured through `theme.watch` on theme change.
- One primary button per area. Sentence case. Plain words in labels and help.
- Every UI change: run `python tools/screenshots.py` and attach light and dark images
  of the pages it changes to the PR. Compare with the gallery
  (`python -m titanium.desktop.design.gallery`).

## Core rules carried over from the prototype

- Timestamps are timezone-aware, stored in UTC, shown in the market's local time.
- Strategy code only sees a guarded view pinned to the decision time.
- One simulation engine. Measurements and backtests read run records; backtests may
  re-run the same engine with changed settings.
- Cash is real currency in the ledger (notional capital); results are shown normalised.
- Plugins add entries to libraries via a manifest; removing one never breaks others.

## Working

- `pip install -e ".[dev]"`, then `pytest -q` (Qt tests run offscreen).
- One section per branch and PR. Keep PRs to one section.
