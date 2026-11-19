"""Measurements page: one tab per measure of success. For now there is one, Profit.

The Profit tab draws the profit of every strategy you tick over time, on a real
time axis so strategies with different trading days line up, plus the default
strategy (hold everything in the dataset). Zoom with the mouse wheel or the
time-frame buttons; the curves and the table are measured from the start of the
visible window, so "profit" always means profit over what you are looking at.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSlider, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

PASS, FAIL = QColor("#1f8a4c"), QColor("#c0392b")
COLORS = ["#2f5bd3", "#c0841a", "#8e44ad", "#16a085", "#d35400", "#2c3e50", "#b4635e"]
DEFAULT_COLOR = QColor("#8a8a84")
DAY = 86400.0
FRAMES = [("All", None), ("5 years", 5 * 365), ("1 year", 365), ("6 months", 182), ("3 months", 91), ("1 month", 30)]


def _secs(times) -> np.ndarray:
    idx = pd.to_datetime(pd.Index(times))
    return ((idx - pd.Timestamp(0)) / pd.Timedelta(seconds=1)).to_numpy(float)


def window_stats(t: np.ndarray, v: np.ndarray, a: float, b: float) -> tuple[float, float] | None:
    """(profit, max drawdown) of an equity curve between times a and b, measured from its value at a."""
    if len(t) == 0:
        return None
    i0 = max(0, int(np.searchsorted(t, a, "right")) - 1)
    i1 = int(np.searchsorted(t, b, "right"))
    seg = v[i0:i1]
    if len(seg) == 0 or seg[0] == 0:
        return None
    seg = seg / seg[0]
    dd = float(np.min(seg / np.maximum.accumulate(seg) - 1))
    return float(seg[-1] - 1), dd


class TimeChart(QWidget):
    """Profit over time for several curves. Wheel zooms, drag pans, double-click shows everything."""

    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[dict] = []
        self.view: tuple[float, float] | None = None
        self._drag = None
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self.setToolTip("Mouse wheel zooms in and out of time, drag to move along it, double-click to see everything.")

    # ---- data
    def set_series(self, series: list[dict]):
        """series: [{"label", "t": seconds array, "v": growth-of-1 array, "color": QColor, "dashed": bool}]"""
        self.series = [s for s in series if len(s["t"])]
        self.view = self._clamp(self.view) if self.view else None
        self.update()
        self.viewChanged.emit()

    def full_range(self) -> tuple[float, float] | None:
        if not self.series:
            return None
        return min(s["t"][0] for s in self.series), max(s["t"][-1] for s in self.series)

    def window(self) -> tuple[float, float] | None:
        return self.view or self.full_range()

    def _clamp(self, view):
        full = self.full_range()
        if not full or not view:
            return None
        a, b = view
        width = min(max(b - a, 3600.0), full[1] - full[0])
        if width >= full[1] - full[0]:
            return None
        a = min(max(a, full[0]), full[1] - width)
        return a, a + width

    def set_view(self, view):
        self.view = self._clamp(view)
        self.update()
        self.viewChanged.emit()

    def last_days(self, days: int | None):
        full = self.full_range()
        if not full or days is None:
            self.set_view(None)
        else:
            self.set_view((full[1] - days * DAY, full[1]))

    def zoom(self, factor: float, at: float | None = None):
        w = self.window()
        if not w:
            return
        a, b = w
        at = (a + b) / 2 if at is None else at
        self.set_view((at - (at - a) * factor, at + (b - at) * factor))

    # ---- geometry
    _L, _R, _T, _B = 58, 14, 28, 30

    def _x_to_t(self, x: float) -> float:
        a, b = self.window()
        return a + (x - self._L) / max(1, self.width() - self._L - self._R) * (b - a)

    # ---- mouse
    def wheelEvent(self, e):
        if self.window():
            self.zoom(0.8 if e.angleDelta().y() > 0 else 1.25, self._x_to_t(e.position().x()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.window():
            self._drag = (e.position().x(), self.window())

    def mouseMoveEvent(self, e):
        if self._drag:
            x0, (a, b) = self._drag
            dt = (e.position().x() - x0) / max(1, self.width() - self._L - self._R) * (b - a)
            self.set_view((a - dt, b - dt))

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.set_view(None)

    # ---- drawing
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = self.palette().color(QPalette.Window).lightness() < 128
        muted = QColor("#9a9a94" if dark else "#6b6b66")
        grid = QColor("#34342f" if dark else "#deded8")
        W, H = self.width(), self.height()
        win = self.window()
        if not win:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, "Run a strategy (Ctrl+Enter) to see its profit over time")
            return
        a, b = win
        curves = []
        for s in self.series:
            t, v = s["t"], s["v"]
            i0 = max(0, int(np.searchsorted(t, a, "right")) - 1)
            i1 = int(np.searchsorted(t, b, "right"))
            if i1 - i0 < 1 or v[i0] == 0:
                continue
            curves.append((s, t[i0:i1], v[i0:i1] / v[i0] - 1))
        vals = [0.0] + [float(x) for _, _, y in curves for x in (y.min(), y.max())]
        lo, hi = min(vals), max(vals)
        if math.isclose(lo, hi):
            hi = lo + 1e-6
        L, R, T, B = self._L, self._R, self._T, self._B
        X = lambda tt: L + (tt - a) / (b - a) * (W - L - R)
        Y = lambda y: T + (hi - y) / (hi - lo) * (H - T - B)
        p.setPen(QPen(grid, 1))
        p.drawLine(QPointF(L, Y(0)), QPointF(W - R, Y(0)))
        p.setPen(muted)
        for y in sorted({lo, 0.0, hi}):
            p.drawText(QRectF(0, Y(y) - 8, L - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{100 * y:+.1f}%")
        fmt = "%Y-%m-%d %H:%M" if b - a < 3 * DAY else "%Y-%m-%d"
        for k in range(5):
            tt = a + k / 4 * (b - a)
            txt = pd.Timestamp(tt, unit="s").strftime(fmt)
            x = X(tt)
            align = Qt.AlignLeft if k == 0 else Qt.AlignRight if k == 4 else Qt.AlignHCenter
            rx = x if k == 0 else x - 120 if k == 4 else x - 60
            p.drawText(QRectF(rx, H - B + 6, 120, 18), align | Qt.AlignTop, txt)
        x_leg = L + 6
        for s, t, y in curves:
            path = QPainterPath(QPointF(X(t[0]), Y(y[0])))
            for tt, yy in zip(t[1:], y[1:]):
                path.lineTo(X(tt), Y(yy))
            pen = QPen(s["color"], 2)
            if s.get("dashed"):
                pen.setStyle(Qt.DashLine)
            p.setClipRect(QRectF(L, 0, W - L - R, H))
            p.setPen(pen)
            p.drawPath(path)
            p.setClipping(False)
            p.setPen(s["color"])
            label = s["label"] if len(s["label"]) <= 34 else s["label"][:33] + "…"
            p.drawText(QPointF(x_leg, 16), label)
            x_leg += p.fontMetrics().horizontalAdvance(label) + 18
        p.end()


class KnobPanel(QWidget):
    """Sliders for the knobs of a strategy written in Python. Letting go of a slider re-runs that strategy."""

    turned = Signal(object, str, object)   # strategy tab, knob name, new value
    write = Signal(object)                 # write the current values into the code as defaults
    reset = Signal(object)

    STEPS = 200

    def __init__(self):
        super().__init__()
        self.tabs: list = []
        self.strategy = QComboBox()
        self.strategy.setToolTip("Which strategy's knobs to show (strategies written in Python).")
        self.strategy.currentIndexChanged.connect(self.rebuild)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        write = QPushButton("Write into code")
        write.setToolTip("Make the current knob positions the defaults in the strategy's code.")
        write.clicked.connect(lambda: self.current() and self.write.emit(self.current()))
        reset = QPushButton("Reset")
        reset.setToolTip("Put every knob back to the value written in the code.")
        reset.clicked.connect(lambda: self.current() and self.reset.emit(self.current()))
        btns = QHBoxLayout()
        btns.addWidget(write)
        btns.addWidget(reset)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("<b>Knobs</b>"))
        lay.addWidget(self.strategy)
        lay.addLayout(self.form)
        lay.addLayout(btns)
        lay.addWidget(self.note)
        lay.addStretch()

    def current(self):
        i = self.strategy.currentIndex()
        return self.tabs[i] if 0 <= i < len(self.tabs) else None

    def set_tabs(self, tabs: list, prefer=None):
        keep = prefer if prefer in tabs else self.current()
        self.tabs = [t for t in tabs if getattr(t, "kind", "") == "python"]
        self.strategy.blockSignals(True)
        self.strategy.clear()
        for t in self.tabs:
            self.strategy.addItem(t.title())
        if keep in self.tabs:
            self.strategy.setCurrentIndex(self.tabs.index(keep))
        self.strategy.blockSignals(False)
        self.rebuild()

    def rebuild(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.sliders = {}
        tab = self.current()
        if tab is None:
            self.note.setText("Strategies written in Python get knobs: put the cursor on a number in the code and "
                              "press Make knob. New… → Python strategy starts one.")
            return
        knobs = [k for k in tab.knobs() if isinstance(k["default"], (int, float)) and k["lo"] is not None]
        if not knobs:
            self.note.setText(f"{tab.key} has no knobs yet. Put the cursor on a number in its code and press Make knob.")
            return
        self.note.setText("Let go of a slider to re-run the strategy with that value. The code is not changed "
                          "until you press Write into code.")
        for k in knobs:
            val = tab.knob_values.get(k["name"], k["default"])
            sl = QSlider(Qt.Horizontal)
            lo, hi = float(k["lo"]), float(k["hi"])
            if k["int"]:
                sl.setRange(int(lo), int(hi))
                sl.setValue(int(val))
            else:
                sl.setRange(0, self.STEPS)
                sl.setValue(round((float(val) - lo) / (hi - lo) * self.STEPS) if hi > lo else 0)
            lbl = QLabel(self._fmt(val, k))
            lbl.setMinimumWidth(56)
            row = QHBoxLayout()
            row.addWidget(sl, 1)
            row.addWidget(lbl)
            sl.valueChanged.connect(lambda _v, k=k, sl=sl, lbl=lbl: lbl.setText(self._fmt(self._value(k, sl), k)))
            sl.sliderReleased.connect(lambda k=k, sl=sl: self.turned.emit(self.current(), k["name"], self._value(k, sl)))
            sl.setToolTip(f"{k['name']}: from {k['lo']} to {k['hi']} (written in the code as {k['default']})")
            self.sliders[k["name"]] = (sl, k)
            self.form.addRow(k["name"], row)

    def _value(self, k, sl):
        if k["int"]:
            return int(sl.value())
        lo, hi = float(k["lo"]), float(k["hi"])
        return round(lo + (hi - lo) * sl.value() / self.STEPS, 6)

    @staticmethod
    def _fmt(v, k):
        return str(int(v)) if k["int"] else f"{float(v):.4g}"

    def turn(self, name: str, value):
        """Move a slider as if by hand and let go (used by tests)."""
        sl, k = self.sliders[name]
        if k["int"]:
            sl.setValue(int(value))
        else:
            lo, hi = float(k["lo"]), float(k["hi"])
            sl.setValue(round((float(value) - lo) / (hi - lo) * self.STEPS))
        sl.sliderReleased.emit()


class ProfitTab(QWidget):
    """Profit of the strategies you tick, plus the default strategy, over a time frame you choose."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[dict] = []  # {"key", "label", "t", "v", "trades", "dataset", "default"}
        self.hidden: set[str] = set()
        self.picker = QListWidget()
        self.picker.setToolTip("Tick the strategies to compare on the graph.")
        self.picker.itemChanged.connect(self._picked)
        self.show_default = QCheckBox("Show default strategy")
        self.show_default.setChecked(True)
        self.show_default.setToolTip("The default strategy spreads the money evenly across every stock in the "
                                     "dataset and holds it (no costs). It is the yardstick to beat.")
        self.show_default.toggled.connect(self.redraw)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Strategies</b>"))
        ll.addWidget(self.picker, 1)
        ll.addWidget(self.show_default)

        self.frame = QComboBox()
        for label, days in FRAMES:
            self.frame.addItem(label, days)
        self.frame.setToolTip("Time frame: how far back from the end of the data to look.")
        self.frame.currentIndexChanged.connect(lambda i: self.chart.last_days(self.frame.itemData(i)))
        zin, zout = QPushButton("+"), QPushButton("−")
        for btn, f, tip in ((zin, 0.5, "Zoom in on time"), (zout, 2.0, "Zoom out")):
            btn.setFixedWidth(32)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _=False, f=f: self.chart.zoom(f))
        self.window_lbl = QLabel()
        self.window_lbl.setStyleSheet("color: gray;")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Time frame:"))
        bar.addWidget(self.frame)
        bar.addWidget(zin)
        bar.addWidget(zout)
        bar.addWidget(self.window_lbl, 1)

        self.chart = TimeChart()
        self.chart.viewChanged.connect(self.fill_table)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(170)
        self.knobs = KnobPanel()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(bar)
        rl.addWidget(self.chart, 1)
        rl.addWidget(self.table)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.addWidget(self.knobs)
        split.setSizes([220, 900, 280])
        lay = QVBoxLayout(self)
        lay.addWidget(split)

    def set_entries(self, entries: list[dict]):
        """entries: strategies with results (and default-strategy curves, flagged "default": True)."""
        self.entries = entries
        self.picker.blockSignals(True)
        self.picker.clear()
        for e in entries:
            if e.get("default"):
                continue
            it = QListWidgetItem(e["label"])
            it.setData(Qt.UserRole, e["key"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked if e["key"] in self.hidden else Qt.Checked)
            self.picker.addItem(it)
        self.picker.blockSignals(False)
        self.redraw()

    def _picked(self, it):
        key = it.data(Qt.UserRole)
        self.hidden.discard(key) if it.checkState() == Qt.Checked else self.hidden.add(key)
        self.redraw()

    def visible(self) -> list[dict]:
        shown = [e for e in self.entries if not e.get("default") and e["key"] not in self.hidden]
        if self.show_default.isChecked():
            datasets = {e["dataset"] for e in shown}
            shown += [e for e in self.entries if e.get("default") and e["dataset"] in datasets]
        return shown

    def redraw(self):
        series, k = [], 0
        for e in self.visible():
            if e.get("default"):
                color = DEFAULT_COLOR
            else:
                color = QColor(COLORS[k % len(COLORS)])
                k += 1
            series.append({"label": e["label"], "t": e["t"], "v": e["v"], "color": color, "dashed": e.get("default")})
        self.chart.set_series(series)

    def fill_table(self):
        win = self.chart.window()
        rows = self.visible()
        if win:
            a, b = win
            fmt = lambda x: pd.Timestamp(x, unit="s").strftime("%Y-%m-%d")
            self.window_lbl.setText(f"  {fmt(a)} to {fmt(b)} · profit measured from the start of this window")
        else:
            self.window_lbl.setText("")
        heads = ["Strategy", "Profit", "Profit $", "Max drawdown", "Trades"]
        t = self.table
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(rows))
        for r, e in enumerate(rows):
            st = window_stats(e["t"], e["v"], *win) if win else None
            trades = [tr for tr in e.get("trades") or [] if win and a <= tr["_t"] <= b]
            usd = [tr["pnl_usd"] for tr in trades if tr.get("pnl_usd") is not None]
            vals = [e["label"], "–" if not st else f"{100 * st[0]:+.2f}%",
                    f"{sum(usd):+,.0f}" if usd else "–", "–" if not st else f"{100 * st[1]:.1f}%",
                    "–" if e.get("default") else str(len(trades))]
            for c, v in enumerate(vals):
                t.setItem(r, c, QTableWidgetItem(v))
            if st:
                t.item(r, 1).setForeground(PASS if st[0] > 0 else FAIL)
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)


class MeasurementsPage(QTabWidget):
    """One tab per measure of success."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profit = ProfitTab()
        self.addTab(self.profit, "Profit")
        self.setTabToolTip(0, "Profit over time. For now profit is the only measure of success.")

    def refresh(self, strategies: list, current=None) -> None:
        """strategies: strategy tabs; those with a result are measured. ``current`` picks whose knobs show."""
        self.profit.knobs.set_tabs(strategies, current)
        entries, defaults = [], {}
        for tab in strategies:
            rep = tab.report
            if not rep:
                continue
            eq = rep["selected"]["equity"]
            trades = [dict(tr, _t=float(_secs([tr["entry_time"]])[0])) for tr in rep["selected"]["trades"]]
            # start the curve at 1 just before the first period, so the first period's profit shows
            t = _secs(eq["t"])
            v = np.asarray(eq["v"], float)
            if len(t):
                t, v = np.r_[t[0] - 1.0, t], np.r_[1.0, v]
            ds = rep["data"]
            entries.append({"key": tab.key, "label": tab.title(), "t": t, "v": v, "trades": trades, "dataset": ds})
            if ds not in defaults and rep.get("default_equity"):
                d = rep["default_equity"]
                defaults[ds] = {"key": "default:" + ds, "label": f"Default: hold everything ({tab.dataset_label()})",
                                "t": _secs(d["t"]), "v": np.asarray(d["v"], float), "dataset": ds, "default": True}
        self.profit.set_entries(entries + list(defaults.values()))
