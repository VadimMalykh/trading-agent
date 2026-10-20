"""Load market data from Postgres for training / inference."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from config import DATABASE_URL

_engine = None


def engine():
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine  # lazy: the torch-free ml_analysis image has no DB driver

        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


def connect():
    """Raw psycopg2 connection (counts / admin)."""
    import psycopg2

    return psycopg2.connect(DATABASE_URL)


def _read_sql(sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    from sqlalchemy import text

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


# X8 (NEXT_TRAINING_PLAN §2): open-interest HISTORY from Binance's public archive, so the
# legacy `oi` / `oi_chg` columns are non-constant inside the training window. When
# ARCHIVE_OI names a parquet (symbol, ts, open_interest, …; built by `m3 archiveoi fetch`),
# `load_open_interest` returns that file's rows for every timestamp BEFORE the collector's
# first row for the pair, followed by the collector's own rows. Unset (the default, and
# always in serving) the loader is exactly what it was. The file's sha8 (in its name) is
# the run's `meta["archive_oi"]`.
ARCHIVE_OI = os.environ.get("ARCHIVE_OI", "").strip()
_archive_oi_cache: Optional[pd.DataFrame] = None

# 🔴 Found 2026-09-24 (X8b's identity check): the archive's `create_time` is the START of the
# 5-minute bucket, but the row carries the value at the bucket's END. Shifting the archive's
# account-ratio rows by +5 min makes them identical to the collector's exchange-stamped rows
# (median 0.011 %, p99 0.02–0.03 %, all twelve pairs); unshifted they disagree by exactly one
# bucket's move (p99 1.3–3.1 %). Open interest shows the same direction (collector polled at
# wall-clock time; nearest-match median 0.034 % shifted vs 0.063 % unshifted). The archive
# flow loader applies the +5 min shift to the two account series unconditionally (verified
# exact; the taker ratio is a bucket aggregate and aligns as is). For open interest the shift
# is a knob, ARCHIVE_OI_SHIFT_MIN, default 0 = exactly what X8 trained on; 5 = the collector's
# convention (what serving sees). Recorded in the checkpoint meta; NEXT_TRAINING_PLAN §2 X8b.
ARCHIVE_OI_SHIFT_MIN = float(os.environ.get("ARCHIVE_OI_SHIFT_MIN", "0") or 0)
ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN = 5.0


def archive_oi_sha() -> Optional[str]:
    """The sha8 embedded in the ARCHIVE_OI file name (metrics_um_5m_<sha8>.parquet), or None."""
    if not ARCHIVE_OI:
        return None
    stem = os.path.splitext(os.path.basename(ARCHIVE_OI))[0]
    return stem.rsplit("_", 1)[-1]


def _archive_oi() -> pd.DataFrame:
    global _archive_oi_cache
    if _archive_oi_cache is None:
        if not os.path.exists(ARCHIVE_OI):
            raise FileNotFoundError(f"ARCHIVE_OI={ARCHIVE_OI!r} does not exist in the container")
        df = pd.read_parquet(ARCHIVE_OI, columns=["symbol", "ts", "open_interest"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        if ARCHIVE_OI_SHIFT_MIN:
            df["ts"] = df["ts"] + pd.Timedelta(minutes=ARCHIVE_OI_SHIFT_MIN)
        _archive_oi_cache = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return _archive_oi_cache


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
    if not ARCHIVE_OI:
        return df
    arch = _archive_oi()
    a = arch[arch["symbol"] == symbol][["ts", "open_interest"]]
    if since:
        a = a[a["ts"] >= pd.Timestamp(since, tz="UTC")]
    if not df.empty:
        a = a[a["ts"] < df["ts"].iloc[0]]
    print(f"Archive OI: {symbol} {len(a)} archive rows "
          f"{'—' if a.empty else a['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} -> "
          f"{'—' if a.empty else a['ts'].iloc[-1].strftime('%Y-%m-%d %H:%M')}, "
          f"collector from {'—' if df.empty else df['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} "
          f"({len(df)} rows), sha8={archive_oi_sha()}, shift_min={ARCHIVE_OI_SHIFT_MIN:g}")
    return pd.concat([a, df], ignore_index=True).sort_values("ts").reset_index(drop=True)


# X8b (NEXT_TRAINING_PLAN §2 X8b): the flow ratios — global long/short ACCOUNT ratio, the
# top-trader long/short ACCOUNT ratio and the taker buy/sell volume ratio — for the `flow`
# feature group. Serving reads the collector's `long_short_ratios` (5m buckets, exchange
# timestamps, since 2026-07-26); training additionally takes the same three series from the
# ARCHIVE_OI parquet (the archive's `count_long_short_ratio`, `count_toptrader_long_short_ratio`
# and `sum_taker_long_short_vol_ratio` columns, renamed by m3/archiveoi.py) for every timestamp
# BEFORE the collector's first row, exactly as `load_open_interest` does. The collector's
# "top" series is the ACCOUNT ratio (endpoint topLongShortAccountRatio), so the archive column
# paired with it is `top_ls_count`, not `top_ls_sum` (the position ratio, which has no live
# counterpart). Unset ARCHIVE_OI = the collector only, which is what serving always sees.
FLOW_COLLECTOR_COLS = ["top_long_short_ratio", "global_long_short_ratio", "taker_buy_sell_ratio"]
_FLOW_ARCHIVE_TO_COLLECTOR = {
    "top_ls_count": "top_long_short_ratio",
    "global_ls": "global_long_short_ratio",
    "taker_ratio": "taker_buy_sell_ratio",
}
_archive_flow_cache: Optional[pd.DataFrame] = None


def _archive_flow() -> pd.DataFrame:
    global _archive_flow_cache
    if _archive_flow_cache is None:
        if not os.path.exists(ARCHIVE_OI):
            raise FileNotFoundError(f"ARCHIVE_OI={ARCHIVE_OI!r} does not exist in the container")
        df = pd.read_parquet(ARCHIVE_OI, columns=["symbol", "ts", *_FLOW_ARCHIVE_TO_COLLECTOR])
        df = df.rename(columns=_FLOW_ARCHIVE_TO_COLLECTOR)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        # The two account ratios are labelled one bucket early in the archive (see
        # ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN above); the taker ratio is not. Re-label them onto
        # the collector's convention so one timestamp means one instant in train and serve.
        acct = df[["symbol", "ts", "top_long_short_ratio", "global_long_short_ratio"]].copy()
        acct["ts"] = acct["ts"] + pd.Timedelta(minutes=ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN)
        taker = df[["symbol", "ts", "taker_buy_sell_ratio"]]
        df = acct.merge(taker, on=["symbol", "ts"], how="outer")
        _archive_flow_cache = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return _archive_flow_cache


def load_long_short_ratios(
    symbol: str,
    since: Optional[str] = None,
) -> pd.DataFrame:
    params: dict = {"symbol": symbol}
    clauses = ["symbol = :symbol", "period = '5m'"]
    if since:
        clauses.append("ts >= :since")
        params["since"] = since
    sql = f"""
        SELECT ts, top_long_short_ratio, global_long_short_ratio, taker_buy_sell_ratio
        FROM long_short_ratios
        WHERE {' AND '.join(clauses)}
        ORDER BY ts ASC
    """
    df = _read_sql(sql, params)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if not ARCHIVE_OI:
        return df
    arch = _archive_flow()
    a = arch[arch["symbol"] == symbol][["ts", *FLOW_COLLECTOR_COLS]]
    if since:
        a = a[a["ts"] >= pd.Timestamp(since, tz="UTC")]
    if not df.empty:
        a = a[a["ts"] < df["ts"].iloc[0]]
    print(f"Archive flow: {symbol} {len(a)} archive rows "
          f"{'—' if a.empty else a['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} -> "
          f"{'—' if a.empty else a['ts'].iloc[-1].strftime('%Y-%m-%d %H:%M')}, "
          f"collector from {'—' if df.empty else df['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} "
          f"({len(df)} rows), sha8={archive_oi_sha()}, account_shift_min={ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN:g}")
    return pd.concat([a, df], ignore_index=True).sort_values("ts").reset_index(drop=True)


# X8c (NEXT_TRAINING_PLAN §2 X8c): the ±0.2 % depth bands for the `depth` feature group.
# Serving reads the collector's `orderbook_snapshots` band columns (500-level poll since
# 2026-10-12 02:17 UTC; NULL before); training additionally takes the archive's reduced rows
# (`m3 archivebook reduce`: Binance's public bookDepth, stale rows dropped, one row per 5m bar)
# for every timestamp BEFORE the collector's first band row — X8's union. The archive rows come
# from the exchange's full book, so their reach is recorded as unbounded; the collector's rows
# carry the deepest level's distance, which the feature uses to mask a band the ladder did not
# reach. The registered stale rule is applied to the collector's rows here (the archive's were
# filtered at reduce time): a row whose six band values on either side equal the previous
# row's on that side is dropped.
ARCHIVE_DEPTH = os.environ.get("ARCHIVE_DEPTH", "").strip()
_archive_depth_cache: Optional[pd.DataFrame] = None
DEPTH_BAND_TAGS = ["0_2", "1", "2", "3", "4", "5"]
DEPTH_COLLECTOR_COLS = [f"{side}_band_{t}" for t in DEPTH_BAND_TAGS for side in ("bid", "ask")]
DEPTH_REACH_UNBOUNDED = 1.0e6


def archive_depth_sha() -> Optional[str]:
    if not ARCHIVE_DEPTH:
        return None
    stem = os.path.splitext(os.path.basename(ARCHIVE_DEPTH))[0]
    return stem.rsplit("_", 1)[-1]


def depth_stale_mask(df: pd.DataFrame) -> np.ndarray:
    """True on a row whose six band values on the bid side, or on the ask side, all equal the
    previous row's — the registered stale rule (X8c). The first row is never stale."""
    if df.empty:
        return np.zeros(0, dtype=bool)
    out = np.zeros(len(df), dtype=bool)
    for side in ("bid", "ask"):
        cols = [f"{side}_band_{t}" for t in DEPTH_BAND_TAGS if f"{side}_band_{t}" in df.columns]
        if not cols:
            continue
        v = df[cols].to_numpy(np.float64)
        same = np.all(v[1:] == v[:-1], axis=1)
        out[1:] |= same
    return out


def _archive_depth() -> pd.DataFrame:
    global _archive_depth_cache
    if _archive_depth_cache is None:
        if not os.path.exists(ARCHIVE_DEPTH):
            raise FileNotFoundError(f"ARCHIVE_DEPTH={ARCHIVE_DEPTH!r} does not exist in the container")
        df = pd.read_parquet(ARCHIVE_DEPTH)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        _archive_depth_cache = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return _archive_depth_cache


_depth_bands_in_db: Optional[bool] = None


def orderbook_has_depth_bands() -> bool:
    """True when `orderbook_snapshots` carries the band columns (migration 20261012000001).
    A training snapshot dumped before 2026-10-12 — X8″'s pinned 20260913T050118Z, which X8c′
    reuses by registration — has none; the collector's contribution is then empty and the
    archive supplies every row. Checked once per process."""
    global _depth_bands_in_db
    if _depth_bands_in_db is None:
        df = _read_sql(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'orderbook_snapshots' AND column_name = 'bid_band_0_2'
            """
        )
        _depth_bands_in_db = not df.empty
        if not _depth_bands_in_db:
            print("Depth bands: orderbook_snapshots has no band columns in this snapshot "
                  "(before migration 20261012000001) — collector rows 0, archive only")
    return _depth_bands_in_db


def load_depth_bands(
    symbol: str,
    since: Optional[str] = None,
) -> pd.DataFrame:
    """(ts, bid_band_0_2, ask_band_0_2, …, bid_reach_bps, ask_reach_bps) for one pair: the
    collector's rows (stale rule applied), preceded by the archive's when ARCHIVE_DEPTH is set.
    On a snapshot without the band columns the collector's part is empty (printed once)."""
    cols = ["ts", *DEPTH_COLLECTOR_COLS, "bid_reach_bps", "ask_reach_bps"]
    if orderbook_has_depth_bands():
        params: dict = {"symbol": symbol}
        clauses = ["symbol = :symbol", "bid_band_0_2 IS NOT NULL"]
        if since:
            clauses.append("ts >= :since")
            params["since"] = since
        sql = f"""
            SELECT {', '.join(cols)}
            FROM orderbook_snapshots
            WHERE {' AND '.join(clauses)}
            ORDER BY ts ASC
        """
        df = _read_sql(sql, params)
    else:
        df = pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
    n_raw = len(df)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df[~depth_stale_mask(df)].reset_index(drop=True)
    if not ARCHIVE_DEPTH:
        return df
    arch = _archive_depth()
    a = arch[arch["symbol"] == symbol].drop(columns=["symbol"])
    if since:
        a = a[a["ts"] >= pd.Timestamp(since, tz="UTC")]
    if not df.empty:
        a = a[a["ts"] < df["ts"].iloc[0]]
    a = a.copy()
    for c in ("bid_reach_bps", "ask_reach_bps"):
        if c not in a.columns:
            a[c] = DEPTH_REACH_UNBOUNDED
    print(f"Archive depth: {symbol} {len(a)} archive rows "
          f"{'—' if a.empty else a['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} -> "
          f"{'—' if a.empty else a['ts'].iloc[-1].strftime('%Y-%m-%d %H:%M')}, "
          f"collector from {'—' if df.empty else df['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} "
          f"({len(df)} rows, {n_raw - len(df)} stale dropped), sha8={archive_depth_sha()}")
    a = a[[c for c in cols if c in a.columns]]
    return pd.concat([a, df], ignore_index=True).sort_values("ts").reset_index(drop=True)


# X14 (NEXT_TRAINING_PLAN §2 X14): the mark–index premium, mark ÷ index − 1 in bps, for the
# `prem` feature group. Serving reads the collector's `funding_rates` poll (mark_price,
# index_price every ~78 s from /fapi/v1/premiumIndex, live since 2026-07-17 on the first
# pairs); training additionally takes the archive's 5m closes (`m3 archiveprem reduce`:
# markPriceKlines ÷ indexPriceKlines, one row per pair-bar, `ts` = the bar's CLOSE) for every
# timestamp BEFORE the collector's first mark row — X8's union. Unset ARCHIVE_PREM = the
# collector only, which is what serving always sees. The file's sha8 is meta["archive_prem"].
ARCHIVE_PREM = os.environ.get("ARCHIVE_PREM", "").strip()
_archive_prem_cache: Optional[pd.DataFrame] = None
PREMIUM_BPS = 1.0e4


def archive_prem_sha() -> Optional[str]:
    if not ARCHIVE_PREM:
        return None
    stem = os.path.splitext(os.path.basename(ARCHIVE_PREM))[0]
    return stem.rsplit("_", 1)[-1]


def _archive_prem() -> pd.DataFrame:
    global _archive_prem_cache
    if _archive_prem_cache is None:
        if not os.path.exists(ARCHIVE_PREM):
            raise FileNotFoundError(f"ARCHIVE_PREM={ARCHIVE_PREM!r} does not exist in the container")
        df = pd.read_parquet(ARCHIVE_PREM, columns=["symbol", "ts", "premium_bps"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        _archive_prem_cache = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return _archive_prem_cache


def load_premium(
    symbol: str,
    since: Optional[str] = None,
) -> pd.DataFrame:
    """(ts, premium_bps) for one pair: the collector's polls with both prices present,
    preceded by the archive's bar-close rows when ARCHIVE_PREM is set. Every row is stamped
    at the moment its value was true (a poll's wall clock; a kline's close), so the feature's
    asof at the bar close needs no shift knob."""
    params: dict = {"symbol": symbol}
    clauses = ["symbol = :symbol", "mark_price IS NOT NULL", "index_price IS NOT NULL", "index_price > 0"]
    if since:
        clauses.append("ts >= :since")
        params["since"] = since
    sql = f"""
        SELECT ts, mark_price, index_price
        FROM funding_rates
        WHERE {' AND '.join(clauses)}
        ORDER BY ts ASC
    """
    df = _read_sql(sql, params)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["premium_bps"] = (df["mark_price"].astype(float) / df["index_price"].astype(float) - 1.0) * PREMIUM_BPS
    df = df[["ts", "premium_bps"]] if not df.empty else pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns, UTC]"),
                                                                       "premium_bps": pd.Series(dtype="float64")})
    if not ARCHIVE_PREM:
        return df
    arch = _archive_prem()
    a = arch[arch["symbol"] == symbol][["ts", "premium_bps"]]
    if since:
        a = a[a["ts"] >= pd.Timestamp(since, tz="UTC")]
    if not df.empty:
        a = a[a["ts"] < df["ts"].iloc[0]]
    print(f"Archive premium: {symbol} {len(a)} archive rows "
          f"{'—' if a.empty else a['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} -> "
          f"{'—' if a.empty else a['ts'].iloc[-1].strftime('%Y-%m-%d %H:%M')}, "
          f"collector from {'—' if df.empty else df['ts'].iloc[0].strftime('%Y-%m-%d %H:%M')} "
          f"({len(df)} rows), sha8={archive_prem_sha()}")
    return pd.concat([a, df], ignore_index=True).sort_values("ts").reset_index(drop=True)


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
    from sqlalchemy import text

    with engine().connect() as conn:
        for t in tables:
            try:
                counts[t] = int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar())
            except Exception as e:
                counts[t] = f"error: {e}"
    return counts
