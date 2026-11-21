"""The component kit. Build UI from these; they take their look from the theme.

Every component restyles itself when the theme changes (the stylesheet does the
work, so nothing here hard-codes a colour).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons, theme
from . import tokens as T

S = T.SPACE


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    """Text in one of the type roles: display, heading, title, label, muted, caption, overline, stat."""
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse if wrap else Qt.NoTextInteraction)
    return lbl


def button(text: str, variant: str = "secondary", icon: str | None = None, tip: str = "") -> QPushButton:
    """variant: primary (one per area), secondary, ghost, danger."""
    b = QPushButton(text)
    if variant != "secondary":
        b.setProperty("variant", variant)
    b.setCursor(Qt.PointingHandCursor)
    if icon:
        def paint(w, name=icon, primary=variant == "primary"):
            p = theme.current()
            w.setIcon(icons.icon(name, p.on_primary if primary else p.text_muted, size=16))
        paint(b)
        theme.watch(b, paint)
    if tip:
        b.setToolTip(tip)
    return b


def badge(text: str, kind: str = "neutral") -> QLabel:
    """kind: neutral, primary, brand, success, danger."""
    lbl = QLabel(text)
    lbl.setProperty("badge", kind)
    lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lbl


def divider() -> QFrame:
    f = QFrame()
    f.setProperty("divider", "true")
    return f


def hbox(*items, spacing: int = S["sm"], margins: int = 0) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(margins, margins, margins, margins)
    for it in items:
        if it is None:
            lay.addStretch()
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


class Card(QFrame):
    """A surface with an optional title row. ``accent``: brand, success, danger."""

    def __init__(self, title: str = "", subtitle: str = "", accent: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("card", "true")
        if accent:
            self.setProperty("accent", accent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(S["lg"], S["lg"], S["lg"], S["lg"])
        self.body.setSpacing(S["md"])
        self.header = QHBoxLayout()
        self.header.setSpacing(S["sm"])
        if title:
            col = QVBoxLayout()
            col.setSpacing(S["xxs"])
            col.addWidget(label(title, "title"))
            if subtitle:
                col.addWidget(label(subtitle, "caption", wrap=True))
            self.header.addLayout(col, 1)
            self.body.addLayout(self.header)

    def add_action(self, widget: QWidget) -> None:
        self.header.addWidget(widget, 0, Qt.AlignTop)


class StatTile(Card):
    """A number with its label, e.g. Profit +12.4%."""

    def __init__(self, caption: str, value: str, note: str = "", parent=None):
        super().__init__(parent=parent)
        self.body.setSpacing(S["xs"])
        self.body.addWidget(label(caption.upper(), "overline"))
        self.value = label(value, "stat")
        self.body.addWidget(self.value)
        if note:
            self.body.addWidget(label(note, "caption"))

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class EmptyState(QFrame):
    """What an area shows before it has anything: an icon, one line of what goes here, and actions."""

    def __init__(self, icon: str, title: str, text: str, actions: list[QPushButton] | None = None, parent=None):
        super().__init__(parent)
        self.setProperty("empty", "true")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S["xxl"], S["xxl"], S["xxl"], S["xxl"])
        lay.setSpacing(S["md"])
        lay.addStretch()
        ic = QLabel()
        ic.setAlignment(Qt.AlignCenter)

        def paint(w, name=icon):
            w.setPixmap(icons.pixmap(name, theme.current().text_faint, 36))
        paint(ic)
        theme.watch(ic, paint)
        lay.addWidget(ic)
        t = label(title, "title")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        body = label(text, "muted", wrap=True)
        body.setAlignment(Qt.AlignCenter)
        body.setFixedWidth(480)
        lay.addLayout(hbox(None, body, None))
        if actions:
            lay.addSpacing(S["sm"])
            lay.addLayout(hbox(None, *actions, None))
        lay.addStretch()


class Segmented(QFrame):
    """A row of mutually exclusive choices, e.g. Patch bay | Code | Run."""

    changed = Signal(int)

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, text in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self.changed.emit)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, i: int) -> None:
        self.group.button(i).setChecked(True)
        self.changed.emit(i)


class SearchField(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._search = act = self.addAction(icons.icon("search", theme.current().text_faint, size=16), QLineEdit.LeadingPosition)
        theme.watch(act, lambda a: a.setIcon(icons.icon("search", theme.current().text_faint, size=16)))


class Logo(QLabel):
    """The Titanium mark, from the shipped artwork."""

    def __init__(self, size: int = 36, parent=None):
        super().__init__(parent)
        from pathlib import Path

        src = QPixmap(str(Path(__file__).resolve().parent.parent / "assets" / "titanium-256.png"))
        ratio = 2.0
        pm = QPixmap(int(size * ratio), int(size * ratio))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(pm.rect(), src)
        p.end()
        pm.setDevicePixelRatio(ratio)
        self.setPixmap(pm)
        self.setFixedSize(size, size)
        self.setToolTip("Titanium")
