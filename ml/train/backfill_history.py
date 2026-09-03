#!/usr/bin/env python3
"""
Backfill historic Binance Futures public data into Postgres (no API keys).

  python backfill_history.py --symbols BTCUSDT,ETHUSDT --intervals 1m,5m,15m,1h --days 180
  python backfill_history.py --symbols BTCUSDT --funding --days 180
  python backfill_history.py --intervals 1m,5m,15m,1h --repair-from 2026-07-17

Klines: paginated /fapi/v1/klines (max 1500 per request).
Funding: /fapi/v1/fundingRate.

Two modes:

  * default — fill only what gap detection reports as MISSING, inserting with
    ON CONFLICT DO NOTHING. Rows that already exist are left alone.
  * --repair-from DATE — ignore gap detection, refetch the whole range from DATE
    to now, and OVERWRITE the stored OHLCV. This exists because the app collector
    used to freeze the first (still-forming) view of every bar, so the corrupt
    rows are present, not missing, and the default mode reports them "already
    covered" and does nothing. See docs/CANDLE_POLL_DEFECT.md.

Neither mode ever stores a bar that has not closed yet: a kline whose close_time
is in the future is the exchange's still-forming bar and is skipped, so this
script cannot itself plant the partial row it is here to repair.
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

from config import DATABASE_URL
from data.db import engine, load_whitelist_pairs

FAPI = "https://fapi.binance.com"
MAX_LIMIT = 1500
SLEEP_S = 0.15

# Retry 429/418/5xx and network errors with exponential backoff (up to ~90s).
# A persistent failure now RAISES instead of silently returning [] and stopping
# the range loop — so a dead pair/interval is never left half-downloaded without
# an ERROR being surfaced (previously `if not batch: break` hid the truncation).
MAX_ATTEMPTS = 12
BACKOFF_BASE_S = 1.5
BACKOFF_MAX_S = 90
_SESSION = requests.Session()


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def get_with_retry(url: str, params: dict) -> requests.Response:
    last_status: Optional[int] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = _SESSION.get(url, params=params, timeout=120)
            if r.status_code == 200:
                return r
            last_status = r.status_code
            retryable = r.status_code in (418, 429) or r.status_code >= 500
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(
                    f"GET {url} failed after {MAX_ATTEMPTS} attempts: {exc!r}"
                ) from exc
            backoff = min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** attempt))
            print(f"    [retry {attempt + 1}/{MAX_ATTEMPTS}] {type(exc).__name__}: backoff {backoff:.0f}s")
            time.sleep(backoff)
            continue
        if not retryable:
            raise RuntimeError(
                f"GET {url} unexpected HTTP {r.status_code}: {r.text[:200]}"
            )
        if attempt == MAX_ATTEMPTS - 1:
            raise RuntimeError(
                f"GET {url} HTTP {last_status} after {MAX_ATTEMPTS} attempts"
            )
        backoff = min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** attempt))
        print(f"    [retry {attempt + 1}/{MAX_ATTEMPTS}] HTTP {r.status_code}: backoff {backoff:.0f}s")
        time.sleep(backoff)
    raise RuntimeError(f"unreachable: GET {url}")


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": MAX_LIMIT,
    }
    return get_with_retry(f"{FAPI}/fapi/v1/klines", params).json()


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> list:
    params = {
        "symbol": symbol,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    }
    return get_with_retry(f"{FAPI}/fapi/v1/fundingRate", params).json()


# Per-call write tally, reported at the end of each symbol/interval. Kept as
# module state because _fetch_loop's upsert callback can only return one number.
_WRITE_STATS = {"inserted": 0, "updated": 0, "unclosed": 0}


def _reset_write_stats() -> None:
    for k in _WRITE_STATS:
        _WRITE_STATS[k] = 0


_ON_CONFLICT_NOTHING = "ON CONFLICT (symbol, interval, open_time) DO NOTHING"
_ON_CONFLICT_REPLACE = """ON CONFLICT (symbol, interval, open_time) DO UPDATE SET
          open = EXCLUDED.open,
          high = EXCLUDED.high,
          low = EXCLUDED.low,
          close = EXCLUDED.close,
          volume = EXCLUDED.volume,
          close_time = EXCLUDED.close_time"""


def upsert_candles(symbol: str, interval: str, rows: list, replace: bool = False) -> int:
    """
    Write klines. With replace=False a row that already exists is left untouched;
    with replace=True its OHLCV is overwritten by the freshly fetched bar, which is
    the only way to repair the partial rows the collector froze (CANDLE_POLL_DEFECT).

    `xmax = 0` in the RETURNING clause is Postgres for "this tuple was inserted, not
    updated", which is what separates a genuine gap fill from a repair.
    """
    if not rows:
        return 0
    sql = text(
        f"""
        INSERT INTO candles (
          symbol, interval, open_time, open, high, low, close, volume, close_time
        ) VALUES (
          :symbol, :interval, to_timestamp(:open_time/1000.0),
          :open, :high, :low, :close, :volume,
          to_timestamp(:close_time/1000.0)
        )
        {_ON_CONFLICT_REPLACE if replace else _ON_CONFLICT_NOTHING}
        RETURNING (xmax = 0) AS inserted
        """
    )
    now_ms = int(time.time() * 1000)
    n = 0
    with engine().begin() as conn:
        for k in rows:
            close_ms = int(k[6])
            # The newest kline of a range ending "now" is the bar still forming. Storing
            # it is exactly the defect this script repairs, so never store it.
            if close_ms >= now_ms:
                _WRITE_STATS["unclosed"] += 1
                continue
            inserted = conn.execute(
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
                    "close_time": close_ms,
                },
            ).scalar()
            # DO NOTHING returns no row for a conflict; DO UPDATE always returns one.
            if inserted is True:
                _WRITE_STATS["inserted"] += 1
            elif inserted is False:
                _WRITE_STATS["updated"] += 1
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


def gap_ranges_ms(
    table: str,
    symbol: str,
    ts_col: str,
    step_ms: int,
    extra: Optional[str] = None,
) -> List[tuple]:
    """
    INTERIOR missing ranges [from_ms, to_ms] strictly inside stored coverage,
    detected via a lead() window (consecutive-row ts diffs > step_ms). Tails
    past the last row are NOT included — those are handled by fetch_ranges().
    Empty list → no interior holes.
    """
    sql = f"""
        WITH g AS (
          SELECT {ts_col} AS t,
                 lead({ts_col}) OVER (PARTITION BY symbol ORDER BY {ts_col}) AS nxt
          FROM {table}
          WHERE symbol = :symbol{f' AND {extra}' if extra else ''}
        )
        SELECT
          (EXTRACT(EPOCH FROM t) * 1000)::bigint + {step_ms} AS from_ms,
          (EXTRACT(EPOCH FROM nxt) * 1000)::bigint - {step_ms} AS to_ms
        FROM g
        WHERE nxt IS NOT NULL
          AND nxt - t > make_interval(secs => {step_ms} / 1000.0)
        ORDER BY 1
    """
    with engine().connect() as conn:
        rows = conn.execute(text(sql), {"symbol": symbol}).fetchall()
    return [(int(r[0]), int(r[1])) for r in rows]


def merge_ranges(ranges: List[tuple]) -> List[tuple]:
    """Sort + merge overlapping/highlighting adjacent ranges (dedupe edges+gaps)."""
    merged = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _fetch_loop(
    fetch, upsert, rows_to_last, symbol: str, ranges, label: str, page_size: int
) -> int:
    fmt = lambda m: datetime.fromtimestamp(m / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    total = 0
    for from_ms, to_ms in ranges:
        print(f"    fetching {label} {fmt(from_ms)} → {fmt(to_ms)}")
        cursor = from_ms
        while cursor <= to_ms:
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


def backfill_klines(
    symbol: str, interval: str, days: int, repair_from: Optional[datetime] = None
) -> int:
    end = datetime.now(timezone.utc)
    step_ms = INTERVAL_STEP_MS.get(interval, 60_000)
    fmt = lambda m: datetime.fromtimestamp(m / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    _reset_write_stats()

    if repair_from is not None:
        # Repair: the rows are PRESENT and wrong, so coverage and gap detection would
        # both say "nothing to do". Refetch the whole window and overwrite.
        start = repair_from
        ranges = [(ms(start), ms(end))]
        print(f"  klines {symbol} {interval}: REPAIR {fmt(ms(start))} → {fmt(ms(end))}")
    else:
        start = end - timedelta(days=days)
        cov = coverage_ms("candles", symbol, "open_time", f"interval = '{interval}'")
        ranges = fetch_ranges(start, end, cov, step_ms)
        gaps = gap_ranges_ms(
            "candles", symbol, "open_time", step_ms, f"interval = '{interval}'"
        )
        if gaps:
            print(f"    {len(gaps)} interior gap(s) detected inside stored range")
            ranges = merge_ranges(ranges + gaps)
        print(f"  klines {symbol} {interval}: window {fmt(ms(start))} → {fmt(ms(end))}")
        if not ranges:
            print(f"    already covered, nothing to fetch")
            return 0

    replace = repair_from is not None
    total = _fetch_loop(
        lambda s, f, t: fetch_klines(s, interval, f, t),
        lambda s, b: upsert_candles(s, interval, b, replace=replace),
        lambda b: int(b[-1][0]),
        symbol,
        ranges,
        "klines",
        MAX_LIMIT,
    )
    print(
        f"  done {symbol} {interval}: ~{total} rows attempted "
        f"(inserted={_WRITE_STATS['inserted']} updated={_WRITE_STATS['updated']} "
        f"unclosed-skipped={_WRITE_STATS['unclosed']})"
    )
    return total


def backfill_funding(symbol: str, days: int) -> int:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    cov = coverage_ms("funding_rates", symbol, "ts")
    ranges = fetch_ranges(start, end, cov, 8 * 3_600_000)
    gaps = gap_ranges_ms("funding_rates", symbol, "ts", 8 * 3_600_000)
    if gaps:
        print(f"    {len(gaps)} interior gap(s) detected inside stored range")
        ranges = merge_ranges(ranges + gaps)
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
    p.add_argument("--symbols", default=None)
    # 5m is in the default set because it is the interval the served model reads and the
    # one the collector defect hit hardest (a 5m bar was frozen after its first fifth).
    p.add_argument("--intervals", default="1m,5m,15m,1h")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--funding", action="store_true", help="Also backfill funding rates")
    p.add_argument("--skip-klines", action="store_true", help="Skip kline backfill (funding only)")
    p.add_argument(
        "--repair-from",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Repair mode: refetch every kline from this UTC date to now and OVERWRITE the "
            "stored OHLCV, ignoring gap detection and --days. Use for CANDLE_POLL_DEFECT "
            "(--repair-from 2026-07-17). Defaults --symbols to every symbol in `candles`."
        ),
    )
    return p.parse_args()


def stored_symbols() -> List[str]:
    """Every symbol that has candles, whitelisted or not — a repair must miss none."""
    with engine().connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT symbol FROM candles ORDER BY 1")).fetchall()
    return [r[0] for r in rows]


def main():
    args = parse_args()

    repair_from = None
    if args.repair_from:
        repair_from = datetime.strptime(args.repair_from, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif repair_from is not None:
        # A repair that only covers the whitelist leaves corrupt rows behind for any pair
        # that was collected earlier under a wider whitelist.
        symbols = stored_symbols()
    else:
        symbols = [s.strip().upper() for s in load_whitelist_pairs()]
    intervals = [i.strip() for i in args.intervals.split(",") if i.strip()]

    print("FluxTrader historic backfill")
    print(f"DB={DATABASE_URL}")
    if repair_from is not None:
        print(f"MODE=REPAIR (overwrite) from {repair_from:%Y-%m-%d} to now")
    print(f"symbols={symbols} days={args.days} intervals={intervals} funding={args.funding}")

    # smoke DB
    with engine().connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM candles")).scalar()
        print(f"candles before: {n}")

    if not args.skip_klines:
        for sym in symbols:
            for iv in intervals:
                try:
                    backfill_klines(sym, iv, args.days, repair_from=repair_from)
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
