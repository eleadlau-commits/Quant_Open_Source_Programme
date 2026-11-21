"""Settings, tucked in the corner of the navigation rail.

Appearance and Skin set the look. Defaults for every run are the app-wide values a run
starts with (``Workspace.run_defaults``). Markets shows each market's sessions and holidays
and edits its defaults: trading hours, decision time and costs (``Workspace.set_market_defaults``). Module library sets the folder the library's own
modules are read from. Plugins lists every plugin, on or off and why, switches them,
and imports ``.tiplug`` packs. Layout shows where every view lives (page or dock).
"""
from __future__ import annotations

from pathlib import Path

from datetime import date

from PySide6.QtCore import QTime, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QTimeEdit, QVBoxLayout, QWidget

from ...app import paths
from ...app.settings import EVERY, RunDefaults
from ...core.markets import Market, MarketDefaults
from ...core.plugins import Library
from ..design import skins, theme
from ..design import tokens as T
from ..design.components import Card, ItemRow, Segmented, Switch, badge, button, divider, hbox, label
from ..market_text import holidays_text, sessions_text, tz_name
from ..views import DOCK, PAGE
from ._base import PageView

S = T.SPACE
FIELD_WIDTH = 260


class SettingsView(PageView):
    view_id = "settings"
    title = "Settings"
    icon = "settings"
    nav = False  # shown in the corner of the rail, not with the pages
    order = 900
    scroll = True

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.column.setSpacing(S["lg"])
        self._build_appearance()
        self._build_skin()
        self._build_run_defaults()
        self._build_markets()
        self._build_library()
        self._build_plugins()
        self._build_layout()
        self.column.addStretch()

    def subtitle(self) -> str:
        return "Appearance, run defaults, markets, the module library, plugins and layout."

    @property
    def workspace(self):
        return self.ctx.workspace if self.ctx is not None else None

    # ---- appearance and skin ------------------------------------------------------
    def _build_appearance(self) -> None:
        look = Card("Appearance", "Light, dark, or the same as the system.")
        form = _form()
        self.theme_box = QComboBox()
        self.theme_box.setFixedWidth(FIELD_WIDTH)
        for mode in theme.MODES:
            self.theme_box.addItem(theme.LABELS[mode], mode)
        if self.ctx is not None:
            saved = self.ctx.settings.value("view/theme", "system")
            self.theme_box.setCurrentIndex(max(0, list(theme.MODES).index(saved) if saved in theme.MODES else 0))
        self.theme_box.currentIndexChanged.connect(self._theme)
        form.addRow(label("Theme", "label"), self.theme_box)
        look.body.addLayout(form)
        self.column.addWidget(look)

    def _build_skin(self) -> None:
        self.skin_card = Card("Skin", "The look of the whole app, in light and dark. Add your own as .toml files "
                                      "in the skins folder, or from a plugin.")
        sform = _form()
        self.skin_box = QComboBox()
        self.skin_box.setFixedWidth(FIELD_WIDTH)
        self._fill_skins()
        self.skin_box.currentIndexChanged.connect(self._skin)
        sform.addRow(label("Skin", "label"), self.skin_box)
        self.skin_about = label("", "caption", wrap=True)
        sform.addRow(label("", "label"), self.skin_about)
        self.skin_card.body.addLayout(sform)
        self.skin_card.body.addWidget(label(f"Skins folder: {paths.skins_folder()}", "caption", wrap=True))
        self.skin_problems = label("", "caption", wrap=True)
        self.skin_card.body.addWidget(self.skin_problems)
        self._describe_skin()
        self.column.addWidget(self.skin_card)

    def _fill_skins(self) -> None:
        self.skin_box.blockSignals(True)
        self.skin_box.clear()
        for sk in skins.available():
            self.skin_box.addItem(sk.name, sk.id)
        current = theme.skin().id
        if self.ctx is not None:
            current = self.ctx.settings.value("view/skin", current)
        self.skin_box.setCurrentIndex(max(0, self.skin_box.findData(current)))
        self.skin_box.blockSignals(False)

    def _theme(self, _i: int) -> None:
        mode = self.theme_box.currentData()
        if self.ctx is not None:
            self.ctx.settings.setValue("view/theme", mode)
            self.ctx.theme_changed.emit(mode)

    def _skin(self, _i: int) -> None:
        skin_id = self.skin_box.currentData()
        if self.ctx is not None:
            self.ctx.settings.setValue("view/skin", skin_id)
            self.ctx.skin_changed.emit(skin_id)
        self._describe_skin()

    def _describe_skin(self) -> None:
        sk = skins.get(self.skin_box.currentData())
        self.skin_about.setText(sk.description)
        issues = skins.problems()
        self.skin_problems.setText("\n".join(issues))
        self.skin_problems.setVisible(bool(issues))

    # ---- defaults for every run --------------------------------------------------------
    def _build_run_defaults(self) -> None:
        card = Card("Defaults for every run", "What a new run starts with, whatever the market. Decision time, "
                                              "trading hours and costs belong to each market. A strategy or a "
                                              "backtest can change any of them for itself.")
        d = self.workspace.run_defaults if self.workspace is not None else RunDefaults()
        grid = QGridLayout()
        grid.setHorizontalSpacing(S["xl"])
        grid.setVerticalSpacing(S["md"])
        self.capital = _number(d.capital, 1, 1e12, decimals=0, step=10_000, suffix="")
        self.capital.setToolTip("Notional starting cash, in the market's currency. Results are shown normalised.")
        self.every_keys = list(EVERY)
        self.every = Segmented(["Day", "Week", "Month"])
        self.every.group.button(self.every_keys.index(d.every)).setChecked(True)
        self.every.setToolTip("How often the strategy decides: every trading day, or the first of each week or month.")
        self.max_gross = _number(d.max_gross * 100, 1, 1000, decimals=0, step=10, suffix=" %")
        self.max_gross.setToolTip("The most the strategy may hold in total, as a share of its equity. "
                                  "100 % means no leverage.")
        self.min_trade = _number(d.min_trade * 100, 0, 99, decimals=2, step=0.1, suffix=" %")
        self.min_trade.setToolTip("Skip trades smaller than this share of equity, so tiny rebalances don't pay costs.")
        for r, (text, w) in enumerate([("Capital", self.capital), ("Decides", self.every)]):
            grid.addWidget(label(text, "label"), r, 0)
            grid.addWidget(w, r, 1)
        for r, (text, w) in enumerate([("Exposure cap", self.max_gross), ("Smallest trade", self.min_trade)]):
            grid.addWidget(label(text, "label"), r, 2)
            grid.addWidget(w, r, 3)
        grid.setColumnStretch(4, 1)
        card.body.addLayout(grid)
        for w in (self.capital, self.max_gross, self.min_trade):
            w.valueChanged.connect(self._save_run_defaults)
        self.every.changed.connect(self._save_run_defaults)
        self.column.addWidget(card)

    def run_defaults(self) -> RunDefaults:
        return RunDefaults(capital=self.capital.value(), every=self.every_keys[self.every.index()],
                           max_gross=round(self.max_gross.value() / 100, 6),
                           min_trade=round(self.min_trade.value() / 100, 6))

    def _save_run_defaults(self, *_):
        if self.ctx is not None:
            self.ctx.save_run_defaults(self.run_defaults())

    # ---- markets ------------------------------------------------------------------------
    def _build_markets(self) -> None:
        card = Card("Markets", "Where instruments trade: sessions, holidays and the defaults runs on each "
                               "market start with. Markets come with the app or from plugins.")
        self.market_rows: dict[str, MarketRow] = {}
        markets = self.workspace.markets() if self.workspace is not None else {}
        own = self.workspace.markets(edited=False) if self.workspace is not None else {}
        for i, (mid, m) in enumerate(markets.items()):
            if i:
                card.body.addWidget(divider())
            row = MarketRow(m, own[mid].defaults, self._save_market)
            self.market_rows[mid] = row
            card.body.addWidget(row)
        self.column.addWidget(card)

    def _save_market(self, market_id: str, defaults: MarketDefaults | None) -> None:
        if self.ctx is not None:
            self.ctx.save_market_defaults(market_id, defaults)

    # ---- module library ----------------------------------------------------------------
    def _build_library(self) -> None:
        card = Card("Module library", "The library's own modules live in a folder: each sub-folder is a library "
                                      "folder, each .py file one module. Starters and plugins add theirs too.")
        self.library_path = label("", "mono", wrap=True)
        self.library_choose = button("Choose folder…", icon="folder")
        self.library_choose.clicked.connect(self._choose_library)
        self.library_open = button("Open", "ghost")
        self.library_open.clicked.connect(self._open_library)
        self.library_reload = button("Read again", "ghost")
        self.library_reload.clicked.connect(self._reload_library)
        card.body.addWidget(self.library_path)
        card.body.addLayout(hbox(self.library_choose, self.library_open, self.library_reload, None))
        self.library_summary = label("", "caption", wrap=True)
        card.body.addWidget(self.library_summary)
        self.library_problems = label("", "error", wrap=True)
        card.body.addWidget(self.library_problems)
        self.column.addWidget(card)
        if self.workspace is not None:
            self.workspace.library_changed.connect(self._show_library)
            self.workspace.plugins.changed.connect(self._show_library)
        self._show_library()

    def _show_library(self) -> None:
        ws = self.workspace
        folder = ws.library_folder if ws is not None else None
        self.library_path.setText(str(folder) if folder else "No folder chosen")
        self.library_open.setEnabled(bool(folder))
        self.library_reload.setEnabled(bool(folder))
        if ws is None:
            self.library_summary.setText("")
            self.library_problems.hide()
            return
        by_folder: dict[str, int] = {}
        for e in ws.registry.entries(Library.MODULES):
            by_folder[e.name.rpartition("/")[0] or "other"] = by_folder.get(e.name.rpartition("/")[0] or "other", 0) + 1
        parts = [f"{name} ({n})" for name, n in sorted(by_folder.items(), key=lambda kv: (kv[0] != "starter", kv[0]))]
        self.library_summary.setText("Library folders: " + (", ".join(parts) if parts else "none yet")
                                     + ("" if folder is None or Path(folder).is_dir() else
                                        ". The folder doesn't exist yet; it is made when you open it."))
        self.library_problems.setText("\n".join(ws.library_problems))
        self.library_problems.setVisible(bool(ws.library_problems))

    def _choose_library(self) -> None:
        start = str(self.workspace.library_folder or paths.library_folder()) if self.workspace else ""
        folder = QFileDialog.getExistingDirectory(self, "Module library folder", start)
        if folder and self.ctx is not None:
            self.ctx.save_library_folder(folder)

    def _open_library(self) -> None:
        folder = self.workspace.library_folder if self.workspace else None
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _reload_library(self) -> None:
        if self.workspace is not None:
            self.workspace.reload_library()

    # ---- plugins -----------------------------------------------------------------------
    def _build_plugins(self) -> None:
        self.plugins_card = Card("Plugins", "Plugins add data sources, generated data, modules and skins. "
                                            "Switching one off removes what it adds; the rest carry on.")
        self.import_button = button("Import pack…", icon="import",
                                    tip="Check a .tiplug file and add it to your plugins")
        self.import_button.clicked.connect(self._import_pack)
        self.plugins_card.add_action(self.import_button)
        self.plugin_list = QVBoxLayout()
        self.plugin_list.setSpacing(0)
        self.plugins_card.body.addLayout(self.plugin_list)
        self.plugin_rows: dict[str, ItemRow] = {}
        self.plugin_message = label("", "caption", wrap=True)
        self.plugin_message.hide()
        self.plugins_card.body.addWidget(self.plugin_message)
        folder = self.workspace.plugins.user_folder if self.workspace is not None else None
        self.import_button.setEnabled(folder is not None)
        self.plugins_card.body.addWidget(label(f"Plugins folder: {folder or paths.plugins_folder()}", "caption", wrap=True))
        self.column.addWidget(self.plugins_card)
        if self.workspace is not None:
            self.workspace.plugins.changed.connect(self._after_plugins_changed)
        self._show_plugins()

    def _show_plugins(self) -> None:
        while self.plugin_list.count():
            w = self.plugin_list.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.plugin_rows.clear()
        if self.workspace is None:
            return
        for i, st in enumerate(self.workspace.plugins.statuses()):
            if i:
                self.plugin_list.addWidget(divider())
            title = f"{st.name or st.id} {st.version}".strip()
            row = ItemRow(title, st.description)
            row.add_badge(badge("Built in" if st.source == "builtin" else "Yours", "neutral"))
            if st.on:
                row.add_badge(badge("On", "success"))
            elif st.switched_off:
                row.add_badge(badge("Off", "neutral"))
            else:
                row.add_badge(badge("Problem", "danger"))
                row.set_note(_sentence(st.reason))
            what = _counted(st.provides)
            if what and not row.note.isVisible():
                row.set_note(f"Adds {what}.")
            switch = Switch(not st.switched_off, tip="Switch this plugin on or off")
            switch.setEnabled(not st.reason.startswith("the id "))  # a duplicate folder can't be switched
            switch.toggled.connect(lambda on, pid=st.id: self._switch_plugin(pid, on))
            row.add_control(switch)
            row.switch = switch
            self.plugin_list.addWidget(row)
            self.plugin_rows[st.id] = row

    def _switch_plugin(self, plugin_id: str, on: bool) -> None:
        if self.workspace is not None:
            self.workspace.plugins.set_enabled(plugin_id, on)  # reloads; changed rebuilds the list

    def _after_plugins_changed(self) -> None:
        skins.load_plugin_entries(self.workspace.registry.entries(Library.SKINS))
        self._fill_skins()
        self._describe_skin()
        self._show_plugins()

    def _import_pack(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import plugin pack", str(Path.home()),
                                              "Plugin packs (*.tiplug);;All files (*)")
        if path:
            self.import_pack(path)

    def import_pack(self, path: str, replace: bool = True) -> bool:
        """Check a .tiplug and install it into the plugins folder; show what happened."""
        from ...plugins import pack

        mgr = self.workspace.plugins
        rep = pack.install(path, replace=replace, run_tests=False, plugins=mgr.user_folder)
        if rep.ok:
            mgr.load()
            self._message(f"Imported {rep.name} {rep.version}.", "caption")
        else:
            self._message(f"Couldn't import {Path(path).name}: " + "; ".join(rep.failed), "error")
        return rep.ok

    def _message(self, text: str, role: str) -> None:
        self.plugin_message.setText(text)
        self.plugin_message.setProperty("role", role)
        self.plugin_message.style().unpolish(self.plugin_message)
        self.plugin_message.style().polish(self.plugin_message)
        self.plugin_message.setVisible(bool(text))

    # ---- layout ------------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.layout_card = Card("Layout", "Every panel can be a page or a dock. Pages fill the main area; "
                                          "docks sit beside the current page.")
        self.layout_grid = QGridLayout()
        self.layout_grid.setHorizontalSpacing(S["xl"])
        self.layout_grid.setVerticalSpacing(S["sm"])
        self.layout_card.body.addLayout(self.layout_grid)
        self.host_boxes: dict[str, QComboBox] = {}
        self.column.addWidget(self.layout_card)

    def show_layout(self, shell) -> None:
        """Fill the Layout card from the shell (called once the window exists, and on every move)."""
        while self.layout_grid.count():
            w = self.layout_grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.host_boxes.clear()
        for r, spec in enumerate(shell.registry.specs()):
            self.layout_grid.addWidget(label(spec.title), r, 0)
            box = QComboBox()
            box.addItem("Page", PAGE)
            box.addItem("Dock", DOCK)
            box.setCurrentIndex(0 if shell.hosts[spec.view_id] == PAGE else 1)
            box.setFixedWidth(140)
            box.currentIndexChanged.connect(lambda _i, v=spec.view_id, b=box: shell.move_view(v, b.currentData()))
            self.layout_grid.addWidget(box, r, 1)
            where = ", ".join(p.title() for p in spec.pages) if spec.pages else "every page"
            self.layout_grid.addWidget(label(f"as a dock, shows on {where}", "caption"), r, 2)
            self.host_boxes[spec.view_id] = box
        self.layout_grid.setColumnStretch(2, 1)


class MarketRow(QWidget):
    """One market: its sessions and holidays, and its defaults to edit."""

    def __init__(self, market: Market, own: MarketDefaults, on_change, parent=None):
        super().__init__(parent)
        self.market, self.own, self.on_change = market, own, on_change
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(S["sm"])
        d = market.defaults
        col.addLayout(hbox(label(market.name, "title"), badge(market.currency), None))
        col.addWidget(label(f"{sessions_text(market)}, {tz_name(market.tz)} time", "muted", wrap=True))
        if market.notes:
            col.addWidget(label(market.notes, "caption", wrap=True))
        year = date.today().year
        n = len(market.holidays(year))
        self.holidays = label(holidays_text(market, year), "mono", wrap=True)
        self.holidays.hide()
        self.holidays_button = button(f"Holidays in {year} ({n})", "ghost", tip="Days without a trading day")
        self.holidays_button.setCheckable(True)
        self.holidays_button.toggled.connect(self.holidays.setVisible)
        col.addLayout(hbox(self.holidays_button, None))
        col.addWidget(self.holidays)

        grid = QGridLayout()
        grid.setHorizontalSpacing(S["xl"])
        grid.setVerticalSpacing(S["md"])
        self.extended = Switch(d.extended_hours, "Trade outside the regular session too")
        self.decide_at = QTimeEdit(QTime.fromString(d.decide_at, "HH:mm"))
        self.decide_at.setDisplayFormat("HH:mm")
        self.decide_at.setFixedWidth(FIELD_WIDTH)
        self.decide_at.setToolTip("When strategies decide, in the market's local time.")
        self.hours = label("", "caption")
        left = [("All sessions", hbox(self.extended, self.hours, None)), ("Decides at", self.decide_at)]
        self._say_hours()
        self.half_spread = _number(d.half_spread_bps, 0, 1_000, decimals=2, step=0.5, suffix=" bps")
        self.half_spread.setToolTip("Half the bid-ask spread paid on each fill, in basis points of the price.")
        self.slippage = _number(d.slippage_bps, 0, 1_000, decimals=2, step=0.5, suffix=" bps")
        self.slippage.setToolTip("Slippage on each fill, in basis points of the price.")
        self.commission = _number(d.commission_per_share, 0, 10, decimals=4, step=0.001, suffix=" per share")
        self.futures_commission = _number(d.futures_commission, 0, 100, decimals=2, step=0.05, suffix=" per side")
        self.futures_commission.setToolTip("Commission per contract per side, in currency.")
        self.futures_slippage = _number(d.futures_slippage_ticks, 0, 100, decimals=1, step=0.5, suffix=" ticks")
        right = []
        if market.trades("stock"):
            right += [("Stock half spread", self.half_spread), ("Stock slippage", self.slippage),
                      ("Stock commission", self.commission)]
        if market.trades("future"):
            right += [("Futures commission", self.futures_commission), ("Futures slippage", self.futures_slippage)]
        for c, rows in ((0, left), (2, right)):
            for r, (text, w) in enumerate(rows):
                grid.addWidget(label(text, "label"), r, c)
                if isinstance(w, QWidget):
                    grid.addWidget(w, r, c + 1)
                else:
                    grid.addLayout(w, r, c + 1)
        grid.setColumnStretch(4, 1)
        col.addLayout(grid)
        self.reset = button("Use the market's own", "ghost", tip="Go back to the defaults this market comes with")
        self.reset.clicked.connect(self.use_own)
        col.addLayout(hbox(self.reset, None))
        self.reset.setVisible(d != own)

        for w in (self.half_spread, self.slippage, self.commission, self.futures_commission, self.futures_slippage):
            w.valueChanged.connect(self._changed)
        self.extended.toggled.connect(self._changed)
        self.extended.toggled.connect(self._say_hours)
        self.decide_at.timeChanged.connect(self._changed)

    def _say_hours(self, *_):
        reg = self.market.session()
        self.hours.setText("On: runs trade every session" if self.extended.isChecked()
                           else f"Off: regular hours only ({reg.start:%H:%M}–{reg.end:%H:%M})")

    def defaults(self) -> MarketDefaults:
        return MarketDefaults(extended_hours=self.extended.isChecked(),
                              decide_at=self.decide_at.time().toString("HH:mm"),
                              half_spread_bps=self.half_spread.value(), slippage_bps=self.slippage.value(),
                              commission_per_share=self.commission.value(),
                              futures_commission=self.futures_commission.value(),
                              futures_slippage_ticks=self.futures_slippage.value())

    def show_defaults(self, d: MarketDefaults) -> None:
        widgets = (self.extended, self.decide_at, self.half_spread, self.slippage, self.commission,
                   self.futures_commission, self.futures_slippage)
        for w in widgets:
            w.blockSignals(True)
        self.extended.setChecked(d.extended_hours)
        self.decide_at.setTime(QTime.fromString(d.decide_at, "HH:mm"))
        self.half_spread.setValue(d.half_spread_bps)
        self.slippage.setValue(d.slippage_bps)
        self.commission.setValue(d.commission_per_share)
        self.futures_commission.setValue(d.futures_commission)
        self.futures_slippage.setValue(d.futures_slippage_ticks)
        for w in widgets:
            w.blockSignals(False)
        self.extended.update()
        self._say_hours()
        self.reset.setVisible(d != self.own)

    def use_own(self) -> None:
        self.show_defaults(self.own)
        self.on_change(self.market.id, None)

    def _changed(self, *_):
        d = self.defaults()
        self.reset.setVisible(d != self.own)
        self.on_change(self.market.id, None if d == self.own else d)


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(S["xl"])
    form.setVerticalSpacing(S["md"])
    return form


def _number(value: float, lo: float, hi: float, decimals: int, step: float, suffix: str) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setFixedWidth(FIELD_WIDTH)
    w.setDecimals(decimals)
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    w.setGroupSeparatorShown(True)
    w.setValue(value)
    return w


WORDS = {"data_sources": ("data source", "data sources"), "generators": ("generator", "generators"),
         "modules": ("module", "modules"), "skins": ("skin", "skins"), "measurements": ("measurement", "measurements"),
         "backtests": ("backtest", "backtests"), "strategies": ("strategy", "strategies")}


def _counted(provides: dict[str, list[str]]) -> str:
    """{"data_sources": ["a", "b"], "modules": ["m"]} -> "2 data sources, 1 module"."""
    parts = []
    for lib, names in provides.items():
        if names:
            one, many = WORDS.get(lib, (lib.replace("_", " "), lib.replace("_", " ")))
            parts.append(f"{len(names)} {one if len(names) == 1 else many}")
    return ", ".join(parts)


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith(".") else text + "."
