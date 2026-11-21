"""Start the desktop app: ``titanium`` or ``python -m titanium.desktop``.

    --light / --dark   force a theme for this session
    --self-test        open the window, check it, and exit (used by CI and installers)
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .context import AppContext
from .design import theme
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
    return win


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Titanium")
    from pathlib import Path

    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets" / "titanium-256.png")))
    ctx = AppContext.default()
    mode = "dark" if "--dark" in argv else "light" if "--light" in argv else ctx.settings.value("view/theme", "system")
    theme.apply(app, mode)
    win = build_window(ctx)
    win.show()
    if "--self-test" in argv:
        app.processEvents()
        ok = win.isVisible() and len(win.views) > 0
        print("self-test", "ok" if ok else "FAILED")
        return 0 if ok else 1
    return app.exec()
