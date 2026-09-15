"""P1 — the historical tape (archive aggTrades), streamed into a per-minute summary.

The full tape is ~136 GB zipped for the twelve pairs from 2023-01 (measured 2026-09-15) and
does not fit the work VM next to everything else, so it is never kept: each daily zip is
fetched, reduced to one row per (symbol, minute), and deleted. The summary is what P1's cost
model reads; the raw day can always be re-fetched for a spot check (`ft2 archive aggTrades`).

Archive row: agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time (ms),
is_buyer_maker (true = the aggressor SOLD, i.e. a seller-initiated trade at the bid).

Per-minute columns (all from the trades inside the minute, [t, t+1min)):
  n_trades, n_buy, n_sell        aggregated trades; buy = buyer was the taker (is_buyer_maker false)
  volume, buy_vol, sell_vol      base quantity
  notional                       Σ price × quantity (USDT)
  vwap, open, high, low, close   trade prices
  ask_last, bid_last             last taker-buy price and last taker-sell price in the minute:
                                 a taker buy trades at the ask and a taker sell at the bid, so
                                 these are the touch prices as seen by the last trade on each side
  eff_spread_bps                 mean over side flips inside the minute of |p_buy − p_sell| / mid
                                 in bps: the realised bid–ask bounce, an effective-spread estimate
                                 that needs no quote data (NaN if the minute has no flip)
  n_flips                        how many buy/sell alternations the estimate averages over
  last_ms                        transact_time of the last trade (for clock checks)

Output: data/tape/<symbol>.parquet (one file per pair, rewritten per run from the per-day
parts under data/tape/parts/<symbol>/<date>.parquet, so the job is resumable per day).
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data

PARTS = data.PROC / "tape" / "parts"
OUT = data.PROC / "tape"


def summarize_day(zip_path: Path, symbol: str) -> pd.DataFrame:
    t = pd.read_csv(zip_path, usecols=["price", "quantity", "transact_time", "is_buyer_maker"],
                    dtype={"price": "float64", "quantity": "float64", "transact_time": "int64", "is_buyer_maker": "bool"})
    if t.empty:
        return pd.DataFrame()
    t = t.sort_values("transact_time", kind="mergesort").reset_index(drop=True)
    t["minute"] = (t["transact_time"] // 60_000) * 60_000
    t["buy"] = ~t["is_buyer_maker"]
    t["notional"] = t["price"] * t["quantity"]
    # side flips: consecutive trades with opposite aggressor → |Δprice| / mid is one bounce sample
    side = t["buy"].to_numpy()
    px = t["price"].to_numpy()
    flip = np.zeros(len(t), dtype=bool)
    flip[1:] = side[1:] != side[:-1]
    bounce = np.full(len(t), np.nan)
    if len(t) > 1:
        mid = (px[1:] + px[:-1]) / 2
        bounce[1:] = np.where(flip[1:], np.abs(px[1:] - px[:-1]) / mid * 1e4, np.nan)
    t["bounce"] = bounce
    t["buy_qty"] = t["quantity"].where(t["buy"], 0.0)
    t["buy_px"] = t["price"].where(t["buy"])       # NaN on sells → groupby.last() skips NaN
    t["sell_px"] = t["price"].where(~t["buy"])
    g = t.groupby("minute", sort=True)
    out = pd.DataFrame({
        "n_trades": g.size(),
        "n_buy": g["buy"].sum(),
        "volume": g["quantity"].sum(),
        "buy_vol": g["buy_qty"].sum(),
        "notional": g["notional"].sum(),
        "open": g["price"].first(), "high": g["price"].max(), "low": g["price"].min(), "close": g["price"].last(),
        "ask_last": g["buy_px"].last(),
        "bid_last": g["sell_px"].last(),
        "eff_spread_bps": g["bounce"].mean(),
        "n_flips": g["bounce"].count(),
        "last_ms": g["transact_time"].max(),
    })
    out["n_sell"] = out["n_trades"] - out["n_buy"]
    out["sell_vol"] = out["volume"] - out["buy_vol"]
    out["vwap"] = out["notional"] / out["volume"]
    out.index = pd.to_datetime(out.index, unit="ms", utc=True).rename("ts")
    out = out.reset_index()
    out.insert(0, "symbol", symbol)
    return out[["symbol", "ts", "n_trades", "n_buy", "n_sell", "volume", "buy_vol", "sell_vol", "notional",
                "vwap", "open", "high", "low", "close", "ask_last", "bid_last", "eff_spread_bps", "n_flips", "last_ms"]]


def _one_day(symbol: str, d: date, keys: dict[str, str], keep_zip: bool) -> str:
    part = PARTS / symbol / f"{d:%Y-%m-%d}.parquet"
    if part.exists():
        return "skip"
    name = f"{symbol}-aggTrades-{d:%Y-%m-%d}.zip"
    key = keys.get(name)
    if key is None:
        return "missing"
    zp = archive.ROOT / "aggTrades" / symbol / name
    st = archive._fetch(key, zp)
    if st in ("bad", "err"):
        return st
    try:
        df = summarize_day(zp, symbol)
    except Exception as e:  # noqa: BLE001
        print(f"  err summarizing {name}: {e!r}", file=sys.stderr, flush=True)
        return "err"
    part.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(part, index=False)
    if not keep_zip:
        zp.unlink(missing_ok=True)
        zp.with_suffix(".zip.ok").unlink(missing_ok=True)
    return "ok"


def run(symbols: list[str], start: str, end: str | None, workers: int = 6, keep_zip: bool = False) -> None:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else date.today() - timedelta(days=2)
    for sym in symbols:
        keys = {k.rsplit("/", 1)[1]: k for k in archive.list_keys(f"data/futures/um/daily/aggTrades/{sym}/") if k.endswith(".zip")}
        days = [s + timedelta(days=i) for i in range((e - s).days + 1)]
        counts = {"ok": 0, "skip": 0, "bad": 0, "err": 0, "missing": 0}
        # a few workers: each day is a 5–50 MB download plus ~1–3 s of pandas; CPU is 4 cores
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for st in ex.map(lambda d: _one_day(sym, d, keys, keep_zip), days):
                counts[st] += 1
        print(f"tape {sym:<13} {counts}", flush=True)
        build(sym)


def build(symbol: str) -> Path:
    """Concatenate the per-day parts of one pair into data/tape/<symbol>.parquet."""
    parts = sorted((PARTS / symbol).glob("*.parquet"))
    if not parts:
        return OUT / f"{symbol}.parquet"
    df = pd.concat((pd.read_parquet(p) for p in parts), ignore_index=True)
    df = df.sort_values("ts", kind="mergesort").drop_duplicates(["ts"], keep="last").reset_index(drop=True)
    df["symbol"] = df["symbol"].astype("category")
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / f"{symbol}.parquet", index=False)
    print(f"  built {symbol}: {len(df):,} minutes {df['ts'].min():%Y-%m-%d} .. {df['ts'].max():%Y-%m-%d}", flush=True)
    return OUT / f"{symbol}.parquet"
