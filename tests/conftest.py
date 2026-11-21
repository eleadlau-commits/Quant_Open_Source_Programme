import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    from titanium.desktop.design import theme

    app = QApplication.instance() or QApplication([])
    theme.apply(app, "light")
    yield app


@pytest.fixture
def ctx(tmp_path):
    from PySide6.QtCore import QSettings

    from titanium.desktop.context import AppContext

    return AppContext(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
