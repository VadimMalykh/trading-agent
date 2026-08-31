"""B2 — book features as M3 regime observables. BOOK_ERA_PLAN.md §B2, gated by §4.2.

## Why this is the highest-expected-value step in the wave

§0.4 says the most probable payoff of the book era is not a second model but **one or two
new regime observables for M3's policy**. The reasoning: the 2026-08-04 audit's strongest
feature was `spread_bps` and the audit classified it **VOL-PROXY** — it predicts how big the
next move is, not which way. That is useless to M2, which emits direction. It is potentially
very valuable to M3, whose largest measured effect (Q1's 4x) *is* a volatility regime
switch, currently keyed off `btc_absret_1d` — BTC's **trailing** 24-hour move. A book-derived
observable would be **contemporaneous**, which is the whole appeal.

## The comparison

For each candidate, restricted to the book era and at fixed coverage:

    baseline            no regime gate at all
    marginal            gate on the candidate's top quintile of BARS
    conditional         the same gate, inside the bars where btc_absret_1d is NOT in its own
                        top quintile

🔴 **The conditional column is the one that matters.** A book observable that lifts P&L only
where `btc_absret_1d` was already firing is the same regime measured a second way, and is
worth very little. One that lifts inside the calm-BTC subset is orthogonal, and is worth a
lot — it would fire on exactly the days the incumbent observable sleeps through.

## Scaling, and why the primary construction is market-wide

`spread_bps` on 1000PEPEUSDT and on BTCUSDT are not the same number, so a gate on the pooled
raw column selects **wide-spread pairs**, not wide-spread moments — a pair filter wearing a
regime's clothes. Every candidate is therefore mapped to its within-pair percentile first.
The **primary** construction then averages that percentile across pairs at each timestamp and
broadcasts it back, which makes it a market-wide observable directly analogous to
`btc_absret_1d`. The per-pair version is printed as a labelled diagnostic, not as a test.

## The gate, and the thing that is easy to get wrong

§4.2: a candidate is worth carrying into M3 if it moves the book-era cov02 slice by **more
than +30 gross bps/trade**, **and** survives conditioning on `btc_absret_1d`, **and** agrees
in sign across all three seeds.

🔴 **That bar is deliberately high because 38 days cannot resolve less** — §1.6 puts the
book-era cov02 CI half-width at ±36 bps. The plan states in advance that **a real +15 bps
effect would fail this gate**, and that such a result must be recorded as **"not yet
decidable", never as a negative result.** Do not let this print a red X and get read as "the
book is useless"; it can only say "big effect" or "cannot tell yet".
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime
from .bookaudit import BOOK_DIR

# The pre-registered candidate list, §B2. `oi_chg` is named there too but B0 could not build
# it — `open_interest` is not one of the tables scripts/gcp_m3_export.sh pulls, filed in
# BACKLOG.md as a one-line export change. Four tests, not a scan; adding a fifth after
# seeing these is exactly the shopping M3_PROTOCOL §0 forbids.
CANDIDATES = ["spread_bps", "trade_count", "trade_vol"]
COMPOSITE = "book_composite"
INCUMBENT = "btc_absret_1d"
REGIME_QUANTILE = 0.80          # Q1's framing: the top quintile of BARS
COVERAGES = [0.02, 0.05]
GATE_LIFT_BPS = 30.0            # §4.2
CI_HALF_WIDTH_BPS = 36.0        # §1.6 — what 38 days can actually resolve


def load_book(pairs: list[str]) -> pd.DataFrame:
    path = os.path.join(BOOK_DIR, "book_era_5m.parquet")
    if not os.path.exists(path):
        raise SystemExit(f"{path} missing — run `./scripts/m3.sh -m m3 bookera` (B0) first")
    b = pd.read_parquet(path)
    b = b[b["pair"].isin(pairs) & (b["has_book"] == 1) & (b["has_trades"] == 1)]
    return b.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)


def observables(book: pd.DataFrame) -> pd.DataFrame:
    """(pair, ts) frame of the candidate observables, both constructions."""
    out = book[["pair", "ts"]].copy()
    mkt_cols = []
    for f in CANDIDATES:
        u = book.groupby("pair", observed=True)[f].rank(pct=True)
        out[f + "_pair"] = u.to_numpy()                       # diagnostic
        mkt_cols.append(f)
        out[f + "_tmp"] = u.to_numpy()
    # market-wide: the cross-sectional mean of the per-pair percentile at each timestamp,
    # broadcast back to every pair — one number describing the market, like btc_absret_1d.
    mkt = out.groupby("ts", observed=True)[[f + "_tmp" for f in mkt_cols]].mean()
    mkt.columns = [f + "_mkt" for f in mkt_cols]
    out = out.merge(mkt.reset_index(), on="ts", how="left")
    out[COMPOSITE] = out[[f + "_mkt" for f in mkt_cols]].mean(axis=1)
    out = out.drop(columns=[f + "_tmp" for f in mkt_cols])
    # 🔴 BOTH TAILS. `backtest.run`'s regime filter always keeps the TOP quantile, so a gate
    # on a column is a gate on its high end. B1 measured `spread_bps` correlating NEGATIVELY
    # with |fwd_ret| (vol_rho -0.28), so for that candidate the volatile tail is the LOW one
    # and testing only the top would test the wrong hypothesis. Negated columns make the low
    # tail reachable through the same code path.
    #
    # ⚠️ This DOUBLES the number of tests, and the orientation is chosen from the data rather
    # than in advance. Read the gate accordingly: it is being asked to clear a bar that is
    # effectively twice as wide, which is another reason a pass here is a hypothesis and not
    # a finding.
    for c in list(out.columns):
        if c.endswith("_mkt") or c == COMPOSITE:
            out[c + "_lo"] = -out[c]
    return out


def primary_observables() -> list[str]:
    hi = [f + "_mkt" for f in CANDIDATES] + [COMPOSITE]
    return hi + [c + "_lo" for c in hi]


def diagnostic_observables() -> list[str]:
    return [f + "_pair" for f in CANDIDATES]


def restrict(d: dumps.Dump, keys: pd.DataFrame) -> dumps.Dump:
    """A dump restricted to a set of (pair, ts) bars, every horizon kept.

    Restricting the BAR POPULATION rather than the trade ledger is what makes the baseline
    and the gated arm comparable: both then rank inside the same book era, so the coverage
    cut means the same thing in both.
    """
    df = d.df.merge(keys[["pair", "ts"]].drop_duplicates(), on=["pair", "ts"], how="inner")
    return dumps.Dump(seed=d.seed, run_id=d.run_id, df=df)


def _spec(coverage: float, col: str | None) -> backtest.PolicySpec:
    return backtest.PolicySpec(
        coverage=coverage, signal_horizon=240, hold_horizon=240,
        regime_col=col, regime_quantile=REGIME_QUANTILE if col else None,
        size_by_regime=False, max_concurrent=None,
        label=f"cov{coverage}_{col or 'nogate'}")


def _score(ds: list, regimes: dict, coverage: float, col: str | None) -> dict:
    t = backtest.run(ds, _spec(coverage, col), regimes).trades
    per_seed = {}
    for seed in {d.seed for d in ds}:
        sub = t[t["seed"] == seed]
        per_seed[seed] = float(sub["signed_ret"].mean() * metrics.BPS) if len(sub) else float("nan")
    return {
        "n": len(t),
        "gross_bps": float(t["signed_ret"].mean() * metrics.BPS) if len(t) else float("nan"),
        "per_seed": per_seed,
    }


def run(ds: list, book: pd.DataFrame, obs: pd.DataFrame) -> dict:
    """Baseline / marginal / conditional, for every observable at every coverage."""
    keys = obs[["pair", "ts"]]
    ds_era = [restrict(d, keys) for d in ds]
    if any(d.df.empty for d in ds_era):
        raise SystemExit("a dump has no rows inside the book era — check the (pair, ts) join")

    regimes = {}
    for d in ds_era:
        r = regime.build(d.df)
        regimes[d.seed] = r.merge(obs, on=["pair", "ts"], how="left")

    # The calm-BTC subset: bars OUTSIDE the incumbent's own top quintile. Taken per seed off
    # that seed's own regime frame, because the cut has to be a quantile of the bars the
    # policy is actually ranking over.
    ds_calm, regimes_calm = [], {}
    for d in ds_era:
        r = regimes[d.seed]
        cut = float(r[INCUMBENT].quantile(REGIME_QUANTILE))
        calm = r[r[INCUMBENT] < cut][["pair", "ts"]]
        dc = restrict(d, calm)
        ds_calm.append(dc)
        regimes_calm[d.seed] = r.merge(calm, on=["pair", "ts"], how="inner")

    results = {}
    for c in COVERAGES:
        base = _score(ds_era, regimes, c, None)
        base_calm = _score(ds_calm, regimes_calm, c, None)
        rows = []
        for col in [INCUMBENT] + primary_observables() + diagnostic_observables():
            marg = _score(ds_era, regimes, c, col)
            cond = _score(ds_calm, regimes_calm, c, col)
            rows.append({
                "observable": col,
                "primary": col in primary_observables() or col == INCUMBENT,
                "n_marg": marg["n"], "marg_bps": marg["gross_bps"],
                "marg_lift": marg["gross_bps"] - base["gross_bps"],
                "n_cond": cond["n"], "cond_bps": cond["gross_bps"],
                "cond_lift": cond["gross_bps"] - base_calm["gross_bps"],
                "seed_lifts": {k: marg["per_seed"][k] - base["per_seed"][k]
                               for k in marg["per_seed"]},
            })
        results[c] = {"baseline": base, "baseline_calm": base_calm,
                      "rows": pd.DataFrame(rows)}
    return results


def gate(results: dict) -> dict:
    """§4.2, evaluated exactly as written — and it can only say PASS or NOT-YET-DECIDABLE."""
    tbl = results[0.02]["rows"]
    cand = tbl[tbl["primary"] & (tbl["observable"] != INCUMBENT)]
    verdicts = []
    for r in cand.itertuples():
        signs = [np.sign(v) for v in r.seed_lifts.values() if np.isfinite(v)]
        agree = len(signs) > 0 and len(set(signs)) == 1
        verdicts.append({
            "observable": r.observable, "marg_lift": r.marg_lift, "cond_lift": r.cond_lift,
            "seeds_agree": agree,
            "pass": bool(r.marg_lift > GATE_LIFT_BPS and r.cond_lift > 0 and agree),
        })
    v = pd.DataFrame(verdicts)
    return {"rows": v, "pass": bool(v["pass"].any()) if len(v) else False}
