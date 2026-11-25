"""The plugin manager: ``Workspace.plugins``.

A plugin is a folder with a ``plugin.json`` (:class:`~titanium.core.plugins.Manifest`)::

    <id>/
      plugin.json   what it is, what it adds, what it needs
      plugin.py     its code: defines setup(plugin); imports only titanium.sdk (optional)
      skins/        optional: skin .toml files, added to the skin library
      tests/        its own tests (pytest), not run when the app loads it
      README.md     what it adds and how to check it

Folders are read from the built-in plugins (``titanium/plugins/builtin``) and the
user's plugins folder (``Documents/Titanium/plugins``). What keeps it safe to remove
any of them:

* a plugin whose ``requires`` are missing or off stays off, with the reason;
* a plugin whose code fails to load, or adds something other than what its manifest
  says, is switched off and every entry it added is taken out of the registry;
* a plugin may import only ``titanium.sdk``, numpy, pandas, a short list of the
  standard library and its own sibling files (checked with ``ast`` before it runs);
* the tests remove each built-in plugin in turn and check the rest still load.

This is hygiene, not a sandbox: a Python plugin can still do anything Python can,
so only add plugins from people you trust.

On/off choices are remembered in ``plugins.json`` next to the user's plugins. No Qt here.
"""
from __future__ import annotations

import ast
import importlib
import json
import re
import sys
import types
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..core.plugins import API_VERSION, Library, Manifest, Registry
from ..plugins import BUILTIN_DIR
from .events import Event

ID = re.compile(r"^[a-z][a-z0-9-]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
SDK = "titanium.sdk"
ALLOWED_IMPORTS = frozenset({
    "__future__", "bisect", "collections", "copy", "dataclasses", "datetime", "decimal", "enum",
    "fractions", "functools", "heapq", "itertools", "json", "math", "operator", "random", "re",
    "statistics", "string", "typing", "warnings", "numpy", "pandas",
})
MODULE_PREFIX = "titanium_plugin_"
ON, OFF = "on", "off"
BUILTIN, USER = "builtin", "user"
DEFAULT = object()  # "use the default" for PluginManager(state_file=...)


class PluginProblem(ValueError):
    """Why a plugin can't be used, in plain words."""


@dataclass
class PluginStatus:
    id: str
    folder: str
    source: str  # builtin | user
    state: str = OFF  # on | off
    reason: str = ""  # why it is off ("" when on)
    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    requires: list[str] = field(default_factory=list)
    provides: dict[str, list[str]] = field(default_factory=dict)
    switched_off: bool = False  # the person turned it off (as opposed to a problem)

    @property
    def on(self) -> bool:
        return self.state == ON

    def to_json(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- checks
def read_manifest(folder: str | Path) -> Manifest:
    """Read and check ``plugin.json``. Raises :class:`PluginProblem` with a plain reason."""
    folder = Path(folder)
    path = folder / "plugin.json"
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise PluginProblem("has no plugin.json") from None
    except ValueError as exc:
        raise PluginProblem(f"plugin.json is not valid JSON ({exc})") from None
    if not isinstance(m, dict):
        raise PluginProblem("plugin.json must be an object")
    pid = m.get("id")
    if not isinstance(pid, str) or not ID.match(pid):
        raise PluginProblem('"id" must be lowercase words joined by dashes, like "my-plugin"')
    if pid != folder.name:
        raise PluginProblem(f'"id" is {pid!r} but the folder is called {folder.name!r}; they must match')
    if not isinstance(m.get("name"), str) or not m["name"]:
        raise PluginProblem('plugin.json has no "name"')
    if not VERSION.match(str(m.get("version", ""))):
        raise PluginProblem('"version" must look like 1.0.0')
    api = m.get("api", API_VERSION)
    if not isinstance(api, int) or not 1 <= api <= API_VERSION:
        raise PluginProblem(f'"api" must be a whole number from 1 to {API_VERSION} (this app\'s plugin API)')
    main = m.get("main", "plugin.py")
    if main is not None:
        if not isinstance(main, str) or not re.match(r"^[a-z_][a-z0-9_]*\.py$", main):
            raise PluginProblem('"main" must be a file name like plugin.py, or null')
        if not (folder / main).is_file():
            raise PluginProblem(f'"main" names {main}, which is not in the folder')
    provides = m.get("provides", {})
    if not isinstance(provides, dict):
        raise PluginProblem('"provides" must be an object like {"data_sources": ["my_source"]}')
    libraries = [lib.value for lib in Library]
    for lib, names in provides.items():
        if lib not in libraries:
            raise PluginProblem(f'"provides" has library {lib!r}; use only: {", ".join(libraries)}')
        if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
            raise PluginProblem(f'"provides.{lib}" must be a list of names')
    requires = m.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(r, str) and ID.match(r) for r in requires):
        raise PluginProblem('"requires" must be a list of plugin ids')
    if pid in requires:
        raise PluginProblem("a plugin cannot require itself")
    known = {"id", "name", "version", "api", "description", "author", "main", "provides", "requires"}
    extra = set(m) - known
    if extra:
        raise PluginProblem(f"plugin.json has unknown fields: {', '.join(sorted(extra))}")
    return Manifest(id=pid, name=m["name"], version=m["version"], api=api,
                    description=str(m.get("description", "")), author=str(m.get("author", "")),
                    main=main, provides=provides, requires=requires)


def code_files(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).rglob("*.py")
                  if "tests" not in p.relative_to(folder).parts and "__pycache__" not in p.parts)


def check_imports(folder: str | Path) -> list[str]:
    """Problems with what the plugin's code imports (empty = fine)."""
    folder = Path(folder)
    problems = []
    for path in code_files(folder):
        rel = path.relative_to(folder).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            problems.append(f"{rel}: syntax error on line {exc.lineno}: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name != SDK and alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                        problems.append(f"{rel}:{node.lineno}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level == 1:
                    continue  # its own sibling files
                if node.level > 1:
                    problems.append(f"{rel}:{node.lineno}: reaches outside its folder (from {'.' * node.level}{mod})")
                elif mod == SDK or (mod == "titanium" and all(a.name == "sdk" for a in node.names)):
                    continue
                elif mod.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"{rel}:{node.lineno}: imports from {mod}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
                    "__import__", "exec", "eval"):
                problems.append(f"{rel}:{node.lineno}: calls {node.func.id}")
            elif isinstance(node, ast.Attribute) and node.attr == "import_module":
                problems.append(f"{rel}:{node.lineno}: uses import_module")
    return [p + " (a plugin may import only titanium.sdk, numpy, pandas, a short list of the standard "
                "library and its own files)" for p in problems]


# ---------------------------------------------------------------- what a plugin's setup() receives
class PluginContext:
    """Handed to a plugin's ``setup(plugin)``. Everything it adds is tagged with its id."""

    def __init__(self, registry: Registry, manifest: Manifest, folder: Path) -> None:
        self._registry = registry
        self.id = manifest.id
        self.name = manifest.name
        self.folder = folder  # to read its own files
        self.added: dict[str, list[str]] = {}

    def add(self, library: Library | str, name: str, obj: Any, doc: str = "") -> None:
        lib = Library(library)
        self._registry.add(lib, name, obj, plugin=self.id, doc=doc or getattr(obj, "doc", ""))
        self.added.setdefault(lib.value, []).append(name)

    def add_module(self, folder: str, template: Any) -> None:
        """Add a module to the module library, in ``folder`` (shown as ``folder/name``)."""
        self.add(Library.MODULES, f"{folder}/{template.name}", template, doc=getattr(template, "doc", ""))

    def add_skin(self, skin: Any, name: str = "") -> None:
        """A skin: a path to a .toml file (relative paths are inside the plugin), or its data."""
        if isinstance(skin, str):
            skin = Path(skin)
        if isinstance(skin, Path) and not skin.is_absolute():
            skin = self.folder / skin
        entry = name or (Path(skin).stem if isinstance(skin, Path) else str(skin.get("id", "")))
        self.add(Library.SKINS, entry, skin)


# ---------------------------------------------------------------- loading
def _module_name(pid: str) -> str:
    return MODULE_PREFIX + pid.replace("-", "_")


def _forget_modules(pid: str) -> None:
    pkg = _module_name(pid)
    for name in [n for n in sys.modules if n == pkg or n.startswith(pkg + ".")]:
        del sys.modules[name]


def _run_code(folder: Path, pid: str, main: str):
    _forget_modules(pid)
    pkg = types.ModuleType(_module_name(pid))
    pkg.__path__ = [str(folder)]
    pkg.__package__ = pkg.__name__
    sys.modules[pkg.__name__] = pkg
    return importlib.import_module(f"{pkg.__name__}.{main[:-3]}")


def scan(folders: Iterable[tuple[Path, str]]) -> list[tuple[Path, str]]:
    found = []
    for base, source in folders:
        base = Path(base)
        if base.is_dir():
            for folder in sorted(base.iterdir()):
                if folder.is_dir() and not folder.name.startswith((".", "_")) and (folder / "plugin.json").exists():
                    found.append((folder, source))
    return found


class PluginManager:
    """Loads plugin folders into a registry and remembers which are switched off.

    ``user_folder``: the user's plugins (None: built-in plugins only, as in tests and
    scripts). ``state_file``: where on/off is remembered (default: ``plugins.json`` in
    ``user_folder``; None keeps it for this session only).
    """

    def __init__(self, registry: Registry, user_folder: Path | str | None = None,
                 state_file: Path | str | None | object = DEFAULT, builtin_folder: Path | str | None = BUILTIN_DIR) -> None:
        self.registry = registry
        self.builtin_folder = Path(builtin_folder) if builtin_folder is not None else None
        self.user_folder = Path(user_folder) if user_folder is not None else None
        if state_file is DEFAULT:
            state_file = self.user_folder / "plugins.json" if self.user_folder is not None else None
        self.state_file = Path(state_file) if state_file is not None else None
        self._off: set[str] = self._read_off()
        self._status: dict[str, PluginStatus] = {}
        self.changed = Event()  # () after every load

    # ---- places and memory -------------------------------------------------------
    def folders(self) -> list[tuple[Path, str]]:
        out = []
        if self.builtin_folder is not None:
            out.append((self.builtin_folder, BUILTIN))
        if self.user_folder is not None:
            out.append((self.user_folder, USER))
        return out

    def _read_off(self) -> set[str]:
        if self.state_file is None:
            return set()
        try:
            return set(json.loads(self.state_file.read_text(encoding="utf-8")).get("off", []))
        except (OSError, ValueError, AttributeError, TypeError):
            return set()

    def switched_off(self) -> set[str]:
        return set(self._off)

    def set_enabled(self, plugin_id: str, on: bool, reload: bool = True) -> None:
        """Switch a plugin on or off, remember it, and load plugins again."""
        self._off.discard(plugin_id) if on else self._off.add(plugin_id)
        if self.state_file is not None:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps({"off": sorted(self._off)}, indent=2) + "\n", encoding="utf-8")
        if reload:
            self.load()

    def set_switched_off(self, plugin_ids, reload: bool = True) -> None:
        """Take the on/off of every plugin from elsewhere (the backtest worker follows the app's
        Settings this way) without writing it down."""
        self._off = set(plugin_ids)
        if reload:
            self.load()

    # ---- loading ------------------------------------------------------------------
    def unload(self) -> None:
        """Take every plugin's entries out of the registry (the app's own stay)."""
        for st in self._status.values():
            self.registry.remove_plugin(st.id)
        self._status.clear()

    def load(self) -> list[PluginStatus]:
        """Load every plugin folder in dependency order. Safe to call again (reloads)."""
        self.unload()
        status = self._status
        pending: dict[str, tuple[PluginStatus, Path, Manifest]] = {}
        for folder, source in scan(self.folders()):
            st = PluginStatus(id=folder.name, folder=str(folder), source=source)
            try:
                m = read_manifest(folder)
            except PluginProblem as exc:
                st.reason = str(exc)
                status[folder.name if folder.name not in status else f"{folder.name} ({source})"] = st
                continue
            st.name, st.version, st.description, st.author = m.name, m.version, m.description, m.author
            st.requires, st.provides = list(m.requires), {k: list(v) for k, v in m.provides.items()}
            if st.id in status:
                st.reason = f"the id {st.id!r} is already used by {status[st.id].folder}"
                status[f"{st.id} ({source})"] = st
                continue
            status[st.id] = st
            if st.id in self._off:
                st.reason, st.switched_off = "switched off", True
                continue
            pending[st.id] = (st, folder, m)

        progress = True
        while pending and progress:
            progress = False
            for pid in list(pending):
                st, folder, m = pending[pid]
                blocked = [r for r in m.requires if r not in status or (r not in pending and not status[r].on)]
                if blocked:
                    r = blocked[0]
                    st.reason = (f"needs plugin {r!r}, which is not installed" if r not in status
                                 else f"needs plugin {r!r}, which is off")
                    del pending[pid]
                    progress = True
                    continue
                if any(r in pending for r in m.requires):
                    continue
                del pending[pid]
                progress = True
                try:
                    self._load_one(folder, m)
                    st.state, st.reason = ON, ""
                except PluginProblem as exc:
                    st.reason = str(exc)
        for pid, (st, _, m) in pending.items():
            st.reason = f"its requirements form a loop ({', '.join(r for r in m.requires if r in pending)})"
        self.changed.emit()
        return self.statuses()

    def _load_one(self, folder: Path, m: Manifest) -> None:
        problems = check_imports(folder)
        if problems:
            raise PluginProblem("; ".join(problems))
        ctx = PluginContext(self.registry, m, folder)
        try:
            for path in sorted((folder / "skins").glob("*.toml")):
                ctx.add_skin(path)
            if m.main:
                mod = _run_code(folder, m.id, m.main)
                setup = getattr(mod, "setup", None)
                if not callable(setup):
                    raise PluginProblem(f"{m.main} has no setup(plugin) function")
                setup(ctx)
        except PluginProblem:
            self._discard(m.id)
            raise
        except Exception as exc:
            self._discard(m.id)
            raise PluginProblem(f"its code failed to load: {type(exc).__name__}: {exc}") from None
        got = {k: sorted(v) for k, v in ctx.added.items() if v}
        want = {k: sorted(v) for k, v in m.provides.items() if v}
        if got != want:
            self._discard(m.id)
            raise PluginProblem(f'"provides" says {want} but it added {got}')

    def _discard(self, pid: str) -> None:
        self.registry.remove_plugin(pid)
        _forget_modules(pid)

    # ---- queries ------------------------------------------------------------------
    def statuses(self) -> list[PluginStatus]:
        return sorted(self._status.values(), key=lambda s: (s.source != BUILTIN, s.name.lower() or s.id))

    def status(self, plugin_id: str) -> PluginStatus:
        return self._status[plugin_id]

    def why_missing(self, library: Library | str, name: str) -> str | None:
        """If a plugin that is off would provide this entry, say which and why."""
        lib = Library(library).value
        for st in self._status.values():
            if not st.on and name in st.provides.get(lib, []):
                return f"it comes from the plugin {st.name or st.id}, which is off: {st.reason}"
        return None
