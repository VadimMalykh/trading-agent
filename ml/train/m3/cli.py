"""`python -m m3 <subcommand>` — the entry point scripts/m3.sh drives.

    ./scripts/m3.sh -m m3 validate            # the two acceptance tests (run this first)
    ./scripts/m3.sh -m m3 policy --help       # score one policy spec
"""
from __future__ import annotations

import argparse

from . import backtest, dumps, metrics, regime, validate


def cmd_validate(args) -> int:
    return validate.main()


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
