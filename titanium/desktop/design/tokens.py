"""Design tokens: type sizes, spacing and control sizes shared by every skin, and the
shapes of a skin (Palette, Effects, Skin).

Colours, radii, fonts and effects come from skin packs (``design/packs/*.toml``,
loaded by :mod:`skins`). UI code never names a colour: it asks ``theme.current()``.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---- type ---------------------------------------------------------------
FONT_FAMILIES = ["Inter", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["JetBrains Mono", "Cascadia Code", "SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono"]


@dataclass(frozen=True)
class Type:
    caption: int = 11
    body: int = 13
    label: int = 12
    title: int = 15
    heading: int = 20
    display: int = 26


TYPE = Type()

# ---- space and shape ----------------------------------------------------
SPACE = {"xxs": 2, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 4, "md": 6, "lg": 8, "xl": 12}  # the Classic skin's radii; use theme.radius() in UI code
NAV_WIDTH = 76
CONTROL_HEIGHT = 30


# ---- colour -------------------------------------------------------------
# The values live in skin packs (design/packs/*.toml); see skins.py.
@dataclass(frozen=True)
class Palette:
    name: str  # "light" or "dark"
    window: str  # the app background
    surface: str  # cards, panels, editors
    surface_alt: str  # hovered rows, inset areas
    sunken: str  # inputs, code
    nav: str  # the navigation rail
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    ink: str  # the logo's black (white in dark mode)
    ink_hover: str
    on_ink: str
    brand: str  # the logo's muted red: the "live" signal
    brand_soft: str
    primary: str  # focus and selection (a fill only in skins whose effects say so)
    primary_hover: str
    primary_soft: str
    on_primary: str
    success: str
    warning: str
    danger: str
    series: tuple[str, ...]  # chart lines, in order
    surface_top: str  # top of a panel's gradient (same as surface when flat)
    highlight: str  # the 1px light catch on a panel's top edge
    glow: str  # colour of the glow around the Run button
    accent_2: str  # second stop of the signal gradient (red into amber)


@dataclass(frozen=True)
class Effects:
    """How a skin dresses the same components. Every field has a plain default."""

    panel_gradient: bool = False  # panels shade from surface_top to surface
    top_highlight: bool = False  # panels catch a light edge on top
    glow: float = 0.0  # 0 to 1: glow around the Run button (QGraphicsDropShadowEffect, Run only)
    canvas: str = "none"  # backdrop for canvases: none, dots, lines
    nav_marker: str = "tile"  # active page in the rail: tile, dot
    primary: str = "fill"  # primary buttons: fill (solid primary) or edge (raised, signal-gradient border)
    run: str = "fill"  # the Run button: fill (like primary) or capsule (pill with a signal border)
    numbers: str = "ui"  # stat figures: ui or mono


@dataclass(frozen=True)
class Skin:
    """A skin pack: light and dark palettes plus shape, fonts and effects."""

    id: str
    name: str
    description: str
    light: Palette
    dark: Palette
    radius: dict
    ui_fonts: tuple[str, ...]
    mono_fonts: tuple[str, ...]
    effects: Effects
    qss: str = ""  # optional extra style sheet; $token placeholders take palette and radius values
    source: str = ""  # where it was loaded from ("" = built in)

    def palette(self, dark: bool) -> Palette:
        return self.dark if dark else self.light
