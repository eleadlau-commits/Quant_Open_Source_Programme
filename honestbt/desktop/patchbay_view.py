"""The patch bay: an interactive node editor over the JSON settings.

Boxes are features, mappings (cables), the strategy, its exit signal, the data
source and the tests. Features and mappings have an output port on the right;
mappings have an input port on the left; the strategy and exit boxes list the
settings you can plug into, one row and one input port each.

Drag a box to move it. Drag from an output port to an input port to plug one
into the other. Drag a plugged cable off its input to unplug it. Double-click a
setting to type a value. Every change becomes a new settings dict, sent out
through ``edited``; the JSON stays the single source of truth, and the box
positions are saved in it under ``patchbay_layout``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMenu,
    QSizePolicy,
    QToolTip,
    QWidget,
)

from ..patchbay import get_path
from ..registry import catalog
from . import builder
from .help import KIND_WORDS, explain, plugin_doc

MIME = "application/x-titanium-plugin"
BW, HEAD, ROW, PORT = 186, 24, 19, 6
ABBR = {"feature": "f", "mapping": "m"}


@dataclass
class Row:
    label: str
    path: str = ""          # settings path this row's input port writes to ("" = no port)
    value: str = ""
    source: tuple | None = None  # ("f"|"m", name) plugged in here
    index: int = -1         # for test rows: position in the evaluator list
    rect: QRectF = field(default_factory=QRectF)


@dataclass
class Box:
    key: str                # "f:gap", "m:k_map", "s", "x", "d", "t"
    kind: str               # f m s x d t
    name: str
    title: str
    rows: list[Row] = field(default_factory=list)
    rect: QRectF = field(default_factory=QRectF)
    in_path: str = ""       # mappings: their input port
    source: tuple | None = None

    @property
    def out_port(self) -> QPointF | None:
        return QPointF(self.rect.right(), self.rect.top() + HEAD / 2) if self.kind in "fm" else None

    @property
    def in_port(self) -> QPointF | None:
        return QPointF(self.rect.left(), self.rect.top() + HEAD / 2) if self.in_path else None


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.Window).lightness() < 128


def _short(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) >= 1e5:
        return f"{v:,.0f}" if abs(v) < 1e6 else f"{v / 1e6:g}M"
    s = json.dumps(v) if not isinstance(v, str) else v
    return s if len(s) <= 14 else s[:13] + "…"


class PatchBayView(QWidget):
    hovered = Signal(str)
    clicked = Signal(str)        # settings key to show in the editor
    edited = Signal(dict, str)   # new settings, what changed
    message = Signal(str)        # e.g. why a cable can't go somewhere

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg: dict = {}
        self.boxes: dict[str, Box] = {}
        self.nodes: list[tuple[str, str, QRectF]] = []
        self.selected: str | None = None
        self._hover = None
        self._drag = None        # ("move", key, offset, press) | ("wire", source, from_pt, unplug_path)
        self._moving: dict[str, QPointF] = {}
        self._mouse = QPointF()
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(240)

    # ------------------------------------------------------------------ model
    def set_config(self, cfg: dict) -> None:
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._moving.clear()
        self._build()
        self.update()

    def sizeHint(self):
        return QSize(560, 320)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not (self.cfg.get(builder.LAYOUT) or {}):
            self._build()

    def _slot_row(self, path: str) -> Row:
        v = get_path(self.cfg, path)
        implicit = v is None
        if implicit:  # not set: the plugin's default applies
            v = builder.slot_default(self.cfg, path)
        feats = self.cfg.get("features") or {}
        src = None
        if isinstance(v, dict) and set(v) == {"$map"}:
            src = ("m", v["$map"])
        elif isinstance(v, dict) and set(v) == {"$feature"}:
            src = ("f", v["$feature"])
        elif isinstance(v, str) and v in feats:
            src = ("f", v)
        label = path.split(".")[-1]
        value = f"← {src[1]}" if src else ("–" if v is None else f"= {_short(v)}")

        return Row(label, path, value, src)

    def _build(self):
        cfg = self.cfg
        feats = cfg.get("features") or {}
        maps = cfg.get("mappings") or {}
        strat = cfg.get("strategy") or {}
        sp = strat.get("params") or {}
        boxes: list[Box] = []
        if not isinstance(feats, dict) or not isinstance(maps, dict):
            feats, maps = {}, {}
        boxes.append(Box("d", "d", (cfg.get("data") or {}).get("plugin", "?"),
                         f"data: {(cfg.get('data') or {}).get('plugin', '?')}"))
        for n, spec in feats.items():
            boxes.append(Box(f"f:{n}", "f", n, f"{n}  ({(spec or {}).get('plugin', '?')})"))
        for n, spec in maps.items():
            spec = spec or {}
            src = spec.get("input")
            source = ("f", src) if src in feats else ("m", src) if src in maps else None
            boxes.append(Box(f"m:{n}", "m", n, f"{n}  ({spec.get('plugin', '?')})",
                             in_path=f"mappings.{n}.input", source=source))
        feat_slots, num_slots = builder.strategy_slots(cfg)
        srows = [self._slot_row(p) for p in feat_slots + num_slots if not p.startswith("strategy.params.exit.")]
        boxes.append(Box("s", "s", strat.get("plugin", ""), f"strategy: {strat.get('plugin', '?')}", srows))
        exit_ = sp.get("exit") if isinstance(sp.get("exit"), dict) else None
        if exit_:
            xrows = [self._slot_row(p) for p in feat_slots + num_slots if p.startswith("strategy.params.exit.")]
            boxes.append(Box("x", "x", exit_.get("plugin", ""), f"exit: {exit_.get('plugin', '?')}", xrows))
        evs = cfg.get("evaluators") or []
        evs = evs if isinstance(evs, list) else [evs]
        trows = [Row(f"suite: {e['$suite']}" if isinstance(e, dict) and "$suite" in e else
                     (e.get("plugin", "?") if isinstance(e, dict) else "?"), index=i) for i, e in enumerate(evs)]
        boxes.append(Box("t", "t", "tests", f"tests ({len(trows)})", trows))

        # positions: being dragged > saved in the settings > automatic columns
        saved = cfg.get(builder.LAYOUT) or {}
        W = max(self.width(), 540)
        cols = [12, max(BW + 36, W * 0.36), max(2 * BW + 54, W - BW - 14)]
        nexty = {0: 12, 1: 12, 2: 12}
        col_of = {"d": 0, "f": 0, "m": 1, "x": 2, "s": 2, "t": 2}
        for b in boxes:
            h = HEAD + len(b.rows) * ROW + (6 if b.rows else 0)
            if b.key in self._moving:
                tl = self._moving[b.key]
            elif isinstance(saved.get(b.key), list) and len(saved[b.key]) == 2:
                tl = QPointF(*saved[b.key])
            else:
                c = col_of[b.kind]
                tl = QPointF(cols[c], nexty[c])
                nexty[c] += h + (14 if b.kind in "dsx" else 10)
            b.rect = QRectF(tl.x(), tl.y(), BW, h)
            for i, r in enumerate(b.rows):
                r.rect = QRectF(b.rect.left(), b.rect.top() + HEAD + i * ROW, BW, ROW)
        self.boxes = {b.key: b for b in boxes}
        self.nodes = [({"d": "d", "s": "s"}.get(b.kind, b.kind), b.name, b.rect) for b in boxes]
        # the canvas grows to fit boxes you placed; automatic columns follow the width instead,
        # so they only ask for the narrowest width their columns need
        auto_right = 3 * BW + 54
        placed = [b.rect.right() for b in boxes if b.key in self._moving or b.key in saved]
        right = max([auto_right, *placed]) + 16
        bottom = max((b.rect.bottom() for b in boxes), default=0) + 16
        size = QSize(int(min(right, 2000)), int(max(240, min(bottom, 3000))))
        if size != self.minimumSize():
            self.setMinimumSize(size)

    # -------------------------------------------------------------- geometry
    def _src_point(self, source) -> QPointF | None:
        b = self.boxes.get(f"{source[0]}:{source[1]}") if source else None
        return b.out_port if b else None

    def in_ports(self):
        """[(path, point, box key)] for every input port."""
        out = []
        for b in self.boxes.values():
            if b.in_path:
                out.append((b.in_path, b.in_port, b.key))
            for r in b.rows:
                if r.path:
                    out.append((r.path, QPointF(r.rect.left(), r.rect.center().y()), b.key))
        return out

    def out_port_at(self, pt):
        for b in self.boxes.values():
            p = b.out_port
            if p is not None and (p - pt).manhattanLength() <= PORT + 6:
                return b
        return None

    def in_port_at(self, pt, loose=False):
        """The input under ``pt``: on its port, or (while wiring) anywhere on its row or box header."""
        for path, p, key in self.in_ports():
            if (p - pt).manhattanLength() <= PORT + 6:
                return path
        if loose:
            for b in self.boxes.values():
                for r in b.rows:
                    if r.path and r.rect.contains(pt):
                        return r.path
                if b.in_path and QRectF(b.rect.left(), b.rect.top(), BW, HEAD).contains(pt):
                    return b.in_path
        return None

    def row_at(self, pt):
        for b in self.boxes.values():
            for r in b.rows:
                if r.rect.contains(pt):
                    return b, r
        return None, None

    def box_at(self, pt):
        for b in reversed(list(self.boxes.values())):
            if b.rect.contains(pt):
                return b
        return None

    def node_at(self, pos):
        b = self.box_at(QPointF(pos))
        return ({"d": "d", "s": "s"}.get(b.kind, b.kind), b.name) if b else None

    def links(self):
        """[(source, target path)] for every plugged cable."""
        out = []
        for b in self.boxes.values():
            if b.in_path and b.source:
                out.append((b.source, b.in_path))
            for r in b.rows:
                if r.source:
                    out.append((r.source, r.path))
        return out

    # --------------------------------------------------------------- drawing
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = _is_dark(self)
        ink = QColor("#ecece8" if dark else "#1d1d1b")
        muted = QColor("#9a9a94" if dark else "#6b6b66")
        line = QColor("#6b6b66" if dark else "#9a9a94")
        accent = QColor("#2f5bd3")
        fills = {"f": QColor("#1f2a44" if dark else "#e8f0ff"), "m": QColor("#3a2f17" if dark else "#fff3dc"),
                 "s": QColor("#183324" if dark else "#e9f7ee"), "x": QColor("#2c1f33" if dark else "#f4ecfa"),
                 "d": QColor("#26262a" if dark else "#f2f2ef"), "t": QColor("#26262a" if dark else "#f2f2ef")}
        ports = {p_: k for p_, _, k in self.in_ports()}

        def cable(a: QPointF, b: QPointF, pen: QPen):
            dx = max(40.0, abs(b.x() - a.x()) / 2)
            path = QPainterPath(a)
            path.cubicTo(a.x() + dx, a.y(), b.x() - dx, b.y(), b.x(), b.y())
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        # the exit plugs into the strategy (fixed, dashed)
        if "x" in self.boxes and "s" in self.boxes:
            x, s = self.boxes["x"].rect, self.boxes["s"].rect
            p.setPen(QPen(line, 1.4, Qt.DashLine))
            if x.left() < s.right() and s.left() < x.right():  # stacked: a short link between them
                top, bot = (s, x) if s.top() < x.top() else (x, s)
                cx = (max(x.left(), s.left()) + min(x.right(), s.right())) / 2
                p.drawLine(QPointF(cx, top.bottom()), QPointF(cx, bot.top()))
            else:
                cable(QPointF(x.right(), x.top() + HEAD / 2), QPointF(s.left(), s.top() + HEAD / 2),
                      QPen(line, 1.4, Qt.DashLine))
        unplugging = self._drag[3] if self._drag and self._drag[0] == "wire" else None
        for source, path in self.links():
            if path == unplugging:
                continue
            a = self._src_point(source)
            b = next((pt for pp, pt, _ in self.in_ports() if pp == path), None)
            if a is not None and b is not None:
                hot = self._hover in (f"{source[0]}:{source[1]}", ports.get(path))
                cable(a, b, QPen(accent if hot else line, 2.2 if hot else 1.5))

        p.setFont(QFont(self.font().family(), 9))
        fm = QFontMetrics(p.font())
        if not any(b.kind == "f" for b in self.boxes.values()):
            p.setPen(muted)
            p.drawText(QRectF(12, 60, BW + 40, 80), Qt.TextWordWrap,
                       "No features yet. Right-click, or drag one in from the Plugin catalogue.")
        for b in self.boxes.values():
            sel = b.key == self.selected
            p.setPen(QPen(accent if sel else (ink if self._hover == b.key else line), 2 if sel else 1))
            p.setBrush(QBrush(fills[b.kind]))
            p.drawRoundedRect(b.rect, 6, 6)
            f = p.font()
            f.setBold(b.kind in "sxt")
            p.setFont(f)
            p.setPen(ink)
            p.drawText(QRectF(b.rect.left() + 10, b.rect.top(), BW - 20, HEAD), Qt.AlignVCenter,
                       fm.elidedText(b.title, Qt.ElideRight, BW - 20))
            f.setBold(False)
            p.setFont(f)
            if b.rows:
                p.setPen(QPen(line, 0.6))
                p.drawLine(QPointF(b.rect.left() + 4, b.rect.top() + HEAD), QPointF(b.rect.right() - 4, b.rect.top() + HEAD))
            for r in b.rows:
                value = fm.elidedText(r.value, Qt.ElideRight, int(BW * 0.45))
                vw = fm.horizontalAdvance(value)
                p.setPen(ink)
                p.drawText(r.rect.adjusted(12, 0, -(vw + 14), 0), Qt.AlignVCenter | Qt.AlignLeft,
                           fm.elidedText(r.label, Qt.ElideRight, int(BW - vw - 26)))
                p.setPen(accent if r.source else muted)
                p.drawText(r.rect.adjusted(0, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, value)
            # ports
            for pt, plugged in ([(b.in_port, b.source is not None)] if b.in_path else []) + \
                    [(QPointF(r.rect.left(), r.rect.center().y()), r.source is not None) for r in b.rows if r.path] + \
                    ([(b.out_port, True)] if b.out_port is not None else []):
                p.setPen(QPen(ink, 1))
                p.setBrush(QBrush(accent if plugged else fills[b.kind]))
                p.drawEllipse(pt, PORT - 1.5, PORT - 1.5)
        # cable being dragged
        if self._drag and self._drag[0] == "wire":
            target = self.in_port_at(self._mouse, loose=True)
            ok = target is not None and builder.connect(self.cfg, self._drag[1], target)[0] is not None
            cable(self._drag[2], self._mouse, QPen(QColor("#1f8a4c") if ok else accent, 2, Qt.DashLine if not ok else Qt.SolidLine))
        p.end()

    # ----------------------------------------------------------- interaction
    def describe(self, node) -> str:
        if node is None:
            return ("Patch bay: drag boxes to move them, drag from a ● output to a setting to plug it in, "
                    "drag a cable off to unplug, double-click a setting to type a value, right-click for more.")
        kind, name = node
        if kind == "s":
            return f"Strategy '{name}': {plugin_doc('strategy', name)} Its rows are settings you can plug cables into."
        if kind == "d":
            return f"Data '{name}': {plugin_doc('data', name)} Right-click to change the data source."
        if kind == "x":
            return f"Exit signal '{name}': {plugin_doc('signal', name)} Plug mappings into its settings."
        if kind == "t":
            return "Tests the best variant must survive. Right-click to add or remove tests."
        what = explain(name, self.cfg) or name
        return what + " Drag its ● output onto a setting to plug it in."

    def _hover_text(self, pt) -> tuple[str | None, str]:
        b, r = self.row_at(pt)
        if r is not None:
            if b.kind == "t":
                return b.key, (explain(r.label.replace("suite: ", ""), self.cfg) or r.label) + " Right-click to remove."
            tip = explain(r.label, self.cfg) or r.label
            how = (f" Plugged into '{r.source[1]}'; drag the cable off to unplug." if r.source else
                   " Drop a cable on it, or double-click to type a value.")
            return f"{b.key}", tip + how
        ob = self.out_port_at(pt)
        if ob is not None:
            return ob.key, f"Output of '{ob.name}'. Drag from here onto a setting or a mapping's input."
        b = self.box_at(pt)
        if b is None:
            return None, self.describe(None)
        return b.key, self.describe(({"d": "d", "s": "s"}.get(b.kind, b.kind), b.name))

    def mousePressEvent(self, e):
        pt = e.position()
        self._mouse = pt
        if e.button() != Qt.LeftButton:
            return
        ob = self.out_port_at(pt)
        if ob is not None:
            self._drag = ("wire", (ob.kind, ob.name), ob.out_port, None)
            return
        path = self.in_port_at(pt)
        if path:
            src = next((s for s, pp in self.links() if pp == path), None)
            a = self._src_point(src)
            if src and a is not None:  # pick the cable up off its input
                self._drag = ("wire", src, a, path)
                self.update()
            return
        b = self.box_at(pt)
        if b is not None:
            self._drag = ("move", b.key, pt - b.rect.topLeft(), pt)
            self.selected = b.key
            self.setFocus()
            self.update()
        else:
            self.selected = None
            self.update()

    def mouseMoveEvent(self, e):
        pt = e.position()
        self._mouse = pt
        if self._drag and self._drag[0] == "move":
            _, key, off, press = self._drag
            if key in self._moving or (pt - press).manhattanLength() >= QApplication.startDragDistance():
                if not self._moving:  # freeze every box where it is, so only this one moves
                    self._moving = {k: b.rect.topLeft() for k, b in self.boxes.items()}
                self._moving[key] = QPointF(max(0.0, pt.x() - off.x()), max(0.0, pt.y() - off.y()))
                self._build()
            self.update()
            return
        if self._drag and self._drag[0] == "wire":
            self.update()
            return
        key, text = self._hover_text(pt)
        on_port = self.out_port_at(pt) is not None or self.in_port_at(pt) is not None
        self.setCursor(Qt.CrossCursor if on_port else Qt.PointingHandCursor if key else Qt.ArrowCursor)
        if key != self._hover or text != getattr(self, "_last_text", None):
            self._hover, self._last_text = key, text
            QToolTip.showText(e.globalPosition().toPoint(), text, self) if key else QToolTip.hideText()
            self.hovered.emit(text)
            self.update()

    def mouseReleaseEvent(self, e):
        drag, self._drag = self._drag, None
        pt = e.position()
        if not drag:
            return
        if drag[0] == "move":
            key = drag[1]
            if self._moving:
                positions = {k: [v.x(), v.y()] for k, v in self._moving.items()}
                self._moving = {}
                self.edited.emit(builder.set_positions(self.cfg, positions), "")
            else:  # a click: show its settings
                b = self.boxes.get(key)
                if b is not None:
                    self.clicked.emit({"s": "strategy", "d": "data", "x": "exit", "t": "evaluators"}.get(b.kind, b.name))
            return
        _, source, _, unplug_path = drag
        target = self.in_port_at(pt, loose=True)
        cfg = self.cfg
        if unplug_path and target == unplug_path:
            self.update()
            return
        if unplug_path:
            cfg = builder.unplug(cfg, unplug_path)
        if target:
            new, msg = builder.connect(cfg, source, target)
            if new is not None:
                self.edited.emit(new, msg)
                return
            self.message.emit(msg)
        if unplug_path:
            self.edited.emit(cfg, f"Unplugged {unplug_path.replace('strategy.params.', '')}.")
        self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.hovered.emit("")
        self.update()

    def mouseDoubleClickEvent(self, e):
        _, r = self.row_at(e.position())
        if r is not None and r.path:
            self.edit_value(r.path)

    def edit_value(self, path: str):
        current = get_path(self.cfg, path)
        text, ok = QInputDialog.getText(self, "Edit setting", f"{path.replace('strategy.params.', '')}\n"
                                        f"{explain(path.split('.')[-1], self.cfg) or ''}",
                                        text=json.dumps(current) if not isinstance(current, str) else current)
        if not ok:
            return
        try:
            value = json.loads(text)
        except ValueError:
            value = text
        self.edited.emit(builder.wire(self.cfg, path, value), f"{path} = {value!r}")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected and self.selected[:2] in ("f:", "m:"):
            kind = "feature" if self.selected[0] == "f" else "mapping"
            name = self.selected[2:]
            self.selected = None
            self.edited.emit(builder.remove(self.cfg, kind, name), f"Removed '{name}'.")
            return
        super().keyPressEvent(e)

    # ---------------------------------------------------- menus and dropping
    def _emit(self, cfg, what):
        self.edited.emit(cfg, what)

    def _plugin_menu(self, menu: QMenu, title: str, kind: str):
        sub = menu.addMenu(title)
        sub.setToolTipsVisible(True)
        for it in catalog().get(kind, []):
            if it["name"].startswith("_"):
                continue
            act = sub.addAction(it["name"])
            act.setToolTip(it["doc"])
            act.triggered.connect(lambda _=False, k=kind, n=it["name"]: self._emit(*self._added(k, n)))
        return sub

    def _added(self, kind, name, at: QPointF | None = None):
        cfg, where = builder.add(self.cfg, kind, name)
        if at is not None and kind in ABBR:
            cfg = builder.set_positions(cfg, {**{k: [b.rect.left(), b.rect.top()] for k, b in self.boxes.items()},
                                              f"{ABBR[kind]}:{where.split('.')[-1]}": [at.x(), at.y()]})
        return cfg, f"Added {KIND_WORDS[kind].lower()} '{name}' at {where}"

    def build_menu(self, node, pt: QPointF | None = None) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        b, r = self.row_at(pt) if pt is not None else (None, None)
        if r is not None and b.kind == "t":
            menu.addAction(f"Remove test '{r.label}'").triggered.connect(
                lambda: self._emit(builder.remove_evaluator(self.cfg, r.index), f"Removed test '{r.label}'."))
            menu.addSeparator()
        elif r is not None and r.path:
            if r.source:
                menu.addAction(f"Unplug '{r.source[1]}'").triggered.connect(
                    lambda: self._emit(builder.unplug(self.cfg, r.path), f"Unplugged {r.label}."))
            menu.addAction(f"Edit {r.label}…").triggered.connect(lambda: self.edit_value(r.path))
            menu.addAction(f"Sweep {r.label} (try several values)").triggered.connect(
                lambda: self._emit(*builder.add_sweep(self.cfg, r.path)))
            menu.addSeparator()
        feat_slots, num_slots = builder.strategy_slots(self.cfg)
        if node and node[0] in ("f", "m"):
            kind, name = node
            title = menu.addAction(f"{'Feature' if kind == 'f' else 'Mapping'} '{name}'")
            title.setEnabled(False)
            targets = (feat_slots if kind == "f" else []) + num_slots
            if targets:
                sub = menu.addMenu("Plug into")
                for path in targets:
                    label = path.replace("strategy.params.", "").replace("exit.params.", "exit ")
                    sub.addAction(label).triggered.connect(
                        lambda _=False, p=path: self._emit(*builder.connect(self.cfg, (kind, name), p)))
            if kind == "m":
                srcs = [n for n in list(self.cfg.get("features") or {}) + list(self.cfg.get("mappings") or {}) if n != name]
                if srcs:
                    sub = menu.addMenu("Take input from")
                    for src in srcs:
                        sk = "f" if src in (self.cfg.get("features") or {}) else "m"
                        sub.addAction(src).triggered.connect(
                            lambda _=False, s=src, k=sk: self._connect_or_say((k, s), f"mappings.{name}.input"))
            menu.addAction(f"Remove '{name}'  (Delete)").triggered.connect(
                lambda: self._emit(builder.remove(self.cfg, "feature" if kind == "f" else "mapping", name),
                                   f"Removed '{name}'"))
            menu.addSeparator()
        if node and node[0] in ("s", "x"):
            self._plugin_menu(menu, "Change strategy", "strategy")
            self._plugin_menu(menu, "Change exit signal", "signal")
            menu.addSeparator()
        if node and node[0] == "d":
            self._plugin_menu(menu, "Change data source", "data")
            menu.addSeparator()
        self._plugin_menu(menu, "Add feature", "feature")
        self._plugin_menu(menu, "Add mapping (cable)", "mapping")
        if not (node and node[0] in ("s", "x")):
            self._plugin_menu(menu, "Set exit signal", "signal")
        self._plugin_menu(menu, "Add test", "evaluator")
        menu.addSeparator()
        menu.addAction("Tidy layout").triggered.connect(
            lambda: self._emit(builder.clear_layout(self.cfg), "Boxes put back in columns."))
        return menu

    def _connect_or_say(self, source, target):
        new, msg = builder.connect(self.cfg, source, target)
        self.edited.emit(new, msg) if new is not None else self.message.emit(msg)

    def contextMenuEvent(self, e):
        pt = QPointF(e.pos())
        self.build_menu(self.node_at(e.pos()), pt).exec(e.globalPos())

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        kind, _, name = bytes(e.mimeData().data(MIME)).decode().partition(":")
        try:
            cfg, msg = self._added(kind, name, e.position())
        except ValueError as exc:
            self.message.emit(str(exc))
            return
        e.acceptProposedAction()
        self.edited.emit(cfg, msg)
