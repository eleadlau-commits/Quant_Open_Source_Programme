"""Light and dark mode. "System" follows the operating system and switches when it does."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

MODES = ("system", "light", "dark")
LABELS = {"system": "Same as the system", "light": "Light", "dark": "Dark"}

_DARK = {
    QPalette.Window: "#1f1f1d", QPalette.WindowText: "#e6e6e1", QPalette.Base: "#161615",
    QPalette.AlternateBase: "#2a2a27", QPalette.ToolTipBase: "#2a2a27", QPalette.ToolTipText: "#e6e6e1",
    QPalette.PlaceholderText: "#8a8a84", QPalette.Text: "#e6e6e1", QPalette.Button: "#2b2b28",
    QPalette.ButtonText: "#e6e6e1", QPalette.BrightText: "#ff6b5e", QPalette.Light: "#3a3a36",
    QPalette.Midlight: "#33332f", QPalette.Mid: "#2a2a27", QPalette.Dark: "#121211", QPalette.Shadow: "#000000",
    QPalette.Highlight: "#3b6fe0", QPalette.HighlightedText: "#ffffff", QPalette.Link: "#7aa2ff",
    QPalette.LinkVisited: "#b38cf0",
}
_LIGHT = {
    QPalette.Window: "#f3f3f1", QPalette.WindowText: "#1d1d1b", QPalette.Base: "#ffffff",
    QPalette.AlternateBase: "#f2f2ef", QPalette.ToolTipBase: "#ffffdc", QPalette.ToolTipText: "#1d1d1b",
    QPalette.PlaceholderText: "#8a8a84", QPalette.Text: "#1d1d1b", QPalette.Button: "#fafaf8",
    QPalette.ButtonText: "#1d1d1b", QPalette.BrightText: "#c0392b", QPalette.Light: "#ffffff",
    QPalette.Midlight: "#e6e6e2", QPalette.Mid: "#c8c8c3", QPalette.Dark: "#9a9a94", QPalette.Shadow: "#5a5a55",
    QPalette.Highlight: "#2f5bd3", QPalette.HighlightedText: "#ffffff", QPalette.Link: "#2f5bd3",
    QPalette.LinkVisited: "#7b3fb0",
}


def system_is_dark() -> bool:
    app = QGuiApplication.instance()
    try:
        return app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt older than 6.5
        return False


def is_dark(mode: str) -> bool:
    return mode == "dark" or (mode == "system" and system_is_dark())


def palette(dark: bool) -> QPalette:
    pal = QPalette()
    for role, color in (_DARK if dark else _LIGHT).items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):  # greyed-out widgets
        pal.setColor(QPalette.Disabled, role, QColor("#6b6b66" if dark else "#a5a5a0"))
    return pal


def apply(app, mode: str) -> bool:
    """Use the Fusion style (the same on every platform) with a light or dark palette. Returns True if dark."""
    dark = is_dark(mode)
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(palette(dark))
    return dark


def code_colors(dark: bool) -> dict[str, str]:
    """Syntax colours for the Python editor."""
    if dark:
        return {"keyword": "#c79bf2", "knob": "#f08a80", "def": "#7aa2ff", "number": "#e0b062",
                "string": "#7fd19b", "comment": "#8a8a84"}
    return {"keyword": "#7b3fb0", "knob": "#b4635e", "def": "#2f5bd3", "number": "#c0841a",
            "string": "#1f8a4c", "comment": "#8a8a84"}
