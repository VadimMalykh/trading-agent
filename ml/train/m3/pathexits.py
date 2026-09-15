"""WALKFORWARD_PROTOCOL §9.8 — X6: price-path exits (volatility-scaled and trailing stops).

The incumbent closes every trade on a 240-minute timer. This harness keeps the incumbent's
trades exactly — same entries, same sizes — and changes ONE thing: a stop may close a trade
EARLY, walking the 5m candle path. An exit may only shorten a trade and the pair stays occupied
until entry + 240 minutes, so every arm holds the incumbent's trades and the contrast is a
same-entries, per-notional one (as §9.6), not a per-day one (as §9.7).

  stop_v<k>    stop at k·σ4h from the entry close, no target
  trail_v<k>   stop at k·σ4h behind the best close since entry
  ..._hi       the same, only on top-regime-quintile trades (size 5/3)

σ4h = sample sd of the pair's 5m log returns over the 288 bars ending at the entry bar, × √48;
distances are applied in log space. Fill: a bar that OPENS through the stop fills at the open,
otherwise a touch of its low (long) / high (short) fills at the stop. Untouched trades keep the
incumbent's own return.

The price path is `output/wf_side/candles_5m` (scripts/gcp_m3_export.sh, 2024-10 → 2026-09),
accepted before §9.8 was written: the rebuilt 240m return equals every fold dump exactly. The
harness re-checks that on every fold-seed before scoring.

Everything here is fixed by §9.8 before any number was read. Changing k, the reference price,
the vol window, adding a target or a combination is a new registration, not a re-run.

Memory discipline: the candle grid once, one fold dump at a time.
"""
from __future__ import annotations

import gc

import numpy as np
import pandas as pd

from . import backtest, dumps, exits, metrics, regime, sidetable, universe
from . import walkforward as wf

EXPLORE_FOLDS = ("F0", "F1")
CONFIRM_FOLDS = ("F2", "F3")
EXPORT_DIR = "output/wf_side"
COST = metrics.TAKER_COST_BPS
HOLD_BARS = 48
VOL_BARS = 288
BAR_NS = 5 * 60 * 1_000_000_000
SQRT_HOLD = float(np.sqrt(HOLD_BARS))
TOP_SIZE = 5.0 / 3.0
CONFIGS = {                                      # the list IS the registration
    "stop_v15": ("stop", 1.5, False), "stop_v25": ("stop", 2.5, False),
    "trail_v15": ("trail", 1.5, False), "trail_v25": ("trail", 2.5, False),
    "trail_v15_hi": ("trail", 1.5, True),
}
BRAKE_SL, BRAKE_TP = 0.02, 0.04                 # the live `auto` brake — information only
STOP_SLIP_BPS = 5.0                             # sensitivity, never a selector
FALLBACK_MAX = 0.10
NULL_TOL = 1e-6


# --------------------------------------------------------------------------------------
# The candle grid
# --------------------------------------------------------------------------------------

class Grid:
    """Per-pair sorted arrays of the 5m path plus σ4h at every bar, and the rebuilt 240m
    forward return the acceptance check compares against the dumps."""

    def __init__(self, candles: pd.DataFrame):
        self.candles = candles
        fwd = sidetable.add_forward_returns(candles, horizons_min=(240,))
        self.fwd240 = fwd[["pair", "ts", "fwd_ret_240"]]
        self.by: dict[str, tuple[np.ndarray, ...]] = {}
        for p, g in candles.groupby("pair", sort=False):
            c = g["close"].to_numpy(np.float64)
            lr = np.empty_like(c)
            lr[0] = np.nan
            lr[1:] = np.log(c[1:] / c[:-1])
            sig = pd.Series(lr).rolling(VOL_BARS, min_periods=VOL_BARS).std(ddof=1).to_numpy()
            self.by[p] = (g["ts"].to_numpy(np.int64), g["open"].to_numpy(np.float64),
                          g["high"].to_numpy(np.float64), g["low"].to_numpy(np.float64), c,
                          sig * SQRT_HOLD)

    def span(self) -> str:
        t = pd.to_datetime(self.candles["ts"], unit="ns", utc=True)
        return (f"{len(self.candles):,} bars x {self.candles['pair'].nunique()} pairs, "
                f"{t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")


def load_grid() -> Grid:
    return Grid(sidetable.load_candles("5m", export_dir=EXPORT_DIR))


# --------------------------------------------------------------------------------------
# One arm: walk each incumbent trade's path under a rule
# --------------------------------------------------------------------------------------

def walk_arm(inc: pd.DataFrame, grid: Grid, mode: str, k: float = 0.0,
             top_only: bool = False) -> pd.DataFrame:
    """`mode` is "null" (rebuild the timer return from candles), "stop" or "trail"."""
    n = len(inc)
    ret = inc["fwd_ret"].to_numpy(np.float64).copy()
    exit_ts = inc["exit_ts"].to_numpy(np.int64).copy()
    reason = np.array(["timer"] * n, dtype=object)
    held = np.full(n, HOLD_BARS, dtype=np.int64)
    fallback = np.zeros(n, dtype=bool)
    pairs = inc["pair"].astype(str).to_numpy()
    entry = inc["entry_ts"].to_numpy(np.int64)
    side = inc["side"].to_numpy(np.float64)
    size = inc["size"].to_numpy(np.float64)
    for i in range(n):
        if top_only and abs(size[i] - TOP_SIZE) > 1e-9:
            continue                                    # not in scope: the timer, not a fallback
        g = grid.by.get(pairs[i])
        if g is None:
            fallback[i] = True
            continue
        ts, o, h, lo, c, sig = g
        kk = int(np.searchsorted(ts, entry[i]))
        if kk >= ts.size or ts[kk] != entry[i] or kk + HOLD_BARS >= ts.size:
            fallback[i] = True
            continue
        e = c[kk]
        if mode == "null":
            ret[i] = c[kk + HOLD_BARS] / e - 1.0
            continue
        v = sig[kk]
        if not np.isfinite(v):
            fallback[i] = True
            continue
        mult = float(np.exp(k * v))
        ref = e
        for j in range(kk + 1, kk + HOLD_BARS + 1):
            px = None
            if side[i] > 0:
                stop = ref / mult
                if o[j] <= stop:
                    px = o[j]
                elif lo[j] <= stop:
                    px = stop
                elif mode == "trail" and c[j] > ref:
                    ref = c[j]
            else:
                stop = ref * mult
                if o[j] >= stop:
                    px = o[j]
                elif h[j] >= stop:
                    px = stop
                elif mode == "trail" and c[j] < ref:
                    ref = c[j]
            if px is not None:
                ret[i] = px / e - 1.0
                reason[i] = "stop"
                held[i] = j - kk
                exit_ts[i] = entry[i] + (j - kk) * BAR_NS
                break
    out = inc.copy()
    out["fwd_ret"] = ret
    out["signed_ret"] = side * ret * size
    out["exit_ts"] = exit_ts
    out["reason"] = reason
    out["hold_min"] = held * 5
    out["fallback"] = fallback
    return out


def brake_arm(inc: pd.DataFrame, grid: Grid) -> pd.DataFrame:
    """The live 2% stop / 4% target, with M3-0b's own touch rule (information only)."""
    b = sidetable.barrier_exit(grid.candles, inc[["pair", "entry_ts", "side"]].copy(),
                               tp=BRAKE_TP, sl=BRAKE_SL, max_bars=HOLD_BARS, touch="intrabar")
    out = inc.copy()
    br = b["barrier_ret"].to_numpy(np.float64)
    fb = ~np.isfinite(br)
    size = inc["size"].to_numpy(np.float64)
    signed = np.where(fb, inc["signed_ret"].to_numpy(np.float64), br * size)
    out["signed_ret"] = signed
    kind = b["barrier_exit"].to_numpy(object)
    out["reason"] = np.where(fb, "timer", np.where(kind == "timeout", "timer", kind))
    bars = b["barrier_bars"].to_numpy(np.int64)
    out["hold_min"] = np.where(fb | (bars < 0), 240, bars * 5)
    out["exit_ts"] = np.where(fb | (bars < 0), inc["exit_ts"].to_numpy(np.int64),
                              b["barrier_exit_ts"].to_numpy(np.int64))
    out["fallback"] = fb
    return out


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------

def check_acceptance(d: dumps.Dump, grid: Grid) -> tuple[bool, str]:
    h = d.at(240)[["pair", "ts", "fwd_ret"]]
    m = h.merge(grid.fwd240, on=["pair", "ts"], how="left")
    miss = int(m["fwd_ret_240"].isna().sum())
    ok = m.dropna(subset=["fwd_ret_240"])
    exact = int((ok["fwd_ret"].to_numpy() == ok["fwd_ret_240"].to_numpy().astype(np.float32)).sum())
    return (miss == 0 and exact == len(ok)), f"240m rebuild {exact:,}/{len(ok):,} exact, {miss} unmatched"


def check_null(null: pd.DataFrame, inc: pd.DataFrame) -> tuple[bool, str]:
    if len(null) != len(inc):
        return False, f"trade count {len(null)} vs {len(inc)}"
    fb = int(null["fallback"].sum())
    dr = float(np.abs(null["fwd_ret"].to_numpy(np.float64) - inc["fwd_ret"].to_numpy(np.float64)).max()) \
        if len(inc) else 0.0
    ds = float(np.abs(null["size"].to_numpy() - inc["size"].to_numpy()).max()) if len(inc) else 0.0
    return (fb == 0 and dr <= NULL_TOL and ds < 1e-12), \
        f"{len(inc):,} trades, max per-trade |Δret| {dr:.1e}, path fallbacks {fb}"


# --------------------------------------------------------------------------------------
# The statistic — arm − incumbent, net bps per unit of notional, clustered on exit days
# --------------------------------------------------------------------------------------

def ledger(t: pd.DataFrame) -> pd.DataFrame:
    return wf._ledger(wf._utc_day(t["exit_ts"]), t["signed_ret"].to_numpy(np.float64),
                      t["size"].to_numpy(np.float64), "trade")


def with_stop_slip(t: pd.DataFrame, bps: float = STOP_SLIP_BPS) -> pd.DataFrame:
    out = t.copy()
    stopped = (out["reason"] != "timer").to_numpy()
    out["signed_ret"] = out["signed_ret"].to_numpy(np.float64) - np.where(
        stopped, bps / metrics.BPS * out["size"].to_numpy(np.float64), 0.0)
    return out


def contrast(arm: pd.DataFrame, inc: pd.DataFrame) -> dict:
    return wf.paired_notional_diff_bps(ledger(arm), ledger(inc))


def _line(name: str, t: pd.DataFrame, inc: pd.DataFrame | None) -> str:
    nr = wf.notional_ratio_bps(ledger(t), COST)
    stopped = float((t["reason"] != "timer").mean()) if "reason" in t and len(t) else 0.0
    hold = float(t["hold_min"].mean()) if "hold_min" in t and len(t) else 240.0
    fb = int(t["fallback"].sum()) if "fallback" in t else 0
    s = (f"  {name:<13} n={len(t):>5,}  exited early {stopped:6.1%}  hold {hold:5.0f}m  "
         f"net/notional @14 {nr['mean_bps']:+7.2f}  maxDD {exits._drawdown(t):+.4f}  fallback {fb}")
    if inc is not None:
        c = contrast(t, inc)
        cs = contrast(with_stop_slip(t), inc)
        pt = universe.paired_diff_bps(t, inc, COST)
        s += (f"\n  {'':<13} vs incumbent {c['diff_bps']:+.2f} [{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}] "
              f"bps/notional over {c['clusters']} days; +{STOP_SLIP_BPS:.0f}bps stop slip {cs['diff_bps']:+.2f}; "
              f"per trade (info) {pt['diff_bps']:+.2f}")
    return s


# --------------------------------------------------------------------------------------
# Scoring one fold
# --------------------------------------------------------------------------------------

def score_fold(fold: str, sized_fields: dict, labels: list[str], grid: Grid,
               with_brake: bool) -> dict:
    sized = backtest.PolicySpec(label="incumbent SIZED", **sized_fields)
    arms: dict[str, list[pd.DataFrame]] = {"incumbent": [], **{l: [] for l in labels}}
    if with_brake:
        arms["brake_2_4"] = []
    checks = []
    for seed, rid in exits._fold_runs(fold):
        d = dumps.load(rid, seed=seed)                  # one dump at a time — memory
        acc_ok, acc_msg = check_acceptance(d, grid)
        reg = regime.build(d.df)
        inc = backtest.run([d], sized, {seed: reg}).trades.reset_index(drop=True)
        inc["seed"] = seed
        del d, reg
        gc.collect()
        null = walk_arm(inc, grid, "null")
        null_ok, null_msg = check_null(null, inc)
        checks.append((seed, acc_ok, acc_msg, null_ok, null_msg))
        arms["incumbent"].append(inc)
        for lab in labels:
            mode, k, top = CONFIGS[lab]
            arms[lab].append(walk_arm(inc, grid, mode, k, top))
        if with_brake:
            arms["brake_2_4"].append(brake_arm(inc, grid))
    out = {k: pd.concat(v, ignore_index=True) for k, v in arms.items()}
    out["checks"] = checks
    return out


# --------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------

def report(sized_fields: dict, stage: str, exploration_recorded: bool = False,
           config: str | None = None) -> int:
    wf.require_walkforward_era()
    print("=" * 96)
    print(f"§9.8 — X6: PRICE-PATH EXITS ON THE FOLDS — stage {stage.upper()}")
    print("=" * 96)
    print(wf.registry_state())
    if dumps.missing_runs():
        print(f"\n🔴 refusing: {dumps.missing_runs()} not recorded.")
        return 2
    if stage == "explore":
        folds, labels, with_brake = EXPLORE_FOLDS, list(CONFIGS), True
        print("\nF0 and F1 only (§9.0 rule 2). Nothing is fitted; all five configurations are scored")
        print("and ONE is chosen by §9.8's rule. The brake arm is information only. F2/F3 are not loaded.")
    elif stage == "confirm":
        if not exploration_recorded:
            print("\n🔴 refusing: --stage confirm reads F2+F3. Pass --exploration-recorded only after")
            print("   the exploration table, the chosen label and the MDE forecast are written into §9.8.")
            return 2
        if config not in CONFIGS:
            print(f"\n🔴 refusing: --config must be one of {list(CONFIGS)}, transcribed from §9.8; got {config!r}.")
            return 2
        folds, labels, with_brake = CONFIRM_FOLDS, [config], False
        print(f"\n🔴 F2 + F3 are being read for §9.8. This happens once. Configuration: {config}")
    else:
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")

    grid = load_grid()
    print(f"\nprice path ({EXPORT_DIR}): {grid.span()}")
    print(f"taker {COST:.0f} bps per round trip on every trade, whatever its exit (cancels in the contrast)")

    res = {}
    for fold in folds:
        print("\n" + "=" * 96)
        print(f"{fold} — the arms (the incumbent's trades; only the exit differs)")
        print("=" * 96)
        res[fold] = score_fold(fold, sized_fields, labels, grid, with_brake)
        for seed, acc_ok, acc_msg, null_ok, null_msg in res[fold]["checks"]:
            print(f"  {seed}: acceptance {'PASS' if acc_ok else 'FAIL'} — {acc_msg}; "
                  f"null == incumbent {'PASS' if null_ok else 'FAIL'} — {null_msg}")
            if not (acc_ok and null_ok):
                print("  🔴 harness check failed; nothing below may be read.")
                return 3
        inc = res[fold]["incumbent"]
        print(_line("incumbent", inc, None))
        for lab in labels + (["brake_2_4"] if with_brake else []):
            t = res[fold][lab]
            share = float(t["fallback"].mean()) if len(t) else 0.0
            if share > FALLBACK_MAX:
                print(f"  🔴 {lab}: fallback share {share:.1%} exceeds §9.8's {FALLBACK_MAX:.0%}; stop and revisit.")
                return 3
            print(_line(lab + (" (info)" if lab == "brake_2_4" else ""), t, inc))

    print("\n" + "=" * 96)
    print(f"THE CONTRAST — arm − incumbent, net bps per unit of notional ({'+'.join(folds)} pooled)")
    print("=" * 96)
    inc_all = pd.concat([res[f]["incumbent"] for f in folds], ignore_index=True)
    rows, pooled = [], {}
    for lab in labels:
        arm_all = pd.concat([res[f][lab] for f in folds], ignore_index=True)
        c = contrast(arm_all, inc_all)
        pooled[lab] = c
        per_seed = {}
        for s in ("s1", "s2", "s3"):
            a = arm_all[arm_all["seed"].map(exits._seed_number) == s]
            b = inc_all[inc_all["seed"].map(exits._seed_number) == s]
            per_seed[s] = contrast(a, b)["diff_bps"]
        rows.append({"config": lab, "diff/notional": c["diff_bps"],
                     "95% CI": f"[{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]", "se": c["se_bps"],
                     "days": c["clusters"], "s1": per_seed["s1"], "s2": per_seed["s2"], "s3": per_seed["s3"],
                     "median seed": float(np.median(list(per_seed.values()))),
                     "early exits": float((arm_all["reason"] != "timer").mean()),
                     "hold": float(arm_all["hold_min"].mean()),
                     "+5bps slip": contrast(with_stop_slip(arm_all), inc_all)["diff_bps"]})
    table = pd.DataFrame(rows)
    print(table.to_string(index=False, float_format=lambda v: f"{v:+.2f}"))
    e = wf.notional_ratio_bps(ledger(inc_all), COST)
    print(f"\n  E, the incumbent's own net bps per unit of notional at taker {COST:.0f} on these folds: "
          f"{e['mean_bps']:+.2f} [{e['lo95_bps']:+.2f}, {e['hi95_bps']:+.2f}] (n {len(inc_all):,} trades)")
    if with_brake:
        br = pd.concat([res[f]["brake_2_4"] for f in folds], ignore_index=True)
        cb = contrast(br, inc_all)
        pt = universe.paired_diff_bps(br, inc_all, COST)
        print(f"  brake 2%/4% (information only, never selectable): {cb['diff_bps']:+.2f} "
              f"[{cb['lo95_bps']:+.2f}, {cb['hi95_bps']:+.2f}] per notional; per trade {pt['diff_bps']:+.2f}; "
              f"stop {float((br['reason'] == 'sl').mean()):.1%} target {float((br['reason'] == 'tp').mean()):.1%}")

    print("\n" + "=" * 96)
    print("THE VERDICT, under §9.8 as written")
    print("=" * 96)
    if stage == "explore":
        best = table.sort_values("diff/notional", ascending=False).iloc[0]
        c = pooled[best["config"]]
        d_here = sum(exits._span_days(f) for f in EXPLORE_FOLDS)
        d_conf = sum(exits._span_days(f) for f in CONFIRM_FOLDS)
        se_conf = c["se_bps"] * np.sqrt(d_here / d_conf)
        passed = best["diff/notional"] > 0 and best["median seed"] > 0
        print(f"  chosen by the rule (highest pooled contrast): {best['config']}  {best['diff/notional']:+.2f} "
              f"[{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]; median seed {best['median seed']:+.2f}")
        print(f"  forecast for the confirmation shape: SE {se_conf:.2f} -> MDE (1.96σ) {1.96 * se_conf:.2f} "
              f"bps per notional  (span days {d_here:.0f} -> {d_conf:.0f})")
        print(f"  exploration gate: best > 0 -> {best['diff/notional'] > 0}; median seed-number > 0 -> {best['median seed'] > 0}")
        verdict = ("GATE PASSED — record this table and the label in §9.8, then run --stage confirm "
                   "--exploration-recorded --config " + best["config"]) if passed else \
            "GATE NOT PASSED — §9.8 closes here; F2/F3 are not read"
        print(f"\n  ==> {verdict}")
    else:
        row = table.iloc[0]
        c = pooled[row["config"]]
        confirmed = c["lo95_bps"] > 0 and row["median seed"] > 0
        print(f"  95% lower bound > 0 -> {c['lo95_bps'] > 0} ({c['lo95_bps']:+.2f}); median seed-number > 0 -> "
              f"{row['median seed'] > 0} ({row['median seed']:+.2f})")
        print(f"\n  ==> {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} (read against E above: an interval that "
              f"excludes E is a detected absence, one that contains it is 'not detectable')")
    return 0
