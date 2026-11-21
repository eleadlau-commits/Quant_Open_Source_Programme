"""The component kit. Build UI from these; they take their look from the theme.

Every component restyles itself when the theme changes (the stylesheet does the
work, so nothing here hard-codes a colour).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import icons, theme
from . import tokens as T

S = T.SPACE


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    """Text in one of the type roles: display, heading, title, label, muted, caption, overline, stat,
    mono (paths, ids), error, key (the left column of a details list)."""
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


# ---- lists, details and forms (added for the Data page) ------------------------------------
class DataTable(QTableWidget):
    """A list of objects, one per row: whole-row selection, no grid, sortable.

    ``set_rows(rows, keys)`` fills it (``keys``: the object ids, in row order);
    ``selected`` fires with the key of the chosen row.
    """

    selected = Signal(str)

    def __init__(self, columns: list[str], stretch: int | None = None, parent=None):
        """``stretch``: the column that takes the spare width (default: the last)."""
        super().__init__(0, len(columns), parent)
        self.stretch = stretch
        self.setHorizontalHeaderLabels(columns)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(stretch is None)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if stretch is not None else Qt.ScrollBarAsNeeded)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.horizontalHeader().setHighlightSections(False)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWordWrap(False)
        self.verticalHeader().setDefaultSectionSize(T.CONTROL_HEIGHT + S["sm"])
        self.itemSelectionChanged.connect(self._emit)

    def set_rows(self, rows: list[tuple], keys: list[str]) -> None:
        keep = self.selected_key()
        self.blockSignals(True)
        self.setSortingEnabled(False)
        self.setRowCount(len(rows))
        for r, (vals, key) in enumerate(zip(rows, keys)):
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.UserRole, key)
                item.setToolTip(str(v))
                self.setItem(r, c, item)
        self.resizeColumnsToContents()
        if self.stretch is not None:
            self.horizontalHeader().setSectionResizeMode(self.stretch, QHeaderView.Stretch)
        self.blockSignals(False)
        if keep in keys:
            self.select(keep)

    def keys(self) -> list[str]:
        return [self.item(r, 0).data(Qt.UserRole) for r in range(self.rowCount())]

    def selected_key(self) -> str | None:
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        return self.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def select(self, key: str) -> None:
        for r in range(self.rowCount()):
            if self.item(r, 0).data(Qt.UserRole) == key:
                self.selectRow(r)
                return

    def _emit(self) -> None:
        key = self.selected_key()
        if key is not None:
            self.selected.emit(key)


class Details(QWidget):
    """A details list: small caps keys on the left, plain values on the right.

    ``set_rows([(key, value), ...])``. A value may be text or a widget (e.g. a row of badges).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(S["lg"])
        self.grid.setVerticalSpacing(S["md"])
        self.grid.setColumnStretch(1, 1)
        self.values: dict[str, QWidget] = {}

    def set_rows(self, rows: list[tuple[str, object]]) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self.values = {}
        for i in range(self.grid.rowCount()):
            self.grid.setRowStretch(i, 0)
        for r, (key, value) in enumerate(rows):
            k = label(key.upper(), "key")
            k.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.grid.addWidget(k, r, 0, Qt.AlignTop)
            if isinstance(value, QWidget):
                v = value
            elif isinstance(value, QLayout):
                v = QWidget()
                value.setContentsMargins(0, 0, 0, 0)
                v.setLayout(value)
            else:
                v = label(str(value), "", wrap=True)
                v.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.grid.addWidget(v, r, 1)
            self.values[key] = v
        self.grid.setRowStretch(len(rows), 1)


class ParamForm(QWidget):
    """Fields for a list of settings (``core.data.Param``): numbers, text, switches, choices,
    dates and file pickers. ``values()`` reads them back; ``changed`` fires on any edit."""

    changed = Signal()

    def __init__(self, params: list, values: dict | None = None, parent=None):
        super().__init__(parent)
        values = values or {}
        self.params = list(params)
        self.inputs: dict[str, QWidget] = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(S["lg"])
        form.setVerticalSpacing(S["md"])
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for p in self.params:
            w = self._field(p, values.get(p.name, p.default))
            if p.help:
                w.setToolTip(p.help)
            self.inputs[p.name] = w
            form.addRow(label(p.label or p.name.replace("_", " ").capitalize(), "label"), w)

    def _field(self, p, value) -> QWidget:
        if p.type == "int":
            w = QSpinBox()
            w.setRange(int(p.minimum if p.minimum is not None else -10**9),
                       int(p.maximum if p.maximum is not None else 10**9))
            w.setValue(int(value))
            w.valueChanged.connect(self._changed)
        elif p.type == "float":
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setSingleStep(0.05)
            w.setRange(float(p.minimum if p.minimum is not None else -1e12),
                       float(p.maximum if p.maximum is not None else 1e12))
            w.setValue(float(value))
            w.valueChanged.connect(self._changed)
        elif p.type == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(self._changed)
        elif p.type == "choice":
            w = QComboBox()
            w.addItems([str(c) for c in p.choices])
            w.setCurrentText(str(value))
            w.currentTextChanged.connect(self._changed)
        elif p.type == "path":
            w = PathField(str(value or ""))
            w.edit.textChanged.connect(self._changed)
        else:  # str, date
            w = QLineEdit(str(value or ""))
            if p.type == "date":
                w.setPlaceholderText("YYYY-MM-DD")
            w.textChanged.connect(self._changed)
        return w

    def _changed(self, *_):
        self.changed.emit()

    def values(self) -> dict:
        out = {}
        for p in self.params:
            w = self.inputs[p.name]
            if isinstance(w, QSpinBox):
                out[p.name] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                out[p.name] = w.value()
            elif isinstance(w, QCheckBox):
                out[p.name] = w.isChecked()
            elif isinstance(w, QComboBox):
                out[p.name] = w.currentText()
            elif isinstance(w, PathField):
                out[p.name] = w.text()
            else:
                out[p.name] = w.text()
        return out

    def set_value(self, name: str, value) -> None:
        w = self.inputs[name]
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            w.setValue(value)
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            w.setCurrentText(str(value))
        else:
            w.setText(str(value))


class PathField(QWidget):
    """A text field for one or more file paths (separated by ';') with a Browse button."""

    def __init__(self, text: str = "", filters: str = "Data files (*.csv *.parquet *.pq);;All files (*)", parent=None):
        super().__init__(parent)
        self.filters = filters
        self.edit = QLineEdit(text)
        self.edit.setPlaceholderText("Choose files")
        self.browse = button("Browse", "secondary", "folder")
        self.browse.clicked.connect(self._pick)
        lay = hbox(self.edit, self.browse)
        self.setLayout(lay)

    def _pick(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", self.filters)
        if files:
            self.edit.setText(";".join(files))

    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)


class Dialog(QDialog):
    """A modal panel: title and help at the top, ``body`` for content, and a footer with
    Cancel and one primary action. ``set_busy`` shows work in progress; ``set_error``
    shows what went wrong in plain words."""

    def __init__(self, title: str, subtitle: str = "", action: str = "Done", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(S["xl"], S["xl"], S["xl"], S["lg"])
        outer.setSpacing(S["lg"])
        head = QVBoxLayout()
        head.setSpacing(S["xs"])
        head.addWidget(label(title, "heading"))
        if subtitle:
            head.addWidget(label(subtitle, "muted", wrap=True))
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(S["md"])
        outer.addLayout(self.body, 1)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        outer.addWidget(self.error)
        self.status = label("", "caption")
        self.cancel = button("Cancel", "ghost")
        self.cancel.clicked.connect(self.reject)
        self.ok = button(action, "primary")
        self.ok.setDefault(True)
        outer.addLayout(hbox(self.status, None, self.cancel, self.ok))

    def set_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def set_busy(self, busy: bool, text: str = "Working…") -> None:
        self.ok.setEnabled(not busy)
        self.cancel.setEnabled(not busy)
        self.status.setText(text if busy else "")
        if busy:
            self.set_error("")


class Switch(QAbstractButton):
    """On or off, for a setting that takes effect at once (a plugin, a feature).
    Classic fills it with ``primary``; skins with edge buttons use ``ink``, never a blue fill."""

    def __init__(self, on: bool = False, tip: str = "", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        if tip:
            self.setToolTip(tip)
        theme.watch(self, lambda w: w.update())

    def sizeHint(self) -> QSize:
        return QSize(36, 20)

    def paintEvent(self, _e) -> None:
        p = theme.current()
        on = self.isChecked()
        fill = p.primary if theme.effects().primary == "fill" else p.ink
        track = QColor(fill if on else p.border_strong)
        if not self.isEnabled():
            track.setAlphaF(0.4)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        h = min(r.height(), 20)
        track_rect = QRectF(r.x(), r.y() + (r.height() - h) / 2, min(r.width(), 36), h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(track_rect, h / 2, h / 2)
        d = h - 6
        x = track_rect.right() - d - 3 if on else track_rect.left() + 3
        painter.setBrush(QColor(p.on_primary if on and fill == p.primary else p.on_ink if on else p.surface_top))
        painter.drawEllipse(QRectF(x, track_rect.top() + 3, d, d))
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(p.primary), 1))
            painter.drawRoundedRect(track_rect.adjusted(-1, -1, 1, 1), h / 2 + 1, h / 2 + 1)
        painter.end()


class ItemRow(QFrame):
    """One item in a list inside a card: a title with a badge, a caption, a note under it
    (e.g. why something is off) and controls on the right. Rows are split by dividers."""

    def __init__(self, title: str, caption: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("itemrow", "true")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, S["sm"], 0, S["sm"])
        outer.setSpacing(S["lg"])
        text = QVBoxLayout()
        text.setSpacing(S["xxs"])
        self.title_row = hbox(label(title, "label"), spacing=S["sm"])
        text.addLayout(self.title_row)
        self.caption = label(caption, "caption", wrap=True)
        self.caption.setVisible(bool(caption))
        text.addWidget(self.caption)
        self.note = label("", "caption", wrap=True)
        self.note.hide()
        text.addWidget(self.note)
        outer.addLayout(text, 1)
        self.controls = hbox(spacing=S["sm"])
        outer.addLayout(self.controls)
        self.title_row.addStretch()

    def add_badge(self, widget: QWidget) -> None:
        self.title_row.insertWidget(self.title_row.count() - 1, widget)

    def add_control(self, widget: QWidget) -> None:
        self.controls.addWidget(widget, 0, Qt.AlignVCenter)

    def set_note(self, text: str, role: str = "caption") -> None:
        self.note.setText(text)
        self.note.setProperty("role", role)
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)
        self.note.setVisible(bool(text))


# Code and knobs live in their own file; they are part of the kit all the same.
from .code_editor import CodeEditor, KnobControl  # noqa: E402,F401
