"""The design gallery: every component of the kit in one window, the visual reference.

    python -m titanium.desktop.design.gallery          (add --dark for dark mode)
"""
from __future__ import annotations

import sys
from dataclasses import fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGridLayout, QLabel, QScrollArea, QSlider, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import icons, theme
from . import tokens as T
from .components import (
    Card, EmptyState, Logo, SearchField, Segmented, StatTile, badge, button, hbox, label,
)

S = T.SPACE


class Swatch(QWidget):
    def __init__(self, name: str, color: str):
        super().__init__()
        self.name, self.color = name, color
        self.setFixedSize(112, 64)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = theme.current()
        p.setPen(QColor(pal.border))
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(0, 0, self.width() - 1, 36, T.RADIUS["md"], T.RADIUS["md"])
        p.setPen(QColor(pal.text))
        p.setFont(theme.ui_font(T.TYPE.caption))
        p.drawText(0, 50, self.name)
        p.setPen(QColor(pal.text_faint))
        p.drawText(0, 62, self.color)


def section(title: str, note: str = "") -> Card:
    return Card(title, note)


def build() -> QWidget:
    pal = theme.current()
    root = QWidget()
    col = QVBoxLayout(root)
    col.setContentsMargins(S["xxl"], S["xxl"], S["xxl"], S["xxl"])
    col.setSpacing(S["xl"])

    head = hbox(Logo(44), spacing=S["md"])
    titles = QVBoxLayout()
    titles.setSpacing(0)
    titles.addWidget(label("Titanium design system", "display"))
    titles.addWidget(label(f"Every component, in the {pal.name} theme. UI code uses only these.", "muted"))
    head.addLayout(titles, 1)
    col.addLayout(head)

    # colour
    c = section("Colour", "Tokens from design/tokens.py. Brand red comes from the logo; blue is for actions.")
    grid = QGridLayout()
    grid.setSpacing(S["md"])
    names = [f.name for f in fields(pal) if f.name not in ("name", "series")]
    for i, n in enumerate(names):
        grid.addWidget(Swatch(n, getattr(pal, n)), i // 7, i % 7)
    c.body.addLayout(grid)
    series = hbox(*[Swatch(f"series {i + 1}", s) for i, s in enumerate(pal.series)], None, spacing=S["md"])
    c.body.addLayout(series)
    col.addWidget(c)

    # type
    t = section("Type", "Inter where installed, then the platform's UI font.")
    for role, sample in (("display", "Display 26 · Titanium"), ("heading", "Heading 20 · Strategies"),
                         ("title", "Title 15 · Monday top-5 gappers"), ("", "Body 13 · Each page manages one kind of object."),
                         ("label", "Label 12 · DATASET"), ("muted", "Muted 13 · Secondary information"),
                         ("caption", "Caption 11 · Updated 2 minutes ago"), ("overline", "OVERLINE 11 · PROFIT")):
        t.body.addWidget(label(sample, role))
    col.addWidget(t)

    # buttons and badges
    b = section("Buttons and badges", "Run is the ink pill. One primary button per area.")
    b.body.addLayout(hbox(button("Run", "run", "play"), button("New strategy", "primary", "plus"), button("Import file", icon="import"),
                          button("Cancel", "ghost"), button("Reset to empty", "danger"),
                          button("Disabled", "primary"), None))
    b.body.itemAt(b.body.count() - 1).layout().itemAt(5).widget().setEnabled(False)
    b.body.addLayout(hbox(badge("Python"), badge("Patch bay", "primary"), badge("Starter", "brand"),
                          badge("Passed", "success"), badge("Failed", "danger"), None))
    seg = Segmented(["Patch bay", "Code", "Run"])
    b.body.addLayout(hbox(seg, None))
    col.addWidget(b)

    # inputs
    inp = section("Inputs")
    combo = QComboBox()
    combo.addItems(["Nasdaq minute bars, 2023-2025", "Synthetic, 40 symbols"])
    chk = QCheckBox("Show the default strategy")
    chk.setChecked(True)
    slider = QSlider(Qt.Horizontal)
    slider.setValue(40)
    slider.setFixedWidth(200)
    inp.body.addLayout(hbox(SearchField("Search modules"), combo, chk, slider, None, spacing=S["lg"]))
    col.addWidget(inp)

    # cards
    row = hbox(spacing=S["lg"])
    row.addWidget(StatTile("Profit", "+12.4%", "vs +8.1% default strategy"))
    row.addWidget(StatTile("Sharpe", "1.32", "52 weekly periods"))
    row.addWidget(StatTile("Max drawdown", "-6.8%", "Mar 2024"))
    ok = Card("Out-of-sample", "In-sample Sharpe 1.4 to out-of-sample 0.9", accent="success")
    ok.add_action(badge("Passed", "success"))
    row.addWidget(ok)
    col.addLayout(row)

    # table
    tc = section("Table", "Lists of datasets, strategies, trades.")
    tbl = QTableWidget(4, 5)
    tbl.setHorizontalHeaderLabels(["Dataset", "Kind", "Instruments", "Range", "Used by"])
    rows = [("Nasdaq minute", "Core", "412", "2023-01-03 to 2025-10-31", "S1, S2"),
            ("Earnings dates", "Complementary", "412", "2023 to 2025", "S2"),
            ("Volatility 20d", "Generated", "412", "2023 to 2025", "S1"),
            ("Synthetic", "Core", "40", "2 years", "")]
    for r, vals in enumerate(rows):
        for k, v in enumerate(vals):
            tbl.setItem(r, k, QTableWidgetItem(v))
    tbl.verticalHeader().setVisible(False)
    tbl.horizontalHeader().setStretchLastSection(True)
    tbl.setShowGrid(False)
    tbl.setFixedHeight(190)
    tbl.resizeColumnsToContents()
    tc.body.addWidget(tbl)
    col.addWidget(tc)

    # icons and empty state
    ic = section("Icons", "Line icons on a 24px grid, drawn in any token colour.")
    grid = QGridLayout()
    grid.setSpacing(S["lg"])
    for i, n in enumerate(icons.NAMES):
        cell = QVBoxLayout()
        pm = QLabel()
        pm.setPixmap(icons.pixmap(n, pal.text, 22))
        pm.setAlignment(Qt.AlignCenter)
        cell.addWidget(pm)
        cap = label(n, "caption")
        cap.setAlignment(Qt.AlignCenter)
        cell.addWidget(cap)
        grid.addLayout(cell, i // 10, i % 10)
    ic.body.addLayout(grid)
    col.addWidget(ic)

    empty = EmptyState("strategies", "No strategies yet",
                       "Start an empty strategy, pick one from the library, or import a Python file.",
                       [button("New strategy", "primary", "plus"), button("Library", icon="library"),
                        button("Import file", icon="import")])
    empty.setMinimumHeight(280)
    col.addWidget(empty)
    col.addStretch()

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(root)
    scroll.setWindowTitle("Titanium design system")
    return scroll


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    theme.apply(app, "dark" if "--dark" in argv else "light")
    w = build()
    w.resize(1280, 900)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
