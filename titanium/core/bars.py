"""Bars and the bar store.

Shapes (all timestamps timezone-aware UTC):

* **minute bars**: a DataFrame indexed by the bar's *start* (``start``), columns
  open, high, low, close, volume. Any session (pre, regular, post, overnight).
* **daily bars**: one row per trading day, derived from the *regular-session*
  minutes. Indexed by the session date (``session``, a plain date label) with the
  usual columns plus ``end``: the UTC time the session closed (13:00 New York on
  early-close days). A daily bar is knowable from ``end`` onwards.
* **series** (complementary and generated data): a DataFrame indexed by the time
  each value became known (``known``), one column per instrument key, or a single
  ``value`` column for market-wide data.

On disk a dataset is a folder of Parquet files; ``catalogue.json`` beside them
lists every dataset's :class:`~titanium.core.data.DatasetInfo`.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, fields
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .data import DataKind, DatasetInfo, Frequency, SourceSpec
from .instruments import Instrument, InstrumentKind
from .markets import MARKETS, Market

OHLCV = ["open", "high", "low", "close", "volume"]
UTC = timezone.utc


def check_minutes(df: pd.DataFrame, what: str = "minute bars") -> pd.DataFrame:
    """Validate (and tidy) a minute-bar frame: aware UTC index, sorted, unique, OHLCV columns."""
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError(f"{what}: the index must be timezone-aware timestamps")
    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        raise ValueError(f"{what}: missing columns {missing}")
    out = df[OHLCV].astype(float)
    out.index = df.index.tz_convert(UTC)
    out.index.name = "start"
    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
    if out.index.has_duplicates:
        out = out[~out.index.duplicated(keep="last")]
    return out


def check_series(df: pd.DataFrame | pd.Series, name: str = "series") -> pd.DataFrame:
    if isinstance(df, pd.Series):
        df = df.to_frame("value")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise ValueError(f"{name}: the index must be the timezone-aware time each value became known")
    out = df.copy()
    out.index = df.index.tz_convert(UTC)
    out.index.name = "known"
    return out.sort_index()


def daily_from_minutes(minutes: pd.DataFrame, market: Market) -> pd.DataFrame:
    """Daily bars from the regular-session minutes of each trading day (early closes respected)."""
    cols = OHLCV + ["end"]
    if minutes.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="session"))
    cal = market.calendar
    start = minutes.index
    local_day = start.tz_convert(market.tz).normalize().tz_localize(None)
    days = pd.DatetimeIndex(local_day.unique())
    opens, closes, keep = {}, {}, []
    for d in days:
        day = d.date()
        if cal is not None and not cal.is_trading_day(day):
            continue
        if cal is not None and hasattr(cal, "session_open"):
            o, c = cal.session_open(day), cal.session_close(day)
        else:
            reg = market.session()
            o = datetime.combine(day, reg.start, market.tz).astimezone(UTC)
            c = datetime.combine(day, reg.end, market.tz).astimezone(UTC)
        opens[d], closes[d] = pd.Timestamp(o), pd.Timestamp(c)
        keep.append(d)
    if not keep:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="session"))
    o_arr = local_day.map(lambda d: opens.get(d, pd.NaT))
    c_arr = local_day.map(lambda d: closes.get(d, pd.NaT))
    o_arr = pd.DatetimeIndex(o_arr)
    c_arr = pd.DatetimeIndex(c_arr)
    one = pd.Timedelta(minutes=1)
    mask = np.asarray((start >= o_arr) & (start + one <= c_arr))
    reg = minutes[mask]
    if reg.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="session"))
    key = pd.DatetimeIndex(np.asarray(local_day)[mask])
    g = reg.groupby(key)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(),
    })
    out.index = pd.DatetimeIndex(out.index, name="session")
    out["end"] = [closes[d] for d in out.index]
    return out


def daily_frame(df: pd.DataFrame, market: Market) -> pd.DataFrame:
    """Tidy imported daily bars: index of session dates, ``end`` added from the calendar."""
    idx = df.index
    if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
        idx = idx.tz_convert(market.tz).tz_localize(None)
    idx = pd.DatetimeIndex(pd.to_datetime(idx)).normalize()
    out = df[OHLCV].astype(float).copy()
    out.index = pd.DatetimeIndex(idx, name="session")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    cal = market.calendar
    ends = []
    for d in out.index:
        day = d.date()
        if cal is not None and hasattr(cal, "session_close"):
            ends.append(pd.Timestamp(cal.session_close(day)))
        else:
            ends.append(pd.Timestamp(datetime.combine(day, market.session().end, market.tz)).tz_convert(UTC))
    out["end"] = pd.DatetimeIndex(ends)
    return out


Frame = pd.DataFrame | Callable[[], pd.DataFrame]


class MarketData:
    """The data of one or more datasets: minute and daily bars per instrument, and series.

    Frames may be given directly or as loaders (called once, on first use), so a
    dataset opened from disk reads only the instruments that are asked for.
    """

    def __init__(self, market: Market | str = "xnas", minute: dict[str, Frame] | None = None,
                 daily: dict[str, Frame] | None = None, series: dict[str, Frame] | None = None,
                 instruments: dict[str, Instrument] | None = None, name: str = "") -> None:
        self.market = MARKETS[market] if isinstance(market, str) else market
        self._minute: dict[str, Frame] = dict(minute or {})
        self._daily: dict[str, Frame] = dict(daily or {})
        self._series: dict[str, Frame] = dict(series or {})
        self.instrument_specs: dict[str, Instrument] = dict(instruments or {})
        self.name = name
        self._spans: dict[str, tuple[date, date] | None] = {}

    # ---- what is here -------------------------------------------------------
    @property
    def instruments(self) -> list[str]:
        return sorted(set(self._minute) | set(self._daily))

    @property
    def series_names(self) -> list[str]:
        return sorted(self._series)

    def has_minutes(self, key: str) -> bool:
        return key in self._minute

    # ---- frames -----------------------------------------------------------------
    @staticmethod
    def _resolve(store: dict[str, Frame], key: str) -> pd.DataFrame:
        obj = store[key]
        if callable(obj):
            obj = obj()
            store[key] = obj
        return obj

    def minute(self, key: str) -> pd.DataFrame:
        if key not in self._minute:
            if key in self._daily:
                return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([], tz=UTC, name="start"))
            raise KeyError(f"no instrument {key!r} in {self.name or 'this data'}")
        return self._resolve(self._minute, key)

    def daily(self, key: str) -> pd.DataFrame:
        if key not in self._daily:
            if key not in self._minute:
                raise KeyError(f"no instrument {key!r} in {self.name or 'this data'}")
            self._daily[key] = daily_from_minutes(self.minute(key), self.market)
        return self._resolve(self._daily, key)

    def series(self, name: str) -> pd.DataFrame:
        if name not in self._series:
            known = ", ".join(self.series_names) or "none"
            raise KeyError(f"no series {name!r} (known: {known})")
        return self._resolve(self._series, name)

    def span(self, key: str) -> tuple[date, date] | None:
        """First and last session the instrument traded (its listing and delisting)."""
        if key not in self._spans:
            d = self.daily(key)
            self._spans[key] = (d.index[0].date(), d.index[-1].date()) if len(d) else None
        return self._spans[key]

    # ---- combining ----------------------------------------------------------------
    def combine(self, *others: "MarketData") -> "MarketData":
        """One view over several datasets (e.g. prices plus news plus features)."""
        out = MarketData(self.market, self._minute, self._daily, self._series, self.instrument_specs, self.name)
        for o in others:
            for k, v in o._minute.items():
                out._minute.setdefault(k, v)
            for k, v in o._daily.items():
                out._daily.setdefault(k, v)
            for k, v in o._series.items():
                if k in out._series:
                    raise ValueError(f"two datasets both provide a series named {k!r}")
                out._series[k] = v
            for k, v in o.instrument_specs.items():
                out.instrument_specs.setdefault(k, v)
        return out

    def frames(self) -> Iterable[tuple[str, str, pd.DataFrame]]:
        """(section, name, frame) for every stored frame: section is minute, daily or series."""
        for k in sorted(self._minute):
            yield "minute", k, self.minute(k)
        for k in sorted(self._daily):
            if k not in self._minute:
                yield "daily", k, self.daily(k)
        for k in sorted(self._series):
            yield "series", k, self.series(k)


# ---- (de)serialising DatasetInfo -------------------------------------------------
def info_to_dict(info: DatasetInfo) -> dict[str, Any]:
    out = asdict(info)
    for k, v in out.items():
        if isinstance(v, Enum):
            out[k] = v.value
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
    out["source"] = {"plugin": info.source.plugin, "params": _jsonable(info.source.params)}
    return out


def info_from_dict(d: dict[str, Any]) -> DatasetInfo:
    known = {f.name for f in fields(DatasetInfo)}
    d = {k: v for k, v in d.items() if k in known}  # ignore keys from newer versions
    d["kind"] = DataKind(d["kind"])
    d["source"] = SourceSpec(d["source"]["plugin"], d["source"].get("params", {}))
    if d.get("frequency"):
        d["frequency"] = Frequency(d["frequency"])
    for k in ("start", "end", "created"):
        if d.get(k):
            d[k] = datetime.fromisoformat(d[k])
    return DatasetInfo(**d)


def _jsonable(params: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in params.items():
        if isinstance(v, (date, datetime)):
            v = v.isoformat()
        elif isinstance(v, Path):
            v = str(v)
        elif isinstance(v, np.generic):
            v = v.item()
        out[k] = v
    return out


def _file_key(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


class BarStore:
    """Datasets on disk: ``<root>/<dataset id>/{minute,daily,series}/*.parquet`` plus ``catalogue.json``."""

    CATALOGUE = "catalogue.json"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # ---- catalogue ----------------------------------------------------------------
    def catalogue(self) -> list[DatasetInfo]:
        path = self.root / self.CATALOGUE
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [info_from_dict(d) for d in data.get("datasets", [])]

    def save_catalogue(self, infos: Iterable[DatasetInfo]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / self.CATALOGUE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "datasets": [info_to_dict(i) for i in infos]}, indent=2),
                       encoding="utf-8")
        tmp.replace(path)

    # ---- datasets ---------------------------------------------------------------------
    def folder(self, dataset_id: str) -> Path:
        return self.root / _file_key(dataset_id)

    def write(self, info: DatasetInfo, data: MarketData) -> DatasetInfo:
        """Write a dataset's frames and fill in what the catalogue records about them."""
        folder = self.folder(info.id)
        if folder.exists():
            shutil.rmtree(folder)
        digest = hashlib.sha1()
        index: dict[str, dict[str, str]] = {"minute": {}, "daily": {}, "series": {}}
        starts, ends, cols = [], [], set()
        for section, name, frame in data.frames():
            sub = folder / section
            sub.mkdir(parents=True, exist_ok=True)
            fname = _file_key(name) + ".parquet"
            frame.to_parquet(sub / fname)
            index[section][name] = fname
            digest.update(section.encode() + name.encode())
            digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
            if len(frame):
                if section == "minute":
                    starts.append(frame.index[0])
                    ends.append(frame.index[-1] + pd.Timedelta(minutes=1))
                elif section == "daily":
                    starts.append(pd.Timestamp(frame.index[0]).tz_localize(data.market.tz).tz_convert(UTC))
                    ends.append(frame["end"].iloc[-1])
                else:
                    starts.append(frame.index[0])
                    ends.append(frame.index[-1])
                if section != "series":
                    cols.update(c for c in frame.columns if c != "end")
        meta = {
            "market": data.market.id,
            "files": index,
            "instruments": {k: {**asdict(v), "kind": v.kind.value} for k, v in data.instrument_specs.items()},
        }
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        info.storage = str(folder)
        info.version = digest.hexdigest()[:12]
        info.market = data.market.id
        info.instruments = data.instruments
        info.series = data.series_names
        if not info.fields:
            info.fields = [c for c in OHLCV if c in cols] if cols else []
        if starts:
            info.start = min(starts).to_pydatetime()
            info.end = max(ends).to_pydatetime()
        info.size_bytes = self.size(info.id)
        return info

    def open(self, dataset_id: str, name: str = "") -> MarketData:
        """A dataset from disk; files are read when first asked for."""
        folder = self.folder(dataset_id)
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        files = meta["files"]

        def loader(path: Path) -> Callable[[], pd.DataFrame]:
            return lambda: pd.read_parquet(path)

        minute = {k: loader(folder / "minute" / f) for k, f in files.get("minute", {}).items()}
        daily = {k: loader(folder / "daily" / f) for k, f in files.get("daily", {}).items()}
        series = {k: loader(folder / "series" / f) for k, f in files.get("series", {}).items()}
        specs = {}
        for k, v in meta.get("instruments", {}).items():
            v = dict(v)
            v["kind"] = InstrumentKind(v["kind"])
            specs[k] = Instrument(**v)
        return MarketData(meta.get("market", "xnas"), minute, daily, series, specs, name or dataset_id)

    def delete(self, dataset_id: str) -> None:
        folder = self.folder(dataset_id)
        if folder.exists():
            shutil.rmtree(folder)

    def size(self, dataset_id: str) -> int:
        folder = self.folder(dataset_id)
        if not folder.exists():
            return 0
        return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
