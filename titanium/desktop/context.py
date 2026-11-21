"""What every view receives: the workspace (app layer) and the settings store."""
from __future__ import annotations

from dataclasses import dataclass, field, fields

from PySide6.QtCore import QSettings

from ..app.events import Event
from ..app.settings import OLD_RUN_KEYS, RunDefaults, migrate_run_settings
from ..app.workspace import Workspace
from ..core.markets import MarketDefaults

RUN_KEYS = [f.name for f in fields(RunDefaults)]  # saved as run/<name>
MARKET_KEYS = [f.name for f in fields(MarketDefaults)]  # saved as markets/<market id>/<name>
LIBRARY_KEY = "library/folder"


@dataclass
class AppContext:
    settings: QSettings
    workspace: Workspace = field(default_factory=Workspace)
    open_page: Event = field(default_factory=Event)  # (view_id,): a view asks the shell to show a page
    theme_changed: Event = field(default_factory=Event)  # (mode,)
    skin_changed: Event = field(default_factory=Event)  # (skin_id,)
    layout_changed: Event = field(default_factory=Event)  # (view_id, host)
    panel_open: Event = field(default_factory=Event)  # (view_id, open): a view is out as a page or a shown dock
    panels: dict = field(default_factory=dict)  # view_id -> open, as last announced

    def __post_init__(self) -> None:
        """Hand the saved run defaults, market defaults (and a saved library folder) to the workspace."""
        migrate_saved_settings(self.settings)
        self.workspace.set_run_defaults(saved_run_defaults(self.settings))
        for mid, market in self.workspace.markets().items():
            saved = saved_market_defaults(self.settings, mid, market.defaults)
            if saved != market.defaults:
                self.workspace.set_market_defaults(mid, saved)
        folder = self.settings.value(LIBRARY_KEY, "")
        if folder:
            self.workspace.set_library_folder(folder)

    def save_run_defaults(self, defaults: RunDefaults) -> None:
        for k, v in defaults.to_dict().items():
            self.settings.setValue(f"run/{k}", v)
        self.workspace.set_run_defaults(defaults)

    def save_market_defaults(self, market_id: str, defaults: MarketDefaults | None) -> None:
        """Save a market's defaults (``None``: back to the market's own) and hand them to the workspace."""
        self.settings.remove(f"markets/{market_id}")
        if defaults is not None:
            for k, v in defaults.to_dict().items():
                self.settings.setValue(f"markets/{market_id}/{k}", v)
        self.workspace.set_market_defaults(market_id, defaults)

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


def saved_market_defaults(settings: QSettings, market_id: str, base: MarketDefaults) -> MarketDefaults:
    return MarketDefaults.from_dict({k: settings.value(f"markets/{market_id}/{k}") for k in MARKET_KEYS}, base)


def migrate_saved_settings(settings: QSettings) -> None:
    """Move decision time and costs an older version saved as run defaults into market defaults."""
    old = {k: settings.value(f"run/{k}") for k in OLD_RUN_KEYS if settings.contains(f"run/{k}")}
    if not old:
        return
    for mid, defaults in migrate_run_settings(old).items():
        if not any(settings.contains(f"markets/{mid}/{k}") for k in MARKET_KEYS):
            for k, v in defaults.to_dict().items():
                settings.setValue(f"markets/{mid}/{k}", v)
    for k in old:
        settings.remove(f"run/{k}")
