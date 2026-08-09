#!/usr/bin/env python3
"""
Backfill historic Binance Futures public data into Postgres (no API keys).

  python backfill_history.py --symbols BTCUSDT,ETHUSDT --intervals 1m,15m,1h --days 180
  python backfill_history.py --symbols BTCUSDT --funding --days 180

Klines: paginated /fapi/v1/klines (max 1500 per request).
Funding: /fapi/v1/fundingRate.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import requests
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DATABASE_URL, PAIRS
from data.db import engine

FAPI = "https://fapi.binance.com"
MAX_LIMIT = 1500
SLEEP_S = 0.15


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": MAX_LIMIT,
    }
    for attempt in range(5):
        r = requests.get(f"{FAPI}/fapi/v1/klines", params=params, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    return []


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> list:
    params = {
        "symbol": symbol,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    }
    for attempt in range(5):
        r = requests.get(f"{FAPI}/fapi/v1/fundingRate", params=params, timeout=60)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    return []


def upsert_candles(symbol: str, interval: str, rows: list) -> int:
    if not rows:
        return 0
    sql = text(
        """
        INSERT INTO candles (
          symbol, interval, open_time, open, high, low, close, volume, close_time
        ) VALUES (
          :symbol, :interval, to_timestamp(:open_time/1000.0),
          :open, :high, :low, :close, :volume,
          to_timestamp(:close_time/1000.0)
        )
        ON CONFLICT (symbol, interval, open_time) DO NOTHING
        """
    )
    n = 0
    with engine().begin() as conn:
        for k in rows:
            conn.execute(
                sql,
                {
                    "symbol": symbol,
                    "interval": interval,
                    "open_time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": int(k[6]),
                },
            )
            n += 1
    return n


def upsert_funding(symbol: str, rows: list) -> int:
    if not rows:
        return 0
    sql = text(
        """
        INSERT INTO funding_rates (
          symbol, ts, mark_price, index_price, last_funding_rate, next_funding_time
        ) VALUES (
          :symbol, to_timestamp(:ts/1000.0), NULL, NULL, :rate, NULL
        )
        ON CONFLICT (symbol, ts) DO NOTHING
        """
    )
    n = 0
    with engine().begin() as conn:
        for row in rows:
            conn.execute(
                sql,
                {
                    "symbol": symbol,
                    "ts": int(row["fundingTime"]),
                    "rate": float(row["fundingRate"]),
                },
            )
            n += 1
    return n


INTERVAL_STEP_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}


def coverage_ms(
    table: str, symbol: str, ts_col: str, extra: Optional[str] = None
) -> Optional[tuple]:
    """(min_ms, max_ms) of stored rows for a symbol, or None if no rows."""
    sql = f"SELECT min({ts_col}), max({ts_col}) FROM {table} WHERE symbol = :symbol"
    if extra:
        sql += f" AND {extra}"
    with engine().connect() as conn:
        lo, hi = conn.execute(text(sql), {"symbol": symbol}).one()
    if lo is None:
        return None
    return int(lo.timestamp() * 1000), int(hi.timestamp() * 1000)


def fetch_ranges(
    start: datetime,
    end: datetime,
    cov: Optional[tuple],
    step_ms: int,
) -> List[tuple]:
    """
    List of [from_ms, to_ms] ranges to fetch for [start, end] given stored
    coverage, covering ONLY the missing parts (older-than-stored + tail).
    Empty list → everything in the window is already stored.
    """
    start_ms = ms(start)
    end_ms = ms(end)
    if cov is None:
        return [(start_ms, end_ms)]
    lo, hi = cov
    left_missing = lo > start_ms
    right_missing = hi < end_ms - step_ms
    if not left_missing and not right_missing:
        return []
    ranges = []
    if left_missing:
        ranges.append((start_ms, min(end_ms, lo)))
    if right_missing:
        ranges.append((max(start_ms, hi + step_ms), end_ms))
    return ranges


def _fetch_loop(
    fetch, upsert, rows_to_last, symbol: str, ranges, label: str, page_size: int
) -> int:
    fmt = lambda m: datetime.fromtimestamp(m / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    total = 0
    for from_ms, to_ms in ranges:
        print(f"    fetching {label} {fmt(from_ms)} → {fmt(to_ms)}")
        cursor = from_ms
        while cursor < to_ms:
            batch = fetch(symbol, cursor, to_ms)
            time.sleep(SLEEP_S)
            if not batch:
                break
            total += upsert(symbol, batch)
            last_t = rows_to_last(batch)
            next_cursor = last_t + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < page_size:
                break
    return total


def backfill_klines(symbol: str, interval: str, days: int) -> int:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    step_ms = INTERVAL_STEP_MS.get(interval, 60_000)
    cov = coverage_ms("candles", symbol, "open_time", f"interval = '{interval}'")
    ranges = fetch_ranges(start, end, cov, step_ms)
    fmt = lambda m: datetime.fromtimestamp(m / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"  klines {symbol} {interval}: window {fmt(ms(start))} → {fmt(ms(end))}")
    if not ranges:
        print(f"    already covered, nothing to fetch")
        return 0
    total = _fetch_loop(
        lambda s, f, t: fetch_klines(s, interval, f, t),
        lambda s, b: upsert_candles(s, interval, b),
        lambda b: int(b[-1][0]),
        symbol,
        ranges,
        "klines",
        MAX_LIMIT,
    )
    print(f"  done {symbol} {interval}: ~{total} rows attempted")
    return total


def backfill_funding(symbol: str, days: int) -> int:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    cov = coverage_ms("funding_rates", symbol, "ts")
    ranges = fetch_ranges(start, end, cov, 8 * 3_600_000)
    fmt = lambda m: datetime.fromtimestamp(m / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"  funding {symbol}: window {fmt(ms(start))} → {fmt(ms(end))}")
    if not ranges:
        print(f"    already covered, nothing to fetch")
        return 0
    total = _fetch_loop(
        fetch_funding,
        upsert_funding,
        lambda b: int(b[-1]["fundingTime"]),
        symbol,
        ranges,
        "funding",
        1000,
    )
    print(f"  done funding {symbol}: ~{total} rows attempted")
    return total


def parse_args():
    p = argparse.ArgumentParser(description="Backfill Binance Futures history → Postgres")
    p.add_argument("--symbols", default=",".join(PAIRS))
    p.add_argument("--intervals", default="1m,15m,1h")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--funding", action="store_true", help="Also backfill funding rates")
    p.add_argument("--skip-klines", action="store_true", help="Skip kline backfill (funding only)")
    return p.parse_args()


def main():
    args = parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]

    print("FluxTrader historic backfill")
    print(f"DB={DATABASE_URL}")
    print(f"symbols={symbols} days={args.days} intervals={intervals} funding={args.funding}")

    # smoke DB
    with engine().connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM candles")).scalar()
        print(f"candles before: {n}")

    if not args.skip_klines:
        for sym in symbols:
            for iv in intervals:
                try:
                    backfill_klines(sym, iv, args.days)
                except Exception as e:
                    print(f"ERROR klines {sym} {iv}: {e}")

    if args.funding:
        for sym in symbols:
            try:
                backfill_funding(sym, args.days)
            except Exception as e:
                print(f"ERROR funding {sym}: {e}")

    with engine().connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM candles")).scalar()
        print(f"candles after: {n}")
    print("Done.")


if __name__ == "__main__":
    main()
