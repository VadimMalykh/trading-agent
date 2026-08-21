"""Build aligned feature matrix for M1 (microstructure + OHLCV)."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

from config import (
    FEATURE_GROUPS,
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

# Canonical feature-column order. Exposed at module level
# so callers (dataset ablation, audit) can map feature name -> matrix column index
# without hardcoding.
#
# 🔴 NEW COLUMNS GO AT THE END, after the masks. The 19 columns below the marker are
# frozen in that order because every checkpoint written before 2026-08-21 encodes
# them positionally in `meta.norm_stats`, and eval/serve must still be able to
# re-score those checkpoints (that is the whole point of --eval-only). Appending
# keeps LEGACY_FEATURE_COLS == FEATURE_COLS[:19] exactly, so an old checkpoint is
# served the same 19 columns it was trained on; inserting mid-list would silently
# feed it a different feature in every position from the insert onward.
LEGACY_FEATURE_COLS = [
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

# --- C12 additions (2026-08-21) --------------------------------------------------
# Why these and not more microstructure: 12 of the 19 legacy columns are CONSTANT in
# the train window and get zeroed, because the train window opens 2022-08 while the
# book/trade/OI feeds open 2026-07. Any new microstructure column would be zeroed the
# same way. So the model has effectively been reading six numbers per bar — four
# single-bar OHLCV derivatives, one 15-bar vol, and funding — with no multi-timescale
# return, no multi-scale volatility, and no market-wide context at all.
#
# Everything here is derived from candles, which span the full history for every pair.
# Windows are expressed in MINUTES and converted to bars per candle interval, so
# `ret_1h` is one hour at 1m, 5m or 15m rather than a different horizon at each.
OWN_PAIR_MULTISCALE_COLS = [
    "ret_1h",   # trailing return over 1h  — the model had no multi-timescale return
    "ret_4h",   # trailing return over 4h    at all, only the single-bar ret_1
    "ret_1d",   # trailing return over 1d
    "vol_1h",   # rolling std of 1-bar returns over 1h
    "vol_4h",   # ... 4h
    "vol_1d",   # ... 1d  (ret_std_15 was the only volatility scale before this)
]

# Cross-pair / market-wide context. These CANNOT be computed from one symbol's
# candles, which is exactly why they are worth adding: they are the only information
# in this list that the encoder could not in principle have extracted from its own
# 32h window. Filled by `apply_market_context` after every pair's frame exists.
MARKET_CONTEXT_COLS = [
    "btc_rel_ret_1h",  # pair's 1h return minus BTC's — "is this idiosyncratic?"
    "beta_btc_1d",     # rolling 1d beta of the pair's bar returns to BTC's
    "xs_rank_1h",      # cross-sectional rank of the 1h return in the universe, [-1,1]
    "xs_disp_1h",      # cross-sectional dispersion (std) of 1h returns, universe-wide
    "has_market",      # presence mask: 1 where the market context is real, else 0
]

# --- C18 (2026-08-22): selectable feature groups ---------------------------------
# The groups above were already separated, but FEATURE_COLS was their unconditional
# concatenation and FEATURE_DIM was asserted equal to its length, so running a subset
# meant editing this file. FEATURE_GROUPS (config) now composes the list, and the
# dimension is DERIVED from it rather than asserted against a second env var.
#
# Order is fixed by _GROUP_ORDER, never by the order the caller types them, because
# LEGACY_FEATURE_COLS == FEATURE_COLS[:19] is a serving contract (see the note above
# LEGACY_FEATURE_COLS) and the C12 columns must keep their positions relative to it.
_FEATURE_GROUPS = {
    "legacy": LEGACY_FEATURE_COLS,
    "multiscale": OWN_PAIR_MULTISCALE_COLS,
    "market": MARKET_CONTEXT_COLS,
}
_GROUP_ORDER = ["legacy", "multiscale", "market"]


def resolve_feature_groups(spec: str):
    """Parse a FEATURE_GROUPS spec into (group names, column list).

    Raises on an unknown group and on dropping 'legacy' rather than silently
    falling back. A silent fallback on a feature-set knob would make the run
    un-attributable, which is the whole reason this knob exists (trap 0.5.3).
    """
    names = [g.strip().lower() for g in spec.split(",") if g.strip()]
    if not names:
        raise ValueError("FEATURE_GROUPS is empty; expected e.g. 'legacy,multiscale'")
    unknown = [g for g in names if g not in _FEATURE_GROUPS]
    if unknown:
        raise ValueError(
            f"FEATURE_GROUPS has unknown group(s) {unknown}; "
            f"valid groups are {_GROUP_ORDER}"
        )
    if "legacy" not in names:
        raise ValueError(
            "FEATURE_GROUPS must include 'legacy' - the 19 frozen columns are a "
            "serving contract (LEGACY_FEATURE_COLS == FEATURE_COLS[:19])."
        )
    ordered = [g for g in _GROUP_ORDER if g in names]
    cols = []
    for g in ordered:
        cols.extend(_FEATURE_GROUPS[g])
    return ordered, cols


# The full canonical list, independent of FEATURE_GROUPS. Reconstructing the columns
# of a checkpoint that recorded none (pre-C12) is POSITIONAL, so it must index the
# canonical order — not whatever subset this process happens to be configured for, or
# a 30-column checkpoint would be rebuilt from a 25-column list.
ALL_FEATURE_COLS = (
    LEGACY_FEATURE_COLS + OWN_PAIR_MULTISCALE_COLS + MARKET_CONTEXT_COLS
)

ACTIVE_FEATURE_GROUPS, FEATURE_COLS = resolve_feature_groups(FEATURE_GROUPS)

# The dimension the model is actually built with. FEATURE_DIM in config.py remains
# the documented default (30); this is the number everything downstream must use.
FEATURE_DIM_EFFECTIVE = len(FEATURE_COLS)

# Trailing windows, in minutes, for the multi-scale columns above.
_SCALE_MINUTES = {"1h": 60, "4h": 240, "1d": 1440}

# C15 (2026-08-22): the beta denominator is masked when BTC's rolling variance falls
# below this FRACTION of its own median variance. The previous guard was an absolute
# 1e-12, roughly six orders of magnitude below a real var(ret_1) (~2.3e-6 at 5m), so
# it never fired -- an absolute constant is not a floor unless it is on the data's
# scale. A relative floor means the same thing at 1m, 5m and 15m and for a quiet pair
# as for a loud one.
BETA_VAR_FLOOR_FRAC = float(os.environ.get("BETA_VAR_FLOOR_FRAC", "0.01"))
BAR_MINUTES_BY_INTERVAL = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}


def bars_for_minutes(candle_interval: str, minutes: int) -> int:
    """Bars spanning `minutes` at `candle_interval`; raises on an unknown interval.

    Deliberately not a silent fallback to 1m: that would make `ret_1d` mean one day
    on some runs and 1/15th of a day on others while still producing a plausible
    column (cf. the R3 silent-primary-fallback lesson).
    """
    bar = BAR_MINUTES_BY_INTERVAL.get(candle_interval)
    if bar is None:
        raise ValueError(
            f"candle_interval={candle_interval!r} is not a known bar size "
            f"(known: {sorted(BAR_MINUTES_BY_INTERVAL)})."
        )
    return max(1, minutes // bar)

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
    feature_cols: list | None = None,
) -> pd.DataFrame:
    """
    Align candles with nearest book/trade/funding/OI features.
    Returns DataFrame indexed by open_time with the requested columns + close.
    When max_rows is set, only the last N candles are loaded (saves memory for inference).

    `feature_cols` defaults to the current FEATURE_COLS. Pass a checkpoint's own
    recorded column list to re-score or serve an older model: a 19-column checkpoint
    must be fed exactly the 19 columns it was trained on, not today's 29.
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

    # --- C12: own-pair multi-scale returns and volatility ------------------------
    # Trailing (backward-looking) returns and vols: at bar t these use bars <= t only,
    # so they are lookahead-free by construction. `min_periods=1` keeps the early bars
    # usable rather than NaN-then-zero, which would otherwise put a long block of
    # artificial zeros at the head of every pair's history.
    close_s = feat["close"]
    for name, minutes in _SCALE_MINUTES.items():
        n = bars_for_minutes(candle_interval, minutes)
        feat[f"ret_{name}"] = (close_s / close_s.shift(n) - 1.0).fillna(0.0)
        feat[f"vol_{name}"] = (
            feat["ret_1"].rolling(n, min_periods=2).std().fillna(0.0)
        )

    # Market-context columns are cross-pair and cannot be computed from one symbol.
    # They are created here (as zeros, mask off) so the column set and its order are
    # identical whether or not a caller runs the second pass — a frame is never
    # silently short a column.
    for c in MARKET_CONTEXT_COLS:
        feat[c] = 0.0

    cols = [c for c in (feature_cols or FEATURE_COLS)]
    missing = [c for c in cols if c not in feat.columns]
    if missing:
        raise ValueError(f"build_feature_frame: unknown feature columns {missing}")
    out = feat[cols + ["close"]].replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return out


def market_context_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    """The small per-pair slice `apply_market_context` needs, as a 2-column frame.

    Kept deliberately narrow: the cross-pair pass runs after every pair's matrix
    already exists, and holding 8-12 full feature frames at once to compute four
    columns would roughly double peak memory on a 2.9M-sample bundle for no reason.
    """
    return frame[["ret_1", "ret_1h"]]


def build_market_inputs(
    symbol: str,
    candle_interval: str = "1m",
    max_rows: int | None = None,
) -> pd.DataFrame:
    """Candles-only version of `market_context_inputs`, for the serving path.

    Training already has every pair's full feature frame in hand, so it slices the
    two columns it needs. Serving does not: it predicts one symbol at a time, so the
    other pairs' inputs must be loaded on purpose. Going through
    `build_feature_frame` would run the book / trade / funding / OI joins for each of
    them as well — four extra queries per pair per refresh, for two columns that are
    derived from `close` alone.
    """
    if max_rows is not None:
        candles = db.load_candles_tail(symbol, candle_interval, n=max_rows)
    else:
        candles = db.load_candles(symbol, candle_interval)
    if candles.empty:
        return pd.DataFrame(columns=["ret_1", "ret_1h"])
    candles = candles.set_index("open_time").sort_index()
    close = candles["close"].astype(float)
    n1h = bars_for_minutes(candle_interval, _SCALE_MINUTES["1h"])
    return pd.DataFrame(
        {
            "ret_1": close.pct_change().fillna(0.0),
            "ret_1h": (close / close.shift(n1h) - 1.0).fillna(0.0),
        },
        index=candles.index,
    ).replace([np.inf, -np.inf], 0.0)


def apply_market_context(
    per_pair: dict,
    candle_interval: str = "1m",
    btc_symbol: str = "BTCUSDT",
) -> dict:
    """
    Compute the cross-pair columns for every pair, aligned to that pair's own bars.

    `per_pair` maps symbol -> the 2-column frame from `market_context_inputs`, each
    indexed by its own bar timestamps. Pairs list at different dates, so the bar
    grids are ragged; everything below joins on the timestamp index rather than
    assuming a shared length.

    Returns symbol -> DataFrame of MARKET_CONTEXT_COLS on that symbol's index.

    All four signals are backward-looking at each bar:
      btc_rel_ret_1h  pair 1h return minus BTC's 1h return over the same bars
      beta_btc_1d     rolling cov(pair ret_1, btc ret_1) / var(btc ret_1) over 1d
      xs_rank_1h      rank of the pair's 1h return among the pairs that HAVE a bar
                      at t, mapped to [-1, 1]; 0 when only one pair is present
      xs_disp_1h      cross-sectional std of those same 1h returns (identical for
                      every pair at a given bar — it describes the market, not the
                      pair)
      has_market      0 where BTC has no bar at t, or fewer than two pairs do, so a
                      degenerate context reads as MISSING rather than as a real zero
                      (the same reason the book/trade columns carry presence masks)
    """
    symbols = [s for s in per_pair if per_pair[s] is not None and len(per_pair[s])]
    out = {}
    if not symbols:
        return out

    # One union grid for the cross-sectional statistics.
    ret1h = pd.DataFrame({s: per_pair[s]["ret_1h"] for s in symbols})
    n_present = ret1h.notna().sum(axis=1)
    # Rank within each bar, scaled to [-1, 1]; a single present pair has no
    # cross-section, so it ranks 0 rather than an arbitrary extreme.
    ranks = ret1h.rank(axis=1, method="average")
    denom = (n_present - 1).replace(0, np.nan)
    scaled_rank = (2.0 * (ranks.sub(1.0, axis=0)).div(denom, axis=0) - 1.0)
    disp = ret1h.std(axis=1, ddof=0)

    beta_bars = bars_for_minutes(candle_interval, _SCALE_MINUTES["1d"])
    btc = per_pair.get(btc_symbol)
    if btc is not None and len(btc):
        btc_ret1 = btc["ret_1"]
        btc_ret1h = btc["ret_1h"]
        btc_var = btc_ret1.rolling(beta_bars, min_periods=2).var()
        # C15 (2026-08-22): a RELATIVE floor for the beta denominator. The old guard
        # was `btc_var > 1e-12`, roughly six orders of magnitude below a real
        # var(ret_1) (~2.3e-6 at 5m), so it floored nothing in practice — it is trap
        # §0.5.5 (an absolute constant is not a floor unless it is on the data's
        # scale). Scale it to the series' own typical variance instead, so the guard
        # means the same thing at 1m, 5m and 15m and for a quiet pair as for a loud
        # one. Windows below the floor are masked, not divided.
        _typ_var = float(np.nanmedian(btc_var.to_numpy()))
        btc_var_floor = (
            _typ_var * BETA_VAR_FLOOR_FRAC
            if np.isfinite(_typ_var) and _typ_var > 0.0
            else 1e-12
        )
    else:
        btc_ret1 = btc_ret1h = btc_var = None
        btc_var_floor = 1e-12

    for s in symbols:
        idx = per_pair[s].index
        df = pd.DataFrame(index=idx)
        has = pd.Series(1.0, index=idx)

        if btc_ret1 is None:
            # No BTC in the universe: the relative/beta columns have no meaning.
            df["btc_rel_ret_1h"] = 0.0
            df["beta_btc_1d"] = 0.0
            has[:] = 0.0
        else:
            b_1h = btc_ret1h.reindex(idx)
            b_1 = btc_ret1.reindex(idx)
            b_var = btc_var.reindex(idx)
            df["btc_rel_ret_1h"] = (per_pair[s]["ret_1h"] - b_1h).fillna(0.0)
            if s == btc_symbol:
                # C15 (2026-08-22): BTC's beta against itself is cov(r,r)/var(r) = 1
                # identically, so the column carries no information for this row. It
                # used to be *computed*, which produced 1.0 everywhere except the
                # warm-up and sub-floor bars that fell through to 0.0 — a raw std of
                # ~1e-3, comfortably above the 1e-8 CONSTANT detector, so it was not
                # zeroed and the per-pair normalizer rendered those few bars as a
                # 590-sigma spike (Q3; BTC's worst tail before C12 was 66 sigma on
                # hl_range). Emit a clean constant instead and let the degenerate
                # handler zero it, exactly as it does for btc_rel_ret_1h on this row.
                df["beta_btc_1d"] = 0.0
            else:
                cov = (
                    per_pair[s]["ret_1"]
                    .rolling(beta_bars, min_periods=2)
                    .cov(b_1)
                )
                # A near-zero BTC variance makes beta explode; treat it as no
                # information rather than dividing by ~0 (the 2026-08-17
                # additive-epsilon lesson — this is a floor with a mask, not an
                # epsilon). The floor is relative to BTC's own typical variance;
                # see where btc_var_floor is computed.
                ok_var = b_var > btc_var_floor
                df["beta_btc_1d"] = np.where(ok_var, cov / b_var.where(ok_var), 0.0)
            has = has.where(b_1h.notna(), 0.0)

        df["xs_rank_1h"] = scaled_rank[s].reindex(idx).fillna(0.0)
        df["xs_disp_1h"] = disp.reindex(idx).fillna(0.0)
        # Fewer than two pairs at a bar means there is no cross-section to speak of.
        df["has_market"] = (
            has.where(n_present.reindex(idx).fillna(0) >= 2, 0.0).astype(float)
        )
        out[s] = (
            df[MARKET_CONTEXT_COLS].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        )
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
