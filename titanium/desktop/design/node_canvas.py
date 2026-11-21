"""A node editor for the kit: boxes with ports and inline knobs, joined by cables.

It knows nothing about strategies. A page fills it with :class:`NodeSpec`
values (``NodeCanvasScene.set_nodes``) and listens to what the user asks for:
a cable dropped on an input, nodes moved, a knob turned, a right-click. The page
decides whether to allow each request and redraws from its model, so the model
stays the only source of truth.

Look: nodes are layered panels (the skin's panel gradient and top highlight),
ports are small rings, cables are thin and quiet, and selection uses the
``primary`` colour, which marks selection only. The backdrop is the skin's
canvas pattern, drawn in scene space so it pans and zooms with the nodes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QStyleOptionGraphicsItem,
)

from . import theme
from . import tokens as T

WIDTH = 224.0
HEAD = 44.0
PORT_ROW = 24.0
KNOB_ROW = 30.0
PAD = 12.0
PORT_R = 5.0
HIT = 11.0  # how close (in scene units) a press must be to a port
MIN_ZOOM, MAX_ZOOM = 0.3, 2.5


def paint_backdrop(p: QPainter, rect: QRectF, step: float = 16.0, scale: float = 1.0) -> None:
    """The skin's canvas pattern (dots or ruled lines) over ``rect``, aligned to a ``step`` grid."""
    kind = theme.effects().canvas
    if kind == "none":
        return
    pal = theme.current()
    if scale < 0.6:  # keep the pattern from turning into a grey wash when zoomed out
        step *= 2
    x0 = int(rect.left() // step) * step
    y0 = int(rect.top() // step) * step
    if kind == "dots":
        pen = QPen(theme.qcolor(pal.border_strong, 0.55), 1.4 / max(scale, 0.01), Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        pts, y = [], y0
        while y < rect.bottom():
            x = x0
            while x < rect.right():
                pts.append(QPointF(x, y))
                x += step
            y += step
        p.drawPoints(pts)
    else:
        p.setPen(QPen(theme.qcolor(pal.border, 0.8), 1 / max(scale, 0.01)))
        y = int(rect.top() // (2 * step)) * 2 * step
        while y < rect.bottom():
            p.drawLine(QLineF(rect.left(), y, rect.right(), y))
            y += 2 * step


def cable_path(a: QPointF, b: QPointF) -> QPainterPath:
    """A cable from an output at ``a`` to an input at ``b``: leaves to the right, arrives from the left."""
    dx = max(48.0, abs(b.x() - a.x()) / 2)
    path = QPainterPath(a)
    path.cubicTo(a.x() + dx, a.y(), b.x() - dx, b.y(), b.x(), b.y())
    return path


@dataclass
class KnobSpec:
    key: str  # what the page calls it ("module.knob")
    name: str
    kind: str  # "real", "int" or "bool"
    value: Any
    lo: float | None = None
    hi: float | None = None
    step: float | None = None
    doc: str = ""


@dataclass
class NodeSpec:
    id: str
    title: str
    overline: str = ""  # small caps above the title (the module's kind)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    plugged: set[str] = field(default_factory=set)  # input names with a cable in
    knobs: list[KnobSpec] = field(default_factory=list)
    pos: tuple[float, float] = (0.0, 0.0)
    tip: str = ""
    note: str = ""  # a short caption under the title (e.g. where it came from)


def node_size(spec: NodeSpec) -> tuple[float, float]:
    rows = max(len(spec.inputs), len(spec.outputs))
    h = HEAD + (rows * PORT_ROW + PAD / 2 if rows else 0) + (len(spec.knobs) * KNOB_ROW + PAD / 2 if spec.knobs else 0)
    return WIDTH, max(h + PAD / 2, HEAD + PAD)


def show_value(v) -> str:
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, int):
        return str(v)
    try:
        return f"{float(v):.4g}"
    except (TypeError, ValueError):
        return str(v)


class NodeItem(QGraphicsObject):
    """One box. Inputs on the left, outputs on the right, knobs below as small sliders and switches."""

    def __init__(self, spec: NodeSpec):
        super().__init__()
        self.spec = spec
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setPos(*spec.pos)
        self.setToolTip(spec.tip)
        self.setZValue(1)
        self._w, self._h = node_size(spec)
        self.highlight: dict[str, str] = {}  # input name -> "ok" / "bad" while a cable is dragged
        self._knob_drag: KnobSpec | None = None
        self._hover_port: str | None = None

    # ---- geometry
    def boundingRect(self) -> QRectF:
        return QRectF(-PORT_R - 2, -2, self._w + 2 * PORT_R + 4, self._h + 4)

    def body(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def _port_y(self, i: int) -> float:
        return HEAD + PAD / 4 + i * PORT_ROW + PORT_ROW / 2

    def input_pos(self, name: str) -> QPointF:
        """Where an input's port is, in scene coordinates."""
        i = self.spec.inputs.index(name)
        return self.mapToScene(QPointF(0, self._port_y(i)))

    def output_pos(self, name: str) -> QPointF:
        i = self.spec.outputs.index(name)
        return self.mapToScene(QPointF(self._w, self._port_y(i)))

    def _knobs_top(self) -> float:
        rows = max(len(self.spec.inputs), len(self.spec.outputs))
        return HEAD + (rows * PORT_ROW + PAD / 2 if rows else 0)

    def knob_rect(self, i: int) -> QRectF:
        return QRectF(PAD, self._knobs_top() + i * KNOB_ROW, self._w - 2 * PAD, KNOB_ROW)

    def _track(self, i: int) -> QRectF:
        r = self.knob_rect(i)
        return QRectF(r.left(), r.top() + 21, r.width(), 4)

    def port_at(self, scene_pt: QPointF, loose: bool = False) -> tuple[str, str] | None:
        """("in" | "out", name) of the port at a scene point. ``loose``: anywhere on an input's row counts."""
        pt = self.mapFromScene(scene_pt)
        for i, name in enumerate(self.spec.outputs):
            if QLineF(pt, QPointF(self._w, self._port_y(i))).length() <= HIT:
                return "out", name
        for i, name in enumerate(self.spec.inputs):
            y = self._port_y(i)
            if QLineF(pt, QPointF(0, y)).length() <= HIT:
                return "in", name
            if loose and 0 <= pt.x() <= self._w * 0.6 and abs(pt.y() - y) <= PORT_ROW / 2:
                return "in", name
        if loose and self.spec.inputs and self.body().contains(pt) and pt.y() < HEAD:
            free = [n for n in self.spec.inputs if n not in self.spec.plugged]
            return "in", (free or self.spec.inputs)[0]
        return None

    def knob_at(self, scene_pt: QPointF) -> int | None:
        pt = self.mapFromScene(scene_pt)
        for i in range(len(self.spec.knobs)):
            if self.knob_rect(i).contains(pt):
                return i
        return None

    # ---- painting
    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        pal, fx = theme.current(), theme.effects()
        p.setRenderHint(QPainter.Antialiasing)
        body = self.body()
        rad = theme.radius("lg")
        if fx.panel_gradient:
            g = QLinearGradient(body.topLeft(), body.bottomLeft())
            g.setColorAt(0, theme.qcolor(pal.surface_top))
            g.setColorAt(1, theme.qcolor(pal.surface))
            brush = QBrush(g)
        else:
            brush = QBrush(theme.qcolor(pal.surface))
        sel = self.isSelected()
        p.setPen(QPen(theme.qcolor(pal.primary if sel else pal.border_strong), 1.6 if sel else 1.0))
        p.setBrush(brush)
        p.drawRoundedRect(body, rad, rad)
        if fx.top_highlight:
            p.setPen(QPen(theme.qcolor(pal.highlight), 1))
            p.drawLine(QLineF(body.left() + rad, body.top() + 1, body.right() - rad, body.top() + 1))

        # head: overline, title, note
        x = PAD
        f = theme.ui_font(T.TYPE.caption - 1, QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(theme.qcolor(pal.text_faint))
        p.drawText(QRectF(x, 7, self._w - 2 * PAD, 12), Qt.AlignLeft | Qt.AlignVCenter, self.spec.overline.upper())
        if self.spec.note:
            p.drawText(QRectF(x, 7, self._w - 2 * PAD, 12), Qt.AlignRight | Qt.AlignVCenter,
                       QFontMetricsF(f).elidedText(self.spec.note, Qt.ElideLeft, self._w * 0.5))
        tf = theme.ui_font(T.TYPE.body)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(theme.qcolor(pal.text))
        p.drawText(QRectF(x, 20, self._w - 2 * PAD, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetricsF(tf).elidedText(self.spec.title, Qt.ElideRight, self._w - 2 * PAD))
        if self.spec.inputs or self.spec.outputs or self.spec.knobs:
            p.setPen(QPen(theme.qcolor(pal.border), 1))
            p.drawLine(QLineF(1, HEAD, self._w - 1, HEAD))

        # ports
        lf = theme.ui_font(T.TYPE.label)
        p.setFont(lf)
        fm = QFontMetricsF(lf)
        for i, name in enumerate(self.spec.inputs):
            y = self._port_y(i)
            p.setPen(theme.qcolor(pal.text_muted))
            p.drawText(QRectF(PAD, y - 9, self._w / 2 - PAD, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(name, Qt.ElideRight, self._w / 2 - PAD))
            self._paint_port(p, QPointF(0, y), name in self.spec.plugged, self.highlight.get(name),
                             self._hover_port == f"in:{name}")
        for i, name in enumerate(self.spec.outputs):
            y = self._port_y(i)
            p.setPen(theme.qcolor(pal.text_muted))
            p.drawText(QRectF(self._w / 2, y - 9, self._w / 2 - PAD, 18), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(name, Qt.ElideRight, self._w / 2 - PAD))
            self._paint_port(p, QPointF(self._w, y), True, None, self._hover_port == f"out:{name}")

        # knobs
        if self.spec.knobs:
            p.setPen(QPen(theme.qcolor(pal.border), 1, Qt.DotLine))
            top = self._knobs_top() - PAD / 4
            p.drawLine(QLineF(PAD, top, self._w - PAD, top))
        mf = theme.mono_font(T.TYPE.label)
        for i, k in enumerate(self.spec.knobs):
            r = self.knob_rect(i)
            p.setFont(lf)
            p.setPen(theme.qcolor(pal.text_muted))
            p.drawText(QRectF(r.left(), r.top() + 2, r.width() * 0.65, 16), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(k.name, Qt.ElideRight, r.width() * 0.65))
            p.setFont(mf)
            p.setPen(theme.qcolor(pal.text))
            if k.kind == "bool":
                self._paint_switch(p, QRectF(r.right() - 26, r.top() + 4, 26, 14), bool(k.value))
                continue
            p.drawText(QRectF(r.left() + r.width() * 0.5, r.top() + 2, r.width() * 0.5, 16),
                       Qt.AlignRight | Qt.AlignVCenter, show_value(k.value))
            self._paint_track(p, self._track(i), self._fraction(k))
        p.setPen(Qt.NoPen)

    def _paint_port(self, p: QPainter, c: QPointF, filled: bool, mark: str | None, hover: bool) -> None:
        pal = theme.current()
        ring = {"ok": pal.success, "bad": pal.danger}.get(mark or "", pal.text if hover else pal.border_strong)
        p.setPen(QPen(theme.qcolor(ring), 2.0 if (mark or hover) else 1.2))
        p.setBrush(theme.qcolor(pal.text_muted if filled else pal.surface))
        p.drawEllipse(c, PORT_R, PORT_R)

    def _paint_track(self, p: QPainter, r: QRectF, frac: float) -> None:
        """Drawn like the kit's sliders (see the QSlider rules in ``theme.stylesheet``)."""
        pal, fx = theme.current(), theme.effects()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(pal.border))
        p.drawRoundedRect(r, 2, 2)
        p.setBrush(theme.qcolor(pal.brand if fx.primary == "edge" else pal.primary))
        p.drawRoundedRect(QRectF(r.left(), r.top(), r.width() * frac, r.height()), 2, 2)
        p.setPen(QPen(theme.qcolor(pal.border_strong), 1))
        p.setBrush(theme.qcolor(pal.surface_top))
        p.drawEllipse(QPointF(r.left() + r.width() * frac, r.center().y()), 5, 5)

    def _paint_switch(self, p: QPainter, r: QRectF, on: bool) -> None:
        pal = theme.current()
        p.setPen(QPen(theme.qcolor(pal.border_strong), 1))
        p.setBrush(theme.qcolor(pal.ink if on else pal.sunken))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qcolor(pal.on_ink if on else pal.text_faint))
        d = r.height() - 4
        p.drawEllipse(QRectF(r.right() - d - 2 if on else r.left() + 2, r.top() + 2, d, d))

    @staticmethod
    def _fraction(k: KnobSpec) -> float:
        if k.lo is None or k.hi is None or k.hi == k.lo:
            return 0.5
        return max(0.0, min(1.0, (float(k.value) - k.lo) / (k.hi - k.lo)))

    def value_at(self, k: KnobSpec, i: int, scene_x: float):
        """The knob value at a horizontal position on its track."""
        tr = self._track(i)
        x = self.mapFromScene(QPointF(scene_x, 0)).x()
        frac = max(0.0, min(1.0, (x - tr.left()) / tr.width()))
        lo, hi = (k.lo if k.lo is not None else 0.0), (k.hi if k.hi is not None else 1.0)
        v = lo + frac * (hi - lo)
        if k.kind == "int":
            step = int(k.step or 1)
            return int(round((v - lo) / step) * step + lo)
        if k.step:
            v = round((v - lo) / k.step) * k.step + lo
        return float(f"{v:.6g}")

    # ---- interaction
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene() is not None:
            self.scene().node_moving(self)
        return super().itemChange(change, value)

    def hoverMoveEvent(self, e) -> None:
        hit = self.port_at(e.scenePos())
        key = f"{hit[0]}:{hit[1]}" if hit else None
        knob = self.knob_at(e.scenePos())
        self.setCursor(Qt.CrossCursor if hit else Qt.PointingHandCursor if knob is not None else Qt.OpenHandCursor)
        if key != self._hover_port:
            self._hover_port = key
            self.update()
        super().hoverMoveEvent(e)

    def hoverLeaveEvent(self, e) -> None:
        self._hover_port = None
        self.update()
        super().hoverLeaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            i = self.knob_at(e.scenePos())
            if i is not None:
                k = self.spec.knobs[i]
                if k.kind == "bool":
                    k.value = not bool(k.value)
                    self.update()
                    self.scene().knob_changed.emit(self.spec.id, k.key, k.value)
                    e.accept()
                    return
                if self._track(i).adjusted(-6, -8, 6, 6).contains(self.mapFromScene(e.scenePos())):
                    self._knob_drag = k
                    self._knob_index = i
                    self._knob_start = k.value
                    self._turn(e.scenePos().x())
                    e.accept()
                    return
        super().mousePressEvent(e)

    def _turn(self, x: float) -> None:
        k = self._knob_drag
        v = self.value_at(k, self._knob_index, x)
        if v != k.value:
            k.value = v
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._knob_drag is not None:
            self._turn(e.scenePos().x())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self._knob_drag is not None:
            k, self._knob_drag = self._knob_drag, None
            if k.value != self._knob_start:
                self.scene().knob_changed.emit(self.spec.id, k.key, k.value)
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        if self.mapFromScene(e.scenePos()).y() < HEAD:
            self.scene().node_activated.emit(self.spec.id)
            return
        super().mouseDoubleClickEvent(e)


@dataclass(frozen=True)
class CableEnds:
    src: str
    src_port: str
    dst: str
    dst_port: str


class CableItem(QGraphicsPathItem):
    def __init__(self, ends: CableEnds | None = None):
        super().__init__()
        self.ends = ends
        self.setZValue(0)
        self.dashed = False
        self.state = ""  # "ok", "bad" or "" (for the cable being dragged)
        if ends is not None:
            self.setFlags(QGraphicsItem.ItemIsSelectable)
            self.setAcceptHoverEvents(True)
            self.setToolTip(f"{ends.src}.{ends.src_port} → {ends.dst}.{ends.dst_port}. Right-click to unplug.")
        self._hover = False

    def set_points(self, a: QPointF, b: QPointF) -> None:
        self.setPath(cable_path(a, b))

    def shape(self) -> QPainterPath:
        s = QPainterPathStroker()
        s.setWidth(10)
        return s.createStroke(self.path())

    def hoverEnterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def paint(self, p: QPainter, option, widget=None) -> None:
        pal = theme.current()
        p.setRenderHint(QPainter.Antialiasing)
        if self.ends is None:  # the one being dragged
            color = {"ok": pal.success, "bad": pal.danger}.get(self.state, pal.text_muted)
            p.setPen(QPen(theme.qcolor(color), 2.0, Qt.DashLine if self.state != "ok" else Qt.SolidLine, Qt.RoundCap))
        elif self.isSelected() or self._hover:
            p.setPen(QPen(theme.qcolor(pal.primary), 2.4, Qt.SolidLine, Qt.RoundCap))
        else:
            p.setPen(QPen(theme.qcolor(pal.text_faint), 1.6, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())


class NodeCanvasScene(QGraphicsScene):
    """Holds the nodes and cables, and turns presses and drags into requests."""

    wire_dropped = Signal(object, object)  # (CableEnds new, CableEnds picked up or None)
    unplugged = Signal(object)  # (CableEnds,): a cable picked off its input and dropped on nothing
    nodes_moved = Signal(dict)  # {node id: (x, y)}
    knob_changed = Signal(str, str, object)  # (node id, knob key, value)
    node_activated = Signal(str)  # double-click on a node's title
    message = Signal(str)  # a hint for the status line

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes: dict[str, NodeItem] = {}
        self.cables: list[CableItem] = []
        self.check: Callable[[CableEnds], str | None] = lambda ends: None  # why a cable can't go there
        self._wire: dict | None = None
        self._press_pos: dict[str, QPointF] = {}
        self.setItemIndexMethod(QGraphicsScene.NoIndex)

    # ---- filling
    def set_nodes(self, specs: list[NodeSpec], links: list[CableEnds]) -> None:
        """Show these nodes and cables (selection is kept by node id)."""
        selected = {n.spec.id for n in self.nodes.values() if n.isSelected()}
        sel_cables = {c.ends for c in self.cables if c.isSelected()}
        if self._wire is not None:
            self._end_wire()
        for item in list(self.nodes.values()) + self.cables:
            self.removeItem(item)
        self.nodes, self.cables = {}, []
        for s in specs:
            n = NodeItem(s)
            self.addItem(n)
            n.setSelected(s.id in selected)
            self.nodes[s.id] = n
        for ends in links:
            if ends.src in self.nodes and ends.dst in self.nodes:
                c = CableItem(ends)
                self.addItem(c)
                c.setSelected(ends in sel_cables)
                self.cables.append(c)
        self._route()

    def _route(self, only: NodeItem | None = None) -> None:
        for c in self.cables:
            e = c.ends
            if only is not None and only.spec.id not in (e.src, e.dst):
                continue
            a, b = self.nodes[e.src], self.nodes[e.dst]
            if e.src_port in a.spec.outputs and e.dst_port in b.spec.inputs:
                c.set_points(a.output_pos(e.src_port), b.input_pos(e.dst_port))

    def node_moving(self, node: NodeItem) -> None:
        self._route(node)

    def selected_nodes(self) -> list[str]:
        return [i for i, n in self.nodes.items() if n.isSelected()]

    def selected_cables(self) -> list[CableEnds]:
        return [c.ends for c in self.cables if c.isSelected()]

    def node_at(self, pt: QPointF) -> NodeItem | None:
        for item in self.items(pt):
            if isinstance(item, NodeItem):
                return item
        return None

    def cable_at(self, pt: QPointF) -> CableItem | None:
        for item in self.items(pt):
            if isinstance(item, CableItem) and item.ends is not None:
                return item
        return None

    def _input_near(self, pt: QPointF) -> tuple[NodeItem, str] | None:
        for n in self.nodes.values():
            hit = n.port_at(pt, loose=True)
            if hit and hit[0] == "in":
                return n, hit[1]
        return None

    # ---- dragging cables
    def start_wire(self, src: str, src_port: str, picked: CableEnds | None = None) -> None:
        start = self.nodes[src].output_pos(src_port)
        temp = CableItem()
        temp.setZValue(3)
        self.addItem(temp)
        temp.set_points(start, start)
        self._wire = {"src": src, "port": src_port, "start": start, "picked": picked, "item": temp}
        if picked is not None:
            for c in self.cables:
                if c.ends == picked:
                    c.hide()
        self.message.emit("Drop the cable on an input. Drop it on empty canvas to cancel.")

    def _mark(self, ends: CableEnds | None) -> str:
        """Shows which input the cable would go into, and whether it may."""
        for n in self.nodes.values():
            if n.highlight:
                n.highlight = {}
                n.update()
        if ends is None:
            return ""
        w = self._wire
        if w["picked"] == ends:
            return "ok"
        reason = self.check(ends)
        n = self.nodes[ends.dst]
        n.highlight = {ends.dst_port: "bad" if reason else "ok"}
        n.update()
        return "bad" if reason else "ok"

    def _wire_target(self, pt: QPointF) -> CableEnds | None:
        hit = self._input_near(pt)
        if hit is None:
            return None
        return CableEnds(self._wire["src"], self._wire["port"], hit[0].spec.id, hit[1])

    def _end_wire(self) -> None:
        w, self._wire = self._wire, None
        self.removeItem(w["item"])
        self._mark(None)
        for c in self.cables:
            c.show()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            node = self.node_at(e.scenePos())
            hit = node.port_at(e.scenePos()) if node is not None else None
            if hit is not None:
                side, port = hit
                if side == "out":
                    self.start_wire(node.spec.id, port)
                    e.accept()
                    return
                plugged = next((c.ends for c in self.cables if c.ends.dst == node.spec.id and c.ends.dst_port == port), None)
                if plugged is not None:  # pick the cable up off this input
                    self.start_wire(plugged.src, plugged.src_port, plugged)
                    e.accept()
                    return
        super().mousePressEvent(e)
        self._press_pos = {i: n.pos() for i, n in self.nodes.items()}

    def mouseMoveEvent(self, e) -> None:
        if self._wire is not None:
            target = self._wire_target(e.scenePos())
            state = self._mark(target)
            item = self._wire["item"]
            item.state = state
            end = self.nodes[target.dst].input_pos(target.dst_port) if target is not None else e.scenePos()
            item.set_points(self._wire["start"], end)
            if state == "bad":
                self.message.emit(self.check(target) or "")
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self._wire is not None:
            target = self._wire_target(e.scenePos())
            picked = self._wire["picked"]
            self._end_wire()
            if target is not None:
                if target != picked:
                    self.wire_dropped.emit(target, picked)
            elif picked is not None:
                self.unplugged.emit(picked)
            else:
                self.message.emit("")
            return
        super().mouseReleaseEvent(e)
        moved = {i: (n.pos().x(), n.pos().y()) for i, n in self.nodes.items()
                 if i in self._press_pos and n.pos() != self._press_pos[i]}
        self._press_pos = {}
        if moved:
            self.nodes_moved.emit(moved)

    def items_rect(self) -> QRectF:
        r = QRectF()
        for n in self.nodes.values():
            r = r.united(n.sceneBoundingRect())
        return r


class NodeCanvasView(QGraphicsView):
    """Shows a :class:`NodeCanvasScene` on the skin's backdrop: wheel to zoom at the cursor,
    middle-drag (or Space and drag) to pan, drag on empty canvas to select a group."""

    zoomed = Signal(float)
    context_menu = Signal(object, QPointF, object)  # (item under the cursor or None, scene point, global QPoint)
    dropped = Signal(str, QPointF)  # (dragged text of ``accept_mime``, scene point)

    accept_mime = ""
    empty_text = ""  # shown in the middle while there are no nodes

    def __init__(self, scene: NodeCanvasScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setFrameShape(QFrame.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.setSceneRect(QRectF(-5000, -5000, 10000, 10000))
        self._pan: QPointF | None = None
        self._space = False
        theme.watch(self, lambda v: (v.viewport().update(), v.scene().update()))

    def zoom(self) -> float:
        return self.transform().m11()

    def set_zoom(self, z: float, anchor: QPointF | None = None) -> None:
        z = max(MIN_ZOOM, min(MAX_ZOOM, z))
        f = z / self.zoom()
        if anchor is None:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.scale(f, f)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.zoomed.emit(self.zoom())

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.zoom() * factor)

    def fit(self) -> None:
        """Show every node (no closer than 100%)."""
        r = self.scene().items_rect()
        if r.isNull():
            self.resetTransform()
            self.centerOn(0, 0)
        else:
            r = r.adjusted(-48, -48, 48, 48)
            self.fitInView(r, Qt.KeepAspectRatio)
            if self.zoom() > 1.0:
                self.set_zoom(1.0)
            self.centerOn(r.center())
        self.zoomed.emit(self.zoom())

    def drawBackground(self, p: QPainter, rect: QRectF) -> None:
        pal = theme.current()
        p.fillRect(rect, theme.qcolor(pal.sunken if theme.effects().canvas != "none" else pal.surface))
        p.setRenderHint(QPainter.Antialiasing)
        paint_backdrop(p, rect, 16.0, self.zoom())

    def drawForeground(self, p: QPainter, rect: QRectF) -> None:
        if self.empty_text and not self.scene().nodes:
            p.save()
            p.resetTransform()
            pal = theme.current()
            p.setFont(theme.ui_font(T.TYPE.body))
            p.setPen(theme.qcolor(pal.text_muted))
            r = QRectF(self.viewport().rect()).adjusted(48, 0, -48, 0)
            p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, self.empty_text)
            p.restore()

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.ShiftModifier:  # shift + wheel pans sideways
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - e.angleDelta().y())
            return
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self.zoom() * (1.15 ** steps), e.position())

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.viewport().unsetCursor()
            return
        super().keyReleaseEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space):
            self._pan = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self._pan is not None:
            self._pan = None
            self.viewport().unsetCursor()
            return
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e) -> None:
        pt = self.mapToScene(e.pos())
        sc: NodeCanvasScene = self.scene()
        item = sc.node_at(pt) or sc.cable_at(pt)
        if isinstance(item, NodeItem) and not item.isSelected():
            sc.clearSelection()
            item.setSelected(True)
        self.context_menu.emit(item, pt, e.globalPos())

    # ---- drops from a library
    def _accepts(self, e) -> bool:
        return bool(self.accept_mime) and e.mimeData().hasFormat(self.accept_mime)

    def dragEnterEvent(self, e) -> None:
        if self._accepts(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        if self._accepts(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if self._accepts(e):
            text = bytes(e.mimeData().data(self.accept_mime)).decode("utf-8")
            self.dropped.emit(text, self.mapToScene(e.position().toPoint()))
            e.acceptProposedAction()
        else:
            super().dropEvent(e)
