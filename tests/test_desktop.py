"""Smoke test for the desktop app (skipped where Qt isn't installed)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


def test_window_runs_small_config():
    from honestbt.desktop.app import MainWindow
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    import json
    cfg = json.loads(w.editor.toPlainText())
    cfg["data"]["params"].update(n_symbols=15, n_days=50)
    cfg["sweep"] = {"strategy.params.exit.params.k": [0.5, 1.0, 2.0]}
    cfg["evaluators"] = [{"plugin": "bootstrap"}, {"plugin": "parameter_stability"}]
    w.editor.setPlainText(json.dumps(cfg))
    w.run()
    t0 = time.time()
    while w._thread is not None and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert "tests" in w.summary.text()
    assert w.sweep_table.rowCount() == 3
