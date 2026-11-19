"""The plugin folders: each one independent, each one removable."""
import json
import textwrap
from pathlib import Path

import pytest

from honestbt import plugins, registry
from honestbt.patchbay import validate

BUILTIN = plugins.BUILTIN_DIR
STARTER = BUILTIN.parent / "starter"
FOLDERS = {p.name: p for d in (BUILTIN, STARTER) for p in d.iterdir() if (p / "plugin.json").exists()}
IDS = sorted(FOLDERS)
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated():
    """Load other sets of folders, then put the real registry back exactly as it was."""
    with plugins.isolated() as load:
        yield lambda *dirs, off=(): load(dirs, off=off)


def write_plugin(base: Path, pid: str, code: str | None = None, **manifest) -> Path:
    folder = base / pid
    folder.mkdir(parents=True)
    m = {"id": pid, "name": pid.title(), "version": "1.0.0", "api": 1, "main": "plugin.py" if code else None,
         "provides": {}, "requires": [], **manifest}
    (folder / "plugin.json").write_text(json.dumps(m))
    if code:
        (folder / "plugin.py").write_text(textwrap.dedent(code))
    return folder


def dependents(pid: str) -> set[str]:
    req = {i: set(json.loads((FOLDERS[i] / "plugin.json").read_text())["requires"]) for i in IDS}
    out, grew = {pid}, True
    while grew:
        new = {i for i, r in req.items() if r & out} - out
        out |= new
        grew = bool(new)
    return out


def test_every_builtin_is_on_documented_and_tested():
    status = {s.id: s for s in plugins.statuses()}
    for pid in IDS:
        assert status[pid].state == "on", (pid, status[pid].reason)
        folder = FOLDERS[pid]
        assert plugins.check_imports(folder) == []
        readme = (folder / "README.md").read_text()
        assert "## What it adds" in readme and "## What it needs" in readme and "## Check it" in readme, pid
        assert list((folder / "tests").glob("test_*.py")), f"{pid} has no tests"


def test_every_registered_plugin_belongs_to_a_folder():
    for kind, items in registry.catalog().items():
        for info in items:
            if not info["name"].startswith("_"):  # test-only plugins registered by the test files
                assert info["plugin"] in IDS, (kind, info["name"], info["plugin"])


@pytest.mark.parametrize("removed", IDS)
def test_removing_any_folder_leaves_the_rest_working(isolated, tmp_path, removed):
    for pid in IDS:
        if pid != removed:
            (tmp_path / pid).symlink_to(FOLDERS[pid], target_is_directory=True)
    status = isolated((tmp_path, "builtin"))
    off = dependents(removed) - {removed}
    for pid in IDS:
        if pid == removed:
            assert pid not in status
        elif pid in off:
            assert status[pid].state == "off" and "needs plugin" in status[pid].reason, (pid, status[pid].reason)
        else:
            assert status[pid].state == "on", (pid, status[pid].reason)
    # A preset that needed it explains what is missing instead of crashing.
    cfg = json.loads((ROOT / "honestbt" / "plugins" / "starter" / "strategies" / "monday_gap_top5.json").read_text())
    for problem in validate(cfg):
        assert "unknown" in problem


def test_config_says_which_plugin_is_off_and_why(isolated, tmp_path):
    for pid in IDS:
        if pid != "exit-signals":
            (tmp_path / pid).symlink_to(FOLDERS[pid], target_is_directory=True)
    isolated((tmp_path, "builtin"))
    cfg = json.loads((ROOT / "honestbt" / "plugins" / "starter" / "strategies" / "monday_gap_top5.json").read_text())
    problems = " ".join(validate(cfg))
    assert "'weekly-topn', which is off: needs plugin 'exit-signals', which is not installed" in problems


def test_switched_off_plugin_stays_off(isolated):
    status = isolated((BUILTIN, "builtin"), off={"bootstrap"})
    assert status["bootstrap"].state == "off" and "switched off" in status["bootstrap"].reason
    assert not registry.has("evaluator", "bootstrap") and registry.has("evaluator", "out_of_sample")
    assert status["honest-tests"].state == "off"  # its suites use bootstrap


def test_failing_plugin_is_switched_off_and_cleaned_up(isolated, tmp_path):
    write_plugin(tmp_path, "half-done", """
        from honestbt.sdk import register

        @register("feature", "half_feature")
        def half_feature(view, symbol):
            return 1.0

        raise RuntimeError("oops")
    """, provides={"feature": ["half_feature"]})
    write_plugin(tmp_path, "fine", """
        from honestbt.sdk import register

        @register("feature", "fine_feature")
        def fine_feature(view, symbol):
            return 2.0
    """, provides={"feature": ["fine_feature"]})
    status = isolated((tmp_path, "user"))
    assert status["half-done"].state == "off" and "RuntimeError: oops" in status["half-done"].reason
    assert not registry.has("feature", "half_feature")
    assert status["fine"].state == "on" and registry.has("feature", "fine_feature")


def test_plugin_may_not_reach_into_the_core_or_other_plugins(isolated, tmp_path):
    write_plugin(tmp_path, "nosy", "from honestbt.engine import run\n")
    write_plugin(tmp_path, "nosy-too", "import subprocess\n")
    status = isolated((tmp_path, "user"))
    assert "imports from honestbt.engine" in status["nosy"].reason
    assert "imports subprocess" in status["nosy-too"].reason


def test_provides_must_match_what_the_code_registers(isolated, tmp_path):
    write_plugin(tmp_path, "liar", """
        from honestbt.sdk import register

        @register("mapping", "secret")
        def secret(x):
            return x
    """, provides={"mapping": ["public"]})
    status = isolated((tmp_path, "user"))
    assert status["liar"].state == "off" and "provides" in status["liar"].reason
    assert not registry.has("mapping", "secret")


def test_user_plugin_cannot_take_a_builtin_id(isolated, tmp_path):
    write_plugin(tmp_path, "bootstrap", "x = 1\n")
    status = isolated((BUILTIN, "builtin"), (tmp_path, "user"))
    assert status["bootstrap"].source == "builtin" and status["bootstrap"].state == "on"
    assert "already used" in status["bootstrap (user)"].reason


def test_user_plugin_with_sibling_file_suite_and_requirement(isolated, tmp_path):
    folder = write_plugin(tmp_path, "my-tests", """
        from honestbt.sdk import Param, Verdict, register

        from .rules import share_positive


        @register("evaluator", "mostly_up", params=[Param("min_share", "float", 0.6)])
        def mostly_up(ectx, min_share=0.6):
            share = share_positive(ectx.sel_result.periods.to_numpy())
            return Verdict("Mostly up", share >= min_share, f"{share:.0%} of periods up", "")
    """, provides={"evaluator": ["mostly_up"]}, requires=["bootstrap"])
    (folder / "rules.py").write_text("def share_positive(r):\n    return float((r > 0).mean())\n")
    (folder / "suites").mkdir()
    (folder / "suites" / "mine.json").write_text(json.dumps([{"plugin": "mostly_up"}, {"plugin": "bootstrap"}]))
    status = isolated((BUILTIN, "builtin"), (tmp_path, "user"))
    assert status["my-tests"].state == "on", status["my-tests"].reason
    assert [e["plugin"] for e in plugins.suite("mine")] == ["mostly_up", "bootstrap"]
    from honestbt.plugins.testing import fake_context
    assert registry.get("evaluator", "mostly_up")(fake_context([[0.01, 0.02, -0.01]])).passed is True


def test_missing_requirement_and_bad_manifest(isolated, tmp_path):
    write_plugin(tmp_path, "lonely", None, requires=["not-here"])
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "plugin.json").write_text("{nope")
    status = isolated((tmp_path, "user"))
    assert status["lonely"].reason == "needs plugin 'not-here', which is not installed"
    assert "not valid JSON" in status["broken"].reason


# ---- .tiplug files

@pytest.fixture
def user_folder(tmp_path, monkeypatch):
    up = tmp_path / "user-plugins"
    monkeypatch.setenv("HONESTBT_PLUGIN_DIR", str(up))
    return up


def test_new_pack_check_install_remove(user_folder, tmp_path):
    from honestbt.plugins import pack as tiplug

    for kind in ("evaluator", "feature", "strategy", "signal", "mapping", "suite", "preset"):
        folder = tiplug.new(f"my-{kind}", kind, base=tmp_path / "src")
        assert tiplug.check(folder).ok, (kind, tiplug.check(folder).text())
    file = tiplug.pack(tmp_path / "src" / "my-evaluator", tmp_path)
    assert file.name == "my-evaluator-0.1.0.tiplug"
    rep = tiplug.install(file)
    assert rep.ok, rep.text()
    assert (user_folder / "my-evaluator" / "plugin.py").exists()
    assert not tiplug.install(file).ok  # already there
    assert tiplug.install(file, replace=True).ok
    tiplug.remove("my-evaluator")
    assert not (user_folder / "my-evaluator").exists()


def test_install_refuses_failing_tests_bad_imports_and_builtin_ids(user_folder, tmp_path):
    from honestbt.plugins import pack as tiplug

    folder = tiplug.new("flaky", "evaluator", base=tmp_path)
    (folder / "tests" / "test_flaky.py").write_text("def test_no():\n    assert 1 == 2\n")
    rep = tiplug.install(folder)
    assert not rep.ok and any("its own tests" in f for f in rep.failed)
    assert not (user_folder / "flaky").exists()

    sneaky = tiplug.new("sneaky", "feature", base=tmp_path)
    (sneaky / "plugin.py").write_text("import os\n" + (sneaky / "plugin.py").read_text())
    assert any("imports os" in f for f in tiplug.check(sneaky).failed)

    clash = write_plugin(tmp_path / "x", "bootstrap", None)
    assert any("built-in" in f for f in tiplug.check(clash).failed)
    with pytest.raises(plugins.PluginProblem):
        tiplug.remove("bootstrap")


def test_unpack_refuses_files_outside_the_folder(tmp_path):
    import zipfile

    from honestbt.plugins import pack as tiplug

    for name, entries in {"escape": ["evil/plugin.json", "../outside.txt"],
                          "two": ["a/plugin.json", "b/plugin.json"]}.items():
        bad = tmp_path / f"{name}.tiplug"
        with zipfile.ZipFile(bad, "w") as z:
            for e in entries:
                z.writestr(e, "{}")
        with pytest.raises(plugins.PluginProblem):
            tiplug.unpack(bad, tmp_path / f"out-{name}")
    assert not (tmp_path / "outside.txt").exists()
    (tmp_path / "junk.tiplug").write_text("not a zip")
    assert not tiplug.check(tmp_path / "junk.tiplug").ok


def test_switching_off_is_remembered(user_folder):
    plugins.set_enabled("bootstrap", False)
    assert "bootstrap" in plugins.switched_off()
    plugins.set_enabled("bootstrap", True)
    assert "bootstrap" not in plugins.switched_off()
