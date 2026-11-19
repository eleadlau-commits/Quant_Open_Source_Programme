"""``.tiplug`` files: one plugin folder packed into one file you can hand to someone.

A ``.tiplug`` is a zip of the folder, with everything under ``<id>/``::

    bootstrap/plugin.json
    bootstrap/plugin.py
    bootstrap/tests/test_bootstrap.py
    bootstrap/README.md

``check`` makes the same checks the app makes on import: the manifest, what the
code imports, that it loads next to the plugins you already have and registers
exactly what it says, that its suites name known tests and its presets are
valid settings, and (where pytest is installed) that its own tests pass.
``install`` checks first, then copies the folder into your plugin folder.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .. import registry
from . import (BUILTIN_DIR, PluginProblem, check_imports, isolated, read_manifest, read_suite, statuses,
               user_dir)

SUFFIX = ".tiplug"
MAX_BYTES = 20 * 1024 * 1024  # unpacked size limit
MAX_FILES = 500
SKIP = ("__pycache__", ".pytest_cache", ".DS_Store")


@dataclass
class Report:
    id: str = ""
    name: str = ""
    version: str = ""
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def text(self) -> str:
        lines = [f"{self.name or self.id} {self.version}".strip()]
        lines += [f"  ✓ {x}" for x in self.passed] + [f"  – {x}" for x in self.skipped] + [f"  ✗ {x}" for x in self.failed]
        lines.append("Every check passed." if self.ok else f"{len(self.failed)} check(s) failed.")
        return "\n".join(lines)


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and not any(s in p.parts for s in SKIP)
                  and p.suffix != ".pyc" and not p.name.startswith("."))


def pack(folder: str | Path, out_dir: str | Path | None = None) -> Path:
    """Pack a plugin folder into ``<id>-<version>.tiplug``. Raises PluginProblem if it is not a plugin."""
    folder = Path(folder).resolve()
    m = read_manifest(folder)
    problems = check_imports(folder)
    if problems:
        raise PluginProblem("; ".join(problems))
    out = Path(out_dir or folder.parent) / f"{m['id']}-{m['version']}{SUFFIX}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _files(folder):
            z.write(f, f"{m['id']}/{f.relative_to(folder).as_posix()}")
    return out


def unpack(file: str | Path, into: str | Path) -> Path:
    """Safely unpack a .tiplug into ``into/<id>`` and return that folder."""
    file = Path(file)
    try:
        z = zipfile.ZipFile(file)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PluginProblem(f"{file.name} is not a plugin file ({exc})") from None
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if not infos:
            raise PluginProblem(f"{file.name} is empty")
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
            raise PluginProblem(f"{file.name} is too big for a plugin")
        tops = set()
        for i in infos:
            p = PurePosixPath(i.filename)
            if p.is_absolute() or ".." in p.parts or "\\" in i.filename or len(p.parts) < 2:
                raise PluginProblem(f"{file.name} has a file outside its plugin folder: {i.filename}")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise PluginProblem(f"{file.name} contains a link ({i.filename}), which plugins may not")
            tops.add(p.parts[0])
        if len(tops) != 1:
            raise PluginProblem(f"{file.name} must hold exactly one plugin folder, found {sorted(tops)}")
        top = tops.pop()
        dest = Path(into) / top
        for i in infos:
            target = dest.joinpath(*PurePosixPath(i.filename).parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return dest


def _run_own_tests(folder: Path) -> tuple[str, str]:
    """('passed' | 'failed' | 'skipped', detail) for the folder's tests/."""
    tests = folder / "tests"
    if not tests.is_dir() or not list(tests.glob("test_*.py")):
        return "skipped", "it has no tests"
    try:
        import pytest
    except ImportError:
        return "skipped", "its tests (pytest is not installed here)"
    buf = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="tiplug-pytest-") as cfgdir, \
            contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        ini = Path(cfgdir) / "pytest.ini"
        ini.write_text("[pytest]\n")
        code = pytest.main([str(tests), "-q", "--import-mode=importlib", "-p", "no:cacheprovider",
                            "--rootdir", str(folder), "-c", str(ini)])
    tail = "\n".join(buf.getvalue().strip().splitlines()[-15:])
    return ("passed", tail.splitlines()[-1] if tail else "") if code == 0 else ("failed", tail)


def check(path: str | Path, run_tests: bool = True) -> Report:
    """Check a plugin folder or .tiplug file without installing it."""
    path = Path(path)
    rep = Report()
    with tempfile.TemporaryDirectory(prefix="tiplug-") as tmp:
        try:
            folder = unpack(path, tmp) if path.is_file() else path.resolve()
            m = read_manifest(folder)
        except PluginProblem as exc:
            rep.failed.append(str(exc))
            return rep
        rep.id, rep.name, rep.version = m["id"], m["name"], m["version"]
        rep.passed.append("plugin.json is complete")
        problems = check_imports(folder)
        if problems:
            rep.failed.extend(problems)
            return rep
        rep.passed.append("imports only the plugin API")
        if (BUILTIN_DIR / m["id"]).exists():
            rep.failed.append(f"the id {m['id']!r} belongs to a built-in plugin; choose another "
                              "(built-in plugins are checked by the test suite)")
            return rep

        # Load it next to everything already installed (minus any older copy of itself).
        stage = Path(tmp) / "_stage"
        shutil.copytree(folder, stage / m["id"], ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
        for s in statuses():
            if s.source in ("user", "starter") and s.id != m["id"] and Path(s.folder).is_dir() and not (stage / s.id).exists():
                shutil.copytree(s.folder, stage / s.id, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
        from ..patchbay import validate

        with isolated() as load:
            status = load([(BUILTIN_DIR, "builtin"), (stage, "user")]).get(m["id"])
            if status is None or status.state != "on":
                rep.failed.append(f"it does not load: {status.reason if status else 'not found'}")
                return rep
            what = ", ".join(f"{len(v)} {k}" for k, v in m["provides"].items()) or "no code"
            rep.passed.append(f"loads with your other plugins and registers what it says ({what})")
            for suite_file in sorted((folder / "suites").glob("*.json")):
                bad = [e["plugin"] for e in read_suite(suite_file) if not registry.has("evaluator", e["plugin"])]
                (rep.failed.append(f"suite {suite_file.stem} names unknown tests: {', '.join(bad)}") if bad
                 else rep.passed.append(f"suite {suite_file.stem} names only known tests"))
            for preset in sorted((folder / "presets").glob("*.json")):
                probs = validate(json.loads(preset.read_text(encoding="utf-8")))
                (rep.failed.append(f"preset {preset.stem}: " + "; ".join(probs)) if probs
                 else rep.passed.append(f"preset {preset.stem} is valid"))
            if run_tests:
                result, detail = _run_own_tests(folder)
                {"passed": rep.passed, "failed": rep.failed, "skipped": rep.skipped}[result].append(
                    f"its own tests: {detail}" if result != "skipped" else detail)
    return rep


def install(file: str | Path, replace: bool = False, run_tests: bool = True) -> Report:
    """Check a .tiplug (or folder) and copy it into the user plugin folder if every check passed."""
    rep = check(file, run_tests=run_tests)
    if not rep.ok:
        return rep
    dest = user_dir() / rep.id
    if dest.exists() and not replace:
        old = read_manifest(dest)["version"] if (dest / "plugin.json").exists() else "?"
        rep.failed.append(f"{rep.id} {old} is already installed; import again with replace to update it")
        return rep
    user_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tiplug-", dir=user_dir()) as tmp:
        src = unpack(file, tmp) if Path(file).is_file() else Path(file)
        staged = Path(tmp) / "_new"
        shutil.copytree(src, staged, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
        if dest.exists():
            shutil.rmtree(dest)
        staged.rename(dest)
    rep.passed.append(f"installed in {dest}")
    return rep


def remove(plugin_id: str) -> Path:
    """Delete one of your own plugin folders (built-in ones can only be switched off)."""
    dest = user_dir() / plugin_id
    if (BUILTIN_DIR / plugin_id).exists() and not dest.exists():
        raise PluginProblem(f"{plugin_id!r} is built in; switch it off instead")
    if not (dest / "plugin.json").exists():
        raise PluginProblem(f"no plugin {plugin_id!r} in {user_dir()}")
    shutil.rmtree(dest)
    return dest


TEMPLATES = {
    "evaluator": '''from honestbt.sdk import Param, Verdict, register


@register("evaluator", "{name}", params=[Param("threshold", "float", 0.0, "Pass if mean period return is above this")],
          doc="One sentence on what this test checks.")
def {name}(ectx, threshold=0.0):
    r = ectx.sel_result.periods.to_numpy()
    if len(r) < 8:
        return Verdict("{title}", None, "Not enough periods", "Need at least 8 periods.")
    mean = float(r.mean())
    return Verdict("{title}", mean > threshold, f"Mean return per period {{mean:+.3%}}",
                   "Explain in plain words what passing or failing means.")
''',
    "feature": '''from honestbt.sdk import NAN, Param, register


@register("feature", "{name}", params=[Param("window", "int", 10, "Days")],
          doc="One sentence on what this value is.")
def {name}(view, symbol, window=10):
    d = view.daily(symbol)  # completed days only: the guard hides the future
    if len(d) < window:
        return NAN
    return float(d.close[-window:].mean())
''',
    "strategy": '''from honestbt.sdk import Entry, Param, Strategy, register


@register("strategy", "{name}", params=[Param("symbol", "str", "MNQ", "What to trade")],
          doc="One sentence on the rules.")
class {cls}(Strategy):
    periods_per_year = 252.0

    def decision_times(self, data):
        return [d.astype("datetime64[m]") + 9 * 60 + 35 for d in data.trading_days]

    def decide(self, view, resolver):
        return []  # return [Entry(...)] to trade
''',
    "signal": '''import numpy as np

from honestbt.sdk import Param, register


@register("signal", "{name}", params=[Param("minutes", "float", 30, "Hold at most this long")],
          doc="One sentence on when it exits. out[i] may use only bars up to i.")
def {name}(path, ctx, minutes=30):
    return path.minutes_held >= minutes - 1
''',
    "mapping": '''from honestbt.sdk import Param, register


@register("mapping", "{name}", params=[Param("scale", "float", 1.0)], doc="One sentence.")
def {name}(x, scale=1.0):
    return scale * x
''',
}


def new(plugin_id: str, kind: str, base: str | Path | None = None, author: str = "") -> Path:
    """Start a plugin folder from a template, ready to edit, test and pack."""
    from . import ID

    if not ID.match(plugin_id):
        raise PluginProblem('the id must be lowercase words joined by dashes, like "my-test"')
    if kind not in TEMPLATES and kind not in ("suite", "preset"):
        raise PluginProblem(f"kind must be one of: {', '.join([*TEMPLATES, 'suite', 'preset'])}")
    folder = Path(base or user_dir()) / plugin_id
    if folder.exists():
        raise PluginProblem(f"{folder} already exists")
    name = plugin_id.replace("-", "_")
    title = plugin_id.replace("-", " ").capitalize()
    (folder / "tests").mkdir(parents=True)
    manifest = {"id": plugin_id, "name": title, "description": "One sentence a person reads in Plugins.",
                "version": "0.1.0", "api": 1, "author": author, "main": "plugin.py",
                "provides": {kind: [name]}, "requires": []}
    if kind in TEMPLATES:
        (folder / "plugin.py").write_text(TEMPLATES[kind].format(name=name, title=title,
                                                                 cls="".join(w.title() for w in name.split("_"))))
        (folder / "tests" / f"test_{name}.py").write_text(
            f'from honestbt.plugins.testing import plugin\n\n\ndef test_{name}_is_registered():\n'
            f'    assert plugin("{kind}", "{name}") is not None\n')
    else:
        manifest.update(main=None, provides={})
        sub = folder / (kind + "s")
        sub.mkdir()
        if kind == "suite":
            manifest["requires"] = ["out-of-sample", "deflated-sharpe"]
            (sub / f"{plugin_id}.json").write_text(json.dumps(
                [{"plugin": "out_of_sample", "params": {"split": 0.6}}, {"plugin": "deflated_sharpe"}], indent=2))
        else:
            (sub / f"{plugin_id}.json").write_text((BUILTIN_DIR.parent / "starter" / "gap-families" / "presets" /
                                                    "monday-ranking-family.json").read_text())
        (folder / "tests" / f"test_{name}.py").write_text(
            "def test_placeholder():\n    assert True  # replace with a real check\n")
    (folder / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (folder / "README.md").write_text(f"# {title}\n\nOne sentence on what it does.\n\n## What it adds\n\n"
                                      f"- {kind}: `{name}`\n\n## What it needs\n\nNothing beyond the core.\n\n"
                                      f"## Check it\n\n```\npython -m honestbt.plugins check {folder}\n```\n")
    return folder
