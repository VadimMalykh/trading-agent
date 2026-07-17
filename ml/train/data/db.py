"""Load market data from Postgres for training."""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import psycopg2

from config import DATABASE_URL


def connect():
    return psycopg2.connect(DATABASE_URL)


def load_candles(
    symbol: str,
    interval: str = "1m",
    limit: Optional[int] = None,
) -> pd.DataFrame:
    sql = """
        SELECT open_time, open, high, low, close, volume, close_time
        FROM candles
        WHERE symbol = %s AND interval = %s
        ORDER BY open_time ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    with connect() as conn:
        df = pd.read_sql(sql, conn, params=(symbol, interval))

    if df.empty:
        return df

    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    return df


def load_orderbook(symbol: str, limit: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT ts, mid, spread, microprice, bid_volume, ask_volume, imbalance,
               bid_depth_near, ask_depth_near, bid_depth_far, ask_depth_far
        FROM orderbook_snapshots
        WHERE symbol = %s
        ORDER BY ts ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    with connect() as conn:
        df = pd.read_sql(sql, conn, params=(symbol,))

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_market_trades(symbol: str, limit: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT window_start, trade_count, volume, buy_volume, sell_volume, vwap, high, low
        FROM market_trades
        WHERE symbol = %s
        ORDER BY window_start ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    with connect() as conn:
        df = pd.read_sql(sql, conn, params=(symbol,))

    if df.empty:
        return df

    df["window_start"] = pd.to_datetime(df["window_start"], utc=True)
    return df


def load_funding(symbol: str) -> pd.DataFrame:
    sql = """
        SELECT ts, mark_price, index_price, last_funding_rate
        FROM funding_rates
        WHERE symbol = %s
        ORDER BY ts ASC
    """
    with connect() as conn:
        df = pd.read_sql(sql, conn, params=(symbol,))

    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def load_open_interest(symbol: str) -> pd.DataFrame:
    sql = """
        SELECT ts, open_interest
        FROM open_interest
        WHERE symbol = %s
        ORDER BY ts ASC
    """
    with connect() as conn:
        df = pd.read_sql(sql, conn, params=(symbol,))

    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


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
    with connect() as conn:
        with conn.cursor() as cur:
            for t in tables:
                try:
                    cur.execute(f"SELECT count(*) FROM {t}")
                    counts[t] = cur.fetchone()[0]
                except Exception as e:
                    counts[t] = f"error: {e}"
    return counts
