"""Start the desktop app: ``titanium`` or ``python -m titanium.desktop``.

    --light / --dark   force a theme for this session
    --skin <id>        use a skin for this session (classic, graphite, or one of yours)
    --self-test        open the window, visit every view, run a small strategy on synthetic
                       data, and exit (used by CI and the installers). The report is printed,
                       and also written to ``TITANIUM_SELFTEST_OUT`` when that is set.
"""
from __future__ import annotations

import sys
from pathlib import Path

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


def self_test(win: MainWindow) -> list[str]:
    """Problems found (empty when all is well). Visits every view, then runs the starter
    momentum strategy through the engine on a small synthetic dataset in a temporary folder,
    so a build that is missing a module, a data file or a plugin fails here."""
    import tempfile

    from ..app.workspace import Workspace
    from ..core.module_library import momentum_rotation

    problems: list[str] = []
    app = QApplication.instance()
    if not win.isVisible():
        problems.append("the window did not open")
    if not win.views:
        problems.append("no views")
    for view_id in list(win.views):
        try:
            win.show_page(view_id)
            app.processEvents()
        except Exception as e:  # noqa: BLE001 - reported, not raised
            problems.append(f"view {view_id}: {e!r}")
    if win.views.get("data") is not None:
        win.show_page("data")
    statuses = {st.id: st for st in win.ctx.workspace.plugins.statuses()}
    for name in ("synthetic-data", "starter-modules", "market-downloads", "realised-volatility", "honest-tests"):
        st = statuses.get(name)
        if st is None or not (st.on or st.switched_off):
            problems.append(f"built-in plugin {name} did not load" + (f": {st.reason}" if st else ""))
    try:
        with tempfile.TemporaryDirectory() as root:
            tws = Workspace(data_root=root)
            info = tws.datasets.add("synthetic_stocks", {"n_symbols": 6, "n_days": 70, "seed": 3})
            g = momentum_rotation(id="selftest")
            g.knob_values["m2.days"] = 10
            record = tws.runs.run(g, {}, info.id)
            if not record.states:
                problems.append("the test run recorded no steps")
    except Exception as e:  # noqa: BLE001
        import traceback

        problems.append(f"test run: {e!r}\n" + "".join(traceback.format_exc(limit=-8)))
    return problems


def _report_self_test(problems: list[str]) -> int:
    import os

    lines = ["self-test " + ("ok" if not problems else "FAILED"), *problems]
    text = "\n".join(lines)
    print(text)
    out = os.environ.get("TITANIUM_SELFTEST_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0 if not problems else 1


APP_ID = "QuantOpenSource.Titanium"  # Windows taskbar grouping; matches the installer's shortcuts
ICON_DIR = Path(__file__).resolve().parent / "assets"


def app_icon() -> QIcon:
    """The logo at every size it was drawn for, so the title bar (16 px) and the taskbar
    (24 to 48 px) get sharp pixels rather than a scaled-down 256 px image."""
    icon = QIcon()
    for f in sorted(ICON_DIR.glob("titanium-*.png")):
        icon.addFile(str(f))
    return icon


def set_windows_app_id() -> None:
    """Without this, Windows groups the window under python(w).exe and shows the Python
    logo in the taskbar when the app runs from source or the use-my-Python install."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001 - cosmetic only
            pass


def main(argv=None, on_shown=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    set_windows_app_id()  # before any window exists
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Titanium")
    app.setWindowIcon(app_icon())
    ctx = AppContext.default()
    load_skins(ctx)
    mode = "dark" if "--dark" in argv else "light" if "--light" in argv else ctx.settings.value("view/theme", "system")
    skin_id = argv[argv.index("--skin") + 1] if "--skin" in argv[:-1] else ctx.settings.value("view/skin", skins.DEFAULT)
    theme.apply(app, mode, skin_id)
    for problem in skins.problems():
        print(problem, file=sys.stderr)
    win = build_window(ctx)
    win.show()
    if on_shown is not None:
        on_shown()  # e.g. close the splash of the portable build
    if "--self-test" in argv:
        app.processEvents()
        return _report_self_test(self_test(win))
    return app.exec()
