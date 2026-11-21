"""Data page: the datasets strategies run on.

Each dataset shows where it comes from, what it holds, which strategies use it and
where it is stored. Data is grouped as core (prices), complementary (known over
time) and generated (made from other data).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFileDialog, QListWidget, QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget

from ...app.datasets import DataKind, DatasetInUse, DatasetInfo, Frequency
from .. import tasks
from ..design import tokens as T
from ..design.components import (
    Card, DataTable, Details, Dialog, EmptyState, ParamForm, SearchField, Segmented, badge, button, hbox, label,
)
from ._base import PageView

S = T.SPACE

KINDS = (
    (DataKind.CORE, "Core", "Prices of the instruments strategies trade.", "brand"),
    (DataKind.COMPLEMENTARY, "Complementary", "Data known over time: news, events, fundamentals.", "primary"),
    (DataKind.GENERATED, "Generated", "Made from other data by generators: features, indicators.", "neutral"),
)
KIND_NAME = {k: name for k, name, _t, _b in KINDS}
KIND_BADGE = {k: b for k, _n, _t, b in KINDS}
FILTERS = (None, DataKind.CORE, DataKind.COMPLEMENTARY, DataKind.GENERATED)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class DataView(PageView):
    view_id = "data"
    title = "Data"
    icon = "data"
    order = 10
    background = True  # load data on a worker thread (tests turn this off)

    def __init__(self, app_ctx=None, parent=None):
        super().__init__(app_ctx, parent)
        self.service = self.ctx.workspace.datasets if self.ctx is not None else None

        row = hbox(spacing=S["lg"])
        self.kind_counts: dict[DataKind, object] = {}
        for kind, name, text, b in KINDS:
            card = Card()
            card.body.setSpacing(S["xs"])
            count = badge("0 datasets", b)
            self.kind_counts[kind] = count
            card.body.addLayout(hbox(label(name, "title"), None, count))
            card.body.addWidget(label(text, "muted", wrap=True))
            row.addWidget(card, 1)
        self.column.addLayout(row)

        self.filter = Segmented(["All", "Core", "Complementary", "Generated"])
        self.filter.changed.connect(lambda _i: self.refresh())
        self.search = SearchField("Search datasets")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.column.addLayout(hbox(self.filter, None, self.search))

        self.stack = QStackedWidget()
        self.empty = EmptyState(
            "data", "No datasets yet",
            "A dataset records where its data comes from, what it holds, where it is stored, "
            "and which strategies use it. Start with synthetic data, or import your own files.",
            [self._add_button("Add dataset", "primary", "plus"), self._import_button()])
        self.stack.addWidget(self.empty)

        body = QWidget()
        split = hbox(spacing=S["lg"])
        body.setLayout(split)
        self.table = DataTable(["Name", "Kind", "Contents", "Range", "Size", "Used by"], stretch=0)
        self.table.selected.connect(self.show_details)
        split.addWidget(self.table, 3)
        self.details = DatasetCard(self)
        self.details.setFixedWidth(380)
        split.addWidget(self.details)
        self.stack.addWidget(body)
        self.no_match = EmptyState("search", "Nothing matches", "Try another filter or search.")
        self.stack.addWidget(self.no_match)
        self.column.addWidget(self.stack, 1)

        if self.service is not None:
            for ev in (self.service.added, self.service.changed, self.service.removed):
                ev.connect(lambda *_: self.refresh())
            ws = self.ctx.workspace
            for ev in (ws.strategies.added, ws.strategies.changed, ws.strategies.removed):
                ev.connect(lambda *_: self.refresh())
        self.refresh()

    # ---- header -------------------------------------------------------------------
    def subtitle(self) -> str:
        return "Where data comes from, what it holds, where it is stored, and who uses it."

    def actions_bar(self):
        return [self._import_button(), self._add_button("Add dataset", "primary", "plus")]

    def _add_button(self, text, variant, icon):
        b = button(text, variant, icon)
        b.clicked.connect(lambda: self.open_add())
        return b

    def _import_button(self):
        b = button("Import files", icon="import")
        b.clicked.connect(self.pick_files)
        return b

    # ---- the list --------------------------------------------------------------------
    def visible(self) -> list[DatasetInfo]:
        if self.service is None:
            return []
        kind = FILTERS[self.filter.index()]
        items = self.service.infos(kind)
        q = self.search.text().strip().lower()
        if q:
            items = [i for i in items if q in i.name.lower() or any(q in s.lower() for s in i.instruments)]
        return items

    def refresh(self) -> None:
        if self.service is None:
            return
        for kind, n in self.service.counts().items():
            self.kind_counts[kind].setText(plural(n, "dataset"))
        items = self.visible()
        if not len(self.service):
            self.stack.setCurrentWidget(self.empty)
            return
        if not items:
            self.stack.setCurrentWidget(self.no_match)
            return
        self.stack.setCurrentIndex(1)
        rows = [(i.name, KIND_NAME[i.kind], self.contents(i, short=True), self.range_text(i, short=True),
                 human_size(i.size_bytes), self.users_text(i)) for i in items]
        keys = [i.id for i in items]
        self.table.set_rows(rows, keys)
        current = self.table.selected_key()
        if current is None or current not in keys:
            self.table.select(keys[0])
        self.show_details(self.table.selected_key())

    # ---- describing a dataset ----------------------------------------------------------
    def contents(self, info: DatasetInfo, short: bool = False) -> str:
        n = len(info.instruments)
        if info.kind is DataKind.CORE:
            freq = {Frequency.MINUTE: "minute bars", Frequency.DAILY: "daily bars"}.get(info.frequency, "bars")
            noun = "instrument"
            if info.instruments and all(":SYN" in k for k in info.instruments):
                noun = "stock"
            return f"{plural(n, noun)}, {freq}"
        series = info.series or info.fields
        what = ", ".join(series) if not short or len(series) <= 1 else plural(len(series), "series")
        return f"{what} for {plural(n, 'instrument')}" if n else what

    def range_text(self, info: DatasetInfo, short: bool = False) -> str:
        if info.start is None or info.end is None:
            return "Empty"
        tz = self.service.market(info.id).tz
        a, b = info.start.astimezone(tz), info.end.astimezone(tz)
        if short:
            return f"{a:%Y-%m-%d} to {b:%Y-%m-%d}"
        fmt = "%d %b %Y %H:%M" if info.frequency is Frequency.MINUTE else "%d %b %Y"
        return f"{a.strftime(fmt).lstrip('0')} to {b.strftime(fmt).lstrip('0')}, {self._tz_name(tz)} time"

    @staticmethod
    def _tz_name(tz) -> str:
        return str(tz).split("/")[-1].replace("_", " ")

    def strategy_name(self, sid: str) -> str:
        ws = self.ctx.workspace
        if sid in ws.strategies:
            return getattr(ws.strategies.get(sid), "name", "") or sid
        return sid

    def users_text(self, info: DatasetInfo) -> str:
        return ", ".join(self.strategy_name(s) for s in info.used_by) or "None yet"

    def source_text(self, info: DatasetInfo) -> str:
        reg = self.service
        name = info.source.plugin
        obj = None
        for getter in (reg.source, reg.generator):
            try:
                obj = getter(name)
                break
            except KeyError:
                continue
        title = getattr(obj, "title", name)
        params = info.source.params
        if name == "file_import":
            files = [p for p in str(params.get("paths", "")).split(";") if p]
            return f"{title}: " + (Path(files[0]).name if len(files) == 1 else plural(len(files), "file"))
        if info.kind is DataKind.GENERATED and info.inputs:
            made_from = ", ".join(self.service.get(i).name for i in info.inputs if i in self.service)
            bits = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in params.items())
            return f"{title} ({bits}) from {made_from or 'a removed dataset'}"
        seed = f" · seed {params['seed']}" if "seed" in params else ""
        edge = [k for k in ("gap_momentum", "orb_momentum", "trend_strength") if params.get(k)]
        return f"{title}{seed}" + (" · planted edge" if edge else " · no edge" if "seed" in params else "")

    # ---- details -------------------------------------------------------------------------
    def show_details(self, dataset_id: str | None) -> None:
        if dataset_id is None or self.service is None or dataset_id not in self.service:
            return
        self.details.show_info(self.service.get(dataset_id))

    # ---- flows -------------------------------------------------------------------------------
    def open_add(self, source: str | None = None, values: dict | None = None) -> "AddDatasetDialog":
        dlg = AddDatasetDialog(self, source, values)
        dlg.open()
        return dlg

    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Import files", "", "Data files (*.csv *.parquet *.pq)")
        if files:
            self.open_add("file_import", {"paths": ";".join(files)})

    def open_generate(self, dataset_id: str) -> "GenerateDialog":
        dlg = GenerateDialog(self, dataset_id)
        dlg.open()
        return dlg

    def remove(self, dataset_id: str, confirm: bool = True) -> bool:
        info = self.service.get(dataset_id)
        if confirm:
            dlg = Dialog("Remove dataset", f"Remove {info.name} and delete its files from {info.storage}? "
                         "This can't be undone.", "Remove")
            dlg.ok.setProperty("variant", "danger")
            if dlg.exec() != Dialog.Accepted:
                return False
        try:
            self.service.remove(dataset_id)
        except DatasetInUse as exc:
            self.details.set_error(f"Can't remove it yet: {exc}.")
            return False
        return True

    def build(self, job, dialog: Dialog | None = None, on_done=None) -> None:
        """Run ``job`` (returns a built DatasetInfo) in the background, then add it to the workspace."""
        if dialog is not None:
            dialog.set_busy(True, "Making the dataset…")

        def done(info):
            self.service.commit(info)
            self.table.select(info.id)
            self.show_details(info.id)
            if dialog is not None:
                dialog.set_busy(False)
                dialog.accept()
            if on_done:
                on_done(info)

        def failed(exc):
            if dialog is not None:
                dialog.set_busy(False)
                dialog.set_error(str(exc) or exc.__class__.__name__)
            else:
                self.details.set_error(str(exc))

        tasks.run(job, done, failed, self.background)


class DatasetCard(Card):
    """The selected dataset: where it comes from, what it holds, who uses it, where it lives."""

    def __init__(self, page: DataView):
        super().__init__()
        self.page = page
        self.info: DatasetInfo | None = None
        self.name = label("", "title", wrap=True)
        self.kind = badge("", "neutral")
        self.body.addLayout(hbox(self.name, None, self.kind))
        self.notes = label("", "caption", wrap=True)
        self.body.addWidget(self.notes)
        self.fields = Details()
        self.body.addWidget(self.fields, 1)
        self.error = label("", "error", wrap=True)
        self.error.hide()
        self.body.addWidget(self.error)
        self.generate = button("Generate", icon="plus", tip="Make generated data (features, indicators) from this dataset")
        self.generate.clicked.connect(lambda: self.info and page.open_generate(self.info.id))
        self.folder = button("Show folder", "ghost", "folder")
        self.folder.clicked.connect(lambda: self.info and QDesktopServices.openUrl(QUrl.fromLocalFile(self.info.storage)))
        self.remove = button("Remove", "danger")
        self.remove.clicked.connect(lambda: self.info and page.remove(self.info.id))
        self.body.addLayout(hbox(self.generate, self.folder, None, self.remove))

    def set_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def show_info(self, info: DatasetInfo) -> None:
        p = self.page
        self.info = info
        self.set_error("")
        self.name.setText(info.name)
        self.kind.setText(KIND_NAME[info.kind])
        self.kind.setProperty("badge", KIND_BADGE[info.kind])
        self.kind.style().unpolish(self.kind)
        self.kind.style().polish(self.kind)
        self.notes.setText(info.notes)
        users = [p.strategy_name(s) for s in info.used_by]
        used = hbox(*[badge(u, "brand") for u in users], None) if users else \
            label("No strategy uses it yet. Strategies choose their data in their settings.", "muted", wrap=True)
        instruments = info.instruments
        listed = ", ".join(k.split(":")[-1] for k in instruments[:8]) + (" …" if len(instruments) > 8 else "")
        rows = [
            ("Source", p.source_text(info)),
            ("Contents", p.contents(info) + (f"\n{listed}" if listed else "")),
            ("Fields", ", ".join(info.fields) or "None"),
            ("Range", p.range_text(info)),
            ("Used by", used),
            ("Storage", label(f"{info.storage}\n{human_size(info.size_bytes)} · version {info.version}", "mono", wrap=True)),
        ]
        self.fields.set_rows(rows)
        self.generate.setVisible(info.kind is DataKind.CORE)


class AddDatasetDialog(Dialog):
    """Pick a data source, fill in its settings, and make the dataset."""

    def __init__(self, page: DataView, source: str | None = None, values: dict | None = None):
        super().__init__("Add dataset", "Choose where the data comes from. Synthetic data has no edge "
                         "unless you plant one, which is how Titanium tests its own tests.", "Add dataset", page)
        self.page = page
        self.resize(760, 520)
        self.sources = [s for s in page.service.sources()]
        self.list = QListWidget()
        self.list.setFixedWidth(240)
        for s in self.sources:
            item = QListWidgetItem(s.title + ("" if getattr(s, "available", True) else "  (coming later)"))
            item.setToolTip(getattr(s, "doc", ""))
            if not getattr(s, "available", True):
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(item)
        self.forms = QStackedWidget()
        self.form_for: dict[str, ParamForm] = {}
        self.docs: dict[str, str] = {}
        for s in self.sources:
            params = list(s.params) if any(q.name == "name" for q in s.params) else list(s.params) + [_NameParam()]
            form = ParamForm(params, values if s.name == source else None)
            self.form_for[s.name] = form
            self.forms.addWidget(form)
        self.doc = label("", "muted", wrap=True)
        right = QWidget()
        col = hbox(spacing=S["lg"])
        right_col = _vbox(self.doc, self.forms)
        right.setLayout(right_col)
        col.addWidget(self.list)
        col.addWidget(right, 1)
        self.body.addLayout(col)
        self.list.currentRowChanged.connect(self._pick)
        start = next((i for i, s in enumerate(self.sources) if s.name == source), 0)
        if not getattr(self.sources[start], "available", True):
            start = next((i for i, s in enumerate(self.sources) if getattr(s, "available", True)), 0)
        self.list.setCurrentRow(start)
        self.ok.clicked.connect(self.submit)

    def current(self):
        return self.sources[self.list.currentRow()]

    def _pick(self, row: int) -> None:
        if row < 0:
            return
        s = self.sources[row]
        self.forms.setCurrentWidget(self.form_for[s.name])
        self.doc.setText(getattr(s, "doc", ""))
        self.ok.setEnabled(getattr(s, "available", True))
        self.ok.setText("Import" if s.name == "file_import" else "Add dataset")
        self.set_error("")

    def values(self) -> dict:
        return self.form_for[self.current().name].values()

    def submit(self) -> None:
        s = self.current()
        params = self.values()
        name = str(params.get("name", "")).strip()
        if s.name != "file_import":
            params.pop("name", None)
        elif not params.get("paths"):
            self.set_error("Choose one or more files first.")
            return
        service = self.page.service
        self.page.build(lambda: service.build(s.name, params, name), self)


class GenerateDialog(Dialog):
    """Make generated data (features, indicators) from a core dataset."""

    def __init__(self, page: DataView, dataset_id: str):
        base = page.service.get(dataset_id)
        super().__init__("Make generated data", f"From {base.name}. Each value is stamped with the time it "
                         "could first be computed, so strategies never see it early.", "Make data", page)
        self.page, self.dataset_id = page, dataset_id
        self.resize(520, 360)
        self.gens = page.service.generators()
        self.choice = QComboBox()
        self.choice.addItems([g.title for g in self.gens])
        self.body.addWidget(self.choice)
        self.doc = label("", "muted", wrap=True)
        self.body.addWidget(self.doc)
        self.forms = QStackedWidget()
        for g in self.gens:
            self.forms.addWidget(ParamForm(list(g.params) + [_NameParam()]))
        self.body.addWidget(self.forms)
        self.choice.currentIndexChanged.connect(self._pick)
        self._pick(0)
        self.ok.clicked.connect(self.submit)

    def _pick(self, i: int) -> None:
        self.forms.setCurrentIndex(i)
        self.doc.setText(getattr(self.gens[i], "doc", ""))

    def submit(self) -> None:
        g = self.gens[self.choice.currentIndex()]
        params = self.forms.currentWidget().values()
        name = str(params.pop("name", "")).strip()
        service = self.page.service
        self.page.build(lambda: service.build_generated(g.name, self.dataset_id, params, name), self)


class _NameParam:
    name, type, default, label = "name", "str", "", "Dataset name"
    help = "Leave empty for a name made from the settings."
    choices, minimum, maximum = (), None, None


def _vbox(*widgets):
    lay = QVBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(S["md"])
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch()
    return lay
