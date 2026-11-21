"""Design tokens: the only place colours, type sizes, spacing and radii are defined.

Distilled from the Titanium prototype: warm neutral greys, ink black, the logo's
muted red as the brand accent, and blue for actions and selection.
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
RADIUS = {"sm": 4, "md": 6, "lg": 8, "xl": 12}
NAV_WIDTH = 76
CONTROL_HEIGHT = 30


# ---- colour -------------------------------------------------------------
@dataclass(frozen=True)
class Palette:
    name: str
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
    brand: str  # the logo's muted red
    brand_soft: str
    primary: str  # actions and selection
    primary_hover: str
    primary_soft: str
    on_primary: str
    success: str
    warning: str
    danger: str
    series: tuple[str, ...]  # chart lines, in order


LIGHT = Palette(
    name="light",
    window="#f3f3f1", surface="#ffffff", surface_alt="#f7f7f5", sunken="#f0f0ed", nav="#ebebe7",
    border="#e3e3de", border_strong="#c8c8c3",
    text="#1d1d1b", text_muted="#6b6b66", text_faint="#9a9a94",
    ink="#111418", ink_hover="#2a2f37", on_ink="#f6f6f3", brand="#b4635e", brand_soft="#f4e6e5",
    primary="#2f5bd3", primary_hover="#264cb5", primary_soft="#e6ecfb", on_primary="#ffffff",
    success="#1f8a4c", warning="#b7791f", danger="#c0392b",
    series=("#2f5bd3", "#b4635e", "#1f8a4c", "#b7791f", "#7b3fb0", "#2a8c9a"),
)

DARK = Palette(
    name="dark",
    window="#1b1b1a", surface="#232321", surface_alt="#2a2a28", sunken="#181817", nav="#151514",
    border="#30302d", border_strong="#45453f",
    text="#e8e8e3", text_muted="#a3a39c", text_faint="#6f6f69",
    ink="#f1f1ec", ink_hover="#d6d6d0", on_ink="#151514", brand="#d08a84", brand_soft="#3a2726",
    primary="#4a7cf0", primary_hover="#6690f5", primary_soft="#1f2a44", on_primary="#ffffff",
    success="#4cc27e", warning="#e0b062", danger="#ff6b5e",
    series=("#6690f5", "#d08a84", "#4cc27e", "#e0b062", "#b38cf0", "#5cc3d1"),
)


def palette(dark: bool) -> Palette:
    return DARK if dark else LIGHT
