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


def _wait(app, w, limit=60):
    t0 = time.time()
    while w._thread is not None and time.time() - t0 < limit:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def test_builder_adds_wires_and_removes_pieces():
    from honestbt.desktop import builder
    from honestbt.patchbay import validate
    from honestbt.registry import load_plugins
    load_plugins()
    cfg = {"data": {"plugin": "synthetic"}, "features": {"atr14": {"plugin": "atr"}},
           "strategy": {"plugin": "weekly_topn", "params": {}}, "evaluators": []}
    cfg2, where = builder.add(cfg, "feature", "realized_vol")
    assert where == "features.realized_vol" and "realized_vol" not in cfg["features"]  # original untouched
    cfg2, where = builder.add(cfg2, "mapping", "linear")
    assert cfg2["mappings"]["linear"]["input"] == "atr14"
    cfg2 = builder.set_input(cfg2, "linear", "realized_vol")
    feat_slots, num_slots = builder.strategy_slots(cfg2)
    assert "strategy.params.rank_by" in feat_slots and "strategy.params.top_n" in num_slots
    cfg2, _ = builder.add(cfg2, "signal", "atr_trailing")
    assert "strategy.params.exit.params.k" in builder.strategy_slots(cfg2)[1]
    cfg2 = builder.wire(cfg2, "strategy.params.exit.params.k", {"$map": "linear"})
    cfg2, _ = builder.add(cfg2, "evaluator", "bootstrap")
    assert cfg2["evaluators"][-1]["plugin"] == "bootstrap"
    assert not validate(cfg2)
    assert "linear" not in builder.remove(cfg2, "mapping", "linear")["mappings"]


def test_new_config_starts_from_a_runnable_example():
    from pathlib import Path
    from honestbt.desktop import builder
    from honestbt.patchbay import validate
    examples = sorted(Path("configs").glob("*.json"))
    cfg = builder.new_config("opening_range_breakout", examples)
    assert cfg["strategy"]["plugin"] == "opening_range_breakout" and cfg["name"].startswith("My ")
    assert not validate(cfg)
    bare = builder.new_config("weekly_topn", [])
    assert bare["strategy"]["params"]["top_n"] == 5 and not validate(bare)


def test_hover_help_explains_words_in_the_settings():
    from honestbt.desktop.help import explain
    from honestbt.registry import load_plugins
    load_plugins()
    cfg = {"features": {"gap": {"plugin": "premarket_gap"}},
           "mappings": {"k_map": {"plugin": "linear", "input": "gap"}},
           "strategy": {"plugin": "weekly_topn", "params": {"top_n": 5}}}
    assert explain('"gap"', cfg).startswith("Feature 'gap' = premarket_gap")
    assert "Mapping" in explain("k_map", cfg)
    assert "How many names" in explain("top_n", cfg)
    assert "strategy family" in explain("sweep", cfg)
    assert explain("bootstrap", cfg).startswith("Test plugin")
    assert explain("honest-stocks", cfg).startswith("Test suite")
    assert explain("zzz_nothing", cfg) is None


def test_verdict_blocks_can_be_moved_and_remember_order(tmp_path):
    from PySide6.QtCore import QSettings
    from honestbt.desktop.verdicts import VerdictBoard
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QSettings(str(tmp_path / "t.ini"), QSettings.IniFormat)
    vs = [{"name": n, "passed": p, "headline": "h", "explanation": "e"} for n, p in
          (("A", True), ("B", False), ("C", None))]
    board = VerdictBoard(settings)
    board.set_verdicts(vs)
    assert board.names() == ["A", "B", "C"]
    board.move("C", "A")
    assert board.names() == ["C", "A", "B"]
    board.cards[1].set_folded(True, remember=True)
    again = VerdictBoard(settings)
    again.set_verdicts(vs + [{"name": "D", "passed": True, "headline": "", "explanation": ""}])
    assert again.names() == ["C", "A", "B", "D"]
    assert again.cards[1].folded and not again.cards[0].folded
    again.reset()
    assert again.names() == ["A", "B", "C", "D"] and not any(c.folded for c in again.cards)
    app.processEvents()


def test_patch_bay_and_catalogue_edit_the_settings():
    import json
    from honestbt.desktop.app import MainWindow
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    app.processEvents()
    menu = w.graph.build_menu(None)
    assert [a.text() for a in menu.actions() if a.menu()][:2] == ["Add feature", "Add mapping (cable)"]
    feat = next(it for it in [w.catalogue.topLevelItem(i) for i in range(w.catalogue.topLevelItemCount())]
                if it.text(0) == "feature")
    child = next(feat.child(i) for i in range(feat.childCount()) if feat.child(i).text(0) == "trailing_return")
    w.catalogue_add(child)
    cfg = json.loads(w.editor.toPlainText())
    assert "trailing_return" in cfg["features"]
    w.graph.repaint()
    assert any(n == "trailing_return" for k, n, _ in w.graph.nodes)
    w.show_help("x")
    assert w.help_line.text() == "x"
    w.show_help("")
    assert "Hover" in w.help_line.text()
