"""Custom Qt widgets: patch-bay graph and equity chart (drawn with QPainter)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.Window).lightness() < 128


class PatchBayView(QWidget):
    """Draws features -> mappings -> strategy, with a cable for every reference."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: dict = {}
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_config(self, cfg: dict) -> None:
        self.cfg = cfg or {}
        self.update()

    @staticmethod
    def _refs(obj, out):
        if isinstance(obj, dict):
            if set(obj) == {"$map"}:
                out.append(("m", obj["$map"]))
            elif set(obj) == {"$feature"}:
                out.append(("f", obj["$feature"]))
            else:
                for k, v in obj.items():
                    if k == "atr_feature" and isinstance(v, str):
                        out.append(("f", v))
                    else:
                        PatchBayView._refs(v, out)
        elif isinstance(obj, list):
            for v in obj:
                PatchBayView._refs(v, out)
        return out

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        ink = QColor("#ecece8" if dark else "#1d1d1b")
        line = QColor("#6b6b66" if dark else "#9a9a94")
        fills = {"f": QColor("#1f2a44" if dark else "#e8f0ff"),
                 "m": QColor("#3a2f17" if dark else "#fff3dc"),
                 "s": QColor("#183324" if dark else "#e9f7ee")}
        W, H = self.width(), self.height()
        feats = list((self.cfg.get("features") or {}).keys())
        maps = list((self.cfg.get("mappings") or {}).keys())
        strat = self.cfg.get("strategy") or {}
        sp = strat.get("params") or {}
        bw, bh = min(170, W * 0.28), 26
        cols = [12, W * 0.36, W - bw - 12]
        pos = {}
        for col, names, key in ((0, feats, "f"), (1, maps, "m")):
            gap = H / (len(names) + 1) if names else H
            for i, n in enumerate(names):
                pos[(key, n)] = QRectF(cols[col], gap * (i + 1) - bh / 2, bw, bh)
        srect = QRectF(cols[2], H / 2 - 48, bw, 96)

        def cable(a: QRectF, b: QRectF):
            path = QPainterPath(QPointF(a.right(), a.center().y()))
            x1, y1, x2, y2 = a.right(), a.center().y(), b.left(), b.center().y()
            path.cubicTo(x1 + 50, y1, x2 - 50, y2, x2, y2)
            p.drawPath(path)

        p.setPen(QPen(line, 1.4))
        p.setBrush(Qt.NoBrush)
        for m in maps:
            src = (self.cfg["mappings"][m] or {}).get("input")
            a = pos.get(("f", src)) or pos.get(("m", src))
            if a:
                cable(a, pos[("m", m)])
        named = [sp.get(k) for k in ("rank_by", "price_feature", "liquidity_feature")]
        for f in [n for n in named if n] :
            if ("f", f) in pos:
                cable(pos[("f", f)], srect)
        for kind, name in self._refs(sp, []):
            if (kind, name) in pos:
                cable(pos[(kind, name)], srect)

        p.setFont(QFont(self.font().family(), 9))
        for (kind, name), r in pos.items():
            p.setPen(QPen(line, 1))
            p.setBrush(QBrush(fills[kind]))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(ink)
            label = name if kind == "f" else f"{name} ({self.cfg['mappings'][name].get('plugin')})"
            p.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        p.setPen(QPen(line, 1))
        p.setBrush(QBrush(fills["s"]))
        p.drawRoundedRect(srect, 6, 6)
        p.setPen(ink)
        exit_ = (sp.get("exit") or {}).get("plugin", "")
        lines = [strat.get("plugin", "strategy"), f"top {sp.get('top_n', '?')} by {sp.get('rank_by', '?')}",
                 f"exit: {exit_}", f"sweep axes: {len(self.cfg.get('sweep') or {})}"]
        for i, t in enumerate(lines):
            f = p.font()
            f.setBold(i == 0)
            p.setFont(f)
            p.drawText(QRectF(srect.left() + 8, srect.top() + 6 + i * 21, bw - 12, 20), Qt.AlignVCenter, t)
        p.end()


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
