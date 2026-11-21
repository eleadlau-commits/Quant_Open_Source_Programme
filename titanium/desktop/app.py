"""Start the desktop app: ``titanium`` or ``python -m titanium.desktop``.

    --light / --dark   force a theme for this session
    --skin <id>        use a skin for this session (classic, graphite, or one of yours)
    --self-test        open the window, check it, and exit (used by CI and installers)
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .context import AppContext
from ..app import paths
from ..core.plugins import Library
from .design import skins, theme
from .pages import default_registry
from .shell import MainWindow


def build_window(ctx: AppContext | None = None) -> MainWindow:
    ctx = ctx or AppContext.default()
    win = MainWindow(default_registry(), ctx)
    settings_view = win.views.get("settings")
    if settings_view is not None:
        settings_view.show_layout(win)
        ctx.layout_changed.connect(lambda *_: QTimer.singleShot(0, lambda: settings_view.show_layout(win)))
    app = QApplication.instance()
    ctx.theme_changed.connect(lambda mode: theme.apply(app, mode))
    ctx.skin_changed.connect(lambda skin_id: theme.apply(app, skin_id=skin_id))
    return win


def load_skins(ctx: AppContext) -> None:
    """Built-in skins, then plugins' skins, then the user's skins folder. Broken ones are
    skipped and listed in ``skins.problems()``; they never stop the app."""
    skins.load_plugin_entries(ctx.workspace.registry.entries(Library.SKINS))
    skins.load_folder(paths.skins_folder())


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Titanium")
    from pathlib import Path

    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "titanium-256.png")))
    ctx = AppContext.default()
    load_skins(ctx)
    mode = "dark" if "--dark" in argv else "light" if "--light" in argv else ctx.settings.value("view/theme", "system")
    skin_id = argv[argv.index("--skin") + 1] if "--skin" in argv[:-1] else ctx.settings.value("view/skin", skins.DEFAULT)
    theme.apply(app, mode, skin_id)
    for problem in skins.problems():
        print(problem, file=sys.stderr)
    win = build_window(ctx)
    win.show()
    if "--self-test" in argv:
        app.processEvents()
        ok = win.isVisible() and len(win.views) > 0
        print("self-test", "ok" if ok else "FAILED")
        return 0 if ok else 1
    return app.exec()
