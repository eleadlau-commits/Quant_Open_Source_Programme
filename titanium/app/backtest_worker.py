"""Backtests in a worker process, so a long test never makes the window stutter.

Python runs one thread's Python code at a time, so a backtest on a thread inside the app
takes turns with the window's drawing. A worker process has its own interpreter: the
window stays as smooth as when nothing runs. No Qt here (the worker never loads it).

    worker = workspace.backtest_worker()     # started once, kept for the session
    worker.submit(job_id, payload)           # payload: BacktestService.payload(job)
    for event in worker.poll():              # from a UI timer; never blocks
        ("progress", job_id, fraction) | ("result", job_id, result, baseline) | ("failed", job_id, reason)
    worker.cancel_current()                  # stops at the next simulator step
    worker.stop()

The worker opens datasets from the data folder itself and keeps them open between jobs;
only run records, settings and results cross. It runs the same ``BacktestService`` code
and the same simulator as the app. If it doesn't stop within ``STUCK_SECONDS`` of a
cancel, or it dies, it is ended and the next job starts a fresh one. Frozen builds must
call ``multiprocessing.freeze_support()`` first thing (``packaging/titanium_main.py``).
"""
from __future__ import annotations

import multiprocessing as mp
import queue as _queue
import time
from typing import Any

SPAWN = mp.get_context("spawn")  # the only way on Windows; the same everywhere for one behaviour
STUCK_SECONDS = 5.0
IDLE_CLOSE_SECONDS = 600.0  # a dataset unused this long is closed in the worker
PROGRESS_EVERY = 0.1


# ---- the worker process ---------------------------------------------------------------------
def serve(conn, spec: dict[str, Any], cancel, progress) -> None:
    """The worker's main loop (runs in the child process)."""
    import sys

    if sys.stderr is None:  # a windowed exe has no console: the worker's errors go to a log beside the app's
        try:
            from .paths import app_folder

            sys.stdout = sys.stderr = open(app_folder() / "titanium-worker.log", "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    from .workspace import Workspace

    ws = Workspace(data_root=spec["data_root"], plugins_folder=spec.get("plugins_folder"))
    ws.plugins.set_switched_off(spec.get("off", ()))
    used: dict[str, float] = {}
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg[0] == "stop":
            return
        if msg[0] == "ping":
            conn.send(("pong",))
            continue
        _, job_id, payload = msg
        try:
            out = _run(ws, job_id, payload, cancel, progress, used)
        except BaseException as e:  # noqa: BLE001 - reported to the app as the job's failure
            out = ("failed", job_id, f"{type(e).__name__}: {e}")
        try:
            conn.send(out)
        except Exception as e:  # noqa: BLE001 - e.g. a plugin's result that can't be pickled
            conn.send(("failed", job_id, f"its result couldn't be sent back ({type(e).__name__}: {e})"))


def _run(ws, job_id: str, payload: dict[str, Any], cancel, progress, used: dict[str, float]):
    off = set(payload.get("off", ()))
    if off != ws.plugins.switched_off():
        ws.plugins.set_switched_off(off)
    now = time.monotonic()
    for info in payload.get("datasets", ()):
        ws.datasets.adopt(info)
        used[info.id] = now
    for ds, last in list(used.items()):
        if now - last > IDLE_CLOSE_SECONDS:
            ws.datasets.close(ds)
            used.pop(ds)
    for rec in payload.get("runs", ()):
        if rec.id not in ws.runs:
            ws.runs.commit(rec)
    rec = ws.runs.get(payload["run_id"])
    job = ws.backtests.prepare(rec, payload["test_id"], payload.get("params"), cancel=cancel)
    last = [0.0]

    def tell(_jid, fraction):
        t = time.monotonic()
        if t - last[0] >= PROGRESS_EVERY or fraction >= 1.0:
            last[0] = t
            try:
                progress.put_nowait((job_id, fraction))
            except _queue.Full:
                pass

    job.progress.connect(tell)
    result = job.execute()
    return ("result", job_id, result, ws.backtests.take_new_baseline(rec.id))


# ---- the app's side ---------------------------------------------------------------------------
class BacktestWorker:
    """The app's handle on the worker process. Use from one thread (the UI thread)."""

    def __init__(self, spec: dict[str, Any]):
        self.spec = dict(spec)
        self.process = None
        self.conn = None
        self.cancel = None
        self.progress = None
        self.current: str | None = None
        self._cancelled_at: float | None = None
        self.problem = ""  # why the last start or job failed, for the log

    # ---- life ------------------------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.is_alive()

    def start(self) -> "BacktestWorker":
        if self.alive:
            return self
        parent, child = SPAWN.Pipe()
        self.cancel = SPAWN.Event()
        self.progress = SPAWN.Queue(maxsize=256)
        self.process = SPAWN.Process(target=serve, args=(child, self.spec, self.cancel, self.progress),
                                     name="titanium-backtests", daemon=True)
        self.process.start()
        child.close()
        self.conn = parent
        return self

    def ready(self, timeout: float = 30.0) -> bool:
        """Wait until the worker answers (it has imported everything). For tests and the build check."""
        self.start()
        self.conn.send(("ping",))
        if self.conn.poll(timeout):
            return self.conn.recv() == ("pong",)
        return False

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            if self.alive:
                self.conn.send(("stop",))
                self.process.join(1.0)
        except (OSError, EOFError, BrokenPipeError):
            pass
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(1.0)
        self._drop()

    def _drop(self) -> None:
        for obj in (self.conn, self.progress):
            try:
                obj.close() if obj is not None else None
            except OSError:
                pass
        self.process = self.conn = self.cancel = self.progress = None
        self.current = None
        self._cancelled_at = None

    # ---- jobs ------------------------------------------------------------------------
    def submit(self, job_id: str, payload: dict[str, Any]) -> None:
        if self.current is not None:
            raise RuntimeError("the worker is still running a test")
        self.start()
        self.cancel.clear()
        self._cancelled_at = None
        self.current = job_id
        self.conn.send(("job", job_id, payload))

    def cancel_current(self) -> None:
        if self.current is not None and self.cancel is not None:
            self.cancel.set()
            if self._cancelled_at is None:
                self._cancelled_at = time.monotonic()

    def poll(self) -> list[tuple]:
        """What happened since the last call; never blocks."""
        out: list[tuple] = []
        if self.process is None:
            return out
        latest: dict[str, float] = {}
        try:
            while True:
                jid, fraction = self.progress.get_nowait()
                latest[jid] = fraction
        except (_queue.Empty, OSError, EOFError, ValueError):
            pass
        out += [("progress", jid, f) for jid, f in latest.items() if jid == self.current]
        try:
            while self.conn.poll():
                msg = self.conn.recv()
                if msg[0] in ("result", "failed") and msg[1] == self.current:
                    self.current = None
                    self._cancelled_at = None
                    out.append(msg)
        except (EOFError, OSError):
            pass
        if self.current is not None:
            stuck = self._cancelled_at is not None and time.monotonic() - self._cancelled_at > STUCK_SECONDS
            if stuck or not self.alive:
                jid = self.current
                self.problem = "it didn't stop when asked" if stuck else "the backtest worker stopped"
                self.stop()  # the next job starts a fresh worker
                out.append(("failed", jid, self.problem))
        return out
