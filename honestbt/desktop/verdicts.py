"""Verdicts tab: one block per test, which you can drag to rearrange and fold away.

The order and which blocks are folded are remembered between runs and between
sessions (keyed by the test's name), so a layout you like stays put.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MIME = "application/x-titanium-verdict"
PASS, FAIL, NA = QColor("#1f8a4c"), QColor("#c0392b"), QColor("#8a8a84")


class VerdictCard(QFrame):
    hovered = Signal(str)

    def __init__(self, v: dict, board: VerdictBoard, about: str = ""):
        super().__init__()
        self.board, self.name, self._press = board, v["name"], None
        color = PASS if v["passed"] is True else FAIL if v["passed"] is False else NA
        tag = "PASS" if v["passed"] is True else "FAIL" if v["passed"] is False else "N/A"
        self.setObjectName("card")
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self._base = f"QFrame#card {{ border: 1px solid palette(mid); border-left: 5px solid {color.name()}; border-radius: 6px; }}"
        self.setStyleSheet(self._base)
        self.about = (about + "\n\n" if about else "") + "Drag the ⠿ handle (or anywhere on the block) to move it."
        self.setToolTip(self.about)

        handle = QLabel("⠿")
        handle.setStyleSheet("color: gray; font-size: 16px;")
        handle.setCursor(Qt.OpenHandCursor)
        handle.setToolTip("Drag to move this test")
        tag_lbl = QLabel(f"<span style='color:{color.name()}; font-weight:700'>{tag}</span>")
        title = QLabel(f"<b>{v['name']}</b>")
        self.fold = QToolButton()
        self.fold.setAutoRaise(True)
        self.fold.setToolTip("Fold or unfold the explanation")
        self.fold.clicked.connect(lambda: self.set_folded(not self.folded, remember=True))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        for w in (handle, tag_lbl, title):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.fold)
        self.headline = QLabel(v["headline"])
        self.headline.setWordWrap(True)
        self.body = QLabel(v["explanation"])
        self.body.setWordWrap(True)
        self.body.setStyleSheet("color: gray;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 8)
        lay.addLayout(top)
        lay.addWidget(self.headline)
        lay.addWidget(self.body)
        self.folded = False
        self.set_folded(board.is_folded(self.name))

    def set_folded(self, folded: bool, remember: bool = False):
        self.folded = folded
        self.body.setVisible(not folded)
        self.fold.setText("▸" if folded else "▾")
        if remember:
            self.board.remember_fold(self.name, folded)

    # ---- hover help
    def enterEvent(self, e):
        self.hovered.emit(f"Test '{self.name}': {self.about}")
        super().enterEvent(e)

    # ---- dragging
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return super().mouseMoveEvent(e)
        mime = QMimeData()
        mime.setData(MIME, self.name.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pix = self.grab()
        drag.setPixmap(pix.scaledToWidth(min(pix.width(), 360), Qt.SmoothTransformation))
        drag.setHotSpot(QPoint(12, 12))
        self._press = None
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME) and bytes(e.mimeData().data(MIME)).decode() != self.name:
            e.acceptProposedAction()
            self.setStyleSheet(self._base + " QFrame#card { background: palette(alternate-base); }")

    def dragLeaveEvent(self, e):
        self.setStyleSheet(self._base)

    def dropEvent(self, e):
        self.setStyleSheet(self._base)
        src = bytes(e.mimeData().data(MIME)).decode()
        after = e.position().y() > self.height() / 2
        self.board.move(src, self.name, after=after)
        e.acceptProposedAction()


class VerdictBoard(QScrollArea):
    """Grid of VerdictCards. Two columns when there is room, one when narrow."""

    hovered = Signal(str)

    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("Titanium", "Titanium")
        self.cards: list[VerdictCard] = []
        self._cols = 0
        self.setWidgetResizable(True)
        inner = QWidget()
        outer = QVBoxLayout(inner)
        bar = QHBoxLayout()
        self.hint = QLabel("<span style='color:gray'>Run a strategy to see one block per test. "
                           "Drag blocks to arrange them.</span>")
        bar.addWidget(self.hint)
        bar.addStretch()
        self.fold_all = QPushButton("Fold all")
        self.fold_all.setToolTip("Fold every block down to its headline, or unfold them all")
        self.fold_all.clicked.connect(self.toggle_all)
        reset = QPushButton("Reset layout")
        reset.setToolTip("Put the blocks back in the order the tests ran, all unfolded")
        reset.clicked.connect(self.reset)
        bar.addWidget(self.fold_all)
        bar.addWidget(reset)
        outer.addLayout(bar)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        outer.addLayout(self.grid)
        outer.addStretch()
        self.setWidget(inner)

    # ---- remembered layout
    def _list(self, key) -> list[str]:
        v = self.settings.value(key, [])
        return [v] if isinstance(v, str) else list(v or [])

    def saved_order(self) -> list[str]:
        return self._list("verdicts/order")

    def is_folded(self, name: str) -> bool:
        return name in self._list("verdicts/folded")

    def remember_fold(self, name: str, folded: bool):
        names = set(self._list("verdicts/folded"))
        names.add(name) if folded else names.discard(name)
        self.settings.setValue("verdicts/folded", sorted(names))

    # ---- content
    def set_verdicts(self, verdicts: list[dict], about: list[str] | None = None):
        for c in self.cards:
            c.setParent(None)
            c.deleteLater()
        about = about or [""] * len(verdicts)
        cards = [VerdictCard(v, self, a) for v, a in zip(verdicts, about)]
        for i, c in enumerate(cards):
            c.setProperty("ran", i)
            c.hovered.connect(self.hovered)
        rank = {n: i for i, n in enumerate(self.saved_order())}
        cards.sort(key=lambda c: rank.get(c.name, len(rank) + c.property("ran")))
        self.cards = cards
        self.hint.setText(f"<span style='color:gray'>{len(cards)} tests. Drag a block onto another to move it; "
                          f"▾ folds it.</span>")
        self._layout(force=True)

    def names(self) -> list[str]:
        return [c.name for c in self.cards]

    def move(self, src: str, target: str, after: bool = False):
        names = self.names()
        if src not in names or target not in names or src == target:
            return
        card = self.cards.pop(names.index(src))
        i = self.names().index(target) + (1 if after else 0)
        self.cards.insert(i, card)
        self._save_order()
        self._layout(force=True)

    def _save_order(self):
        # keep tests not shown in this run where they were, so switching strategies doesn't lose a layout
        shown = self.names()
        rest = [n for n in self.saved_order() if n not in shown]
        self.settings.setValue("verdicts/order", shown + rest)

    def reset(self):
        self.settings.remove("verdicts/order")
        self.settings.remove("verdicts/folded")
        for c in self.cards:
            c.set_folded(False)
        self.cards.sort(key=lambda c: c.property("ran") or 0)
        self._layout(force=True)

    def toggle_all(self):
        fold = not all(c.folded for c in self.cards)
        for c in self.cards:
            c.set_folded(fold, remember=True)
        self.fold_all.setText("Unfold all" if fold else "Fold all")

    def _layout(self, force=False):
        cols = 2 if self.viewport().width() >= 720 else 1
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols, Qt.AlignTop)
        for col in range(2):
            self.grid.setColumnStretch(col, 1 if col < cols else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()
