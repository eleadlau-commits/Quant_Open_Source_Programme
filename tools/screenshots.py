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


def shoot(app, skin_id: str, out: Path, sample: Path | None = None) -> None:
    for mode in ("light", "dark"):
        theme.apply(app, mode, skin_id)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = AppContext(QSettings(str(Path(tmp) / "s.ini"), QSettings.IniFormat))
            win = build_window(ctx)
            win.resize(1440, 900)
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
                ws = Workspace(data_root=sample)
                ws.strategies.put("gap-fade", StrategyGraph("gap-fade", "Gap fade"))
                ctx = AppContext(QSettings(str(Path(tmp) / "s2.ini"), QSettings.IniFormat), ws)
                win = build_window(ctx)
                win.resize(1440, 900)
                win.show()
                win.show_page("data")
                settle(app)
                win.grab().save(str(out / f"data-datasets-{mode}.png"))
                win.close()
        g = build_gallery()
        g.resize(1280, 2200)
        g.show()
        settle(app)
        g.widget().grab().save(str(out / f"gallery-{mode}.png"))
        g.close()


def shoot_patch_bay(app, tmp: Path, out: Path, mode: str) -> None:
    """The patch bay with the example strategy, a module selected, and a folder of your own in the library."""
    from titanium.core.module_library import STARTER, momentum_rotation

    ws = Workspace(modules_root=tmp / "modules")
    ws.modules.copy_to(f"{STARTER}/Momentum", "My signals")
    ctx = AppContext(QSettings(str(tmp / "s3.ini"), QSettings.IniFormat), ws)
    win = build_window(ctx)
    win.resize(1440, 900)
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


if __name__ == "__main__":
    raise SystemExit(main())
