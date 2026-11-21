"""The component kit. Build UI from these; they take their look from the theme.

Every component restyles itself when the theme changes (the stylesheet does the
work, so nothing here hard-codes a colour).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
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
            if not primary:
                color = p.text_muted
            else:  # primary: white on a fill, the brand red on a raised edge button
                color = p.on_primary if theme.effects().primary == "fill" else p.brand
            w.setIcon(icons.icon(name, color, size=16))
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


class RunButton(QPushButton):
    """The Run action: a red play mark, the label, and the shortcut beside it.

    The skin decides its shape (``effects.run``: fill or capsule) and whether it glows
    (``effects.glow``). ``set_running(True)`` shows it is busy: the label reads
    "Running", the hint shows progress, and a glowing skin pulses.
    """

    def __init__(self, text: str = "Run", shortcut: str = "Ctrl ↵", tip: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("variant", "run")
        self.setCursor(Qt.PointingHandCursor)
        self._text, self._shortcut = text, shortcut
        if tip:
            self.setToolTip(tip)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S["md"] - 2, 0, S["md"], 0)
        lay.setSpacing(S["sm"] - 1)
        self.mark = QLabel()
        self.label = QLabel(text)
        self.label.setProperty("role", "runtext")
        self.hint = QLabel(shortcut)
        self.hint.setProperty("role", "runhint")
        for w in (self.mark, self.label, self.hint):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)
        self.running = False
        self._pulse = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1400, loopCount=-1)
        self._pulse.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse.valueChanged.connect(self._pulse_step)
        self.retheme()
        theme.watch(self, RunButton.retheme)

    def sizeHint(self) -> QSize:
        h = self.layout().sizeHint()
        return QSize(h.width(), T.CONTROL_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def retheme(self) -> None:
        p, fx = theme.current(), theme.effects()
        on_fill = fx.run == "fill"
        self.mark.setPixmap(icons.pixmap("play", p.on_primary if on_fill else p.brand, 11))
        self.hint.setFont(theme.mono_font(T.TYPE.caption - 1))
        if fx.glow > 0:
            fx_ = self.graphicsEffect()
            if not isinstance(fx_, QGraphicsDropShadowEffect):
                fx_ = QGraphicsDropShadowEffect(self)
                fx_.setOffset(0, 0)
                self.setGraphicsEffect(fx_)
            self._glow_at(0.0)
        else:
            self.setGraphicsEffect(None)
        self._sync_pulse()

    def _glow_at(self, t: float) -> None:
        """t from 0 (resting glow) to 1 (peak of a running pulse)."""
        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsDropShadowEffect):
            return
        g = theme.effects().glow
        strength = g * (0.55 + 0.45 * t) if self.running else g * 0.5
        eff.setBlurRadius(14 + 14 * t if self.running else 14)
        eff.setColor(theme.qcolor(theme.current().glow, strength))

    def _pulse_step(self, v) -> None:
        self._glow_at(1 - abs(1 - 2 * float(v)))

    def _sync_pulse(self) -> None:
        if self.running and isinstance(self.graphicsEffect(), QGraphicsDropShadowEffect):
            if self._pulse.state() != QVariantAnimation.Running:
                self._pulse.start()
        else:
            self._pulse.stop()
            self._glow_at(0.0)

    def set_running(self, running: bool, progress: str = "") -> None:
        self.running = running
        self.setProperty("running", "true" if running else "false")
        self.label.setText("Running" if running else self._text)
        self.hint.setText(progress if running and progress else self._shortcut)
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()
        self._sync_pulse()


class Canvas(QFrame):
    """A working surface for things laid out in space (the patch bay, charts).
    Draws the skin's backdrop: plain, a dot grid or ruled lines (``effects.canvas``)."""

    STEP = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("canvas", "true")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(S["lg"], S["lg"], S["lg"], S["lg"])
        theme.watch(self, lambda w: w.update())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        kind = theme.effects().canvas
        if kind == "none":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.current()
        inset, step = 6, self.STEP
        w, h = self.width() - inset, self.height() - inset
        if kind == "dots":
            p.setPen(QPen(theme.qcolor(pal.border_strong, 0.55), 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawPoints([QPointF(x, y) for x in range(step, w, step) for y in range(step, h, step)])
        else:
            p.setPen(QPen(theme.qcolor(pal.border, 0.8), 1))
            for y in range(step * 2, h, step * 2):
                p.drawLine(inset, y, w, y)
        p.end()


def paint_nav_marker(widget: QWidget) -> None:
    """The active page's marker in the navigation rail, for skins with ``nav_marker = "dot"``:
    a small glowing brand-red dot in the button's top-right corner. Called from the
    rail button's paintEvent; does nothing for other skins or unchecked buttons."""
    if theme.effects().nav_marker != "dot" or not getattr(widget, "isChecked", lambda: False)():
        return
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    pal = theme.current()
    c = QPointF(widget.width() - 9.5, 9.5)
    p.setPen(Qt.NoPen)
    for radius, alpha in ((6.0, 0.12), (4.0, 0.25)):
        p.setBrush(theme.qcolor(pal.glow, alpha))
        p.drawEllipse(c, radius, radius)
    p.setBrush(theme.qcolor(pal.brand))
    p.drawEllipse(c, 2.4, 2.4)
    p.end()


# Code and knobs live in their own file; they are part of the kit all the same.
from .code_editor import CodeEditor, KnobControl  # noqa: E402,F401
