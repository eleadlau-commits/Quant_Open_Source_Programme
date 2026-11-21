"""A tiny observer: ``changed = Event(); changed.connect(fn); changed.emit(...)``. No Qt needed."""
from __future__ import annotations

from typing import Any, Callable


class Event:
    def __init__(self) -> None:
        self._handlers: list[Callable[..., Any]] = []

    def connect(self, fn: Callable[..., Any]) -> None:
        if fn not in self._handlers:
            self._handlers.append(fn)

    def disconnect(self, fn: Callable[..., Any]) -> None:
        if fn in self._handlers:
            self._handlers.remove(fn)

    def emit(self, *args: Any) -> None:
        for fn in list(self._handlers):
            fn(*args)
