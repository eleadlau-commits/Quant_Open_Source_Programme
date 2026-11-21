"""The patch bay: graph edits, the canvas, the module library folders, and the round trip with the Code view."""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from titanium.app.module_folders import ModuleFolderError, ModuleFolders
from titanium.app.workspace import Workspace
from titanium.core import patchbay as pb
from titanium.core.module_library import STARTER, ModuleTemplate, momentum_rotation, register_starters
from titanium.core.plugins import Library, Registry
from titanium.core.strategy import Link, StrategyGraph, graph_to_dict
from titanium.core.strategy_code import generate, update_from_code


def _reg():
    reg = Registry()
    register_starters(reg)
    return reg


# ---------------------------------------------------------------- graph edits (no UI)
def test_link_refuses_taken_inputs_and_unknown_ports_with_reasons():
    g = momentum_rotation()  # m1 -> m2 -> m3
    taken = pb.link_problem(g, Link("m1", "scores", "m3", "scores"))
    assert "already taken by Above moving average" in taken
    with pytest.raises(pb.LinkRefused, match="taken"):
        pb.add_link(g, Link("m1", "scores", "m3", "scores"))
    assert "already linked" in pb.link_problem(g, Link("m1", "scores", "m2", "scores"))
    assert "no output" in pb.link_problem(g, Link("m1", "nope", "m2", "scores"))
    assert "no input" in pb.link_problem(g, Link("m1", "scores", "m2", "nope"))
    assert "no longer" in pb.link_problem(g, Link("m9", "scores", "m2", "scores"))


def test_a_cycle_is_refused():
    reg = _reg()
    g = StrategyGraph("S1", "Loop")
    g, a = pb.add_from_library(g, reg, f"{STARTER}/Above moving average")
    g, b = pb.add_from_library(g, reg, f"{STARTER}/Above moving average")
    g = pb.add_link(g, Link(a.id, "scores", b.id, "scores"))
    reason = pb.link_problem(g, Link(b.id, "scores", a.id, "scores"))
    assert reason and "loop" in reason
    assert "itself" in pb.link_problem(g, Link(b.id, "scores", b.id, "scores")) or \
        "taken" in pb.link_problem(g, Link(b.id, "scores", b.id, "scores"))
    assert "itself" in pb.link_problem(pb.remove_links(g, g.links), Link(b.id, "scores", b.id, "scores"))


def test_edits_return_new_graphs_and_leave_the_old_one_alone():
    g = momentum_rotation()
    before = graph_to_dict(g)
    g2 = pb.remove_modules(g, ["m2"])
    assert graph_to_dict(g) == before
    assert [m.id for m in g2.modules] == ["m1", "m3"] and g2.links == []
    g3 = pb.move(g, {"m1": (10, 20)})
    assert g3.module("m1").layout == (10.0, 20.0) and g.module("m1").layout == (40.0, 60.0)
    g4 = pb.set_knob(g, "m1.days", 30)
    assert g4.knob_values == {"m1.days": 30} and g.knob_values == {}
    assert pb.set_knob(g4, "m1.days", 20).knob_values == {}
    g5 = pb.rename(g, "m1", "  Fast   momentum ")
    assert g5.module("m1").name == "Fast momentum"
    with pytest.raises(ValueError):
        pb.rename(g, "m1", "  ")


def test_removing_a_module_drops_its_turned_knobs():
    g = pb.set_knob(momentum_rotation(), "m1.days", 30)
    assert pb.remove_modules(g, ["m1"]).knob_values == {}


def test_duplicate_copies_modules_inner_links_and_knob_values():
    g = pb.set_knob(momentum_rotation(), "m1.days", 30)
    g2, made = pb.duplicate(g, ["m1", "m2"])
    assert len(made) == 2 and len(g2.modules) == 5
    a, b = made
    assert Link(a, "scores", b, "scores") in g2.links
    assert g2.knob_values[f"{a}.days"] == 30
    assert g2.module(a).layout == (72.0, 92.0)
    update_from_code(g2, generate(g2))  # the copies still make a valid file


def test_tidy_lays_out_columns_in_link_order():
    g = momentum_rotation()
    g = pb.move(g, {"m1": (900, 0), "m2": (0, 400), "m3": (300, 900)})
    t = pb.tidy(g)
    xs = [t.module(i).layout[0] for i in ("m1", "m2", "m3")]
    assert xs == sorted(xs) and len(set(xs)) == 3
    assert {t.module(i).layout[1] for i in ("m1", "m2", "m3")} == {40.0}


def test_modules_without_a_position_are_placed_beside_the_others():
    g = momentum_rotation()
    g, m = pb.add_from_library(g, _reg(), f"{STARTER}/Momentum")
    spot = pb.place_new(g)
    assert set(spot) == {m.id} and spot[m.id][0] > 632


# ---------------------------------------------------------------- your module folders (no UI)
def test_module_folders_create_rename_move_delete(tmp_path):
    reg = _reg()
    lib = ModuleFolders(reg, tmp_path)
    assert lib.folders() == []
    lib.create_folder("Signals")
    with pytest.raises(ModuleFolderError, match="already"):
        lib.create_folder("signals")
    with pytest.raises(ModuleFolderError, match="starter"):
        lib.create_folder("Starter")
    entry = lib.copy_to(f"{STARTER}/Momentum", "Signals")
    assert entry == "Signals/Momentum" and lib.is_mine(entry)
    assert not lib.is_mine(f"{STARTER}/Momentum")
    assert reg.get(Library.MODULES, entry).code == reg.get(Library.MODULES, f"{STARTER}/Momentum").code
    assert lib.copy_to(f"{STARTER}/Momentum", "Signals") == "Signals/Momentum 2"
    entry = lib.rename(entry, "Fast momentum")
    lib.create_folder("Filters")
    moved = lib.move(entry, "Filters")
    assert moved == "Filters/Fast momentum" and lib.modules("Signals") == ["Momentum 2"]
    with pytest.raises(ModuleFolderError, match="still has modules"):
        lib.delete_folder("Filters")
    assert lib.rename_folder("Filters", "Trend") == "Trend"
    assert lib.modules("Trend") == ["Fast momentum"]
    lib.delete("Trend/Fast momentum")
    lib.delete_folder("Trend")
    assert lib.folders() == ["Signals"]
    with pytest.raises(ModuleFolderError, match="your own folders"):
        lib.delete(f"{STARTER}/Momentum")
    # what is on disk comes back in a new session
    reg2 = _reg()
    ModuleFolders(reg2, tmp_path)
    assert "Signals/Momentum 2" in [e.name for e in reg2.entries(Library.MODULES)]


def test_a_broken_module_file_is_skipped(tmp_path):
    (tmp_path / "Mine").mkdir()
    (tmp_path / "Mine" / "bad.json").write_text("{not json")
    lib = ModuleFolders(_reg(), tmp_path)
    assert lib.folders() == ["Mine"] and lib.modules("Mine") == []


def test_workspace_keeps_user_modules_in_its_folder(tmp_path):
    ws = Workspace(modules_root=tmp_path)
    ws.modules.save("Mine", ModuleTemplate("Hold all", "decide", "def hold_all(view):\n    return {}\n", []))
    assert (tmp_path / "Mine").is_dir()
    assert "Mine/Hold all" in [e.name for e in ws.registry.entries(Library.MODULES)]


# ---------------------------------------------------------------- the canvas
@pytest.fixture
def win(qapp, ctx, tmp_path, monkeypatch):
    from titanium.desktop.app import build_window

    monkeypatch.setenv("TITANIUM_HOME", str(tmp_path / "home"))
    w = build_window(ctx)
    w.resize(1280, 820)
    w.show()
    w.show_page("strategies")
    qapp.processEvents()
    yield w
    w.close()


def _bay(win, qapp, graph=None):
    view = win.views["strategies"]
    g = graph or momentum_rotation(id="S7")
    view.open_graph(g, view=0)
    qapp.processEvents()
    tab = view.tabs.currentWidget()
    return tab, tab.patch


def test_the_patch_bay_draws_every_module_and_cable(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    assert tab.views.currentWidget() is bay
    assert set(bay.scene.nodes) == {"m1", "m2", "m3"} and len(bay.scene.cables) == 2
    node = bay.scene.nodes["m1"]
    assert (node.pos().x(), node.pos().y()) == (40.0, 60.0)
    assert [k.key for k in bay.scene.nodes["m3"].spec.knobs] == ["m3.top", "m3.positive_only"]


def test_canvas_edits_go_through_the_workspace_and_show_in_code(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.unplug([Link("m2", "scores", "m3", "scores")])
    assert ctx.workspace.strategies.get("S7").links == [Link("m1", "scores", "m2", "scores")]
    assert 'links={"scores": "m2.scores"}' not in tab.code.editor.toPlainText()
    assert bay.link("m1", "scores", "m3", "scores")
    assert 'links={"scores": "m1.scores"}' in tab.code.editor.toPlainText().split("def top_n_equal_weight")[0]
    # refused: the input is taken; nothing changes and the reason is shown
    before = graph_to_dict(ctx.workspace.strategies.get("S7"))
    assert not bay.link("m2", "scores", "m3", "scores")
    assert graph_to_dict(ctx.workspace.strategies.get("S7")) == before
    assert not bay.error.isHidden() and "already taken" in bay.status.text()
    # a knob turned on a module shows in the code and the Knobs dock
    bay.turn_knob("m3.top", 8)
    assert '"m3.top": 8' in tab.code.editor.toPlainText()
    assert win.views["knobs"].controls["m3.top"].value == 8


def test_code_edits_redraw_the_canvas(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    tab.switch.set_index(1)
    src = tab.code.editor.toPlainText()
    src = src.replace('name="Momentum"', 'name="Slow momentum"')
    src = src.replace('@module(id="m3", name="Top N equal weight", kind="decide", links={"scores": "m2.scores"})',
                      '@module(id="m3", name="Top N equal weight", kind="decide", links={"scores": "m1.scores"})')
    tab.code.editor.setPlainText(src)
    assert tab.code.read_back()
    assert bay.scene.nodes["m1"].spec.title == "Slow momentum"
    assert {(c.ends.src, c.ends.dst) for c in bay.scene.cables} == {("m1", "m2"), ("m1", "m3")}
    assert bay.scene.nodes["m1"].pos().x() == 40.0  # positions are kept across code edits


def test_round_trip_both_ways_keeps_the_graph(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.add_module(f"{STARTER}/Momentum", QPointF(100, 400))
    new_id = [i for i in bay.scene.nodes if i not in ("m1", "m2", "m3")][0]
    bay.move_modules({"m2": (360.0, 200.0)})
    bay.rename_module(new_id, "Second momentum")
    g = ctx.workspace.strategies.get("S7")
    # the code view's file reads back into the same graph (layout comes along from the graph);
    # the only difference is the copy's function name, which the file keeps unique
    tab.switch.set_index(1)

    def shape(graph):
        d = graph_to_dict(graph)
        for m in d["modules"]:
            m.pop("code")
        return d

    assert shape(update_from_code(g, tab.code.editor.toPlainText())) == shape(g)
    assert tab.code.read_back()
    assert shape(ctx.workspace.strategies.get("S7")) == shape(g)
    g = ctx.workspace.strategies.get("S7")
    assert "def momentum_2(view)" in g.module(new_id).code
    assert graph_to_dict(update_from_code(g, generate(g))) == graph_to_dict(g)  # and stable from then on
    assert bay.scene.nodes[new_id].spec.title == "Second momentum"
    assert g.module("m2").layout == (360.0, 200.0)


def test_delete_undo_redo(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.scene.nodes["m2"].setSelected(True)
    bay.delete_selection()
    assert "m2" not in [m.id for m in ctx.workspace.strategies.get("S7").modules]
    assert ctx.workspace.strategies.get("S7").links == []
    assert bay.undo()
    g = ctx.workspace.strategies.get("S7")
    assert [m.id for m in g.modules] == ["m1", "m2", "m3"] and len(g.links) == 2
    assert 'id="m2"' in tab.code.editor.toPlainText()
    assert bay.redo()
    assert "m2" not in [m.id for m in ctx.workspace.strategies.get("S7").modules]
    assert not bay.redo()
    # a selected cable on its own is unplugged
    bay.undo()
    bay.scene.clearSelection()
    bay.scene.cables[0].setSelected(True)
    bay.delete_selection()
    assert len(ctx.workspace.strategies.get("S7").links) == 1


def test_delete_key_removes_the_selection(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.view.setFocus()
    bay.scene.nodes["m1"].setSelected(True)
    QTest.keyClick(bay.view, Qt.Key_Delete)
    qapp.processEvents()
    assert [m.id for m in ctx.workspace.strategies.get("S7").modules] == ["m2", "m3"]
    QTest.keyClick(bay.view, Qt.Key_Z, Qt.ControlModifier)
    assert len(ctx.workspace.strategies.get("S7").modules) == 3


def test_dragging_a_cable_with_the_mouse(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.unplug([Link("m2", "scores", "m3", "scores")])
    view, scene = bay.view, bay.scene
    a = view.mapFromScene(scene.nodes["m1"].output_pos("scores"))
    b = view.mapFromScene(scene.nodes["m3"].input_pos("scores"))
    vp = view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(vp, (a + b) / 2)
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, b)
    qapp.processEvents()
    assert Link("m1", "scores", "m3", "scores") in ctx.workspace.strategies.get("S7").links
    # picking the cable off its input and dropping it on nothing unplugs it
    c = view.mapFromScene(scene.nodes["m3"].input_pos("scores"))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, c)
    QTest.mouseMove(vp, c + type(c)(-40, 200))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, c + type(c)(-40, 200))
    qapp.processEvents()
    assert Link("m1", "scores", "m3", "scores") not in ctx.workspace.strategies.get("S7").links


def test_moving_a_module_saves_its_position(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    view, node = bay.view, bay.scene.nodes["m1"]
    start = view.mapFromScene(node.mapToScene(QPointF(60, 12)))
    end = start + type(start)(0, 120)
    vp = view.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, start)
    for i in range(1, 7):
        QTest.mouseMove(vp, start + type(start)(0, 20 * i))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, end)
    qapp.processEvents()
    x, y = ctx.workspace.strategies.get("S7").module("m1").layout
    assert x == 40.0 and y > 100


def test_menus_offer_add_remove_rename_unplug(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    texts = lambda m: [a.text() for a in m.actions()]  # noqa: E731
    empty = bay.build_menu(None, QPointF(0, 0))
    assert "Add module here" in texts(empty) and "Tidy layout" in texts(empty)
    add = empty.actions()[0].menu()
    assert "Momentum" in texts(add)
    node = bay.build_menu(bay.scene.nodes["m3"], QPointF(0, 0))
    assert {"Rename…", "Show code", "Unplug", "Duplicate", "Remove"} <= set(texts(node))
    cable = bay.build_menu(bay.scene.cables[0], QPointF(0, 0))
    assert texts(cable)[0] == "Unplug"
    cable.actions()[0].trigger()
    assert len(ctx.workspace.strategies.get("S7").links) == 1


def test_tidy_zoom_and_fit(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.move_modules({"m1": (900.0, 500.0)})
    bay.tidy()
    g = ctx.workspace.strategies.get("S7")
    assert g.module("m1").layout[0] < g.module("m2").layout[0] < g.module("m3").layout[0]
    bay.view.set_zoom(1.0)
    bay.zoom_in_btn.click()
    assert bay.view.zoom() == pytest.approx(1.2)
    bay.view.set_zoom(99)
    assert bay.view.zoom() == pytest.approx(2.5)
    assert bay.zoom_label.text() == "250%"


def test_show_code_puts_the_cursor_on_the_module(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.show_code.emit("m3")
    assert tab.views.currentWidget() is tab.code
    line = tab.code.editor.textCursor().block().text()
    assert line.startswith("def top_n_equal_weight")


def test_knob_dragged_on_a_module(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    node = bay.scene.nodes["m1"]
    track = node._track(0)
    vp = bay.view.viewport()
    p = bay.view.mapFromScene(node.mapToScene(QPointF(track.right() - 1, track.center().y())))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p)
    qapp.processEvents()
    assert ctx.workspace.strategies.get("S7").knob_value("m1.days") >= 115
    # a switch flips with one click
    node = bay.scene.nodes["m3"]
    r = node.knob_rect(1)
    p = bay.view.mapFromScene(node.mapToScene(QPointF(r.right() - 10, r.top() + 10)))
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p)
    qapp.processEvents()
    assert ctx.workspace.strategies.get("S7").knob_value("m3.positive_only") is False


def test_empty_strategy_shows_a_hint_and_accepts_a_module(win, ctx, qapp):
    view = win.views["strategies"]
    g = view.new_strategy()
    bay = view.tabs.currentWidget().patch
    assert bay.view.empty_text and not bay.scene.nodes
    mid = bay.add_module(f"{STARTER}/Top N equal weight", QPointF(200, 100))
    assert ctx.workspace.strategies.get(g.id).module(mid).layout == (176.0, 84.0)


# ---------------------------------------------------------------- the Module library dock
def test_module_library_lists_folders_searches_and_adds(win, ctx, qapp):
    lib = win.views["module_library"]
    top = [lib.tree.topLevelItem(i).text(0) for i in range(lib.tree.topLevelItemCount())]
    assert top[0] == "Starter"
    assert lib.visible_modules() == [f"{STARTER}/Above moving average", f"{STARTER}/Momentum",
                                     f"{STARTER}/Top N equal weight"]
    lib.search.setText("equal")
    assert lib.visible_modules() == [f"{STARTER}/Top N equal weight"]
    lib.search.setText("")
    tab, bay = _bay(win, qapp)
    ctx.workspace.focus_strategy("S7")
    mid = lib.add_to_strategy(f"{STARTER}/Momentum")
    assert mid in bay.scene.nodes and len(ctx.workspace.strategies.get("S7").modules) == 4


def test_module_library_folders_from_the_dock(win, ctx, qapp):
    lib = win.views["module_library"]
    assert lib.new_folder("Mine")
    assert lib.copy_module(f"{STARTER}/Momentum", "Mine") == "Mine/Momentum"
    names = [lib.tree.topLevelItem(i).text(0) for i in range(lib.tree.topLevelItemCount())]
    assert names == ["Starter", "Mine"]
    assert lib.new_folder("Mine") is None and not lib.error.isHidden()
    assert lib.rename_module("Mine/Momentum", "Fast") == "Mine/Fast"
    lib.new_folder("Other")
    assert lib.file_module("Mine/Fast", "Other") == "Other/Fast"
    assert lib.delete_folder("Other") is None  # not empty
    assert lib.delete_module("Other/Fast") and lib.delete_folder("Other")
    menu = lib.build_menu(None)
    assert [a.text() for a in menu.actions()] == ["New folder…"]
    starter_item = lib.tree.topLevelItem(0).child(0)
    assert "Copy to" in [a.text() for a in lib.build_menu(starter_item).actions()]
    assert (ctx.workspace.modules.root / "Mine").is_dir()


def test_save_a_module_from_the_canvas_into_a_folder(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.rename_module("m1", "My momentum")
    entry = bay.save_to_folder("m1", "Signals")
    assert entry == "Signals/My momentum"
    lib = win.views["module_library"]
    assert entry in lib.visible_modules()
    # and back onto the canvas from there
    mid = bay.add_module(entry, QPointF(0, 300))
    assert ctx.workspace.strategies.get("S7").module(mid).source == entry


def test_dropping_a_library_module_on_the_canvas(win, ctx, qapp):
    tab, bay = _bay(win, qapp)
    bay.view.dropped.emit(f"{STARTER}/Momentum", QPointF(500, 500))
    g = ctx.workspace.strategies.get("S7")
    assert len(g.modules) == 4 and g.modules[-1].layout == (476.0, 484.0)
    data = win.views["module_library"].tree.mimeData([win.views["module_library"].tree.topLevelItem(0).child(1)])
    from titanium.desktop.views import MODULE_MIME

    assert bytes(data.data(MODULE_MIME)).decode() == f"{STARTER}/Momentum"


def test_patch_bay_in_every_skin(qapp, ctx, tmp_path, monkeypatch):
    from titanium.desktop.app import build_window
    from titanium.desktop.design import skins, theme

    monkeypatch.setenv("TITANIUM_HOME", str(tmp_path / "home"))
    try:
        for sk in skins.available():
            for mode in ("light", "dark"):
                theme.apply(qapp, mode, sk.id)
                w = build_window(ctx)
                w.show()
                w.show_page("strategies")
                w.views["strategies"].open_graph(momentum_rotation(id="S8"), view=0)
                qapp.processEvents()
                assert not w.grab().isNull()
                w.close()
    finally:
        theme.apply(qapp, "light", skins.DEFAULT)
