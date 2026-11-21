"""The shell: pages, docks, moving views between them, themes, the gallery."""
import pytest
from PySide6.QtCore import Qt

from titanium.desktop.app import build_window
from titanium.desktop.design import theme
from titanium.core.data import DataKind
from titanium.desktop.views import DOCK, PAGE


@pytest.fixture
def win(qapp, ctx):
    w = build_window(ctx)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()  # so later tests don't restyle it on every theme change
    from PySide6.QtCore import QEvent

    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


def test_four_pages_and_settings_in_the_corner(win):
    assert [b for b in win.nav_buttons] == ["data", "strategies", "compare", "backtests", "settings"]
    assert win.corner_box.indexOf(win.nav_buttons["settings"]) >= 0
    assert win.current == "data"


def test_docks_show_only_on_their_page(win, qapp):
    assert not win.docks["knobs"].isVisible()
    win.show_page("strategies")
    qapp.processEvents()
    assert win.docks["knobs"].isVisible()
    win.show_page("compare")
    assert not win.docks["knobs"].isVisible()


def test_a_view_moves_between_page_and_dock_and_is_remembered(win, ctx, qapp):
    win.move_view("knobs", PAGE)
    assert win.hosts["knobs"] == PAGE and "knobs" in win.nav_buttons and win.current == "knobs"
    win.move_view("compare", DOCK)
    assert "compare" in win.docks and "compare" not in win.nav_buttons
    w2 = build_window(ctx)  # a new window restores the saved layout
    assert w2.hosts["knobs"] == PAGE and w2.hosts["compare"] == DOCK
    w2.close()


def test_moving_the_current_page_to_a_dock_falls_back(win):
    win.show_page("backtests")
    win.move_view("backtests", DOCK)
    assert win.current == "data"


def test_new_strategy_opens_a_tab_with_three_views(win, ctx):
    view = win.views["strategies"]
    g = view.new_strategy()
    assert g.id in ctx.workspace.strategies
    tab = view.tabs.currentWidget()
    assert tab.views.count() == 3
    tab.switch.set_index(2)
    assert tab.views.currentIndex() == 2
    view.close_tab(0)
    assert g.id not in ctx.workspace.strategies


def test_theme_switch_restyles_everything(win, qapp, ctx):
    ctx.theme_changed.emit("dark")
    assert theme.current().name == "dark"
    ctx.theme_changed.emit("light")
    assert theme.current().name == "light"


def test_gallery_builds(qapp):
    from titanium.desktop.design.gallery import build

    w = build()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.close()


def test_no_hard_coded_colours_outside_the_design_system():
    """UI code takes colours from tokens only (the gallery and tokens are the exceptions)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "titanium" / "desktop"
    offenders = []
    for f in root.rglob("*.py"):
        if f.parent.name == "design":
            continue
        if re.search(r"#[0-9a-fA-F]{6}\b|setStyleSheet\(", f.read_text()):
            offenders.append(str(f.relative_to(root)))
    assert offenders == []


# ---------------------------------------------------------------- the Code view and Knobs dock
PLAIN_FILE = '''"""Hold everything."""
SETTINGS = {"every": "day"}


def decide(F, p):
    w = 0.25
    return {s: w for s in F.universe()}
'''


def _code_tab(win, qapp):
    from titanium.core.module_library import momentum_rotation

    win.show_page("strategies")
    view = win.views["strategies"]
    g = momentum_rotation(id="S9")
    view.open_graph(g, view=1)
    qapp.processEvents()
    return view, view.tabs.currentWidget()


def test_code_view_shows_the_strategy_and_reads_edits_back(win, ctx, qapp):
    view, tab = _code_tab(win, qapp)
    code = tab.code
    assert tab.views.currentWidget() is code
    assert "def momentum(view):" in code.editor.toPlainText()
    code.editor.setPlainText(code.editor.toPlainText().replace('knob("top", 5,', 'knob("top", 7,'))
    assert code.read_back()
    g = ctx.workspace.strategies.get("S9")
    assert g.knobs()["m3.top"].default == 7
    assert tab.badge.text() == "3 modules"


def test_code_view_keeps_the_last_good_graph_on_a_syntax_error(win, ctx, qapp):
    view, tab = _code_tab(win, qapp)
    tab.code.editor.setPlainText("def broken(:\n")
    assert not tab.code.read_back()
    assert tab.code.error.isVisibleTo(tab) and len(ctx.workspace.strategies.get("S9").modules) == 3


def test_make_knob_with_the_cursor_on_a_number(win, ctx, qapp):
    view, tab = _code_tab(win, qapp)
    ed = tab.code.editor
    text = ed.toPlainText()
    pos = text.index("scores[s] > 0 or") + len("scores[s] > ")
    c = ed.textCursor()
    c.setPosition(pos)
    ed.setTextCursor(c)
    assert tab.code.make_knob() == "value"
    assert 'knob("value", 0, lo=0, hi=10)' in ed.toPlainText()
    assert "m3.value" in ctx.workspace.strategies.get("S9").knobs()
    assert ed.textCursor().block().text().strip().startswith("best = ")  # the cursor stayed on its line


def test_knobs_dock_lists_and_turns_knobs(win, ctx, qapp):
    view, tab = _code_tab(win, qapp)
    knobs = win.views["knobs"]
    assert set(knobs.controls) == {"m1.days", "m2.days", "m3.top", "m3.positive_only"}
    knobs.controls["m3.top"].slider.setValue(3)
    g = ctx.workspace.strategies.get("S9")
    assert g.knob_values == {"m3.top": 3}
    assert 'KNOBS = {"m3.top": 3}' in tab.code.editor.toPlainText()
    knobs.controls["m3.positive_only"].switch.setChecked(False)
    assert g.knob_values["m3.positive_only"] is False
    knobs.reset()
    assert g.knob_values == {} and "KNOBS" not in tab.code.editor.toPlainText()


def test_knobs_dock_follows_the_tab_in_front(win, ctx, qapp):
    view, tab = _code_tab(win, qapp)
    view.new_strategy()
    assert win.views["knobs"].controls == {}
    view.tabs.setCurrentWidget(tab)
    assert len(win.views["knobs"].controls) == 4


def test_import_python_file_opens_one_module_on_the_code_view(win, ctx, qapp, tmp_path):
    f = tmp_path / "hold_everything.py"
    f.write_text(PLAIN_FILE)
    win.show_page("strategies")
    view = win.views["strategies"]
    g = view.import_python(f)
    tab = view.tabs.currentWidget()
    assert g.name == "Hold everything" and [m.id for m in g.modules] == ["decide"]
    assert tab.views.currentIndex() == 1 and "def decide(F, p):" in tab.code.editor.toPlainText()
    assert tab.badge.text() == "1 module"


def test_add_module_from_the_library_and_save(win, ctx, qapp, tmp_path):
    from titanium.core.strategy import load_strategy

    win.show_page("strategies")
    view = win.views["strategies"]
    g = view.new_strategy()
    tab = view.tabs.currentWidget()
    tab.code.add_module("starter/Momentum")
    g = ctx.workspace.strategies.get(g.id)
    assert [m.name for m in g.modules] == ["Momentum"]
    assert "def momentum(view):" in tab.code.editor.toPlainText()
    path = view.save_current(tmp_path)
    assert load_strategy(path).modules[0].name == "Momentum"
    view.close_tab(view.tabs.currentIndex())
    assert g.id not in ctx.workspace.strategies


def test_code_editor_and_knob_control_in_the_kit(qapp):
    from titanium.desktop.design.components import CodeEditor, KnobControl

    ed = CodeEditor()
    ed.setPlainText("x = 1\n")
    ed.set_text_preserving("x = 2\n")
    assert ed.toPlainText() == "x = 2\n"
    ed.undo()
    assert ed.toPlainText() == "x = 1\n"
    seen = []
    k = KnobControl("days", "real", 0.5, 0.0, 1.0)
    k.changed.connect(seen.append)
    k.slider.setValue(100)
    assert seen == [0.5] or seen == []  # 100 of 200 steps is the same value
    k.slider.setValue(200)
    assert seen[-1] == 1.0


# ---- the Data page ---------------------------------------------------------------------
def test_data_page_lists_filters_and_describes_datasets(win, ctx, qapp):
    from titanium.core.strategy import StrategyGraph

    view = win.views["data"]
    view.background = False
    assert view.stack.currentWidget() is view.empty
    dlg = view.open_add()
    dlg.form_for["synthetic_stocks"].set_value("n_symbols", 2)
    dlg.form_for["synthetic_stocks"].set_value("n_days", 10)
    dlg.submit()
    assert len(ctx.workspace.datasets) == 1 and not dlg.isVisible()
    core = ctx.workspace.datasets.infos()[0]
    assert view.table.keys() == [core.id]
    assert view.details.fields.values["Contents"].text().startswith("2 stocks, minute bars")
    assert "New York time" in view.details.fields.values["Range"].text()

    gen = view.open_generate(core.id)
    gen.submit()
    assert ctx.workspace.datasets.counts()[DataKind.GENERATED] == 1
    assert view.kind_counts[DataKind.GENERATED].text() == "1 dataset"
    view.filter.set_index(3)
    assert len(view.table.keys()) == 1 and view.table.keys()[0] != core.id
    view.filter.set_index(0)
    view.search.setText("zzz")
    assert view.stack.currentWidget() is view.no_match
    view.search.setText("")

    ctx.workspace.strategies.put("S1", StrategyGraph("S1", "Gap fade", settings={"datasets": [core.id]}))
    view.table.select(core.id)
    assert "Gap fade" in [view.table.item(i, 5).text() for i in range(view.table.rowCount())]
    assert not view.remove(core.id, confirm=False)  # in use
    assert view.details.error.isVisible()


def test_unavailable_sources_cannot_be_added(win):
    view = win.views["data"]
    dlg = view.open_add("polygon")
    assert dlg.current().name == "synthetic_stocks"  # falls back to a source that works
    row = [s.name for s in dlg.sources].index("polygon")
    assert not dlg.list.item(row).flags() & Qt.ItemIsEnabled
    dlg.list.setCurrentRow(row)
    assert not dlg.ok.isEnabled()
    dlg.reject()


def test_import_needs_files(win):
    view = win.views["data"]
    view.background = False
    dlg = view.open_add("file_import")
    dlg.submit()
    assert dlg.error.isVisible() and len(view.ctx.workspace.datasets) == 0
    dlg.reject()


def test_background_build_reports_errors(win, qapp):
    view = win.views["data"]
    dlg = view.open_add("file_import", {"paths": "/no/such/file.csv"})
    dlg.submit()
    for _ in range(200):
        qapp.processEvents()
        if dlg.error.isVisible():
            break
        import time
        time.sleep(0.01)
    assert "no such file" in dlg.error.text()
    dlg.reject()


def test_self_test_visits_every_view_and_runs_a_strategy(win):
    from titanium.desktop.app import self_test

    win.show()
    assert self_test(win) == []


def test_every_page_fits_a_small_screen(win, qapp):
    """A laptop at 150% scaling with the taskbar on the side gives about 1,230 x 760 points.
    Every page, and the Strategies page with its docks and an open strategy, must fit."""
    from titanium.core.module_library import momentum_rotation

    win.show()
    for view_id, host in win.hosts.items():
        if host == "page":
            win.show_page(view_id)
            qapp.processEvents()
            hint = win.minimumSizeHint()
            assert hint.width() <= 1150 and hint.height() <= 760, (view_id, hint)
    win.show_page("strategies")
    sv = win.views["strategies"]
    sv.open_graph(momentum_rotation(id="S1"))
    tab = sv.tabs.currentWidget()
    for i in range(3):
        tab._switch_to(i)
        qapp.processEvents()
        hint = win.minimumSizeHint()
        assert hint.width() <= 1150 and hint.height() <= 760, (i, hint)
