"""The acceptance tests. Run these before believing any policy number this package prints.

M3_PLAN §M3-0a and §6 make two reproductions non-optional, for the same reason
`reaggregate_preds.py --validate` exists: this code deliberately duplicates definitions
that live in `eval_m2.py` / `gate.py`, and a duplicate that has drifted produces numbers
that look fine and are wrong.

  TEST 1 — fixed coverage. Under the trivial policy "enter when in the top c% by
  confidence, hold 48 bars, exit", reproduce each seed's LOGGED table (trades, gross bps,
  win rate). The reference constants below are copied from logs/O2.log, logs/P0-seed2.log
  and logs/P0-seed3.log, i.e. from the trainer's own output rather than from a summary.

  TEST 2 — the regime ladder. Reproduce NEXT_TRAINING_PLAN §1.8's cov05 quintile ladder for
  `btc_absret_1d`, which is the finding the whole milestone rests on and whose harness was
  never committed (M3_PLAN §1.4, risk #6).

TIE CELL. Seed 3 at cov05 has two bars tied at the boundary confidence for one slot, so the
selection there is not uniquely defined by "top 5%". The tie-inclusive rule this harness
uses (backtest.py) reproduces the logged cell anyway; `reaggregate_preds.py`'s argpartition
does not (1,222 trades / +9.43 against the logged 1,223 / +9.60). The check below therefore
still demands a digit-exact match everywhere and only tolerates that one cell if it moves.

"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest, dumps, regime
from .metrics import BPS

# --- Reference: the trainer's own logged tables, primary horizon 240m -----------------
# seed -> cov -> (trades, gross_bps, win)
PUBLISHED_FIXED_COV = {
    "s1": {0.01: (469, +24.50, 0.597), 0.02: (708, +22.11, 0.581), 0.05: (1361, +3.50, 0.546),
           0.10: (2577, -5.16, 0.515), 0.20: (4489, -3.13, 0.524)},
    "s2": {0.01: (283, +16.59, 0.597), 0.02: (486, +16.83, 0.582), 0.05: (1134, +14.66, 0.550),
           0.10: (2141, +4.90, 0.534), 0.20: (4239, +1.81, 0.536)},
    "s3": {0.01: (329, +14.47, 0.571), 0.02: (589, +26.23, 0.569), 0.05: (1223, +9.60, 0.554),
           0.10: (2386, +6.80, 0.538), 0.20: (4734, +1.34, 0.523)},
}

# NEXT_TRAINING_PLAN §1.3's pooled table (trade-weighted across the three seeds).
PUBLISHED_POOLED = {0.01: (1081, +19.38), 0.02: (1783, +22.03), 0.05: (3718, +8.91),
                    0.10: (7104, +1.89), 0.20: (13462, -0.00)}

# NEXT_TRAINING_PLAN §1.8, pooled cov05 trades bucketed into quintiles by btc_absret_1d.
PUBLISHED_LADDER_BPS = [-3.4, -15.3, +10.1, +17.4, +35.5]
PUBLISHED_LADDER_DIR_ACC = [0.517, 0.494, 0.545, 0.579, 0.618]
PUBLISHED_LADDER_N = 3717
PUBLISHED_Q5_PER_SEED = [+34.8, +32.5, +38.7]

# §1.8's rule, evaluated at three coverages: (in-state trades, in-state bps, out bps)
PUBLISHED_RULE = {0.05: (742, +35.5, None), 0.02: (493, +54.9, +9.1), 0.01: (339, +45.9, +7.2)}


def _dir_acc(trades: pd.DataFrame) -> tuple[float, int]:
    """Directional accuracy over a trade set: flat bars (y3 == 1) are excluded, exactly as
    gate.py does, and a trade is a hit when its side matches the realised class."""
    d = trades[trades["y3"] != 1]
    if d.empty:
        return 0.0, 0
    predicted = np.where(d["side"].to_numpy() > 0, 2, 0)
    hits = int((predicted == d["y3"].to_numpy()).sum())
    return hits / len(d), len(d)


def test_fixed_coverage(ds: list[dumps.Dump]) -> bool:
    print("\n" + "=" * 88)
    print("TEST 1 — fixed-coverage reproduction (trivial policy: top-c%, hold 48 bars)")
    print("=" * 88)
    ok = True
    pooled_rows = []
    for cov in (0.01, 0.02, 0.05, 0.10, 0.20):
        res = backtest.run(ds, backtest.PolicySpec(coverage=cov, label=f"fixedcov{cov}"))
        tot_trades, tot_ret = 0, 0.0
        print(f"\ncov={cov:.2f}   {'seed':>5} {'trades':>8} {'published':>10} "
              f"{'gross_bps':>10} {'published':>10} {'win':>6} {'published':>10}  verdict")
        for d in ds:
            t = res.trades[res.trades["seed"] == d.seed]
            g = t["signed_ret"].mean() * BPS
            w = float((t["signed_ret"] > 0).mean())
            p_tr, p_g, p_w = PUBLISHED_FIXED_COV[d.seed][cov]
            match = (len(t) == p_tr) and abs(g - p_g) < 0.005 and abs(w - p_w) < 0.0005
            ok &= match or (d.seed == "s3" and cov == 0.05)   # the documented tie cell
            note = "MATCH" if match else ("tie-cell (known, §backtest docstring)"
                                          if d.seed == "s3" and cov == 0.05 else "🔴 MISMATCH")
            print(f"       {d.seed:>5} {len(t):8,} {p_tr:10,} {g:+10.2f} {p_g:+10.2f} "
                  f"{w:6.3f} {p_w:10.3f}  {note}")
            tot_trades += len(t)
            tot_ret += float(t["signed_ret"].sum())
        pooled_bps = tot_ret / tot_trades * BPS if tot_trades else 0.0
        p_tr, p_g = PUBLISHED_POOLED[cov]
        pooled_rows.append((cov, tot_trades, p_tr, pooled_bps, p_g))
    print(f"\n{'cov':>6} {'pooled trades':>14} {'published':>10} {'pooled bps':>11} {'published':>10}")
    for cov, tr, p_tr, bps, p_g in pooled_rows:
        print(f"{cov:6.2f} {tr:14,} {p_tr:10,} {bps:+11.2f} {p_g:+10.2f}")
    print("\n(the pooled row is trade-weighted across seeds; §1.3 prints 3718 at cov05 where "
          "§1.8 prints 3717 — 3717 is the reproducible count)")
    return ok


def test_regime_ladder(ds: list[dumps.Dump], regimes: dict) -> bool:
    print("\n" + "=" * 88)
    print("TEST 2 — the §1.8 regime ladder for btc_absret_1d, rebuilt from the dumps")
    print("=" * 88)

    res = backtest.run(ds, backtest.PolicySpec(coverage=0.05, label="cov05"))
    t = res.trades.merge(
        pd.concat([r.assign(seed=s) for s, r in regimes.items()])[
            ["seed", "pair", "ts", "btc_absret_1d"]
        ].rename(columns={"ts": "entry_ts"}),
        on=["seed", "pair", "entry_ts"], how="left",
    )
    n_missing = int(t["btc_absret_1d"].isna().sum())
    t = t.dropna(subset=["btc_absret_1d"])
    print(f"\npooled cov05 trades with a regime value: {len(t):,} "
          f"(published {PUBLISHED_LADDER_N:,}; {n_missing} dropped for an incomplete lookback)")

    t["q"] = pd.qcut(t["btc_absret_1d"], 5, labels=False)
    print(f"\n{'quintile':>9} {'trades':>8} {'gross_bps':>10} {'published':>10} "
          f"{'dir_acc':>8} {'published':>10} {'range of btc_absret_1d':>26}")
    ok = True
    for q in range(5):
        sub = t[t["q"] == q]
        bps = sub["signed_ret"].mean() * BPS
        acc, _ = _dir_acc(sub)
        pb, pa = PUBLISHED_LADDER_BPS[q], PUBLISHED_LADDER_DIR_ACC[q]
        close = abs(bps - pb) < 3.0 and abs(acc - pa) < 0.02
        ok &= close
        rng = f"{sub['btc_absret_1d'].min():.4f}–{sub['btc_absret_1d'].max():.4f}"
        print(f"{'Q' + str(q + 1):>9} {len(sub):8,} {bps:+10.1f} {pb:+10.1f} "
              f"{acc:8.3f} {pa:10.3f} {rng:>26}  {'ok' if close else '🔴'}")

    print(f"\nQ5 per seed (published {PUBLISHED_Q5_PER_SEED}):")
    for d in ds:
        sub = t[(t["seed"] == d.seed) & (t["q"] == 4)]
        print(f"   {d.seed}: {sub['signed_ret'].mean() * BPS:+.1f} bps  (n={len(sub)})")

    # The rule as §1.8 states it: an absolute threshold on BTC's trailing-24h |return|.
    q5_cut = float(t[t["q"] == 4]["btc_absret_1d"].min())
    bars = pd.concat(regimes.values())["btc_absret_1d"].dropna()
    frac = float((bars >= q5_cut).mean())
    print(f"\nthe Q5 boundary this rebuild derives: {q5_cut:.4f} "
          f"(published {regime.PUBLISHED_REGIME_THRESHOLD:.4f}); "
          f"it selects {frac:.3%} of bars (published {regime.PUBLISHED_REGIME_BAR_FRACTION:.1%})")
    return ok


def main(pairs=None) -> int:
    ds = dumps.load_baseline(pairs=pairs or dumps.BASE8)
    print(f"loaded {len(ds)} dumps: " + ", ".join(f"{d.seed}={d.run_id}" for d in ds))

    drift = regime.check_compounding(ds[0].df)
    print(f"horizon compounding check (§1.8 reported 3.2e-7): max abs diff {drift:.2e}")

    ok1 = test_fixed_coverage(ds)
    regimes = {d.seed: regime.build(d.df) for d in ds}
    ok2 = test_regime_ladder(ds, regimes)

    print("\n" + "=" * 88)
    print(f"TEST 1 fixed coverage : {'PASS' if ok1 else '🔴 FAIL'}")
    print(f"TEST 2 regime ladder  : {'PASS' if ok2 else '🔴 FAIL'}")
    print("=" * 88)
    return 0 if (ok1 and ok2) else 1
