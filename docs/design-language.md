# Titanium design language

Agreed with E on 2026-11-21. The default look is **Graphite**. The original look is kept as the **Classic** skin.

## The idea

Titanium should feel like a cockpit for money: precise, calm and a little futuristic, without looking like a game.
The hand-inked logo and its muted red stay at the centre. Everything else is quiet graphite (dark) or brushed aluminium (light).

## Rules every skin follows

1. **No big blue blocks.** Blue (`primary`) marks focus and selection only. Graphite never uses it as a button fill.
2. **Red means live.** The logo's red (`brand`) is the signal colour. It marks the play mark, the active page, the selected strategy tab, a run in progress and the first chart series.
3. **The signal gradient** runs from red into amber (`brand` to `accent_2`) and fades into the border. It edges the one primary button in an area and the Run button. It never fills a large area.
4. **Panels are layered, not boxed.** In Graphite, panels shade slightly from `surface_top` to `surface` and catch a 1px light edge on top (`highlight`). Spacing does more work than borders.
5. **Numbers read like instruments.** Stat figures use the mono face (JetBrains Mono) with fixed-width digits. Overlines are small caps with wide tracking.
6. **Canvases have a backdrop.** The patch bay and charts sit on a fine dot grid (`Canvas`).
7. **Glow is rare.** Only the Run button glows, and it pulses only while a run is in progress. Large panels never glow.
8. **Words stay plain.** Sentence case, plain labels, one primary button per area (from the foundation conventions).

## The Run button

`RunButton` is a capsule with a red play mark, the label and the shortcut (`Ctrl ↵`) inside it, edged with the signal gradient.
`set_running(True, "61%")` changes the label to "Running", shows progress in place of the shortcut, turns the edge solid red and pulses the glow.
In Classic it is the original solid blue button.

## Skin packs

A skin is a TOML file. The built-in skins are in `titanium/desktop/design/packs/`, and `classic.toml` lists every key.
Users add skins in `Documents/Titanium/skins/` (or `$TITANIUM_HOME/skins`). Plugins add them through `Library.SKINS`, as a path, TOML data or a `Skin`.

```toml
id = "midnight"            # lower-case letters, digits, - or _
name = "Midnight"
description = "Graphite with a blue signal."
extends = "graphite"       # inherit everything left out
# optional extra Qt style sheet, with $token and $radius_md placeholders (top-level, before any [table])
qss = """
QLabel[role="overline"] { color: $brand; }
"""

[effects]                  # optional; see tokens.Effects
glow = 0.3

[dark]                     # any palette colour, as #rrggbb or #rrggbbaa
brand = "#6aa0ff"
accent_2 = "#9ad0ff"
```

The effects are:

- `panel_gradient` and `top_highlight`: layered panels.
- `glow`: 0 to 1, the Run button only.
- `canvas`: `none`, `dots` or `lines`.
- `nav_marker`: `tile` or `dot`.
- `primary`: `fill` or `edge`.
- `run`: `fill` or `capsule`.
- `numbers`: `ui` or `mono`.

A broken skin is skipped, its reason is shown in Settings, and the app uses the default skin.
A user skin can't replace a built-in id.
