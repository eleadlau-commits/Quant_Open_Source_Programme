"""The data sources that ship with the app (``Library.DATA_SOURCES`` entries).

* ``synthetic_stocks``: random-walk Nasdaq minute bars with no edge by default,
  and an optional planted edge for testing the testers.
* ``synthetic_futures``: random-walk Globex-session minute bars for NQ/MNQ.
* ``file_import``: Parquet or CSV files (bars or complementary data).
* ``polygon``, ``databento``: downloads, not built yet (listed so the page can say so).

Each source has a ``params`` list (shown as the add form), ``describe`` (what the
dataset will be) and ``load`` (the :class:`~titanium.core.bars.MarketData`).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .bars import OHLCV, MarketData, check_minutes, check_series, daily_frame
from .data import DataKind, DatasetInfo, Frequency, Param, SourceSpec
from .instruments import Instrument, InstrumentKind
from .markets import CME_GLOBEX, MARKETS, NASDAQ, Market
from .plugins import Library, Registry


class Source:
    """Base for built-in sources: parameters with defaults, describe, load."""

    name = ""
    title = ""
    kind = DataKind.CORE
    doc = ""
    params: list[Param] = []
    available = True
    market: Market = NASDAQ

    def resolve(self, spec: SourceSpec | dict[str, Any] | None = None) -> dict[str, Any]:
        given = spec.params if isinstance(spec, SourceSpec) else (spec or {})
        unknown = set(given) - {p.name for p in self.params}
        if unknown:
            raise ValueError(f"{self.name}: unknown settings {sorted(unknown)}")
        return {p.name: given.get(p.name, p.default) for p in self.params}

    def spec(self, **params: Any) -> SourceSpec:
        return SourceSpec(self.name, self.resolve(params))

    def default_name(self, params: dict[str, Any]) -> str:
        return self.title

    def describe(self, spec: SourceSpec) -> DatasetInfo:
        params = self.resolve(spec)
        return DatasetInfo(id="", name=self.default_name(params), kind=self.kind,
                           source=SourceSpec(self.name, params), market=self.market.id,
                           frequency=Frequency.MINUTE if self.kind is DataKind.CORE else None,
                           notes=self.doc)

    def load(self, spec: SourceSpec) -> MarketData:  # pragma: no cover - overridden
        raise NotImplementedError


def _local_minutes(day: date, minutes: np.ndarray, tz) -> pd.DatetimeIndex:
    """Minute-of-day offsets (may be negative: the evening before) on ``day``, local time -> UTC."""
    base = np.datetime64(day.isoformat(), "m")
    naive = pd.DatetimeIndex((base + minutes.astype("timedelta64[m]")).astype("datetime64[ns]"))
    return naive.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")


class SyntheticStocks(Source):
    """Random-walk minute bars with pre-market, gaps, penny stocks, IPOs and delistings.

    By default there is **no edge**: overnight gaps say nothing about the rest of the
    day, so an honest evaluator should fail any gap strategy run on it. ``gap_momentum``
    > 0 plants a known edge (stocks that gap up keep drifting up), which it should find.
    """

    name = "synthetic_stocks"
    title = "Synthetic stocks"
    doc = "Random-walk Nasdaq minute bars. No edge unless you plant one."
    params = [
        Param("n_symbols", "int", 20, "Stocks", "How many tickers to make.", minimum=1, maximum=500),
        Param("n_days", "int", 60, "Trading days", "Length of the history.", minimum=5, maximum=2500),
        Param("start", "date", "2024-01-02", "First day", "Starts on the first trading day from here."),
        Param("seed", "int", 7, "Seed", "Same seed, same data.", minimum=0),
        Param("gap_momentum", "float", 0.0, "Planted edge",
              "Intraday drift per unit of overnight gap. 0 means no edge.", minimum=0.0, maximum=5.0),
        Param("delist_frac", "float", 0.1, "Delisting share", "Share of names that crash and delist.",
              minimum=0.0, maximum=1.0),
    ]

    def default_name(self, p):
        edge = f", planted edge {p['gap_momentum']:g}" if p["gap_momentum"] else ""
        return f"Synthetic stocks ({p['n_symbols']} names, {p['n_days']} days{edge})"

    def load(self, spec: SourceSpec) -> MarketData:
        p = self.resolve(spec)
        n_symbols, n_days, seed = int(p["n_symbols"]), int(p["n_days"]), int(p["seed"])
        gap_momentum, delist_frac = float(p["gap_momentum"]), float(p["delist_frac"])
        mk = self.market
        cal = mk.calendar
        start = date.fromisoformat(str(p["start"]))
        days = cal.trading_days(start, start + timedelta(days=int(n_days * 1.6) + 15))[:n_days]
        rng = np.random.default_rng(seed)
        pre = np.arange(9 * 60, 9 * 60 + 30)  # pre-market from 09:00 keeps the data small
        n_pre = len(pre)
        day_shape = []
        for d in days:
            close = cal.local_close(d)
            reg = np.arange(9 * 60 + 30, close.hour * 60 + close.minute)
            day_shape.append((np.concatenate([pre, reg]), _local_minutes(d, np.concatenate([pre, reg]), mk.tz)))

        minute: dict[str, pd.DataFrame] = {}
        specs: dict[str, Instrument] = {}
        for k in range(n_symbols):
            sym = f"SYN{k:03d}"
            price = float(np.exp(rng.uniform(np.log(1.5), np.log(250))))
            ann_vol = float(np.exp(rng.normal(np.log(0.45), 0.4)))
            base_shares = float(np.exp(rng.normal(np.log(3e5), 1.2)))
            d_vol = ann_vol / np.sqrt(252)
            m_vol = d_vol * 0.8 / np.sqrt(390)
            gap_vol = d_vol * 0.6
            first = int(rng.integers(0, max(1, n_days // 3))) if rng.random() < 0.2 else 0  # some list later
            last = n_days
            crash = rng.random() < delist_frac
            if crash and first + 30 < n_days:
                last = int(rng.integers(first + 30, n_days))
            idx_parts, rows = [], []
            for di in range(first, last):
                mins, idx = day_shape[di]
                n_reg = len(mins) - n_pre
                u_shape = 1.0 + 2.0 * (np.linspace(-1, 1, n_reg) ** 2)
                gap = gap_vol * rng.standard_t(3)
                if crash and last < n_days and di > last - 10:
                    gap -= 0.08
                prev = price
                target = prev * np.exp(gap)
                pm = prev * np.exp(np.linspace(0, gap, n_pre) + rng.normal(0, gap_vol * 0.15, n_pre))
                pm[-1] = target
                r = rng.normal(gap_momentum * gap / n_reg, m_vol, n_reg)
                closes = np.concatenate([pm, target * np.exp(np.cumsum(r))])
                opens = np.concatenate([[prev], closes[:-1]])
                spread = np.abs(rng.normal(0, m_vol, len(mins))) * closes
                vol = np.concatenate([base_shares * 0.002 * rng.random(n_pre),
                                      base_shares / 390 * u_shape * rng.lognormal(0, 0.5, n_reg)])
                price = float(closes[-1])
                idx_parts.append(idx)
                rows.append(np.column_stack([opens, np.maximum(opens, closes) + spread,
                                             np.minimum(opens, closes) - spread, closes, np.round(vol)]))
            if not rows:
                continue
            key = f"{mk.id}:{sym}"
            minute[key] = check_minutes(pd.DataFrame(np.vstack(rows), index=idx_parts[0].append(idx_parts[1:]),
                                                     columns=OHLCV))
            specs[key] = Instrument(sym, InstrumentKind.STOCK, mk.id, name=f"Synthetic stock {k}")
        return MarketData(mk, minute, instruments=specs, name=self.default_name(p))


class SyntheticFutures(Source):
    """Random-walk Globex minute bars for a Nasdaq-100 futures contract (NQ / MNQ).

    18:00 the evening before to 17:00, with a quiet overnight, a burst at the 09:30 open
    and volatility clustering. No edge by default; ``orb_momentum`` plants an opening
    range breakout edge and ``trend_strength`` a persistent daily drift.
    """

    name = "synthetic_futures"
    title = "Synthetic futures"
    doc = "Random-walk Nasdaq futures (MNQ) minute bars, nearly round the clock. No edge unless planted."
    market = CME_GLOBEX
    params = [
        Param("symbol", "choice", "MNQ", "Contract", "Prices are the same for NQ and MNQ.", choices=("MNQ", "NQ")),
        Param("n_days", "int", 60, "Trading days", "Length of the history.", minimum=5, maximum=2500),
        Param("start", "date", "2024-01-02", "First day", "Starts on the first trading day from here."),
        Param("seed", "int", 11, "Seed", "Same seed, same data.", minimum=0),
        Param("price", "float", 18000.0, "Starting level", minimum=1.0),
        Param("ann_vol", "float", 0.22, "Yearly volatility", minimum=0.01, maximum=2.0),
        Param("orb_momentum", "float", 0.0, "Planted breakout edge",
              "Drift after 09:45 per unit of the opening move. 0 means no edge.", minimum=0.0, maximum=5.0),
        Param("trend_strength", "float", 0.0, "Planted trend",
              "Size of a slowly changing daily drift, in daily volatilities. 0 means none.", minimum=0.0, maximum=5.0),
    ]
    TICK = 0.25

    def default_name(self, p):
        return f"Synthetic {p['symbol']} ({p['n_days']} days)"

    @staticmethod
    def _profile(mins: np.ndarray) -> np.ndarray:
        v = np.full(len(mins), 0.35)
        v[(mins >= 3 * 60) & (mins < 9 * 60 + 30)] = 0.6
        v[(mins >= 8 * 60 + 30) & (mins < 8 * 60 + 35)] = 1.5
        rth = (mins >= 9 * 60 + 30) & (mins < 16 * 60)
        t = (mins[rth] - (9 * 60 + 30)) / 390.0
        v[rth] = 1.0 + 1.6 * np.exp(-t / 0.08) + 0.4 * t ** 4
        v[(mins >= 16 * 60) & (mins < 17 * 60)] = 0.5
        return v

    def load(self, spec: SourceSpec) -> MarketData:
        p = self.resolve(spec)
        mk = self.market
        start = date.fromisoformat(str(p["start"]))
        n_days = int(p["n_days"])
        days = mk.calendar.trading_days(start, start + timedelta(days=int(n_days * 1.6) + 15))[:n_days]
        rng = np.random.default_rng(int(p["seed"]))
        offs = np.r_[np.arange(18 * 60, 24 * 60) - 24 * 60, np.arange(0, 17 * 60)]
        mins = offs % (24 * 60)
        prof = self._profile(mins)
        prof = prof / np.sqrt(np.sum(prof ** 2))
        d_vol = float(p["ann_vol"]) / np.sqrt(252)
        i_open = int(np.flatnonzero(mins == 9 * 60 + 30)[0])
        i_box = int(np.flatnonzero(mins == 9 * 60 + 45)[0])
        i_close = int(np.flatnonzero(mins == 16 * 60)[0])
        trend, orb = float(p["trend_strength"]), float(p["orb_momentum"])
        log_v, drift, price = 0.0, 0.0, float(p["price"])
        idx_parts, rows = [], []
        for d in days:
            log_v = 0.9 * log_v + rng.normal(0, 0.25)
            dv = d_vol * np.exp(log_v - 0.25 ** 2 / (2 * (1 - 0.81)))
            drift = 0.98 * drift + rng.normal(0, trend * np.sqrt(1 - 0.98 ** 2))
            sig = dv * prof
            r = rng.standard_t(5, len(mins)) * sig * np.sqrt(3 / 5) + drift * dv / len(mins)
            if orb:
                r[i_box:i_close] += orb * float(np.sum(r[i_open:i_box])) / (i_close - i_box)
            closes = price * np.exp(np.cumsum(r))
            opens = np.r_[price, closes[:-1]]
            wick = np.abs(rng.normal(0, 1, len(mins))) * sig * closes * 0.6
            highs = np.maximum(opens, closes) + wick
            lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 1, len(mins))) * sig * closes * 0.6
            o, h, l, c = (np.round(x / self.TICK) * self.TICK for x in (opens, highs, lows, closes))
            h, l = np.maximum.reduce([h, o, c]), np.minimum.reduce([l, o, c])
            vol = np.round(200 * prof / prof.mean() * rng.lognormal(0, 0.4, len(mins)))
            price = float(c[-1])
            idx_parts.append(_local_minutes(d, offs, mk.tz))
            rows.append(np.column_stack([o, h, l, c, vol]))
        sym = str(p["symbol"])
        key = f"{mk.id}:{sym}"
        df = check_minutes(pd.DataFrame(np.vstack(rows), index=idx_parts[0].append(idx_parts[1:]), columns=OHLCV))
        spec_ = Instrument(sym, InstrumentKind.FUTURE, mk.id, tick_size=self.TICK,
                           multiplier=2.0 if sym == "MNQ" else 20.0, name=f"Synthetic {sym}")
        return MarketData(mk, {key: df}, instruments={key: spec_}, name=self.default_name(p))


TIME_COLUMNS = ("timestamp", "time", "datetime", "date", "ts", "start", "known")


class FileImport(Source):
    """Parquet or CSV files: price bars (core) or values known over time (complementary).

    One file per instrument (named after it, e.g. ``AAPL.csv``) or per series. Timestamps
    without a time zone are read in the market's local time. Bars are read as minute or
    daily bars from their spacing. Date-only complementary values count as known at that
    day's close, so they cannot leak into the same day's decisions.
    """

    name = "file_import"
    title = "Import files"
    doc = "Parquet or CSV files on this computer, copied into the data folder."
    params = [
        Param("paths", "path", "", "Files", "One or more files, separated by ';', or a folder."),
        Param("kind", "choice", "core", "What the files hold",
              "core: price bars. complementary: values known over time.", choices=("core", "complementary")),
        Param("market", "choice", "xnas", "Market", "Calendar and time zone.", choices=tuple(MARKETS)),
        Param("timezone", "str", "", "Time zone of naive timestamps", "Empty means the market's time zone."),
        Param("name", "str", "", "Dataset name", "Empty means the file or folder name."),
    ]

    @staticmethod
    def files(paths: str | list[str]) -> list[Path]:
        items = paths if isinstance(paths, list) else [x for x in str(paths).split(";") if x.strip()]
        out: list[Path] = []
        for item in items:
            path = Path(str(item).strip()).expanduser()
            if path.is_dir():
                out += sorted(f for f in path.iterdir() if f.suffix.lower() in (".csv", ".parquet", ".pq"))
            elif path.exists():
                out.append(path)
            else:
                raise FileNotFoundError(f"no such file: {path}")
        if not out:
            raise ValueError("no Parquet or CSV files to import")
        return out

    def default_name(self, p):
        if p.get("name"):
            return str(p["name"])
        try:
            files = self.files(p["paths"])
        except (FileNotFoundError, ValueError):
            return "Imported data"
        return files[0].stem if len(files) == 1 else f"{files[0].parent.name} ({len(files)} files)"

    def describe(self, spec: SourceSpec) -> DatasetInfo:
        info = super().describe(spec)
        p = self.resolve(spec)
        info.kind = DataKind(p["kind"])
        info.market = p["market"]
        info.frequency = None
        return info

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if path.suffix.lower() in (".parquet", ".pq"):
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
        df.columns = [str(c).strip().lower() for c in df.columns]
        if not isinstance(df.index, pd.DatetimeIndex):
            col = next((c for c in TIME_COLUMNS if c in df.columns), None)
            if col is None:
                raise ValueError(f"{path.name}: no time column (expected one of {', '.join(TIME_COLUMNS)})")
            df = df.set_index(col)
        return df

    @staticmethod
    def _times(index, tz: str) -> tuple[pd.DatetimeIndex, bool]:
        """Parsed timestamps in UTC, and whether they were dates only."""
        if isinstance(index, pd.DatetimeIndex):
            idx = index
        else:
            sample = pd.Index(index).astype(str)
            idx = pd.DatetimeIndex(pd.to_datetime(sample, utc=False, format="mixed"))
        date_only = bool(len(idx)) and idx.tz is None and bool((idx == idx.normalize()).all())
        if idx.tz is None:
            idx = idx.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
        return idx.tz_convert("UTC"), date_only

    def load(self, spec: SourceSpec) -> MarketData:
        p = self.resolve(spec)
        mk = MARKETS[p["market"]]
        tz = p["timezone"] or mk.timezone
        minute, daily, series, specs = {}, {}, {}, {}
        for path in self.files(p["paths"]):
            df = self._read(path)
            if p["kind"] == "core":
                missing = [c for c in ("open", "high", "low", "close") if c not in df.columns]
                if missing:
                    raise ValueError(f"{path.name}: price bars need columns {missing}")
                if "volume" not in df.columns:
                    df["volume"] = 0.0
                sym = path.stem.upper()
                key = f"{mk.id}:{sym}"
                idx, date_only = self._times(df.index, tz)
                step = pd.Series(idx).diff().median() if len(idx) > 1 else pd.Timedelta(days=1)
                if date_only or step >= pd.Timedelta(hours=12):
                    local = idx.tz_convert(mk.tz).tz_localize(None).normalize()
                    daily[key] = daily_frame(df.set_axis(local), mk)
                else:
                    minute[key] = check_minutes(df.set_axis(idx), path.name)
                specs[key] = Instrument(sym, InstrumentKind.STOCK, mk.id)
            else:
                idx, date_only = self._times(df.index, tz)
                if date_only:  # known at that day's close, never earlier
                    local_days = idx.tz_convert(mk.tz).date
                    idx = pd.DatetimeIndex([mk.calendar.session_close(d) if mk.calendar.is_trading_day(d)
                                            else datetime.combine(d, mk.session().end, mk.tz)
                                            for d in local_days]).tz_convert("UTC")
                df = df.set_axis(idx)
                values = df.select_dtypes("number")
                if "symbol" in df.columns and len(values.columns) == 1:  # long format: one row per symbol
                    keys = mk.id + ":" + df["symbol"].astype(str).str.upper()
                    frame = values.assign(key=keys.values).pivot_table(index=values.index, columns="key",
                                                                       values=values.columns[0])
                    frame.columns.name = None
                else:
                    frame = values.set_axis(["value"], axis=1) if len(values.columns) == 1 else values
                series[path.stem.lower()] = check_series(frame, path.name)
        return MarketData(mk, minute, daily, series, specs, name=self.default_name(p))


class Download(Source):
    """A data vendor download. Not built yet: listed so the Data page can show it is coming."""

    available = False
    params = [
        Param("symbols", "str", "QQQ", "Symbols", "Comma separated."),
        Param("start", "date", "2024-01-02", "First day"),
        Param("end", "date", "2024-03-29", "Last day"),
        Param("api_key", "str", "", "API key", "Stored only on this computer."),
    ]

    def load(self, spec: SourceSpec) -> MarketData:
        raise NotImplementedError(f"Downloading from {self.title} is not built yet.")


class Polygon(Download):
    name = "polygon"
    title = "Polygon"
    doc = "US stock minute bars from Polygon.io. Coming later."


class Databento(Download):
    name = "databento"
    title = "Databento"
    doc = "US stock and futures minute bars from Databento. Coming later."


BUILTIN_SOURCES: tuple[type[Source], ...] = (SyntheticStocks, SyntheticFutures, FileImport, Polygon, Databento)


def register_sources(registry: Registry) -> None:
    """Add the built-in sources (skipping names a plugin already provides)."""
    have = {e.name for e in registry.entries(Library.DATA_SOURCES)}
    for cls in BUILTIN_SOURCES:
        if cls.name not in have:
            registry.add(Library.DATA_SOURCES, cls.name, cls(), doc=cls.doc)


__all__ = ["Source", "SyntheticStocks", "SyntheticFutures", "FileImport", "Polygon", "Databento",
           "register_sources"]
