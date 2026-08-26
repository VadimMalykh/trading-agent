"""Re-aggregate a run's `eval_preds.parquet` onto an arbitrary subset of pairs.

WHY THIS EXISTS. When an arm changes the *validation population* — a different pair
set (O8), a different bar interval (P2) — its logged `cov05` slice is not selecting
from the same universe as the baseline's, so the headline Wilson-LB and the
fixed-coverage P&L are not comparable to §1.3's (see NEXT_TRAINING_PLAN.md §0.6 and
§1.9). The honest comparison is to re-aggregate the arm's per-bar predictions onto
the baseline's pairs and re-derive the tables there. This has now been needed twice
(Q1's regime analysis, O8's 12-pair arm) and rebuilt from scratch both times.

It reads the parquet dump that C9 writes on every run, so it needs no GPU, no DB and
no checkpoint — only pandas/numpy. The metric definitions are deliberate duplicates of
`gate.fixed_coverage_metrics` and `eval_m2.simulate_pnl`; keep them in step, and note
that `--validate` is what proves they are (see below).

ALWAYS RUN `--validate` FIRST. It recomputes the tables on the *full* population, which
must reproduce the run's logged `Fixed-coverage directional edge` and `Fixed-coverage
P&L` blocks exactly. If it does not, the harness has drifted from the trainer and no
subset number it prints can be trusted.

Usage:
    gcloud storage cp gs://fluxtrader-train-artifacts/eval/<run_id>/eval_preds.parquet \
        ml/train/output/eval_dumps/eval_preds_<run_id>.parquet
    ./scripts/m3.sh reaggregate_preds.py output/eval_dumps/eval_preds_<run_id>.parquet --validate
    ./scripts/m3.sh reaggregate_preds.py output/eval_dumps/eval_preds_<run_id>.parquet --pairs BASE8

Needs only `pandas pyarrow numpy` and never runs on the VM — but like everything else in
this project it runs in Docker, not on the host. Use the torch-free analysis container:

    ./scripts/m3.sh reaggregate_preds.py output/eval_dumps/eval_preds_<run_id>.parquet --validate

Note that its `torch.topk`-free tie-breaking differs from the trainer's at a contended
coverage boundary; `ml/train/m3/backtest.py` documents the case and takes the tie-inclusive
definition instead.
"""
import argparse

import numpy as np
import pandas as pd

# The 8-pair set every experiment from the E-wave onward used as its control, and the
# universe §1.3's banked numbers are measured on. Re-aggregating onto it is the
# apples-to-apples comparison for any arm that trained on a different pair set.
BASE8 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT",
    "WLDUSDT", "HYPEUSDT", "ZECUSDT", "1000PEPEUSDT",
]

FIXED_COVERAGES = (0.01, 0.02, 0.05, 0.10, 0.20)
BAR_SECONDS = 300          # 5m bars; the whole current lineage
MAKER_COST_BPS, TAKER_COST_BPS = 5.0, 14.0


def wilson_lower_bound(hits: int, n: int, z: float = 1.96) -> float:
    """Mirror of gate.wilson_lower_bound."""
    if n == 0:
        return 0.0
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / denom


def serial_pnl(times, side, fwd_ret, pair, hold_bars):
    """Mirror of eval_m2.simulate_pnl at cost=0: per pair, enter when gated, hold
    `hold_bars`, ignore new gates while a position is open. Returns (gross, n_trades,
    win_rate). Cost is applied afterwards as `gross - n_trades * cost`, exactly as the
    trainer does, so no re-run is needed to change fees."""
    hold_ns = hold_bars * BAR_SECONDS * 1_000_000_000
    total, n_trades, wins = 0.0, 0, 0
    for p in np.unique(pair):
        m = pair == p
        order = np.argsort(times[m], kind="mergesort")
        t_p, s_p, r_p = times[m][order], side[m][order], fwd_ret[m][order]
        open_entry = None                      # (entry_time, side, fwd_ret_at_entry)
        for t, s, r in zip(t_p, s_p, r_p):
            if open_entry is not None:
                et, es, er = open_entry
                if t >= et + hold_ns:
                    total += es * er
                    wins += (es * er) > 0
                    n_trades += 1
                    open_entry = None
            if open_entry is None:
                open_entry = (t, s, r)
        if open_entry is not None:             # book the position still open at the end
            _, es, er = open_entry
            total += es * er
            wins += (es * er) > 0
            n_trades += 1
    return total, n_trades, (wins / n_trades if n_trades else 0.0)


def report(df: pd.DataFrame, label: str, hold_bars: int, coverages=FIXED_COVERAGES):
    """The two logged tables — fixed-coverage directional edge and fixed-coverage P&L —
    recomputed on whatever subset of bars `df` holds."""
    d = df.reset_index(drop=True)
    conf = d["conf"].to_numpy(np.float64)
    y3 = d["y3"].to_numpy()
    side = d["side"].to_numpy(np.float64)
    ts = d["ts"].to_numpy()
    ret = d["fwd_ret"].to_numpy(np.float64)
    pair = d["pair"].to_numpy()
    n = len(d)

    print(f"\n### {label}  (n_bars={n:,}, pairs={d['pair'].nunique()}, hold={hold_bars} bars)")
    print(f"{'cov':>6} {'n_gated':>10} {'thr':>7} {'dir_acc':>8} {'wilson_lb':>10} {'n_dir':>9} "
          f"{'trades':>8} {'gross_bps':>10} {'net@5':>8} {'net@14':>8} {'win':>6}")
    for cov in coverages:
        k = int(round(n * cov))
        if k <= 0:
            continue
        # torch.topk semantics: the k highest confidences, ties broken by position.
        idx = np.argpartition(-conf, k - 1)[:k]
        idx = idx[np.argsort(-conf[idx], kind="stable")]

        sub_y, sub_side = y3[idx], side[idx]
        true_dir = sub_y != 1                                  # flat bars excluded
        n_dir = int(true_dir.sum())
        predicted = np.where(sub_side > 0, 2, 0)               # side -1/+1 -> class 0/2
        hits = int((predicted[true_dir] == sub_y[true_dir]).sum())
        dir_acc = hits / n_dir if n_dir else 0.0

        gross, trades, win = serial_pnl(ts[idx], sub_side, ret[idx], pair[idx], hold_bars)
        gross_bps = gross / trades * 1e4 if trades else 0.0
        print(f"{cov:6.3f} {k:10,} {conf[idx].min():7.3f} {dir_acc:8.3f} "
              f"{wilson_lower_bound(hits, n_dir):10.3f} {n_dir:9,} {trades:8,} "
              f"{gross_bps:+10.2f} {gross_bps - MAKER_COST_BPS:+8.2f} "
              f"{gross_bps - TAKER_COST_BPS:+8.2f} {win:6.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("parquet", help="path to a run's eval_preds.parquet")
    ap.add_argument("--horizon", type=int, default=240, help="horizon in minutes (default: the primary, 240)")
    ap.add_argument("--pairs", default="BASE8",
                    help="'BASE8', 'ALL', or a comma-separated pair list")
    ap.add_argument("--validate", action="store_true",
                    help="also print the full population — MUST reproduce the run's logged tables")
    ap.add_argument("--split-new", action="store_true",
                    help="also print the pairs NOT in --pairs, on their own")
    args = ap.parse_args()

    df = pd.read_parquet(args.parquet)
    h = df[df["horizon"] == args.horizon]
    if h.empty:
        raise SystemExit(f"no rows at horizon {args.horizon}; have {sorted(df['horizon'].unique())}")
    hold_bars = args.horizon * 60 // BAR_SECONDS

    if args.pairs == "ALL":
        selected = sorted(h["pair"].unique())
    elif args.pairs == "BASE8":
        selected = BASE8
    else:
        selected = [p.strip() for p in args.pairs.split(",") if p.strip()]

    if args.validate:
        report(h, "FULL POPULATION — must match the run's logged tables exactly", hold_bars)

    missing = sorted(set(selected) - set(h["pair"].unique()))
    if missing:
        print(f"\n⚠️  requested pairs absent from this dump: {missing}")
    report(h[h["pair"].isin(selected)], f"RE-AGGREGATED on {len(selected)} pairs: {sorted(selected)}", hold_bars)

    if args.split_new:
        rest = sorted(set(h["pair"].unique()) - set(selected))
        if rest:
            report(h[h["pair"].isin(rest)], f"the remaining pairs only: {rest}", hold_bars)


if __name__ == "__main__":
    main()
