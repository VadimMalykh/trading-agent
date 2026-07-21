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


def backfill_klines(symbol: str, interval: str, days: int) -> int:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    cursor = ms(start)
    end_ms = ms(end)
    total = 0
    print(f"  klines {symbol} {interval} from {start.date()} → {end.date()}")

    while cursor < end_ms:
        batch = fetch_klines(symbol, interval, cursor, end_ms)
        time.sleep(SLEEP_S)
        if not batch:
            break
        total += upsert_candles(symbol, interval, batch)
        last_open = int(batch[-1][0])
        next_cursor = last_open + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < MAX_LIMIT:
            break
        print(f"    … {symbol} {interval} inserted~{total} last_open_ms={last_open}")

    print(f"  done {symbol} {interval}: ~{total} rows attempted")
    return total


def backfill_funding(symbol: str, days: int) -> int:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    cursor = ms(start)
    end_ms = ms(end)
    total = 0
    print(f"  funding {symbol} from {start.date()} → {end.date()}")

    while cursor < end_ms:
        batch = fetch_funding(symbol, cursor, end_ms)
        time.sleep(SLEEP_S)
        if not batch:
            break
        total += upsert_funding(symbol, batch)
        last_t = int(batch[-1]["fundingTime"])
        next_cursor = last_t + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < 1000:
            break

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
