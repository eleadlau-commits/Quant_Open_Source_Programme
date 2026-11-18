"""Smoke test for the desktop app (skipped where Qt isn't installed)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
QtCore = pytest.importorskip("PySide6.QtCore")


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


def test_window_runs_orb_config():
    from honestbt.desktop.app import MainWindow
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    import json
    i = w.preset.findText("nq_orb_trend_filter")
    assert i >= 0
    w.preset.setCurrentIndex(i)
    cfg = json.loads(w.editor.toPlainText())
    cfg["data"]["params"]["n_days"] = 80
    cfg["sweep"] = {"strategy.params.target_r": [2.0, 3.0, 4.0]}
    cfg["evaluators"] = [{"plugin": "ablation"}, {"plugin": "parameter_stability"}]
    w.editor.setPlainText(json.dumps(cfg))
    w.run()
    t0 = time.time()
    while w._thread is not None and time.time() - t0 < 60:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    assert "ranked" in w.summary.text()
    assert w.trades_table.horizontalHeaderItem(7).text() == "R"
    assert len(w.chart.series) == 2


def test_plugins_window_switches_a_plugin_off_and_on():
    from honestbt import plugins
    from honestbt.desktop.app import MainWindow
    from honestbt.desktop.plugins_dialog import PluginsDialog
    from honestbt.registry import has
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    assert w.preset.findText("monday-gap-exit-family (gap-families)") >= 0
    with plugins.isolated():
        dlg = PluginsDialog(w)
        dlg.changed.connect(w.plugins_changed)
        row = next(i for i, s in enumerate(dlg.rows) if s.id == "bootstrap")
        dlg.table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
        app.processEvents()
        assert not has("evaluator", "bootstrap")
        assert any(s.id == "honest-tests" and s.state == "off" for s in dlg.rows)
        assert w.preset.findText("monday-gap-exit-family (gap-families)") < 0  # needs the suites
        row = next(i for i, s in enumerate(dlg.rows) if s.id == "bootstrap")
        dlg.table.item(row, 0).setCheckState(QtCore.Qt.Checked)
        assert has("evaluator", "bootstrap")
    plugins.set_enabled("bootstrap", True)
