"""How quick a re-run feels: run time, the worst UI stall while it computes, and the cost of one knob step.

    python tools/bench_rerun.py DATA_ROOT "dataset name part"

Opens the momentum rotation example on that dataset in the real window (offscreen), runs it
in the background a few times while a 5 ms timer measures how long the UI thread goes
without a turn, then turns a knob a dozen times without running.
"""
import os, sys, time, pathlib, tempfile, statistics as st
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, QTimer, QElapsedTimer
app = QApplication([])
from titanium.desktop.design import theme; theme.apply(app, "dark")
from titanium.app.workspace import Workspace
from titanium.core.module_library import momentum_rotation
from titanium.desktop.context import AppContext
from titanium.desktop.app import build_window
root = pathlib.Path(sys.argv[1]); name = sys.argv[2]
ws = Workspace(data_root=root)
ds = [i for i in ws.datasets.infos("core") if name in i.name][0]
tmp = tempfile.mkdtemp()
ctx = AppContext(QSettings(tmp + "/s.ini", QSettings.IniFormat), ws)
w = build_window(ctx); w.resize(1440, 900); w.show(); w.show_page("strategies")
g = momentum_rotation(id="S1"); g.knob_values["m2.days"] = 10; g.settings["datasets"] = [ds.id]
w.views["strategies"].open_graph(g)
tab = w.views["strategies"].tabs.currentWidget(); rv = tab.run_view
app.processEvents()

def wait_run():
    """Start a background run; return (wall seconds, worst UI stall ms, UI ticks)."""
    gaps, clock = [], QElapsedTimer(); clock.start(); last = [clock.elapsed()]
    def tick():
        now = clock.elapsed(); gaps.append(now - last[0]); last[0] = now
    t = QTimer(); t.setInterval(5); t.timeout.connect(tick); t.start()
    t0 = time.perf_counter(); tab.run()
    while rv.running or getattr(rv, "_bjob", None) is not None:
        app.processEvents()
    # old code: the default strategy keeps running after the run ends
    end = time.perf_counter() + 0.05
    while time.perf_counter() < end or ws.runs.active():
        app.processEvents()
    t.stop()
    return time.perf_counter() - t0, max(gaps) if gaps else 0, len(gaps)

a = wait_run(); print(f"first run (opens dataset, plus default strategy): {a[0]*1000:.0f} ms, worst UI stall {a[1]} ms")
runs = [wait_run() for _ in range(3)]
print(f"re-run: {st.median(r[0] for r in runs)*1000:.0f} ms, worst UI stall {max(r[1] for r in runs)} ms")
vals = iter([2, 3, 4, 5] * 10)
def step():
    t = time.perf_counter(); rv.knobs.turn("m3.top", next(vals)); rv._timer.stop(); app.processEvents()
    return (time.perf_counter() - t) * 1000
steps = [step() for _ in range(12)]
print(f"one knob step (UI thread, no run): median {st.median(steps):.1f} ms, worst {max(steps):.1f} ms")
