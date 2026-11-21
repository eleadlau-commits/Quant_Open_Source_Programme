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
