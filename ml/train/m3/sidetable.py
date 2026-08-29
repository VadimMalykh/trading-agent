"""M3-0b (+ BOOK_ERA_PLAN B0) — the price/funding side-table.

WHAT THIS UNLOCKS, AND WHY IT IS A SEPARATE STEP. `m3/backtest.py` can only exit at 60,
240 or 1440 minutes, because those are the horizons the eval dumps carry a `fwd_ret` for
and it reads no price series at all. That bounds M3 in four places at once:

  1. **Barrier exits** — the open C4b mismatch. Under triple-barrier labels the model
     predicts a TP/SL outcome while `simulate_pnl` books `fwd_ret` at a fixed `hold_bars`.
     Deciding whether that matters needs the path between entry and exit, not its endpoint.
  2. **Funding** — at a 4h hold this is a real term in the P&L and it is *signed*: it can
     pay you. Every M3 number to date silently sets it to zero.
  3. **Position-state observations** — M3-3's feature vector had to leave out unrealised
     P&L, time-in-trade drawdown and the like, for want of a price path.
  4. **M3-5's catastrophe brake** — the live `auto` path attaches a stop and a target, which
     is an unmeasured deviation from the fixed 4h hold the policy was actually scored on.

THE ALIGNMENT IS SHARED, DELIBERATELY. BOOK_ERA_PLAN B0 wants the same `(pair, ts)` grid
with book columns added. Building it twice risks two different alignments and neither being
evidence about the other, so the book columns are built here, by this module, from the same
grid function — `build_price_table` for M3-0b's full validation window, `build_book_era` for
B0's book era.

🔴 THE ACCEPTANCE TEST IS THE GATE, NOT A FORMALITY. `fwd_ret_240` rebuilt here must match
the eval dumps' own `fwd_ret` on a `(pair, ts)` join. This is the same discipline that made
`reaggregate_preds.py` credible: the side-table's whole claim is that it describes the same
market the dumps describe, and a rebuilt price path that disagrees with the dump is
measuring a different series. If it does not match, nothing downstream is evidence. Run
`m3 sidetable` and read TEST 1 before using any other function in this module.

TWO WINDOWS, TWO EXPORTS. The book and tape begin 2026-08-05, but the dumps' validation
window opens 2025-12-10 — so M3-0b's price path is exported separately and more widely than
M3-4's book era (see the header of scripts/gcp_m3_export.sh). `EXPORT_DIR` holds the wide
price/funding slice; `BOOK_DIR` holds the book-era ones.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .bookprep import EXPORT_DIR as BOOK_DIR
from .bookprep import _csv, load_snapshots, load_trades

# Where the wide price/funding slice lands. Separate from BOOK_DIR because it spans the
# whole validation window rather than the book era, and because overwriting the m3_4 export
# would break M3-4's byte-identical reproduction.
EXPORT_DIR = os.environ.get("M3_SIDE_DIR", "/workspace/train/output/m3_0b")

BAR_MINUTES = {"1m": 1, "5m": 5}

# The horizons B0 asks for. 240 is the one the acceptance test runs on, because it is the
# policy's primary horizon and the dumps carry it.
HORIZONS_MIN = (5, 15, 60, 240)

# Training's staleness caps (ml/train/config.py). Re-stated rather than imported because
# `config.py` reads them from the environment and this module must pin what the *training
# run* used, not what a container happens to be configured with today. B0 §B0 requires the
# side-table use the same caps as training; a different cap is a different alignment.
BOOK_MAX_AGE = 5.0
TRADES_MAX_AGE = 5.0
FUNDING_OI_MAX_AGE = 480.0


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def load_candles(interval: str = "5m", export_dir: str | None = None) -> pd.DataFrame:
    """The exported candle slice, as `(pair, ts, open, high, low, close, volume)`.

    `ts` is int64 UTC nanoseconds, matching the dumps' own `ts` encoding, so every join
    downstream is an exact integer join rather than a float-tolerant timestamp compare.
    """
    d = export_dir or EXPORT_DIR
    df = _csv(f"candles_{interval}", ["open_time", "close_time"], export_dir=d)
    out = pd.DataFrame({
        "pair": df["symbol"].astype(str),
        "ts": pd.DatetimeIndex(df["open_time"]).asi8,
    })
    for c in ("open", "high", "low", "close", "volume"):
        out[c] = df[c].astype("float64")
    # mergesort keeps this stable, which matters because forward returns below are a
    # POSITIONAL shift and a non-deterministic order would silently change them.
    return out.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)


def load_funding(export_dir: str | None = None) -> pd.DataFrame:
    """The exported funding slice, as `(pair, ts, last_funding_rate, mark_price)`.

    ⚠️ `mark_price` is NaN before 2026-07: the dense mark-price poll started with the
    collector's July change, while `last_funding_rate` runs the whole window. Anything that
    needs a mark price is therefore book-era-only; the funding term itself is not.
    """
    d = export_dir or EXPORT_DIR
    df = _csv("funding", ["ts"], export_dir=d)
    out = pd.DataFrame({
        "pair": df["symbol"].astype(str),
        "ts": pd.DatetimeIndex(df["ts"]).asi8,
        "funding_rate": df["last_funding_rate"].astype("float64"),
        "mark_price": df["mark_price"].astype("float64"),
    })
    return out.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Forward returns — the quantity the acceptance test is about
# --------------------------------------------------------------------------------------

def add_forward_returns(candles: pd.DataFrame, interval: str = "5m",
                        horizons_min=HORIZONS_MIN) -> pd.DataFrame:
    """Add `fwd_ret_<h>` for each horizon, exactly as training defines it.

    🔴 POSITIONAL SHIFT, NOT A TIME OFFSET, and that is required for the acceptance test to
    mean anything. `data/features.forward_return` is `close.shift(-h_bars) / close - 1` over
    the candle rows *as loaded from the table*, so where the series has a gap the training
    label reaches across it to the next available row rather than to a wall-clock +240m that
    does not exist. Reproducing the dump therefore means reproducing that behaviour, gaps
    included. A time-based asof would be defensible on its own terms and would NOT match.

    The trailing `h_bars` rows of each pair get NaN, the same tail semantics as training.
    """
    bar = BAR_MINUTES[interval]
    out = candles.copy()
    g = out.groupby("pair", sort=False)["close"]
    for h in horizons_min:
        if h % bar:
            raise ValueError(f"horizon {h}m is not a multiple of the {interval} bar")
        n = h // bar
        out[f"fwd_ret_{h}"] = g.shift(-n) / out["close"] - 1.0
    return out


# --------------------------------------------------------------------------------------
# Funding
# --------------------------------------------------------------------------------------

def add_funding(grid: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    """asof-join the prevailing funding rate onto the bar grid, with training's 8h cap.

    This reproduces `data/features.build_feature_frame`'s `funding` column: forward-fill the
    last observed rate onto each bar and mark it stale past `FUNDING_OI_MAX_AGE` minutes.
    `has_funding` is the presence mask, so a consumer can tell a real zero rate from an
    absent one — the same distinction training draws.
    """
    out = grid.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    src = funding[["pair", "ts", "funding_rate"]].rename(columns={"ts": "src_ts"})
    j = _asof(out, src, "src_ts")
    age_min = (j["ts"] - j["src_ts"]) / 6e10
    stale = (~np.isfinite(age_min) | (age_min > FUNDING_OI_MAX_AGE)).to_numpy()
    out["funding_rate"] = np.where(stale, 0.0, j["funding_rate"].fillna(0.0).to_numpy())
    out["has_funding"] = (~stale).astype("int8")
    return out


def _asof(left: pd.DataFrame, right: pd.DataFrame, right_ts: str) -> pd.DataFrame:
    """`merge_asof` on `ts` within `pair`, returned in `left`'s row order.

    pandas requires the `on` key to be sorted GLOBALLY, not merely within each `by` group,
    so both sides are re-sorted on `ts` alone for the merge and the result is put back into
    the caller's order afterwards. Doing this in one place keeps the two callers from
    disagreeing about row order, which would silently mis-attach every column.
    """
    l = left[["pair", "ts"]].reset_index(drop=True)
    order = l.sort_values("ts", kind="mergesort").index
    j = pd.merge_asof(
        l.loc[order], right.sort_values(right_ts, kind="mergesort"),
        left_on="ts", right_on=right_ts, by="pair", direction="backward",
    )
    j.index = order
    return j.sort_index()


def funding_settlements(funding: pd.DataFrame) -> pd.DataFrame:
    """The settlement events themselves: `(pair, ts, funding_rate)`, one row per settlement.

    🔴 THE SCHEDULE IS PER PAIR AND MUST NOT BE HARDCODED. Eleven of the twelve pairs settle
    every 8 hours at 00:00/08:00/16:00 UTC, but **HYPEUSDT settles every 4 hours** — it has
    exactly twice as many settlement rows over the same window. A side-table that assumed a
    uniform 8h cycle would understate HYPE's funding by half, on a pair the policy trades.
    So the events are read out of the data rather than generated from an assumed calendar.

    🔴 A BOUNDARY ROW IS NOT A SETTLEMENT, and getting this wrong inflates the funding term.
    Before 2026-07 the table *is* the settlement series — one row per settlement, so every
    row lands on a settlement hour. From July the collector polls the mark price
    continuously, so rows land in EVERY hour and "a row within a minute of the hour" picks
    up all 24 of them. Scoring that way reported BTCUSDT at 5.28 settlements/day against a
    true 3, and charged July-and-later trades a correspondingly inflated funding cost.

    So the settlement HOURS are identified first, per pair, and only then are rows kept:
    a settlement hour is one that carries a boundary row on essentially every day of the
    window. That separates the two eras without hardcoding the date the collector changed —
    a real settlement hour is present on ~100% of days, while an hour that only has rows
    because of the dense poll is present on the ~20% of days that poll covers.
    """
    f = funding.dropna(subset=["funding_rate"]).copy()
    t = pd.to_datetime(f["ts"], unit="ns", utc=True)
    # A settlement lands on the hour, to the second; the dense poll's rows scatter across it.
    f["hour_of_day"] = t.dt.hour
    f["hour"] = t.dt.floor("h")
    f["date"] = t.dt.date
    at_boundary = f[(t - t.dt.floor("h")).dt.total_seconds() < 60.0]

    ev = (at_boundary.sort_values(["pair", "ts"], kind="mergesort")
          .groupby(["pair", "hour"], as_index=False)
          .agg(ts=("ts", "first"), funding_rate=("funding_rate", "first"),
               hour_of_day=("hour_of_day", "first"), date=("date", "first")))

    keep = []
    for pair, g in ev.groupby("pair", sort=False):
        n_days = g["date"].nunique()
        share = g.groupby("hour_of_day")["date"].nunique() / max(n_days, 1)
        hours = set(share[share >= 0.9].index)
        keep.append(g[g["hour_of_day"].isin(hours)])
    out = pd.concat(keep, ignore_index=True) if keep else ev.iloc[:0]
    return out[["pair", "ts", "funding_rate"]].sort_values(
        ["pair", "ts"], kind="mergesort").reset_index(drop=True)


def funding_cost_bps(trades: pd.DataFrame, settlements: pd.DataFrame,
                     entry_col: str = "entry_ts", exit_col: str = "exit_ts",
                     side_col: str = "side") -> pd.Series:
    """Funding paid per trade, in bps of notional, signed so that positive = a COST.

    A perpetual settles funding at discrete instants; a position that is open across one
    pays `rate x notional` if long and receives it if short (when the rate is positive,
    longs pay shorts). A position that opens and closes between two settlements pays
    nothing at all — which is why this is a sum over events in `(entry, exit]` rather than
    a rate multiplied by a holding time. At a 4h hold most trades cross zero or one
    settlement, so the term is lumpy per trade, not proportional to duration.

    Returned in bps so it lands in the same units as every other cost in M3.
    """
    out = np.zeros(len(trades), dtype="float64")
    if trades.empty:
        return pd.Series(out, index=trades.index)
    ev_by_pair = {p: g for p, g in settlements.groupby("pair", sort=False)}
    entry = trades[entry_col].to_numpy()
    exit_ = trades[exit_col].to_numpy()
    side = trades[side_col].to_numpy()
    for i, (pair, a, b, s) in enumerate(zip(trades["pair"].to_numpy(), entry, exit_, side)):
        g = ev_by_pair.get(pair)
        if g is None:
            continue
        ts = g["ts"].to_numpy()
        lo, hi = np.searchsorted(ts, a, "right"), np.searchsorted(ts, b, "right")
        if hi > lo:
            out[i] = float(s) * g["funding_rate"].to_numpy()[lo:hi].sum() * 1e4
    return pd.Series(out, index=trades.index)


# --------------------------------------------------------------------------------------
# Barrier exits — the C4b mismatch, made measurable
# --------------------------------------------------------------------------------------

def barrier_exit(grid: pd.DataFrame, entries: pd.DataFrame, tp: float, sl: float,
                 max_bars: int, interval: str = "5m",
                 touch: str = "intrabar") -> pd.DataFrame:
    """Walk each entry forward to the first TP/SL touch, else time out.

    `tp` and `sl` are fractions of the entry price (e.g. 0.004 = 40bps), applied in the
    direction of the trade: a long's target is `entry*(1+tp)` and its stop `entry*(1-sl)`;
    a short's are mirrored. Returns one row per entry with the realised return, the exit bar
    and how it ended (`tp` / `sl` / `timeout`).

    🔴 TWO CONVENTIONS THAT CHANGE THE ANSWER, both made explicit rather than defaulted:

    `touch="intrabar"` tests the bar's high and low, which is what a resting stop actually
    experiences. `touch="close"` tests only closes, which is what `data/features.
    triple_barrier_labels` does when it builds the LABEL the model was trained on. They are
    not the same, and the gap between them is a real part of the C4b question: the label was
    made on closes, so a P&L booked on intrabar touches is measuring something the model was
    never trained to predict. Report both.

    **Same-bar ambiguity is resolved as the STOP.** When one bar's range spans both
    barriers, 5m OHLC cannot say which came first, and assuming the target is how a
    backtest manufactures free money. Charging the stop is the conservative reading and
    it is applied uniformly, so the bias it introduces is known and one-directional.
    """
    if touch not in ("intrabar", "close"):
        raise ValueError(f"touch must be 'intrabar' or 'close', got {touch!r}")

    idx = {}
    arrays = {}
    for pair, g in grid.groupby("pair", sort=False):
        g = g.sort_values("ts", kind="mergesort")
        idx[pair] = g["ts"].to_numpy()
        arrays[pair] = (g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy())

    n = len(entries)
    ret = np.full(n, np.nan)
    kind = np.array(["timeout"] * n, dtype=object)
    bars_held = np.full(n, -1, dtype="int64")
    exit_ts = np.full(n, -1, dtype="int64")

    for i, (pair, ts0, s) in enumerate(zip(entries["pair"].to_numpy(),
                                           entries["entry_ts"].to_numpy(),
                                           entries["side"].to_numpy())):
        arr = arrays.get(pair)
        if arr is None:
            continue
        high, low, close = arr
        t = idx[pair]
        k = int(np.searchsorted(t, ts0, "left"))
        if k >= len(t) or t[k] != ts0:
            continue                      # entry bar not in the grid — leave NaN, count it
        entry_px = close[k]
        up = entry_px * (1.0 + (tp if s > 0 else sl))
        dn = entry_px * (1.0 - (sl if s > 0 else tp))
        last = min(k + max_bars, len(t) - 1)
        for j in range(k + 1, last + 1):
            hi_j, lo_j = (high[j], low[j]) if touch == "intrabar" else (close[j], close[j])
            hit_up, hit_dn = hi_j >= up, lo_j <= dn
            if hit_up or hit_dn:
                # Both in one bar: charge the adverse one (see the docstring).
                if hit_up and hit_dn:
                    px, kind[i] = (dn if s > 0 else up), "sl"
                elif hit_up:
                    px, kind[i] = up, ("tp" if s > 0 else "sl")
                else:
                    px, kind[i] = dn, ("sl" if s > 0 else "tp")
                ret[i] = float(s) * (px / entry_px - 1.0)
                bars_held[i], exit_ts[i] = j - k, t[j]
                break
        else:
            if last > k:
                ret[i] = float(s) * (close[last] / entry_px - 1.0)
                bars_held[i], exit_ts[i] = last - k, t[last]

    out = entries.copy()
    out["barrier_ret"] = ret
    out["barrier_exit"] = kind
    out["barrier_bars"] = bars_held
    out["barrier_exit_ts"] = exit_ts
    return out


# --------------------------------------------------------------------------------------
# Building the tables
# --------------------------------------------------------------------------------------

def build_price_table(interval: str = "5m", export_dir: str | None = None,
                      horizons_min=HORIZONS_MIN) -> pd.DataFrame:
    """M3-0b's side-table: the price path plus the funding term, over the whole window."""
    candles = load_candles(interval, export_dir=export_dir)
    grid = add_forward_returns(candles, interval=interval, horizons_min=horizons_min)
    return add_funding(grid, load_funding(export_dir=export_dir))


def build_book_era(interval: str = "5m") -> pd.DataFrame:
    """B0's side-table: the same grid over the book era, with the book/tape columns added.

    The five book scalars are the ones `data/features.py` derives from
    `orderbook_snapshots`, and the three tape ones the ones it derives from
    `market_trades` — reproduced here with the SAME asof-join and the SAME staleness caps
    training uses (`BOOK_MAX_AGE`, `TRADES_MAX_AGE`), because a side-table aligned
    differently from training is not evidence about training.

    ⚠️ `oi` / `oi_chg` are two of B0's eleven scalars and are NOT here: `open_interest` was
    never added to the export (scripts/gcp_m3_export.sh pulls five tables and that is not
    one of them). Nine of eleven are built; the two missing are named in the report rather
    than silently absent.
    """
    candles = load_candles(interval, export_dir=BOOK_DIR)
    grid = add_forward_returns(candles, interval=interval)
    grid = add_funding(grid, load_funding(export_dir=BOOK_DIR))

    snaps = load_snapshots()
    book = pd.DataFrame({
        "pair": snaps["symbol"].astype(str),
        "ts": pd.DatetimeIndex(snaps["ts"]).asi8,
        # Same derivations as data/features.py, from the same columns.
        "spread_bps": (snaps["spread"] / snaps["mid"] * 1e4).astype("float64"),
        "imbalance": snaps["imbalance"].astype("float64"),
        "micro_mid": (snaps["microprice"] / snaps["mid"] - 1.0).astype("float64"),
        "bid_ask_vol_ratio": (snaps["bid_volume"] /
                              snaps["ask_volume"].replace(0.0, np.nan)).astype("float64"),
        "depth_near_imb": ((snaps["bid_depth_near"] - snaps["ask_depth_near"]) /
                           (snaps["bid_depth_near"] + snaps["ask_depth_near"]
                            ).replace(0.0, np.nan)).astype("float64"),
    }).sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    grid = _asof_block(grid, book, BOOK_MAX_AGE, "has_book")

    tp = load_trades()
    tape = pd.DataFrame({
        "pair": tp["symbol"].astype(str),
        "ts": pd.DatetimeIndex(tp["window_start"]).asi8,
        "trade_count": tp["trade_count"].astype("float64"),
        "buy_sell_imb": ((tp["buy_volume"] - tp["sell_volume"]) /
                         (tp["buy_volume"] + tp["sell_volume"]
                          ).replace(0.0, np.nan)).astype("float64"),
        "trade_vol": tp["volume"].astype("float64"),
    }).sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    return _asof_block(grid, tape, TRADES_MAX_AGE, "has_trades")


def _asof_block(grid: pd.DataFrame, src: pd.DataFrame, max_age_min: float,
                mask_col: str) -> pd.DataFrame:
    """asof-ffill every column of `src` onto `grid`, zeroing rows staler than the cap.

    This is `data/features._align_with_age` + `_stale_mask` expressed as a merge_asof over
    a stacked (pair, ts) frame rather than per-symbol reindexing — the same operation, since
    both forward-fill the last source row and then age it against the bar's own timestamp.
    Stale rows are zeroed and flagged rather than dropped, exactly as training does, so a
    consumer can tell a real zero from an absent reading.
    """
    cols = [c for c in src.columns if c not in ("pair", "ts")]
    out = grid.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    j = _asof(out, src.rename(columns={"ts": "src_ts"}), "src_ts")
    age_min = (j["ts"] - j["src_ts"]) / 6e10
    stale = (~np.isfinite(age_min) | (age_min > max_age_min)).to_numpy()
    for c in cols:
        out[c] = np.where(stale, 0.0, j[c].fillna(0.0).to_numpy())
    out[mask_col] = (~stale).astype("int8")
    return out
