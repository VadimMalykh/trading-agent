"""WALKFORWARD_PROTOCOL §9.9 (X18) — the 1440-minute head as its own policy arm.

The served model emits a 24-hour forecast at every bar that the policy has never traded on
(M3-2's `hold1440` gated on the 240m head). This module scores it as a policy arm of its own:
gate on the 1440m head's confidence at a coverage cut, hold 1440 minutes, the incumbent's size
ladder and one-position-per-pair rule, taker cost — and compares what it earns **per calendar
day** with what the incumbent earns on the same days.

Explore on the served family's three X8″ dumps (`bookentry.RUNS`); confirm once on the
X8-recipe folds F2 + F3 (`dumps.WALKFORWARD_X8_RUNS`), whose val windows are disjoint from the
served window. Everything below is mechanics fixed by §9.9 before any number was read.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import backtest, bookentry, dumps, metrics, regime
from . import walkforward as wf

COST = metrics.TAKER_COST_BPS          # 14, the published taker line
PRIMARY = "L02"
CONFIRM_FOLDS = ("F2", "F3")
OUT_DIR = os.environ.get("M3_LONGHEAD_DIR", "output/longhead")
NS_DAY = 86_400 * 1_000_000_000
MIN_PAIRS_PER_SEED = 9                  # §9.9 harness check 4
TOL = 1e-9
SETTLEMENTS = {240: 1, 1440: 3}         # funding settlements a hold can cross (bound, not a model)

# The arms — the list is the registration (§9.9). Every field the incumbent fixes (the ladder,
# the serial rule, both sides, the model's side) is copied from the incumbent's own spec, so
# the only things that differ are the head, the cut and the hold.
_BASE_FIELDS = ("regime_col", "regime_quantile", "regime_min", "size_by_regime",
                "max_concurrent", "sides", "side_from")
ARM_FIELDS = {
    "L02": dict(coverage=0.02, signal_horizon=1440, hold_horizon=1440),
    "L05": dict(coverage=0.05, signal_horizon=1440, hold_horizon=1440),
    "H24": dict(coverage=0.02, signal_horizon=240, hold_horizon=1440),
}


def arm_specs(inc: dict) -> dict[str, backtest.PolicySpec]:
    base = {k: inc[k] for k in _BASE_FIELDS if k in inc}
    specs = {"INC": backtest.PolicySpec(label="INC", **inc)}
    for name, f in ARM_FIELDS.items():
        specs[name] = backtest.PolicySpec(label=name, **f, **base)
    return specs


# --- the dumps ---------------------------------------------------------------------------

def clean(d: dumps.Dump) -> tuple[dumps.Dump, dict[int, int]]:
    """§9.9 check 2: rows with a NaN forward return are counted per horizon and dropped
    BEFORE any cut is derived, so the 1440 arm's coverage is a share of bars it can book."""
    nan = d.df["fwd_ret"].isna().to_numpy()
    counts = {int(h): int(n) for h, n in d.df.loc[nan, "horizon"].value_counts().items()}
    if not nan.any():
        return d, counts
    return dumps.Dump(seed=d.seed, run_id=d.run_id,
                      df=d.df.loc[~nan].reset_index(drop=True)), counts


def load_explore() -> list[dumps.Dump]:
    return bookentry.load_dumps()


def load_confirm() -> list[dumps.Dump]:
    runs = {k: v for k, v in dumps.WALKFORWARD_X8_RUNS.items() if k[:2] in CONFIRM_FOLDS and v}
    return [dumps.load(r, seed=k) for k, r in runs.items()]


def fold_of(seed: str) -> str:
    """'F2s1' -> 'F2'; the served family's 's1' -> 'served'."""
    return seed[:2] if seed[:1] == "F" and len(seed) >= 4 else "served"


# --- the statistic -------------------------------------------------------------------------

def calendar(ds: list[dumps.Dump]) -> pd.DatetimeIndex:
    """Every calendar day of the window, from the 240 rows' first bar to their last."""
    lo = min(int(d.at(240)["ts"].min()) for d in ds)
    hi = max(int(d.at(240)["ts"].max()) for d in ds)
    lo_d = pd.Timestamp(lo, unit="ns", tz="UTC").floor("D")
    hi_d = pd.Timestamp(hi, unit="ns", tz="UTC").floor("D")
    return pd.date_range(lo_d, hi_d, freq="D", tz="UTC")


def net_bps(t: pd.DataFrame) -> np.ndarray:
    """Net per trade in bps of the size unit: signed return × 1e4 − cost × size."""
    return t["signed_ret"].to_numpy(np.float64) * metrics.BPS - COST * t["size"].to_numpy(np.float64)


def daily_net(t: pd.DataFrame, days: pd.DatetimeIndex, n_seeds: int) -> pd.Series:
    """N(d): the arm's net P&L on each calendar day d, by ENTRY day, summed over the seeds
    given and divided by their number — zero on a day with no entry."""
    if t.empty:
        return pd.Series(0.0, index=days)
    day = pd.to_datetime(t["entry_ts"], unit="ns", utc=True).dt.floor("D")
    s = pd.Series(net_bps(t), index=t.index).groupby(day.to_numpy()).sum()
    return s.reindex(days, fill_value=0.0) / float(n_seeds)


def diff_stats(D: np.ndarray, z: float = 1.96) -> dict:
    """Mean of the daily difference with the plain day-cluster SE and, beside it, a
    Newey–West lag-1 SE (a 24-hour trade's return overlaps the next day's)."""
    D = np.asarray(D, np.float64)
    G = D.size
    if G < 2:
        return {"mean": float(D.mean()) if G else float("nan"), "se": float("nan"),
                "lo95": float("nan"), "hi95": float("nan"), "se_nw": float("nan"),
                "lo95_nw": float("nan"), "hi95_nw": float("nan"), "days": int(G)}
    m = float(D.mean())
    e = D - m
    g0 = float((e * e).mean())
    g1 = float((e[1:] * e[:-1]).mean()) if G > 1 else 0.0
    se = float(np.sqrt(g0 / (G - 1.0)))
    var_nw = max(g0 + 2.0 * g1, 0.0) / G
    se_nw = float(np.sqrt(var_nw))
    return {"mean": m, "se": se, "lo95": m - z * se, "hi95": m + z * se,
            "se_nw": se_nw, "lo95_nw": m - z * se_nw, "hi95_nw": m + z * se_nw, "days": int(G)}


# --- descriptive lines -------------------------------------------------------------------

def dir_acc(t: pd.DataFrame) -> tuple[float, int]:
    r = t["fwd_ret"].to_numpy(np.float64)
    s = t["side"].to_numpy(np.float64)
    moved = r != 0.0
    n = int(moved.sum())
    return (float((s[moved] * r[moved] > 0).mean()) if n else float("nan")), n


def occupancy(t: pd.DataFrame, days: int, n_pairs: int, n_seeds: int) -> float:
    if t.empty or days <= 0:
        return 0.0
    held = float((t["exit_ts"] - t["entry_ts"]).sum()) / NS_DAY
    return held / (days * n_pairs * n_seeds)


def n_selected(d: dumps.Dump, spec: backtest.PolicySpec, thr: float) -> int:
    conf = d.at(spec.signal_horizon)["conf"].to_numpy(np.float64)
    return int((conf >= thr).sum())


FUNDING_FILES = ("output/book_era2/funding.parquet", "output/m3_0b/funding.parquet")


def funding_bound(ds: list[dumps.Dump]) -> dict[str, float] | str:
    """Mean |funding rate| per pair over the window, in bps per settlement — a bound on what
    `fwd_ret` leaves out, multiplied by the settlements a hold crosses. The dump carries no
    funding; the exported slices (B0 / M3-0b: symbol, ts, last_funding_rate) do."""
    paths = [f for f in FUNDING_FILES if os.path.exists(f)]
    if not paths:
        return "not computed (no exported funding slice on disk)"
    f = pd.concat([pd.read_parquet(x, columns=["symbol", "ts", "last_funding_rate"]) for x in paths],
                  ignore_index=True)
    lo = min(int(d.at(240)["ts"].min()) for d in ds)
    hi = max(int(d.at(240)["ts"].max()) for d in ds)
    ts = pd.to_datetime(f["ts"], utc=True).astype("int64").to_numpy()
    win = f.loc[(ts >= lo) & (ts <= hi)]
    path = " + ".join(paths)
    if win.empty:
        return f"not computed (no funding rows inside the window in {path})"
    # one row per settlement, not per poll: the rate is constant between settlements
    rate = win.drop_duplicates(["symbol", "last_funding_rate"])
    out = rate.groupby("symbol")["last_funding_rate"].apply(lambda s: float(np.abs(s).mean())) * metrics.BPS
    print(f"funding slice: {path}, {len(win):,} rows in the window, {len(rate):,} distinct settlements")
    return {str(p): float(v) for p, v in out.items()}


# --- the run ---------------------------------------------------------------------------------

def run_arms(ds: list[dumps.Dump], specs: dict[str, backtest.PolicySpec]) -> dict[str, backtest.Result]:
    regimes = {d.seed: regime.build(d.df) for d in ds} if any(s.regime_col for s in specs.values()) else None
    return {name: backtest.run(ds, spec, regimes=regimes) for name, spec in specs.items()}


def check_incumbent(raw: list[dumps.Dump], cleaned: list[dumps.Dump], spec: backtest.PolicySpec) -> tuple[bool, str]:
    """§9.9 check 1: the incumbent scored on the cleaned dumps equals the incumbent scored on
    the raw dumps — the ledger the wave-2 studies read — to 1e-9 per seed."""
    regimes_raw = {d.seed: regime.build(d.df) for d in raw} if spec.regime_col else None
    regimes_cl = {d.seed: regime.build(d.df) for d in cleaned} if spec.regime_col else None
    a = backtest.run(raw, spec, regimes=regimes_raw).trades
    b = backtest.run(cleaned, spec, regimes=regimes_cl).trades
    ok, lines = True, []
    for seed in sorted(set(a["seed"]) | set(b["seed"])):
        x, y = a[a["seed"] == seed], b[b["seed"] == seed]
        same = (len(x) == len(y)
                and abs(float(x["size"].sum()) - float(y["size"].sum())) <= TOL
                and abs(float(x["signed_ret"].sum()) - float(y["signed_ret"].sum())) <= TOL
                and not x["signed_ret"].isna().any())
        ok &= bool(same)
        lines.append(f"{seed}: n {len(x)} / {len(y)}, Σsize {float(x['size'].sum()):.6f} / "
                     f"{float(y['size'].sum()):.6f}, Σsigned {float(x['signed_ret'].sum()):.9f} / "
                     f"{float(y['signed_ret'].sum()):.9f} -> {'ok' if same else 'MISMATCH'}")
    return ok, "\n".join(lines)


def daily_table(results: dict[str, backtest.Result], ds: list[dumps.Dump]) -> dict:
    """Per fold (one fold = 'served' on the explore stage): the calendar, each arm's pooled
    daily series, each seed's daily series, and the D series against INC."""
    folds: dict[str, list[dumps.Dump]] = {}
    for d in ds:
        folds.setdefault(fold_of(d.seed), []).append(d)
    out = {"days": {}, "pooled": {}, "per_seed": {}}
    for fold, fds in folds.items():
        days = calendar(fds)
        seeds = [d.seed for d in fds]
        out["days"][fold] = days
        for name, r in results.items():
            t = r.trades[r.trades["seed"].isin(seeds)] if len(r.trades) else r.trades
            out["pooled"].setdefault(name, {})[fold] = daily_net(t, days, len(seeds))
            for s in seeds:
                ts_ = t[t["seed"] == s] if len(t) else t
                out["per_seed"].setdefault(name, {})[s] = daily_net(ts_, days, 1)
    return out


def _concat(series_by_fold: dict[str, pd.Series]) -> np.ndarray:
    return np.concatenate([s.to_numpy(np.float64) for _, s in sorted(series_by_fold.items())])


def confirm_days() -> int:
    n = 0
    for f in CONFIRM_FOLDS:
        lo, hi = dumps.WALKFORWARD_X8_SPLITS[f]
        n += int((pd.Timestamp(hi, tz="UTC").floor("D") - pd.Timestamp(lo, tz="UTC").floor("D")).days) + 1
    return n


def report(spec_fields: dict, stage: str, exploration_recorded: bool = False) -> int:
    if stage not in ("explore", "confirm"):
        raise SystemExit("--stage explore|confirm")
    if stage == "confirm" and not exploration_recorded:
        raise SystemExit("--stage confirm needs --exploration-recorded: §9.9's exploration "
                         "table, MDE forecast and PASSED verdict must be in the record first")
    os.makedirs(OUT_DIR, exist_ok=True)
    raw = load_explore() if stage == "explore" else load_confirm()
    print(f"=== X18 longhead — stage {stage} — {len(raw)} dumps: "
          + ", ".join(f"{d.seed}={d.run_id}" for d in raw))

    # check 2: NaN rows
    cleaned, counts = [], {}
    for d in raw:
        c, k = clean(d)
        cleaned.append(c)
        counts[d.seed] = k
    print("check 2 — NaN fwd_ret rows dropped before the cut, per seed and horizon: "
          + "; ".join(f"{s}: {k or 'none'}" for s, k in counts.items()))

    specs = arm_specs(spec_fields)
    print("arms: " + " | ".join(f"{n}: head {s.signal_horizon} cov {s.coverage} hold "
                               f"{s.hold_horizon or s.signal_horizon}" for n, s in specs.items()))

    # check 1: the incumbent is unchanged by the cleaning
    ok1, lines1 = check_incumbent(raw, cleaned, specs["INC"])
    print(f"check 1 — INC on cleaned dumps reproduces INC on raw dumps: {'PASS' if ok1 else 'FAIL'}\n{lines1}")

    results = run_arms(cleaned, specs)
    n_pairs = max(len(d.df["pair"].unique()) for d in cleaned)
    seeds = [d.seed for d in cleaned]

    # check 3 and 4, and the per-arm descriptive table
    rows = []
    ok3 = ok4 = True
    for name, r in results.items():
        t = r.trades
        for d in cleaned:
            thr = r.thresholds[d.seed]
            sel = n_selected(d, specs[name], thr)
            bars = len(d.at(specs[name].signal_horizon))
            share = sel / bars
            tt = t[t["seed"] == d.seed]
            blocked = 1.0 - len(tt) / sel if sel else float("nan")
            pairs_hit = int(tt["pair"].nunique()) if len(tt) else 0
            ok3 &= share >= specs[name].coverage * 0.999
            ok4 &= pairs_hit >= MIN_PAIRS_PER_SEED
            rows.append({"arm": name, "seed": d.seed, "cut": round(thr, 5), "selected": sel,
                         "share": round(share, 4), "trades": len(tt), "blocked": round(blocked, 3),
                         "pairs": pairs_hit})
    print("check 3 — bars at or above the cut vs coverage (tie-inclusive, ≥ cov×bars): "
          f"{'PASS' if ok3 else 'FAIL'}; check 4 — ≥ {MIN_PAIRS_PER_SEED} pairs per arm-seed: "
          f"{'PASS' if ok4 else 'FAIL'}")
    print(pd.DataFrame(rows).to_string(index=False))

    # the statistic
    tab = daily_table(results, cleaned)
    G = sum(len(v) for v in tab["days"].values())
    inc_pooled = _concat(tab["pooled"]["INC"])
    print(f"\n=== daily net P&L, bps of the size unit, {G} calendar days "
          f"({', '.join(f'{f}: {len(v)}' for f, v in tab['days'].items())}); cost taker {COST} ===")
    stat_rows, verdict = [], {}
    for name in ("L02", "L05", "H24"):
        D = _concat(tab["pooled"][name]) - inc_pooled
        st = diff_stats(D)
        per_seed = {}
        for s in seeds:
            Ds = tab["per_seed"][name][s].to_numpy(np.float64) - tab["per_seed"]["INC"][s].to_numpy(np.float64)
            per_seed[s] = float(Ds.mean())
        med = float(np.median(list(per_seed.values())))
        n_pos = sum(v > 0 for v in per_seed.values())
        stat_rows.append({"arm": name, "D mean/day": round(st["mean"], 3), "se": round(st["se"], 3),
                          "lo95": round(st["lo95"], 3), "hi95": round(st["hi95"], 3),
                          "se_nw1": round(st["se_nw"], 3), "lo95_nw1": round(st["lo95_nw"], 3),
                          "median seed": round(med, 3), "seeds>0": f"{n_pos}/{len(per_seed)}",
                          **{f"D {s}": round(v, 3) for s, v in per_seed.items()}})
        verdict[name] = {"stat": st, "per_seed": per_seed, "median": med}
        pd.DataFrame({"day": np.concatenate([v.to_numpy() for _, v in sorted(tab["days"].items())]),
                      "D": D}).to_csv(os.path.join(OUT_DIR, f"{stage}_D_{name}.csv"), index=False)
    print(pd.DataFrame(stat_rows).to_string(index=False))
    arm_rows = []
    for name, r in results.items():
        t = r.trades
        N = _concat(tab["pooled"][name])
        da, nd = dir_acc(t)
        up, dn = t[t["side"] > 0], t[t["side"] < 0]
        book = t[t["has_book"] > 0] if "has_book" in t else t.iloc[0:0]
        pre = t[t["has_book"] <= 0] if "has_book" in t else t.iloc[0:0]
        led = bookentry.ledger(t)
        nr = wf.notional_ratio_bps(led, COST)
        pc = bookentry.contrast(t, results["INC"].trades) if name != "INC" else {"diff_bps": 0.0, "lo95_bps": 0.0, "hi95_bps": 0.0}
        arm_rows.append({"arm": name, "trades": len(t), "per day": round(len(t) / G / len(seeds), 3),
                         "net/day (pooled)": round(float(N.mean()), 3),
                         "per-notional net": round(nr["mean_bps"], 2),
                         "per-notional vs INC": f"{pc['diff_bps']:+.2f} [{pc['lo95_bps']:+.2f}, {pc['hi95_bps']:+.2f}]",
                         "dir_acc": round(da, 4), "n_dir": nd,
                         "up": f"{dir_acc(up)[0]:.3f} ({len(up)})", "down": f"{dir_acc(dn)[0]:.3f} ({len(dn)})",
                         "book": f"{dir_acc(book)[0]:.3f} ({len(book)})", "pre_book": f"{dir_acc(pre)[0]:.3f} ({len(pre)})",
                         "occupancy": round(occupancy(t, G, n_pairs, len(seeds)), 4)})
        t.to_csv(os.path.join(OUT_DIR, f"{stage}_trades_{name}.csv"), index=False)
    print("\n=== per arm, descriptive (per-notional lines are §9.6's statistic, exit-day clusters) ===")
    print(pd.DataFrame(arm_rows).to_string(index=False))
    print("\nper-pair trade counts (pooled over seeds):")
    print(pd.DataFrame({n: r.trades["pair"].value_counts() for n, r in results.items()}).fillna(0).astype(int).to_string())

    fb = funding_bound(cleaned)
    if isinstance(fb, str):
        print(f"\nfunding bound: {fb}")
    else:
        m = float(np.mean(list(fb.values())))
        print(f"\nfunding bound — mean |rate| per settlement, bps: " + ", ".join(f"{p} {v:.2f}" for p, v in sorted(fb.items()))
              + f"; mean {m:.2f} × settlements crossed: hold 240 ≤ {m * SETTLEMENTS[240]:.2f}, hold 1440 ≤ {m * SETTLEMENTS[1440]:.2f} bps per trade")

    # the gate, mechanical
    v = verdict[PRIMARY]
    if stage == "explore":
        passed = v["stat"]["mean"] > 0 and v["median"] > 0
        mde = v["stat"]["se"] * np.sqrt(G / confirm_days()) * 1.96 if np.isfinite(v["stat"]["se"]) else float("nan")
        print(f"\n=== §9.9 exploration gate on {PRIMARY}: pooled D {v['stat']['mean']:+.3f} bps/day "
              f"[{v['stat']['lo95']:+.3f}, {v['stat']['hi95']:+.3f}], median seed {v['median']:+.3f} -> "
              f"{'PASSED' if passed else 'NOT PASSED'} ===")
        print(f"forecast confirmation MDE on F2 + F3 ({confirm_days()} days): {mde:.3f} bps/day")
    else:
        confirmed = v["stat"]["lo95"] > 0 and v["median"] > 0
        print(f"\n=== §9.9 confirmation on {PRIMARY}, F2 + F3: pooled D {v['stat']['mean']:+.3f} bps/day "
              f"[{v['stat']['lo95']:+.3f}, {v['stat']['hi95']:+.3f}], median seed-fold {v['median']:+.3f} -> "
              f"{'CONFIRMED' if confirmed else 'NOT CONFIRMED'} ===")
    print(f"harness checks: 1 {'PASS' if ok1 else 'FAIL'}, 3 {'PASS' if ok3 else 'FAIL'}, 4 {'PASS' if ok4 else 'FAIL'}"
          + ("" if (ok1 and ok3 and ok4) else " — a failed check voids the read above"))
    return 0 if (ok1 and ok3 and ok4) else 2
