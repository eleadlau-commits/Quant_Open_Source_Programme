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
    assert not win.docks["module_library"].isVisible()
    win.show_page("strategies")
    qapp.processEvents()
    assert win.docks["module_library"].isVisible()
    assert not win.docks["knobs"].isVisible() and not win.docks["trade_log"].isVisible()  # pop-outs start hidden
    win.show_page("compare")
    assert not win.docks["module_library"].isVisible()


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
    assert not view.close_tab(0)  # the default strategy never closes
    view.close_tab(view.tabs.currentIndex())
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
    market = view.details.market.text()
    assert market.startswith("Nasdaq (US)") and "Regular 09:30–16:00" in market and "USD" in market
    assert "Runs trade regular hours" in market
    assert view.table.item(0, 2).text() == "Nasdaq"
    view.market_filter.setCurrentIndex(view.market_filter.findData("cme"))
    assert view.stack.currentWidget() is view.no_match
    view.market_filter.setCurrentIndex(0)

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
    assert "Gap fade" in [view.table.item(i, 6).text() for i in range(view.table.rowCount())]
    assert not view.remove(core.id, confirm=False)  # in use
    assert view.details.error.isVisible()


def test_unavailable_sources_cannot_be_added(win):
    view = win.views["data"]
    dlg = view.open_add("polygon")
    assert dlg.current().name == "synthetic_stocks"  # falls back to a source that works
    row = dlg.row_of["polygon"]
    assert not dlg.list.item(row).flags() & Qt.ItemIsEnabled
    dlg.list.setCurrentRow(row)
    assert not dlg.ok.isEnabled()
    dlg.reject()


def test_add_dataset_groups_sources_by_market(win):
    dlg = win.views["data"].open_add()
    headings = [dlg.list.item(i).text() for i in range(dlg.list.count()) if dlg.list.item(i).data(Qt.UserRole) is None]
    assert headings[:2] == ["Nasdaq (US)", "CME Globex (US index futures)"] and headings[-1] == "Any market"
    assert dlg.row_of["synthetic_stocks"] < dlg.row_of["synthetic_futures"] < dlg.row_of["file_import"]
    dlg.list.setCurrentRow(dlg.row_of["synthetic_futures"])
    assert dlg.current().name == "synthetic_futures" and "Makes CME data" in dlg.doc.text()
    dlg.list.setCurrentRow(0)  # a heading can't be picked
    assert dlg.current().name == "synthetic_futures"
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


def test_first_launch_adds_samples_once(win, ctx, qapp):
    from titanium.desktop.app import add_samples_on_first_launch

    assert add_samples_on_first_launch(ctx, background=False)
    assert len(ctx.workspace.datasets) == 2
    view = win.views["data"]
    assert view.samples_row.isVisibleTo(view)
    assert not add_samples_on_first_launch(ctx, background=False)  # only the first time
    view.remove_samples()
    assert not len(ctx.workspace.datasets) and not view.samples_row.isVisibleTo(view)
    assert not add_samples_on_first_launch(ctx, background=False)


def test_panels_menu_shows_and_hides_docks_and_remembers(win, ctx, qapp):
    from PySide6.QtCore import QSettings

    from titanium.desktop.app import build_window
    from titanium.desktop.context import AppContext

    assert win.panels_button.parent() is win.rail
    menu = win.panels_menu()
    acts = {a.data(): a for a in menu.actions() if a.isCheckable()}
    assert {"module_library", "knobs", "trade_log"} <= set(acts)
    win.show_page("data")
    win.docks["module_library"].hide_by_user()  # the close button
    assert not win.panels_menu().actions()[[a.data() for a in win.panels_menu().actions()].index("module_library")].isChecked()
    # a new window remembers it was closed
    again = build_window(AppContext(QSettings(ctx.settings.fileName(), QSettings.IniFormat), ctx.workspace))
    assert again.docks["module_library"].user_hidden
    again.close()
    # showing it from the menu goes to a page it belongs on
    win.set_panel_shown("module_library", True)
    assert win.current == "strategies" and win.docks["module_library"].isVisible()
    assert "module_library" not in win._saved_hidden()


def test_wrapped_text_is_never_squeezed(qapp):
    """A wrapped label keeps the height its text needs, so a short container scrolls instead of
    cutting text off mid-line (the Data details pane used to slice its ticker list)."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from titanium.desktop.design.components import label, scrolling

    text = ", ".join(f"SYN{i:03d}" for i in range(40))
    lbl = label(text, wrap=True)
    box = QWidget()
    QVBoxLayout(box).addWidget(lbl)
    area = scrolling(box)
    area.resize(160, 60)  # far shorter than the text
    area.show()
    qapp.processEvents()
    assert lbl.height() >= lbl.heightForWidth(lbl.width()) > 60
    assert area.verticalScrollBar().maximum() > 0  # it scrolls rather than clips
    lbl.setText("short")
    qapp.processEvents()
    assert lbl.minimumHeight() < 30 and area.verticalScrollBar().maximum() == 0  # and lets go for less text
    area.close()


# ---- strategies: one add button, the pinned default, closing and deleting ---------------
def test_one_add_button_in_the_header_with_the_add_options(win):
    view = win.views["strategies"]
    new = next(w for w in view.actions_bar() if w.text() == "New strategy")
    texts = [a.text() for a in new.menu().actions()]
    assert texts == ["New empty strategy", "From the strategy library…", "Import a Python file…",
                     "Open a strategy file…"]
    assert view.tabs.cornerWidget(Qt.TopRightCorner) is None  # no second + by the tabs
    before = view.tabs.count()
    new.menu().actions()[0].trigger()
    assert view.tabs.count() == before + 1


def test_default_strategy_is_pinned_first_read_only_and_never_closes(win, ctx, qapp):
    from PySide6.QtWidgets import QTabBar

    from titanium.core.default_strategy import DEFAULT_STRATEGY_ID

    view = win.views["strategies"]
    tab = view.tabs.widget(0)
    assert tab is view.default_tab and tab.locked and view.tabs.tabText(0) == "Default"
    assert DEFAULT_STRATEGY_ID in ctx.workspace.strategies
    assert view.tabs.tabBar().tabButton(0, QTabBar.RightSide) is None
    assert tab.badge.text() == "Read-only" and tab.duplicate_btn.isVisibleTo(tab)
    assert tab.code.editor.isReadOnly() and not tab.patch.add_btn.isVisibleTo(tab.patch)
    # its logic can't change, its knobs can
    before = len(tab.patch.graph.modules)
    tab.patch.add_module("starter/Momentum")
    assert len(ctx.workspace.strategies.get(DEFAULT_STRATEGY_ID).modules) == before
    assert tab.patch.error.text() == "Read-only"
    tab.patch.turn_knob("hold.exposure", 0.5)
    assert ctx.workspace.strategies.get(DEFAULT_STRATEGY_ID).knob_values == {"hold.exposure": 0.5}
    # no close, no delete
    assert not view.close_tab(0)
    assert not view.ask_delete(DEFAULT_STRATEGY_ID)
    assert [a.text() for a in view._tab_menu(0).actions()] == ["Duplicate to edit"]
    # moved tabs never push it off the left
    view.new_strategy()
    view.tabs.tabBar().moveTab(1, 0)
    qapp.processEvents()
    assert view.tabs.widget(0) is view.default_tab
    # duplicating gives an editable copy with its own id
    copy = view.duplicate(DEFAULT_STRATEGY_ID)
    assert copy.id != DEFAULT_STRATEGY_ID and copy.name == "Hold everything"
    assert not view.tabs.currentWidget().locked and not view.tabs.currentWidget().code.editor.isReadOnly()


def test_new_strategies_show_names_reuse_free_numbers_and_rename(win, ctx):
    view = win.views["strategies"]
    a, b = view.new_strategy(), view.new_strategy()
    assert (a.name, b.name) == ("Strategy 1", "Strategy 2")
    assert view.tabs.tabText(view.tabs.indexOf(view.tab_of(b.id))) == "Strategy 2"  # no id shown
    view.close_tab(view.tabs.indexOf(view.tab_of(a.id)))
    c = view.new_strategy()
    assert c.name == "Strategy 1" and c.id not in (a.id, b.id)
    assert view.rename(c.id, "Gap fade")
    assert ctx.workspace.strategies.get(c.id).name == "Gap fade"
    assert view.tabs.tabText(view.tabs.indexOf(view.tab_of(c.id))) == "Gap fade"
    texts = [x.text() for x in view._tab_menu(view.tabs.indexOf(view.tab_of(c.id))).actions() if x.text()]
    assert texts == ["Save", "Rename…", "Duplicate", "Close", "Delete…"]


def test_closing_asks_about_unsaved_changes_and_keeps_runs(win, ctx, tmp_path, monkeypatch):
    from titanium.desktop.pages.strategies import StrategiesView

    view = win.views["strategies"]
    g = view.new_strategy()
    tab = view.tab_of(g.id)
    asked = []
    monkeypatch.setattr(StrategiesView, "ask_save", lambda self, t: asked.append(t) or "cancel")
    assert view.close_tab(view.tabs.indexOf(tab))
    assert not asked  # nothing changed: closes without asking
    g = view.new_strategy()
    tab = view.tab_of(g.id)
    tab.code.add_module("starter/Momentum")
    assert not view.close_tab(view.tabs.indexOf(tab)) and asked  # cancelled
    path = view.save_current(tmp_path, tab=tab)
    assert path.name == f"{g.name}.json"
    asked.clear()
    assert view.close_tab(view.tabs.indexOf(tab)) and not asked
    # opening the file again brings the same strategy back (same id, so its runs are still its own)
    again = view.open_file(path)
    assert again.id == g.id


def test_deleting_removes_the_tab_runs_and_optionally_the_file(win, ctx, tmp_path, monkeypatch):
    from titanium.core.module_library import momentum_rotation
    from titanium.desktop.pages.strategies import StrategiesView

    ws = ctx.workspace
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 3, "n_days": 25, "seed": 4})
    view = win.views["strategies"]
    g = momentum_rotation(id=ws.new_strategy_id())
    g.settings["datasets"] = [info.id]
    view.open_graph(g)
    rec = ws.runs.run(g.id)
    path = view.save_current(tmp_path)
    seen = []
    monkeypatch.setattr(StrategiesView, "confirm_delete",
                        lambda self, tab, fp: seen.append(fp) or (False, False))
    assert not view.ask_delete(g.id) and view.tab_of(g.id) is not None  # cancelled: nothing goes
    assert seen[0].runs == 1
    monkeypatch.setattr(StrategiesView, "confirm_delete", lambda self, tab, fp: (True, True))
    assert view.ask_delete(g.id)
    assert view.tab_of(g.id) is None and g.id not in ws.strategies and rec.id not in ws.runs
    assert not path.exists()
