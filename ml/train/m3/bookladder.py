"""BOOK_ERA_PLAN §R.4 — X7: a book observable as the size-ladder key.

The live policy sizes every trade by the BAR-quintile of `btc_absret_1d` (⅓ .. 5⁄3). On the
book era that key points the wrong way (§R.1). This harness keeps the incumbent's trades exactly
and swaps only the ladder's key for one of §B2's registered book observables, so every arm takes
identical trades and the contrast is a same-entries, per-notional one (§9.6's statistic).

Why the population is narrowed before anything is ranked: `backtest.run` drops a selected bar
whose `regime_col` is missing, so two arms keyed on columns with different gaps would take
different trades. Restricting every seed to bars where the incumbent key AND all ten book keys
are present makes `regime_col` affect the size alone — and the harness check verifies it.

🔴 The exploration population is the book era B1/B2 already read. It can close the question, not
establish it; the confirmation (§R.4) is on untouched forward bars and is built when due.

Everything here is fixed by §R.4 before any number was read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import backtest, bookregime, dumps, metrics, regime
from . import walkforward as wf

COVERAGE = 0.05                       # §R.4: the only decidable coverage
COVERAGE_INFO = 0.02
INCUMBENT = bookregime.INCUMBENT
SERVED_SEED = "s2"
CONFIRM_ON_OR_AFTER = "2027-03-10"
CONFIRM_DAYS = 180.0
COST = metrics.TAKER_COST_BPS
SIZES = np.array([1.0, 2.0, 3.0, 4.0, 5.0]) / 3.0


def population(ds: list[dumps.Dump], obs: pd.DataFrame) -> tuple[list[dumps.Dump], dict, list[str]]:
    """Each seed's bars restricted to the book era and to rows where every key is present."""
    keys = bookregime.primary_observables(obs)
    cols = [INCUMBENT] + keys
    out_ds, regimes = [], {}
    for d in ds:
        de = bookregime.restrict(d, obs[["pair", "ts"]])
        r = regime.build(de.df).merge(obs, on=["pair", "ts"], how="left")
        r = r[r[cols].notna().all(axis=1)].reset_index(drop=True)
        out_ds.append(bookregime.restrict(de, r[["pair", "ts"]]))
        regimes[d.seed] = r
    return out_ds, regimes, keys


def arm(ds: list[dumps.Dump], regimes: dict, sized_fields: dict, coverage: float,
        key: str | None) -> pd.DataFrame:
    """`key=None` is the flat arm: the incumbent's regime column (same NaN population), size 1."""
    f = {**sized_fields, "coverage": coverage, "regime_col": key or INCUMBENT,
         "size_by_regime": key is not None}
    return backtest.run(ds, backtest.PolicySpec(label=key or "flat", **f), regimes).trades


def check_same_trades(a: pd.DataFrame, inc: pd.DataFrame) -> tuple[bool, str]:
    cols = ["seed", "pair", "entry_ts"]
    x = a[cols].sort_values(cols).to_numpy()
    y = inc[cols].sort_values(cols).to_numpy()
    same = x.shape == y.shape and bool((x == y).all())
    sizes_ok = bool(np.isclose(a["size"].to_numpy()[:, None], SIZES[None, :]).any(axis=1).all()) \
        or bool(np.allclose(a["size"].to_numpy(), 1.0))
    return same and sizes_ok, f"{len(a):,} vs {len(inc):,} trades, identical={same}, sizes on the ladder={sizes_ok}"


def ledger(t: pd.DataFrame) -> pd.DataFrame:
    return wf._ledger(wf._utc_day(t["exit_ts"]), t["signed_ret"].to_numpy(np.float64),
                      t["size"].to_numpy(np.float64), "trade")


def contrast(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    return wf.paired_notional_diff_bps(ledger(a), ledger(b))


def _span_days(t: pd.DataFrame) -> float:
    return float((t["exit_ts"].max() - t["entry_ts"].min()) / 86_400e9) if len(t) else 0.0


def _table(arms: dict[str, pd.DataFrame], keys: list[str]) -> tuple[pd.DataFrame, dict]:
    inc, flat = arms["incumbent"], arms["flat"]
    rows, pooled = [], {}
    for k in keys:
        t = arms[k]
        c = contrast(t, inc)
        pooled[k] = c
        per = {s: contrast(t[t["seed"] == s], inc[inc["seed"] == s])["diff_bps"] for s in ("s1", "s2", "s3")}
        rows.append({"key": k, "vs incumbent": c["diff_bps"],
                     "95% CI": f"[{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]", "se": c["se_bps"],
                     "days": c["clusters"], "s1": per["s1"], "s2": per["s2"], "s3": per["s3"],
                     "median seed": float(np.median(list(per.values()))),
                     "vs flat": contrast(t, flat)["diff_bps"],
                     "net/notional @14": wf.notional_ratio_bps(ledger(t), COST)["mean_bps"]})
    return pd.DataFrame(rows), pooled


def report(sized_fields: dict, stage: str, exploration_recorded: bool = False,
           config: str | None = None) -> int:
    print("=" * 96)
    print(f"BOOK_ERA_PLAN §R.4 — X7: A BOOK OBSERVABLE AS THE SIZE-LADDER KEY — stage {stage.upper()}")
    print("=" * 96)
    if stage == "confirm":
        today = pd.Timestamp.now(tz="UTC").normalize()
        if today < pd.Timestamp(CONFIRM_ON_OR_AFTER, tz="UTC"):
            print(f"\n🔴 refusing: §R.4's confirmation is read once, on or after {CONFIRM_ON_OR_AFTER}; "
                  f"no earlier look at the forward window is permitted.")
            return 2
        if not exploration_recorded or not config:
            print("\n🔴 refusing: pass --exploration-recorded and --config <key> transcribed from §R.4.")
            return 2
        print("\n🔴 the confirmation loader (policy_bars + forward candle and book exports) is built when")
        print("   due, from §R.4's confirmation paragraph. It does not exist yet.")
        return 2
    if stage != "explore":
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")
    if dumps.ERA != "repaired":
        print(f"\n🔴 refusing: §R.4 explores on M3_ERA=repaired, got {dumps.ERA!r}.")
        return 2

    print("\n🔴 NOT CLEAN EVIDENCE: B1/B2 already read these bars and scored these keys as filters.")
    print("   This stage can close the question; only the forward confirmation can establish it.")
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    obs = bookregime.observables(bookregime.load_book(dumps.BASE8))
    ds_pop, regimes, keys = population(ds, obs)
    for d in ds_pop:
        t = pd.to_datetime(d.df["ts"], unit="ns", utc=True)
        print(f"  {d.seed}: {d.df[['pair', 'ts']].drop_duplicates().shape[0]:,} bars x {d.df['pair'].nunique()} pairs, "
              f"{t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")
    print(f"  keys ({len(keys)}): {', '.join(keys)}")

    for cov in (COVERAGE, COVERAGE_INFO):
        label = "PRIMARY" if cov == COVERAGE else "information only"
        print("\n" + "=" * 96)
        print(f"COVERAGE {cov} — {label}")
        print("=" * 96)
        arms = {"incumbent": arm(ds_pop, regimes, sized_fields, cov, INCUMBENT),
                "flat": arm(ds_pop, regimes, sized_fields, cov, None)}
        for k in keys:
            arms[k] = arm(ds_pop, regimes, sized_fields, cov, k)
        inc = arms["incumbent"]
        bad = False
        for name, t in arms.items():
            if name == "incumbent":
                continue
            ok, msg = check_same_trades(t, inc)
            if not ok or name == "flat":
                print(f"  harness check {name}: {'PASS' if ok else 'FAIL'} — {msg}")
            bad |= not ok
        if bad:
            print("  🔴 harness check failed; nothing below may be read.")
            return 3
        print(f"  harness check: all {len(keys)} key arms take the incumbent's {len(inc):,} trades exactly — PASS")
        e = contrast(inc, arms["flat"])
        ni = wf.notional_ratio_bps(ledger(inc), COST)
        print(f"  incumbent net/notional @14 {ni['mean_bps']:+.2f}; "
              f"E (incumbent ladder − flat) {e['diff_bps']:+.2f} [{e['lo95_bps']:+.2f}, {e['hi95_bps']:+.2f}]; "
              f"span {_span_days(inc):.1f} days")
        table, pooled = _table(arms, keys)
        print(table.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))

        if cov != COVERAGE:
            continue
        best = table.sort_values("vs incumbent", ascending=False).iloc[0]
        k = best["key"]
        s2 = contrast(arms[k][arms[k]["seed"] == SERVED_SEED], inc[inc["seed"] == SERVED_SEED])
        days = _span_days(inc)
        mde = 1.96 * s2["se_bps"] * np.sqrt(days / CONFIRM_DAYS) if days else float("nan")
        passed = best["vs incumbent"] > 0 and best["median seed"] > 0
        print("\n" + "=" * 96)
        print("THE VERDICT, under §R.4 as written")
        print("=" * 96)
        print(f"  chosen by the rule (highest pooled contrast): {k}  {best['vs incumbent']:+.2f} {best['95% CI']}; "
              f"median seed {best['median seed']:+.2f}")
        print(f"  forecast confirmation MDE (s2-only SE {s2['se_bps']:.2f} x sqrt({days:.0f}/{CONFIRM_DAYS:.0f}) x 1.96): "
              f"{mde:.2f} bps per notional")
        print(f"  exploration gate: best > 0 -> {best['vs incumbent'] > 0}; median seed > 0 -> {best['median seed'] > 0}")
        verdict = (f"GATE PASSED — record this in §R.4 and add the confirmation row to BACKLOG, dated "
                   f"{CONFIRM_ON_OR_AFTER}, key {k}") if passed else \
            "GATE NOT PASSED — §R.4 closes here; nothing is exported"
        print(f"\n  ==> {verdict}")
    return 0
