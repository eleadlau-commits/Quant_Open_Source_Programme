"""Screenshots of every page and the design gallery, in light and dark.

    python tools/screenshots.py [out_dir]     (default: docs/screenshots)

The default skin's images go in out_dir; every other skin's in out_dir/skins/<id>/.

Every pull request that changes the UI runs this and attaches the images, so the
look is reviewed against the gallery before it is merged.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from titanium.app.workspace import Workspace  # noqa: E402
from titanium.core.strategy import StrategyGraph  # noqa: E402
from titanium.desktop.app import build_window  # noqa: E402
from titanium.desktop.context import AppContext  # noqa: E402
from titanium.desktop.design import skins, theme  # noqa: E402
from titanium.desktop.design.gallery import build as build_gallery  # noqa: E402


# window size for the shots; TITANIUM_SHOT_SIZE=1150x720 checks a small screen
SIZE = tuple(int(n) for n in os.environ.get("TITANIUM_SHOT_SIZE", "1440x900").split("x"))


def settle(app, n=30):
    for _ in range(n):
        app.processEvents()


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0] if argv else "docs/screenshots")
    app = QApplication.instance() or QApplication([])
    sample = tempfile.mkdtemp(prefix="titanium-shots-")
    sample_datasets(Path(sample))
    for sk in skins.available():
        out = root if sk.id == skins.DEFAULT else root / "skins" / sk.id
        out.mkdir(parents=True, exist_ok=True)
        shoot(app, sk.id, out, Path(sample))
    print(f"saved to {root}")
    return 0


def sample_datasets(root: Path) -> None:
    """A few small datasets so the Data page can be shot with something in it."""
    ws = Workspace(data_root=root)
    stocks = ws.datasets.add("synthetic_stocks", {"n_symbols": 12, "n_days": 40})
    ws.datasets.add("synthetic_stocks", {"n_symbols": 12, "n_days": 40, "gap_momentum": 1.5, "seed": 8})
    ws.datasets.add("synthetic_futures", {"n_days": 40})
    ws.datasets.generate("realised_vol", stocks.id, {"window": 10})
    ws.datasets.use(stocks.id, "gap-fade")
    ws.datasets.add("synthetic_stocks", {"n_symbols": 10, "n_days": 160, "seed": 4})  # for the Run view


def shoot_run(app, tmp: Path, sample: Path, out: Path, mode: str) -> None:
    """The Run view after a real run of the example strategy on synthetic data."""
    from titanium.core.module_library import momentum_rotation

    ws = Workspace(data_root=sample)
    info = next(i for i in ws.datasets.infos("core") if i.name.startswith("Synthetic stocks (10"))
    ctx = AppContext(QSettings(str(tmp / "s3.ini"), QSettings.IniFormat), ws)
    win = build_window(ctx)
    win.resize(*SIZE)
    win.show()
    win.show_page("strategies")
    g = momentum_rotation(id="S1")
    g.settings["datasets"] = [info.id]
    view = win.views["strategies"]
    view.open_graph(g)
    tab = view.tabs.currentWidget()
    tab.run_view.background = False
    tab.run()
    tab.run_view.local_pick.setCurrentIndex(tab.run_view.local_pick.findText("Weights"))
    settle(app)
    win.grab().save(str(out / f"strategy-run-{mode}.png"))
    tab.run_view.settings_btn.setChecked(True)  # the Run settings panel: where each value comes from
    settle(app)
    win.grab().save(str(out / f"strategy-run-settings-{mode}.png"))
    tab.run_view.settings_btn.setChecked(False)
    settle(app)
    from titanium.desktop.design.components import BusyOverlay  # the busy state while a run computes
    ov = BusyOverlay.of(win)
    ov.start("Running Momentum rotation\n42%", ov.stop)
    ov._appear()
    ov._fade_step(1.0)
    ov._spin_step(70.0)
    settle(app)
    win.grab().save(str(out / f"strategy-run-busy-{mode}.png"))
    ov.stop()
    win.show_page("data")
    settle(app)
    win.close()


def shoot(app, skin_id: str, out: Path, sample: Path | None = None) -> None:
    for mode in ("light", "dark"):
        theme.apply(app, mode, skin_id)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AppContext(QSettings(str(Path(tmp) / "s.ini"), QSettings.IniFormat))
            win = build_window(ctx)
            win.resize(*SIZE)
            win.show()
            settle(app)
            for page in ("data", "strategies", "compare", "backtests", "settings"):
                win.show_page(page)
                settle(app)
                win.grab().save(str(out / f"{page}-{mode}.png"))
            win.show_page("strategies")
            win.views["strategies"].new_strategy()
            settle(app)
            win.grab().save(str(out / f"strategy-tab-{mode}.png"))
            from titanium.core.module_library import momentum_rotation

            view = win.views["strategies"]
            view.open_graph(momentum_rotation(id="S2"), view=1)
            view.tabs.currentWidget().code.editor.setFocus()
            settle(app)
            win.grab().save(str(out / f"strategy-code-{mode}.png"))
            win.close()
            shoot_patch_bay(app, Path(tmp), out, mode)
            if sample is not None:
                shoot_run(app, Path(tmp), sample, out, mode)
                shoot_compare_backtests(app, Path(tmp), sample, out, mode)
            if sample is not None:
                ws = Workspace(data_root=sample)
                ws.strategies.put("gap-fade", StrategyGraph("gap-fade", "Gap fade"))
                ctx = AppContext(QSettings(str(Path(tmp) / "s2.ini"), QSettings.IniFormat), ws)
                win = build_window(ctx)
                win.resize(*SIZE)
                win.show()
                win.show_page("data")
                settle(app)
                win.grab().save(str(out / f"data-datasets-{mode}.png"))
                win.close()
            shoot_settings(app, out, mode, Path(tmp))
        g = build_gallery()
        g.resize(1280, 2200)
        g.show()
        settle(app)
        g.widget().grab().save(str(out / f"gallery-{mode}.png"))
        g.close()


_TESTED: dict = {}


def tested_workspace(sample: Path) -> Workspace:
    """Two strategies run on synthetic data, with the default strategy and a set of tests run on the
    first. Made once and shared by every skin and mode (the work doesn't depend on the look)."""
    if "ws" in _TESTED:
        return _TESTED["ws"]
    from titanium.core.module_library import momentum_rotation

    ws = Workspace(data_root=sample)
    info = next(i for i in ws.datasets.infos("core") if i.name.startswith("Synthetic stocks (10"))
    a = momentum_rotation(id="S1")
    a.settings["datasets"] = [info.id]
    b = momentum_rotation(id="S2", name="Fast momentum")
    b.settings["datasets"] = [info.id]
    b.knob_values = {"m1.days": 10, "m3.top": 3}
    ws.strategies.put("S1", a)
    ws.strategies.put("S2", b)
    ws.runs.run("S2")
    ra = ws.runs.run("S1")
    ws.runs.commit(ws.runs.prepare_baseline(ra).execute())
    for tid, params in (("out_of_sample", {}), ("bootstrap", {}), ("deflated_sharpe", {}), ("cost_stress", {}),
                        ("random_baseline", {"n": 8}), ("benchmark", {}), ("parameter_stability", {})):
        ws.backtests.run(ra.id, tid, params)
    _TESTED["ws"] = ws
    return ws


def shoot_compare_backtests(app, tmp: Path, sample: Path, out: Path, mode: str) -> None:
    ws = tested_workspace(sample)
    ctx = AppContext(QSettings(str(tmp / "s4.ini"), QSettings.IniFormat), ws)
    win = build_window(ctx)
    win.resize(*SIZE)
    win.show()
    win.show_page("compare")
    settle(app)
    win.grab().save(str(out / f"compare-runs-{mode}.png"))
    win.show_page("backtests")
    view = win.views["backtests"]
    view.select_strategy("S1")
    settle(app)
    win.grab().save(str(out / f"backtests-results-{mode}.png"))
    win.close()


def shoot_patch_bay(app, tmp: Path, out: Path, mode: str) -> None:
    """The patch bay with the example strategy, a module selected, and a folder of your own in the library."""
    from titanium.core.module_library import STARTER, momentum_rotation

    ws = Workspace(library_folder=tmp / "library")
    ws.modules.copy_to(f"{STARTER}/Momentum", "My signals")
    ctx = AppContext(QSettings(str(tmp / "s3.ini"), QSettings.IniFormat), ws)
    win = build_window(ctx)
    win.resize(*SIZE)
    win.show()
    win.show_page("strategies")
    view = win.views["strategies"]
    g = momentum_rotation(id="S1")
    view.open_graph(g, view=0)
    bay = view.tabs.currentWidget().patch
    bay.turn_knob("m3.top", 8)
    settle(app)
    bay.view.fit()
    bay.scene.nodes["m2"].setSelected(True)
    settle(app)
    win.grab().save(str(out / f"patch-bay-{mode}.png"))
    win.close()


def shoot_settings(app, out: Path, mode: str, tmp: Path) -> None:
    """The whole Settings page, with a plugin of your own and one that can't load."""
    import json

    plugins = tmp / "plugins"
    for pid, name, extra in (("neon-skin", "Neon skin", {"main": None, "provides": {}}),
                             ("bootstrap-test", "Bootstrap test", {"main": None, "requires": ["out-of-sample"]})):
        (plugins / pid).mkdir(parents=True, exist_ok=True)
        (plugins / pid / "plugin.json").write_text(json.dumps({
            "id": pid, "name": name, "version": "0.3.0", "description": {
                "neon-skin": "A brighter signal colour for Graphite.",
                "bootstrap-test": "Resamples weekly returns to see if the result could be luck."}[pid], **extra}))
    ws = Workspace(plugins_folder=plugins, library_folder=tmp / "library")
    ctx = AppContext(QSettings(str(tmp / "s3.ini"), QSettings.IniFormat), ws)
    win = build_window(ctx)
    win.resize(1440, 1900)
    win.show()
    win.show_page("settings")
    settle(app)
    win.grab().save(str(out / f"settings-full-{mode}.png"))
    win.close()


if __name__ == "__main__":
    raise SystemExit(main())
