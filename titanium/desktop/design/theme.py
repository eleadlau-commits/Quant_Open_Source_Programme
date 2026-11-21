"""Applies a skin to Qt: Fusion style, a QPalette and one generated stylesheet.

Components pick their look with Qt properties (``variant``, ``role``), never with
inline style sheets, so the whole app restyles from the current skin alone.
A skin (see :mod:`skins`) holds the colours, radii, fonts and effects; this module
is still the only place styling is generated.
"""
from __future__ import annotations

import weakref
from string import Template
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette

from . import icons, skins
from . import tokens as T

MODES = ("system", "light", "dark")
LABELS = {"system": "Same as the system", "light": "Light", "dark": "Dark"}

_skin: T.Skin | None = None
_mode: str = "system"
_current: T.Palette | None = None
_watchers: list[tuple[weakref.ref, Callable]] = []


def watch(widget, fn: Callable) -> None:
    """Call ``fn(widget)`` whenever the theme or skin changes (for icons and custom painting)."""
    _watchers.append((weakref.ref(widget), fn))


def skin() -> T.Skin:
    """The skin in use."""
    global _skin
    if _skin is None:
        _skin = skins.get(skins.DEFAULT)
    return _skin


def current() -> T.Palette:
    """The palette in use (custom-painted widgets read their colours from here)."""
    return _current or skin().light


def radius(size: str = "md") -> int:
    return skin().radius[size]


def effects() -> T.Effects:
    return skin().effects


def system_is_dark() -> bool:
    app = QGuiApplication.instance()
    try:
        return app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt older than 6.5
        return False


def is_dark(mode: str) -> bool:
    return mode == "dark" or (mode == "system" and system_is_dark())


def qcolor(c: str, alpha: float | None = None) -> QColor:
    """A token colour (#rrggbb or #rrggbbaa) as a QColor, optionally with an alpha from 0 to 1."""
    col = QColor(c[:7])
    if len(c) == 9:
        col.setAlpha(int(c[7:9], 16))
    if alpha is not None:
        col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


def css(c: str) -> str:
    """A token colour for a style sheet (#rrggbbaa becomes rgba())."""
    if len(c) == 9:
        r, g, b, a = (int(c[i:i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r}, {g}, {b}, {a})"
    return c


def _family(candidates) -> str:
    have = set(QFontDatabase.families())
    return next((f for f in candidates if f in have), candidates[-1])


def ui_font(size: int = T.TYPE.body, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(_family(skin().ui_fonts))
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def mono_font(size: int = T.TYPE.body) -> QFont:
    f = QFont(_family(skin().mono_fonts))
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
        pal.setColor(role, qcolor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, qcolor(p.text_faint))
    return pal


def _vgrad(top: str, bottom: str) -> str:
    return f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {css(top)}, stop:1 {css(bottom)})"


def _signal(p: T.Palette) -> str:
    """The signal gradient (red into amber, fading into the border) used on edges."""
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {css(p.brand)}, stop:0.55 {css(p.accent_2)}, "
            f"stop:1 {css(p.border_strong)})")


def stylesheet(p: T.Palette, sk: T.Skin | None = None) -> str:
    sk = sk or skin()
    fx, r, s, ty = sk.effects, sk.radius, T.SPACE, T.TYPE
    c = {k: css(v) for k, v in vars(p).items() if isinstance(v, str)}
    panel = _vgrad(p.surface_top, p.surface) if fx.panel_gradient else c["surface"]
    edge = f"border-top: 1px solid {c['highlight']};" if fx.top_highlight else ""
    stat_family = f'font-family: "{_family(sk.mono_fonts)}"; font-weight: 500;' if fx.numbers == "mono" else "font-weight: 600;"
    pill = T.CONTROL_HEIGHT // 2

    if fx.primary == "edge":
        primary = f"""
QPushButton[variant="primary"] {{ background: {panel}; color: {c['text']}; border: 1px solid {_signal(p)}; {edge} font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {c['surface_top']}; border: 1px solid {c['brand']}; }}
QPushButton[variant="primary"]:pressed {{ background: {c['sunken']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['surface']}; border: 1px solid {c['border']}; color: {c['text_faint']}; }}"""
    else:
        primary = f"""
QPushButton[variant="primary"] {{ background: {c['primary']}; color: {c['on_primary']}; border: 1px solid {c['primary']}; }}
QPushButton[variant="primary"]:hover {{ background: {c['primary_hover']}; border-color: {c['primary_hover']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['text_faint']}; }}"""

    if fx.run == "capsule":
        run = f"""
QPushButton[variant="run"] {{ background: {panel}; border: 1px solid {_signal(p)}; {edge}
            border-radius: {pill}px; padding: 0 {s['md']}px 0 {s['md'] - 2}px; }}
QPushButton[variant="run"]:hover {{ background: {c['surface_top']}; border: 1px solid {c['brand']}; }}
QPushButton[variant="run"]:pressed {{ background: {c['sunken']}; }}
QPushButton[variant="run"][running="true"] {{ border: 1px solid {c['brand']}; }}
QPushButton[variant="run"] QLabel[role="runtext"] {{ color: {c['text']}; font-weight: 600; background: transparent; }}
QPushButton[variant="run"] QLabel[role="runhint"] {{ color: {c['text_faint']}; font-size: {ty.caption - 1}px; background: transparent; }}"""
    else:
        run = f"""
QPushButton[variant="run"] {{ background: {c['primary']}; border: 1px solid {c['primary']}; border-radius: {r['md']}px;
            padding: 0 {s['md']}px 0 {s['md'] - 2}px; }}
QPushButton[variant="run"]:hover {{ background: {c['primary_hover']}; border-color: {c['primary_hover']}; }}
QPushButton[variant="run"][running="true"] {{ background: {c['primary_hover']}; }}
QPushButton[variant="run"] QLabel[role="runtext"] {{ color: {c['on_primary']}; font-weight: 600; background: transparent; }}
QPushButton[variant="run"] QLabel[role="runhint"] {{ color: {c['primary_soft']}; font-size: {ty.caption - 1}px; background: transparent; }}"""

    nav_checked = (f"background: {panel}; color: {c['text']}; border: 1px solid {c['border']}; {edge}"
                   if fx.nav_marker == "dot" else
                   f"background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};")
    seg_checked = f"background: {panel}; color: {c['text']}; border: 1px solid {c['border']}; {edge}"

    sheet = f"""
* {{ outline: none; }}
QWidget {{ color: {c['text']}; font-size: {ty.body}px; }}
QMainWindow, QDialog {{ background: {c['window']}; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']};
            border-radius: {r['md']}px; padding: {s['xs']}px {s['sm']}px; }}

/* ---- navigation rail ---- */
#NavRail {{ background: {c['nav']}; border-right: 1px solid {c['border']}; }}
#NavRail QToolButton {{ border: 1px solid transparent; border-radius: {r['lg']}px; padding: {s['sm']}px 0;
            color: {c['text_muted']}; font-size: {ty.caption}px; font-weight: 500; }}
#NavRail QToolButton:hover {{ background: {c['surface_alt']}; color: {c['text']}; }}
#NavRail QToolButton:checked {{ {nav_checked} }}

/* ---- page header ---- */
#PageHeader {{ background: {c['window']}; border-bottom: 1px solid {c['border']}; }}
QLabel[role="display"] {{ font-size: {ty.display}px; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: {ty.heading}px; font-weight: 600; }}
QLabel[role="title"] {{ font-size: {ty.title}px; font-weight: 600; }}
QLabel[role="label"] {{ font-size: {ty.label}px; font-weight: 600; color: {c['text_muted']}; }}
QLabel[role="muted"] {{ color: {c['text_muted']}; }}
QLabel[role="caption"] {{ font-size: {ty.caption}px; color: {c['text_muted']}; }}
QLabel[role="overline"] {{ font-size: {ty.caption}px; font-weight: 600; color: {c['text_faint']};
            letter-spacing: {1.2 if fx.numbers == "mono" else 0.6}px; }}
QLabel[role="stat"] {{ font-size: {ty.heading}px; {stat_family} }}

/* ---- cards ---- */
QFrame[card="true"] {{ background: {panel}; border: 1px solid {c['border']}; {edge} border-radius: {r['lg']}px; }}
QFrame[card="true"][accent="brand"] {{ border-left: 3px solid {c['brand']}; }}
QFrame[card="true"][accent="success"] {{ border-left: 3px solid {c['success']}; }}
QFrame[card="true"][accent="danger"] {{ border-left: 3px solid {c['danger']}; }}
QFrame[divider="true"] {{ background: {c['border']}; border: none; max-height: 1px; min-height: 1px; }}
QFrame[empty="true"] {{ background: transparent; border: 1px dashed {c['border_strong']}; border-radius: {r['xl']}px; }}
QFrame[canvas="true"] {{ background: {c['sunken'] if fx.canvas != "none" else c['surface']}; border: 1px solid {c['border']};
            border-radius: {r['lg']}px; }}
QFrame[canvas="true"] QFrame[empty="true"] {{ border-color: transparent; }}

/* ---- buttons ---- */
QPushButton {{ background: {panel}; color: {c['text']}; border: 1px solid {c['border_strong']}; {edge}
            border-radius: {r['md']}px; padding: 0 {s['md']}px; min-height: {T.CONTROL_HEIGHT - 2}px; font-weight: 500; }}
QPushButton:hover {{ background: {c['surface_alt']}; }}
QPushButton:pressed {{ background: {c['sunken']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; border-color: {c['border']}; }}
{primary}
{run}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {c['text_muted']}; }}
QPushButton[variant="ghost"]:hover {{ background: {c['surface_alt']}; color: {c['text']}; }}
QPushButton[variant="danger"] {{ color: {c['danger']}; }}
QToolButton {{ border: 1px solid transparent; border-radius: {r['md']}px; padding: {s['xs']}px; }}
QToolButton:hover {{ background: {c['surface_alt']}; }}
QToolButton:checked {{ background: {c['primary_soft']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---- segmented control ---- */
#Segmented {{ background: {c['sunken']}; border: 1px solid {c['border']}; border-radius: {r['lg']}px; }}
#Segmented QPushButton {{ background: transparent; border: 1px solid transparent; border-radius: {r['md']}px;
            color: {c['text_muted']}; min-height: {T.CONTROL_HEIGHT - 6}px; padding: 0 {s['lg']}px; }}
#Segmented QPushButton:hover {{ color: {c['text']}; }}
#Segmented QPushButton:checked {{ {seg_checked} }}

/* ---- badges ---- */
QLabel[badge="neutral"] {{ background: {c['sunken']}; color: {c['text_muted']}; border-radius: {r['sm']}px;
            padding: 1px {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="primary"] {{ background: {c['primary_soft']}; color: {c['primary']}; border-radius: {r['sm']}px;
            padding: 1px {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="brand"] {{ background: {c['brand_soft']}; color: {c['brand']}; border-radius: {r['sm']}px;
            padding: 1px {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="success"] {{ color: {c['success']}; border: 1px solid {c['success']}; border-radius: {r['sm']}px;
            padding: 0 {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}
QLabel[badge="danger"] {{ color: {c['danger']}; border: 1px solid {c['danger']}; border-radius: {r['sm']}px;
            padding: 0 {s['sm']}px; font-size: {ty.caption}px; font-weight: 600; }}

/* ---- inputs ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{ background: {c['surface'] if not fx.panel_gradient else c['sunken']};
            border: 1px solid {c['border_strong'] if not fx.panel_gradient else c['border']};
            border-radius: {r['md']}px; padding: 0 {s['sm']}px; min-height: {T.CONTROL_HEIGHT - 2}px;
            selection-background-color: {c['primary']}; selection-color: {c['on_primary']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{ border: 1px solid {c['primary']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({icons.file("chevron", p.text_muted)}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border_strong']};
            selection-background-color: {c['primary_soft']}; selection-color: {c['text']}; }}
QPlainTextEdit, QTextEdit {{ background: {c['sunken']}; border: 1px solid {c['border']}; border-radius: {r['md']}px;
            selection-background-color: {c['primary']}; }}
QPlainTextEdit[code="true"] {{ color: {c['text']}; padding: {s['xs']}px 0; selection-color: {c['on_primary']}; }}
QPlainTextEdit[code="true"]:focus {{ border: 1px solid {c['border_strong']}; }}
QLabel[role="knobvalue"] {{ color: {c['text']}; font-size: {ty.label}px; }}
QCheckBox {{ spacing: {s['sm']}px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['brand'] if fx.primary == "edge" else c['primary']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['surface_top']}; border: 1px solid {c['border_strong']}; width: 14px;
            margin: -6px 0; border-radius: 7px; }}

/* ---- tables and lists ---- */
QTableView, QTreeView, QListView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r['lg']}px;
            gridline-color: {c['border']}; selection-background-color: {c['primary_soft']}; selection-color: {c['text']};
            alternate-background-color: {c['surface_alt']}; }}
QTableView::item, QTreeView::item, QListView::item {{ padding: {s['xs']}px {s['sm']}px; border: none; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['text_muted']}; border: none;
            border-bottom: 1px solid {c['border']}; padding: {s['sm']}px; font-size: {ty.label}px; font-weight: 600; }}

/* ---- tabs (strategy tabs) ---- */
QTabWidget::pane {{ border: none; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {c['text_muted']}; border: none; border-bottom: 2px solid transparent;
            padding: {s['sm']}px {s['md']}px; margin-right: {s['xs']}px; font-weight: 500; }}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['brand']}; }}

/* ---- docks ---- */
QDockWidget {{ titlebar-close-icon: none; color: {c['text_muted']}; font-size: {ty.label}px; font-weight: 600; }}
QDockWidget::title {{ background: {c['window']}; padding: {s['sm']}px {s['md']}px; border-bottom: 1px solid {c['border']}; }}
QMainWindow::separator {{ background: {c['border']}; width: 1px; height: 1px; }}

/* ---- scroll bars ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c['border_strong']}; border-radius: 3px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {c['text_faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; height: 0; width: 0; }}

/* ---- menus and status bar ---- */
QMenu {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: {r['lg']}px; padding: {s['xs']}px; }}
QMenu::item {{ padding: {s['xs'] + 2}px {s['lg']}px; border-radius: {r['sm']}px; }}
QMenu::item:selected {{ background: {c['primary_soft']}; color: {c['text']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: {s['xs']}px {s['sm']}px; }}
QStatusBar {{ background: {c['nav'] if fx.panel_gradient else c['window']}; color: {c['text_muted']}; border-top: 1px solid {c['border']}; font-size: {ty.caption}px; }}
QStatusBar::item {{ border: none; }}
"""
    if sk.qss:
        sheet += "\n/* ---- skin extras ---- */\n" + Template(sk.qss).safe_substitute(
            {**c, **{f"radius_{k}": v for k, v in r.items()}})
    return sheet


def apply(app, mode: str | None = None, skin_id: str | None = None) -> bool:
    """Style the whole app. ``mode``: system, light or dark; ``skin_id``: a skin's id.
    Either left out keeps what is in use. Returns True if dark."""
    global _current, _mode, _skin
    if mode is not None:
        _mode = mode
    if skin_id is not None or _skin is None:
        _skin = skins.get(skin_id or skins.DEFAULT)
    dark = is_dark(_mode)
    _current = _skin.palette(dark)
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
