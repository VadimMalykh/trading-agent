"""Load market data from Postgres for training / inference."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text

from config import DATABASE_URL

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


def connect():
    """Raw psycopg2 connection (counts / admin)."""
    import psycopg2

    return psycopg2.connect(DATABASE_URL)


def _read_sql(sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    return pd.read_sql(text(sql), engine(), params=params or {})


def load_candles(
    symbol: str,
    interval: str = "1m",
    limit: Optional[int] = None,
) -> pd.DataFrame:
    sql = """
        SELECT open_time, open, high, low, close, volume, close_time
        FROM candles
        WHERE symbol = :symbol AND interval = :interval
        ORDER BY open_time ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    df = _read_sql(sql, {"symbol": symbol, "interval": interval})
    if df.empty:
        return df

    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df


# How long after a bar's `close_time` its stored row is trusted to be final. The collector
# polls `/fapi/v1/klines limit=5` once a minute per pair and replaces the row on conflict, so
# for up to a poll period after the close the row is still the last IN-BAR snapshot: measured
# at the 2026-09-11 04:55 close, the 12 rows settled 7–93 s after `close_time`, and 10 of the
# forward test's first 42 ledger rows were scored on such a snapshot (M3_FIDELITY_RESULTS §7.6
# "Acceptance", BACKLOG row 9). 120 s = one poll period plus margin.
CANDLE_SETTLE_S = int(os.environ.get("CANDLE_SETTLE_S", "120"))


def load_candles_tail(
    symbol: str,
    interval: str = "1m",
    n: int = 640,
    as_of: Optional[datetime] = None,
) -> pd.DataFrame:
    """The last `n` CLOSED candles for `symbol`/`interval`, oldest first.

    `as_of` (UTC; tz-aware or naive) bounds the tail: only candles whose `close_time` is at
    or before it are returned. It defaults to **now minus `CANDLE_SETTLE_S`**, which excludes
    the still-forming bar and the bar that closed less than a poll period ago, whose stored
    row may still be the collector's last in-bar snapshot. An explicit `as_of` is taken as
    given (no settle subtracted): a replay that wants what a live tick at time T saw passes
    `T - CANDLE_SETTLE_S`; a replay at a bar boundary C passes `C + interval` and gets the bar
    that opened at C as its last row.

    The collector stores the forming bar and replaces it on every poll until it closes
    (collector.ex `insert_candle`), so without this bound the newest row is a partial
    bar whose close moves with every poll. Offline, every training and evaluation window
    ends on a complete bar; live, serve.py was scoring the partial one and re-scoring it
    every 30 s as it changed — the forward test's first trade fired on such a re-score
    (M3_FIDELITY_RESULTS §7.6, 2026-09-11). A replay at a historical bar passes `as_of`
    explicitly and gets exactly what a live tick at that moment would have seen.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc) - timedelta(seconds=CANDLE_SETTLE_S)
    # `candles.close_time` is `timestamp(6)` WITHOUT time zone (Ecto :utc_datetime_usec), so
    # bind a naive UTC value and compare timestamp to timestamp — no session-TZ dependence.
    if as_of.tzinfo is not None:
        as_of = as_of.astimezone(timezone.utc).replace(tzinfo=None)
    sql = """
        SELECT open_time, open, high, low, close, volume, close_time
        FROM candles
        WHERE symbol = :symbol AND interval = :interval AND close_time <= :as_of
        ORDER BY open_time DESC
        LIMIT :n
    """
    df = _read_sql(sql, {"symbol": symbol, "interval": interval, "n": int(n), "as_of": as_of})
    if df.empty:
        return df
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    return df.sort_values("open_time").reset_index(drop=True)



def load_orderbook(
    symbol: str,
    limit: Optional[int] = None,
    since: Optional[str] = None,
) -> pd.DataFrame:
    params: dict = {"symbol": symbol}
    clauses = ["symbol = :symbol"]
    if since:
        clauses.append("ts >= :since")
        params["since"] = since
    sql = f"""
        SELECT ts, mid, spread, microprice, bid_volume, ask_volume, imbalance,
               bid_depth_near, ask_depth_near, bid_depth_far, ask_depth_far
        FROM orderbook_snapshots
        WHERE {' AND '.join(clauses)}
        ORDER BY ts ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    df = _read_sql(sql, params)
    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_market_trades(
    symbol: str,
    limit: Optional[int] = None,
    since: Optional[str] = None,
) -> pd.DataFrame:
    params: dict = {"symbol": symbol}
    clauses = ["symbol = :symbol"]
    if since:
        clauses.append("window_start >= :since")
        params["since"] = since
    sql = f"""
        SELECT window_start, trade_count, volume, buy_volume, sell_volume, vwap, high, low
        FROM market_trades
        WHERE {' AND '.join(clauses)}
        ORDER BY window_start ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    df = _read_sql(sql, params)
    if df.empty:
        return df

    df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
    return df


def load_funding(
    symbol: str,
    since: Optional[str] = None,
) -> pd.DataFrame:
    params: dict = {"symbol": symbol}
    clauses = ["symbol = :symbol"]
    if since:
        clauses.append("ts >= :since")
        params["since"] = since
    sql = f"""
        SELECT ts, mark_price, index_price, last_funding_rate
        FROM funding_rates
        WHERE {' AND '.join(clauses)}
        ORDER BY ts ASC
    """
    df = _read_sql(sql, params)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_open_interest(
    symbol: str,
    since: Optional[str] = None,
) -> pd.DataFrame:
    params: dict = {"symbol": symbol}
    clauses = ["symbol = :symbol"]
    if since:
        clauses.append("ts >= :since")
        params["since"] = since
    sql = f"""
        SELECT ts, open_interest
        FROM open_interest
        WHERE {' AND '.join(clauses)}
        ORDER BY ts ASC
    """
    df = _read_sql(sql, params)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_whitelist_pairs(fallback: list | None = None) -> list:
    """
    Pairs from app_settings (UI whitelist), else symbols that have candles,
    else fallback / env defaults.
    """
    from config import PAIRS

    fallback = fallback or PAIRS
    try:
        sql = """
            SELECT value FROM app_settings WHERE key = :key
        """
        df = _read_sql(sql, {"key": "whitelist_pairs"})
        if not df.empty:
            val = df.iloc[0]["value"]
            if isinstance(val, str):
                import json

                val = json.loads(val)
            if isinstance(val, dict) and isinstance(val.get("pairs"), list):
                pairs = [str(p).upper().strip() for p in val["pairs"] if str(p).strip()]
                if pairs:
                    return pairs
    except Exception:
        pass

    try:
        df = _read_sql(
            """
            SELECT DISTINCT symbol FROM candles
            ORDER BY symbol
            """
        )
        if not df.empty:
            return [str(s).upper() for s in df["symbol"].tolist()]
    except Exception:
        pass

    return list(fallback)


def table_counts() -> dict:
    tables = [
        "candles",
        "orderbook_snapshots",
        "market_trades",
        "funding_rates",
        "open_interest",
        "liquidations",
    ]
    counts = {}
    with engine().connect() as conn:
        for t in tables:
            try:
                counts[t] = int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar())
            except Exception as e:
                counts[t] = f"error: {e}"
    return counts
