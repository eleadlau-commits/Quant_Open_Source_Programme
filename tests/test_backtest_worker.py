"""Backtests in the worker process: same results as on a thread, cancel, crash, the queue."""
import time

import pytest

from titanium.app.workspace import Workspace
from titanium.core.module_library import momentum_rotation


@pytest.fixture(scope="module")
def ws():
    w = Workspace()
    info = w.datasets.add("synthetic_stocks", {"n_symbols": 5, "n_days": 45, "seed": 3})
    g = momentum_rotation(id="S1")
    g.settings["datasets"] = [info.id]
    g.knob_values = {"m1.days": 10, "m2.days": 15}
    w.strategies.put("S1", g)
    w.rec = w.runs.run("S1")
    assert w.backtest_worker().ready(60)
    yield w
    w.stop_backtest_worker()


def wait(worker, job_id, seconds=60):
    seen = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for ev in worker.poll():
            seen.append(ev)
            if ev[0] in ("result", "failed") and ev[1] == job_id:
                return ev, seen
        time.sleep(0.01)
    raise AssertionError("the worker didn't answer")


def submit(ws, test_id, params=None):
    job = ws.backtests.prepare(ws.rec, test_id, params)
    ws.backtest_worker().submit(job.id, ws.backtests.payload(job, ws.plugins.switched_off()))
    return job


def test_every_built_in_test_gives_the_same_verdict_in_the_worker(ws):
    def same(v):  # the default strategy's run gets a new id wherever it is made
        details = {k: x for k, x in v.details.items() if k != "baseline_run"}
        return repr((v.outcome, v.headline, v.explanation, details))

    for t in ws.backtests.tests():
        job = submit(ws, t.id)
        ev, _ = wait(ws.backtest_worker(), job.id)
        assert ev[0] == "result", ev
        local = ws.backtests.prepare(ws.rec, t.id).execute()
        assert same(ev[2].verdict) == same(local.verdict), t.id
        ws.backtests.finish_remote(job, ev[3])
    assert ws.runs.baseline_for(ws.rec) is not None  # the worker's default-strategy run joined the app's runs
    assert not ws.backtests.active()


def test_cancel_stops_the_test_and_the_worker_stays(ws):
    worker = ws.backtest_worker()
    job = submit(ws, "random_baseline", {"n": 300})
    time.sleep(0.3)
    worker.cancel_current()
    ev, _ = wait(worker, job.id, 20)
    assert ev[0] == "result" and ev[2].status == "cancelled"
    ws.backtests.finish_remote(job)
    assert worker.alive
    job = submit(ws, "bootstrap")  # and runs the next one
    assert wait(worker, job.id)[0][2].status == "done"
    ws.backtests.finish_remote(job)


def test_a_worker_that_dies_fails_the_job_and_a_new_one_starts(ws):
    worker = ws.backtest_worker()
    job = submit(ws, "random_baseline", {"n": 300})
    worker.process.kill()
    ev, _ = wait(worker, job.id, 20)
    assert ev[0] == "failed" and "stopped" in ev[2] and not worker.alive
    result = ws.backtests.failed_result(job, ev[2])
    assert result.status == "failed" and "worker" in result.verdict.explanation
    ws.backtests.finish_remote(job)
    job = submit(ws, "bootstrap")  # submit starts a fresh worker
    assert wait(worker, job.id)[0][2].status == "done"
    ws.backtests.finish_remote(job)


def test_the_worker_reopens_a_dataset_whose_version_changed(ws):
    from dataclasses import replace

    info = ws.datasets.get(ws.rec.dataset_id)
    ws.datasets.adopt(replace(info, version="other"))
    assert ws.datasets.get(info.id).version == "other"
    ws.datasets.adopt(info)
    assert ws.datasets.get(info.id).version == info.version


def test_the_queue_runs_tests_in_the_worker(ws, qapp):
    from PySide6.QtTest import QTest

    from titanium.desktop.backtest_queue import BacktestQueue

    q = BacktestQueue(ws)
    results, progress = [], []
    q.result.connect(results.append)
    q.progress.connect(lambda t, f: progress.append(f))
    q.start(ws.rec.id, ["cost_stress", "deflated_sharpe"])
    assert q.worker is ws.backtest_worker()
    for _ in range(2000):
        if not q.running:
            break
        QTest.qWait(10)
    assert [r.test_id for r in results] == ["cost_stress", "deflated_sharpe"]
    assert all(r.status == "done" for r in results)
    assert set(ws.backtests.results(ws.rec.id)) >= {"cost_stress", "deflated_sharpe"}
    # stopping a test in the worker shows it as stopped
    q.start(ws.rec.id, ["random_baseline"], {"random_baseline": {"n": 300}})
    QTest.qWait(200)
    q.stop()
    for _ in range(2000):
        if not q.running:
            break
        QTest.qWait(10)
    assert results[-1].status == "cancelled"
