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
    for sk in skins.available():
        out = root if sk.id == skins.DEFAULT else root / "skins" / sk.id
        out.mkdir(parents=True, exist_ok=True)
        shoot(app, sk.id, out)
    print(f"saved to {root}")
    return 0


def shoot(app, skin_id: str, out: Path) -> None:
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
            win.close()
        g = build_gallery()
        g.resize(1280, 2200)
        g.show()
        settle(app)
        g.widget().grab().save(str(out / f"gallery-{mode}.png"))
        g.close()


if __name__ == "__main__":
    raise SystemExit(main())
