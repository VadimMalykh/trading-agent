#!/usr/bin/env python3
"""GBT (LightGBM) diagnostic baseline for the M2 directional gate.

DIAGNOSTIC ONLY — not a serve path. Answers the single gating question in
docs/NEXT_TRAINING_PLAN.md ("E4-GBT"): is the ceiling signal-limited or
model-limited? A gradient-boosted tree on the SAME features / labels / split /
gate / P&L sim as the M2 LSTM gives a fast, architecture-free read:

  GBT ~= LSTM and also net-negative -> signal-limited (candles carry ~no
      cost-surviving edge; pivot to data/features, not architecture).
  GBT clearly BEATS LSTM      -> LSTM is leaving signal on the table.
  GBT clearly WORSE than LSTM -> LSTM temporal modeling is helping; signal thin.

To stay directly comparable to the served directional gate we reuse the M2 data
bundle, the SAME global time split, the SAME per-pair z-score norm, and — crucially
— the SAME `gate.fixed_coverage_metrics` + `eval_m2.simulate_pnl` reporting. The
GBT is a BINARY up/down classifier trained on moved bars only (mirroring
`train_m2.directional_loss`); its p(up) is mapped into [down, flat, up] logits via
`gate.dir_logits_to_three_class` so every downstream metric is identical to the
LSTM's directional head.

Feature representation: each sample is the flattened last `SEQ_LEN` bars is far too
wide (128 * 19 = 2432 cols) and mostly redundant, so by default we build a COMPACT
per-window summary (last bar + a few rolling stats over the window) — the standard
GBT-on-sequences trick. `--flatten` switches to the full flattened window if you
want the raw comparison.

Run (local):
  docker compose --profile ml run --rm ml_trainer python gbt_baseline.py \
    --pairs BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT
Optional: --tail-days N (bound RAM), --label-mode triple_barrier, --flatten.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    CANDLE_INTERVAL,
    HORIZONS_MINUTES,
    OUTPUT_DIR,
    PAIRS,
    PRIMARY_HORIZON,
    ROUND_TRIP_COST,
    SEQ_LEN,
    VAL_FRACTION,
    WF_WINDOWS,
)
from data.dataset import (
    apply_norm_to_bundle,
    build_m2_index_bundle,
    fit_norm_from_bundle,
    horizon_bars,
    pair_ids_for_indices,
    time_split_indices,
)
from data.db import load_whitelist_pairs
from data.features import FEATURE_COLS

import torch  # only for the shared gate/sim tensors (CPU)

from gate import (
    dir_logits_to_three_class,
    directional_signal,
    fixed_coverage_metrics,
    side_split_metrics,
)
from eval_m2 import simulate_pnl, walk_forward_edge  # reuse identical P&L + WF

FIXED_COVERAGES = [0.01, 0.02, 0.05, 0.10, 0.20]


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def _rolling_summary(win: np.ndarray) -> np.ndarray:
    """Compact per-window features from a [SEQ_LEN, F] window (post-norm).

    last bar (F) + mean/std/min/max over the window (4F) + last-minus-first (F).
    Keeps the GBT input to 7F cols instead of SEQ_LEN*F, which trees handle far
    better than 2000+ mostly-redundant flattened columns.
    """
    last = win[-1]
    mean = win.mean(axis=0)
    std = win.std(axis=0)
    mn = win.min(axis=0)
    mx = win.max(axis=0)
    delta = win[-1] - win[0]
    return np.concatenate([last, mean, std, mn, mx, delta]).astype(np.float32)


def build_xy(bundle, sample_idx, horizon_key: str, flatten: bool):
    """Return (X[n, D], dir_label[n] in {0 down,1 up,-1 flat/invalid-for-dir},
    y3[n] 3-class, fwd_ret[n], times[n], pair_ids[n]).

    dir_label is the BINARY up/down target on MOVED bars (mirrors
    train_m2.directional_loss); flat/true bars are -1 and excluded from FIT only.
    Everything is returned for ALL gated samples so eval mirrors the LSTM path.
    """
    seq_len = bundle.seq_len
    pi_all = bundle.pair_i[sample_idx]
    t_all = bundle.t_i[sample_idx]
    n = sample_idx.shape[0]

    feats_dim = bundle.series[0].feats.shape[1]
    if flatten:
        D = seq_len * feats_dim
    else:
        D = 6 * feats_dim  # last, mean, std, min, max, delta
    X = np.empty((n, D), dtype=np.float32)
    y3 = np.empty(n, dtype=np.int64)
    fwd = np.empty(n, dtype=np.float32)

    for i in range(n):
        pi = int(pi_all[i])
        t = int(t_all[i])
        ser = bundle.series[pi]
        win = ser.feats[t - seq_len : t]
        X[i] = win.reshape(-1) if flatten else _rolling_summary(win)
        y3[i] = int(ser.labels[horizon_key][t])
        fwd[i] = float(ser.returns[horizon_key][t])

    dir_label = np.where(y3 == 2, 1, np.where(y3 == 0, 0, -1)).astype(np.int64)
    times = bundle.times[sample_idx]
    pair_ids = pair_ids_for_indices(bundle, sample_idx)
    return X, dir_label, y3, fwd, times, pair_ids


def p_up_to_dir_logits(p_up: np.ndarray) -> torch.Tensor:
    """Map GBT p(up) -> 2-class directional logits [down, up] so the shared
    gate.directional_signal / fixed_coverage / simulate_pnl path applies verbatim.
    logit = log(p/(1-p)); clamp p away from 0/1 for finite logits."""
    p = np.clip(p_up.astype(np.float64), 1e-6, 1 - 1e-6)
    logit_up = np.log(p / (1.0 - p))
    dir_logits = np.stack([-logit_up, logit_up], axis=1)  # [down, up]
    return torch.from_numpy(dir_logits.astype(np.float32))


def main():
    ap = argparse.ArgumentParser(description="GBT diagnostic baseline vs M2 LSTM gate")
    ap.add_argument("--pairs", default="", help="Comma-separated; default DB whitelist")
    ap.add_argument("--tail-days", type=int, default=None, help="Last N days per pair")
    ap.add_argument(
        "--flatten",
        action="store_true",
        help="Full flattened SEQ_LEN*F window instead of the compact summary",
    )
    ap.add_argument(
        "--label-mode",
        default=None,
        help="Override LABEL_MODE for this run (fixed|triple_barrier)",
    )
    ap.add_argument("--num-leaves", type=int, default=63)
    ap.add_argument("--n-estimators", type=int, default=400)
    ap.add_argument("--learning-rate", type=float, default=0.05)
    ap.add_argument("--out", default=None, help="Write JSON report to this path")
    args = ap.parse_args()

    if args.label_mode:
        import os

        os.environ["LABEL_MODE"] = args.label_mode
        # config.LABEL_MODE is read at import in features.make_labels_and_returns'
        # default arg; reload so the override takes effect for the bundle build.
        import importlib
        import config as _cfg
        import data.features as _feat

        importlib.reload(_cfg)
        importlib.reload(_feat)
        import data.dataset as _ds

        importlib.reload(_ds)

    import lightgbm as lgb

    from data.dataset import build_m2_index_bundle as _build  # post-reload safe

    if args.pairs.strip():
        pairs = [x.strip().upper() for x in args.pairs.split(",") if x.strip()]
    else:
        pairs = load_whitelist_pairs(fallback=PAIRS)

    horizons = HORIZONS_MINUTES
    primary = str(PRIMARY_HORIZON if PRIMARY_HORIZON in horizons else horizons[0])
    max_rows = args.tail_days * 1440 if args.tail_days else None

    print(f"GBT baseline | pairs={pairs} | primary={primary}m | flatten={args.flatten}")
    print(f"Building bundle (label_mode={args.label_mode or 'config default'})...")
    bundle = _build(
        pairs=pairs, seq_len=SEQ_LEN, horizons_minutes=horizons, max_rows=max_rows
    )
    if bundle.n_samples == 0:
        print("No samples")
        sys.exit(2)

    tr_idx, va_idx = time_split_indices(bundle.times, VAL_FRACTION)
    # Fit norm on the train split only (no leakage), same as eval_m2 / train_m2.
    norm = fit_norm_from_bundle(bundle, tr_idx)
    apply_norm_to_bundle(bundle, norm)

    print(f"Train samples={tr_idx.shape[0]:,}  Val samples={va_idx.shape[0]:,}")
    t_va = bundle.times[va_idx]
    print(f"Val window [{_ns_to_iso(int(t_va.min()))} -> {_ns_to_iso(int(t_va.max()))}]")

    Xtr, dtr, _y3tr, _ftr, _ttr, _ptr = build_xy(bundle, tr_idx, primary, args.flatten)
    Xva, dva, y3va, fva, tva, pva = build_xy(bundle, va_idx, primary, args.flatten)

    # Fit on MOVED train bars only (binary up/down), mirroring directional_loss.
    fit_mask = dtr >= 0
    n_fit = int(fit_mask.sum())
    print(f"Fitting LightGBM on {n_fit:,} moved train bars (up/down)...")
    clf = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=args.n_estimators,
        num_leaves=args.num_leaves,
        learning_rate=args.learning_rate,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        n_jobs=-1,
        verbosity=-1,
    )
    clf.fit(Xtr[fit_mask], dtr[fit_mask])

    # Predict p(up) on ALL val bars; build the shared 3-class gate tensors.
    p_up = clf.predict_proba(Xva)[:, 1]
    dir_logits = p_up_to_dir_logits(p_up)
    gate_logits = dir_logits_to_three_class(dir_logits)
    y_true = torch.from_numpy(y3va.astype(np.int64))
    fwd_ret = torch.from_numpy(fva.astype(np.float32))
    hold_bars = horizon_bars(CANDLE_INTERVAL, int(primary))

    print("\n=== Fixed-coverage directional edge (primary %sm) ===" % primary)
    fc_rows = []
    for cov in FIXED_COVERAGES:
        fc = fixed_coverage_metrics(gate_logits, y_true, cov)
        fc_rows.append(fc)
        print(
            f"  cov={fc['coverage']:.3f}  dir_acc={fc['dir_acc']:.4f}  "
            f"lb={fc['dir_acc_wilson_lb']:.4f}  n_dir={fc['n_true_directional_gated']}"
        )

    print("\n=== Serial P&L (14bps round-trip default) by gate coverage ===")
    side, conf = directional_signal(gate_logits)
    pnl_rows = []
    for cov in FIXED_COVERAGES:
        k = int(round(len(conf) * cov))
        if k <= 0:
            continue
        thr = float(torch.topk(conf, k).values.min().item())
        mask = conf >= thr
        pnl = simulate_pnl(side, conf, mask, fwd_ret, tva, pva, hold_bars, ROUND_TRIP_COST)
        pnl["gate_coverage"] = cov
        pnl_rows.append(pnl)
        print(
            f"  cov={cov:.3f}  net={pnl['total_net_ret']:+.4f}  "
            f"trades={pnl['n_trades']}  win={pnl['win_rate']:.3f}  "
            f"sharpe={pnl['daily_sharpe']}  maxdd={pnl['max_dd']:+.4f}"
        )

    print("\n=== Side split @cov0.05 (one-mode check) ===")
    ss = side_split_metrics(gate_logits, y_true, 0.05)
    for name in ("up", "down"):
        s = ss[name]
        print(
            f"  {name}: n_dir={s['n_dir']}  dir_acc={s['dir_acc']:.4f}  lb={s['wilson_lb']:.4f}"
        )

    print("\n=== Walk-forward fixed-cov edge (%d folds) ===" % WF_WINDOWS)
    wf = walk_forward_edge(gate_logits, y_true, tva, WF_WINDOWS)
    for w in wf:
        fc5 = w.get("cov05", {})
        print(
            f"  fold {w['window']}: n={w['n']}  cov05 lb={fc5.get('wilson_lb', 0):.4f}"
        )

    report = {
        "kind": "gbt_baseline",
        "pairs": pairs,
        "primary": primary,
        "flatten": args.flatten,
        "label_mode": args.label_mode or bundle.meta.get("label_mode"),
        "n_train": int(tr_idx.shape[0]),
        "n_val": int(va_idx.shape[0]),
        "n_fit_moved": n_fit,
        "val_start": _ns_to_iso(int(t_va.min())),
        "val_end": _ns_to_iso(int(t_va.max())),
        "fixed_coverage": fc_rows,
        "pnl": pnl_rows,
        "side_split_cov05": ss,
        "walk_forward": wf,
        "gbt_params": {
            "n_estimators": args.n_estimators,
            "num_leaves": args.num_leaves,
            "learning_rate": args.learning_rate,
        },
    }
    out_path = args.out or f"{OUTPUT_DIR}/gbt_baseline_{primary}m.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport written: {out_path}")
    print(
        "\nInterpretation: compare cov0.05 lb + net P&L vs the live E2b LSTM "
        "(0.566 lb / all-neg P&L). GBT~=LSTM & neg => signal-limited; GBT>>LSTM "
        "=> architecture headroom; GBT<<LSTM => temporal modeling helps."
    )


if __name__ == "__main__":
    main()
