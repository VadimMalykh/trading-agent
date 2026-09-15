"""P1 — the collector's raw order-book ladder (`orderbook_levels`, up to 100 levels a side,
~12 s cadence, 2026-08-05 →) reduced to what pricing a trade needs: per snapshot, the touch,
the notional resting near the touch, and the slippage a market order of a given notional
would have paid walking the book.

Raw row (scripts/export.sh levels): symbol, ts, event_time, transaction_time, last_update_id,
depth, bids, asks — `bids`/`asks` are JSON arrays of [price, quantity], best first.

Per-snapshot output columns (data/ladder/<symbol>.parquet):
  best_bid, best_ask, mid, spread_bps             the touch; spread = (ask − bid) / mid in bps
  n_bid, n_ask                                    levels present (100 when the ladder is full)
  bid_extent_bps, ask_extent_bps                  how far from mid the last level sits — a
                                                  notional that needs more than the ladder holds
                                                  is censored (NaN below), not extrapolated
  usd_bid_02, usd_ask_02, usd_bid_1, usd_ask_1    notional resting within 0.2 % and 1 % of mid
                                                  (the archive `depth` table's bands, for scaling
                                                  impact back in time)
  slip_buy_<N>, slip_sell_<N>                     for each notional N (USDT) in NOTIONALS: the
                                                  fill VWAP of a market order of N versus mid, in
                                                  bps, positive = paid. Includes the half-spread;
                                                  impact beyond the touch is slip − spread_bps/2.
                                                  NaN if the ladder holds less than N on that side.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

NOTIONALS = [1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000]   # USDT, per side
BANDS = [0.002, 0.01]                                                          # 0.2 % and 1 % of mid


def slip_col(side: str, n: int) -> str:
    return f"slip_{side}_{n}"


SLIP_COLS = [slip_col(s, n) for s in ("buy", "sell") for n in NOTIONALS]
COLS = ["symbol", "ts", "event_time", "best_bid", "best_ask", "mid", "spread_bps", "n_bid", "n_ask",
        "bid_extent_bps", "ask_extent_bps", "usd_bid_02", "usd_ask_02", "usd_bid_1", "usd_ask_1", *SLIP_COLS]


def walk(px: np.ndarray, qty: np.ndarray, mid: float, notionals: list[int]) -> np.ndarray:
    """Slippage (bps of mid, positive = worse than mid) of filling each notional against one side
    of the book. `px` is best-first (ascending asks or descending bids). NaN where the side holds
    less than the notional."""
    notion = px * qty
    cum_n = np.cumsum(notion)
    cum_q = np.cumsum(qty)
    out = np.full(len(notionals), np.nan)
    for i, n in enumerate(notionals):
        k = int(np.searchsorted(cum_n, n))          # first level at which cumulative notional ≥ n
        if k >= len(cum_n):
            continue
        prev_n = cum_n[k - 1] if k else 0.0
        prev_q = cum_q[k - 1] if k else 0.0
        q = prev_q + (n - prev_n) / px[k]
        out[i] = abs(n / q / mid - 1.0) * 1e4
    return out


def summarize(bids_json: str, asks_json: str) -> list[float]:
    """One raw ladder row → the numeric columns of COLS after `event_time` (same order)."""
    b = np.asarray(json.loads(bids_json), dtype=float)
    a = np.asarray(json.loads(asks_json), dtype=float)
    if b.ndim != 2 or a.ndim != 2 or len(b) == 0 or len(a) == 0:
        return [np.nan] * (len(COLS) - 3)
    bpx, bq = b[:, 0], b[:, 1]
    apx, aq = a[:, 0], a[:, 1]
    best_bid, best_ask = bpx[0], apx[0]
    mid = (best_bid + best_ask) / 2
    band_usd = []
    for pct in BANDS:
        band_usd.append(float((bpx * bq)[bpx >= mid * (1 - pct)].sum()))
        band_usd.append(float((apx * aq)[apx <= mid * (1 + pct)].sum()))
    return [best_bid, best_ask, mid, (best_ask - best_bid) / mid * 1e4, len(bpx), len(apx),
            (mid - bpx[-1]) / mid * 1e4, (apx[-1] - mid) / mid * 1e4, *band_usd,
            *walk(apx, aq, mid, NOTIONALS), *walk(bpx, bq, mid, NOTIONALS)]


def summarize_frame(chunk: pd.DataFrame) -> pd.DataFrame:
    rows = [summarize(b, a) for b, a in zip(chunk["bids"].to_numpy(), chunk["asks"].to_numpy())]
    out = pd.DataFrame(rows, columns=COLS[3:])
    out.insert(0, "event_time", pd.to_datetime(chunk["event_time"].to_numpy(), utc=True, format="ISO8601"))
    out.insert(0, "ts", pd.to_datetime(chunk["ts"].to_numpy(), utc=True, format="ISO8601"))
    out.insert(0, "symbol", chunk["symbol"].to_numpy())
    out["n_bid"] = out["n_bid"].astype("Int16")
    out["n_ask"] = out["n_ask"].astype("Int16")
    return out
