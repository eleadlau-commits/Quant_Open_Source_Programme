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


@pytest.fixture(autouse=True)
def no_strategy_dialogs(request, monkeypatch):
    """Closing or deleting a strategy asks first; tests answer for the user instead of a dialog
    blocking (closing discards changes, deleting is confirmed and keeps the saved file)."""
    if "qapp" not in request.fixturenames:
        return
    from titanium.desktop.pages.strategies import StrategiesView

    monkeypatch.setattr(StrategiesView, "ask_save", lambda self, tab: "discard")
    monkeypatch.setattr(StrategiesView, "confirm_delete", lambda self, tab, footprint: (True, False))
