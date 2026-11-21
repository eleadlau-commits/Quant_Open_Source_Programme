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
    layout_changed: Event = field(default_factory=Event)  # (view_id, host)

    @classmethod
    def default(cls) -> "AppContext":
        return cls(QSettings("Titanium", "Titanium"))
