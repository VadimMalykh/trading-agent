"""Load market data from Postgres for training / inference."""

from __future__ import annotations

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


def load_orderbook(symbol: str, limit: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT ts, mid, spread, microprice, bid_volume, ask_volume, imbalance,
               bid_depth_near, ask_depth_near, bid_depth_far, ask_depth_far
        FROM orderbook_snapshots
        WHERE symbol = :symbol
        ORDER BY ts ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    df = _read_sql(sql, {"symbol": symbol})
    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_market_trades(symbol: str, limit: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT window_start, trade_count, volume, buy_volume, sell_volume, vwap, high, low
        FROM market_trades
        WHERE symbol = :symbol
        ORDER BY window_start ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    df = _read_sql(sql, {"symbol": symbol})
    if df.empty:
        return df

    df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
    return df


def load_funding(symbol: str) -> pd.DataFrame:
    sql = """
        SELECT ts, mark_price, index_price, last_funding_rate
        FROM funding_rates
        WHERE symbol = :symbol
        ORDER BY ts ASC
    """
    df = _read_sql(sql, {"symbol": symbol})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_open_interest(symbol: str) -> pd.DataFrame:
    sql = """
        SELECT ts, open_interest
        FROM open_interest
        WHERE symbol = :symbol
        ORDER BY ts ASC
    """
    df = _read_sql(sql, {"symbol": symbol})
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
