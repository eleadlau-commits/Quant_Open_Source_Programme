"""The design gallery: every component of the kit in one window, the visual reference.

    python -m titanium.desktop.design.gallery          (add --dark for dark mode, --skin <id> for a skin)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, fields

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGridLayout, QLabel, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from . import icons, theme
from . import tokens as T
from .chart import SUB, ChartMarker, ChartSeries, TimeChart
from .components import (
    CableEnds, Canvas, Card, CodeEditor, DataTable, Details, EmptyState, ItemRow, KnobControl, KnobSpec, Logo,
    NodeCanvasScene, NodeCanvasView, NodeSpec, ParamForm, RunButton, SearchField, Segmented, StatTile, Switch, badge,
    button, divider, hbox, label,
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
        p.setPen(theme.qcolor(pal.border))
        p.setBrush(theme.qcolor(self.color))
        p.drawRoundedRect(0, 0, self.width() - 1, 36, theme.radius("md"), theme.radius("md"))
        p.setPen(theme.qcolor(pal.text))
        p.setFont(theme.ui_font(T.TYPE.caption))
        p.drawText(0, 50, self.name)
        p.setPen(theme.qcolor(pal.text_faint))
        p.drawText(0, 62, self.color)


@dataclass(frozen=True)
class _Param:
    """Stands in for a data source's setting (anything with these fields works in ParamForm)."""

    name: str
    type: str
    default: object
    label: str = ""
    help: str = ""
    choices: tuple = ()
    minimum: float | None = None
    maximum: float | None = None


def section(title: str, note: str = "") -> Card:
    return Card(title, note)


def sample_chart() -> TimeChart:
    """A chart with made-up numbers (a strategy, the default strategy, two weights and some trades)."""
    import math
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2024, 1, 2, 20, 50, tzinfo=timezone.utc)
    days = [t0 + timedelta(days=i) for i in range(0, 252) if (t0 + timedelta(days=i)).weekday() < 5]
    strat = [(t, 1 + 0.0012 * i + 0.04 * math.sin(i / 9)) for i, t in enumerate(days)]
    base = [(t, 1 + 0.0007 * i + 0.025 * math.sin(i / 13 + 1)) for i, t in enumerate(days)]
    w1 = [(t, 50 + 40 * math.sin(i / 17)) for i, t in enumerate(days)]
    w2 = [(t, 50 - 40 * math.sin(i / 17)) for i, t in enumerate(days)]
    chart = TimeChart()
    chart.set_data([ChartSeries("Momentum rotation", strat), ChartSeries("Default strategy", base, dashed=True),
                    ChartSeries("AAPL", w1, panel=SUB, color=1), ChartSeries("MSFT", w2, panel=SUB, color=2)],
                   [ChartMarker(days[i], 1 if n % 2 == 0 else -1, "trade") for n, i in enumerate(range(10, 160, 15))],
                   fmt=lambda v: f"{v:.2f}", sub_fmt=lambda v: f"{v:.0f}%")
    chart.setFixedHeight(300)
    return chart


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
    titles.addWidget(label(f"Every component, in the {theme.skin().name} skin, {pal.name} theme. UI code uses only these.", "muted"))
    head.addLayout(titles, 1)
    col.addLayout(head)

    # colour
    c = section("Colour", f"Tokens from the {theme.skin().name} skin pack. Brand red comes from the logo and marks what is live.")
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
    b = section("Buttons and badges", "One primary button per area. Run is its own component.")
    running = RunButton()
    running.set_running(True, "61%")
    b.body.addLayout(hbox(RunButton(), running, None))
    b.body.addLayout(hbox(button("New strategy", "primary", "plus"), button("Import file", icon="import"),
                          button("Cancel", "ghost"), button("Reset to empty", "danger"),
                          button("Disabled", "primary"), None))
    b.body.itemAt(b.body.count() - 1).layout().itemAt(4).widget().setEnabled(False)  # the Disabled one
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
    inp.body.addLayout(hbox(SearchField("Search modules"), combo, chk, slider, Switch(True), Switch(False), None,
                            spacing=S["lg"]))
    col.addWidget(inp)

    # list rows
    lr = section("List rows", "ItemRow: an item in a card, with a badge, a caption, a note and a Switch on the right.")
    on = ItemRow("Synthetic data 1.0.0", "Random-walk stock and futures minute bars.")
    on.add_badge(badge("Built in", "neutral"))
    on.add_control(Switch(True))
    off = ItemRow("Bootstrap test 0.3.0", "Resamples weekly returns.")
    off.add_badge(badge("Problem", "danger"))
    off.set_note("Needs plugin 'out-of-sample', which is not installed.")
    off.add_control(Switch(False))
    lr.body.addWidget(on)
    lr.body.addWidget(divider())
    lr.body.addWidget(off)
    col.addWidget(lr)

    # cards
    row = hbox(spacing=S["lg"])
    row.addWidget(StatTile("Profit", "+12.4%", "vs +8.1% default strategy"))
    row.addWidget(StatTile("Sharpe", "1.32", "52 weekly periods"))
    row.addWidget(StatTile("Max drawdown", "-6.8%", "Mar 2024"))
    ok = Card("Out-of-sample", "In-sample Sharpe 1.4 to out-of-sample 0.9", accent="success")
    ok.add_action(badge("Passed", "success"))
    row.addWidget(ok)
    col.addLayout(row)

    # canvas
    cv = section("Canvas", "The patch bay and charts sit on the skin's backdrop.")
    canvas = Canvas()
    canvas.setFixedHeight(120)
    canvas.body.addWidget(label("Modules go here", "muted"), 0, Qt.AlignCenter)
    cv.body.addWidget(canvas)
    cv.body.addWidget(label("Node canvas: modules with ports and inline knobs, joined by cables "
                            "(NodeCanvasScene and NodeCanvasView inside Canvas(backdrop=False)).", "caption", wrap=True))
    nodes = Canvas(backdrop=False)
    nodes.setFixedHeight(230)
    scene = NodeCanvasScene(nodes)
    scene.set_nodes([
        NodeSpec("m1", "Momentum", "transform · m1", [], ["scores"], set(),
                 [KnobSpec("m1.days", "days", "int", 20, 5, 120, 1)], (0, 20)),
        NodeSpec("m2", "Top N equal weight", "decide · m2", ["scores"], [], {"scores"},
                 [KnobSpec("m2.top", "top", "int", 5, 1, 20, 1), KnobSpec("m2.positive_only", "positive_only", "bool", True)],
                 (320, 0)),
    ], [CableEnds("m1", "scores", "m2", "scores")])
    scene.nodes["m2"].setSelected(True)
    nview = NodeCanvasView(scene)
    nodes.body.addWidget(nview)
    cv.body.addWidget(nodes)
    nview.centerOn(scene.items_rect().center())
    col.addWidget(cv)

    # chart
    ch = section("Chart", "TimeChart: a thin viewer of a run. Wheel zooms in time, drag pans, the crosshair reads every line; "
                          "trade dots, a dashed default strategy and a panel below for local series.")
    ch.body.addWidget(sample_chart())
    col.addWidget(ch)

    # code and knobs
    cd = section("Code and knobs", "The strategy code editor (mono face, the skin's code colours) and knob controls.")
    ed = CodeEditor()
    ed.setPlainText('''@module(id="m1", name="Momentum", kind="transform", outputs=["scores"])
def momentum(view):
    """Return over the last `days` completed days."""
    days = knob("days", 20, lo=5, hi=120)  # a knob
    scores = {}
    for s in view.universe():
        close = list(view.bars(s, "1d")["close"])
        if len(close) > days:
            scores[s] = close[-1] / close[-days - 1] - 1
    return scores
''')
    ed.setFixedHeight(230)
    knobs = QVBoxLayout()
    knobs.setSpacing(S["sm"])
    knobs.addWidget(KnobControl("days", "int", 20, 5, 120, 1, "Momentum"))
    knobs.addWidget(KnobControl("min_move", "real", 0.02, 0.0, 0.1, None, "Top N"))
    knobs.addWidget(KnobControl("positive_only", "bool", True, note="Top N"))
    knobs.addStretch()
    box = QWidget()
    box.setFixedWidth(260)
    box.setLayout(knobs)
    cd.body.addLayout(hbox(ed, box, spacing=S["lg"]))
    col.addWidget(cd)

    # table
    tc = section("Table", "DataTable: lists of datasets, strategies, trades. Whole rows select.")
    tbl = DataTable(["Dataset", "Kind", "Instruments", "Range", "Used by"])
    rows = [("Nasdaq minute", "Core", "412", "2023-01-03 to 2025-10-31", "S1, S2"),
            ("Earnings dates", "Complementary", "412", "2023 to 2025", "S2"),
            ("Volatility 20d", "Generated", "412", "2023 to 2025", "S1"),
            ("Synthetic", "Core", "40", "2 years", "")]
    tbl.set_rows(rows, [r[0] for r in rows])
    tbl.select("Earnings dates")
    tbl.setFixedHeight(190)
    tc.body.addWidget(tbl)
    col.addWidget(tc)

    # details and forms
    row2 = hbox(spacing=S["lg"])
    dc = section("Details", "Details: what an object is, key by key.")
    det = Details()
    det.set_rows([("Source", "Synthetic stocks · seed 7"), ("Contents", "20 stocks, minute bars"),
                  ("Range", "2 Jan 2024 to 27 Mar 2024, New York time"),
                  ("Used by", hbox(badge("Gap fade", "brand"), badge("ORB 15m", "brand"), None))])
    dc.body.addWidget(det)
    row2.addWidget(dc, 1)
    fc = section("Form", "ParamForm: fields made from a list of settings.")
    fc.body.addWidget(ParamForm([_Param("n_symbols", "int", 20, "Stocks"),
                                 _Param("gap_momentum", "float", 0.0, "Planted edge"),
                                 _Param("kind", "choice", "core", "What the files hold", choices=("core", "complementary")),
                                 _Param("annualise", "bool", True, "Yearly figure"),
                                 _Param("paths", "path", "", "Files")]))
    row2.addWidget(fc, 1)
    col.addLayout(row2)

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
    skin_id = argv[argv.index("--skin") + 1] if "--skin" in argv[:-1] else None
    theme.apply(app, "dark" if "--dark" in argv else "light", skin_id)
    w = build()
    w.resize(1280, 900)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
