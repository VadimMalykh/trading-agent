"""`python -m m3 <subcommand>` — the entry point scripts/m3.sh drives.

    ./scripts/m3.sh -m m3 validate            # the two acceptance tests (run this first)
    ./scripts/m3.sh -m m3 power               # the pre-registration facts (M3_PROTOCOL §2/§4)
    ./scripts/m3.sh -m m3 policy --help       # score one policy spec
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime, validate


def cmd_validate(args) -> int:
    return validate.main()


# The grid docs/M3_PROTOCOL.md §3 pre-registers. It lives here, in code, so that "the 36
# configurations" is a list a later session can re-derive rather than a claim in prose.
GRID_COVERAGE = (0.01, 0.02, 0.05)
GRID_HOLD = (60, 240, 1440)
GRID_REGIME_Q = (None, 0.80)
GRID_MAX_CONC = (None, 3)
MIN_TRADES_PER_WINDOW = 100          # M3_PROTOCOL §4 rule P4


def primary_grid() -> list[backtest.PolicySpec]:
    """The 3 x 3 x 2 x 2 = 36 specs of the primary grid, in a fixed, reproducible order."""
    specs = []
    for cov in GRID_COVERAGE:
        for hold in GRID_HOLD:
            for rq in GRID_REGIME_Q:
                for mc in GRID_MAX_CONC:
                    specs.append(backtest.PolicySpec(
                        coverage=cov, signal_horizon=240, hold_horizon=hold,
                        regime_col="btc_absret_1d" if rq is not None else None,
                        regime_quantile=rq, max_concurrent=mc,
                        label=f"cov{cov:g}_hold{hold}_rq{rq if rq else 'none'}_mc{mc or 'none'}",
                    ))
    return specs


def cmd_power(args) -> int:
    """Print the sample-size and uncertainty facts M3-1 pre-registers on — COUNTS ONLY.

    No net-P&L number for any grid config is printed here, deliberately: this command runs
    BEFORE the search and its whole purpose is to fix the eligibility rule without anyone
    having seen which configs make money. The one P&L figure it does show is §1.3's
    already-published cov05 slice, used to calibrate the standard error.
    """
    ds = dumps.load_baseline(pairs=dumps.BASE8)

    print("=" * 88)
    print("A. DATA EXTENT — the windows are not equal, and two are truncated by the dump")
    print("=" * 88)
    allbars = pd.concat([dumps.add_window(d.at(240)) for d in ds], ignore_index=True)
    for name, lo, hi in dumps.WINDOWS:
        sub = allbars[allbars["window"] == name]
        t = pd.to_datetime(sub["ts"], unit="ns", utc=True)
        days = (t.max() - t.min()).total_seconds() / 86400 if len(sub) else 0.0
        print(f"  {name} [{lo} .. {hi})  bars={len(sub):>7,}  actual span={days:5.1f}d  "
              f"{t.min():%Y-%m-%d} .. {t.max():%Y-%m-%d}")

    print("\n" + "=" * 88)
    print("B. STANDARD ERROR CALIBRATION on §1.3's published cov05 slice")
    print("=" * 88)
    t = backtest.run(ds, backtest.PolicySpec(coverage=0.05, signal_horizon=240)).trades
    for cost, name in ((0.0, "gross"), (metrics.TAKER_COST_BPS, "net @ taker 14bps")):
        c = metrics.clustered_mean_bps(t, cost)
        x = (t["signed_ret"] - cost / metrics.BPS).to_numpy() * metrics.BPS
        iid = x.std(ddof=1) / np.sqrt(len(x))
        print(f"  {name:>18}: mean={c['mean_bps']:+6.2f}  n={c['n']:,}  clusters={c['clusters']}  "
              f"iid_se={iid:.2f}  clustered_se={c['se_bps']:.2f}  ({c['se_bps']/iid:.2f}x)  "
              f"95% CI=[{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]")
    print(f"  per-trade sd = {x.std(ddof=1):.1f} bps")

    print("\n" + "=" * 88)
    print(f"C. TRADE COUNTS per window for all {len(primary_grid())} primary-grid configs.")
    print(f"   ELIGIBLE = every window has >= {MIN_TRADES_PER_WINDOW} pooled trades (rule P4).")
    print("=" * 88)
    regimes = {d.seed: regime.build(d.df) for d in ds}
    print(f"{'config':<40}" + "".join(f"{n:>8}" for n in ("w1", "w2", "w3", "w4", "total"))
          + "   eligible")
    eligible = []
    for spec in primary_grid():
        tr = dumps.add_window(backtest.run(ds, spec, regimes).trades, ts_col="entry_ts")
        per = [int((tr["window"] == n).sum()) for n in ("w1", "w2", "w3", "w4")]
        ok = min(per) >= MIN_TRADES_PER_WINDOW
        eligible.append(ok)
        print(f"{spec.label:<40}" + "".join(f"{v:>8,}" for v in per + [len(tr)])
              + f"   {'YES' if ok else 'no'}")
    print(f"\n  {sum(eligible)} of {len(eligible)} configs are eligible for promotion; "
          f"the rest are under-sampled and are reported but cannot win (M3_PROTOCOL §4).")
    return 0


def cmd_policy(args) -> int:
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    spec = backtest.PolicySpec(
        coverage=args.coverage,
        signal_horizon=args.signal_horizon,
        hold_horizon=args.hold_horizon,
        regime_col=args.regime_col,
        regime_quantile=args.regime_quantile,
        regime_min=args.regime_min,
        size_by_regime=args.size_by_regime,
        max_concurrent=args.max_concurrent,
        sides=args.sides,
        label=args.label or "policy",
    )
    regimes = {d.seed: regime.build(d.df) for d in ds} if spec.regime_col else None
    res = backtest.run(ds, spec, regimes)
    t = res.trades

    print(f"\npolicy: {spec}")
    print(f"per-seed confidence thresholds: "
          + ", ".join(f"{k}={v:.4f}" for k, v in res.thresholds.items()))
    if res.regime_thresholds:
        print("per-seed regime thresholds:   "
              + ", ".join(f"{k}={v:.4f}" for k, v in res.regime_thresholds.items()))

    span = metrics.span_days(t)
    for cost, name in ((metrics.MAKER_COST_BPS, "maker 5bps"), (metrics.TAKER_COST_BPS, "taker 14bps")):
        s = metrics.summarise(t, cost, span, n_seeds=len(ds))
        print(f"\n--- {name} " + "-" * 60)
        print(f"trades={s['trades']:,}  gross={s['gross_bps']:+.2f}bps  net={s['net_bps']:+.2f}bps  "
              f"win={s['win']:.3f}  trades/day={s['trades_per_day']:.2f}  "
              f"maxdd={s['maxdd']:.4f}  sharpe={s['sharpe']:.2f}")
        w = metrics.by_window(t, cost)
        print(w.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))
        worst = w.loc[w["net_bps"].idxmin()]
        print(f"WORST WINDOW: {worst['window']}  net={worst['net_bps']:+.2f}bps  "
              f"(n={int(worst['trades'])}) — this is the number M3-1 scores on")
        print(metrics.side_split(t, cost).to_string(index=False,
                                                    float_format=lambda v: f"{v:+.3f}"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="m3", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="run the two acceptance tests").set_defaults(fn=cmd_validate)
    sub.add_parser("power", help="pre-registration facts: spans, SE calibration, eligibility"
                   ).set_defaults(fn=cmd_power)

    p = sub.add_parser("policy", help="score one policy spec")
    p.add_argument("--coverage", type=float, default=0.05)
    p.add_argument("--signal-horizon", type=int, default=240)
    p.add_argument("--hold-horizon", type=int, default=None, choices=[60, 240, 1440])
    p.add_argument("--regime-col", default=None)
    p.add_argument("--regime-quantile", type=float, default=None,
                   help="threshold as a quantile of BARS, re-derived per split")
    p.add_argument("--regime-min", type=float, default=None, help="absolute threshold (discouraged)")
    p.add_argument("--size-by-regime", action="store_true")
    p.add_argument("--max-concurrent", type=int, default=None)
    p.add_argument("--sides", default="both", choices=["both", "long", "short"])
    p.add_argument("--label", default="")
    p.set_defaults(fn=cmd_policy)

    args = ap.parse_args()
    return args.fn(args)
