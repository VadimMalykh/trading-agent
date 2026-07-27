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


def _sign_acc_lb(feat: np.ndarray, target: np.ndarray) -> tuple[float, float, int]:
    """sign(feat-median) vs sign(target), inverse-orientation allowed. -> (acc, lb, n)."""
    acc, lb, n = sign_accuracy(feat, target)
    return acc, lb, n


def subwindow_stability(feat: np.ndarray, fwd: np.ndarray, n_thirds: int = 3) -> dict:
    """
    Split into consecutive equal windows; report per-window Spearman + sign-acc.
    A genuine effect keeps the SAME sign across all windows; a regime/trend
    artifact flips. Verdict STABLE iff all windows share the sign of the full-window
    Spearman and each |rho| is non-trivial.
    """
    n = feat.size
    if n < n_thirds * 200:
        return {"verdict": "n/a (too few rows)", "windows": []}
    full_rho = spearman(feat, fwd)
    full_sign = np.sign(full_rho) if full_rho != 0 else 0.0
    edges = np.linspace(0, n, n_thirds + 1, dtype=int)
    windows = []
    signs_ok = True
    for i in range(n_thirds):
        a, b = edges[i], edges[i + 1]
        fx, fy = feat[a:b], fwd[a:b]
        rho = spearman(fx, fy)
        acc, lb, m = _sign_acc_lb(fx, fy)
        windows.append(
            {"rho": round(rho, 4), "sign_acc": round(acc, 4),
             "sign_acc_lb": round(lb, 4), "n": m}
        )
        # same sign as full window and not negligible
        if full_sign == 0 or np.sign(rho) != full_sign or abs(rho) < 0.01:
            signs_ok = False
    verdict = "STABLE" if signs_ok else "UNSTABLE"
    return {"verdict": verdict, "full_rho": round(full_rho, 4), "windows": windows}


def volatility_control(feat: np.ndarray, fwd: np.ndarray, n_buckets: int = 5) -> dict:
    """
    Distinguish directional alpha from a volatility proxy.

    - corr_absfwd:  Spearman(feat, |fwd|)  -> how much the feature is a vol proxy
    - residual_rho: Spearman(feat, signed_fwd residual after removing |fwd| via OLS)
                    -> directional content independent of volatility (linear control)
    - buckets:      within each |fwd| quantile bucket, feature->direction sign-acc/LB
                    -> non-parametric control; DIRECTIONAL iff the edge persists
                       across buckets (not only in the high-|fwd| bucket)
    Verdict (bucket-driven): DIRECTIONAL iff >=ceil(n_buckets/2) buckets have LB>0.50
    with a consistent orientation; else VOL-PROXY.
    """
    absf = np.abs(fwd)
    corr_absfwd = spearman(feat, absf)

    # OLS residual of signed fwd on |fwd| (+intercept); Spearman(feat, resid)
    X = np.column_stack([np.ones_like(absf), absf])
    try:
        beta, *_ = np.linalg.lstsq(X, fwd, rcond=None)
        resid = fwd - X @ beta
        residual_rho = spearman(feat, resid)
    except np.linalg.LinAlgError:
        residual_rho = float("nan")

    # Bucketed non-parametric test
    buckets = []
    dir_hits = 0
    med = np.median(feat)
    try:
        qcodes = pd.qcut(pd.Series(absf), q=n_buckets, labels=False, duplicates="drop")
        qcodes = qcodes.to_numpy()
    except ValueError:
        qcodes = np.zeros_like(absf, dtype=int)
    # Fix a single orientation from the full sample so buckets are comparable
    full_acc, _, _ = sign_accuracy(feat, fwd)
    orient = 1.0 if (np.median((feat > med).astype(float)) is not None) else 1.0
    # determine orientation: does feat>med predict fwd>0 (>0.5) or the inverse?
    move_all = fwd != 0
    base = ((feat > med) == (fwd > 0))[move_all].mean() if move_all.any() else 0.5
    invert = base < 0.5
    for bcode in sorted(set(qcodes.tolist())):
        m = qcodes == bcode
        fx, fy = feat[m], fwd[m]
        mv = fy != 0
        nb = int(mv.sum())
        if nb < 30:
            buckets.append({"bucket": int(bcode), "n": nb, "sign_acc": None, "lb": None})
            continue
        pred_up = (fx > med)
        if invert:
            pred_up = ~pred_up
        agree = (pred_up[mv] == (fy[mv] > 0))
        hits = int(agree.sum())
        acc = hits / nb
        lb = wilson_lower_bound(hits, nb)
        buckets.append({"bucket": int(bcode), "n": nb, "sign_acc": round(acc, 4), "lb": round(lb, 4)})
        if lb > 0.50:
            dir_hits += 1

    scored = [b for b in buckets if b["lb"] is not None]
    need = int(np.ceil(len([b for b in buckets]) / 2.0))
    verdict = "DIRECTIONAL" if (scored and dir_hits >= need) else "VOL-PROXY"
    return {
        "verdict": verdict,
        "corr_absfwd": round(corr_absfwd, 4),
        "residual_rho": round(residual_rho, 4) if residual_rho == residual_rho else None,
        "n_buckets_dir": dir_hits,
        "n_buckets_scored": len(scored),
        "buckets": buckets,
    }


def audit_pair(pair: str, horizons: list[int], interval: str, min_rows: int,
               deep: bool = True, n_thirds: int = 3, n_buckets: int = 5) -> dict:
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
            rec = {
                "spearman": round(rho, 4),
                "decile_monotonicity": round(mono, 3) if mono == mono else None,
                "sign_dir_acc": round(acc, 4),
                "sign_dir_acc_wilson_lb": round(lb, 4),
                "n_move": n,
            }
            if deep:
                stab = subwindow_stability(x, fwd_v, n_thirds=n_thirds)
                vol = volatility_control(x, fwd_v, n_buckets=n_buckets)
                rec["deep_dive"] = {"stability": stab, "vol_control": vol}
            feats_report[f] = rec
        out["horizons"][str(h)] = {
            "n_valid": int(valid.sum()),
            "features": feats_report,
        }
    return out


def _fmt_feat_row(name: str, r: dict) -> str:
    if r.get("constant"):
        return f"    {name:<18} (constant — no book history in window)"
    base = (
        f"    {name:<18} rho={r['spearman']:+.4f}  "
        f"mono={r['decile_monotonicity'] if r['decile_monotonicity'] is not None else 'n/a':<5}  "
        f"sign_acc={r['sign_dir_acc']:.3f} lb={r['sign_dir_acc_wilson_lb']:.3f}  "
        f"n={r['n_move']}"
    )
    dd = r.get("deep_dive")
    if dd:
        stab = dd["stability"]["verdict"]
        vol = dd["vol_control"]
        base += (
            f"\n      └─ {stab:<8} · {vol['verdict']:<11} "
            f"(vol_corr={vol['corr_absfwd']:+.3f} resid_rho="
            f"{vol['residual_rho'] if vol['residual_rho'] is not None else 'n/a'} "
            f"dir_buckets={vol['n_buckets_dir']}/{vol['n_buckets_scored']})"
        )
    return base


def main():
    ap = argparse.ArgumentParser(description="Microstructure feature-signal audit (read-only)")
    ap.add_argument("--pairs", default="")
    ap.add_argument("--horizons", default=",".join(str(h) for h in HORIZONS_MINUTES))
    ap.add_argument("--min-rows", type=int, default=500)
    ap.add_argument("--no-deep", action="store_true", help="skip stability/vol-control deep dive")
    ap.add_argument("--thirds", type=int, default=3, help="sub-windows for stability test")
    ap.add_argument("--vol-buckets", type=int, default=5, help="|fwd| quantile buckets for vol control")
    args = ap.parse_args()
    deep = not args.no_deep

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
    if deep:
        print(
            "Deep dive (per feature):\n"
            "  STABLE/UNSTABLE  = same-sign Spearman across all sub-windows? (thirds)\n"
            "  DIRECTIONAL/VOL-PROXY = does the sign edge persist across |fwd| buckets\n"
            "    after controlling for volatility (bucketed test drives the verdict)?\n"
            "  => STABLE+DIRECTIONAL = genuine directional alpha (escalate).\n"
            "     STABLE+VOL-PROXY   = risk feature -> quantile head, not direction.\n"
            "     UNSTABLE           = regime/trend artifact -> keep collecting."
        )

    report = {"pairs": {}, "horizons": horizons, "interval": CANDLE_INTERVAL}
    best_overall = 0.0
    directional_hits = []  # (pair, horizon, feature, rho) that are STABLE + DIRECTIONAL
    for pair in pairs:
        try:
            res = audit_pair(
                pair, horizons, CANDLE_INTERVAL, args.min_rows,
                deep=deep, n_thirds=args.thirds, n_buckets=args.vol_buckets,
            )
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
                    dd = r.get("deep_dive")
                    if (
                        dd
                        and dd["stability"]["verdict"] == "STABLE"
                        and dd["vol_control"]["verdict"] == "DIRECTIONAL"
                        and r["sign_dir_acc_wilson_lb"] > 0.50
                    ):
                        directional_hits.append((pair, h, name, r["spearman"]))

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    out_path = Path(OUTPUT_DIR) / "microstructure_audit.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 64)
    print(f"Strongest |Spearman| across all pairs/features/horizons: {best_overall:.4f}")

    if deep:
        print("\nSTABLE + DIRECTIONAL findings (genuine directional alpha candidates):")
        if directional_hits:
            # group by feature for readability
            by_feat: dict[str, list] = {}
            for pr, h, name, rho in directional_hits:
                by_feat.setdefault(name, []).append((pr, h, rho))
            for name, hits in sorted(by_feat.items(), key=lambda kv: -len(kv[1])):
                combos = ", ".join(f"{pr}@{h}m(rho={rho:+.3f})" for pr, h, rho in hits)
                print(f"  {name}: {len(hits)} pair/horizon(s) -> {combos}")
            feats = sorted({n for _, _, n, _ in directional_hits})
            print(
                f"\n=> {len(directional_hits)} STABLE+DIRECTIONAL signal(s) across "
                f"features {feats}."
            )
            print(
                "   ESCALATE: this is genuine directional content beyond volatility.\n"
                "   Next: dense-window ablation training run (book features on vs off)\n"
                "   on the live-book window; don't wait for 60d to start validating."
            )
        else:
            print("  (none) — no feature is both STABLE across sub-windows AND DIRECTIONAL")
            print("  after volatility control.")
            print(
                "\n=> Signals seen are likely volatility proxies or regime/trend artifacts.\n"
                "   Route strong VOL-PROXY features (e.g. spread_bps) to the quantile/risk\n"
                "   head, not direction. Keep collecting; re-audit at ~30d."
            )
    elif best_overall >= 0.03:
        print("=> A book feature shows a non-trivial monotone relationship. Re-run without")
        print("   --no-deep to test whether it is directional or a volatility artifact.")
    else:
        print("=> No book feature clears ~0.03 yet. Keep collecting and re-audit.")
    print(f"Wrote {out_path}")
    print("\nReminder: run this on the ALWAYS-ON VM for the real ~9-day majors book")
    print("data; a fresh local DB may have little/no orderbook history.")


if __name__ == "__main__":
    main()
