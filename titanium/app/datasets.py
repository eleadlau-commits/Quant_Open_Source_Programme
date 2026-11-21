"""The dataset service: ``Workspace.datasets``.

Adds datasets from data sources, imports files, makes generated data, removes
datasets, and tracks which strategies use each one. It is a :class:`Collection`
of :class:`DatasetInfo`, so views hear about every change, and it saves the
catalogue to the data folder after each one.

Long work (loading a source, writing Parquet) is split from announcing it:
``build`` / ``build_generated`` can run on a worker thread, then ``commit`` on the
UI thread puts the dataset in the collection. ``add``, ``import_files`` and
``generate`` do both in one call.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..core.bars import BarStore, MarketData
from ..core.data import DataKind, DatasetInfo, Frequency, SourceSpec
from ..core.generators import register_generators
from ..core.guard import Guard
from ..core.markets import MARKETS, NASDAQ
from ..core.plugins import Library, Registry
from ..core.sources import register_sources
from .events import Event
from .collection import Collection


__all__ = ["DataKind", "DatasetInUse", "DatasetInfo", "DatasetService", "Frequency"]


class DatasetInUse(RuntimeError):
    """Raised when removing a dataset that strategies or generated datasets still need."""


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:32] or "dataset"


class DatasetService(Collection[DatasetInfo]):
    def __init__(self, registry: Registry, root: Path | str | None = None) -> None:
        super().__init__()
        self.registry = registry
        register_sources(registry)
        register_generators(registry)
        self._root = Path(root) if root is not None else None
        self._store: BarStore | None = None
        self._open: dict[str, MarketData] = {}
        self.usage_changed = Event()  # (dataset_id,)
        if self._root is not None:
            for info in self.store.catalogue():
                self._items[info.id] = info

    # ---- where datasets live ------------------------------------------------------
    @property
    def root(self) -> Path:
        """The data folder. Without one, a temporary folder for this session only."""
        if self._root is None:
            self._root = Path(tempfile.mkdtemp(prefix="titanium-data-"))
        return self._root

    @property
    def store(self) -> BarStore:
        if self._store is None:
            self._store = BarStore(self.root)
        return self._store

    def _save(self) -> None:
        self.store.save_catalogue(self.infos())

    # ---- what can be added ----------------------------------------------------------
    def sources(self) -> list:
        """Data sources, ready ones first, in their preferred order."""
        objs = [e.obj for e in self.registry.entries(Library.DATA_SOURCES)]
        return sorted(objs, key=lambda o: (not getattr(o, "available", True), getattr(o, "order", 50)))

    def source(self, name: str):
        return self.registry.get(Library.DATA_SOURCES, name)

    def generators(self) -> list:
        return [e.obj for e in self.registry.entries(Library.GENERATORS)]

    def generator(self, name: str):
        return self.registry.get(Library.GENERATORS, name)

    # ---- reading ------------------------------------------------------------------------
    def infos(self, kind: DataKind | str | None = None) -> list[DatasetInfo]:
        items = list(self._items.values())
        if kind is not None:
            items = [i for i in items if i.kind is DataKind(kind)]
        return sorted(items, key=lambda i: (list(DataKind).index(i.kind), i.name.lower()))

    def counts(self) -> dict[DataKind, int]:
        out = {k: 0 for k in DataKind}
        for i in self._items.values():
            out[i.kind] += 1
        return out

    def open(self, dataset_id: str) -> MarketData:
        """The dataset's data (files are read when first used)."""
        if dataset_id not in self._open:
            info = self.get(dataset_id)
            self._open[dataset_id] = self.store.open(dataset_id, info.name)
        return self._open[dataset_id]

    def view(self, dataset_ids: str | Iterable[str], as_of) -> Guard:
        """A guarded view over one or more datasets (the first sets the market)."""
        ids = [dataset_ids] if isinstance(dataset_ids, str) else list(dataset_ids)
        data = self.open(ids[0]).combine(*(self.open(i) for i in ids[1:]))
        return Guard(data, as_of)

    def market(self, dataset_id: str):
        """The market (calendar, time zone) a dataset follows."""
        return MARKETS.get(self.get(dataset_id).market, NASDAQ)

    def dependents(self, dataset_id: str) -> list[str]:
        """Generated datasets made from this one."""
        return [i.id for i in self._items.values() if dataset_id in i.inputs]

    # ---- adding -----------------------------------------------------------------------------
    def new_id(self, name: str) -> str:
        while True:
            candidate = f"{_slug(name)}-{uuid.uuid4().hex[:6]}"
            if candidate not in self._items:
                return candidate

    def build(self, source: str, params: dict[str, Any] | None = None, name: str = "") -> DatasetInfo:
        """Load a source and write it to the data folder. Safe off the UI thread; announces nothing."""
        src = self.source(source)
        if not getattr(src, "available", True):
            raise NotImplementedError(f"{getattr(src, 'title', source)} is not available yet")
        spec = SourceSpec(source, src.resolve(params or {}) if hasattr(src, "resolve") else dict(params or {}))
        info = src.describe(spec)
        info.name = name or info.name
        info.id = self.new_id(info.name)
        data = src.load(spec)
        if info.kind is DataKind.CORE and info.frequency is None:
            info.frequency = Frequency.MINUTE if any(data.has_minutes(k) for k in data.instruments) else Frequency.DAILY
        info.created = datetime.now(timezone.utc)
        return self.store.write(info, data)

    def build_generated(self, generator: str, input_id: str, params: dict[str, Any] | None = None,
                        name: str = "") -> DatasetInfo:
        gen = self.generator(generator)
        params = {p.name: (params or {}).get(p.name, p.default) for p in gen.params}
        base = self.get(input_id)
        series = gen.generate(self.open(input_id), params)
        title = name or f"{gen.title} of {base.name}"
        data = MarketData(base.market, series=series, name=title)
        info = DatasetInfo(id=self.new_id(title), name=title, kind=DataKind.GENERATED,
                           source=SourceSpec(generator, params), frequency=Frequency.DAILY,
                           inputs=[input_id], notes=getattr(gen, "doc", ""),
                           created=datetime.now(timezone.utc))
        info = self.store.write(info, data)
        info.instruments = sorted({c for f in series.values() for c in f.columns if c != "value"})
        info.fields = sorted(series)
        return info

    def commit(self, info: DatasetInfo) -> DatasetInfo:
        """Put a built dataset in the workspace (on the UI thread) and save the catalogue."""
        self._open.pop(info.id, None)
        self.put(info.id, info)
        self._save()
        return info

    def add(self, source: str, params: dict[str, Any] | None = None, name: str = "") -> DatasetInfo:
        return self.commit(self.build(source, params, name))

    def import_files(self, paths: str | list[str], kind: DataKind | str = DataKind.CORE, market: str = "xnas",
                     timezone: str = "", name: str = "") -> DatasetInfo:
        if isinstance(paths, (list, tuple)):
            paths = ";".join(str(p) for p in paths)
        params = {"paths": str(paths), "kind": DataKind(kind).value, "market": market,
                  "timezone": timezone, "name": name}
        return self.add("file_import", params, name)

    def generate(self, generator: str, input_id: str, params: dict[str, Any] | None = None,
                 name: str = "") -> DatasetInfo:
        return self.commit(self.build_generated(generator, input_id, params, name))

    def rename(self, dataset_id: str, name: str) -> None:
        info = self.get(dataset_id)
        info.name = name
        self.put(dataset_id, info)
        self._save()

    # ---- removing -----------------------------------------------------------------------------
    def remove(self, id: str, force: bool = False) -> None:
        """Remove a dataset and its files. Refuses while it is in use unless ``force``."""
        if id not in self._items:
            return
        info = self._items[id]
        needed = info.used_by + self.dependents(id)
        if needed and not force:
            raise DatasetInUse(f"{info.name} is still used by {', '.join(needed)}")
        self._open.pop(id, None)
        self.store.delete(id)
        super().remove(id)
        self._save()

    # ---- who uses what ------------------------------------------------------------------------
    def use(self, dataset_id: str, strategy_id: str) -> None:
        info = self.get(dataset_id)
        if strategy_id not in info.used_by:
            info.used_by.append(strategy_id)
            self._usage(info)

    def release(self, dataset_id: str, strategy_id: str) -> None:
        info = self._items.get(dataset_id)
        if info is not None and strategy_id in info.used_by:
            info.used_by.remove(strategy_id)
            self._usage(info)

    def used_by(self, dataset_id: str) -> list[str]:
        return list(self.get(dataset_id).used_by)

    def uses_of(self, strategy_id: str) -> list[str]:
        return [i.id for i in self.infos() if strategy_id in i.used_by]

    def sync_strategy(self, strategy_id: str, dataset_ids: Iterable[str]) -> None:
        """Make the strategy's uses match ``dataset_ids`` (unknown ids are ignored)."""
        wanted = {d for d in dataset_ids if d in self._items}
        for d in self.uses_of(strategy_id):
            if d not in wanted:
                self.release(d, strategy_id)
        for d in sorted(wanted):
            self.use(d, strategy_id)

    def _usage(self, info: DatasetInfo) -> None:
        self.changed.emit(info.id, info)
        self.usage_changed.emit(info.id)
        self._save()
