"""One strategy: its patch bay, its settings and its last result. Each lives in its own tab."""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..patchbay import validate
from .help import UI
from .patchbay_view import PatchBayView
from .widgets import HoverEditor

PASS, FAIL = QColor("#1f8a4c"), QColor("#c0392b")
_ids = itertools.count(1)


def pct(x, d=2):
    return "–" if x is None else f"{100 * x:+.{d}f}%"


def clean(cfg: dict) -> dict:
    """Settings as the app uses them: the strategy exactly as written, no sweep."""
    return {k: v for k, v in cfg.items() if k != "sweep"}


class TabBase(QWidget):
    """What every strategy tab has: a name, a summary of the last run, its trades and its test results."""

    edited = Signal()      # settings changed (results are now out of date)
    hovered = Signal(str)  # hover help text
    status = Signal(str)   # a short message for the status bar
    kind = "patchbay"

    def _init_common(self, path, number):
        self.number = number or next(_ids)
        self.key = f"S{self.number}"
        self.path = path
        self.run = None           # runner.StrategyRun of the last run
        self.report: dict | None = None
        self.results: dict[str, dict] = {}  # test plugin -> verdict, from the Backtests page
        self.stale = False        # settings changed since the last run
        self.summary = QLabel("Not run yet. Press Run strategy (Ctrl+Enter).")
        self.summary.setWordWrap(True)
        self.summary.setFrameShape(QFrame.StyledPanel)
        self.summary.setMargin(6)
        self.summary.setToolTip("The result of the last run of this strategy, exactly as written.")
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet(f"color: {FAIL.name()};")
        self.trades_table = QTableWidget()
        self.trades_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.trades_table.setSortingEnabled(True)
        self.trades_table.verticalHeader().setVisible(False)

    # ---- naming
    def name(self) -> str:
        cfg = self.config() or {}
        return cfg.get("name") or (self.path.stem if self.path else "untitled")

    def title(self) -> str:
        return f"{self.key}: {self.name()}"

    def tab_text(self) -> str:
        n = self.name()
        return f"{self.key}  {n[:22]}{'…' if len(n) > 22 else ''}"

    def dataset_label(self) -> str:
        d = (self.config() or {}).get("data") or {}
        return d.get("plugin", "?")

    def _mark_stale(self):
        if self.report and not self.stale:
            self.stale = True
            self.summary.setText(self.summary.text() + "<br><b>Settings changed since this run.</b> "
                                 "Run again to update.")

    # ---- results
    def set_result(self, run, report: dict):
        self.run, self.report, self.stale = run, report, False
        self.results = {}
        m = report["selected"]["metrics"]
        eq = report["selected"]["equity"]
        profit = (eq["v"][-1] - 1) if eq["v"] else None
        span = f"{eq['t'][0][:10]} to {eq['t'][-1][:10]}" if eq["t"] else "no periods"
        money = f" (${m['total_pnl_usd']:+,.0f})" if "total_pnl_usd" in m else ""
        color = PASS if (profit or 0) > 0 else FAIL
        self.summary.setText(
            f"<b style='color:{color.name()}'>Profit {pct(profit)}{money}</b> over {span} · "
            f"{m.get('n_trades', 0)} trades · max drawdown {pct(m.get('max_drawdown'), 1)}"
            f"<br><span style='color:gray'>{report['data']} · {report['elapsed_s']} s. "
            f"See the Measurements page to compare, and Backtests to test it.</span>")
        self.fill_trades(report["selected"]["trades"])

    def fill_trades(self, trades):
        t = self.trades_table
        t.setSortingEnabled(False)
        futures = bool(trades) and trades[0].get("pnl_usd") is not None
        heads = ["symbol", "entry", "exit", "held (min)", "reason", "side" if futures else "score",
                 "net $" if futures else "net"] + (["R"] if futures else [])
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(trades))
        for r, tr in enumerate(trades):
            vals = [tr["symbol"], tr["entry_time"][:16].replace("T", " "), tr["exit_time"][:16].replace("T", " "),
                    str(tr["minutes_held"]), tr["reason"]]
            if futures:
                rm = tr.get("r_multiple")
                vals += ["long" if tr.get("side", 1) > 0 else "short", f"{tr['pnl_usd']:+,.2f}",
                         "–" if rm is None else f"{rm:+.2f}"]
            else:
                vals += [pct(tr.get("score")), pct(tr["net_return"])]
            for c, v in enumerate(vals):
                t.setItem(r, c, QTableWidgetItem(v))
            t.item(r, 6).setForeground(PASS if tr["net_return"] > 0 else FAIL)
        t.resizeColumnsToContents()
        t.setSortingEnabled(True)



class StrategyTab(TabBase):
    """A strategy built in the patch bay from plugin modules (saved as .json)."""

    def __init__(self, cfg: dict, path: Path | None = None, number: int | None = None):
        super().__init__()
        self._init_common(path, number)

        self.graph = PatchBayView()
        self.graph.hovered.connect(self.hovered)
        self.graph.clicked.connect(self.reveal)
        self.graph.edited.connect(self.apply_config)
        self.graph.message.connect(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.graph)

        self.editor = HoverEditor()
        self.editor.hovered.connect(self.hovered)
        self.editor.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        edit_page = QWidget()
        el = QVBoxLayout(edit_page)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.editor)
        el.addWidget(self.problems)
        self.lower = QTabWidget()
        self.lower.addTab(edit_page, "Settings (JSON)")
        self.lower.addTab(self.trades_table, "Trades")
        self.lower.setTabToolTip(0, UI["Settings (JSON)"])
        self.lower.setTabToolTip(1, UI["Trades"])

        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.summary)
        tl.addWidget(QLabel("<b>Patch bay</b> <span style='color:gray'>data and features → strategy → trading "
                            "engine · drag ● outputs onto settings to wire · right-click for more</span>"))
        tl.addWidget(scroll, 1)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.lower)
        split.setSizes([520, 360])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(split)

        self.editor.setPlainText(json.dumps(clean(cfg), indent=2))
        self.editor.textChanged.connect(self.on_edit)
        self.on_edit(initial=True)

    # ---- settings
    def config(self) -> dict | None:
        try:
            cfg = json.loads(self.editor.toPlainText())
        except json.JSONDecodeError as e:
            self.problems.setText(f"JSON error, line {e.lineno}: {e.msg}")
            return None
        return cfg if isinstance(cfg, dict) else None

    def set_config(self, cfg: dict, path: Path | None = None):
        self.path = path
        self.editor.setPlainText(json.dumps(clean(cfg), indent=2))

    def apply_config(self, cfg: dict, what: str = ""):
        """Write new settings into the editor as one undoable step (Ctrl+Z in the editor undoes it)."""
        bar = self.editor.verticalScrollBar()
        keep = bar.value()
        cur = self.editor.textCursor()
        cur.beginEditBlock()
        cur.select(cur.SelectionType.Document)
        cur.insertText(json.dumps(clean(cfg), indent=2))
        cur.endEditBlock()
        bar.setValue(keep)
        if what:
            self.status.emit(what)

    def reveal(self, key: str):
        self.lower.setCurrentIndex(0)
        self.editor.select_key(key)

    def on_edit(self, initial: bool = False):
        cfg = self.config()
        if cfg is None:
            return
        self.problems.setText("\n".join(validate(cfg)))
        self.graph.set_config(cfg)
        self.editor.cfg = cfg
        if not initial:
            self._mark_stale()
            self.edited.emit()

class DefaultTab(QWidget):
    """The default strategy: the yardstick every strategy is compared with."""

    def __init__(self):
        super().__init__()
        text = QLabel(
            "<h3>Default strategy: hold everything</h3>"
            "<p>Spread the money evenly across every stock in the dataset and hold it. Each day the account is "
            "split equally across every name that traded, so stocks that list later join in and stocks that "
            "are delisted stay in until their last day. No trading costs.</p>"
            "<p>It runs automatically on the dataset of every strategy you run. Tick <b>Show default "
            "strategy</b> on the Measurements page to draw it next to your strategies.</p>"
            "<p style='color:gray'>For a futures dataset with one contract it is simply holding that contract.</p>")
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay = QVBoxLayout(self)
        lay.addWidget(text)
