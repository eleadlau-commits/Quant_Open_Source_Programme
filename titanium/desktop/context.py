"""What every view receives: the workspace (app layer) and the settings store."""
from __future__ import annotations

from dataclasses import dataclass, field, fields

from PySide6.QtCore import QSettings

from ..app.events import Event
from ..app.settings import RunDefaults
from ..app.workspace import Workspace

RUN_KEYS = [f.name for f in fields(RunDefaults)]  # saved as run/<name>
LIBRARY_KEY = "library/folder"


@dataclass
class AppContext:
    settings: QSettings
    workspace: Workspace = field(default_factory=Workspace)
    open_page: Event = field(default_factory=Event)  # (view_id,): a view asks the shell to show a page
    theme_changed: Event = field(default_factory=Event)  # (mode,)
    skin_changed: Event = field(default_factory=Event)  # (skin_id,)
    layout_changed: Event = field(default_factory=Event)  # (view_id, host)

    def __post_init__(self) -> None:
        """Hand the saved run defaults (and a saved library folder) to the workspace."""
        self.workspace.set_run_defaults(saved_run_defaults(self.settings))
        folder = self.settings.value(LIBRARY_KEY, "")
        if folder:
            self.workspace.set_library_folder(folder)

    def save_run_defaults(self, defaults: RunDefaults) -> None:
        for k, v in defaults.to_dict().items():
            self.settings.setValue(f"run/{k}", v)
        self.workspace.set_run_defaults(defaults)

    def save_library_folder(self, folder: str) -> None:
        self.settings.setValue(LIBRARY_KEY, folder)
        self.workspace.set_library_folder(folder or None)

    @classmethod
    def default(cls) -> "AppContext":
        from ..app import paths

        settings = QSettings("Titanium", "Titanium")
        ws = Workspace(data_root=paths.app_folder() / "data", plugins_folder=paths.plugins_folder(),
                       library_folder=settings.value(LIBRARY_KEY, "") or paths.library_folder())
        return cls(settings, ws)


def saved_run_defaults(settings: QSettings) -> RunDefaults:
    return RunDefaults.from_dict({k: settings.value(f"run/{k}") for k in RUN_KEYS})
