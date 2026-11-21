"""Runs backtests one after another off the UI thread, so each result shows as it arrives.

Shared by the Backtests page and the Run view's backtest block:

    queue = BacktestQueue(workspace)
    queue.result.connect(show)            # a BacktestResult, already committed to workspace.backtests
    queue.start(run_id, ["bootstrap", "cost_stress"])   # params: the strategy's own, unless given
    queue.stop()                          # cancels the test running now and drops the rest
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from . import tasks


class BacktestQueue(QObject):
    started = Signal(str, str, int, int)  # run_id, test_id, position (1-based), of how many
    progress = Signal(str, float)  # test_id, fraction 0..1 of the test running now
    result = Signal(object)  # BacktestResult
    idle = Signal()  # nothing left to run

    def __init__(self, workspace, parent=None, background: bool = True):
        super().__init__(parent)
        self.workspace = workspace
        self.background = background  # tests and screenshots run inline
        self.todo: list[tuple[str, str, dict[str, Any] | None]] = []
        self.job = None
        self.done = 0
        self.total = 0
        self._poll = QTimer(self, interval=150)
        self._poll.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        return self.job is not None or bool(self.todo)

    def current(self) -> str | None:
        return self.job.test_id if self.job is not None else None

    def pending(self) -> list[str]:
        return [t for _, t, _ in self.todo]

    def start(self, run_id: str, test_ids: list[str], params: dict[str, dict[str, Any]] | None = None) -> None:
        """Queue tests on a run (behind any already queued, skipping ones already waiting)."""
        waiting = {(r, t) for r, t, _ in self.todo}
        if self.job is not None:
            waiting.add((self.job.record.id, self.job.test_id))
        new = [(run_id, t, (params or {}).get(t)) for t in test_ids if (run_id, t) not in waiting]
        if not self.running:
            self.done, self.total = 0, 0
        self.total += len(new)
        self.todo += new
        if self.job is None:
            self._next()

    def stop(self) -> None:
        self.todo.clear()
        if self.job is not None:
            self.workspace.backtests.cancel(self.job.id)

    def _next(self) -> None:
        while self.todo:
            run_id, test_id, params = self.todo.pop(0)
            try:
                job = self.workspace.backtests.prepare(run_id, test_id, params)
            except (KeyError, ValueError):
                self.done += 1
                continue
            self.job = job
            self.started.emit(run_id, test_id, self.done + 1, self.total)
            self._poll.start()
            tasks.run(job.execute, lambda res, job=job: self._finished(job, res),
                      lambda e, job=job: self._failed(job, e), self.background)
            return
        self.job = None
        self._poll.stop()
        self.idle.emit()

    def _tick(self) -> None:
        if self.job is not None:
            self.progress.emit(self.job.test_id, self.job.fraction)

    def _finished(self, job, res) -> None:
        if job is not self.job:
            return
        self.job = None
        self.done += 1
        self.workspace.backtests.commit(res)
        self.result.emit(res)
        self._next()

    def _failed(self, job, e: Exception) -> None:  # execute reports failures as results; this is a safety net
        if job is not self.job:
            return
        self.job = None
        self.done += 1
        self._next()
