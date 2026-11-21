from datetime import datetime, timezone

import pytest

from titanium.core.markets import NASDAQ
from titanium.core.plugins import Library, Manifest, Registry
from titanium.core.portfolio import PortfolioState, Position
from titanium.core.strategy import Knob, KnobType, Module, StrategyGraph


def test_market_shows_utc_in_local_time():
    ts = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    assert NASDAQ.local(ts).hour == 9 and NASDAQ.local(ts).minute == 30
    assert NASDAQ.session().name == "regular"
    with pytest.raises(ValueError):
        NASDAQ.local(datetime(2026, 7, 1, 13, 30))  # naive timestamps are refused


def test_knobs_are_keyed_by_module():
    g = StrategyGraph("S1", "test", modules=[
        Module("m1", "decide", "decide", knobs=[Knob("days", KnobType.INT, 20, 5, 120)])])
    assert list(g.knobs()) == ["m1.days"]


def test_portfolio_weights_and_growth():
    t = datetime(2026, 1, 2, tzinfo=timezone.utc)
    s = PortfolioState(t, cash=50_000, positions={"xnas:AAA": Position("xnas:AAA", 100, 400, 50_000)},
                       equity=100_000, capital=80_000)
    assert s.weights() == {"xnas:AAA": 0.5}
    assert s.growth == 1.25


def test_registry_tracks_plugins():
    reg = Registry()
    reg.add(Library.MEASUREMENTS, "profit", object(), plugin="core-measures")
    reg.add(Library.BACKTESTS, "bootstrap", object(), plugin="bootstrap")
    with pytest.raises(ValueError):
        reg.add(Library.MEASUREMENTS, "profit", object())
    reg.remove_plugin("bootstrap")
    assert [e.name for e in reg.entries(Library.BACKTESTS)] == []
    with pytest.raises(KeyError, match="known: none"):
        reg.get(Library.BACKTESTS, "bootstrap")


def test_manifest_rejects_unknown_library(tmp_path):
    (tmp_path / "plugin.json").write_text('{"id": "x", "name": "X", "version": "1.0.0", "provides": {"widgets": ["a"]}}')
    with pytest.raises(ValueError, match="unknown libraries"):
        Manifest.read(tmp_path)
