"""What every view receives: the workspace (app layer) and the settings store."""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QSettings

from ..app.events import Event
from ..app.workspace import Workspace


@dataclass
class AppContext:
    settings: QSettings
    workspace: Workspace = field(default_factory=Workspace)
    open_page: Event = field(default_factory=Event)  # (view_id,): a view asks the shell to show a page
    theme_changed: Event = field(default_factory=Event)  # (mode,)
    skin_changed: Event = field(default_factory=Event)  # (skin_id,)
    layout_changed: Event = field(default_factory=Event)  # (view_id, host)

    @classmethod
    def default(cls) -> "AppContext":
        from ..app.paths import app_folder

        return cls(QSettings("Titanium", "Titanium"), Workspace(data_root=app_folder() / "data", modules_root=app_folder() / "modules"))
