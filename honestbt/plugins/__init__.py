"""Plugin folders: one folder per plugin, each independent of the others.

A plugin folder looks like this::

    <id>/
      plugin.json   what it is and what it needs (see below)
      plugin.py     its code: @register(...) calls, importing only honestbt.sdk
      suites/       optional: named test suites, one JSON list of evaluators per file
      presets/      optional: settings files (a strategy family is a preset with a sweep)
      tests/        its own tests (pytest), not run when the app loads it
      README.md     what it adds, what it needs, how to check it

``plugin.json``::

    {"id": "bootstrap", "name": "Bootstrap test", "version": "1.0.0", "api": 1,
     "description": "One sentence.", "author": "E",
     "main": "plugin.py",                       # or null for a pack of suites/presets only
     "provides": {"evaluator": ["bootstrap"]},  # every name its code registers, by kind
     "requires": ["exit-signals"]}              # ids of plugin folders it needs

Folders are read from two places: the built-in ones in ``honestbt/plugins/builtin``
and your own in the user plugin folder (``~/Documents/Titanium/plugins``, or
``$HONESTBT_PLUGIN_DIR``). What keeps it safe to remove any folder:

* a plugin whose ``requires`` are missing or off is left off, with the reason;
* a plugin whose code fails to load is switched off and everything it registered
  is taken out again; the rest carry on;
* a plugin may import only ``honestbt.sdk``, numpy, pandas, a short list of the
  standard library and its own sibling files, so plugins never reach into each
  other or into the core's insides;
* the tests remove each built-in folder in turn and check the rest still load.

This is hygiene, not a sandbox: a Python plugin can still do anything Python can,
so only add plugins from people you trust.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import re
import sys
import types
from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from pathlib import Path

from .. import registry
from ..paths import app_dir

BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
ID = re.compile(r"^[a-z][a-z0-9-]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
SUITE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ALLOWED_IMPORTS = frozenset({
    "__future__", "bisect", "collections", "copy", "dataclasses", "datetime", "decimal", "enum",
    "fractions", "functools", "hashlib", "heapq", "itertools", "json", "math", "operator", "pathlib",
    "random", "re", "statistics", "typing", "warnings", "numpy", "pandas",
})
MODULE_PREFIX = "honestbt_plugin_"


class PluginProblem(ValueError):
    pass


@dataclass
class PluginStatus:
    id: str
    folder: str
    source: str  # builtin | user | pip
    state: str = "off"  # on | off
    reason: str = ""
    name: str = ""
    version: str = ""
    description: str = ""
    author: str = ""
    api: int = 1
    requires: list[str] = field(default_factory=list)
    provides: dict[str, list[str]] = field(default_factory=dict)
    suites: list[str] = field(default_factory=list)
    presets: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


_STATUS: dict[str, PluginStatus] = {}
_SUITES: dict[str, tuple[str, list[dict]]] = {}  # name -> (plugin id, evaluator specs)
_PRESETS: list[dict] = []  # {"name", "plugin", "path"}


# ---------------------------------------------------------------- places

def user_dir() -> Path:
    """Where your own plugin folders live (and the on/off settings)."""
    env = os.environ.get("HONESTBT_PLUGIN_DIR")
    return Path(env) if env else app_dir() / "plugins"


def _settings_path() -> Path:
    return user_dir() / "settings.json"


def switched_off() -> set[str]:
    try:
        return set(json.loads(_settings_path().read_text()).get("off", []))
    except (OSError, ValueError, AttributeError):
        return set()


def set_enabled(plugin_id: str, on: bool) -> None:
    """Switch a plugin on or off. Takes effect the next time plugins load (restart the app)."""
    off = switched_off()
    off.discard(plugin_id) if on else off.add(plugin_id)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"off": sorted(off)}, indent=2))


# ---------------------------------------------------------------- checks

def read_manifest(folder: Path) -> dict:
    """Read and check ``plugin.json``; raises PluginProblem with a plain reason."""
    from ..sdk import API_VERSION

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
    api = m.get("api")
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
        raise PluginProblem('"provides" must be an object like {"evaluator": ["bootstrap"]}')
    for kind, names in provides.items():
        if kind not in registry.KINDS:
            raise PluginProblem(f'"provides" has kind {kind!r}; use only: {", ".join(registry.KINDS)}')
        if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
            raise PluginProblem(f'"provides.{kind}" must be a list of names')
    if provides and main is None:
        raise PluginProblem('"provides" lists code, but "main" is null')
    requires = m.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(r, str) and ID.match(r) for r in requires):
        raise PluginProblem('"requires" must be a list of plugin ids')
    if pid in requires:
        raise PluginProblem("a plugin cannot require itself")
    return {**m, "main": main, "provides": provides, "requires": requires}


def _code_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*.py")
                  if "tests" not in p.relative_to(folder).parts and "__pycache__" not in p.parts)


def check_imports(folder: Path) -> list[str]:
    """Problems with what the plugin's code imports (empty = fine)."""
    problems = []
    for path in _code_files(folder):
        rel = path.relative_to(folder).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            problems.append(f"{rel}: syntax error on line {exc.lineno}: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "honestbt.sdk":
                        continue
                    if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                        problems.append(f"{rel}:{node.lineno}: imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level == 1:
                    continue  # its own sibling files
                if node.level > 1:
                    problems.append(f"{rel}:{node.lineno}: reaches outside its folder (from {'.' * node.level}{mod})")
                elif mod == "honestbt.sdk" or (mod == "honestbt" and all(a.name == "sdk" for a in node.names)):
                    continue
                elif mod.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"{rel}:{node.lineno}: imports from {mod}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
                problems.append(f"{rel}:{node.lineno}: calls __import__")
    return [p + " (a plugin may import only honestbt.sdk, numpy, pandas, a short list of the standard "
                "library and its own files)" for p in problems]


def read_suite(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PluginProblem(f"suites/{path.name} is not valid JSON ({exc})") from None
    if isinstance(data, dict):
        data = data.get("evaluators")
    if not isinstance(data, list) or not all(isinstance(e, dict) and isinstance(e.get("plugin"), str) for e in data):
        raise PluginProblem(f'suites/{path.name} must be a list like [{{"plugin": "bootstrap", "params": {{}}}}]')
    return data


# ---------------------------------------------------------------- loading

def _module_name(pid: str) -> str:
    return MODULE_PREFIX + pid.replace("-", "_")


def _forget_modules(pid: str) -> None:
    pkg = _module_name(pid)
    for name in [n for n in sys.modules if n == pkg or n.startswith(pkg + ".")]:
        del sys.modules[name]


def _run_code(folder: Path, pid: str, main: str) -> None:
    _forget_modules(pid)
    pkg = types.ModuleType(_module_name(pid))
    pkg.__path__ = [str(folder)]
    pkg.__package__ = pkg.__name__
    sys.modules[pkg.__name__] = pkg
    importlib.import_module(f"{pkg.__name__}.{main[:-3]}")


def _load_one(st: PluginStatus, folder: Path, m: dict) -> None:
    problems = check_imports(folder)
    if problems:
        raise PluginProblem("; ".join(problems))
    suites = {}
    for path in sorted((folder / "suites").glob("*.json")):
        if not SUITE_NAME.match(path.stem):
            raise PluginProblem(f"suites/{path.name}: name it with lowercase letters, digits, - or _")
        if path.stem in _SUITES:
            raise PluginProblem(f"suite {path.stem!r} is already provided by plugin {_SUITES[path.stem][0]!r}")
        suites[path.stem] = read_suite(path)
    presets = []
    for path in sorted((folder / "presets").glob("*.json")):
        try:
            if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                raise ValueError("not an object")
        except ValueError as exc:
            raise PluginProblem(f"presets/{path.name} is not a settings file ({exc})") from None
        presets.append({"name": path.stem, "plugin": st.id, "path": str(path)})

    if m["main"]:
        previous = registry.set_owner(st.id)
        try:
            _run_code(folder, st.id, m["main"])
        except Exception as exc:
            registry.unregister_owner(st.id)
            _forget_modules(st.id)
            raise PluginProblem(f"its code failed to load: {type(exc).__name__}: {exc}") from None
        finally:
            registry.set_owner(previous)
        got = registry.owned_by(st.id)
        want = {k: sorted(v) for k, v in m["provides"].items() if v}
        if got != want:
            registry.unregister_owner(st.id)
            _forget_modules(st.id)
            raise PluginProblem(f'"provides" says {want} but the code registered {got}')
    _SUITES.update({name: (st.id, specs) for name, specs in suites.items()})
    _PRESETS.extend(presets)
    st.suites, st.presets = sorted(suites), [p["name"] for p in presets]


def _scan(dirs: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    found = []
    for base, source in dirs:
        if base.is_dir():
            for folder in sorted(base.iterdir()):
                if folder.is_dir() and not folder.name.startswith((".", "_")) and (folder / "plugin.json").exists():
                    found.append((folder, source))
    return found


def load_all(dirs: list[tuple[Path, str]] | None = None, off: set[str] | None = None,
             include_pip: bool = True) -> dict[str, PluginStatus]:
    """Load plugin folders in dependency order. Returns the status of each."""
    _STATUS.clear()
    _SUITES.clear()
    _PRESETS.clear()
    if dirs is None:
        dirs = [(BUILTIN_DIR, "builtin"), (user_dir(), "user")]
    off = switched_off() if off is None else off

    pending: dict[str, tuple[PluginStatus, Path, dict]] = {}
    for folder, source in _scan(dirs):
        st = PluginStatus(id=folder.name, folder=str(folder), source=source)
        try:
            m = read_manifest(folder)
        except PluginProblem as exc:
            st.reason = str(exc)
            _STATUS.setdefault(f"{folder.name} ({source})" if folder.name in _STATUS else folder.name, st)
            continue
        st.name, st.version, st.api = m["name"], m["version"], m["api"]
        st.description, st.author = m.get("description", ""), m.get("author", "")
        st.requires, st.provides = m["requires"], m["provides"]
        if st.id in _STATUS:
            st.reason = f"the id {st.id!r} is already used by {_STATUS[st.id].folder}"
            _STATUS[f"{st.id} ({source})"] = st
            continue
        _STATUS[st.id] = st
        if st.id in off:
            st.reason = "switched off in Plugins"
            continue
        pending[st.id] = (st, Path(folder), m)

    progress = True
    while pending and progress:
        progress = False
        for pid in list(pending):
            st, folder, m = pending[pid]
            blocked = [r for r in m["requires"] if r not in _STATUS or (r not in pending and _STATUS[r].state != "on")]
            if blocked:
                r = blocked[0]
                st.reason = (f"needs plugin {r!r}, which is not installed" if r not in _STATUS
                             else f"needs plugin {r!r}, which is off")
                del pending[pid]
                progress = True
                continue
            if any(r in pending for r in m["requires"]):
                continue
            del pending[pid]
            progress = True
            try:
                _load_one(st, folder, m)
                st.state, st.reason = "on", ""
            except PluginProblem as exc:
                st.reason = str(exc)
    for pid, (st, _, m) in pending.items():
        st.reason = f"its requirements form a loop ({', '.join(r for r in m['requires'] if r in pending)})"

    if include_pip:
        for ep in entry_points(group="honestbt.plugins"):
            pid = f"pip:{ep.name}"
            st = PluginStatus(id=pid, folder=ep.value, source="pip", name=ep.name)
            previous = registry.set_owner(pid)
            try:
                ep.load()
                st.state = "on"
                st.provides = registry.owned_by(pid)
            except Exception as exc:
                registry.unregister_owner(pid)
                st.reason = f"failed to load: {type(exc).__name__}: {exc}"
            finally:
                registry.set_owner(previous)
            _STATUS[pid] = st
    return dict(_STATUS)


# ---------------------------------------------------------------- queries

def statuses() -> list[PluginStatus]:
    registry.load_plugins()
    return sorted(_STATUS.values(), key=lambda s: (s.source != "builtin", s.id))


def why_missing(kind: str, name: str) -> str | None:
    """If a plugin that is off would provide this, say which and why."""
    for st in _STATUS.values():
        if st.state == "off" and name in st.provides.get(kind, []):
            return f"it comes from plugin {st.id!r}, which is off: {st.reason}"
    return None


def suite(name: str) -> list[dict]:
    registry.load_plugins()
    if name not in _SUITES:
        owners = [st for st in _STATUS.values() if st.state == "off" and name in st.suites]
        raise KeyError(f"no test suite named {name!r}" + (f" (plugin {owners[0].id!r} is off)" if owners else
                                                          f" (known: {', '.join(sorted(_SUITES)) or 'none'})"))
    return [dict(e) for e in _SUITES[name][1]]


def suites() -> dict[str, list[dict]]:
    registry.load_plugins()
    return {name: [dict(e) for e in specs] for name, (_, specs) in sorted(_SUITES.items())}


def presets() -> list[dict]:
    """Settings files shipped inside plugin folders: [{"name", "plugin", "path"}]."""
    registry.load_plugins()
    return [dict(p) for p in _PRESETS]


def plugin_module(plugin_id: str):
    """The loaded main module of a plugin folder (for that plugin's own tests)."""
    registry.load_plugins()
    st = _STATUS.get(plugin_id)
    if st is None or st.state != "on":
        raise KeyError(f"plugin {plugin_id!r} is not loaded" + (f": {st.reason}" if st else ""))
    main = read_manifest(Path(st.folder))["main"]
    return sys.modules[f"{_module_name(plugin_id)}.{main[:-3]}"]


def reload() -> list[PluginStatus]:
    """Forget every plugin and load the folders again (after an import or an on/off switch)."""
    registry.reset()
    registry.load_plugins()
    return statuses()


class isolated:
    """Load other sets of folders inside a ``with`` block, then put everything back as it was.

        with isolated() as load:
            status = load([(folder, "user")])
    """

    def __enter__(self):
        registry.load_plugins()
        self._saved = ({k: dict(v) for k, v in registry._REGISTRY.items()}, dict(_STATUS), dict(_SUITES),
                       list(_PRESETS), {n: m for n, m in sys.modules.items() if n.startswith(MODULE_PREFIX)})

        def load(dirs, off=(), include_pip=False):
            for items in registry._REGISTRY.values():
                items.clear()
            return load_all(dirs=list(dirs), off=set(off), include_pip=include_pip)

        return load

    def __exit__(self, *exc):
        reg, status, suites_, presets_, mods = self._saved
        for k, v in reg.items():
            registry._REGISTRY[k].clear()
            registry._REGISTRY[k].update(v)
        _STATUS.clear()
        _STATUS.update(status)
        _SUITES.clear()
        _SUITES.update(suites_)
        _PRESETS[:] = presets_
        for n in [n for n in sys.modules if n.startswith(MODULE_PREFIX)]:
            del sys.modules[n]
        sys.modules.update(mods)
        return False
