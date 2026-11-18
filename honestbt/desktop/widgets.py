"""Custom Qt widgets: patch-bay graph and equity chart (drawn with QPainter)."""
from __future__ import annotations

import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QPlainTextEdit, QToolTip, QWidget

from .help import explain

_WORD = re.compile(r"[\w$.\-]")


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.Window).lightness() < 128


class HoverEditor(QPlainTextEdit):
    """Settings editor that explains the word under the mouse (tooltip and the help line)."""

    hovered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.cfg: dict = {}
        self._last = None

    def word_at(self, pos) -> str:
        cur = self.cursorForPosition(pos)
        text, i = cur.block().text(), cur.positionInBlock()
        if not text or i > len(text):
            return ""
        a = b = i
        while a > 0 and _WORD.match(text[a - 1]):
            a -= 1
        while b < len(text) and _WORD.match(text[b]):
            b += 1
        return text[a:b]

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        word = self.word_at(e.position().toPoint())
        if word == self._last:
            return
        self._last = word
        tip = explain(word, self.cfg)
        if tip:
            QToolTip.showText(e.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()
        self.hovered.emit(tip or "")

    def leaveEvent(self, e):
        self._last = None
        self.hovered.emit("")
        super().leaveEvent(e)

    def select_key(self, key: str) -> bool:
        """Put the cursor on the first `"key":` in the text and scroll to it."""
        doc = self.document()
        found = doc.find(f'"{key}"')
        if found.isNull():
            return False
        self.setTextCursor(found)
        self.centerCursor()
        self.setFocus()
        return True


class EquityChart(QWidget):
    """Line chart of one or more equity curves (growth of 1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[tuple[str, list[float], QColor]] = []
        self.setMinimumHeight(220)

    def set_series(self, series):
        self.series = series
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        muted = QColor("#9a9a94" if dark else "#6b6b66")
        grid = QColor("#34342f" if dark else "#deded8")
        W, H = self.width(), self.height()
        vals = [v for _, s, _ in self.series for v in s]
        if not vals:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, "Run a configuration to see the equity curve")
            return
        lo, hi = min(vals + [1.0]), max(vals + [1.0])
        if math.isclose(lo, hi):
            hi = lo + 1e-6
        left, right, top_, bottom = 48, 10, 24, 20
        n = max(len(s) for _, s, _ in self.series)
        X = lambda i: left + i / max(1, n - 1) * (W - left - right)
        Y = lambda v: top_ + (hi - v) / (hi - lo) * (H - top_ - bottom)
        p.setPen(QPen(grid, 1))
        p.drawLine(QPointF(left, Y(1.0)), QPointF(W - right, Y(1.0)))
        p.setPen(muted)
        p.drawText(QRectF(0, Y(hi) - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{hi:.2f}")
        p.drawText(QRectF(0, Y(lo) - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{lo:.2f}")
        p.drawText(QRectF(0, Y(1.0) - 8, left - 6, 16), Qt.AlignRight | Qt.AlignVCenter, "1.00")
        for k, (label, s, color) in enumerate(self.series):
            path = QPainterPath(QPointF(X(0), Y(s[0])))
            for i, v in enumerate(s[1:], 1):
                path.lineTo(X(i), Y(v))
            p.setPen(QPen(color, 2))
            p.drawPath(path)
            p.drawText(QPointF(left + 8 + k * 140, 14), label)
        p.end()
