"""Objects by id, with events the views listen to."""
from __future__ import annotations

from typing import Generic, TypeVar

from .events import Event

T = TypeVar("T")


class Collection(Generic[T]):
    """Objects by id, with events the views listen to."""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}
        self.added = Event()  # (id, obj)
        self.changed = Event()  # (id, obj)
        self.removed = Event()  # (id,)

    def put(self, id: str, obj: T) -> None:
        new = id not in self._items
        self._items[id] = obj
        (self.added if new else self.changed).emit(id, obj)

    def get(self, id: str) -> T:
        return self._items[id]

    def remove(self, id: str) -> None:
        if self._items.pop(id, None) is not None:
            self.removed.emit(id)

    def ids(self) -> list[str]:
        return list(self._items)

    def __contains__(self, id: object) -> bool:
        return id in self._items

    def __len__(self) -> int:
        return len(self._items)
