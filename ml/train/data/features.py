"""Build aligned feature matrix for M1 (microstructure + OHLCV)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    FEATURE_DIM,
    BOOK_MAX_AGE_MIN,
    TRADES_MAX_AGE_MIN,
    FUNDING_OI_MAX_AGE_MIN,
    LABEL_MODE,
    TB_TP_MULT,
    TB_SL_MULT,
    TB_VOL_WINDOW,
    TB_MIN_BARRIER,
)
from data import db

# Canonical feature-column order (must match FEATURE_DIM). Exposed at module level
# so callers (dataset ablation, audit) can map feature name -> matrix column index
# without hardcoding. The 16 signal features come first (stable indices), then the
# 3 presence masks.
FEATURE_COLS = [
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
    "has_book",
    "has_trades",
    "has_funding_oi",
]
assert len(FEATURE_COLS) == FEATURE_DIM

# The microstructure ("book") features — order-book + trade-flow + funding/OI —
# i.e. everything except the 4 OHLCV-derived cols, rolling vol, and the masks.
# Used for the dense-window ablation (book-ON vs book-OFF).
BOOK_FEATURES = [
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
]


def _safe_div(a, b, default=0.0):
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, a / b, default)
    return out


def _align_with_age(src: pd.DataFrame, grid: pd.Index) -> tuple[pd.DataFrame, np.ndarray]:
    """asof-ffill `src` (indexed by its own timestamps) onto the candle `grid`, and
    return (aligned_frame, age_minutes) where age_minutes[i] is how stale the
    forward-filled source row is at grid bar i.

    `src.index` is the source's real timestamps; we ffill both the source columns
    AND the source timestamp itself, so age = grid_time - ffilled_source_time. Bars
    before the first source row get age = +inf (nothing to fill → genuinely missing).
    """
    aligned = src.reindex(grid, method="ffill")
    # Carry the source timestamp through the same ffill to recover per-bar age. Build
    # it as a tz-aware DatetimeIndex so .asi8 gives consistent UTC-ns for both sides
    # (a plain object Series of tz-aware Timestamps does not convert cleanly).
    src_ts = pd.DatetimeIndex(src.index).to_series(index=src.index).reindex(
        grid, method="ffill"
    )
    src_ts = pd.DatetimeIndex(src_ts)  # NaT-safe; .asi8 → int64 ns (NaT = sentinel)
    grid_ns = pd.DatetimeIndex(grid).asi8  # UTC ns since epoch
    src_ns = src_ts.asi8
    age_min = (grid_ns - src_ns) / 6e10  # ns → minutes
    # Pre-first-row bars have NaT source → force +inf age (genuinely missing).
    age_min = np.where(np.asarray(src_ts.isna()), np.inf, age_min)
    return aligned, age_min


def _stale_mask(age_min: np.ndarray, max_age_min: float) -> np.ndarray:
    """True where the ffilled source is too old to trust (or absent). max_age_min<=0
    disables the cap (legacy unbounded ffill; only absence counts as stale)."""
    if max_age_min and max_age_min > 0:
        return ~np.isfinite(age_min) | (age_min > max_age_min)
    return ~np.isfinite(age_min)


def build_feature_frame(
    symbol: str,
    candle_interval: str = "1m",
    max_rows: int | None = None,
) -> pd.DataFrame:
    """
    Align candles with nearest book/trade/funding/OI features.
    Returns DataFrame indexed by open_time with FEATURE_DIM columns + close for labels.
    When max_rows is set, only the last N candles are loaded (saves memory for inference).
    """
    if max_rows is not None:
        candles = db.load_candles_tail(symbol, candle_interval, n=max_rows)
    else:
        candles = db.load_candles(symbol, candle_interval)
    if candles.empty or len(candles) < 40:
        return pd.DataFrame()

    min_time = candles["open_time"].iloc[0].isoformat() if max_rows is not None else None

    candles = candles.set_index("open_time").sort_index()
    feat = pd.DataFrame(index=candles.index)

    # OHLCV-derived (raw-ish, not hand TA indicators)
    feat["ret_1"] = candles["close"].pct_change().fillna(0.0)
    feat["hl_range"] = _safe_div(candles["high"] - candles["low"], candles["close"])
    feat["oc_range"] = _safe_div(candles["close"] - candles["open"], candles["open"])
    feat["log_vol"] = np.log1p(candles["volume"].astype(float))
    feat["close"] = candles["close"].astype(float)

    # Order book (asof join). Presence mask lets the model tell real zeros from
    # "no book data" (per-row: forward-filled book known at that bar, else 0).
    book = db.load_orderbook(symbol, since=min_time)
    book_cols = ["spread_bps", "imbalance", "micro_mid", "bid_ask_vol_ratio", "depth_near_imb"]
    if not book.empty:
        book = book.set_index("ts").sort_index()
        book_aligned, book_age = _align_with_age(book, feat.index)
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
        # Staleness cap: a snapshot older than BOOK_MAX_AGE_MIN (or absent) is
        # treated as MISSING — zero the features and drop the presence mask — so a
        # frozen snapshot forward-filled across a collection outage can't masquerade
        # as live book (see docs/NEXT_TRAINING_PLAN.md TASK 1).
        stale = _stale_mask(book_age, BOOK_MAX_AGE_MIN)
        for c in book_cols:
            feat.loc[stale, c] = 0.0
        feat["has_book"] = (~stale).astype(np.float32)
    else:
        for c in book_cols:
            feat[c] = 0.0
        feat["has_book"] = 0.0

    # Trade flow
    trades = db.load_market_trades(symbol, since=min_time)
    trade_cols = ["trade_count", "buy_sell_imb", "trade_vol"]
    if not trades.empty:
        trades = trades.set_index("window_start").sort_index()
        t_aligned, t_age = _align_with_age(trades, feat.index)
        feat["trade_count"] = t_aligned["trade_count"].fillna(0.0)
        feat["buy_sell_imb"] = _safe_div(
            t_aligned["buy_volume"] - t_aligned["sell_volume"],
            t_aligned["buy_volume"] + t_aligned["sell_volume"] + 1e-9,
        )
        feat["trade_vol"] = np.log1p(t_aligned["volume"].fillna(0.0).astype(float))
        # Staleness cap (same rationale as book): stale/absent trade-flow → missing.
        stale = _stale_mask(t_age, TRADES_MAX_AGE_MIN)
        for c in trade_cols:
            feat.loc[stale, c] = 0.0
        feat["has_trades"] = (~stale).astype(np.float32)
    else:
        for c in trade_cols:
            feat[c] = 0.0
        feat["has_trades"] = 0.0

    # Funding / OI. One shared presence flag: 1.0 where EITHER funding or OI is
    # known at/before this bar (both are low-frequency, ffilled series).
    # has_funding_oi = 1 where EITHER source is fresh (within FUNDING_OI_MAX_AGE_MIN);
    # each source's own features are zeroed on the bars where IT is stale/absent.
    has_funding_oi = np.zeros(len(feat), dtype=np.float32)

    funding = db.load_funding(symbol, since=min_time)
    if not funding.empty:
        funding = funding.set_index("ts").sort_index()
        f_aligned, f_age = _align_with_age(funding, feat.index)
        f_stale = _stale_mask(f_age, FUNDING_OI_MAX_AGE_MIN)
        feat["funding"] = f_aligned["last_funding_rate"].fillna(0.0)
        feat.loc[f_stale, "funding"] = 0.0
        has_funding_oi = np.maximum(has_funding_oi, (~f_stale).astype(np.float32))
    else:
        feat["funding"] = 0.0

    oi = db.load_open_interest(symbol, since=min_time)
    if not oi.empty:
        oi = oi.set_index("ts").sort_index()
        o_aligned, o_age = _align_with_age(oi, feat.index)
        o_stale = _stale_mask(o_age, FUNDING_OI_MAX_AGE_MIN)
        feat["oi"] = np.log1p(o_aligned["open_interest"].fillna(0.0).astype(float))
        feat["oi_chg"] = o_aligned["open_interest"].pct_change().fillna(0.0)
        feat.loc[o_stale, "oi"] = 0.0
        feat.loc[o_stale, "oi_chg"] = 0.0
        has_funding_oi = np.maximum(has_funding_oi, (~o_stale).astype(np.float32))
    else:
        feat["oi"] = 0.0
        feat["oi_chg"] = 0.0

    feat["has_funding_oi"] = has_funding_oi

    # Rolling vol (simple, not a classic indicator package)
    feat["ret_std_15"] = feat["ret_1"].rolling(15, min_periods=1).std().fillna(0.0)

    out = feat[FEATURE_COLS + ["close"]].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return out


def forward_return(close: pd.Series, horizon_bars: int) -> pd.Series:
    """Raw forward return over horizon_bars (NaN at the tail where unknown)."""
    return close.shift(-horizon_bars) / close - 1.0


def labels_from_return(fwd: pd.Series, flat_threshold: float) -> pd.Series:
    """Discretize a forward-return series into 0=down / 1=flat / 2=up / -1=invalid."""
    labels = pd.Series(1, index=fwd.index, dtype=int)  # flat default
    labels[fwd > flat_threshold] = 2
    labels[fwd < -flat_threshold] = 0
    labels[fwd.isna()] = -1  # invalid
    return labels


def make_labels(close: pd.Series, horizon_bars: int, flat_threshold: float) -> pd.Series:
    """Direction: 0=down, 1=flat, 2=up based on forward return over horizon_bars."""
    return labels_from_return(forward_return(close, horizon_bars), flat_threshold)


def triple_barrier_labels(
    close: pd.Series,
    horizon_bars: int,
    tp_mult: float = TB_TP_MULT,
    sl_mult: float = TB_SL_MULT,
    vol_window: int = TB_VOL_WINDOW,
    min_barrier: float = TB_MIN_BARRIER,
) -> pd.Series:
    """Triple-barrier direction label: 0=down / 1=flat(timeout) / 2=up / -1=invalid.

    From each bar t, walk forward up to ``horizon_bars`` and check whether the
    close crosses a volatility-scaled +TP or -SL barrier first:
      UP   (2) if close >= entry*(1 + tp) before close <= entry*(1 - sl)
      DOWN (0) if the -SL barrier is touched first
      FLAT (1) if neither barrier is hit by the horizon (timeout)

    Barriers are per-bar volatility-scaled: tp = tp_mult * sigma, sl = sl_mult *
    sigma, where sigma = rolling std of 1-bar returns over ``vol_window`` bars,
    floored at ``min_barrier`` so a dead-flat window still uses a sane band. This
    labels what a TP/SL trade would REALIZE, unlike the fixed-Δt endpoint sign.

    Tail bars without a full ``horizon_bars`` lookahead are -1 (invalid), matching
    ``labels_from_return`` semantics so downstream validity masks drop them.

    Uses close-to-barrier crossing (no intrabar high/low), a standard tradeable-
    label approximation; on 1m bars over 30m+ horizons the discretization error is
    small relative to the vol-scaled band.
    """
    c = close.to_numpy(dtype=np.float64)
    n = c.shape[0]
    ret1 = np.zeros(n, dtype=np.float64)
    ret1[1:] = c[1:] / c[:-1] - 1.0
    sigma = (
        pd.Series(ret1).rolling(vol_window, min_periods=1).std().fillna(0.0).to_numpy()
    )
    tp = np.maximum(tp_mult * sigma, min_barrier)
    sl = np.maximum(sl_mult * sigma, min_barrier)

    labels = np.full(n, -1, dtype=np.int64)
    last_valid = n - horizon_bars  # bars [0, last_valid) have a full lookahead
    for t in range(max(0, last_valid)):
        entry = c[t]
        up_barrier = entry * (1.0 + tp[t])
        dn_barrier = entry * (1.0 - sl[t])
        lab = 1  # timeout / flat default
        hi = t + horizon_bars
        for j in range(t + 1, hi + 1):
            cj = c[j]
            if cj >= up_barrier:
                lab = 2
                break
            if cj <= dn_barrier:
                lab = 0
                break
        labels[t] = lab
    return pd.Series(labels, index=close.index, dtype=int)


def make_labels_and_returns(
    close: pd.Series,
    horizon_bars: int,
    flat_threshold: float,
    label_mode: str = LABEL_MODE,
) -> tuple[pd.Series, pd.Series]:
    """Return (3-class labels, raw forward return) sharing one fwd computation.

    The raw forward return is always the fixed-Δt forward return (the regression
    target for the quantile head and the realized P&L per trade). The 3-class /
    directional labels are derived per ``label_mode``:
      "fixed"          -> sign of the fixed-Δt forward return vs flat_threshold
                          (legacy, byte-identical to the served recipe).
      "triple_barrier" -> volatility-scaled TP/SL/timeout (see triple_barrier_labels).

    Invalid tail bars are -1 in the labels and NaN in the returns (masked out
    downstream).
    """
    fwd = forward_return(close, horizon_bars)
    if label_mode == "triple_barrier":
        labels = triple_barrier_labels(close, horizon_bars)
        # Keep the invalid-tail semantics aligned with the return series so the
        # validity mask (label >= 0) and NaN forward returns agree.
        labels[fwd.isna()] = -1
        return labels, fwd
    return labels_from_return(fwd, flat_threshold), fwd
