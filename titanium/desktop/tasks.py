"""Run slow work (loading data, writing files) off the UI thread.

``run(fn, on_done, on_error)`` calls ``fn()`` on a worker thread, then ``on_done(result)``
or ``on_error(exception)`` back on the UI thread. With ``background=False`` it runs
inline, which tests and scripts use.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_alive: set = set()


class _Relay(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any], relay: _Relay) -> None:
        super().__init__()
        self.fn, self.relay = fn, relay

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # reported to the UI, never swallowed
            self.relay.failed.emit(exc)
        else:
            self.relay.done.emit(result)


def run(fn: Callable[[], Any], on_done: Callable[[Any], None], on_error: Callable[[Exception], None],
        background: bool = True) -> None:
    if not background:
        try:
            result = fn()
        except Exception as exc:
            on_error(exc)
        else:
            on_done(result)
        return
    relay = _Relay()
    _alive.add(relay)

    def finish(cb):
        def inner(value):
            _alive.discard(relay)
            cb(value)
        return inner

    relay.done.connect(finish(on_done))
    relay.failed.connect(finish(on_error))
    QThreadPool.globalInstance().start(_Job(fn, relay))
