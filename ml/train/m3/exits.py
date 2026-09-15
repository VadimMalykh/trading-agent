"""WALKFORWARD_PROTOCOL §9.7 — X4: signal-conditioned exits on the folds.

The incumbent closes every trade on a 240-minute timer. This harness keeps the incumbent's
entries (cut, regime filter, ladder size, serial per pair) and changes ONE thing — when the
trade closes — in two pre-registered ways:

  flip(c)     at t+60 / t+120 / t+180: the 240m head takes the OPPOSITE side with conf >= cut(c)
              -> exit at that bar (return = compounded 60m legs).
  persist(c)  at t+240 (and t+480): the 240m head takes the SAME side with conf >= cut(c)
              -> hold another 240 minutes with no crossing (return = compounded 240m legs);
              at most two extensions.

The price path is the dumps' own: four 60m forward returns compound to the 240m return
(regime.check_compounding, 3.2e-7), so exits on the hourly grid need no side-table. Each trade
pays exactly one round trip whatever its exit — the gate is net of crossings by construction.

Everything here is fixed by §9.7 before any number was read. Changing a mark, a cut, the cap
or adding a combination arm is a new registration, not a re-run.

Memory discipline: one fold dump at a time.
"""
from __future__ import annotations

import gc

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime, universe
from . import walkforward as wf

EXPLORE_FOLDS = ("F0", "F1")
CONFIRM_FOLDS = ("F2", "F3")
COST = metrics.TAKER_COST_BPS
NS = 1_000_000_000
MIN_NS = 60 * NS
HOLD_MIN = 240
MARKS_MIN = (60, 120, 180)                      # §9.7: flip checks, hourly
MAX_EXT = 2                                      # §9.7: 12-hour cap
CONFIGS = {                                      # the list IS the registration
    "flip02": ("flip", 0.02), "flip05": ("flip", 0.05),
    "persist02": ("persist", 0.02), "persist05": ("persist", 0.05),
}
FALLBACK_MAX = 0.10
COMPOUND_TOL = 1e-5
LADDER_QS = [0.2, 0.4, 0.6, 0.8]


# --------------------------------------------------------------------------------------
# One fold-seed: the incumbent's entry candidates, and the per-pair lookup of later bars
# --------------------------------------------------------------------------------------

def entry_candidates(d: dumps.Dump, sized_fields: dict, reg: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """The incumbent's candidate bars, built exactly as backtest.run builds them: coverage
    cut over the seed's own 240m confidences, regime filter (NaN dropped), ladder size."""
    spec = backtest.PolicySpec(label="incumbent", **sized_fields)
    sig = d.at(spec.signal_horizon)[["pair", "ts", "conf", "side"]]
    hold = d.at(spec.hold_horizon or spec.signal_horizon)[["pair", "ts", "fwd_ret"]]
    bars = sig.merge(hold, on=["pair", "ts"], how="inner")
    conf = bars["conf"].to_numpy(np.float64)
    cuts = {c: backtest.coverage_threshold(conf, c) for c in (0.02, 0.05)}
    thr = backtest.coverage_threshold(conf, spec.coverage)
    sel = bars[conf >= thr].copy()
    r = reg[["pair", "ts", spec.regime_col]]
    sel = sel.merge(r, on=["pair", "ts"], how="left")
    sel = sel[sel[spec.regime_col].notna()].copy()
    sel["regime"] = sel[spec.regime_col]
    edges = r[spec.regime_col].quantile(LADDER_QS).to_numpy()
    q = np.searchsorted(edges, sel[spec.regime_col].to_numpy(), side="right")
    sel["size"] = (q.astype(np.float64) + 1.0) / 3.0
    sel = sel.sort_values("ts", kind="mergesort").reset_index(drop=True)
    return sel, cuts


class PairPath:
    """Sorted per-pair arrays of the 240m head (conf, side, fwd_ret) and the 60m head
    (fwd_ret), looked up by exact bar timestamp."""

    def __init__(self, h240: pd.DataFrame, h60: pd.DataFrame):
        h240 = h240.sort_values("ts")
        h60 = h60.sort_values("ts")
        self.t240 = h240["ts"].to_numpy(np.int64)
        self.conf = h240["conf"].to_numpy(np.float64)
        self.side = h240["side"].to_numpy(np.float64)
        self.r240 = h240["fwd_ret"].to_numpy(np.float64)
        self.t60 = h60["ts"].to_numpy(np.int64)
        self.r60 = h60["fwd_ret"].to_numpy(np.float64)

    def _idx(self, t: np.ndarray, ts: int) -> int:
        i = int(np.searchsorted(t, ts))
        return i if i < t.size and t[i] == ts else -1

    def sig(self, ts: int) -> tuple[float, float, float] | None:
        i = self._idx(self.t240, ts)
        return None if i < 0 else (self.side[i], self.conf[i], self.r240[i])

    def leg60(self, ts: int) -> float:
        i = self._idx(self.t60, ts)
        return float("nan") if i < 0 else float(self.r60[i])


def paths_for(d: dumps.Dump) -> dict[str, PairPath]:
    h240 = d.at(240)[["pair", "ts", "conf", "side", "fwd_ret"]]
    h60 = d.at(60)[["pair", "ts", "fwd_ret"]]
    return {p: PairPath(h240[h240["pair"] == p], h60[h60["pair"] == p])
            for p in h240["pair"].unique()}


# --------------------------------------------------------------------------------------
# The simulator — backtest._simulate_seed's loop with a rule-dependent exit
# --------------------------------------------------------------------------------------

def simulate(sel: pd.DataFrame, paths: dict[str, PairPath], mode: str, cut: float | None,
             seed: str) -> pd.DataFrame:
    """Serial per pair, no cap (the incumbent's spec), entries in time order; the exit is
    the timer unless `mode` says otherwise. `mode="null"` must reproduce backtest.run."""
    ts = sel["ts"].to_numpy(np.int64)
    pair = sel["pair"].astype(str).to_numpy()
    side = sel["side"].to_numpy(np.float64)
    r240 = sel["fwd_ret"].to_numpy(np.float64)
    size = sel["size"].to_numpy(np.float64)
    regime_v = sel["regime"].to_numpy(np.float64)
    conf_v = sel["conf"].to_numpy(np.float64)
    hold_ns = HOLD_MIN * MIN_NS
    open_until: dict[str, int] = {}
    rows = []
    for i in range(len(sel)):
        t, p = int(ts[i]), pair[i]
        if p in open_until and open_until[p] > t:          # invariant 2: serial per pair
            continue
        s = side[i]
        ret, exit_ts, reason, fallback = r240[i], t + hold_ns, "timer", False
        path = paths.get(p)
        if mode == "flip" and path is not None:
            legs: list[float] = []
            for k, m in enumerate(MARKS_MIN, start=1):
                legs.append(path.leg60(t + (m - 60) * MIN_NS))
                at = path.sig(t + m * MIN_NS)
                if at is None:
                    continue
                s_b, c_b, _ = at
                if s_b == -s and c_b >= cut:
                    if any(np.isnan(x) for x in legs):
                        fallback = True
                    else:
                        ret = float(np.prod([1.0 + x for x in legs]) - 1.0)
                        exit_ts, reason = t + m * MIN_NS, f"flip{k}"
                    break
        elif mode == "persist" and path is not None:
            total, e, n = 1.0 + ret, t + hold_ns, 0
            while n < MAX_EXT:
                at = path.sig(e)
                if at is None:
                    break
                s_e, c_e, r_e = at
                if not (s_e == s and c_e >= cut):
                    break
                if np.isnan(r_e):
                    fallback = True
                    break
                total *= 1.0 + r_e
                e += hold_ns
                n += 1
            if n:
                ret, exit_ts, reason = total - 1.0, e, f"ext{n}"
        rows.append((p, t, exit_ts, s, ret, size[i], s * ret * size[i], regime_v[i],
                     conf_v[i], reason, (exit_ts - t) // MIN_NS, fallback))
        open_until[p] = exit_ts
    out = pd.DataFrame(rows, columns=["pair", "entry_ts", "exit_ts", "side", "fwd_ret", "size",
                                      "signed_ret", "regime", "conf", "reason", "hold_min",
                                      "fallback"])
    out["seed"] = seed
    return out


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------

def check_null(null: pd.DataFrame, inc: pd.DataFrame) -> tuple[bool, str]:
    if len(null) != len(inc):
        return False, f"trade count {len(null)} vs {len(inc)}"
    a = null.sort_values(["pair", "entry_ts"]).reset_index(drop=True)
    b = inc.sort_values(["pair", "entry_ts"]).reset_index(drop=True)
    if not ((a["pair"].to_numpy() == b["pair"].to_numpy()).all()
            and (a["entry_ts"].to_numpy() == b["entry_ts"].to_numpy()).all()
            and (a["exit_ts"].to_numpy() == b["exit_ts"].to_numpy()).all()):
        return False, "entry/exit sets differ"
    ds = float(np.abs(a["size"].to_numpy() - b["size"].to_numpy()).max())
    dp = float(abs(a["signed_ret"].sum() - b["signed_ret"].sum()))
    return (ds < 1e-9 and dp < 1e-9), f"max |Δsize| {ds:.1e}, |ΔΣ signed_ret| {dp:.1e}"


def check_compounding(d: dumps.Dump) -> float:
    return max(regime.check_compounding(d.df, pair=p) for p in d.df["pair"].unique())


# --------------------------------------------------------------------------------------
# The statistic — net P&L per seed-day, arm − incumbent
# --------------------------------------------------------------------------------------

def daily_pnl(t: pd.DataFrame, cost: float = COST) -> pd.Series:
    """Σ over the UTC exit day of (signed_ret × 1e4 − cost × size): P&L in bps of one size
    unit of notional."""
    if t.empty:
        return pd.Series(dtype=np.float64)
    day = pd.to_datetime(t["exit_ts"], unit="ns", utc=True).dt.floor("D")
    pnl = t["signed_ret"].to_numpy(np.float64) * metrics.BPS - cost * t["size"].to_numpy(np.float64)
    return pd.Series(pnl).groupby(day.to_numpy()).sum()


def daily_diff(arm: pd.DataFrame, inc: pd.DataFrame, n_seeds: int, z: float = 1.96) -> dict:
    """Mean over the union of exit days of (arm − incumbent) daily P&L, per seed-day; SE over
    days as the independent units; the total over the span = mean × days."""
    a, b = daily_pnl(arm), daily_pnl(inc)
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).fillna(0.0)
    diff = (j["a"] - j["b"]).to_numpy(np.float64) / n_seeds
    n = diff.size
    if n < 2:
        return {"mean": float(diff.mean()) if n else 0.0, "se": float("nan"), "lo95": float("nan"),
                "hi95": float("nan"), "days": n, "total": float(diff.sum())}
    mean, se = float(diff.mean()), float(diff.std(ddof=1) / np.sqrt(n))
    return {"mean": mean, "se": se, "lo95": mean - z * se, "hi95": mean + z * se, "days": n,
            "total": float(diff.sum())}


def daily_level(t: pd.DataFrame, n_seeds: int) -> float:
    p = daily_pnl(t)
    return float(p.sum() / max(p.size, 1) / n_seeds)


def _drawdown(t: pd.DataFrame) -> float:
    if t.empty:
        return 0.0
    s = t.sort_values("exit_ts")
    net = s["signed_ret"].to_numpy(np.float64) - COST / metrics.BPS * s["size"].to_numpy(np.float64)
    return metrics.max_drawdown(np.cumsum(net))


def _seed_number(seed_label: str) -> str:
    return seed_label[-2:]


def _fold_runs(fold: str) -> list[tuple[str, str]]:
    got = [(seed, rid) for seed, rid in dumps.recorded_runs().items()
           if dumps.fold_of(seed) == fold]
    if len(got) != 3:
        raise SystemExit(f"§9.7 needs every seed of {fold}; have {[s for s, _ in got]}")
    return got


def _span_days(fold: str) -> float:
    lo, hi = dumps.WALKFORWARD_SPLITS[fold]
    return (pd.Timestamp(hi) - pd.Timestamp(lo)).total_seconds() / 86400.0


# --------------------------------------------------------------------------------------
# Scoring one fold
# --------------------------------------------------------------------------------------

def score_fold(fold: str, sized_fields: dict, labels: list[str]) -> dict:
    sized = backtest.PolicySpec(label="incumbent SIZED", **sized_fields)
    arms: dict[str, list[pd.DataFrame]] = {"incumbent": [], "null": [], **{l: [] for l in labels}}
    checks = []
    for seed, rid in _fold_runs(fold):
        d = dumps.load(rid, seed=seed)                  # one dump at a time — memory
        comp = check_compounding(d)
        reg = regime.build(d.df)
        inc = backtest.run([d], sized, {seed: reg}).trades
        sel, cuts = entry_candidates(d, sized_fields, reg)
        paths = paths_for(d)
        null = simulate(sel, paths, "null", None, seed)
        ok, msg = check_null(null, inc)
        checks.append((seed, comp, ok, msg, cuts))
        arms["incumbent"].append(inc)
        arms["null"].append(null)
        for lab in labels:
            mode, c = CONFIGS[lab]
            arms[lab].append(simulate(sel, paths, mode, cuts[c], seed))
        del d, reg, paths, sel
        gc.collect()
    out = {k: pd.concat(v, ignore_index=True) for k, v in arms.items()}
    out["checks"] = checks
    return out


def _arm_line(name: str, t: pd.DataFrame, inc: pd.DataFrame | None, n_seeds: int) -> str:
    lvl = daily_level(t, n_seeds)
    per_trade = metrics.clustered_mean_bps(t, COST)["mean_bps"] if len(t) else float("nan")
    mix = ""
    if "reason" in t:
        vc = t["reason"].value_counts(normalize=True).sort_index()
        mix = "  exits " + " ".join(f"{k}:{v:.1%}" for k, v in vc.items())
    hold = float(t["hold_min"].mean()) if "hold_min" in t else 240.0
    fb = int(t["fallback"].sum()) if "fallback" in t else 0
    s = (f"  {name:<11} n={len(t):>5,}  hold {hold:5.0f}m  size {t['size'].mean():.3f}  "
         f"net/seed-day {lvl:+7.2f}  per trade @14 {per_trade:+7.2f}  maxDD {_drawdown(t):+.4f}"
         f"  fallback {fb}{mix}")
    if inc is not None and name != "incumbent":
        dd = daily_diff(t, inc, n_seeds)
        pt = universe.paired_diff_bps(t, inc, COST)
        s += (f"\n  {'':<11} vs incumbent: {dd['mean']:+.2f} [{dd['lo95']:+.2f}, {dd['hi95']:+.2f}] "
              f"per seed-day over {dd['days']} days (total {dd['total']:+.0f} per seed); "
              f"per trade (info) {pt['diff_bps']:+.2f} [{pt['lo95_bps']:+.2f}, {pt['hi95_bps']:+.2f}]")
    return s


# --------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------

def report(sized_fields: dict, stage: str, exploration_recorded: bool = False,
           config: str | None = None) -> int:
    wf.require_walkforward_era()
    print("=" * 96)
    print(f"§9.7 — X4: SIGNAL-CONDITIONED EXITS ON THE FOLDS — stage {stage.upper()}")
    print("=" * 96)
    print(wf.registry_state())
    if dumps.missing_runs():
        print(f"\n🔴 refusing: {dumps.missing_runs()} not recorded.")
        return 2
    if stage == "explore":
        folds, labels = EXPLORE_FOLDS, list(CONFIGS)
        print("\nF0 and F1 only (§9.0 rule 2). Nothing is fitted; all four configurations are scored")
        print("and ONE is chosen by §9.7's rule. Decides nothing about promotion. F2/F3 are not loaded.")
    elif stage == "confirm":
        if not exploration_recorded:
            print("\n🔴 refusing: --stage confirm reads F2+F3. Pass --exploration-recorded only after")
            print("   the exploration table, the chosen label and the MDE forecast are written into §9.7.")
            return 2
        if config not in CONFIGS:
            print(f"\n🔴 refusing: --config must be one of {list(CONFIGS)}, transcribed from §9.7; got {config!r}.")
            return 2
        folds, labels = CONFIRM_FOLDS, [config]
        print(f"\n🔴 F2 + F3 are being read for §9.7. This happens once. Configuration: {config}")
    else:
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")
    print(f"\ntaker {COST:.0f} bps per round trip on every trade, whatever its exit")

    res = {}
    for fold in folds:
        print("\n" + "=" * 96)
        print(f"{fold} — the arms (same entry rule; only the exit differs)")
        print("=" * 96)
        res[fold] = score_fold(fold, sized_fields, labels)
        for seed, comp, ok, msg, cuts in res[fold]["checks"]:
            print(f"  {seed}: compounding max|Δ| {comp:.1e} ({'ok' if comp <= COMPOUND_TOL else 'FAIL'});"
                  f" null == incumbent: {'PASS' if ok else 'FAIL'} — {msg}; cuts 0.02={cuts[0.02]:.4f} 0.05={cuts[0.05]:.4f}")
            if comp > COMPOUND_TOL or not ok:
                print("  🔴 harness check failed; nothing below may be read.")
                return 3
        inc = res[fold]["incumbent"]
        print(_arm_line("incumbent", inc, None, 3))
        for lab in labels:
            t = res[fold][lab]
            share = float(t["fallback"].mean()) if len(t) else 0.0
            if share > FALLBACK_MAX:
                print(f"  🔴 {lab}: fallback share {share:.1%} exceeds §9.7's {FALLBACK_MAX:.0%}; stop and revisit.")
                return 3
            print(_arm_line(lab, t, inc, 3))

    print("\n" + "=" * 96)
    print(f"THE CONTRAST — arm − incumbent, net bps per seed-day ({'+'.join(folds)} pooled)")
    print("=" * 96)
    inc_all = pd.concat([res[f]["incumbent"] for f in folds], ignore_index=True)
    rows, pooled = [], {}
    for lab in labels:
        arm_all = pd.concat([res[f][lab] for f in folds], ignore_index=True)
        dd = daily_diff(arm_all, inc_all, 3)
        pooled[lab] = (dd, arm_all)
        per_seed = {}
        for s in ("s1", "s2", "s3"):
            a = arm_all[arm_all["seed"].map(_seed_number) == s]
            b = inc_all[inc_all["seed"].map(_seed_number) == s]
            per_seed[s] = daily_diff(a, b, 1)["mean"]
        pt = universe.paired_diff_bps(arm_all, inc_all, COST)
        rows.append({"config": lab, "mean/seed-day": dd["mean"], "95% CI": f"[{dd['lo95']:+.2f}, {dd['hi95']:+.2f}]",
                     "se": dd["se"], "days": dd["days"], "total/seed": dd["total"],
                     "s1": per_seed["s1"], "s2": per_seed["s2"], "s3": per_seed["s3"],
                     "median seed": float(np.median(list(per_seed.values()))),
                     "n trades": len(arm_all), "hold": float(arm_all["hold_min"].mean()),
                     "per trade (info)": pt["diff_bps"]})
    table = pd.DataFrame(rows)
    print(table.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
    e_level = daily_level(inc_all, 3)
    print(f"\n  E, the incumbent's own mean net per seed-day on these folds: {e_level:+.2f} "
          f"(n {len(inc_all):,} trades)")

    print("\n" + "=" * 96)
    print("THE VERDICT, under §9.7 as written")
    print("=" * 96)
    if stage == "explore":
        best = table.sort_values("mean/seed-day", ascending=False).iloc[0]
        dd = pooled[best["config"]][0]
        d_here = sum(_span_days(f) for f in EXPLORE_FOLDS)
        d_conf = sum(_span_days(f) for f in CONFIRM_FOLDS)
        se_conf = dd["se"] * np.sqrt(d_here / d_conf)
        passed = best["mean/seed-day"] > 0 and best["median seed"] > 0
        print(f"  chosen by the rule (highest pooled mean/seed-day): {best['config']}  "
              f"{best['mean/seed-day']:+.2f} [{dd['lo95']:+.2f}, {dd['hi95']:+.2f}]; median seed {best['median seed']:+.2f}")
        print(f"  forecast for the confirmation shape: SE {se_conf:.2f} -> MDE (1.96σ) {1.96 * se_conf:.2f} "
              f"bps per seed-day  (span days {d_here:.0f} -> {d_conf:.0f})")
        print(f"  exploration gate: best > 0 -> {best['mean/seed-day'] > 0}; median seed-number > 0 -> {best['median seed'] > 0}")
        print(f"\n  ==> {'GATE PASSED — record this table and the label in §9.7, then run --stage confirm --exploration-recorded --config ' + best['config'] if passed else 'GATE NOT PASSED — §9.7 closes here; F2/F3 are not read'}")
    else:
        row = table.iloc[0]
        dd = pooled[row["config"]][0]
        confirmed = dd["lo95"] > 0 and row["median seed"] > 0
        print(f"  95% lower bound > 0 -> {dd['lo95'] > 0} ({dd['lo95']:+.2f}); median seed-number > 0 -> "
              f"{row['median seed'] > 0} ({row['median seed']:+.2f})")
        print(f"\n  ==> {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} (read against E above: an interval that "
              f"excludes E is a detected absence, one that contains it is 'not detectable')")
    return 0
