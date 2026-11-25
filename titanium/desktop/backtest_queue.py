"""Runs backtests one after another off the UI thread, so each result shows as it arrives.

Shared by the Backtests page and the Run view's backtest block:

    queue = BacktestQueue(workspace)
    queue.result.connect(show)            # a BacktestResult, already committed to workspace.backtests
    queue.start(run_id, ["bootstrap", "cost_stress"])   # params: the strategy's own, unless given
    queue.stop()                          # cancels the test running now and drops the rest

In the app, tests run in the backtest worker process (``Workspace.backtest_worker``), so the
window stays smooth while they compute; where the worker can't be used (it failed to
start, or ``use_worker`` is off) they run on a thread as before. Tests run inline with
``background=False``.
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
        self.use_worker = True  # in the worker process when it can be started, else on a thread
        self.worker = None  # the worker running the current job, if it runs in one
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

    def _worker(self):
        if not (self.background and self.use_worker):
            return None
        get = getattr(self.workspace, "backtest_worker", None)
        return get() if get is not None else None

    def stop(self) -> None:
        self.todo.clear()
        if self.job is not None:
            self.workspace.backtests.cancel(self.job.id)
            if self.worker is not None:
                self.worker.cancel_current()

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
            worker = self._worker()
            if worker is not None:
                try:
                    worker.submit(job.id, self.workspace.backtests.payload(job, self.workspace.plugins.switched_off()))
                except Exception as e:  # noqa: BLE001 - e.g. a run that can't be sent: run it here instead
                    worker.problem = f"{type(e).__name__}: {e}"
                    worker = None
            self.worker = worker
            self._poll.setInterval(50 if worker is not None else 150)
            self._poll.start()
            if worker is None:
                tasks.run(job.execute, lambda res, job=job: self._finished(job, res),
                          lambda e, job=job: self._failed(job, e), self.background)
            return
        self.job = None
        self._poll.stop()
        self.idle.emit()

    def _tick(self) -> None:
        if self.job is None:
            return
        if self.worker is not None:
            self._from_worker(self.job, self.worker)
            return
        self.progress.emit(self.job.test_id, self.job.fraction)

    def _from_worker(self, job, worker) -> None:
        for event in worker.poll():
            kind, jid = event[0], event[1]
            if jid != job.id:
                continue
            if kind == "progress":
                job.fraction = event[2]
                self.progress.emit(job.test_id, job.fraction)
            elif kind == "result":
                self.workspace.backtests.finish_remote(job, event[3])
                self._finished(job, event[2])
                return
            else:  # the worker failed or stopped: show it as the test's result
                self.workspace.backtests.finish_remote(job)
                self._finished(job, self.workspace.backtests.failed_result(job, event[2]))
                return

    def _finished(self, job, res) -> None:
        if job is not self.job:
            return
        self.job = None
        self.worker = None
        self.done += 1
        self.workspace.backtests.commit(res)
        self.result.emit(res)
        self._next()

    def _failed(self, job, e: Exception) -> None:  # execute reports failures as results; this is a safety net
        if job is not self.job:
            return
        self.job = None
        self.worker = None
        self.done += 1
        self._next()
