"""Your own modules in the module library, kept in folders: ``Workspace.modules``.

They live in the module library folder (``Workspace.library_folder``, chosen in
Settings; ``paths.app_folder() / "library"`` by default): one sub-folder per library
folder, one ``.py`` file per module, read by ``core.module_library.load_library_folder``.
This service makes, renames and deletes those folders and files, then has the
workspace read the folder again, so every page that lists modules sees the change
(``Workspace.library_changed``).

Starters and plugin modules can't be changed here, only copied into one of your folders.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.module_library import LIBRARY_PLUGIN, STARTER, ModuleTemplate, template_from_file
from ..core.plugins import Library
from ..core.strategy import Module

if TYPE_CHECKING:
    from .workspace import Workspace

USER = LIBRARY_PLUGIN  # the registry's plugin id for modules in your folders


class ModuleFolderError(ValueError):
    """A folder or module operation that can't be done (the message says why)."""


def _clean(name: str, what: str) -> str:
    name = " ".join(str(name).split())
    if not name:
        raise ModuleFolderError(f"the {what} needs a name")
    if "/" in name or "\\" in name or name.startswith((".", "_")):
        raise ModuleFolderError(f"a {what} name can't contain / or \\, or start with . or _")
    return name


def _file_stem(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "", name).strip().replace(" ", "_").lower() or "module"


def module_file(t: ModuleTemplate) -> str:
    """A library module as the ``.py`` file the library folder holds."""
    outs = json.dumps(list(t.outputs))
    return (f"from titanium.sdk import knob, module\n\n\n"
            f"@module(name={json.dumps(t.name, ensure_ascii=False)}, kind={json.dumps(t.kind)}, outputs={outs})\n"
            f"{t.code.strip(chr(10))}\n")


def template_from_module(m: Module, name: str | None = None) -> ModuleTemplate:
    """A strategy's module as a library entry (its code, kind and outputs)."""
    doc = ""
    try:
        fn = next(n for n in ast.parse(m.code).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        doc = ((ast.get_docstring(fn) or "").strip().splitlines() or [""])[0]
    except (SyntaxError, StopIteration):
        pass
    return ModuleTemplate(name or m.name, m.kind, m.code, [p.name for p in m.outputs], doc)


class ModuleFolders:
    def __init__(self, workspace: "Workspace") -> None:
        self.ws = workspace

    @property
    def registry(self):
        return self.ws.registry

    @property
    def root(self) -> Path:
        """The library folder (a temporary one for the session if the workspace has none)."""
        if self.ws.library_folder is None:
            self.ws.set_library_folder(Path(tempfile.mkdtemp(prefix="titanium-library-")))
        self.ws.library_folder.mkdir(parents=True, exist_ok=True)
        return self.ws.library_folder

    # ---- reading
    def folders(self) -> list[str]:
        """Your folders, by name."""
        root = self.ws.library_folder
        if root is None or not root.is_dir():
            return []
        return sorted((p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))),
                      key=str.lower)

    def modules(self, folder: str) -> list[str]:
        return sorted(self._read(folder), key=str.lower)

    def is_mine(self, entry_name: str) -> bool:
        """True for a library entry in one of your folders (one you can rename, move or delete)."""
        return any(e.name == entry_name and e.plugin == USER for e in self.registry.entries(Library.MODULES))

    def _read(self, folder: str) -> dict[str, tuple[Path, ModuleTemplate]]:
        out: dict[str, tuple[Path, ModuleTemplate]] = {}
        root = self.ws.library_folder
        d = root / folder if root is not None else None
        if d is None or not d.is_dir():
            return out
        for f in sorted(d.glob("*.py")):
            try:
                t = template_from_file(f)
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
                continue  # a broken file never breaks the library (Settings lists it)
            out.setdefault(t.name, (f, t))
        return out

    def reload(self) -> None:
        self.ws.reload_library()

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
        new = _clean(new, "folder")
        if new == old:
            return old
        if new.lower() != old.lower():
            new = self._check_new_folder(new)
        (self.root / old).rename(self.root / new)
        self.reload()
        return new

    def delete_folder(self, name: str) -> None:
        if name not in self.folders():
            raise ModuleFolderError(f"no folder called “{name}”")
        d = self.root / name
        if any(d.glob("*.py")):
            raise ModuleFolderError(f"“{name}” still has modules in it. Move or delete them first")
        shutil.rmtree(d)
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
        path = self.root / folder / f"{stem}.py"
        while path.exists():
            n += 1
            path = self.root / folder / f"{stem}_{n}.py"
        t = ModuleTemplate(name, template.kind, template.code, list(template.outputs), template.doc)
        path.write_text(module_file(t), encoding="utf-8")
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
        path.unlink()
        return self.save(folder, t)

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
