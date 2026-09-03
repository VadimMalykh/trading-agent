#!/usr/bin/env python3
"""
Compare STORED candles against Binance's own closed klines at identical open_time.

This is the check that was missing when the candle-poll defect ran undetected for six
weeks (docs/CANDLE_POLL_DEFECT.md). The 2026-09-01 investigation compared live
confidence to the offline split's confidence and found them identical -- correctly, since
both are computed from the same stored candles. A defect in the stored *inputs* is
invisible to any check that compares two outputs of the same input. The only check that
catches it is stored-row vs the exchange, which is what this script does.

  python verify_candles.py --days 2026-08-20                       # one day, all pairs
  python verify_candles.py --days 2026-08-20,2026-09-01 --intervals 5m
  python verify_candles.py --since-yesterday                       # the daily guard

Exit code is 0 when every checked (symbol, interval, day) meets the pass condition and 1
otherwise, so this can be run from cron on the VM as a standing integrity guard.

The pass condition is EXACT equality, not closeness. A closed kline is immutable, so a
correctly stored bar reproduces Binance's numbers bit for bit; "nearly right" volume is
the signature of a partial bar, which is precisely what we are looking for.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))

from data.db import engine, load_whitelist_pairs

FAPI = "https://fapi.binance.com"
BARS_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24}

# A stored bar must reproduce the closed kline exactly. Anything below this fraction of
# exact matches is reported as a failure.
PASS_FRACTION = 1.0


def fetch_klines(symbol: str, interval: str, start_ms: int, limit: int) -> pd.DataFrame:
    url = (
        f"{FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&limit={limit}"
    )
    for attempt in range(4):
        try:
            rows = json.loads(urllib.request.urlopen(url, timeout=30).read())
            break
        except Exception as e:  # 429/418/5xx/network -- back off and retry
            if attempt == 3:
                raise
            print(f"    retry {symbol} {interval}: {e}")
            time.sleep(2**attempt)
    return pd.DataFrame(
        {
            "open_time": pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
            "ref_open": [float(r[1]) for r in rows],
            "ref_high": [float(r[2]) for r in rows],
            "ref_low": [float(r[3]) for r in rows],
            "ref_close": [float(r[4]) for r in rows],
            "ref_volume": [float(r[5]) for r in rows],
            "close_time": [int(r[6]) for r in rows],
        }
    )


def stored_candles(symbol: str, interval: str, day: datetime) -> pd.DataFrame:
    sql = text(
        """
        SELECT open_time, open, high, low, close, volume
        FROM candles
        WHERE symbol = :sym AND interval = :iv
          AND open_time >= :a AND open_time < :b
        ORDER BY open_time
        """
    )
    with engine().connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"sym": symbol, "iv": interval, "a": day, "b": day + timedelta(days=1)}
        )
    df["open_time"] = pd.to_datetime(df.open_time, utc=True)
    return df


def check(symbol: str, interval: str, day: datetime) -> tuple[bool, str]:
    now_ms = int(time.time() * 1000)
    ref = fetch_klines(symbol, interval, int(day.timestamp() * 1000), BARS_PER_DAY[interval])
    # Never judge a bar that has not closed yet: the exchange's own newest row is partial
    # too, so comparing it would report a false mismatch on the current day.
    ref = ref[ref.close_time < now_ms]
    db = stored_candles(symbol, interval, day)
    if ref.empty:
        return True, f"{symbol:>12} {interval:>3} {day:%Y-%m-%d}: no closed klines yet, skipped"

    j = ref.merge(db, on="open_time", how="left")
    missing = int(j.open.isna().sum())
    m = j.dropna(subset=["open"])
    if m.empty:
        return False, f"{symbol:>12} {interval:>3} {day:%Y-%m-%d}: FAIL all {len(ref)} bars MISSING"

    exact = {
        "vol": float((m.volume == m.ref_volume).mean()),
        "close": float((m.close == m.ref_close).mean()),
        "high": float((m.high == m.ref_high).mean()),
        "low": float((m.low == m.ref_low).mean()),
    }
    worst = min(exact.values())
    ok = worst >= PASS_FRACTION and missing == 0
    vol_ratio = float((m.volume / m.ref_volume).median())
    line = (
        f"{symbol:>12} {interval:>3} {day:%Y-%m-%d}: {'ok  ' if ok else 'FAIL'} "
        f"{len(m):>4}/{len(ref)} bars, exact vol={exact['vol']:.3f} close={exact['close']:.3f} "
        f"high={exact['high']:.3f} low={exact['low']:.3f}, median vol ratio={vol_ratio:.3f}"
        + (f", MISSING={missing}" if missing else "")
    )
    return ok, line


def parse_args():
    p = argparse.ArgumentParser(description="Stored candles vs Binance closed klines")
    p.add_argument("--symbols", default=None, help="default: every symbol in `candles`")
    p.add_argument("--intervals", default="5m")
    p.add_argument("--days", default=None, help="comma-separated YYYY-MM-DD")
    p.add_argument(
        "--since-yesterday",
        action="store_true",
        help="check yesterday only -- the shape the daily cron guard runs",
    )
    return p.parse_args()


def stored_symbols() -> list[str]:
    with engine().connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT DISTINCT symbol FROM candles ORDER BY 1"))]


def main() -> int:
    args = parse_args()

    if args.days:
        days = [
            datetime.strptime(d.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            for d in args.days.split(",")
            if d.strip()
        ]
    elif args.since_yesterday:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        days = [today - timedelta(days=1)]
    else:
        print("give --days or --since-yesterday")
        return 2

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = stored_symbols() or [s.strip().upper() for s in load_whitelist_pairs()]
    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]
    for iv in intervals:
        if iv not in BARS_PER_DAY:
            print(f"unsupported interval {iv}; known: {sorted(BARS_PER_DAY)}")
            return 2

    print(f"verifying {len(symbols)} symbol(s) x {intervals} over {len(days)} day(s)")
    failures = 0
    for day in days:
        for sym in symbols:
            for iv in intervals:
                try:
                    ok, line = check(sym, iv, day)
                except Exception as e:
                    ok, line = False, f"{sym:>12} {iv:>3} {day:%Y-%m-%d}: ERROR {e}"
                print(line)
                failures += 0 if ok else 1
                time.sleep(0.15)

    total = len(days) * len(symbols) * len(intervals)
    print(f"\n{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
