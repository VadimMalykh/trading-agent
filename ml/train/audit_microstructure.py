#!/usr/bin/env python3
"""
Microstructure feature-signal audit (READ-ONLY, no training).

Decides whether the order-book / trade-flow / OI features carry any directional
signal *before* committing to weeks of data collection. For each pair it looks
ONLY at the live window where book data actually exists (has_book == 1) and, per
microstructure feature and horizon, measures:

  - Spearman rank correlation vs the forward return   (linear-ish monotone signal)
  - decile monotonicity                                (is the relationship ordered?)
  - sign-agreement directional accuracy + Wilson LB    (does sign(feat-median)
                                                        predict sign(fwd return)?)
  - n and a small-sample warning

Interpretation (baked into the printout):
  On a pair with enough live rows (majors ~9d ≈ ~13k 1m bars), a microstructure
  feature with |Spearman| >~ 0.03 AND a Wilson-LB sign-accuracy > 0.51 is a real
  (if small) edge → collecting more book history is worth it. If every book
  feature is indistinguishable from noise (|rho|<~0.01, LB<=0.50), the book edge
  is not showing up yet → don't over-invest; keep collecting and re-audit.

  ~2–9 days is enough for a SMELL TEST only. Treat a positive as "worth more
  collection", a null as "inconclusive", never as a final verdict.

Run (Docker only):
  docker compose --profile ml run --rm ml_trainer python audit_microstructure.py
  # meaningful result needs the always-on VM's real ~9-day book data:
  #   run the same command there (that DB has the live orderbook_snapshots)

Options:
  --pairs BTCUSDT,ETHUSDT   restrict pairs (default: DB whitelist)
  --horizons 5,30,60        forward-return horizons in minutes
  --min-rows 500            skip a pair/window with fewer live rows than this
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CANDLE_INTERVAL, HORIZONS_MINUTES, OUTPUT_DIR, PAIRS
from data.db import load_whitelist_pairs
from data.features import build_feature_frame, forward_return
from data.dataset import horizon_bars
from gate import wilson_lower_bound

# Microstructure (non-OHLCV) features to test. These are the columns that are
# zero-filled when the live collector has no history — the whole point of the audit.
MICRO_FEATURES = [
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


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rho = Pearson on ranks. NaN-safe via pandas ranking."""
    if x.size < 3:
        return float("nan")
    xr = pd.Series(x).rank().to_numpy()
    yr = pd.Series(y).rank().to_numpy()
    xr = xr - xr.mean()
    yr = yr - yr.mean()
    denom = np.sqrt((xr * xr).sum() * (yr * yr).sum())
    if denom == 0:
        return 0.0
    return float((xr * yr).sum() / denom)


def decile_monotonicity(feat: np.ndarray, fwd: np.ndarray, n_bins: int = 10) -> float:
    """
    Fraction of adjacent decile steps whose mean-forward-return moves in a
    consistent direction (max over up/down). 1.0 = perfectly monotone; ~0.5 =
    no ordering. Robust, non-parametric complement to Spearman.
    """
    if feat.size < n_bins * 5:
        return float("nan")
    try:
        bins = pd.qcut(pd.Series(feat), q=n_bins, duplicates="drop")
    except ValueError:
        return float("nan")
    means = pd.Series(fwd).groupby(bins, observed=True).mean().to_numpy()
    if means.size < 3:
        return float("nan")
    diffs = np.diff(means)
    if diffs.size == 0:
        return float("nan")
    up = float((diffs > 0).mean())
    return max(up, 1.0 - up)


def sign_accuracy(feat: np.ndarray, fwd: np.ndarray) -> tuple[float, float, int]:
    """
    Does sign(feat - median) predict sign(fwd)? Restrict to bars where fwd != 0.
    Returns (dir_acc, wilson_lb, n). Also tries the flipped sign and keeps the
    better-than-0.5 orientation (a feature can be inversely predictive).
    """
    med = np.median(feat)
    pred_up = feat > med
    true_up = fwd > 0
    move = fwd != 0
    n = int(move.sum())
    if n == 0:
        return 0.0, 0.0, 0
    agree = (pred_up[move] == true_up[move])
    hits = int(agree.sum())
    acc = hits / n
    # allow inverse relationship
    if acc < 0.5:
        acc = 1.0 - acc
        hits = n - hits
    return acc, wilson_lower_bound(hits, n), n


def audit_pair(pair: str, horizons: list[int], interval: str, min_rows: int) -> dict:
    frame = build_feature_frame(pair, interval)
    if frame.empty:
        return {"pair": pair, "error": "no feature frame"}

    # Restrict to the live window where book data actually exists.
    if "has_book" not in frame.columns:
        return {"pair": pair, "error": "has_book column missing (retrain features?)"}
    live = frame[frame["has_book"] > 0]
    n_live = len(live)
    first_book = str(live.index.min()) if n_live else None

    out = {
        "pair": pair,
        "n_rows_total": int(len(frame)),
        "n_rows_live_book": int(n_live),
        "first_book_ts": first_book,
        "horizons": {},
    }
    if n_live < min_rows:
        out["warning"] = f"only {n_live} live-book rows (< {min_rows}); too few to trust"
        return out

    close = live["close"]
    h_bars = {h: horizon_bars(interval, h) for h in horizons}

    for h in horizons:
        fwd = forward_return(close, h_bars[h]).to_numpy()
        valid = ~np.isnan(fwd)
        fwd_v = fwd[valid]
        feats_report = {}
        for f in MICRO_FEATURES:
            if f not in live.columns:
                continue
            x = live[f].to_numpy()[valid]
            # skip near-constant features (nothing to correlate)
            if np.nanstd(x) < 1e-12:
                feats_report[f] = {"constant": True}
                continue
            rho = spearman(x, fwd_v)
            mono = decile_monotonicity(x, fwd_v)
            acc, lb, n = sign_accuracy(x, fwd_v)
            feats_report[f] = {
                "spearman": round(rho, 4),
                "decile_monotonicity": round(mono, 3) if mono == mono else None,
                "sign_dir_acc": round(acc, 4),
                "sign_dir_acc_wilson_lb": round(lb, 4),
                "n_move": n,
            }
        out["horizons"][str(h)] = {
            "n_valid": int(valid.sum()),
            "features": feats_report,
        }
    return out


def _fmt_feat_row(name: str, r: dict) -> str:
    if r.get("constant"):
        return f"    {name:<18} (constant — no book history in window)"
    return (
        f"    {name:<18} rho={r['spearman']:+.4f}  "
        f"mono={r['decile_monotonicity'] if r['decile_monotonicity'] is not None else 'n/a':<5}  "
        f"sign_acc={r['sign_dir_acc']:.3f} lb={r['sign_dir_acc_wilson_lb']:.3f}  "
        f"n={r['n_move']}"
    )


def main():
    ap = argparse.ArgumentParser(description="Microstructure feature-signal audit (read-only)")
    ap.add_argument("--pairs", default="")
    ap.add_argument("--horizons", default=",".join(str(h) for h in HORIZONS_MINUTES))
    ap.add_argument("--min-rows", type=int, default=500)
    args = ap.parse_args()

    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    if args.pairs.strip():
        pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    else:
        pairs = load_whitelist_pairs(fallback=PAIRS)

    print("Microstructure feature-signal audit (READ-ONLY)")
    print("=" * 64)
    print(f"pairs={pairs} horizons={horizons}m interval={CANDLE_INTERVAL} min_rows={args.min_rows}")
    print(
        "Signal to look for: |rho| >~ 0.03 AND wilson_lb(sign_acc) > 0.51 on a\n"
        "pair with enough live rows => book edge is real (small) => worth collecting.\n"
        "All-noise (|rho|<~0.01, lb<=0.50) => not showing yet; keep collecting.\n"
        "NOTE: 2-9 days is a SMELL TEST only, not a final verdict."
    )

    report = {"pairs": {}, "horizons": horizons, "interval": CANDLE_INTERVAL}
    best_overall = 0.0
    for pair in pairs:
        try:
            res = audit_pair(pair, horizons, CANDLE_INTERVAL, args.min_rows)
        except Exception as e:  # keep going across pairs
            res = {"pair": pair, "error": repr(e)}
        report["pairs"][pair] = res

        print(f"\n--- {pair} ---")
        if res.get("error"):
            print(f"  ERROR: {res['error']}")
            continue
        print(
            f"  rows total={res['n_rows_total']} live_book={res['n_rows_live_book']} "
            f"first_book={res['first_book_ts']}"
        )
        if res.get("warning"):
            print(f"  WARNING: {res['warning']}")
            continue
        for h, hd in res["horizons"].items():
            print(f"  horizon {h}m (n_valid={hd['n_valid']}):")
            # sort features by |spearman| desc for readability
            items = sorted(
                hd["features"].items(),
                key=lambda kv: abs(kv[1].get("spearman", 0.0) or 0.0),
                reverse=True,
            )
            for name, r in items:
                print(_fmt_feat_row(name, r))
                if not r.get("constant"):
                    best_overall = max(best_overall, abs(r.get("spearman", 0.0) or 0.0))

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    out_path = Path(OUTPUT_DIR) / "microstructure_audit.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 64)
    print(f"Strongest |Spearman| across all pairs/features/horizons: {best_overall:.4f}")
    if best_overall >= 0.03:
        print("=> A book feature shows a non-trivial monotone relationship. Collecting")
        print("   more microstructure history is likely worth it. Confirm the same")
        print("   feature's wilson_lb(sign_acc) > 0.51 above before deciding.")
    else:
        print("=> No book feature clears ~0.03 yet. Either too little live data or no")
        print("   edge is present. Keep collecting and re-audit; do not over-invest.")
    print(f"Wrote {out_path}")
    print("\nReminder: run this on the ALWAYS-ON VM for the real ~9-day majors book")
    print("data; a fresh local DB may have little/no orderbook history.")


if __name__ == "__main__":
    main()
