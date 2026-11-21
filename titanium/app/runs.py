"""The run service: ``Workspace.runs``.

Runs a strategy through the simulator and keeps the run records for the session
(Compare, Backtests and the run view read them here). Like the dataset service, the
slow part is split from announcing it, so the desktop can run it off the UI thread:

    job = workspace.runs.prepare("S1")          # UI thread
    tasks.run(job.execute, workspace.runs.commit, on_error)   # worker, then UI thread
    workspace.runs.cancel(job.id)               # any time: stops at the next step

``run(...)`` does both in one call (tests, scripts). A failed run is still committed,
with ``status == "failed"`` and the error, so the person can see what happened.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Callable

from ..core.run import RunRecord
from ..core.sim import RunFailed, SimEngine
from ..core.strategy import StrategyGraph
from .collection import Collection
from .events import Event


class RunJob:
    """One prepared run. ``execute`` is safe on a worker thread and announces nothing."""

    def __init__(self, engine: SimEngine, strategy: Any, dataset_id: str, settings: dict[str, Any],
                 on_done: Callable[["RunJob"], None] | None = None):
        self.id = f"run-{uuid.uuid4().hex[:8]}"
        self.engine, self.strategy, self.dataset_id, self.settings = engine, strategy, dataset_id, settings
        self.progress = Event()  # (run_id, fraction 0..1), emitted on the thread running execute
        self.fraction = 0.0
        self._cancel = threading.Event()
        self._on_done = on_done

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _progress(self, fraction: float) -> None:
        self.fraction = fraction
        self.progress.emit(self.id, fraction)

    def execute(self) -> RunRecord:
        try:
            return self.engine.run(self.strategy, self.dataset_id, self.settings, cancel=self._cancel,
                                   progress=self._progress, run_id=self.id)
        except RunFailed as e:
            return e.record
        finally:
            if self._on_done is not None:
                self._on_done(self)


class RunService(Collection[RunRecord]):
    def __init__(self, datasets, strategies: Collection[StrategyGraph]):
        super().__init__()
        self.datasets = datasets
        self.strategies = strategies
        self.engine = SimEngine(datasets)
        self._jobs: dict[str, RunJob] = {}
        self._lock = threading.Lock()
        self.started = Event()  # (run_id,)
        # () -> settings every run starts from (Workspace sets it to its run defaults);
        # the strategy's settings and then the run's go on top
        self.defaults: Callable[[], dict[str, Any]] | None = None

    def _resolve(self, strategy: str | Any) -> Any:
        if isinstance(strategy, str):
            return self.strategies.get(strategy)
        return strategy

    @staticmethod
    def dataset_of(strategy: Any, settings: dict[str, Any] | None = None) -> str:
        cfg = {**(getattr(strategy, "settings", None) or {}), **(settings or {})}
        ds = cfg.get("dataset") or (cfg.get("datasets") or [None])[0]
        if not ds:
            raise ValueError("the strategy doesn't say which dataset to run on (settings['dataset'])")
        return ds

    def prepare(self, strategy: str | Any, settings: dict[str, Any] | None = None,
                dataset_id: str | None = None) -> RunJob:
        """A run of ``strategy`` (an id in ``Workspace.strategies``, or a graph) ready to execute."""
        strat = self._resolve(strategy)
        ds = dataset_id or self.dataset_of(strat, settings)
        cfg = dict(settings or {})
        if self.defaults is not None:
            from .settings import merge

            cfg = merge(self.defaults(), getattr(strat, "settings", None) or {}, cfg)
        job = RunJob(self.engine, strat, ds, cfg, on_done=self._finished)
        with self._lock:
            self._jobs[job.id] = job
        self.started.emit(job.id)
        return job

    def _finished(self, job: RunJob) -> None:
        with self._lock:
            self._jobs.pop(job.id, None)

    def commit(self, record: RunRecord) -> RunRecord:
        """Keep a finished run for the session (on the UI thread)."""
        self.put(record.id, record)
        return record

    def run(self, strategy: str | Any, settings: dict[str, Any] | None = None,
            dataset_id: str | None = None) -> RunRecord:
        return self.commit(self.prepare(strategy, settings, dataset_id).execute())

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(run_id)
        if job is None:
            return False
        job.cancel()
        return True

    def active(self) -> list[str]:
        with self._lock:
            return list(self._jobs)

    def records(self, strategy_id: str | None = None) -> list[RunRecord]:
        recs = [self.get(i) for i in self.ids()]
        return [r for r in recs if strategy_id is None or r.strategy_id == strategy_id]
