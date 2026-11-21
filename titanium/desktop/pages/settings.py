"""Settings, tucked in the corner of the navigation rail.

Appearance and Skin set the look. Defaults for every run are what the engine starts a
run with (``Workspace.run_defaults``). Module library sets the folder the library's own
modules are read from. Plugins lists every plugin, on or off and why, switches them,
and imports ``.tiplug`` packs. Layout shows where every view lives (page or dock).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QVBoxLayout

from ...app import paths
from ...app.settings import TIMEFRAMES, RunDefaults
from ...core.plugins import Library
from ..design import skins, theme
from ..design import tokens as T
from ..design.components import Card, ItemRow, Segmented, Switch, badge, button, divider, hbox, label
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
        self._build_library()
        self._build_plugins()
        self._build_layout()
        self.column.addStretch()

    def subtitle(self) -> str:
        return "Appearance, run defaults, the module library, plugins and layout."

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
        card = Card("Defaults for every run", "What a new run starts with. A strategy or a backtest can change "
                                              "any of them for itself.")
        d = self.workspace.run_defaults if self.workspace is not None else RunDefaults()
        form = _form()
        self.capital = _number(d.capital, 1, 1e12, decimals=0, step=10_000, suffix="")
        self.capital.setToolTip("Notional starting cash, in the market's currency. Results are shown normalised.")
        form.addRow(label("Capital", "label"), self.capital)
        self.commission = _number(d.commission_bps, 0, 1_000, decimals=2, step=0.5, suffix=" bps")
        self.commission.setToolTip("Commission per trade, in basis points of the traded value.")
        form.addRow(label("Commission", "label"), self.commission)
        self.slippage = _number(d.slippage_bps, 0, 1_000, decimals=2, step=0.5, suffix=" bps")
        self.slippage.setToolTip("Slippage per trade, in basis points of the traded value.")
        form.addRow(label("Slippage", "label"), self.slippage)
        self.timeframes = list(TIMEFRAMES)
        self.timeframe = Segmented([TIMEFRAMES[t] for t in self.timeframes])
        self.timeframe.group.button(self.timeframes.index(d.timeframe)).setChecked(True)
        form.addRow(label("Time frame", "label"), self.timeframe)
        card.body.addLayout(form)
        for w in (self.capital, self.commission, self.slippage):
            w.valueChanged.connect(self._save_run_defaults)
        self.timeframe.changed.connect(self._save_run_defaults)
        self.column.addWidget(card)

    def run_defaults(self) -> RunDefaults:
        return RunDefaults(capital=self.capital.value(), commission_bps=self.commission.value(),
                           slippage_bps=self.slippage.value(), timeframe=self.timeframes[self.timeframe.index()])

    def _save_run_defaults(self, *_):
        if self.ctx is not None:
            self.ctx.save_run_defaults(self.run_defaults())

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
