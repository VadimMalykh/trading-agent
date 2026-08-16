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

Run on a THROWAWAY VM (preferred — 8 pairs x full history needs ~2-4GB):
  ./scripts/gcp_gbt.sh
The always-on collector VM is 2GB and also runs postgres + app + inference; an
8-pair full-history run gets OOM-killed there (silently — the kernel kills the
python process mid-bundle and no report is written). Run it on the temp VM, or
bound RAM explicitly with --tail-days / --max-train-rows.

Run in the ml_trainer container against whatever DB that container sees:
  docker compose --profile ml run --rm ml_trainer python gbt_baseline.py \
    --pairs BTCUSDT,ETHUSDT,SOLUSDT,DOGEUSDT,WLDUSDT,HYPEUSDT,ZECUSDT,1000PEPEUSDT
Optional: --tail-days N + --max-train-rows N (bound RAM), --label-mode
triple_barrier, --flatten.

MEMORY NOTES (why this file is written the way it is): the design matrix, not the
bundle, dominates. Peak is kept to roughly one copy of the FIT matrix by
  * materializing X only for the rows actually fitted (moved bars), never for all
    train rows followed by a boolean-mask copy (that doubled peak),
  * handing the matrix to LightGBM as a constructed `lgb.Dataset` and freeing the
    raw float32 copy before boosting starts,
  * streaming the val split through `predict` in bounded row chunks, so the val
    matrix is never fully materialized,
  * dropping bundle arrays no longer needed after the split (non-primary horizon
    labels/returns, raw closes, book mask).
`[mem]` lines report RSS at each step so a future OOM is diagnosable from the log.
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


def _rss_mb() -> float:
    """Resident set size in MB (Linux /proc; falls back to getrusage)."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.readline().split()[1]) * 4096 / 1e6
    except OSError:
        import resource

        # Linux reports ru_maxrss in KB (macOS in bytes — dev-only path).
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3


def _mem(tag: str) -> None:
    print(f"  [mem] {tag}: rss={_rss_mb():.0f} MB", flush=True)


def feature_dim(bundle, flatten: bool) -> int:
    f = bundle.series[0].feats.shape[1]
    # flatten: raw window; else last, mean, std, min, max, delta
    return bundle.seq_len * f if flatten else 6 * f


def _fill_summary(win: np.ndarray, row: np.ndarray, f: int) -> None:
    """Compact per-window features from a [SEQ_LEN, F] window (post-norm), written
    IN PLACE into `row` (length 6F).

    last bar (F) + mean/std/min/max over the window (4F) + last-minus-first (F).
    Keeps the GBT input to 6F cols instead of SEQ_LEN*F, which trees handle far
    better than 2000+ mostly-redundant flattened columns. Column ORDER must stay
    last|mean|std|min|max|delta — changing it changes what the model sees.
    """
    row[0:f] = win[-1]
    np.mean(win, axis=0, out=row[f : 2 * f])
    np.std(win, axis=0, out=row[2 * f : 3 * f])
    np.min(win, axis=0, out=row[3 * f : 4 * f])
    np.max(win, axis=0, out=row[4 * f : 5 * f])
    np.subtract(win[-1], win[0], out=row[5 * f : 6 * f])


def build_x(bundle, sample_idx, flatten: bool, out: np.ndarray | None = None):
    """Materialize the design matrix X[n, D] for `sample_idx` only.

    Split out from the label side (see `labels_for`) so callers can filter rows
    BEFORE paying for their features — building X for all train rows and then
    doing X[mask] doubled peak RSS. `out` lets the val loop reuse one chunk
    buffer instead of allocating per chunk.
    """
    seq_len = bundle.seq_len
    f = bundle.series[0].feats.shape[1]
    n = int(sample_idx.shape[0])
    X = out if out is not None else np.empty((n, feature_dim(bundle, flatten)), dtype=np.float32)
    pi_all = bundle.pair_i[sample_idx]
    t_all = bundle.t_i[sample_idx]
    for i in range(n):
        t = int(t_all[i])
        win = bundle.series[int(pi_all[i])].feats[t - seq_len : t]
        if flatten:
            X[i] = win.reshape(-1)
        else:
            _fill_summary(win, X[i], f)
    return X


def labels_for(bundle, sample_idx, horizon_key: str):
    """Return (y3[n] 3-class, dir_label[n] in {0 down,1 up,-1 flat/invalid},
    fwd_ret[n]) for `sample_idx` — no design matrix, so this is cheap.

    dir_label is the BINARY up/down target on MOVED bars (mirrors
    train_m2.directional_loss); flat bars are -1 and excluded from FIT only.
    Labels are returned for ALL gated samples so eval mirrors the LSTM path.
    Gathered per pair (vectorized) rather than row-by-row in python.
    """
    pi_all = bundle.pair_i[sample_idx]
    t_all = bundle.t_i[sample_idx]
    n = int(sample_idx.shape[0])
    y3 = np.empty(n, dtype=np.int8)
    fwd = np.empty(n, dtype=np.float32)
    for pi, ser in enumerate(bundle.series):
        m = pi_all == pi
        if not m.any():
            continue
        t = t_all[m]
        y3[m] = ser.labels[horizon_key][t]
        fwd[m] = ser.returns[horizon_key][t]
    dir_label = np.where(y3 == 2, 1, np.where(y3 == 0, 0, -1)).astype(np.int8)
    return y3, dir_label, fwd


def drop_unused_bundle_arrays(bundle, keep_key: str) -> None:
    """Free per-pair arrays this diagnostic never reads again.

    Only the PRIMARY horizon's labels/returns are used downstream; `close` (P&L
    sim works off fwd_ret) and `book_present` (no --require-book here) are unused
    entirely. Must run AFTER fit_norm/apply_norm (which touch only `feats`).
    """
    for ser in bundle.series:
        for store in (ser.labels, ser.returns):
            for k in [k for k in store if k != keep_key]:
                store.pop(k)
        ser.close = None
        ser.book_present = None


def subsample_rows(n: int, cap: int | None) -> np.ndarray | None:
    """Evenly-spaced row selector keeping the full time span, or None for all.

    Uniform stride (not a random draw) so the fitted sample still covers the
    whole train window rather than over-weighting whichever pairs/epochs a random
    subset happened to hit.
    """
    if not cap or n <= cap:
        return None
    return np.unique(np.linspace(0, n - 1, cap).astype(np.int64))


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
    ap.add_argument("--seed", type=int, default=42, help="LightGBM seed (bagging)")
    ap.add_argument(
        "--max-train-rows",
        type=int,
        default=None,
        help="Cap FITTED rows (even stride over the train window). Bounds the peak "
        "design matrix: rows * (6*F or SEQ_LEN*F) * 4 bytes.",
    )
    ap.add_argument(
        "--chunk-mb",
        type=int,
        default=128,
        help="Val prediction is streamed in row chunks of about this many MB",
    )
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
    # Silent primary fallback is the R3 trap (see docs/NEXT_TRAINING_PLAN.md): the
    # run completes but reports a horizon you never asked for, voiding the
    # LSTM comparison. Make it loud.
    if PRIMARY_HORIZON in horizons:
        primary = str(PRIMARY_HORIZON)
    else:
        primary = str(horizons[0])
        print(
            f"WARNING: PRIMARY_HORIZON={PRIMARY_HORIZON} is NOT in "
            f"HORIZONS_MINUTES={horizons} -> falling back to {primary}m. "
            f"Numbers below are {primary}m and are NOT comparable to a 30m LSTM run. "
            f"Set both env vars (e.g. HORIZONS_MINUTES=5,30,60 PRIMARY_HORIZON=30)."
        )
    max_rows = args.tail_days * 1440 if args.tail_days else None

    print(
        f"GBT baseline | pairs={pairs} | horizons={horizons} | primary={primary}m "
        f"| seq_len={SEQ_LEN} | flatten={args.flatten}"
    )
    print(f"Building bundle (label_mode={args.label_mode or 'config default'})...")
    bundle = _build(
        pairs=pairs, seq_len=SEQ_LEN, horizons_minutes=horizons, max_rows=max_rows
    )
    if bundle.n_samples == 0:
        print("No samples")
        sys.exit(2)

    _mem("bundle built")
    tr_idx, va_idx = time_split_indices(bundle.times, VAL_FRACTION)
    # Fit norm on the train split only (no leakage), same as eval_m2 / train_m2.
    norm = fit_norm_from_bundle(bundle, tr_idx)
    apply_norm_to_bundle(bundle, norm)
    # Everything below reads only the primary horizon + feats; free the rest.
    drop_unused_bundle_arrays(bundle, primary)
    _mem("normed + trimmed")

    print(f"Train samples={tr_idx.shape[0]:,}  Val samples={va_idx.shape[0]:,}")
    t_va = bundle.times[va_idx]
    print(f"Val window [{_ns_to_iso(int(t_va.min()))} -> {_ns_to_iso(int(t_va.max()))}]")

    D = feature_dim(bundle, args.flatten)

    # --- fit set: MOVED train bars only (binary up/down), mirroring
    # directional_loss. Select the rows FIRST, then build X for just those rows.
    _y3tr, dtr, _fwdtr = labels_for(bundle, tr_idx, primary)
    moved = np.nonzero(dtr >= 0)[0]
    n_moved = int(moved.shape[0])
    keep = subsample_rows(n_moved, args.max_train_rows)
    if keep is not None:
        moved = moved[keep]
        print(
            f"Subsampled fit rows: {moved.shape[0]:,} of {n_moved:,} moved train bars "
            f"(even stride, --max-train-rows={args.max_train_rows}) — "
            f"{n_moved - moved.shape[0]:,} DROPPED"
        )
    fit_idx = tr_idx[moved]
    y_fit = (dtr[moved] == 1).astype(np.int8)
    n_fit = int(fit_idx.shape[0])
    del dtr, _y3tr, _fwdtr

    print(
        f"Fitting LightGBM on {n_fit:,} moved train bars (up/down), "
        f"D={D} cols (~{n_fit * D * 4 / 1e6:.0f} MB design matrix)..."
    )
    X_fit = build_x(bundle, fit_idx, args.flatten)
    _mem("fit matrix built")
    # Native API (not LGBMClassifier) so the raw float32 copy can be released the
    # moment LightGBM has binned it — the sklearn wrapper holds a reference to X
    # for the whole fit, roughly doubling peak. Params below are the exact
    # equivalents of the previous LGBMClassifier kwargs.
    params = {
        "objective": "binary",
        "num_leaves": args.num_leaves,
        "learning_rate": args.learning_rate,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "feature_fraction": 0.8,
        "lambda_l2": 1.0,
        "num_threads": 0,  # 0 = all cores (sklearn n_jobs=-1)
        "seed": args.seed,
        "force_col_wise": True,  # skip the row/col-wise probe (saves a pass + RAM)
        "verbosity": -1,
    }
    dtrain = lgb.Dataset(X_fit, label=y_fit, free_raw_data=True)
    dtrain.construct()
    del X_fit
    _mem("binned (raw X freed)")
    booster = lgb.train(params, dtrain, num_boost_round=args.n_estimators)
    del dtrain
    _mem("trained")

    # --- val: labels for ALL val bars; p(up) streamed in bounded row chunks so
    # the val design matrix is never fully materialized.
    y3va, _dva, fva = labels_for(bundle, va_idx, primary)
    tva = bundle.times[va_idx]
    pva = pair_ids_for_indices(bundle, va_idx)
    n_va = int(va_idx.shape[0])
    chunk = max(1, int(args.chunk_mb * 1e6) // (D * 4))
    p_up = np.empty(n_va, dtype=np.float64)
    buf = np.empty((min(chunk, n_va), D), dtype=np.float32)
    print(f"Predicting {n_va:,} val bars in chunks of {chunk:,} rows...")
    for s in range(0, n_va, chunk):
        sl = va_idx[s : s + chunk]
        xb = build_x(bundle, sl, args.flatten, out=buf[: sl.shape[0]])
        p_up[s : s + sl.shape[0]] = booster.predict(xb)
    del buf
    _mem("val predicted")
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
        "horizons": horizons,
        "primary": primary,
        "seq_len": SEQ_LEN,
        "flatten": args.flatten,
        "label_mode": args.label_mode or bundle.meta.get("label_mode"),
        "n_train": int(tr_idx.shape[0]),
        "n_val": int(va_idx.shape[0]),
        "n_fit_moved": n_fit,
        "n_moved_available": n_moved,
        "tail_days": args.tail_days,
        "feature_cols": D,
        "peak_rss_mb": round(_rss_mb(), 1),
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
            "seed": args.seed,
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
