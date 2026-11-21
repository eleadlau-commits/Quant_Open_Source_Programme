"""The backtest service: ``Workspace.backtests``.

Runs the tests in ``Library.BACKTESTS`` on a run record and keeps the results for the
session (the Backtests page and the run view's backtest block read them here). Like the
run service, the slow part is split from announcing it:

    job = workspace.backtests.prepare(run_id, "cost_stress")      # UI thread
    tasks.run(job.execute, workspace.backtests.commit, on_error)  # worker, then UI thread
    workspace.backtests.cancel(job.id)                            # stops at the next rerun

``run(run_id, test_id)`` does both in one call (tests, scripts). Each job runs one test, so
a page that runs several shows each result as it arrives. Reruns a test asks for (with
changed costs, knobs or a stand-in strategy) go through the same simulator; they are cached
per run, so tests run one after another share them, and they are not added to
``Workspace.runs``. The default strategy's run is, so Compare can show it.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..core.backtests import BacktestContext, BacktestInfo, Verdict
from ..core.baseline import HoldEverything, baseline_settings
from ..core.plugins import Library, Registry
from ..core.run import RunRecord
from ..core.sim import RunFailed
from ..core.strategy import StrategyGraph, graph_from_dict
from .collection import Collection
from .events import Event

UTC = timezone.utc
SETTINGS_KEY = "backtests"  # strategy.settings["backtests"]: {test_id: {param: value}}; missing = every test


@dataclass
class BacktestResult:
    id: str
    run_id: str
    strategy_id: str
    test_id: str
    name: str
    verdict: Verdict
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "done"  # done, cancelled or failed (the test itself broke; the verdict says why)
    seconds: float = 0.0
    finished: datetime | None = None
    reruns: int = 0  # how many extra runs of the simulator it took

    @property
    def outcome(self) -> str:
        return self.verdict.outcome


def info_of(entry) -> BacktestInfo:
    """A library entry's :class:`BacktestInfo` (made up from its name and doc when it has none)."""
    obj = entry.obj
    info = getattr(obj, "info", None)
    if isinstance(info, BacktestInfo):
        return info
    return BacktestInfo(getattr(obj, "id", entry.name), getattr(obj, "name", entry.name), entry.doc)


class _Cache:
    """Reruns of one run, shared by the tests run on it."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reruns: dict[str, RunRecord] = {}
        self.baseline: RunRecord | None = None
        self.new_baseline = False


class BacktestJob:
    """One test on one run. ``execute`` is safe on a worker thread and announces nothing."""

    def __init__(self, service: "BacktestService", record: RunRecord, test_id: str, params: dict[str, Any]):
        self.id = f"bt-{uuid.uuid4().hex[:8]}"
        self.service, self.record, self.test_id, self.params = service, record, test_id, params
        self.progress = Event()  # (job_id, fraction), on the thread running execute
        self.fraction = 0.0
        self._cancel = threading.Event()
        self.reruns = 0

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _progress(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.progress.emit(self.id, self.fraction)

    def execute(self) -> BacktestResult:
        svc, rec = self.service, self.record
        entry = svc.entry(self.test_id)
        info = info_of(entry)
        start = time.perf_counter()
        status = "done"
        try:
            ctx = svc.context(rec, self)
            verdict = entry.obj.evaluate(ctx, **self.params)
            if self.cancelled:
                status = "cancelled"
                verdict = Verdict(info.name, None, "Stopped before it finished", "You stopped this test.")
        except _Stopped:
            status = "cancelled"
            verdict = Verdict(info.name, None, "Stopped before it finished", "You stopped this test.")
        except Exception as e:  # noqa: BLE001 - shown to the person as the result
            status = "failed"
            verdict = Verdict(info.name, None, "The test couldn't run", f"{type(e).__name__}: {e}")
        finally:
            svc._finished(self)
        return BacktestResult(f"{rec.id}:{self.test_id}", rec.id, rec.strategy_id, self.test_id, info.name, verdict,
                              dict(self.params), status, time.perf_counter() - start, datetime.now(UTC), self.reruns)


class _Stopped(Exception):
    pass


class BacktestService(Collection[BacktestResult]):
    """Results are kept by ``"<run id>:<test id>"``: the latest result of each test on each run."""

    def __init__(self, registry: Registry, runs, strategies: Collection[StrategyGraph]):
        super().__init__()
        self.registry, self.runs, self.strategies = registry, runs, strategies
        self._caches: dict[str, _Cache] = {}
        self._jobs: dict[str, BacktestJob] = {}
        self._lock = threading.Lock()
        self.started = Event()  # (job_id, run_id, test_id)

    # ---- the library ------------------------------------------------------------------
    def entry(self, test_id: str):
        for e in self.registry.entries(Library.BACKTESTS):
            if e.name == test_id:
                return e
        known = ", ".join(e.name for e in self.registry.entries(Library.BACKTESTS)) or "none"
        raise KeyError(f"no backtest called {test_id!r} (known: {known})")

    def tests(self) -> list[BacktestInfo]:
        """Every test in the library, in the order the plugins list them."""
        entries = self.registry.entries(Library.BACKTESTS)
        order = {name: i for i, name in enumerate(_listed_order(entries))}
        return [info_of(e) for e in sorted(entries, key=lambda e: order.get(e.name, 1e9))]

    def plugin_of(self, test_id: str) -> str:
        return self.entry(test_id).plugin

    # ---- which tests a strategy uses ------------------------------------------------------
    def used(self, strategy: Any) -> dict[str, dict[str, Any]]:
        """{test_id: params} the strategy uses (``settings["backtests"]``); every test when it says nothing."""
        cfg = (getattr(strategy, "settings", None) or {}).get(SETTINGS_KEY)
        ids = [t.id for t in self.tests()]
        if cfg is None:
            return {i: {} for i in ids}
        return {i: dict(cfg.get(i) or {}) for i in ids if i in cfg}

    def set_used(self, strategy_id: str, used: dict[str, dict[str, Any]]) -> None:
        graph = copy.deepcopy(self.strategies.get(strategy_id))
        graph.settings[SETTINGS_KEY] = {k: dict(v) for k, v in used.items()}
        self.strategies.put(strategy_id, graph)

    # ---- running ------------------------------------------------------------------------
    def _record(self, run: str | RunRecord) -> RunRecord:
        return self.runs.get(run) if isinstance(run, str) else run

    def prepare(self, run: str | RunRecord, test_id: str, params: dict[str, Any] | None = None) -> BacktestJob:
        rec = self._record(run)
        if rec.status != "done":
            raise ValueError(f"run {rec.id} {rec.status}; only finished runs can be tested")
        self.entry(test_id)
        if params is None:
            strat = self.strategies.get(rec.strategy_id) if rec.strategy_id in self.strategies else None
            params = self.used(strat).get(test_id, {}) if strat is not None else {}
        job = BacktestJob(self, rec, test_id, dict(params))
        with self._lock:
            self._jobs[job.id] = job
        self.started.emit(job.id, rec.id, test_id)
        return job

    def _finished(self, job: BacktestJob) -> None:
        with self._lock:
            self._jobs.pop(job.id, None)

    def commit(self, result: BacktestResult) -> BacktestResult:
        """Keep a result (on the UI thread). A default-strategy run made for it joins ``Workspace.runs``."""
        cache = self._caches.get(result.run_id)
        if cache is not None and cache.new_baseline and cache.baseline is not None:
            cache.new_baseline = False
            if cache.baseline.id not in self.runs:
                self.runs.commit(cache.baseline)
        self.put(result.id, result)
        return result

    def run(self, run: str | RunRecord, test_id: str, params: dict[str, Any] | None = None) -> BacktestResult:
        return self.commit(self.prepare(run, test_id, params).execute())

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel()
        return True

    def active(self) -> list[str]:
        with self._lock:
            return list(self._jobs)

    # ---- results ----------------------------------------------------------------------
    def results(self, run_id: str) -> dict[str, BacktestResult]:
        out = {}
        for i in self.ids():
            r = self.get(i)
            if r.run_id == run_id:
                out[r.test_id] = r
        return out

    def forget(self, run_id: str) -> None:
        for i in [i for i in self.ids() if self.get(i).run_id == run_id]:
            self.remove(i)
        self._caches.pop(run_id, None)

    # ---- what a test is given ----------------------------------------------------------
    def strategy_of(self, rec: RunRecord) -> Any:
        """The strategy exactly as it was run: from the record's snapshot, else the live one."""
        snap = rec.strategy_snapshot or {}
        if snap.get("modules"):
            return graph_from_dict(snap)
        if rec.strategy_id in self.strategies:
            return self.strategies.get(rec.strategy_id)
        raise ValueError("this run can't be repeated: it didn't come from a strategy in the workspace")

    def context(self, rec: RunRecord, job: BacktestJob) -> BacktestContext:
        cache = self._caches.setdefault(rec.id, _Cache())
        engine = self.runs.engine
        graph = None
        try:
            base = self.strategy_of(rec)
            graph = base if isinstance(base, StrategyGraph) else None
        except ValueError:
            base = None

        def stop_check() -> bool:
            return job.cancelled

        def rerun(settings: dict[str, Any] | None = None, knobs: dict[str, Any] | None = None,
                  strategy: Any = None, key: str | None = None) -> RunRecord:
            if job.cancelled:
                raise _Stopped()
            strat = strategy if strategy is not None else base
            if strat is None:
                raise ValueError("this run can't be repeated: it didn't come from a strategy in the workspace")
            if knobs:
                if not isinstance(strat, StrategyGraph):
                    raise ValueError("only strategies built from modules have knobs to turn")
                strat = copy.deepcopy(strat)
                strat.knob_values = {**strat.knob_values, **knobs}
            cfg = _merge(rec.settings, settings or {})
            cfg.pop("probes", None)
            k = key or repr((sorted((knobs or {}).items()), repr(sorted(cfg.items(), key=lambda kv: kv[0])),
                             id(strategy) if strategy is not None else None))
            with cache.lock:
                hit = cache.reruns.get(k)
            if hit is not None:
                return hit
            try:
                out = engine.run(strat, rec.dataset_id, cfg, cancel=job._cancel)
            except RunFailed as e:
                raise RuntimeError(f"a rerun failed: {e.record.error}") from e
            if out.status == "cancelled" or job.cancelled:
                raise _Stopped()
            job.reruns += 1
            if strategy is None:  # stand-in strategies are new objects each time; don't keep them
                with cache.lock:
                    cache.reruns[k] = out
            return out

        def baseline() -> RunRecord | None:
            with cache.lock:
                if cache.baseline is not None:
                    return cache.baseline
            have = self.runs.baseline_for(rec)
            if have is None:
                if job.cancelled:
                    raise _Stopped()
                cfg = baseline_settings(rec.settings)  # straight to the engine: no events off the UI thread
                try:
                    have = engine.run(HoldEverything(cfg), rec.dataset_id, cfg, cancel=job._cancel)
                except RunFailed:
                    return None
                if have.status != "done":
                    return None
                cache.new_baseline = True
            with cache.lock:
                cache.baseline = have
            return have

        history = [r for r in self.runs.records(rec.strategy_id) if r.id != rec.id] if rec.strategy_id else []
        return BacktestContext(rec, rerun, baseline=baseline, history=history, progress=job._progress,
                               cancelled=stop_check, graph=graph, strategy=base)


def _listed_order(entries) -> list[str]:
    """Entries in the order their objects say (``order`` attribute), then by name."""
    return [e.name for e in sorted(entries, key=lambda e: (getattr(e.obj, "order", 100), e.name))]


def _merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in top.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
