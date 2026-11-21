"""Applies the tokens to Qt: Fusion style, a QPalette and one generated stylesheet.

Components pick their look with Qt properties (``variant``, ``role``), never with
inline style sheets, so the whole app restyles from :mod:`tokens` alone.
"""
from __future__ import annotations

import weakref
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

from . import icons
from . import tokens as T

MODES = ("system", "light", "dark")
LABELS = {"system": "Same as the system", "light": "Light", "dark": "Dark"}

_current: T.Palette = T.LIGHT
_watchers: list[tuple[weakref.ref, Callable]] = []


def watch(widget, fn: Callable) -> None:
    """Call ``fn(widget)`` whenever the theme changes (for icons and custom painting)."""
    _watchers.append((weakref.ref(widget), fn))


def current() -> T.Palette:
    """The palette in use (custom-painted widgets read their colours from here)."""
    return _current


def system_is_dark() -> bool:
    app = QGuiApplication.instance()
    try:
        return app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt older than 6.5
        return False


def is_dark(mode: str) -> bool:
    return mode == "dark" or (mode == "system" and system_is_dark())


def _family(candidates: list[str]) -> str:
    have = set(QFontDatabase.families())
    return next((f for f in candidates if f in have), candidates[-1])


def ui_font(size: int = T.TYPE.body, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(_family(T.FONT_FAMILIES))
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def mono_font(size: int = T.TYPE.body) -> QFont:
    f = QFont(_family(T.MONO_FAMILIES))
    f.setPixelSize(size)
    f.setStyleHint(QFont.Monospace)
    return f


def qpalette(p: T.Palette) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.Window: p.window, QPalette.WindowText: p.text, QPalette.Base: p.surface,
        QPalette.AlternateBase: p.surface_alt, QPalette.ToolTipBase: p.surface, QPalette.ToolTipText: p.text,
        QPalette.PlaceholderText: p.text_faint, QPalette.Text: p.text, QPalette.Button: p.surface,
        QPalette.ButtonText: p.text, QPalette.BrightText: p.danger, QPalette.Light: p.surface,
        QPalette.Midlight: p.border, QPalette.Mid: p.border_strong, QPalette.Dark: p.border_strong,
        QPalette.Shadow: "#000000", QPalette.Highlight: p.primary, QPalette.HighlightedText: p.on_primary,
        QPalette.Link: p.primary, QPalette.LinkVisited: p.primary,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(p.text_faint))
    return pal


def stylesheet(p: T.Palette) -> str:
    r, s, ty = T.RADIUS, T.SPACE, T.TYPE
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p.text}; font-size: {ty.body}px; }}
QMainWindow, QDialog {{ background: {p.window}; }}
QToolTip {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
            border-radius: {r['md']}px; padding: {s['xs']}px {s['sm']}px; }}

/* ---- navigation rail ---- */
#NavRail {{ background: {p.nav}; border-right: 1px solid {p.border}; }}
#NavRail QToolButton {{ border: none; border-radius: {r['lg']}px; padding: {s['sm']}px 0;
            color: {p.text_muted}; font-size: {ty.caption}px; font-weight: 500; }}
#NavRail QToolButton:hover {{ background: {p.surface_alt}; color: {p.text}; }}
#NavRail QToolButton:checked {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; }}

/* ---- page header ---- */
#PageHeader {{ background: {p.window}; border-bottom: 1px solid {p.border}; }}
QLabel[role="display"] {{ font-size: {ty.display}px; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: {ty.heading}px; font-weight: 600; }}
QLabel[role="title"] {{ font-size: {ty.title}px; font-weight: 600; }}
QLabel[role="label"] {{ font-size: {ty.label}px; font-weight: 600; color: {p.text_muted}; }}
QLabel[role="muted"] {{ color: {p.text_muted}; }}
QLabel[role="caption"] {{ font-size: {ty.caption}px; color: {p.text_muted}; }}
QLabel[role="overline"] {{ font-size: {ty.caption}px; font-weight: 600; color: {p.text_faint};
            letter-spacing: 0.6px; }}
QLabel[role="stat"] {{ font-size: {ty.heading}px; font-weight: 600; }}

/* ---- cards ---- */
QFrame[card="true"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {r['lg']}px; }}
QFrame[card="true"][accent="brand"] {{ border-left: 3px solid {p.brand}; }}
QFrame[card="true"][accent="success"] {{ border-left: 3px solid {p.success}; }}
QFrame[card="true"][accent="danger"] {{ border-left: 3px solid {p.danger}; }}
QFrame[divider="true"] {{ background: {p.border}; border: none; max-height: 1px; min-height: 1px; }}
QFrame[empty="true"] {{ background: transparent; border: 1px dashed {p.border_strong}; border-radius: {r['xl']}px; }}

/* ---- buttons ---- */
QPushButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
            border-radius: {r['md']}px; padding: 0 {s['md']}px; min-height: {T.CONTROL_HEIGHT - 2}px; font-weight: 500; }}
QPushButton:hover {{ background: {p.surface_alt}; }}
QPushButton:pressed {{ background: {p.sunken}; }}
QPushButton:disabled {{ color: {p.text_faint}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{ background: {p.primary}; color: {p.on_primary}; border: 1px solid {p.primary}; }}
QPushButton[variant="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.border}; border-color: {p.border}; color: {p.text_faint}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {p.text_muted}; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_alt}; color: {p.text}; }}
QPushButton[variant="danger"] {{ color: {p.danger}; }}
QToolButton {{ border: 1px solid transparent; border-radius: {r['md']}px; padding: {s['xs']}px; }}
QToolButton:hover {{ background: {p.surface_alt}; }}
QToolButton:checked {{ background: {p.primary_soft}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---- segmented control ---- */
#Segmented {{ background: {p.sunken}; border: 1px solid {p.border}; border-radius: {r['lg']}px; }}
#Segmented QPushButton {{ background: transparent; border: none; border-radius: {r['md']}px;
            color: {p.text_muted}; min-height: {T.CONTROL_HEIGHT - 6}px; padding: 0 {s['lg']}px; }}
#Segmented QPushButton:hover {{ color: {p.text}; }}
#Segmented QPushButton:checked {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; }}

/* ---- badges ---- */
QLabel[badge="neutral"] {{ background: {p.sunken}; color: {p.text_muted}; border-radius: {r['sm']}px;
            padding: 1px {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="primary"] {{ background: {p.primary_soft}; color: {p.primary}; border-radius: {r['sm']}px;
            padding: 1px {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="brand"] {{ background: {p.brand_soft}; color: {p.brand}; border-radius: {r['sm']}px;
            padding: 1px {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="success"] {{ color: {p.success}; border: 1px solid {p.success}; border-radius: {r['sm']}px;
            padding: 0 {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="danger"] {{ color: {p.danger}; border: 1px solid {p.danger}; border-radius: {r['sm']}px;
            padding: 0 {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}

/* ---- inputs ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{ background: {p.surface}; border: 1px solid {p.border_strong};
            border-radius: {r['md']}px; padding: 0 {s['sm']}px; min-height: {T.CONTROL_HEIGHT - 2}px;
            selection-background-color: {p.primary}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{ border: 1px solid {p.primary}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({icons.file("chevron", p.text_muted)}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border_strong};
            selection-background-color: {p.primary_soft}; selection-color: {p.text}; }}
QPlainTextEdit, QTextEdit {{ background: {p.sunken}; border: 1px solid {p.border}; border-radius: {r['md']}px;
            selection-background-color: {p.primary}; }}
QCheckBox {{ spacing: {s['sm']}px; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.primary}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.surface}; border: 1px solid {p.border_strong}; width: 14px;
            margin: -6px 0; border-radius: 7px; }}

/* ---- tables and lists ---- */
QTableView, QTreeView, QListView {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {r['lg']}px;
            gridline-color: {p.border}; selection-background-color: {p.primary_soft}; selection-color: {p.text};
            alternate-background-color: {p.surface_alt}; }}
QTableView::item, QTreeView::item, QListView::item {{ padding: {s['xs']}px {s['sm']}px; border: none; }}
QHeaderView::section {{ background: {p.surface}; color: {p.text_muted}; border: none;
            border-bottom: 1px solid {p.border}; padding: {s['sm']}px; font-size: {ty.label}px; font-weight: 600; }}

/* ---- tabs (strategy tabs) ---- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p.text_muted}; border: none; border-bottom: 2px solid transparent;
            padding: {s['sm']}px {s['md']}px; margin-right: {s['xs']}px; font-weight: 500; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.brand}; }}

/* ---- docks ---- */
QDockWidget {{ titlebar-close-icon: none; color: {p.text_muted}; font-size: {ty.label}px; font-weight: 600; }}
QDockWidget::title {{ background: {p.window}; padding: {s['sm']}px {s['md']}px; border-bottom: 1px solid {p.border}; }}
QMainWindow::separator {{ background: {p.border}; width: 1px; height: 1px; }}

/* ---- scroll bars ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {p.border_strong}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {p.text_faint}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; height: 0; width: 0; }}

/* ---- menus and status bar ---- */
QMenu {{ background: {p.surface}; border: 1px solid {p.border_strong}; border-radius: {r['lg']}px; padding: {s['xs']}px; }}
QMenu::item {{ padding: {s['xs'] + 2}px {s['lg']}px; border-radius: {r['sm']}px; }}
QMenu::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: {s['xs']}px {s['sm']}px; }}
QStatusBar {{ background: {p.window}; color: {p.text_muted}; border-top: 1px solid {p.border}; font-size: {ty.caption}px; }}
QStatusBar::item {{ border: none; }}
"""


def apply(app, mode: str = "system") -> bool:
    """Style the whole app from the tokens. Returns True if dark."""
    global _current
    dark = is_dark(mode)
    _current = T.palette(dark)
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setFont(ui_font())
    app.setPalette(qpalette(_current))
    app.setStyleSheet(stylesheet(_current))
    alive = []
    for ref, fn in _watchers:
        w = ref()
        if w is None:
            continue
        try:
            fn(w)
        except RuntimeError:  # the Qt object behind it is gone
            continue
        alive.append((ref, fn))
    _watchers[:] = alive
    return dark
