"""Plugins add entries to the app's libraries.

A plugin is a folder with a ``plugin.json`` manifest. It may contribute to any
library: data sources, generated-data generators, patch-bay modules, strategies,
measurements, backtests, market models, and later brokers, views and exporters.
Removing one plugin never breaks the others. Plugins are trusted code, not a sandbox.

The registry is an object, not module-level state, so tests and the app each own one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

API_VERSION = 1


class Library(str, Enum):
    DATA_SOURCES = "data_sources"
    GENERATORS = "generators"
    MODULES = "modules"
    STRATEGIES = "strategies"
    MEASUREMENTS = "measurements"
    BACKTESTS = "backtests"
    MARKETS = "markets"
    BROKERS = "brokers"  # later: live engine
    VIEWS = "views"  # later: extra panels and editors
    EXPORTERS = "exporters"  # later


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    api: int = API_VERSION
    description: str = ""
    author: str = ""
    main: str | None = "plugin.py"
    provides: dict[str, list[str]] = field(default_factory=dict)  # Library value -> entry names
    requires: list[str] = field(default_factory=list)  # other plugin ids

    @classmethod
    def read(cls, folder: Path) -> "Manifest":
        data = json.loads((Path(folder) / "plugin.json").read_text(encoding="utf-8"))
        unknown = set(data.get("provides", {})) - {lib.value for lib in Library}
        if unknown:
            raise ValueError(f"plugin {data.get('id')!r} provides unknown libraries: {sorted(unknown)}")
        return cls(**data)


@dataclass
class Entry:
    library: Library
    name: str
    obj: Any
    plugin: str  # id of the plugin that added it ("" = the app itself)
    doc: str = ""


class Registry:
    """Every library's entries, by name, remembering which plugin added each."""

    def __init__(self) -> None:
        self._entries: dict[Library, dict[str, Entry]] = {lib: {} for lib in Library}

    def add(self, library: Library, name: str, obj: Any, plugin: str = "", doc: str = "") -> Entry:
        if name in self._entries[library]:
            raise ValueError(f"{library.value} entry {name!r} already exists")
        entry = Entry(library, name, obj, plugin, doc)
        self._entries[library][name] = entry
        return entry

    def get(self, library: Library, name: str) -> Any:
        try:
            return self._entries[library][name].obj
        except KeyError:
            known = ", ".join(sorted(self._entries[library])) or "none"
            raise KeyError(f"no {library.value} entry named {name!r} (known: {known})") from None

    def entries(self, library: Library) -> list[Entry]:
        return [self._entries[library][n] for n in sorted(self._entries[library])]

    def remove_plugin(self, plugin: str) -> None:
        for items in self._entries.values():
            for name in [n for n, e in items.items() if e.plugin == plugin]:
                del items[name]
