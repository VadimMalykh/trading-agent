"""Build aligned feature matrix for M1 (microstructure + OHLCV)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import FEATURE_DIM
from data import db


def _safe_div(a, b, default=0.0):
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, a / b, default)
    return out


def build_feature_frame(symbol: str, candle_interval: str = "1m") -> pd.DataFrame:
    """
    Align candles with nearest book/trade/funding/OI features.
    Returns DataFrame indexed by open_time with FEATURE_DIM columns + close for labels.
    """
    candles = db.load_candles(symbol, candle_interval)
    if candles.empty or len(candles) < 40:
        return pd.DataFrame()

    candles = candles.set_index("open_time").sort_index()
    feat = pd.DataFrame(index=candles.index)

    # OHLCV-derived (raw-ish, not hand TA indicators)
    feat["ret_1"] = candles["close"].pct_change().fillna(0.0)
    feat["hl_range"] = _safe_div(candles["high"] - candles["low"], candles["close"])
    feat["oc_range"] = _safe_div(candles["close"] - candles["open"], candles["open"])
    feat["log_vol"] = np.log1p(candles["volume"].astype(float))
    feat["close"] = candles["close"].astype(float)

    # Order book (asof join)
    book = db.load_orderbook(symbol)
    if not book.empty:
        book = book.set_index("ts").sort_index()
        book_aligned = book.reindex(feat.index, method="ffill")
        feat["spread_bps"] = _safe_div(book_aligned["spread"], book_aligned["mid"]) * 1e4
        feat["imbalance"] = book_aligned["imbalance"].fillna(0.0)
        feat["micro_mid"] = _safe_div(
            book_aligned["microprice"] - book_aligned["mid"], book_aligned["mid"]
        )
        feat["bid_ask_vol_ratio"] = _safe_div(
            book_aligned["bid_volume"], book_aligned["ask_volume"] + 1e-9
        )
        feat["depth_near_imb"] = _safe_div(
            book_aligned["bid_depth_near"] - book_aligned["ask_depth_near"],
            book_aligned["bid_depth_near"] + book_aligned["ask_depth_near"] + 1e-9,
        )
    else:
        for c in ["spread_bps", "imbalance", "micro_mid", "bid_ask_vol_ratio", "depth_near_imb"]:
            feat[c] = 0.0

    # Trade flow
    trades = db.load_market_trades(symbol)
    if not trades.empty:
        trades = trades.set_index("window_start").sort_index()
        t_aligned = trades.reindex(feat.index, method="ffill")
        feat["trade_count"] = t_aligned["trade_count"].fillna(0.0)
        feat["buy_sell_imb"] = _safe_div(
            t_aligned["buy_volume"] - t_aligned["sell_volume"],
            t_aligned["buy_volume"] + t_aligned["sell_volume"] + 1e-9,
        )
        feat["trade_vol"] = np.log1p(t_aligned["volume"].fillna(0.0).astype(float))
    else:
        feat["trade_count"] = 0.0
        feat["buy_sell_imb"] = 0.0
        feat["trade_vol"] = 0.0

    # Funding / OI
    funding = db.load_funding(symbol)
    if not funding.empty:
        funding = funding.set_index("ts").sort_index()
        f_aligned = funding.reindex(feat.index, method="ffill")
        feat["funding"] = f_aligned["last_funding_rate"].fillna(0.0)
    else:
        feat["funding"] = 0.0

    oi = db.load_open_interest(symbol)
    if not oi.empty:
        oi = oi.set_index("ts").sort_index()
        o_aligned = oi.reindex(feat.index, method="ffill")
        feat["oi"] = np.log1p(o_aligned["open_interest"].fillna(0.0).astype(float))
        feat["oi_chg"] = o_aligned["open_interest"].pct_change().fillna(0.0)
    else:
        feat["oi"] = 0.0
        feat["oi_chg"] = 0.0

    # Rolling vol (simple, not a classic indicator package)
    feat["ret_std_15"] = feat["ret_1"].rolling(15, min_periods=1).std().fillna(0.0)

    feature_cols = [
        "ret_1",
        "hl_range",
        "oc_range",
        "log_vol",
        "spread_bps",
        "imbalance",
        "micro_mid",
        "bid_ask_vol_ratio",
        "depth_near_imb",
        "trade_count",
        "buy_sell_imb",
        "trade_vol",
        "funding",
        "oi",
        "oi_chg",
        "ret_std_15",
    ]
    assert len(feature_cols) == FEATURE_DIM

    out = feat[feature_cols + ["close"]].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return out


def make_labels(close: pd.Series, horizon_bars: int, flat_threshold: float) -> pd.Series:
    """Direction: 0=down, 1=flat, 2=up based on forward return over horizon_bars."""
    fwd = close.shift(-horizon_bars) / close - 1.0
    labels = pd.Series(1, index=close.index, dtype=int)  # flat default
    labels[fwd > flat_threshold] = 2
    labels[fwd < -flat_threshold] = 0
    labels[fwd.isna()] = -1  # invalid
    return labels
