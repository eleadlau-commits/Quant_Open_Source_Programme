"""Datasets and the look-ahead-guarded view onto them.

Three kinds of data, as in the prototype:

* **core**: prices (bars) of the instruments a strategy trades.
* **complementary**: other data known over time (news, events, fundamentals),
  each value stamped with the time it became known.
* **generated**: produced from other data by a generator (features, indicators).

Strategy-specific state (positions, orders) is not data: it lives in the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class DataKind(str, Enum):
    CORE = "core"
    COMPLEMENTARY = "complementary"
    GENERATED = "generated"


class Frequency(str, Enum):
    MINUTE = "1min"
    DAILY = "1d"


@dataclass(frozen=True)
class SourceSpec:
    """Where a dataset comes from: a data-source plugin and its settings."""

    plugin: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetInfo:
    """What the Data page shows and manages for one dataset."""

    id: str
    name: str
    kind: DataKind
    source: SourceSpec
    instruments: list[str] = field(default_factory=list)  # Instrument.key values
    frequency: Frequency | None = None
    start: datetime | None = None
    end: datetime | None = None
    fields: list[str] = field(default_factory=list)
    storage: str = ""  # where it lives on disk
    version: str = ""  # changes whenever the content changes (used as a cache key and in run bundles)
    used_by: list[str] = field(default_factory=list)  # strategy ids
    notes: str = ""


class LookAheadError(RuntimeError):
    """Raised when code asks for data that did not exist yet at the current time."""


@runtime_checkable
class GuardedView(Protocol):
    """The only window strategy code gets onto data, pinned to ``as_of``.

    Anything not knowable at ``as_of`` is invisible; explicitly asking for it raises
    :class:`LookAheadError`. A bar is visible once it has *ended*.
    """

    as_of: datetime

    def universe(self) -> list[str]:
        """Instruments listed and tradable at ``as_of`` (future delistings included: no survivorship bias)."""
        ...

    def bars(self, instrument: str, frequency: Frequency, start: datetime | None = None,
             end: datetime | None = None) -> Any:
        """Completed bars (open, high, low, close, volume) ending by ``end`` (default ``as_of``)."""
        ...

    def series(self, name: str, instrument: str | None = None) -> Any:
        """Complementary or generated data known by ``as_of``."""
        ...


@runtime_checkable
class DataSource(Protocol):
    """A data-source plugin: loads (or downloads) a dataset."""

    def describe(self, spec: SourceSpec) -> DatasetInfo: ...

    def load(self, spec: SourceSpec) -> Any: ...
