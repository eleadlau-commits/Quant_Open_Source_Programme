"""TimeChart: a thin, themed viewer for time series from a run record.

It draws what it is given and nothing more: curves on a real time axis, an optional
panel below for local series (positions, weights, module outputs), an optional right
axis for an overlay, and trade dots. The mouse wheel zooms in time around the cursor,
dragging pans, a double-click shows everything again, and a crosshair reads every
series at the time under the cursor.

    chart = TimeChart()
    chart.set_data([ChartSeries("Strategy", points), ChartSeries("Default", base, dashed=True)],
                   markers=[ChartMarker(t, +1, "Bought 10 AAA")], fmt=lambda v: f"{v:.2f}")

Colours come from the skin: series take ``palette.series`` in order (the first is the
brand red), a dashed series is drawn in the muted text colour, entries are success
dots and exits danger dots.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Callable, Sequence

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip

from . import theme
from . import tokens as T
from .components import Canvas

UTC = timezone.utc
MAIN, SUB = "main", "sub"
LEFT, RIGHT = "left", "right"
Format = Callable[[float], str]


def plain(v: float) -> str:
    return f"{v:,.4g}"


@dataclass
class ChartSeries:
    """One line. ``points``: (time, value) pairs, times timezone-aware (or naive UTC).

    ``panel``: main or sub (the panel below). ``axis``: left, or right for an overlay
    on the main panel with its own scale. ``color``: an index into the skin's series
    colours (default: next in order)."""

    name: str
    points: Sequence[tuple[datetime, float]]
    dashed: bool = False
    panel: str = MAIN
    axis: str = LEFT
    color: int | None = None
    t: np.ndarray = field(init=False, repr=False)
    v: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        pts = [(a, b) for a, b in self.points if b is not None and math.isfinite(b)]
        self.t = np.array([_secs(a) for a, _ in pts], dtype=float)
        self.v = np.array([b for _, b in pts], dtype=float)

    def at(self, t: float) -> float | None:
        """The value in force at time t (the last point at or before it)."""
        if not len(self.t) or t < self.t[0]:
            return None
        return float(self.v[max(0, int(np.searchsorted(self.t, t, "right")) - 1)])


@dataclass
class ChartMarker:
    """A trade dot. ``side`` +1 for an entry, -1 for an exit; ``text`` shows on hover."""

    time: datetime
    side: int = 1
    text: str = ""


def _secs(t: datetime) -> float:
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.timestamp()


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Round tick values covering lo..hi (steps of 1, 2 or 5 times a power of ten)."""
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo]
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step) * step
    out, x = [], first
    while x <= hi + step * 1e-9:
        out.append(round(x, 12))
        x += step
    return out


# time steps for the axis: (seconds, label format)
_TIME_STEPS = [
    (60, "%H:%M"), (300, "%H:%M"), (900, "%H:%M"), (1800, "%H:%M"), (3600, "%H:%M"), (3 * 3600, "%H:%M"),
    (86400, "%d %b"), (2 * 86400, "%d %b"), (7 * 86400, "%d %b"), (14 * 86400, "%d %b"),
    (30 * 86400, "%b %Y"), (91 * 86400, "%b %Y"), (182 * 86400, "%b %Y"), (365 * 86400, "%Y"),
]


def time_ticks(a: float, b: float, tz: tzinfo, max_ticks: int) -> list[tuple[float, str]]:
    """Tick times between a and b (seconds), on local-time boundaries, with their labels."""
    span = max(1.0, b - a)
    step, fmt = next(((s, f) for s, f in _TIME_STEPS if span / s <= max_ticks), _TIME_STEPS[-1])
    start = datetime.fromtimestamp(a, tz)
    if step >= 365 * 86400:
        cur = start.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        months = 12 * max(1, round(step / (365 * 86400)))
    elif step >= 30 * 86400:
        cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        months = max(1, round(step / (30 * 86400)))
    else:
        months = 0
        if step >= 86400:
            cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
            if step >= 7 * 86400:  # weeks start on Monday
                cur -= timedelta(days=cur.weekday())
        else:
            cur = start.replace(minute=0, second=0, microsecond=0)
    out = []
    for _ in range(400):
        s = cur.timestamp()
        if s > b:
            break
        if s >= a:
            out.append((s, cur.strftime(fmt).lstrip("0") if fmt.startswith("%d") else cur.strftime(fmt)))
        if months:
            m = cur.month - 1 + months
            cur = cur.replace(year=cur.year + m // 12, month=m % 12 + 1)
        else:
            cur = datetime.fromtimestamp(s + step, tz)
            if step >= 86400:  # stay on midnight across clock changes
                cur = cur.replace(hour=0, minute=0, second=0, microsecond=0)
    return out


class TimeChart(Canvas):
    """A time-series chart on the skin's canvas backdrop. See the module docstring."""

    view_changed = Signal()

    L, R_PAD, T_PAD, B_PAD, GAP = 62, 16, 30, 26, 20
    SUB_SHARE = 0.32  # share of the plot height the panel below takes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.series: list[ChartSeries] = []
        self.markers: list[ChartMarker] = []
        self.formats: dict[str, Format] = {MAIN: plain, SUB: plain, RIGHT: plain}
        self.tz: tzinfo = UTC
        self.empty_text = "Nothing to show yet"
        self.view: tuple[float, float] | None = None  # None: everything
        self._hover: float | None = None
        self._drag: tuple[float, tuple[float, float]] | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self.setToolTip("")

    # ---- data -----------------------------------------------------------------------
    def set_data(self, series: Sequence[ChartSeries], markers: Sequence[ChartMarker] = (),
                 fmt: Format | None = None, sub_fmt: Format | None = None, right_fmt: Format | None = None,
                 keep_view: bool = True) -> None:
        self.series = [s for s in series if len(s.t)]
        self.markers = sorted(markers, key=lambda m: _secs(m.time))
        self.formats = {MAIN: fmt or plain, SUB: sub_fmt or plain, RIGHT: right_fmt or plain}
        self.view = self._clamp(self.view) if keep_view else None
        self.update()
        self.view_changed.emit()

    def set_timezone(self, tz: tzinfo) -> None:
        self.tz = tz
        self.update()

    def full_range(self) -> tuple[float, float] | None:
        if not self.series:
            return None
        return min(float(s.t[0]) for s in self.series), max(float(s.t[-1]) for s in self.series)

    def window(self) -> tuple[float, float] | None:
        return self.view or self.full_range()

    def _clamp(self, view):
        full = self.full_range()
        if not full or not view:
            return None
        width = min(max(view[1] - view[0], 600.0), full[1] - full[0])
        if width >= full[1] - full[0]:
            return None
        a = min(max(view[0], full[0]), full[1] - width)
        return a, a + width

    def set_view(self, view: tuple[float, float] | None) -> None:
        self.view = self._clamp(view)
        self.update()
        self.view_changed.emit()

    def zoom(self, factor: float, at: float | None = None) -> None:
        w = self.window()
        if not w:
            return
        a, b = w
        at = (a + b) / 2 if at is None else at
        self.set_view((at - (at - a) * factor, at + (b - at) * factor))

    # ---- geometry -------------------------------------------------------------------
    def _has(self, panel: str, axis: str | None = None) -> bool:
        return any(s.panel == panel and (axis is None or s.axis == axis) for s in self.series)

    def _right_pad(self) -> int:
        return 62 if self._has(MAIN, RIGHT) else self.R_PAD

    def _panels(self) -> dict[str, QRectF]:
        w, h = self.width(), self.height()
        left, right = self.L, w - self._right_pad()
        top, bottom = self.T_PAD, h - self.B_PAD
        if not self._has(SUB):
            return {MAIN: QRectF(left, top, right - left, bottom - top)}
        sub_h = (bottom - top - self.GAP) * self.SUB_SHARE
        main_h = bottom - top - self.GAP - sub_h
        return {MAIN: QRectF(left, top, right - left, main_h),
                SUB: QRectF(left, top + main_h + self.GAP, right - left, sub_h)}

    def _x(self, t: float, r: QRectF) -> float:
        a, b = self.window()
        return r.left() + (t - a) / max(1e-9, b - a) * r.width()

    def _t(self, x: float) -> float:
        a, b = self.window()
        r = self._panels()[MAIN]
        return a + (x - r.left()) / max(1.0, r.width()) * (b - a)

    def _range(self, panel: str, axis: str) -> tuple[float, float] | None:
        a, b = self.window()
        lo, hi = math.inf, -math.inf
        for s in self.series:
            if s.panel != panel or s.axis != axis:
                continue
            i0 = max(0, int(np.searchsorted(s.t, a, "right")) - 1)
            i1 = int(np.searchsorted(s.t, b, "right"))
            seg = s.v[i0:i1]
            if len(seg):
                lo, hi = min(lo, float(seg.min())), max(hi, float(seg.max()))
        if not math.isfinite(lo):
            return None
        if hi - lo < 1e-12:
            pad = abs(hi) * 0.05 or 1.0
            return lo - pad, hi + pad
        pad = (hi - lo) * 0.08
        return lo - pad, hi + pad

    @staticmethod
    def _y(v: float, rng: tuple[float, float], r: QRectF) -> float:
        lo, hi = rng
        return r.bottom() - (v - lo) / (hi - lo) * r.height()

    # ---- mouse ----------------------------------------------------------------------
    def wheelEvent(self, e) -> None:
        if self.window():
            self.zoom(0.8 if e.angleDelta().y() > 0 else 1.25, self._t(e.position().x()))

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.window():
            self._drag = (e.position().x(), self.window())
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        x = e.position().x()
        if self._drag:
            x0, (a, b) = self._drag
            dt = (x - x0) / max(1.0, self._panels()[MAIN].width()) * (b - a)
            self.set_view((a - dt, b - dt))
        if self.window() and self._panels()[MAIN].left() <= x <= self._panels()[MAIN].right():
            self._hover = self._t(x)
            m = self._marker_near(e.position())
            if m is not None and m.text:
                QToolTip.showText(e.globalPosition().toPoint(), m.text, self)
            else:
                QToolTip.hideText()
        else:
            self._hover = None
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, e) -> None:
        self.set_view(None)

    def _marker_points(self) -> list[tuple[QPointF, ChartMarker]]:
        main = [s for s in self.series if s.panel == MAIN and s.axis == LEFT]
        if not main or not self.markers:
            return []
        r = self._panels()[MAIN]
        rng = self._range(MAIN, LEFT)
        a, b = self.window()
        out = []
        for m in self.markers:
            t = _secs(m.time)
            v = main[0].at(t)
            if v is None or not (a <= t <= b):
                continue
            out.append((QPointF(self._x(t, r), self._y(v, rng, r)), m))
        return out

    def _marker_near(self, pos: QPointF, radius: float = 6.0) -> ChartMarker | None:
        best = None
        for pt, m in self._marker_points():
            d = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
            if d <= radius and (best is None or d < best[0]):
                best = (d, m)
        return best[1] if best else None

    # ---- drawing --------------------------------------------------------------------
    def _color(self, s: ChartSeries, i: int):
        pal = theme.current()
        if s.dashed:
            return theme.qcolor(pal.text_muted)
        idx = s.color if s.color is not None else i
        return theme.qcolor(pal.series[idx % len(pal.series)])

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # the canvas backdrop
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.current()
        if not self.series:
            p.setPen(theme.qcolor(pal.text_muted))
            p.setFont(theme.ui_font(T.TYPE.body))
            p.drawText(self.rect(), Qt.AlignCenter, self.empty_text)
            p.end()
            return
        panels = self._panels()
        mono = theme.mono_font(T.TYPE.caption)
        p.setFont(mono)
        grid = QPen(theme.qcolor(pal.border), 1)
        faint = theme.qcolor(pal.text_faint)
        muted = theme.qcolor(pal.text_muted)

        ranges: dict[tuple[str, str], tuple[float, float]] = {}
        for name, r in panels.items():
            for axis in (LEFT, RIGHT):
                rng = self._range(name, axis)
                if rng is None:
                    continue
                ranges[(name, axis)] = rng
                fmt = self.formats[RIGHT if axis == RIGHT else name]
                ticks = nice_ticks(rng[0], rng[1], 5 if name == MAIN else 2)
                for v in ticks:
                    y = self._y(v, rng, r)
                    if axis == LEFT:
                        p.setPen(grid)
                        p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                        p.setPen(faint)
                        p.drawText(QRectF(0, y - 8, r.left() - 8, 16), Qt.AlignRight | Qt.AlignVCenter, fmt(v))
                    else:
                        p.setPen(faint)
                        p.drawText(QRectF(r.right() + 8, y - 8, 60, 16), Qt.AlignLeft | Qt.AlignVCenter, fmt(v))
            p.setPen(grid)
            p.drawLine(r.bottomLeft(), r.bottomRight())

        # time axis
        a, b = self.window()
        main = panels[MAIN]
        bottom = max(r.bottom() for r in panels.values())
        for t, text in time_ticks(a, b, self.tz, max(2, int(main.width() // 90))):
            x = self._x(t, main)
            p.setPen(QPen(theme.qcolor(pal.border, 0.5), 1, Qt.DotLine))
            for r in panels.values():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(faint)
            p.drawText(QRectF(x - 45, bottom + 4, 90, 16), Qt.AlignHCenter | Qt.AlignTop, text)

        # series
        colors = {}
        for i, s in enumerate(self.series):
            colors[id(s)] = c = self._color(s, i)
            rng = ranges.get((s.panel, s.axis))
            if rng is None:
                continue
            r = panels[s.panel]
            i0 = max(0, int(np.searchsorted(s.t, a, "right")) - 1)
            i1 = min(len(s.t), int(np.searchsorted(s.t, b, "right")) + 1)
            if i1 - i0 < 1:
                continue
            xs = r.left() + (s.t[i0:i1] - a) / max(1e-9, b - a) * r.width()
            ys = r.bottom() - (s.v[i0:i1] - rng[0]) / (rng[1] - rng[0]) * r.height()
            path = QPainterPath(QPointF(xs[0], ys[0]))
            for x, y in zip(xs[1:], ys[1:]):
                path.lineTo(x, y)
            pen = QPen(c, 1.3 if s.dashed or s.panel == SUB else 1.7)
            if s.dashed:
                pen.setStyle(Qt.DashLine)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.save()
            p.setClipRect(r.adjusted(-2, -2, 2, 2))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.restore()

        # trade dots
        for pt, m in self._marker_points():
            p.setPen(QPen(theme.qcolor(pal.surface), 1.2))
            p.setBrush(theme.qcolor(pal.success if m.side > 0 else pal.danger))
            p.drawEllipse(pt, 3.6, 3.6)

        # crosshair and readout
        at = self._hover if self._hover is not None else b
        if self._hover is not None:
            x = self._x(self._hover, main)
            p.setPen(QPen(muted, 1, Qt.DashLine))
            for r in panels.values():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            for s in self.series:
                rng = ranges.get((s.panel, s.axis))
                v = s.at(self._hover)
                if rng is None or v is None:
                    continue
                p.setPen(QPen(theme.qcolor(pal.surface), 1.5))
                p.setBrush(colors[id(s)])
                p.drawEllipse(QPointF(x, self._y(v, rng, panels[s.panel])), 3.2, 3.2)
        self._readout(p, at, colors, mono)
        p.end()

    def _readout(self, p: QPainter, at: float, colors: dict, mono) -> None:
        """The legend row above the plot: the time and every series' value there."""
        pal = theme.current()
        x = float(self.L)
        y = 8.0
        p.setFont(mono)
        stamp = datetime.fromtimestamp(at, self.tz).strftime("%Y-%m-%d %H:%M")
        p.setPen(theme.qcolor(pal.text_muted))
        p.drawText(QRectF(x, y, 140, 16), Qt.AlignLeft | Qt.AlignVCenter, stamp)
        x += p.fontMetrics().horizontalAdvance(stamp) + 18
        ui = theme.ui_font(T.TYPE.caption)
        for s in self.series[:8]:
            v = s.at(at)
            fmt = self.formats[RIGHT if s.axis == RIGHT else s.panel]
            text = f"{s.name}  {fmt(v) if v is not None else '–'}"
            p.setPen(Qt.NoPen)
            p.setBrush(colors[id(s)])
            p.drawRoundedRect(QRectF(x, y + 5, 8, 6 if not s.dashed else 2), 1, 1)
            p.setFont(ui)
            p.setPen(theme.qcolor(pal.text))
            w = p.fontMetrics().horizontalAdvance(text)
            if x + 12 + w > self.width() - 8:
                break
            p.drawText(QRectF(x + 12, y, w + 4, 16), Qt.AlignLeft | Qt.AlignVCenter, text)
            x += 12 + w + 16
