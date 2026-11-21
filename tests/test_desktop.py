"""The shell: pages, docks, moving views between them, themes, the gallery."""
import pytest

from titanium.desktop.app import build_window
from titanium.desktop.design import theme
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
