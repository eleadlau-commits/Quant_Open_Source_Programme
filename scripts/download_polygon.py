"""Download US minute bars (incl. pre-market and delisted tickers) from Polygon
into the local Parquet cache used by the ``parquet`` data plugin.

    export POLYGON_API_KEY=...
    python scripts/download_polygon.py --start 2022-01-01 --end 2024-12-31 --out data

Strategy for keeping the download affordable:

1. For every trading day, fetch the *grouped daily* bars (one request per day,
   includes tickers that later delisted). This gives price and dollar volume
   for the universe filter.
2. Keep tickers that pass the filter (price, dollar volume) on at least one
   week-start day.
3. Download minute bars (extended hours) only for those tickers.

Prices are split-adjusted (``adjusted=true``); otherwise a split shows up as a
huge fake gap and lands in the top 5.

STATUS: written against Polygon's public REST docs but not yet run with a real
key. Expect to adjust pagination / rate limiting on first use.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://api.polygon.io"


def get(path: str, key: str, **params) -> dict:
    params["apiKey"] = key
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt * 6)
                continue
            raise
    raise RuntimeError(f"rate-limited too often: {path}")


def grouped_daily(day: str, key: str) -> pd.DataFrame:
    js = get(f"/v2/aggs/grouped/locale/us/market/stocks/{day}", key, adjusted="true")
    df = pd.DataFrame(js.get("results") or [])
    if df.empty:
        return df
    df = df.rename(columns={"T": "ticker", "c": "close", "v": "volume"})
    df["date"] = day
    df["dollar_volume"] = df["close"] * df["volume"]
    return df[["date", "ticker", "close", "volume", "dollar_volume"]]


def minute_bars(ticker: str, start: str, end: str, key: str) -> pd.DataFrame:
    rows, url_path = [], f"/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000}
    while True:
        js = get(url_path, key, **params)
        rows.extend(js.get("results") or [])
        nxt = js.get("next_url")
        if not nxt:
            break
        q = urllib.parse.urlparse(nxt)
        url_path = q.path
        params = dict(urllib.parse.parse_qsl(q.query))
        params.pop("apiKey", None)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    idx = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    out = pd.DataFrame({"open": df["o"], "high": df["h"], "low": df["l"], "close": df["c"], "volume": df["v"]})
    out.index = pd.DatetimeIndex(idx, name="timestamp")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data")
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--min-dollar-volume", type=float, default=5e6)
    args = ap.parse_args()
    key = os.environ["POLYGON_API_KEY"]
    out = Path(args.out)
    (out / "minute").mkdir(parents=True, exist_ok=True)

    daily_path = out / "grouped_daily.parquet"
    if daily_path.exists():
        daily = pd.read_parquet(daily_path)
    else:
        frames = []
        for day in pd.bdate_range(args.start, args.end):
            df = grouped_daily(day.strftime("%Y-%m-%d"), key)
            if not df.empty:
                frames.append(df)
        daily = pd.concat(frames, ignore_index=True)
        daily.to_parquet(daily_path)

    daily["date"] = pd.to_datetime(daily["date"])
    daily["week"] = daily["date"].dt.to_period("W-SUN")
    ok = daily[(daily["close"] >= args.min_price) & (daily["dollar_volume"] >= args.min_dollar_volume)]
    tickers = sorted(ok["ticker"].unique())
    print(f"{len(tickers)} tickers pass the filter at least once")
    for i, t in enumerate(tickers):
        f = out / "minute" / f"{t}.parquet"
        if f.exists():
            continue
        df = minute_bars(t, args.start, args.end, key)
        if not df.empty:
            df.to_parquet(f)
        print(f"[{i + 1}/{len(tickers)}] {t}: {len(df):,} bars")


if __name__ == "__main__":
    main()
