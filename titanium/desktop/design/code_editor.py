"""Kit components for code: a Python editor with line numbers and syntax colours, and
the knob controls (slider for numbers, switch for true/false).

Colours come from the skin palette's ``code_*`` keys; the font is the skin's mono face.
"""
from __future__ import annotations

import keyword
import re

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QSlider, QVBoxLayout, QWidget

from . import theme
from . import tokens as T

S = T.SPACE
BUILTINS = ("abs", "all", "any", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "range",
            "round", "set", "sorted", "str", "sum", "tuple", "zip", "None", "True", "False", "self")


def _fmt(color: str, bold: bool = False, italic: bool = False, background: str | None = None) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.DemiBold)
    if italic:
        f.setFontItalic(True)
    if background:
        f.setBackground(QColor(background))
    return f


class PythonHighlighter(QSyntaxHighlighter):
    """Keywords, functions, decorators, strings, numbers, comments, and ``knob(...)`` calls."""

    def __init__(self, document):
        super().__init__(document)
        self.retheme()

    def retheme(self) -> None:
        p = theme.current()
        kw = r"\b(" + "|".join(keyword.kwlist) + r")\b"
        self.rules = [
            (QRegularExpression(kw), _fmt(p.code_keyword, bold=True)),
            (QRegularExpression(r"\b(" + "|".join(BUILTINS) + r")\b"), _fmt(p.code_keyword)),
            (QRegularExpression(r"\b[A-Za-z_]\w*(?=\()"), _fmt(p.code_function)),
            (QRegularExpression(r"(?<=\bdef )\w+|(?<=\bclass )\w+"), _fmt(p.code_function, bold=True)),
            (QRegularExpression(r"\b(0[xob])?[0-9][0-9_]*(\.[0-9_]+)?([eE][+-]?[0-9]+)?\b"), _fmt(p.code_number)),
            (QRegularExpression(r"^\s*@[\w.]+"), _fmt(p.code_decorator, italic=True)),
            (QRegularExpression(r"[rbfu]{0,2}\"[^\"\\\n]*(\\.[^\"\\\n]*)*\"|[rbfu]{0,2}'[^'\\\n]*(\\.[^'\\\n]*)*'"),
             _fmt(p.code_string)),
            (QRegularExpression(r"#[^\n]*"), _fmt(p.code_comment, italic=True)),
        ]
        self.knob = QRegularExpression(r"\bknob\([^()\n]*\)")
        self.knob_fmt = QTextCharFormat()
        self.knob_fmt.setBackground(QColor(p.code_knob))
        self.triple = _fmt(p.code_string)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        for rx, fmt in self.rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
        it = self.knob.globalMatch(text)
        while it.hasNext():
            m = it.next()
            for i in range(m.capturedStart(), m.capturedStart() + m.capturedLength()):
                f = self.format(i)
                f.setBackground(self.knob_fmt.background())
                self.setFormat(i, 1, f)
        self._triple_quotes(text)

    def _triple_quotes(self, text: str) -> None:
        """Docstrings across lines: block state 1 = inside \"\"\", 2 = inside '''."""
        self.setCurrentBlockState(0)
        pos = 0
        state = self.previousBlockState()
        while True:
            if state in (1, 2):
                delim = '"""' if state == 1 else "'''"
                end = text.find(delim, pos)
                if end < 0:
                    self.setFormat(pos, len(text) - pos, self.triple)
                    self.setCurrentBlockState(state)
                    return
                self.setFormat(pos, end + 3 - pos, self.triple)
                pos, state = end + 3, 0
                continue
            m = re.compile(r'"""|\'\'\'').search(text, pos)
            if not m or "#" in text[pos:m.start()]:
                return
            state = 1 if m.group() == '"""' else 2
            self.setFormat(m.start(), 3, self.triple)
            pos = m.end()


class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """A Python editor: mono font, line numbers, syntax colours, 4-space tabs.

    ``set_text_preserving`` replaces the text with one undoable edit of only the
    part that changed, so the cursor and scroll position stay put.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("code", "true")
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = PythonHighlighter(self.document())
        self.gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _: self._fit_gutter())
        self.updateRequest.connect(self._scroll_gutter)
        self.cursorPositionChanged.connect(self.gutter.update)
        self.retheme()
        theme.watch(self, CodeEditor.retheme)

    def retheme(self) -> None:
        f = theme.mono_font(T.TYPE.body)
        self.setFont(f)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter.retheme()
        self._fit_gutter()

    # ---- line numbers
    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return S["md"] + self.fontMetrics().horizontalAdvance("9") * digits + S["sm"]

    def _fit_gutter(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect, dy) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event) -> None:
        pal = theme.current()
        p = QPainter(self.gutter)
        p.setFont(self.font())
        current = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                n = block.blockNumber()
                p.setPen(QColor(pal.text_muted if n == current else pal.text_faint))
                p.drawText(0, top, self.gutter.width() - S["sm"], h, Qt.AlignRight | Qt.AlignVCenter, str(n + 1))
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        p.end()

    # ---- editing
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers():
            line = self.textCursor().block().text()
            indent = line[:len(line) - len(line.lstrip())]
            if line.rstrip().endswith(":"):
                indent += "    "
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(event)

    def cursor_line_col(self) -> tuple[int, int]:
        """1-based line and 0-based column of the cursor."""
        c = self.textCursor()
        return c.blockNumber() + 1, c.positionInBlock()

    def set_text_preserving(self, text: str) -> None:
        old = self.toPlainText()
        if old == text:
            return
        a = 0
        n = min(len(old), len(text))
        while a < n and old[a] == text[a]:
            a += 1
        b = 0
        while b < n - a and old[-1 - b] == text[-1 - b]:
            b += 1
        c = QTextCursor(self.document())
        c.setPosition(a)
        c.setPosition(len(old) - b, QTextCursor.KeepAnchor)
        c.insertText(text[a:len(text) - b])


class KnobControl(QWidget):
    """One knob: its name, its value, and a slider (real and whole numbers) or a switch (true/false).

    ``kind`` is "real", "int" or "bool". Emits ``changed(value)`` as it is turned.
    """

    changed = Signal(object)
    STEPS = 200  # slider positions for a real knob

    def __init__(self, name: str, kind: str, value, lo=None, hi=None, step=None, note: str = "", parent=None):
        super().__init__(parent)
        self.kind, self.lo, self.hi = kind, lo, hi
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, S["xs"], 0, S["xs"])
        lay.setSpacing(S["xs"])
        top = QHBoxLayout()
        top.setSpacing(S["sm"])
        self.name = QLabel(name)
        self.name.setProperty("role", "label")
        top.addWidget(self.name, 1)
        if note:
            n = QLabel(note)
            n.setProperty("role", "caption")
            top.addWidget(n)
        self.value_label = QLabel()
        self.value_label.setProperty("role", "knobvalue")
        top.addWidget(self.value_label)
        lay.addLayout(top)
        if kind == "bool":
            self.switch = QCheckBox()
            self.switch.toggled.connect(lambda v: self._emit(bool(v)))
            lay.addWidget(self.switch)
            self.slider = None
        else:
            self.switch = None
            self.slider = QSlider(Qt.Horizontal)
            if kind == "int":
                self.slider.setRange(int(lo), int(hi))
                self.slider.setSingleStep(int(step or 1))
            else:
                self.slider.setRange(0, self.STEPS)
            self.slider.valueChanged.connect(lambda i: self._emit(self._from_slider(i)))
            lay.addWidget(self.slider)
        self.retheme()
        theme.watch(self, KnobControl.retheme)
        self.set_value(value)

    def retheme(self) -> None:
        self.value_label.setFont(theme.mono_font(T.TYPE.label))

    def _from_slider(self, i: int):
        if self.kind == "int":
            return int(i)
        return float(self.lo + (self.hi - self.lo) * i / self.STEPS)

    def _to_slider(self, v) -> int:
        if self.kind == "int":
            return int(v)
        span = (self.hi - self.lo) or 1
        return round((float(v) - self.lo) / span * self.STEPS)

    @staticmethod
    def show(v) -> str:
        if isinstance(v, bool):
            return "on" if v else "off"
        if isinstance(v, int):
            return str(v)
        return f"{v:.4g}"

    def _emit(self, v) -> None:
        self.value = v
        self.value_label.setText(self.show(v))
        if not self._quiet:
            self.changed.emit(v)

    _quiet = False

    def set_value(self, v) -> None:
        """Show ``v`` without emitting ``changed``."""
        self._quiet = True
        try:
            self.value = v
            if self.switch is not None:
                self.switch.setChecked(bool(v))
            else:
                self.slider.setValue(self._to_slider(v))
            self.value_label.setText(self.show(v))
        finally:
            self._quiet = False
