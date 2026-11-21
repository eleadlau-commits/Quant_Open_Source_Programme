"""The Settings page: run defaults, the module library folder, the Plugins card."""
import json

import pytest
from PySide6.QtCore import QSettings

from titanium.app.settings import RunDefaults
from titanium.app.workspace import Workspace
from titanium.core.plugins import Library
from titanium.desktop.context import AppContext
from titanium.desktop.design.components import ItemRow, Switch
from titanium.desktop.pages.settings import SettingsView
from titanium.plugins import pack as P


@pytest.fixture
def home(tmp_path):
    return tmp_path


@pytest.fixture
def ctx(home):
    ws = Workspace(data_root=home / "data", plugins_folder=home / "plugins", library_folder=home / "library")
    return AppContext(QSettings(str(home / "settings.ini"), QSettings.IniFormat), ws)


@pytest.fixture
def page(qapp, ctx):
    view = SettingsView(ctx)
    view.show()
    qapp.processEvents()
    yield view
    view.close()


def test_the_page_keeps_its_cards(page):
    from titanium.desktop.design.components import Card
    titles = [c.findChildren(type(page.skin_about))[0].text() for c in page.findChildren(Card)]
    for t in ("Appearance", "Skin", "Defaults for every run", "Markets", "Module library", "Plugins", "Layout"):
        assert t in titles


def test_run_defaults_are_saved_and_reach_the_workspace(page, ctx, home):
    page.capital.setValue(250_000)
    page.every.set_index(1)
    page.max_gross.setValue(150)
    page.min_trade.setValue(0.5)
    want = RunDefaults(capital=250_000, every="week", max_gross=1.5, min_trade=0.005)
    assert ctx.workspace.run_defaults == want
    assert ctx.workspace.run_settings()["every"] == "week"
    # a new session reads them back into its workspace
    again = AppContext(QSettings(str(home / "settings.ini"), QSettings.IniFormat), Workspace())
    assert again.workspace.run_defaults == want
    assert SettingsView(again).capital.value() == 250_000


def test_market_defaults_are_saved_and_old_run_costs_move_to_markets(home):
    from titanium.core.markets import NASDAQ, MarketDefaults

    path = str(home / "old.ini")
    old = QSettings(path, QSettings.IniFormat)
    for k, v in {"capital": 5e4, "decide_at": "10:30", "slippage_bps": 9.0, "futures_slippage_ticks": 2.0}.items():
        old.setValue(f"run/{k}", v)
    old.sync()
    ctx = AppContext(QSettings(path, QSettings.IniFormat), Workspace())
    ws = ctx.workspace
    assert ws.run_defaults.capital == 5e4
    xnas, cme = ws.market("xnas").defaults, ws.market("cme").defaults
    assert xnas.decide_at == cme.decide_at == "10:30" and xnas.slippage_bps == 9 and cme.futures_slippage_ticks == 2
    assert xnas.extended_hours is False and cme.extended_hours is True  # each market keeps its own
    assert not ctx.settings.contains("run/slippage_bps")
    ctx.save_market_defaults("xnas", MarketDefaults(half_spread_bps=2))
    again = AppContext(QSettings(path, QSettings.IniFormat), Workspace())
    assert again.workspace.market("xnas").defaults == MarketDefaults(half_spread_bps=2)
    again.save_market_defaults("xnas", None)
    assert AppContext(QSettings(path, QSettings.IniFormat), Workspace()).workspace.market("xnas").defaults == \
        NASDAQ.defaults


def test_markets_card_shows_sessions_and_edits_defaults(page, ctx, home):
    from titanium.core.markets import CME_GLOBEX

    assert set(page.market_rows) >= {"xnas", "cme"}
    cme = page.market_rows["cme"]
    assert cme.extended.isChecked() and not cme.reset.isVisible()
    assert cme.futures_slippage.isVisibleTo(page) and cme.half_spread.parent() is None  # CME lists futures only
    assert "Christmas Day: closed" in cme.holidays.text()
    cme.futures_slippage.setValue(2)
    assert ctx.workspace.market("cme").defaults.futures_slippage_ticks == 2 and cme.reset.isVisible()
    again = AppContext(QSettings(str(home / "settings.ini"), QSettings.IniFormat), Workspace())
    assert again.workspace.market("cme").defaults.futures_slippage_ticks == 2
    assert SettingsView(again).market_rows["cme"].futures_slippage.value() == 2
    cme.use_own()
    assert ctx.workspace.market("cme").defaults == CME_GLOBEX.defaults and not cme.reset.isVisible()
    xnas = page.market_rows["xnas"]
    xnas.extended.setChecked(True)
    assert ctx.workspace.run_settings(market="xnas")["extended_hours"] is True


def test_every_plugin_is_listed_with_a_switch(page, ctx):
    ids = {s.id for s in ctx.workspace.plugins.statuses()}
    assert set(page.plugin_rows) == ids
    row = page.plugin_rows["synthetic-data"]
    assert isinstance(row, ItemRow) and row.switch.isChecked() and "2 data sources" in row.note.text()


def test_switching_a_plugin_off_removes_its_entries_and_is_remembered(page, ctx, home, qapp):
    page.plugin_rows["realised-volatility"].switch.setChecked(False)
    qapp.processEvents()
    assert ctx.workspace.registry.entries(Library.GENERATORS) == []
    assert json.loads((home / "plugins" / "plugins.json").read_text()) == {"off": ["realised-volatility"]}
    row = page.plugin_rows["realised-volatility"]
    assert not row.switch.isChecked()
    page.plugin_rows["realised-volatility"].switch.setChecked(True)
    qapp.processEvents()
    assert [e.name for e in ctx.workspace.registry.entries(Library.GENERATORS)] == ["realised_vol"]


def test_a_broken_plugin_shows_why(qapp, home):
    folder = home / "plugins" / "needs-ghost"
    folder.mkdir(parents=True)
    (folder / "plugin.json").write_text(json.dumps({"id": "needs-ghost", "name": "Needs ghost", "version": "1.0.0",
                                                    "main": None, "requires": ["ghost"]}))
    ws = Workspace(plugins_folder=home / "plugins")
    view = SettingsView(AppContext(QSettings(str(home / "s.ini"), QSettings.IniFormat), ws))
    assert view.plugin_rows["needs-ghost"].note.text() == "Needs plugin 'ghost', which is not installed."


def test_import_pack_installs_and_lists_it(page, ctx, home):
    src = P.new("extra-modules", "modules", base=home / "work")
    file = P.pack(src, home / "out")
    assert page.import_pack(str(file))
    assert "extra-modules" in page.plugin_rows and page.plugin_rows["extra-modules"].switch.isChecked()
    assert "extra_modules/Extra modules" in {e.name for e in ctx.workspace.registry.entries(Library.MODULES)}
    assert page.plugin_message.text().startswith("Imported")
    (home / "junk.tiplug").write_text("nope")
    assert not page.import_pack(str(home / "junk.tiplug"))
    assert page.plugin_message.text().startswith("Couldn't import junk.tiplug")


def test_the_library_card_shows_the_folder_and_its_modules(page, ctx, home):
    assert str(home / "library") in page.library_path.text()
    assert "starter (3)" in page.library_summary.text()
    (home / "mine").mkdir()
    (home / "mine" / "rsi").mkdir()
    (home / "mine" / "rsi" / "rsi.py").write_text("def rsi(view):\n    return {}\n")
    ctx.save_library_folder(str(home / "mine"))
    assert page.library_path.text() == str(home / "mine")
    assert "rsi (1)" in page.library_summary.text()
    assert ctx.settings.value("library/folder") == str(home / "mine")


def test_switch_in_the_kit(qapp):
    s = Switch(True)
    s.show()
    s.grab()
    s.click()
    assert not s.isChecked()
