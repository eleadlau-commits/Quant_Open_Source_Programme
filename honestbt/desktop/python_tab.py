"""A strategy written as one Python file: code editor, its modules drawn as a patch bay, and knobs.

The patch bay here is drawn from the code: the dataset feeds the Data → Data
modules (functions in the file), which feed ``decide`` (the Data → Buy/Sell
module), which feeds the trading engine. Each box lists the knobs inside it.
Put the cursor on a number and press "Make knob" to turn it into a knob you
can move in the Knobs panel.
"""
from __future__ import annotations

import keyword
import re
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QRegularExpression, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPalette, QPen, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from .. import pystrategy as ps
from ..patchbay import validate
from .strategy_tab import TabBase

MOD_COLORS = {"data": "#eef0f2", "Data → Data": "#e8eefc", "Data → Buy/Sell": "#e6f4ea", "engine": "#fdf3e1"}
MOD_COLORS_DARK = {"data": "#2d2f33", "Data → Data": "#26304a", "Data → Buy/Sell": "#233a2c", "engine": "#3d3420"}


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, doc, dark: bool = False):
        super().__init__(doc)
        self.set_dark(dark, rehighlight=False)

    def set_dark(self, dark: bool, rehighlight: bool = True):
        from .theme import code_colors
        c = code_colors(dark)

        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            f.setFontItalic(italic)
            return f
        kw = r"\b(" + "|".join(keyword.kwlist) + r")\b"
        self.rules = [(QRegularExpression(kw), fmt(c["keyword"], bold=True)),
                      (QRegularExpression(r"\bknob\b"), fmt(c["knob"], bold=True)),
                      (QRegularExpression(r"\bdef\s+\w+"), fmt(c["def"], bold=True)),
                      (QRegularExpression(r"\b\d+(\.\d+)?\b"), fmt(c["number"])),
                      (QRegularExpression(r"(\"[^\"]*\"|'[^']*')"), fmt(c["string"])),
                      (QRegularExpression(r"#[^\n]*"), fmt(c["comment"], italic=True))]
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text):
        for rx, f in self.rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), f)


class CodeEditor(QPlainTextEdit):
    hovered = Signal(str)

    def __init__(self):
        super().__init__()
        self.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = PythonHighlighter(self.document(), self.palette().color(QPalette.Base).lightness() < 128)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Tab and not e.modifiers():
            self.insertPlainText("    ")
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            line = self.textCursor().block().text()
            indent = re.match(r"\s*", line).group(0) + ("    " if line.rstrip().endswith(":") else "")
            super().keyPressEvent(e)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(e)

    def cursor_pos(self) -> tuple[int, int]:
        c = self.textCursor()
        return c.blockNumber() + 1, c.positionInBlock()

    def goto_line(self, line: int):
        block = self.document().findBlockByNumber(max(0, line - 1))
        c = QTextCursor(block)
        self.setTextCursor(c)
        self.centerCursor()
        self.setFocus()


class CodeBayView(QWidget):
    """The strategy file's modules as boxes: dataset → Data → Data → decide (Data → Buy/Sell) → trading engine."""

    clicked = Signal(int)   # line to show in the code
    hovered = Signal(str)

    def __init__(self):
        super().__init__()
        self.src, self.knob_values = "", {}
        self.boxes: list[tuple[QRectF, dict]] = []
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_source(self, src: str, knob_values: dict):
        self.src, self.knob_values = src, knob_values
        self.update()

    def _layout(self):
        try:
            st = ps.settings(self.src)
        except ps.StrategyFileError:
            st = {}
        mods = ps.modules(self.src)
        kn = {k["name"]: k for k in ps.knobs(self.src)}
        d = st.get("data") or {}
        data = {"title": f"data: {d.get('plugin', '?')}", "kind": "data", "lines": [
            f"{k} = {v}" for k, v in (d.get("params") or {}).items()][:5], "line": 1, "name": "data"}
        engine = {"title": "trading engine", "kind": "engine", "line": 1, "name": "engine", "lines": [
            f"decides {'each week' if st.get('every') == 'week' else 'each day'} at {st.get('decide_at', '15:50')}",
            "fills at the next bar's open", f"max exposure {st.get('max_gross', 1.0):g}"]}
        dd = [m for m in mods if m["kind"] == "Data → Data"]
        bs = [m for m in mods if m["kind"] == "Data → Buy/Sell"]

        def box(m):
            lines = [f"⚙ {n} = {self.knob_values.get(n, kn[n]['default'])}" for n in m["knobs"] if n in kn]
            return {"title": f"{m['name']}({', '.join(m['args'])})", "kind": m["kind"], "line": m["line"],
                    "name": m["name"], "lines": ([m["doc"]] if m["doc"] else []) + lines, "calls": m["calls"]}
        return data, [box(m) for m in dd], [box(m) for m in bs], engine

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = self.palette().color(QPalette.Window).lightness() < 128
        fills = MOD_COLORS_DARK if dark else MOD_COLORS
        text = self.palette().color(QPalette.WindowText)
        muted = QColor("#9a9a94" if dark else "#6b6b66")
        data, dd, bs, engine = self._layout()
        fm = p.fontMetrics()
        lh = fm.height() + 2
        W = self.width()
        cols = [[data], dd or [], bs or [], [engine]]
        colw = (W - 50) / 4
        self.boxes = []
        pos = {}
        y_max = 0
        for c, col in enumerate(cols):
            y = 14
            for b in col:
                h = 10 + lh * (1 + len(b["lines"]))
                r = QRectF(14 + c * (colw + 8), y, colw - 8, h)
                pos[b["name"]] = r
                self.boxes.append((r, b))
                y += h + 14
            y_max = max(y_max, y)
        self.setMinimumHeight(int(y_max + 10))
        # cables
        p.setPen(QPen(muted, 1.5))

        def cable(a: QRectF, b: QRectF):
            s, e = QPointF(a.right(), a.top() + lh), QPointF(b.left(), b.top() + lh)
            path = QPainterPath(s)
            dx = max(30.0, (e.x() - s.x()) / 2)
            path.cubicTo(s + QPointF(dx, 0), e - QPointF(dx, 0), e)
            p.drawPath(path)
        for b in dd:
            cable(pos["data"], pos[b["name"]])
        for b in bs:
            used = [m for m in dd if m["name"] in b.get("calls", [])]
            for m in used:
                cable(pos[m["name"]], pos[b["name"]])
            if not used:
                cable(pos["data"], pos[b["name"]])
            cable(pos[b["name"]], pos["engine"])
        if not bs:
            p.setPen(QColor("#c0392b"))
            p.drawText(QPointF(14 + 2 * (colw + 8), 30), "No decide(F, p) yet")
        # boxes
        for r, b in self.boxes:
            p.setPen(QPen(muted, 1))
            p.setBrush(QColor(fills.get(b["kind"], fills["data"])))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(text)
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(r.left() + 8, r.top() + 5, r.width() - 12, lh), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(b["title"], Qt.ElideRight, int(r.width() - 16)))
            f.setBold(False)
            p.setFont(f)
            for i, line in enumerate(b["lines"]):
                p.setPen(QColor("#b4635e") if line.startswith("⚙") else muted)
                p.drawText(QRectF(r.left() + 8, r.top() + 5 + lh * (i + 1), r.width() - 12, lh),
                           Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(line, Qt.ElideRight, int(r.width() - 16)))
        p.setPen(muted)
        for c, label in enumerate(("Data", "Data → Data", "Data → Buy/Sell", "")):
            p.drawText(QPointF(16 + c * (colw + 8), 10), label)
        p.end()

    def _at(self, pt):
        return next((b for r, b in self.boxes if r.contains(pt)), None)

    def mousePressEvent(self, e):
        b = self._at(e.position())
        if b:
            self.clicked.emit(b["line"])

    def mouseMoveEvent(self, e):
        b = self._at(e.position())
        if b is None:
            self.hovered.emit("")
        elif b["kind"] == "engine":
            self.hovered.emit("The trading engine: turns the positions decide() asks for into fills at the next bar's "
                              "open, paying spread and slippage. Change when it decides in SETTINGS.")
        elif b["kind"] == "data":
            self.hovered.emit("The dataset this strategy runs on (SETTINGS['data']). Every module only sees data up "
                              "to the moment it decides.")
        else:
            self.hovered.emit(f"{b['kind']} module '{b['name']}'. Click to show its code. ⚙ lines are knobs.")


class PythonTab(TabBase):
    """A strategy written as one Python file (saved as .py)."""

    kind = "python"
    knobs_changed = Signal()

    def __init__(self, src: str, path: Path | None = None, number: int | None = None):
        super().__init__()
        self._init_common(path, number)
        self.knob_values: dict = {}

        self.bay = CodeBayView()
        self.bay.clicked.connect(self.editor_goto)
        self.bay.hovered.connect(self.hovered)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.bay)

        self.editor = CodeEditor()
        self.make_knob_btn = QPushButton("Make knob")
        self.make_knob_btn.setToolTip("Put the cursor on a number in the code and press this: the number becomes a "
                                      "knob you can turn in the Knobs panel (Ctrl+K).")
        self.make_knob_btn.setShortcut("Ctrl+K")
        self.make_knob_btn.clicked.connect(self.make_knob)
        self.knobs_lbl = QLabel()
        self.knobs_lbl.setStyleSheet("color: gray;")
        bar = QHBoxLayout()
        bar.addWidget(self.make_knob_btn)
        bar.addWidget(self.knobs_lbl, 1)
        code_page = QWidget()
        cl = QVBoxLayout(code_page)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addLayout(bar)
        cl.addWidget(self.editor, 1)
        cl.addWidget(self.problems)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(QLabel("<b>Patch bay</b> <span style='color:gray'>drawn from the code · click a box to see "
                            "its code</span>"))
        tl.addWidget(scroll, 1)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(code_page)
        split.setSizes([240, 600])
        self._finish(split)

        self.editor.setPlainText(src)
        self.editor.textChanged.connect(self.on_edit)
        self.on_edit(initial=True)

    # ---- the file
    def source(self) -> str:
        return self.editor.toPlainText()

    def config(self) -> dict | None:
        src = self.source()
        try:
            cfg = ps.to_config(src)
        except (ps.StrategyFileError, SyntaxError):
            return None
        cfg["strategy"]["params"]["knobs"] = dict(self.knob_values)
        return cfg

    def set_config(self, cfg: dict, path: Path | None = None):
        """Only Python sources can be loaded here; the app opens .json strategies in their own tab."""
        code = (cfg.get("strategy") or {}).get("params", {}).get("code")
        if code is not None:
            self.path = path
            self.editor.setPlainText(code)

    def apply_config(self, cfg: dict, what: str = ""):
        """Settings changed elsewhere (e.g. tests ticked on the Backtests page): write them into SETTINGS."""
        src = self.source()
        try:
            st = ps.settings(src)
        except ps.StrategyFileError as e:
            self.status.emit(str(e))
            return
        for k in ("data", "costs", "evaluators"):
            if k in cfg:
                st[k] = cfg[k]
        cur = self.editor.textCursor()
        pos = cur.position()
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText(ps.set_settings(src, st))
        cur.endEditBlock()
        cur.setPosition(min(pos, len(self.source())))
        self.editor.setTextCursor(cur)
        if what:
            self.status.emit(what)

    def reveal(self, key: str):
        pass

    def editor_goto(self, line: int):
        self.editor.goto_line(line)

    def knobs(self) -> list[dict]:
        return ps.knobs(self.source())

    def on_edit(self, initial: bool = False):
        src = self.source()
        cfg = self.config()
        probs = ps.check(src) if cfg is None else validate(cfg)
        self.problems.setText("\n".join(probs))
        names = {k["name"] for k in self.knobs()}
        self.knob_values = {k: v for k, v in self.knob_values.items() if k in names}
        self.bay.set_source(src, self.knob_values)
        n = len(names)
        self.knobs_lbl.setText(f"{n} knob{'s' if n != 1 else ''}: {', '.join(sorted(names))}" if n else
                               "No knobs yet. Put the cursor on a number and press Make knob.")
        if not initial:
            self._mark_stale()
            self.edited.emit()
            self.knobs_changed.emit()

    def make_knob(self):
        line, col = self.editor.cursor_pos()
        old = self.source()
        try:
            new, name = ps.make_knob(old, line, col)
        except (ps.StrategyFileError, SyntaxError) as e:
            self.status.emit(str(e))
            return
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText(new)
        cur.endEditBlock()
        self.editor.goto_line(line + new.count("\n") - old.count("\n"))
        self.status.emit(f"'{name}' is now a knob. Turn it in the Knobs panel.")

    def set_knob(self, name: str, value):
        self.knob_values[name] = value
        self.bay.set_source(self.source(), self.knob_values)
        self._mark_stale()

    def write_knobs_into_code(self):
        src = self.source()
        for n, v in self.knob_values.items():
            src = ps.set_knob_default(src, n, v)
        self.knob_values = {}
        self.editor.setPlainText(src)

    def insert_module(self, code: str, name: str):
        """Add a module from the library to the file, above decide()."""
        src = self.source()
        if re.search(rf"^def {re.escape(name)}\(", src, re.M):
            self.status.emit(f"The file already has a module called {name}.")
            return
        m = re.search(r"^def decide\(", src, re.M)
        at = m.start() if m else len(src)
        new = src[:at] + code.strip() + "\n\n\n" + src[at:]
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText(new)
        cur.endEditBlock()
        self.editor.goto_line(src[:at].count("\n") + 1)
        self.status.emit(f"Added module {name}. Call it from decide(F, p).")
