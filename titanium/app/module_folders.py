"""Your own modules in the module library, kept in folders: ``Workspace.modules``.

Each folder is a directory under ``paths.app_folder() / "modules"``, and each
module a small JSON file in it (name, kind, outputs, doc, code). They are put in
the registry's module library as ``"folder/name"`` entries (plugin ``"user"``),
next to the starter folder and any plugin folders, so every page that lists
modules sees them. Starters and plugin modules can't be changed here, only copied
into one of your folders.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from ..core.module_library import STARTER, ModuleTemplate, add_module
from ..core.plugins import Library, Registry
from ..core.strategy import Module
from .events import Event

USER = "user"  # the registry's plugin id for your modules
FORMAT = "titanium.module"


class ModuleFolderError(ValueError):
    """A folder or module operation that can't be done (the message says why)."""


def _clean(name: str, what: str) -> str:
    name = " ".join(str(name).split())
    if not name:
        raise ModuleFolderError(f"the {what} needs a name")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise ModuleFolderError(f"a {what} name can't contain / or \\")
    return name


def _file_stem(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "", name).strip() or "module"


def template_from_module(m: Module, name: str | None = None) -> ModuleTemplate:
    """A strategy's module as a library entry (its code, kind and outputs)."""
    import ast

    doc = ""
    try:
        fn = next(n for n in ast.parse(m.code).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        doc = ((ast.get_docstring(fn) or "").strip().splitlines() or [""])[0]
    except (SyntaxError, StopIteration):
        pass
    return ModuleTemplate(name or m.name, m.kind, m.code, [p.name for p in m.outputs], doc)


class ModuleFolders:
    """``root``: where the folders live. Without one (tests, scripts) a temporary folder."""

    def __init__(self, registry: Registry, root: Path | str | None = None) -> None:
        self.registry = registry
        self._root = Path(root) if root is not None else None
        self.changed = Event()  # () after any folder or module changes
        self.reload()

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = Path(tempfile.mkdtemp(prefix="titanium-modules-"))
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    # ---- reading
    def folders(self) -> list[str]:
        """Your folders, by name."""
        if self._root is None or not self._root.exists():
            return []
        return sorted((p.name for p in self._root.iterdir() if p.is_dir()), key=str.lower)

    def modules(self, folder: str) -> list[str]:
        return sorted(self._read(folder), key=str.lower)

    def is_mine(self, entry_name: str) -> bool:
        """True for a library entry in one of your folders (one you can rename, move or delete)."""
        return any(e.name == entry_name and e.plugin == USER for e in self.registry.entries(Library.MODULES))

    def _read(self, folder: str) -> dict[str, tuple[Path, ModuleTemplate]]:
        out: dict[str, tuple[Path, ModuleTemplate]] = {}
        d = (self._root / folder) if self._root is not None else None
        if d is None or not d.is_dir():
            return out
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("format") != FORMAT:
                    continue
                t = ModuleTemplate(data["name"], data.get("kind", "transform"), data["code"],
                                   list(data.get("outputs", [])), data.get("doc", ""))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # a broken file never breaks the library
            out.setdefault(t.name, (f, t))
        return out

    def reload(self) -> None:
        """Put your modules (as saved on disk) in the registry."""
        self.registry.remove_plugin(USER)
        for folder in self.folders():
            for _name, (_f, t) in self._read(folder).items():
                try:
                    add_module(self.registry, folder, t, USER)
                except ValueError:  # same name as a plugin's entry: the plugin's stays
                    pass
        self.changed.emit()

    # ---- folders
    def _check_new_folder(self, name: str) -> str:
        name = _clean(name, "folder")
        if name.lower() == STARTER:
            raise ModuleFolderError("“starter” is the app’s own folder; pick another name")
        if name.lower() in (f.lower() for f in self.folders()):
            raise ModuleFolderError(f"there is already a folder called “{name}”")
        return name

    def create_folder(self, name: str) -> str:
        name = self._check_new_folder(name)
        (self.root / name).mkdir()
        self.reload()
        return name

    def rename_folder(self, old: str, new: str) -> str:
        if old not in self.folders():
            raise ModuleFolderError(f"no folder called “{old}”")
        if _clean(new, "folder").lower() != old.lower():
            new = self._check_new_folder(new)
        else:
            new = _clean(new, "folder")
        (self.root / old).rename(self.root / new)
        self.reload()
        return new

    def delete_folder(self, name: str) -> None:
        if name not in self.folders():
            raise ModuleFolderError(f"no folder called “{name}”")
        if self.modules(name):
            raise ModuleFolderError(f"“{name}” still has modules in it. Move or delete them first")
        for f in (self.root / name).iterdir():
            f.unlink()
        (self.root / name).rmdir()
        self.reload()

    # ---- modules
    def save(self, folder: str, template: ModuleTemplate, replace: bool = False) -> str:
        """Save a module into one of your folders (made if missing). Returns its library entry name."""
        folder = _clean(folder, "folder")
        name = _clean(template.name, "module")
        if folder not in self.folders():
            self.create_folder(folder)
        have = self._read(folder)
        if name in have and not replace:
            raise ModuleFolderError(f"“{folder}” already has a module called “{name}”")
        if name in have:
            have[name][0].unlink()
        stem, n = _file_stem(name), 1
        path = self.root / folder / f"{stem}.json"
        while path.exists():
            n += 1
            path = self.root / folder / f"{stem} {n}.json"
        path.write_text(json.dumps({"format": FORMAT, "name": name, "kind": template.kind,
                                    "outputs": list(template.outputs), "doc": template.doc,
                                    "code": template.code}, indent=2) + "\n", encoding="utf-8")
        self.reload()
        return f"{folder}/{name}"

    def _mine(self, entry_name: str) -> tuple[str, str, Path, ModuleTemplate]:
        folder, _, name = entry_name.rpartition("/")
        hit = self._read(folder).get(name) if folder in self.folders() else None
        if hit is None:
            raise ModuleFolderError("only modules in your own folders can be changed; copy it to one first")
        return folder, name, hit[0], hit[1]

    def copy_to(self, entry_name: str, folder: str) -> str:
        """Copy any library module (a starter, a plugin's, or yours) into one of your folders."""
        t: ModuleTemplate = self.registry.get(Library.MODULES, entry_name)
        name, n = t.name, 1
        while name in self._read(folder):
            n += 1
            name = f"{t.name} {n}"
        return self.save(folder, ModuleTemplate(name, t.kind, t.code, list(t.outputs), t.doc))

    def move(self, entry_name: str, folder: str) -> str:
        src_folder, name, path, t = self._mine(entry_name)
        if folder == src_folder:
            return entry_name
        if name in self._read(folder):
            raise ModuleFolderError(f"“{folder}” already has a module called “{name}”")
        new = self.save(folder, t)
        path.unlink()
        self.reload()
        return new

    def rename(self, entry_name: str, new_name: str) -> str:
        folder, name, path, t = self._mine(entry_name)
        new_name = _clean(new_name, "module")
        if new_name == name:
            return entry_name
        if new_name in self._read(folder):
            raise ModuleFolderError(f"“{folder}” already has a module called “{new_name}”")
        path.unlink()
        return self.save(folder, ModuleTemplate(new_name, t.kind, t.code, list(t.outputs), t.doc))

    def delete(self, entry_name: str) -> None:
        _folder, _name, path, _t = self._mine(entry_name)
        path.unlink()
        self.reload()
