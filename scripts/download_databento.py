"""Download CME Nasdaq futures minute bars (NQ / MNQ) from Databento into the
local Parquet cache read by the ``parquet`` data plugin.

    pip install databento
    export DATABENTO_API_KEY=...
    python scripts/download_databento.py --root MNQ --start 2022-01-01 --end 2025-12-31 --out data
    # prints the cost estimate first; add --yes to actually download

What it does and why:

* Dataset ``GLBX.MDP3`` (CME Globex), schema ``ohlcv-1m``: one bar per minute
  in which the contract traded, labelled by its start time, full Globex
  session (overnight included, which the 15-minute EMA200 needs).
* Continuous front month by volume (``MNQ.v.0``), so the series follows the
  contract people actually trade and rolls when volume moves to the next one.
* **Back-adjustment.** A raw continuous series jumps at every quarterly roll
  (the next contract trades at a different price). That jump is not a real
  move, and it would distort EMAs and any multi-day indicator. We also fetch
  the second month (``MNQ.v.1``); at each roll, the gap between the new and
  old contract over the last minute before the roll is subtracted from all
  earlier bars (difference adjustment, which keeps point P&L exact).
* Timestamps are stored in UTC; the ``parquet`` plugin converts them to
  New York time, so DST is handled.

Things to know about real data that the synthetic set does not have:

* Holidays and early closes (e.g. 13:00 ET the day after Thanksgiving): the
  strategy goes flat at the last bar before ``flat_time``, and the engine
  labels those exits ``delisted_or_halted`` because the session ended early.
* Minutes with no trades have no bar. The resampler handles gaps.
* MNQ only exists from May 2019. For longer history use NQ prices (the same
  index, ``--root NQ``) and set ``point_value`` to 2 in the config to size
  results as one MNQ.

STATUS: written against Databento's documented Python client but not yet run
with a real key. Expect small fixes on first use.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"


def fetch(client, symbol: str, start: str, end: str) -> pd.DataFrame:
    data = client.timeseries.get_range(dataset=DATASET, schema=SCHEMA, stype_in="continuous",
                                       symbols=[symbol], start=start, end=end)
    df = data.to_df()  # index ts_event (UTC, bar start); prices as floats
    return df[["open", "high", "low", "close", "volume", "instrument_id"]].sort_index()


def back_adjust(front: pd.DataFrame, second: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Difference-adjust the front-month series at each roll."""
    front = front.copy()
    ids = front["instrument_id"].to_numpy()
    roll_pos = [i for i in range(1, len(ids)) if ids[i] != ids[i - 1]]
    rolls = []
    for i in reversed(roll_pos):  # latest roll first, so adjustments accumulate backwards
        t_prev = front.index[i - 1]
        new_id = ids[i]
        # Last minute at or before t_prev where the *new* contract traded as second month.
        cand = second[(second.index <= t_prev) & (second["instrument_id"] == new_id)]
        if cand.empty:
            rolls.append({"time": str(front.index[i]), "gap": None, "note": "no overlap; left unadjusted"})
            continue
        t_common = cand.index[-1]
        old_px = front.loc[:t_common, "close"].iloc[-1]
        gap = float(cand["close"].iloc[-1] - old_px)
        front.iloc[:i, front.columns.get_indexer(["open", "high", "low", "close"])] += gap
        rolls.append({"time": str(front.index[i]), "gap": gap})
    return front, list(reversed(rolls))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="MNQ", help="Futures root: MNQ or NQ")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data")
    ap.add_argument("--yes", action="store_true", help="Download after showing the cost estimate")
    args = ap.parse_args()

    import databento as db  # optional dependency

    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("set DATABENTO_API_KEY")
    client = db.Historical(key)
    syms = [f"{args.root}.v.0", f"{args.root}.v.1"]
    cost = sum(client.metadata.get_cost(dataset=DATASET, schema=SCHEMA, stype_in="continuous",
                                        symbols=[s], start=args.start, end=args.end) for s in syms)
    print(f"Estimated cost for {syms} {args.start}..{args.end}: ${cost:,.2f}")
    if not args.yes:
        print("Re-run with --yes to download.")
        return
    front = fetch(client, syms[0], args.start, args.end)
    second = fetch(client, syms[1], args.start, args.end)
    adj, rolls = back_adjust(front, second)
    for r in rolls:
        print("roll", r)
    out = Path(args.out) / "minute"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.root}.parquet"
    adj[["open", "high", "low", "close", "volume"]].to_parquet(path)
    print(f"wrote {len(adj):,} bars to {path}")


if __name__ == "__main__":
    main()
