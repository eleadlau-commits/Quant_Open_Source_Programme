"""``.tiplug`` files: one plugin folder packed into one file you can hand to someone.

A ``.tiplug`` is a zip of the folder, with everything under ``<id>/``::

    my-source/plugin.json
    my-source/plugin.py
    my-source/tests/test_my_source.py
    my-source/README.md

``check`` makes the same checks the app makes on import: the manifest, what the code
imports, that it loads next to the plugins you already have and adds exactly what it
says, and (where pytest is installed) that its own tests pass. ``install`` checks
first, then copies the folder into your plugins folder.
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

from ..app import paths
from ..app.plugins import (BUILTIN, ID, USER, PluginManager, PluginProblem, check_imports, read_manifest)
from ..core.plugins import Library, Registry
from . import BUILTIN_DIR

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
        lines += [f"  ✓ {x}" for x in self.passed] + [f"  – {x}" for x in self.skipped]
        lines += [f"  ✗ {x}" for x in self.failed]
        lines.append("Every check passed." if self.ok else f"{len(self.failed)} check(s) failed.")
        return "\n".join(lines)


def user_folder() -> Path:
    return paths.plugins_folder()


def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and not any(s in p.parts for s in SKIP)
                  and p.suffix != ".pyc" and not p.name.startswith("."))


def _ignore():
    return shutil.ignore_patterns(*SKIP, "*.pyc")


def pack(folder: str | Path, out_dir: str | Path | None = None) -> Path:
    """Pack a plugin folder into ``<id>-<version>.tiplug``. Raises PluginProblem if it is not a plugin."""
    folder = Path(folder).resolve()
    m = read_manifest(folder)
    problems = check_imports(folder)
    if problems:
        raise PluginProblem("; ".join(problems))
    out_dir = Path(out_dir or folder.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{m.id}-{m.version}{SUFFIX}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _files(folder):
            z.write(f, f"{m.id}/{f.relative_to(folder).as_posix()}")
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
            if p.is_absolute() or ".." in p.parts or "\\" in i.filename or ":" in i.filename or len(p.parts) < 2:
                raise PluginProblem(f"{file.name} has a file outside its plugin folder: {i.filename}")
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                raise PluginProblem(f"{file.name} contains a link ({i.filename}), which plugins may not")
            tops.add(p.parts[0])
        if len(tops) != 1:
            raise PluginProblem(f"{file.name} must hold exactly one plugin folder, found {sorted(tops)}")
        top = tops.pop()
        if not ID.match(top):
            raise PluginProblem(f"{file.name}: the folder inside is called {top!r}, which is not a plugin id")
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


def check(path: str | Path, run_tests: bool = True, plugins: str | Path | None = None) -> Report:
    """Check a plugin folder or .tiplug file without installing it.

    ``plugins``: the user plugins folder it must load next to (default: yours)."""
    path = Path(path)
    rep = Report()
    installed = Path(plugins) if plugins is not None else user_folder()
    with tempfile.TemporaryDirectory(prefix="tiplug-") as tmp:
        try:
            folder = unpack(path, tmp) if path.is_file() else path.resolve()
            m = read_manifest(folder)
        except PluginProblem as exc:
            rep.failed.append(str(exc))
            return rep
        rep.id, rep.name, rep.version = m.id, m.name, m.version
        rep.passed.append("plugin.json is complete")
        problems = check_imports(folder)
        if problems:
            rep.failed.extend(problems)
            return rep
        rep.passed.append("imports only the plugin API")
        builtin = folder.parent.resolve() == BUILTIN_DIR.resolve()
        if (BUILTIN_DIR / m.id).exists() and not builtin:
            rep.failed.append(f"the id {m.id!r} belongs to a built-in plugin; choose another")
            return rep

        # Load it next to everything already installed (minus any older copy of itself).
        stage = Path(tmp) / "_stage"
        stage.mkdir()
        if not builtin:
            shutil.copytree(folder, stage / m.id, ignore=_ignore())
        if installed.is_dir():
            for other in installed.iterdir():
                if (other / "plugin.json").exists() and other.name != m.id and not (stage / other.name).exists():
                    shutil.copytree(other, stage / other.name, ignore=_ignore())
        mgr = PluginManager(Registry(), user_folder=stage, state_file=None)
        mgr.load()
        try:
            st = mgr.status(m.id)
        except KeyError:
            st = None
        if st is None or not st.on:
            rep.failed.append(f"it does not load: {st.reason if st else 'not found'}")
            return rep
        what = ", ".join(f"{len(v)} {Library(k).value.replace('_', ' ')}" for k, v in m.provides.items()) or "nothing"
        rep.passed.append(f"loads with your other plugins and adds what it says ({what})")
        if run_tests:
            result, detail = _run_own_tests(folder)
            {"passed": rep.passed, "failed": rep.failed, "skipped": rep.skipped}[result].append(
                f"its own tests: {detail}" if result != "skipped" else detail)
    return rep


def install(file: str | Path, replace: bool = False, run_tests: bool = True,
            plugins: str | Path | None = None) -> Report:
    """Check a .tiplug (or folder) and copy it into the plugins folder if every check passed."""
    target = Path(plugins) if plugins is not None else user_folder()
    rep = check(file, run_tests=run_tests, plugins=target)
    if not rep.ok:
        return rep
    dest = target / rep.id
    if dest.exists() and not replace:
        try:
            old = read_manifest(dest).version
        except PluginProblem:
            old = "?"
        rep.failed.append(f"{rep.id} {old} is already installed; import it again with replace to update it")
        return rep
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tiplug-", dir=target) as tmp:
        src = unpack(file, tmp) if Path(file).is_file() else Path(file)
        staged = Path(tmp) / "_new"
        shutil.copytree(src, staged, ignore=_ignore())
        if dest.exists():
            shutil.rmtree(dest)
        staged.rename(dest)
    rep.passed.append(f"installed in {dest}")
    return rep


def remove(plugin_id: str, plugins: str | Path | None = None) -> Path:
    """Delete one of your own plugin folders (built-in ones can only be switched off)."""
    target = Path(plugins) if plugins is not None else user_folder()
    dest = target / plugin_id
    if (BUILTIN_DIR / plugin_id).exists() and not dest.exists():
        raise PluginProblem(f"{plugin_id!r} is built in; switch it off instead")
    if not ID.match(plugin_id) or not (dest / "plugin.json").exists():
        raise PluginProblem(f"no plugin {plugin_id!r} in {target}")
    shutil.rmtree(dest)
    return dest


TEMPLATES = {
    "data_sources": '''from titanium.sdk import DataKind, Library, MarketData, Param, Source


class {cls}(Source):
    name = "{name}"
    title = "{title}"
    kind = DataKind.CORE
    doc = "One sentence on where the data comes from."
    params = [Param("days", "int", 20, "Days", "How many days to make.", minimum=1)]

    def load(self, spec):
        params = self.resolve(spec)
        raise NotImplementedError(f"load {{params['days']}} days here and return MarketData")


def setup(plugin):
    plugin.add(Library.DATA_SOURCES, {cls}.name, {cls}(), doc={cls}.doc)
''',
    "generators": '''from titanium.sdk import Library, Param


class {cls}:
    name = "{name}"
    title = "{title}"
    doc = "One sentence on what this series is."
    params = [Param("window", "int", 20, "Window (days)", minimum=1)]

    def generate(self, data, params):
        """Return {{field: frame}}; stamp each value with the time it became known."""
        return {{}}


def setup(plugin):
    plugin.add(Library.GENERATORS, {cls}.name, {cls}(), doc={cls}.doc)
''',
    "modules": '''from titanium.sdk import ModuleTemplate

CODE = """def {name}(view):
    \\"\\"\\"One sentence on what this module computes.\\"\\"\\"
    days = knob("days", 20, lo=5, hi=120)
    return {{s: 0.0 for s in view.universe()}}
"""


def setup(plugin):
    plugin.add_module("{folder}", ModuleTemplate("{title}", "transform", CODE, outputs=["scores"],
                                                 doc="One sentence a person reads in the library."))
''',
    "skins": None,
}

SKIN = '''id = "{plugin_id}"
name = "{title}"
description = "One sentence on the look."
extends = "graphite"

[dark]
brand = "#E5484D"
'''


def new(plugin_id: str, library: str = "modules", base: str | Path | None = None, author: str = "") -> Path:
    """Start a plugin folder from a template, ready to edit, test and pack."""
    if not ID.match(plugin_id):
        raise PluginProblem('the id must be lowercase words joined by dashes, like "my-source"')
    if library not in TEMPLATES:
        raise PluginProblem(f"what it adds must be one of: {', '.join(TEMPLATES)}")
    folder = Path(base or user_folder()) / plugin_id
    if folder.exists():
        raise PluginProblem(f"{folder} already exists")
    name = plugin_id.replace("-", "_")
    title = plugin_id.replace("-", " ").capitalize()
    cls = "".join(w.title() for w in name.split("_"))
    (folder / "tests").mkdir(parents=True)
    entry = f"{name}/{title}" if library == "modules" else (plugin_id if library == "skins" else name)
    manifest = {"id": plugin_id, "name": title, "version": "0.1.0", "api": 1,
                "description": "One sentence a person reads in Plugins.", "author": author,
                "main": "plugin.py", "provides": {library: [entry]}, "requires": []}
    if library == "skins":
        manifest["main"] = None
        (folder / "skins").mkdir()
        (folder / "skins" / f"{plugin_id}.toml").write_text(SKIN.format(plugin_id=plugin_id, title=title))
    else:
        (folder / "plugin.py").write_text(TEMPLATES[library].format(name=name, title=title, cls=cls, folder=name))
    (folder / "tests" / f"test_{name}.py").write_text(
        f'from titanium.plugins.testing import loaded\n\n\ndef test_{name}_loads():\n'
        f'    reg = loaded("{plugin_id}")\n    assert reg.get("{library}", "{entry}") is not None\n')
    (folder / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (folder / "README.md").write_text(f"# {title}\n\nOne sentence on what it does.\n\n## What it adds\n\n"
                                      f"- {library}: `{entry}`\n\n## What it needs\n\nNothing beyond the core.\n\n"
                                      f"## Check it\n\n```\npython -m titanium.plugins check {folder}\n```\n")
    return folder


def statuses(plugins: str | Path | None = None):
    """Every plugin the app would load, with its state and reason."""
    mgr = PluginManager(Registry(), user_folder=Path(plugins) if plugins is not None else user_folder())
    return mgr.load()


__all__ = ["BUILTIN", "USER", "Report", "check", "install", "new", "pack", "remove", "statuses", "unpack"]
