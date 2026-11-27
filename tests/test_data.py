"""The data layer: calendar, bar store, the look-ahead guard (ported from the prototype), sources."""
from datetime import date, datetime, time, timezone

import numpy as np
import pandas as pd
import pytest

from titanium.core.bars import BarStore, MarketData, daily_from_minutes, info_from_dict, info_to_dict
from titanium.core.calendars import NasdaqCalendar, easter
from titanium.core.data import DataKind, DatasetInfo, Frequency, GuardedView, LookAheadError, SourceSpec
from titanium.core.generators import RealisedVolatility
from titanium.core.guard import Guard
from titanium.core.markets import NASDAQ
from titanium.core.plugins import Library, Registry
from titanium.core.sources import FileImport, SyntheticFutures, SyntheticStocks, register_sources

NY = NASDAQ.tz


def ny(day, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), NY)


@pytest.fixture(scope="module")
def small_data() -> MarketData:
    src = SyntheticStocks()
    return src.load(src.spec(n_symbols=6, n_days=40, seed=3))


@pytest.fixture(scope="module")
def day(small_data):
    key = small_data.instruments[0]
    return small_data.daily(key).index[10].date()


# ---- calendar -------------------------------------------------------------------
def test_calendar_matches_published_nasdaq_schedule():
    cal = NasdaqCalendar()
    assert len(cal.trading_days(date(2024, 1, 1), date(2024, 12, 31))) == 252
    assert len(cal.trading_days(date(2025, 1, 1), date(2025, 12, 31))) == 250
    assert easter(2026) == date(2026, 4, 5)
    for closed in (date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
                   date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
                   date(2025, 1, 9)):  # 2026 holidays (July 4th is a Saturday) and the Carter day of mourning
        assert not cal.is_trading_day(closed), closed
    assert cal.is_trading_day(date(2021, 12, 31))  # a Saturday New Year is not moved to Friday
    assert cal.early_close(date(2025, 11, 28)) == time(13, 0)
    assert cal.early_close(date(2025, 12, 24)) == time(13, 0)
    assert cal.early_close(date(2025, 7, 3)) == time(13, 0)
    assert cal.early_close(date(2025, 7, 2)) is None


def test_session_times_are_utc_and_follow_daylight_saving():
    cal = NasdaqCalendar()
    assert cal.session_open(date(2025, 1, 6)) == datetime(2025, 1, 6, 14, 30, tzinfo=timezone.utc)
    assert cal.session_open(date(2025, 7, 7)) == datetime(2025, 7, 7, 13, 30, tzinfo=timezone.utc)
    assert cal.session_close(date(2025, 11, 28)) == datetime(2025, 11, 28, 18, 0, tzinfo=timezone.utc)
    assert NASDAQ.calendar is not None


# ---- bars --------------------------------------------------------------------------
def test_daily_bars_come_from_regular_session_minutes_only():
    d = date(2025, 11, 28)  # early close at 13:00
    idx = pd.date_range(ny(d, "09:00"), ny(d, "16:59"), freq="1min").tz_convert("UTC")
    m = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": np.arange(len(idx), dtype=float),
                      "volume": 1.0}, index=idx)
    daily = daily_from_minutes(m, NASDAQ)
    assert len(daily) == 1
    row = daily.iloc[0]
    assert row["volume"] == 210  # 09:30 to 12:59: the minutes of a 13:00 close
    assert row["close"] == m.loc[pd.Timestamp(ny(d, "12:59")), "close"]
    assert row["end"] == pd.Timestamp("2025-11-28 18:00", tz="UTC")


def test_minute_timestamps_are_utc(small_data):
    m = small_data.minute(small_data.instruments[0])
    assert str(m.index.tz) == "UTC"
    assert m.index[0].tz_convert(NY).time() == time(9, 0)


# ---- guard (the prototype's honesty tests) ---------------------------------------------
def test_guard_is_a_guarded_view(small_data, day):
    assert isinstance(Guard(small_data, ny(day, "10:00")), GuardedView)
    with pytest.raises(ValueError):
        Guard(small_data, datetime(2024, 1, 3, 10, 0))  # naive times are refused


def test_minute_bars_end_by_as_of(small_data, day):
    key = small_data.instruments[0]
    v = Guard(small_data, ny(day, "09:30"))
    bars = v.bars(key, Frequency.MINUTE)
    assert bars.index[-1] + pd.Timedelta(minutes=1) <= v.as_of
    assert bars.index[-1].tz_convert(NY).time() == time(9, 29)  # the 09:29 bar is the last visible one


def test_asking_for_the_future_raises(small_data, day):
    key = small_data.instruments[0]
    v = Guard(small_data, ny(day, "09:30"))
    with pytest.raises(LookAheadError):
        v.bars(key, Frequency.MINUTE, end=ny(day, "09:31"))
    with pytest.raises(LookAheadError):
        v.bars(key, Frequency.DAILY, start=ny(day, "12:00"))


def test_daily_excludes_today_until_the_close(small_data, day):
    key = small_data.instruments[0]
    assert Guard(small_data, ny(day, "15:59")).daily(key).index[-1].date() < day
    assert Guard(small_data, ny(day, "16:00")).daily(key).index[-1].date() == day


def test_daily_bar_visible_at_early_close():
    src = SyntheticStocks()
    data = src.load(src.spec(n_symbols=1, n_days=5, start="2025-11-25", delist_frac=0.0))
    key = data.instruments[0]
    d = date(2025, 11, 28)
    assert Guard(data, ny(d, "12:59")).daily(key).index[-1].date() < d
    assert Guard(data, ny(d, "13:00")).daily(key).index[-1].date() == d


def test_premarket_last_uses_only_premarket(small_data, day):
    key = small_data.instruments[0]
    at_open = Guard(small_data, ny(day, "09:30")).premarket_last(key)
    assert at_open == Guard(small_data, ny(day, "11:00")).premarket_last(key)
    assert Guard(small_data, ny(day, "09:10")).premarket_last(key) != at_open


def test_delisted_names_stay_in_universe_until_they_stop_trading():
    src = SyntheticStocks()
    d = src.load(src.spec(n_symbols=30, n_days=120, seed=1, delist_frac=0.5))
    cal = NASDAQ.calendar
    last_day = max(d.span(k)[1] for k in d.instruments)
    gone = [k for k in d.instruments if d.span(k)[1] < last_day]
    assert gone, "the data should contain delisted names"
    key = gone[0]
    last = d.span(key)[1]
    assert key in Guard(d, ny(last, "09:30")).universe()
    later = cal.next_trading_day(cal.next_trading_day(last))
    assert key not in Guard(d, ny(later, "09:30")).universe()


def test_series_are_visible_from_their_known_time(small_data, day):
    gen = RealisedVolatility()
    feats = MarketData(NASDAQ, series=gen.generate(small_data, {"window": 3}))
    data = small_data.combine(feats)
    key = small_data.instruments[0]
    name = gen.series_name({"window": 3})
    before = Guard(data, ny(day, "15:59")).series(name, key)
    after = Guard(data, ny(day, "16:00")).series(name, key)
    assert len(after) == len(before) + 1
    assert after.index[-1] == pd.Timestamp(ny(day, "16:00")).tz_convert("UTC")
    with pytest.raises(ValueError):
        Guard(data, ny(day, "16:00")).series(name)  # per instrument: must say which


# ---- store ----------------------------------------------------------------------------
def test_store_round_trip_and_catalogue(tmp_path, small_data):
    store = BarStore(tmp_path)
    info = DatasetInfo("ds-1", "Small", DataKind.CORE, SourceSpec("synthetic_stocks", {"seed": 3}))
    info = store.write(info, small_data)
    assert info.instruments == small_data.instruments and info.version and info.size_bytes > 0
    assert info.start.tzinfo is not None
    store.save_catalogue([info])
    again = store.catalogue()[0]
    assert again == info
    opened = store.open("ds-1")
    key = small_data.instruments[0]
    pd.testing.assert_frame_equal(opened.minute(key), small_data.minute(key), check_freq=False)
    assert opened.daily(key)["end"].iloc[-1] == small_data.daily(key)["end"].iloc[-1]
    store.delete("ds-1")
    assert store.size("ds-1") == 0


def test_info_serialises(small_data):
    info = DatasetInfo("x", "X", DataKind.GENERATED, SourceSpec("realised_vol", {"window": 5}),
                       frequency=Frequency.DAILY, start=datetime(2024, 1, 2, tzinfo=timezone.utc), inputs=["a"])
    assert info_from_dict(info_to_dict(info)) == info


# ---- sources ------------------------------------------------------------------------------
def test_sources_register_once():
    reg = Registry()
    register_sources(reg)
    register_sources(reg)
    names = [e.name for e in reg.entries(Library.DATA_SOURCES)]
    assert {"synthetic_stocks", "synthetic_futures", "file_import", "polygon", "databento"} <= set(names)
    with pytest.raises(NotImplementedError):
        reg.get(Library.DATA_SOURCES, "polygon").load(SourceSpec("polygon"))


def test_synthetic_stocks_are_reproducible_and_have_no_edge_by_default():
    src = SyntheticStocks()
    a = src.load(src.spec(n_symbols=40, n_days=60, seed=5, delist_frac=0.0))
    b = src.load(src.spec(n_symbols=40, n_days=60, seed=5, delist_frac=0.0))
    k = a.instruments[0]
    pd.testing.assert_frame_equal(a.minute(k), b.minute(k))

    def gap_vs_day(data):
        xs, ys = [], []
        for key in data.instruments:
            d = data.daily(key)
            prev = d["close"].shift()
            xs += list(np.log(d["open"] / prev).iloc[1:])
            ys += list(np.log(d["close"] / d["open"]).iloc[1:])
        return np.corrcoef(xs, ys)[0, 1]

    planted = src.load(src.spec(n_symbols=40, n_days=60, seed=5, delist_frac=0.0, gap_momentum=2.0))
    assert abs(gap_vs_day(a)) < 0.1
    assert gap_vs_day(planted) > 0.3


def test_synthetic_futures_trade_overnight():
    src = SyntheticFutures()
    data = src.load(src.spec(n_days=3))
    m = data.minute("cme:MNQ")
    local = m.index.tz_convert(NY)
    assert local[0].hour == 18  # the evening before the first day
    assert ((m["close"] / 0.25) % 1 == 0).all()
    assert len(data.daily("cme:MNQ")) == 3
    assert data.instrument_specs["cme:MNQ"].multiplier == 2.0


def test_file_import_reads_minute_daily_and_complementary(tmp_path):
    d = date(2025, 3, 3)
    idx = pd.date_range(ny(d, "09:30").replace(tzinfo=None), periods=30, freq="1min")
    pd.DataFrame({"Time": idx, "Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}) \
        .to_csv(tmp_path / "aapl.csv", index=False)
    pd.DataFrame({"date": ["2025-03-03", "2025-03-04"], "open": 1, "high": 2, "low": 0.5, "close": 1.5}) \
        .to_parquet(tmp_path / "msft.parquet")
    pd.DataFrame({"date": ["2025-03-03", "2025-03-03"], "symbol": ["aapl", "msft"], "score": [0.2, -0.1]}) \
        .to_csv(tmp_path / "sentiment.csv", index=False)
    src = FileImport()
    core = src.load(src.spec(paths=f"{tmp_path / 'aapl.csv'};{tmp_path / 'msft.parquet'}"))
    assert core.minute("xnas:AAPL").index[0] == pd.Timestamp("2025-03-03 14:30", tz="UTC")  # naive = New York
    assert len(core.daily("xnas:MSFT")) == 2 and not core.has_minutes("xnas:MSFT")
    comp = src.load(src.spec(paths=str(tmp_path / "sentiment.csv"), kind="complementary"))
    s = comp.series("sentiment")
    assert list(s.columns) == ["xnas:AAPL", "xnas:MSFT"]
    assert s.index[0] == pd.Timestamp("2025-03-03 21:00", tz="UTC")  # date-only values are known at the close
    v = Guard(comp, ny(d, "15:00"))
    assert v.series("sentiment", "xnas:AAPL").empty


def test_datasets_save_in_a_fresh_process_with_qt_loaded(tmp_path):
    """Regression: on Python 3.15 with Qt loaded first, pyarrow's thread pool was an
    unresolved lazy import and adding a dataset failed with "'lazy_import' object is not
    callable". Run in a clean process, as the app does, so nothing has resolved it yet."""
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(f"""
        import threading
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from titanium.app.workspace import Workspace
        ws = Workspace(data_root={str(tmp_path)!r})
        errors = []
        def job():
            try:
                for source in ("synthetic_futures", "synthetic_stocks"):
                    ws.datasets.build(source, {{"n_days": 5}})
            except Exception as e:
                errors.append(repr(e))
        t = threading.Thread(target=job)
        t.start(); t.join()
        print(errors or "ok")
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180,
                         env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"})
    assert out.stdout.strip().endswith("ok"), out.stdout + out.stderr


def test_sample_datasets_are_marked_saved_and_removed_together(tmp_path):
    from titanium.app.samples import add_samples, remove_samples
    from titanium.app.workspace import Workspace

    ws = Workspace(data_root=tmp_path)
    infos = add_samples(ws.datasets)
    assert [i.market for i in infos] == ["xnas", "cme"] and all(i.sample for i in infos)
    again = Workspace(data_root=tmp_path)
    assert all(i.sample for i in again.datasets.infos())
    ws.datasets.use(infos[0].id, "S1")
    assert remove_samples(ws.datasets) == [infos[1].id]  # one a strategy uses stays
    ws.datasets.release(infos[0].id, "S1")
    assert remove_samples(ws.datasets) == [infos[0].id] and not len(ws.datasets)


def test_closed_strategies_free_their_datasets_and_old_uses_are_forgotten(tmp_path):
    from titanium.app.workspace import Workspace
    from titanium.core.strategy import StrategyGraph

    ws = Workspace(data_root=tmp_path)
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 2, "n_days": 5})
    ws.strategies.put("S1", StrategyGraph("S1", "Gap fade", settings={"datasets": [info.id]}))
    assert ws.datasets.used_by(info.id) == ["S1"]
    # the next start has no strategies open, so nothing holds the dataset (older versions kept "S1")
    assert Workspace(data_root=tmp_path).datasets.used_by(info.id) == []
    ws.strategies.remove("S1")  # the tab closed
    assert ws.datasets.used_by(info.id) == []
    ws.datasets.remove(info.id)
    assert not len(Workspace(data_root=tmp_path).datasets)


def test_half_made_datasets_are_swept_and_locked_files_never_keep_one(tmp_path, monkeypatch):
    from titanium.app.workspace import Workspace
    from titanium.core.bars import BarStore

    ws = Workspace(data_root=tmp_path)
    info = ws.datasets.add("synthetic_stocks", {"n_symbols": 2, "n_days": 5})
    # a dataset that failed half way: files on disk, not in the catalogue
    broken = tmp_path / "synthetic-stocks-dead01" / "minute"
    broken.mkdir(parents=True)
    (broken / "x.parquet").write_bytes(b"half")
    (tmp_path / "my notes").mkdir()  # not a dataset folder: left alone
    again = Workspace(data_root=tmp_path)
    assert again.datasets.leftovers == ["synthetic-stocks-dead01"]
    assert not (tmp_path / "synthetic-stocks-dead01").exists() and (tmp_path / "my notes").exists()
    assert info.id in again.datasets
    # a file that can't be deleted (open in another program) doesn't keep the dataset listed

    def locked(self, dataset_id):
        raise PermissionError("the file is open in another program")

    monkeypatch.setattr(BarStore, "delete", locked)
    again.datasets.remove(info.id)
    assert info.id not in again.datasets
    monkeypatch.undo()
    third = Workspace(data_root=tmp_path)
    assert not len(third.datasets) and third.datasets.leftovers  # and the next start deletes its files


def test_file_import_keeps_dates_of_utc_stamped_daily_bars(tmp_path):
    """A date names a session. Daily bars stamped at midnight UTC (or read with the time zone set to
    UTC) used to land on the day before: Monday's prices on a Sunday, and each day's close visible a
    day early."""
    days = pd.bdate_range("2024-03-04", periods=5)
    px = np.arange(5) * 1.0 + 100
    rows = {"open": px, "high": px + 0.5, "low": px - 0.5, "close": px, "volume": 1}
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), **rows}).to_csv(tmp_path / "AAA.csv", index=False)
    pd.DataFrame({"date": days.tz_localize("UTC").strftime("%Y-%m-%dT%H:%M:%S%z"), **rows}).to_csv(
        tmp_path / "BBB.csv", index=False)
    news = tmp_path / "news"
    news.mkdir()
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "value": px}).to_csv(news / "mood.csv", index=False)
    src = FileImport()
    want = [d.date() for d in days]
    for tz in ("", "UTC"):
        md = src.load(src.spec(paths=f"{tmp_path / 'AAA.csv'};{tmp_path / 'BBB.csv'}", timezone=tz))
        for key in ("xnas:AAA", "xnas:BBB"):
            d = md.daily(key)
            assert [i.date() for i in d.index] == want, (tz, key)
            assert list(d["close"]) == list(px)
        md = src.load(src.spec(paths=str(news / "mood.csv"), kind="complementary", timezone=tz))
        known = md.series("mood").index.tz_convert(NASDAQ.tz)
        assert [t.date() for t in known] == want and all(t.hour == 16 for t in known), tz



def test_file_import_keeps_the_hour_the_clocks_go_back(tmp_path):
    """A futures file in local time repeats 01:00-01:59 when the clocks go back. Both passes used to
    collapse into one row with no time."""
    first = pd.date_range("2024-11-03 00:30", "2024-11-03 01:59", freq="1min")
    second = pd.date_range("2024-11-03 01:00", "2024-11-03 02:30", freq="1min")
    stamps = list(first.strftime("%Y-%m-%d %H:%M")) + list(second.strftime("%Y-%m-%d %H:%M"))
    px = np.arange(len(stamps)) + 1.0
    pd.DataFrame({"time": stamps, "open": px, "high": px, "low": px, "close": px, "volume": 1}).to_csv(
        tmp_path / "ES.csv", index=False)
    src = FileImport()
    md = src.load(src.spec(paths=str(tmp_path / "ES.csv"), market="cme"))
    m = md.minute("cme:ES")
    assert len(m) == len(stamps) and not m.index.isna().any()
    assert m.index.is_monotonic_increasing and (m.index.to_series().diff().dropna() == pd.Timedelta("1min")).all()



def test_file_import_reads_futures_on_a_futures_market(tmp_path):
    """Futures files imported into CME used to become stocks: cash paid the whole contract value, no
    contract size, and only the regular stock session traded."""
    idx = pd.date_range("2024-03-04 08:30", periods=30, freq="1min")
    px = np.arange(30) + 5000.0
    rows = {"time": idx.strftime("%Y-%m-%d %H:%M"), "open": px, "high": px, "low": px, "close": px, "volume": 1}
    for name in ("ESZ4", "MNQ", "XYZ"):
        pd.DataFrame(rows).to_csv(tmp_path / f"{name}.csv", index=False)
    src = FileImport()
    md = src.load(src.spec(paths=f"{tmp_path / 'ESZ4.csv'};{tmp_path / 'MNQ.csv'}", market="cme"))
    es, mnq = md.instrument_specs["cme:ESZ4"], md.instrument_specs["cme:MNQ"]
    assert es.kind.value == "future" and (es.multiplier, es.tick_size) == (50.0, 0.25)
    assert mnq.multiplier == 2.0
    with pytest.raises(ValueError, match="unknown futures contract"):
        src.load(src.spec(paths=str(tmp_path / "XYZ.csv"), market="cme"))
    xyz = src.load(src.spec(paths=str(tmp_path / "XYZ.csv"), market="cme", multiplier=10.0, tick_size=0.5))
    assert xyz.instrument_specs["cme:XYZ"].multiplier == 10.0
    stock = src.load(src.spec(paths=str(tmp_path / "XYZ.csv"), market="xnas"))
    assert stock.instrument_specs["xnas:XYZ"].kind.value == "stock"
