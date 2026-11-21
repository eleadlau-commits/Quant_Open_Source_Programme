"""Plugins: loading, requirements, failures, the import rule, on/off, .tiplug packs, the CLI."""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
import zipfile

import pytest

from titanium.app.plugins import PluginManager, PluginProblem, check_imports, read_manifest
from titanium.app.settings import RunDefaults
from titanium.app.workspace import Workspace
from titanium.core.module_library import LIBRARY_PLUGIN, load_library_folder, template_from_file
from titanium.core.plugins import Library, Registry
from titanium.plugins import BUILTIN_DIR
from titanium.plugins import pack as P
from titanium.plugins.__main__ import main as cli

BUILTINS = sorted(p.name for p in BUILTIN_DIR.iterdir() if (p / "plugin.json").exists())


def make(base, pid, code="", provides=None, requires=(), main="plugin.py", **extra):
    """A plugin folder in ``base``."""
    folder = base / pid
    folder.mkdir(parents=True)
    manifest = {"id": pid, "name": pid.replace("-", " ").capitalize(), "version": "1.0.0", "api": 1,
                "main": main, "provides": provides or {}, "requires": list(requires), **extra}
    (folder / "plugin.json").write_text(json.dumps(manifest))
    if main:
        (folder / main).write_text(textwrap.dedent(code) or "def setup(plugin):\n    pass\n")
    return folder


SOURCE = '''
from titanium.sdk import Library, Source


class S(Source):
    name = "{name}"
    title = "{name}"


def setup(plugin):
    plugin.add(Library.DATA_SOURCES, "{name}", S())
'''


def manager(user=None, builtin=BUILTIN_DIR, state=None):
    return PluginManager(Registry(), user_folder=user, state_file=state, builtin_folder=builtin)


# ---- the built-in plugins ------------------------------------------------------------------
def test_builtin_plugins_all_load_and_tag_their_entries():
    mgr = manager()
    mgr.load()
    assert [s.id for s in mgr.statuses() if not s.on] == []
    assert {s.id for s in mgr.statuses()} == set(BUILTINS)
    by_plugin = {e.name: e.plugin for e in mgr.registry.entries(Library.DATA_SOURCES)}
    assert by_plugin["synthetic_stocks"] == "synthetic-data" and by_plugin["polygon"] == "market-downloads"
    assert mgr.registry.entries(Library.GENERATORS)[0].plugin == "realised-volatility"
    assert {e.plugin for e in mgr.registry.entries(Library.MODULES)} == {"starter-modules"}


def test_the_workspace_has_everything_it_had_before():
    ws = Workspace()
    names = {e.name for e in ws.registry.entries(Library.DATA_SOURCES)}
    assert {"synthetic_stocks", "synthetic_futures", "file_import", "polygon", "databento"} <= names
    assert [e.name for e in ws.registry.entries(Library.GENERATORS)] == ["realised_vol"]
    assert len(ws.registry.entries(Library.MODULES)) == 3
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 3, "n_days": 5})
    ws.datasets.generate("realised_vol", info.id, {"window": 2})


@pytest.mark.parametrize("removed", BUILTINS)
def test_removing_any_builtin_plugin_leaves_the_rest_working(tmp_path, removed):
    folder = tmp_path / "builtin"
    shutil.copytree(BUILTIN_DIR, folder, ignore=shutil.ignore_patterns(removed, "__pycache__"))
    mgr = manager(builtin=folder)
    mgr.load()
    assert {s.id for s in mgr.statuses()} == set(BUILTINS) - {removed}
    assert all(s.on for s in mgr.statuses()), [(s.id, s.reason) for s in mgr.statuses()]
    assert all(e.plugin != removed for lib in Library for e in mgr.registry.entries(lib))
    ws = Workspace(registry=mgr.registry)  # the workspace (and file import) still start
    assert "file_import" in {e.name for e in ws.registry.entries(Library.DATA_SOURCES)}


@pytest.mark.parametrize("plugin_id", BUILTINS)
def test_builtin_plugins_pass_their_own_check(plugin_id, tmp_path):
    rep = P.check(BUILTIN_DIR / plugin_id, run_tests=False, plugins=tmp_path)
    assert rep.ok, rep.text()


# ---- requirements and failures ----------------------------------------------------------------
def test_missing_or_off_requirements_keep_a_plugin_off(tmp_path):
    make(tmp_path, "needs-ghost", requires=["ghost"])
    make(tmp_path, "base")
    make(tmp_path, "needs-base", requires=["base"])
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert "not installed" in mgr.status("needs-ghost").reason and not mgr.status("needs-ghost").on
    assert mgr.status("needs-base").on
    mgr.set_enabled("base", False)
    assert mgr.status("base").switched_off
    assert mgr.status("needs-base").reason == "needs plugin 'base', which is off"


def test_requirement_loops_are_reported(tmp_path):
    make(tmp_path, "a", requires=["b"])
    make(tmp_path, "b", requires=["a"])
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert "loop" in mgr.status("a").reason and not mgr.status("b").on


def test_a_plugin_whose_code_fails_is_switched_off_and_its_entries_removed(tmp_path):
    make(tmp_path, "broken", SOURCE.format(name="half") + "\n    raise RuntimeError('boom')\n",
         provides={"data_sources": ["half"]})
    make(tmp_path, "fine", SOURCE.format(name="fine"), provides={"data_sources": ["fine"]})
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert "RuntimeError: boom" in mgr.status("broken").reason
    assert [e.name for e in mgr.registry.entries(Library.DATA_SOURCES)] == ["fine"]
    assert not any(n.startswith("titanium_plugin_broken") for n in sys.modules)


def test_provides_must_match_what_the_code_adds(tmp_path):
    make(tmp_path, "liar", SOURCE.format(name="real"), provides={"data_sources": ["claimed"]})
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert '"provides" says' in mgr.status("liar").reason
    assert mgr.registry.entries(Library.DATA_SOURCES) == []


def test_a_plugin_cannot_take_a_builtin_name(tmp_path):
    make(tmp_path, "copycat", SOURCE.format(name="synthetic_stocks"), provides={"data_sources": ["synthetic_stocks"]})
    mgr = manager(tmp_path)
    mgr.load()
    assert "already exists" in mgr.status("copycat").reason
    assert mgr.registry.entries(Library.DATA_SOURCES)[-1].plugin == "synthetic-data"


def test_bad_manifests_are_listed_with_a_reason(tmp_path):
    (tmp_path / "Bad").mkdir()
    (tmp_path / "Bad" / "plugin.json").write_text('{"id": "Bad"}')
    make(tmp_path, "odd", provides={"widgets": ["x"]})
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert "lowercase" in mgr.status("Bad").reason
    assert "widgets" in mgr.status("odd").reason
    with pytest.raises(PluginProblem, match="folder is called"):
        read_manifest(make(tmp_path / "x", "right", main=None).rename(tmp_path / "x" / "wrong"))


def test_reload_keeps_the_apps_own_entries(tmp_path):
    reg = Registry()
    reg.add(Library.MEASUREMENTS, "profit", object())
    mgr = PluginManager(reg)
    mgr.load()
    mgr.load()
    assert [e.name for e in reg.entries(Library.MEASUREMENTS)] == ["profit"]
    assert len(reg.entries(Library.MODULES)) == 3


# ---- the import rule ------------------------------------------------------------------------------
@pytest.mark.parametrize("line, ok", [
    ("import numpy as np", True),
    ("import pandas", True),
    ("from collections import deque", True),
    ("from titanium.sdk import Library", True),
    ("from titanium import sdk", True),
    ("from . import helpers", True),
    ("import os", False),
    ("import subprocess", False),
    ("from titanium.core.sources import Source", False),
    ("from titanium.app import paths", False),
    ("from .. import other", False),
    ("__import__('os')", False),
    ("exec('import os')", False),
])
def test_plugins_import_only_the_sdk_and_an_allowlist(tmp_path, line, ok):
    folder = make(tmp_path, "imports", f"{line}\n\n\ndef setup(plugin):\n    pass\n")
    (folder / "helpers.py").write_text("X = 1\n")
    assert (check_imports(folder) == []) is ok


def test_a_plugin_breaking_the_import_rule_never_runs(tmp_path):
    marker = tmp_path / "ran"
    make(tmp_path, "sneaky", f"import os\nopen({str(marker)!r}, 'w').close()\n\n\ndef setup(plugin):\n    pass\n")
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert "imports os" in mgr.status("sneaky").reason and not marker.exists()


def test_plugins_can_use_their_own_sibling_files(tmp_path):
    folder = make(tmp_path, "split", "from .sources import add_all\n\n\ndef setup(plugin):\n    add_all(plugin)\n",
                  provides={"data_sources": ["split_source"]})
    (folder / "sources.py").write_text(SOURCE.format(name="split_source").replace("def setup", "def add_all"))
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert mgr.status("split").on, mgr.status("split").reason


# ---- on/off, skins, workspace ----------------------------------------------------------------
def test_on_and_off_is_remembered(tmp_path):
    user = tmp_path / "plugins"
    ws = Workspace(plugins_folder=user)
    ws.plugins.set_enabled("synthetic-data", False)
    assert "synthetic_stocks" not in {e.name for e in ws.registry.entries(Library.DATA_SOURCES)}
    assert "Synthetic data" in ws.plugins.why_missing(Library.DATA_SOURCES, "synthetic_stocks")
    again = Workspace(plugins_folder=user)
    assert again.plugins.status("synthetic-data").switched_off
    assert "synthetic_stocks" not in {e.name for e in again.registry.entries(Library.DATA_SOURCES)}
    again.plugins.set_enabled("synthetic-data", True)
    assert Workspace(plugins_folder=user).plugins.status("synthetic-data").on


def test_why_missing_names_the_plugin():
    mgr = manager()
    mgr.set_enabled("realised-volatility", False)
    assert "Realised volatility" in mgr.why_missing(Library.GENERATORS, "realised_vol")
    assert mgr.why_missing(Library.GENERATORS, "nothing") is None


def test_a_skin_pack_plugin_needs_no_code(tmp_path):
    folder = make(tmp_path, "neon", main=None, provides={"skins": ["neon"]})
    (folder / "skins").mkdir()
    (folder / "skins" / "neon.toml").write_text('id = "neon"\nname = "Neon"\nextends = "graphite"\n')
    mgr = manager(tmp_path, builtin=None)
    mgr.load()
    assert mgr.status("neon").on, mgr.status("neon").reason
    assert mgr.registry.get(Library.SKINS, "neon") == folder / "skins" / "neon.toml"


def test_user_plugins_load_next_to_the_builtins(tmp_path):
    make(tmp_path, "extra-source", SOURCE.format(name="extra"), provides={"data_sources": ["extra"]})
    ws = Workspace(plugins_folder=tmp_path)
    assert ws.datasets.source("extra").title == "extra"
    assert ws.plugins.status("extra-source").source == "user"


# ---- run defaults and the library folder ------------------------------------------------------
def test_run_defaults_read_back_and_apply():
    d = RunDefaults.from_dict({"capital": "250000", "commission_bps": None, "slippage_bps": "x", "timeframe": "1min"})
    assert d == RunDefaults(capital=250_000, timeframe="1min")
    assert d.apply({"capital": 5}) == {**d.to_dict(), "capital": 5}
    with pytest.raises(ValueError):
        RunDefaults(capital=0)
    with pytest.raises(ValueError):
        RunDefaults(timeframe="weekly")
    ws = Workspace()
    heard = []
    ws.run_defaults_changed.connect(heard.append)
    ws.set_run_defaults(d)
    ws.set_run_defaults(d)
    assert heard == [d] and ws.run_settings({"slippage_bps": 9})["slippage_bps"] == 9


def test_the_library_folder_adds_modules_by_folder(tmp_path):
    (tmp_path / "gaps").mkdir()
    (tmp_path / "gaps" / "gap.py").write_text(textwrap.dedent('''
        from titanium.sdk import knob, module


        @module(kind="transform", outputs=["scores"], name="Overnight gap")
        def overnight_gap(view):
            """The overnight gap of each stock."""
            n = knob("n", 3)
            return {}
    '''))
    (tmp_path / "gaps" / "broken.py").write_text("x = 1\n")
    (tmp_path / "exits").mkdir()
    (tmp_path / "exits" / "hold.py").write_text("@module(kind='decide')\ndef hold(scores):\n    return {}\n")
    t = template_from_file(tmp_path / "gaps" / "gap.py")
    assert (t.name, t.kind, t.outputs, t.doc) == ("Overnight gap", "transform", ["scores"], "The overnight gap of each stock.")
    assert t.code.startswith("def overnight_gap(view):") and "@module" not in t.code
    t.module("M1")  # it reads as a module (knobs, ports)
    ws = Workspace(library_folder=tmp_path)
    names = {e.name: e.plugin for e in ws.registry.entries(Library.MODULES)}
    assert names["gaps/Overnight gap"] == LIBRARY_PLUGIN and names["exits/Hold"] == LIBRARY_PLUGIN
    assert any("broken.py" in p for p in ws.library_problems)
    (tmp_path / "exits" / "hold.py").unlink()
    ws.reload_library()
    assert "exits/Hold" not in {e.name for e in ws.registry.entries(Library.MODULES)}
    assert load_library_folder(Registry(), tmp_path / "missing") == (0, [])


# ---- .tiplug packs ---------------------------------------------------------------------------------
def test_pack_check_install_and_remove(tmp_path):
    src = make(tmp_path / "src", "extra-source", SOURCE.format(name="extra"), provides={"data_sources": ["extra"]})
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "junk.pyc").write_bytes(b"x")
    file = P.pack(src, tmp_path / "out")
    assert file.name == "extra-source-1.0.0.tiplug"
    assert all(n.startswith("extra-source/") and "__pycache__" not in n for n in zipfile.ZipFile(file).namelist())
    installed = tmp_path / "plugins"
    rep = P.check(file, run_tests=False, plugins=installed)
    assert rep.ok, rep.text()
    rep = P.install(file, run_tests=False, plugins=installed)
    assert rep.ok and (installed / "extra-source" / "plugin.json").exists()
    again = P.install(file, run_tests=False, plugins=installed)
    assert not again.ok and "already installed" in again.failed[0]
    assert P.install(file, replace=True, run_tests=False, plugins=installed).ok
    assert Workspace(plugins_folder=installed).datasets.source("extra")
    P.remove("extra-source", plugins=installed)
    assert not (installed / "extra-source").exists()
    with pytest.raises(PluginProblem, match="built in"):
        P.remove("synthetic-data", plugins=installed)


def test_check_refuses_bad_packs(tmp_path):
    bad = tmp_path / "evil.tiplug"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("evil/plugin.json", "{}")
        z.writestr("evil/../../escape.py", "x")
    assert "outside its plugin folder" in P.check(bad, run_tests=False, plugins=tmp_path).failed[0]
    two = tmp_path / "two.tiplug"
    with zipfile.ZipFile(two, "w") as z:
        z.writestr("a/plugin.json", "{}")
        z.writestr("b/plugin.json", "{}")
    assert "exactly one" in P.check(two, run_tests=False, plugins=tmp_path).failed[0]
    (tmp_path / "junk.tiplug").write_text("not a zip")
    assert "not a plugin file" in P.check(tmp_path / "junk.tiplug", run_tests=False, plugins=tmp_path).failed[0]
    clash = make(tmp_path / "src", "synthetic-data", main=None)
    assert "built-in" in P.check(clash, run_tests=False, plugins=tmp_path).failed[0]
    sneaky = make(tmp_path / "src", "sneaky", "import os\n\ndef setup(plugin):\n    pass\n")
    assert not P.check(sneaky, run_tests=False, plugins=tmp_path).ok
    with pytest.raises(PluginProblem):
        P.pack(sneaky)
    broken = make(tmp_path / "src", "broken", "def setup(plugin):\n    raise ValueError('no')\n")
    assert "does not load" in P.check(broken, run_tests=False, plugins=tmp_path).failed[0]


@pytest.mark.parametrize("library", list(P.TEMPLATES))
def test_new_plugins_from_every_template_pass_the_check(tmp_path, library):
    folder = P.new(f"my-{library.replace('_', '-')}", library, base=tmp_path / "work")
    rep = P.check(folder, run_tests=False, plugins=tmp_path / "plugins")
    assert rep.ok, rep.text()


def test_a_new_plugins_own_tests_run_in_the_check(tmp_path):
    folder = P.new("my-module", "modules", base=tmp_path / "work")
    rep = P.check(folder, run_tests=True, plugins=tmp_path / "plugins")
    assert rep.ok, rep.text()
    assert any("its own tests" in p for p in rep.passed)


def test_the_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TITANIUM_HOME", str(tmp_path / "home"))
    assert cli(["new", "cli-source", "--adds", "data_sources", "--in", str(tmp_path / "work")]) == 0
    assert cli(["check", str(tmp_path / "work" / "cli-source"), "--no-tests"]) == 0
    assert cli(["pack", str(tmp_path / "work" / "cli-source"), "--out", str(tmp_path / "out")]) == 0
    assert cli(["install", str(tmp_path / "out" / "cli-source-0.1.0.tiplug"), "--no-tests"]) == 0
    capsys.readouterr()
    assert cli(["list"]) == 0
    out = capsys.readouterr().out
    assert "cli-source" in out and "synthetic-data" in out
    assert cli(["remove", "cli-source"]) == 0
    assert cli(["new", "Bad Id"]) == 1
