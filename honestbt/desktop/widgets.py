"""Custom Qt widgets: patch-bay graph and equity chart (drawn with QPainter)."""
from __future__ import annotations

import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QMenu, QPlainTextEdit, QSizePolicy, QToolTip, QWidget

from ..registry import catalog
from . import builder
from .help import KIND_WORDS, explain, plugin_doc

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


class PatchBayView(QWidget):
    """Draws features -> mappings -> strategy, with a cable for every reference.

    It is also where you build: click a box to jump to its settings, right-click to
    add features, mappings, exits and tests, or to plug one piece into another.
    Every edit is sent out as a new settings dict through ``edited``.
    """

    hovered = Signal(str)
    clicked = Signal(str)        # settings key to show in the editor
    edited = Signal(dict, str)   # new settings, what changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: dict = {}
        self.nodes: list[tuple[str, str, QRectF]] = []
        self._hover = None
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
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
        srect = QRectF(cols[2], H / 2 - 52, bw, 104)
        drect = QRectF(cols[2], 8, bw, bh)

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
        self.nodes = [(k, n, r) for (k, n), r in pos.items()]
        self.nodes += [("s", strat.get("plugin", ""), srect), ("d", (self.cfg.get("data") or {}).get("plugin", ""), drect)]
        if not feats and not maps:
            p.setPen(line)
            p.drawText(QRectF(12, 0, W * 0.6, H), Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
                       "No features yet. Right-click here to add one.")
        p.setPen(QPen(line, 1))
        p.setBrush(QBrush(fills["f"].lighter(104)))
        p.drawRoundedRect(drect, 6, 6)
        p.setPen(ink)
        p.drawText(drect.adjusted(8, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   f"data: {(self.cfg.get('data') or {}).get('plugin', '?')}")
        for (kind, name), r in pos.items():
            p.setPen(QPen(ink if self._hover == (kind, name) else line, 2 if self._hover == (kind, name) else 1))
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
        if strat.get("plugin") == "opening_range_breakout":
            filt = (f"filter: {sp.get('trend_timeframe', 15)}m EMA{sp.get('ema_fast', 50)}/{sp.get('ema_slow', 200)}"
                    if sp.get("trend_filter") else "filter: off")
            lines = [strat.get("plugin"), f"box {sp.get('box_start', '09:30')}-{sp.get('box_end', '09:45')}, "
                     f"1R/{sp.get('target_r', 3):g}R", filt,
                     f"sweep axes: {len(self.cfg.get('sweep') or {})}"]
        elif strat.get("plugin") == "weekly_topn":
            lines = [strat.get("plugin", "strategy"), f"top {sp.get('top_n', '?')} by {sp.get('rank_by', '?')}",
                     f"exit: {exit_}", f"sweep axes: {len(self.cfg.get('sweep') or {})}"]
        else:
            lines = [strat.get("plugin", "strategy"), f"exit: {exit_ or 'none'}",
                     f"sweep axes: {len(self.cfg.get('sweep') or {})}"]
        evs = self.cfg.get("evaluators") or []
        lines.append(f"tests: {len(evs) if isinstance(evs, list) else 1}" +
                     (" (+suites)" if any(isinstance(e, dict) and "$suite" in e for e in (evs if isinstance(evs, list) else [])) else ""))
        for i, t in enumerate(lines):
            f = p.font()
            f.setBold(i == 0)
            p.setFont(f)
            p.drawText(QRectF(srect.left() + 8, srect.top() + 4 + i * 19, bw - 12, 19), Qt.AlignVCenter, t)
        p.end()

    # ---- interaction
    def node_at(self, pos):
        for kind, name, r in reversed(self.nodes):
            if r.contains(QPointF(pos)):
                return kind, name
        return None

    def describe(self, node) -> str:
        if node is None:
            return "Patch bay: right-click to add features, mappings, an exit or tests; click a box to edit it."
        kind, name = node
        if kind == "s":
            return f"Strategy '{name}': {plugin_doc('strategy', name)} Click to edit its settings. Right-click to change it."
        if kind == "d":
            return f"Data '{name}': {plugin_doc('data', name)} Click to edit. Right-click to change the data source."
        what = explain(name, self.cfg) or name
        return what + " Click to edit it. Right-click to plug it in or remove it."

    def mouseMoveEvent(self, e):
        node = self.node_at(e.position().toPoint())
        if node != self._hover:
            self._hover = node
            self.setCursor(Qt.PointingHandCursor if node else Qt.ArrowCursor)
            text = self.describe(node)
            QToolTip.showText(e.globalPosition().toPoint(), text, self) if node else QToolTip.hideText()
            self.hovered.emit(text)
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.hovered.emit("")
        self.update()

    def mousePressEvent(self, e):
        node = self.node_at(e.position().toPoint())
        if node and e.button() == Qt.LeftButton:
            kind, name = node
            self.clicked.emit({"s": "strategy", "d": "data"}.get(kind, name))

    def _emit(self, cfg, what):
        self.edited.emit(cfg, what)

    def _plugin_menu(self, menu: QMenu, title: str, kind: str):
        sub = menu.addMenu(title)
        for it in catalog().get(kind, []):
            if it["name"].startswith("_"):
                continue
            act = sub.addAction(it["name"])
            act.setToolTip(it["doc"])
            act.setStatusTip(it["doc"].split("\n\n")[0])
            act.triggered.connect(lambda _=False, k=kind, n=it["name"]: self._emit(*self._added(k, n)))
        sub.setToolTipsVisible(True)
        return sub

    def _added(self, kind, name):
        cfg, where = builder.add(self.cfg, kind, name)
        return cfg, f"Added {KIND_WORDS[kind].lower()} '{name}' at {where}"

    def build_menu(self, node) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        feat_slots, num_slots = builder.strategy_slots(self.cfg)
        if node and node[0] in ("f", "m"):
            kind, name = node
            title = menu.addAction(f"{'Feature' if kind == 'f' else 'Mapping'} '{name}'")
            title.setEnabled(False)
            if kind == "f" and feat_slots:
                sub = menu.addMenu("Use for strategy setting")
                for path in feat_slots:
                    sub.addAction(path.split(".")[-1]).triggered.connect(
                        lambda _=False, p=path: self._emit(builder.wire(self.cfg, p, name), f"{p} = '{name}'"))
            if kind == "m":
                if num_slots:
                    sub = menu.addMenu("Plug into strategy setting")
                    for path in num_slots:
                        label = path.replace("strategy.params.", "").replace("exit.params.", "exit ")
                        sub.addAction(label).triggered.connect(
                            lambda _=False, p=path: self._emit(builder.wire(self.cfg, p, {"$map": name}),
                                                               f"{p} now follows mapping '{name}'"))
                srcs = [n for n in list(self.cfg.get("features") or {}) + list(self.cfg.get("mappings") or {}) if n != name]
                if srcs:
                    sub = menu.addMenu("Take input from")
                    for src in srcs:
                        sub.addAction(src).triggered.connect(
                            lambda _=False, s=src: self._emit(builder.set_input(self.cfg, name, s),
                                                              f"Mapping '{name}' now takes '{s}'"))
            menu.addAction(f"Remove '{name}'").triggered.connect(
                lambda: self._emit(builder.remove(self.cfg, "feature" if kind == "f" else "mapping", name),
                                   f"Removed '{name}'"))
            menu.addSeparator()
        if node and node[0] == "s":
            self._plugin_menu(menu, "Change strategy", "strategy")
            self._plugin_menu(menu, "Set exit signal", "signal")
            menu.addSeparator()
        if node and node[0] == "d":
            self._plugin_menu(menu, "Change data source", "data")
            menu.addSeparator()
        self._plugin_menu(menu, "Add feature", "feature")
        self._plugin_menu(menu, "Add mapping (cable)", "mapping")
        if not (node and node[0] == "s"):
            self._plugin_menu(menu, "Set exit signal", "signal")
        self._plugin_menu(menu, "Add test", "evaluator")
        return menu

    def contextMenuEvent(self, e):
        self.build_menu(self.node_at(e.pos())).exec(e.globalPos())


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
