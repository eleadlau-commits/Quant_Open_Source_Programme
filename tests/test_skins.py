"""Skin packs: built-ins load, every skin builds the app, broken skins fall back, switching restyles."""
import pytest

from titanium.core.plugins import Library, Registry
from titanium.desktop.design import skins, theme

GOOD = """
id = "{id}"
name = "Mine"
extends = "graphite"
[dark]
brand = "#55aaff"
"""


@pytest.fixture
def fresh_skins(qapp):
    """Each test starts from the built-in skins only and ends back on the default."""
    skins.reset()
    yield
    skins.reset()
    theme.apply(qapp, "light", skins.DEFAULT)


def test_builtin_skins_load_and_graphite_is_default(fresh_skins):
    ids = [s.id for s in skins.available()]
    assert ids[0] == skins.DEFAULT == "graphite"
    assert "classic" in ids
    assert skins.problems() == []
    g = skins.get("graphite")
    assert g.effects.run == "capsule" and g.effects.primary == "edge"
    assert skins.get("classic").light.primary == "#2f5bd3"  # the original look is kept exactly


def test_a_user_skin_can_extend_a_builtin(fresh_skins, tmp_path):
    (tmp_path / "mine.toml").write_text(GOOD.format(id="mine"))
    loaded = skins.load_folder(tmp_path)
    assert [s.id for s in loaded] == ["mine"]
    mine = skins.get("mine")
    assert mine.dark.brand == "#55aaff"
    assert mine.dark.window == skins.get("graphite").dark.window  # inherited
    assert mine.effects == skins.get("graphite").effects


@pytest.mark.parametrize("text, reason", [
    ("id = 'bad'\nname = 'x'\nthis is not toml", "Skipped skin"),
    ("id = 'bad'\nextends = 'graphite'\n[dark]\nbrand = 'red'", "not a #rrggbb"),
    ("id = 'bad'\nextends = 'graphite'\n[light]\nsparkle = '#ffffff'", "unknown colour"),
    ("id = 'bad'\nextends = 'nope'", "isn't loaded"),
    ("id = 'bad'\nextends = 'graphite'\n[effects]\nrun = 'rocket'", "effects.run"),
    ("id = 'bad'\nname = 'no colours'\n[shape]\nradius = {sm=1, md=2, lg=3, xl=4}", "missing colours"),
])
def test_a_broken_skin_is_skipped_and_the_default_is_used(fresh_skins, tmp_path, qapp, text, reason):
    (tmp_path / "bad.toml").write_text(text)
    assert skins.load_folder(tmp_path) == []
    assert any(reason in p for p in skins.problems()), skins.problems()
    assert skins.get("bad").id == skins.DEFAULT
    theme.apply(qapp, "dark", "bad")  # never crashes
    assert theme.skin().id == skins.DEFAULT


def test_a_user_skin_cannot_replace_a_builtin(fresh_skins, tmp_path):
    (tmp_path / "graphite.toml").write_text(GOOD.format(id="graphite"))
    skins.load_folder(tmp_path)
    assert skins.get("graphite").source == ""
    assert any("built-in" in p for p in skins.problems())


def test_a_missing_folder_is_fine(fresh_skins, tmp_path):
    assert skins.load_folder(tmp_path / "nothing-here") == []
    assert skins.problems() == []


def test_plugins_can_add_skins(fresh_skins, tmp_path):
    path = tmp_path / "plug.toml"
    path.write_text(GOOD.format(id="from-path"))
    reg = Registry()
    reg.add(Library.SKINS, "from-path", path, plugin="neon")
    reg.add(Library.SKINS, "from-data", {"id": "from-data", "extends": "classic"}, plugin="neon")
    skins.load_plugin_entries(reg.entries(Library.SKINS))
    ids = {s.id for s in skins.available()}
    assert {"from-path", "from-data"} <= ids


@pytest.mark.parametrize("skin_id", ["graphite", "classic"])
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_window_and_gallery_build_under_every_skin(qapp, ctx, skin_id, mode):
    from titanium.desktop.app import build_window
    from titanium.desktop.design.gallery import build

    theme.apply(qapp, mode, skin_id)
    try:
        assert theme.skin().id == skin_id and theme.current().name == mode
        w = build_window(ctx)
        w.show()
        w.show_page("strategies")
        w.views["strategies"].new_strategy()
        qapp.processEvents()
        w.close()
        g = build()
        g.resize(1200, 800)
        g.show()
        qapp.processEvents()
        g.close()
    finally:
        theme.apply(qapp, "light", skins.DEFAULT)


def test_switching_skin_restyles_and_is_remembered(qapp, ctx):
    from titanium.desktop.app import build_window

    win = build_window(ctx)
    win.show()
    settings = win.views["settings"]
    calls = []
    theme.watch(win, lambda w: calls.append(theme.skin().id))
    try:
        settings.skin_box.setCurrentIndex(settings.skin_box.findData("classic"))
        assert theme.skin().id == "classic"
        assert ctx.settings.value("view/skin") == "classic"
        assert calls[-1] == "classic"  # watchers fired, so icons and painting follow
        settings.skin_box.setCurrentIndex(settings.skin_box.findData("graphite"))
        assert theme.skin().id == "graphite" and calls[-1] == "graphite"
    finally:
        win.close()
        theme.apply(qapp, "light", skins.DEFAULT)


def test_run_button_shows_running(qapp):
    from titanium.desktop.design.components import RunButton

    b = RunButton("Run", "Ctrl ↵")
    assert b.label.text() == "Run" and b.hint.text() == "Ctrl ↵"
    b.set_running(True, "61%")
    assert b.property("running") == "true" and b.label.text() == "Running" and b.hint.text() == "61%"
    b.set_running(False)
    assert b.label.text() == "Run" and b.hint.text() == "Ctrl ↵"
    assert b.sizeHint().height() > 0


def test_glow_only_on_skins_that_ask_for_it(qapp):
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    from titanium.desktop.design.components import RunButton

    b = RunButton()
    try:
        theme.apply(qapp, "dark", "graphite")
        assert isinstance(b.graphicsEffect(), QGraphicsDropShadowEffect)
        theme.apply(qapp, "dark", "classic")
        assert b.graphicsEffect() is None
    finally:
        theme.apply(qapp, "light", skins.DEFAULT)
