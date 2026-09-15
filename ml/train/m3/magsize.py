"""WALKFORWARD_PROTOCOL §9.6 — X3: predicted-magnitude sizing on the folds.

The incumbent's size ladder keys on `btc_absret_1d`, BTC's TRAILING 24h |return|. This
harness keeps the incumbent's entries and the incumbent's ladder mapping (bar-quintiles ->
1/3 .. 5/3) and changes ONE thing: the key becomes an out-of-fold prediction of the
pair-normalised FORWARD 4h magnitude, |fwd_ret_240| / rv_7d, from thirteen dump-derived,
lookahead-free observables. The contrast is X3 - incumbent per unit of notional.

Everything here is fixed by §9.6 before any number was read: the feature list, the target,
the model and its parameters, the round-selection rule, the fold shape, the statistic, the
gates. Changing any of them is a new registration, not a re-run.

Memory discipline, as learnfolds: one fold dump at a time — twelve dumps OOM the container.
"""
from __future__ import annotations

import gc

import numpy as np
import pandas as pd

from . import backtest, dumps, metrics, regime
from . import walkforward as wf

EXPLORE_FOLDS = ("F0", "F1")
CONFIRM_FOLDS = ("F2", "F3")
PLAN = {
    "explore": {"F0": ("F1",), "F1": ("F0",)},                   # two-unit leave-one-out
    "confirm": {"F2": ("F0", "F1", "F3"), "F3": ("F0", "F1", "F2")},
}
COST = metrics.TAKER_COST_BPS
SIGNAL_HORIZON = 240

# §9.6: the observation vector, in a fixed order. The list IS the registration.
FEATURES = [
    "btc_absret_1d",      # 1  the incumbent key — the model can only add to it
    "rv_1d", "rv_7d", "rv_30d",   # 2-4 own-pair realised vol of trailing-60m returns
    "vol_expansion",      # 5  rv_1d / rv_7d
    "abs_trail_60m", "abs_trail_240m", "abs_trail_1440m",   # 6-8 own-pair trailing |return|
    "xs_disp_4h",         # 9  cross-sectional sd of trailing-240m returns
    "xs_disp_1h",         # 10 cross-sectional sd of trailing-60m returns (O5's feature)
    "xs_absmean_4h",      # 11 cross-sectional mean |trailing-240m return|
    "hour_utc", "dow",    # 12-13 volatility seasonality
]
TARGET = "m_rel"                                  # |fwd_ret_240| / rv_7d
KEY_INCUMBENT = "btc_absret_1d"
KEY_ABLATION = "rv_1d"                            # for information only, explore only

# §9.6: the model, fixed. `deterministic` + a fixed seed + fixed threads => reproducible.
LGB_PARAMS = dict(objective="regression", num_leaves=15, learning_rate=0.05,
                  min_data_in_leaf=5000, feature_fraction=0.8, bagging_fraction=0.8,
                  bagging_freq=1, lambda_l2=10.0, seed=20260915, deterministic=True,
                  force_row_wise=True, num_threads=4, verbose=-1)
MAX_ROUNDS = 2000
PATIENCE = 50
WINSOR_Q = 0.99
LADDER_QS = [0.2, 0.4, 0.6, 0.8]                  # backtest.run's edges, verbatim
FALLBACK_MAX = 0.05                               # §9.6: stop if more trades fall back
# §9.4's recorded exit-day clusters of the incumbent on F2+F3, for the MDE forecast. It is a
# constant so the explore stage never has to open an F2/F3 dump (§9.0 rule 2).
CONFIRM_CLUSTERS = 286


# --------------------------------------------------------------------------------------
# Pass 1 — the per-bar frame, one dump at a time
# --------------------------------------------------------------------------------------

def frame(d: dumps.Dump) -> pd.DataFrame:
    """(pair, ts, seed, fwd_ret, FEATURES, TARGET) for every 240m bar of one fold-seed.

    Built from the dump alone by Q1's construction (regime.py): fwd_ret at horizon h shifted
    back h minutes is the trailing return, so nothing here needs the DB or an export.
    """
    reg = regime.build(d.df)
    sig = d.at(SIGNAL_HORIZON)[["pair", "ts", "fwd_ret"]].copy()
    out = sig.merge(reg[["pair", "ts", "btc_absret_1d", "rv_1d", "rv_7d", "rv_30d",
                         "xs_disp_4h", "trail_240m"]], on=["pair", "ts"], how="left")
    for h in (60, 1440):
        out = out.merge(regime.trailing_return(d.df, h), on=["pair", "ts"], how="left")
    with np.errstate(divide="ignore", invalid="ignore"):
        out["vol_expansion"] = out["rv_1d"] / out["rv_7d"].replace(0.0, np.nan)
        out[TARGET] = out["fwd_ret"].abs() / out["rv_7d"].replace(0.0, np.nan)
    for h in (60, 240, 1440):
        out[f"abs_trail_{h}m"] = out[f"trail_{h}m"].abs()
    xs1 = out.groupby("ts", observed=True)["trail_60m"].std().rename("xs_disp_1h")
    xsa = out.groupby("ts", observed=True)["abs_trail_240m"].mean().rename("xs_absmean_4h")
    out = out.merge(xs1.reset_index(), on="ts", how="left")
    out = out.merge(xsa.reset_index(), on="ts", how="left")
    t = pd.to_datetime(out["ts"], unit="ns", utc=True)
    out["hour_utc"] = t.dt.hour.astype(np.float64)
    out["dow"] = t.dt.dayofweek.astype(np.float64)
    out["seed"] = d.seed
    cols = ["pair", "ts", "seed", "fwd_ret"] + FEATURES + [TARGET]
    return out[cols].reset_index(drop=True)


def _fold_runs(fold: str) -> list[tuple[str, str]]:
    got = [(seed, rid) for seed, rid in dumps.recorded_runs().items()
           if dumps.fold_of(seed) == fold]
    if len(got) != 3:
        raise SystemExit(f"§9.6 needs every seed of {fold}; have {[s for s, _ in got]}")
    return got


def build_frames(folds: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """fold -> the frame over its three seeds, DEDUPLICATED on (pair, ts): the target and
    every feature are checkpoint-independent (§9.6), so a bar is one training row however
    many seeds scored it. Only the named folds are read from disk."""
    frames = {}
    for fold in folds:
        parts = []
        for seed, rid in _fold_runs(fold):
            d = dumps.load(rid, seed=seed)          # one dump at a time — memory
            f = frame(d)
            del d
            gc.collect()
            parts.append(f)
            print(f"  {seed}  {len(f):>9,} bars   complete {int(f[FEATURES + [TARGET]].notna().all(axis=1).sum()):>9,}")
        allf = pd.concat(parts, ignore_index=True)
        dedup = allf.drop_duplicates(subset=["pair", "ts"], keep="first").reset_index(drop=True)
        print(f"  {fold}: {len(allf):,} seed-bars -> {len(dedup):,} unique (pair, ts)")
        frames[fold] = dedup
        del allf, parts
        gc.collect()
    return frames


# --------------------------------------------------------------------------------------
# Pass 2 — the fit (training folds only) and the out-of-fold key
# --------------------------------------------------------------------------------------

class Fit:
    def __init__(self, booster, rounds: int, n_train: int, n_early: int, winsor: float,
                 gain: pd.Series):
        self.booster, self.rounds, self.n_train = booster, rounds, n_train
        self.n_early, self.winsor, self.gain = n_early, winsor, gain

    def predict(self, f: pd.DataFrame) -> np.ndarray:
        """The key for every row with a complete vector; NaN otherwise."""
        ok = f[FEATURES].notna().all(axis=1).to_numpy()
        out = np.full(len(f), np.nan)
        if ok.any():
            out[ok] = self.booster.predict(f.loc[ok, FEATURES].to_numpy(np.float64),
                                           num_iteration=self.rounds)
        return out


def fit(train: pd.DataFrame) -> Fit:
    """§9.6: complete rows only; target winsorised at the training 99th percentile; rounds
    by early stopping on the LATER calendar half of the training bars after fitting on the
    earlier half; then a refit on all training bars for that many rounds. The held-out fold
    is never touched here."""
    import lightgbm as lgb

    tr = train[train[FEATURES + [TARGET]].notna().all(axis=1)]
    y = tr[TARGET].to_numpy(np.float64)
    winsor = float(np.quantile(y, WINSOR_Q))
    y = np.minimum(y, winsor)
    X = tr[FEATURES].to_numpy(np.float64)
    ts = tr["ts"].to_numpy(np.int64)
    mid = (ts.min() + ts.max()) / 2.0
    early, late = ts < mid, ts >= mid
    d_early = lgb.Dataset(X[early], y[early], feature_name=FEATURES, free_raw_data=False)
    d_late = lgb.Dataset(X[late], y[late], reference=d_early, free_raw_data=False)
    probe = lgb.train(LGB_PARAMS, d_early, num_boost_round=MAX_ROUNDS, valid_sets=[d_late],
                      callbacks=[lgb.early_stopping(PATIENCE, verbose=False)])
    rounds = int(probe.best_iteration or MAX_ROUNDS)
    full = lgb.train(LGB_PARAMS, lgb.Dataset(X, y, feature_name=FEATURES), num_boost_round=rounds)
    gain = pd.Series(full.feature_importance("gain"), index=FEATURES)
    gain = gain / gain.sum() if gain.sum() > 0 else gain
    return Fit(full, rounds, int(len(tr)), int(early.sum()), winsor, gain)


# --------------------------------------------------------------------------------------
# Pass 3 — the ladder, the overlays, the arms
# --------------------------------------------------------------------------------------

def ladder(key: np.ndarray, population: pd.Series) -> np.ndarray:
    """backtest.run's sizing, verbatim: quintile edges of the BAR population, size (q+1)/3.
    NaN keys come back NaN so the caller can apply §9.6's fallback explicitly."""
    edges = population.quantile(LADDER_QS).to_numpy()
    q = np.searchsorted(edges, key, side="right")
    size = (q.astype(np.float64) + 1.0) / 3.0
    size[np.isnan(key)] = np.nan
    return size


def overlay_for(reg: pd.DataFrame, key: np.ndarray | None, key_name: str) -> pd.DataFrame:
    """(pair, ts, xsize, fallback) for one fold-seed's regime frame `reg`.

    `key=None` means "key on `key_name`, a column of `reg`" — used for the harness check
    (btc_absret_1d must reproduce the incumbent) and for the rv_1d ablation. Otherwise `key`
    is the model's prediction aligned to `reg`'s rows; where it is missing the incumbent's
    own size is used and the row is flagged (§9.6's fallback)."""
    inc_size = ladder(reg[KEY_INCUMBENT].to_numpy(np.float64), reg[KEY_INCUMBENT])
    if key is None:
        k = reg[key_name].to_numpy(np.float64)
        size = ladder(k, reg[key_name])
    else:
        k = np.asarray(key, np.float64)
        size = ladder(k, pd.Series(k))
    fallback = np.isnan(size)
    size = np.where(fallback, inc_size, size)
    return pd.DataFrame({"pair": reg["pair"].to_numpy(), "ts": reg["ts"].to_numpy(np.int64),
                         "xsize": size, "fallback": fallback})


def x3_fields(sized_fields: dict) -> dict:
    """The X3 arm: the incumbent's fields with the ladder key swapped. `regime_col` stays,
    as a condition without a threshold, so both arms exclude exactly the same bars."""
    f = dict(sized_fields)
    f["size_by_regime"] = False
    f["size_col"] = "xsize"
    return f


def flat_fields(sized_fields: dict) -> dict:
    """Flat size on the incumbent's exact entries (the ladder's own worth, E). This is NOT
    cli.GRID_WINNER_SPEC, whose regime_col=None admits the first-day bars the incumbent
    drops; here regime_col stays so the trade sets coincide."""
    f = dict(sized_fields)
    f["size_by_regime"] = False
    return f


def score_fold(held: str, fit_: Fit, sized_fields: dict, with_ablation: bool) -> dict:
    """Simulate the held-out fold: incumbent, X3, the harness-check arm, the flat arm and
    (explore only) the rv_1d ablation — all on the same dumps, same entries."""
    sized = backtest.PolicySpec(label="incumbent SIZED", **sized_fields)
    x3 = backtest.PolicySpec(label="X3 magsize", **x3_fields(sized_fields))
    flat = backtest.PolicySpec(label="flat (same entries)", **flat_fields(sized_fields))
    arms = {"incumbent": [], "x3": [], "check": [], "flat": [], "ablation": []}
    fallback_n, trade_n = 0, 0
    for seed, rid in _fold_runs(held):
        d = dumps.load(rid, seed=seed)              # one dump at a time — memory
        reg = regime.build(d.df)
        regimes = {seed: reg}
        f = frame(d)
        # align the key to reg's rows
        key = pd.Series(fit_.predict(f), index=pd.MultiIndex.from_frame(f[["pair", "ts"]]))
        key = key.reindex(pd.MultiIndex.from_frame(reg[["pair", "ts"]])).to_numpy()
        ov_x3 = overlay_for(reg, key, "x3")
        ov_check = overlay_for(reg, None, KEY_INCUMBENT)
        arms["incumbent"].append(backtest.run([d], sized, regimes).trades)
        t_x3 = backtest.run([d], x3, regimes, overlay={seed: ov_x3.drop(columns="fallback")}).trades
        arms["x3"].append(t_x3)
        arms["check"].append(backtest.run([d], x3, regimes,
                                          overlay={seed: ov_check.drop(columns="fallback")}).trades)
        arms["flat"].append(backtest.run([d], flat, regimes).trades)
        if with_ablation:
            ov_ab = overlay_for(reg, None, KEY_ABLATION)
            arms["ablation"].append(backtest.run([d], x3, regimes,
                                                 overlay={seed: ov_ab.drop(columns="fallback")}).trades)
        fb = t_x3.merge(ov_x3[["pair", "ts", "fallback"]], left_on=["pair", "entry_ts"],
                        right_on=["pair", "ts"], how="left")
        fallback_n += int(fb["fallback"].fillna(True).sum())
        trade_n += int(len(t_x3))
        del d, reg, f
        gc.collect()
    out = {k: pd.concat(v, ignore_index=True) for k, v in arms.items() if v}
    out["fallback"] = (fallback_n, trade_n)
    return out


# --------------------------------------------------------------------------------------
# The statistics
# --------------------------------------------------------------------------------------

def _ledger(t: pd.DataFrame) -> pd.DataFrame:
    """`signed_ret` already carries size (backtest._simulate_seed), so gross = signed_ret and
    notional = size."""
    if t.empty:
        return pd.DataFrame({"day": [], "gross": [], "notional": [], "kind": []})
    day = pd.to_datetime(t["exit_ts"], unit="ns", utc=True).dt.floor("D").to_numpy()
    return wf._ledger(day, t["signed_ret"].to_numpy(np.float64),
                      t["size"].to_numpy(np.float64), "trade")


def _rate(t: pd.DataFrame, cost: float) -> dict:
    return wf.notional_ratio_bps(_ledger(t), cost)


def _diff(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    return wf.paired_notional_diff_bps(_ledger(a), _ledger(b))


def _drawdown(t: pd.DataFrame, cost: float) -> float:
    if t.empty:
        return 0.0
    s = t.sort_values("exit_ts")
    net = s["signed_ret"].to_numpy(np.float64) - cost / metrics.BPS * s["size"].to_numpy(np.float64)
    return metrics.max_drawdown(np.cumsum(net))


def _check_identical(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    """§9.6's harness check: same trades, same sizes, same P&L to 1e-9."""
    if len(a) != len(b):
        return False, f"trade count {len(a)} vs {len(b)}"
    ka = a.sort_values(["seed", "pair", "entry_ts"]).reset_index(drop=True)
    kb = b.sort_values(["seed", "pair", "entry_ts"]).reset_index(drop=True)
    same_keys = (ka["pair"].to_numpy() == kb["pair"].to_numpy()).all() and \
                (ka["entry_ts"].to_numpy() == kb["entry_ts"].to_numpy()).all()
    if not same_keys:
        return False, "entry sets differ"
    ds = float(np.abs(ka["size"].to_numpy() - kb["size"].to_numpy()).max())
    dp = float(abs(ka["signed_ret"].sum() - kb["signed_ret"].sum()))
    ok = ds < 1e-9 and dp < 1e-9
    return ok, f"max |Δsize| {ds:.2e}, |ΔΣ signed_ret| {dp:.2e}"


def _arm_line(name: str, t: pd.DataFrame, inc: pd.DataFrame | None) -> str:
    r14, r5 = _rate(t, COST), _rate(t, metrics.MAKER_COST_BPS)
    r11 = _rate(t, wf.VERIFIED_TAKER_LINE_BPS)
    ms = float(t["size"].mean()) if len(t) else float("nan")
    per_trade = metrics.clustered_mean_bps(t, COST)["mean_bps"] if len(t) else float("nan")
    s = (f"  {name:<22} n={len(t):>5,}  mean size {ms:.3f}  per notional: "
         f"@14 {r14['mean_bps']:+7.2f} [{r14['lo95_bps']:+.2f}, {r14['hi95_bps']:+.2f}]  "
         f"@11.84 {r11['mean_bps']:+7.2f}  @5 {r5['mean_bps']:+7.2f}   per trade @14 {per_trade:+7.2f}"
         f"   maxDD {_drawdown(t, COST):+.4f}")
    if inc is not None and len(t) and len(inc):
        d = _diff(t, inc)
        s += (f"\n  {'':<22} vs incumbent per notional: {d['diff_bps']:+.2f} "
              f"[{d['lo95_bps']:+.2f}, {d['hi95_bps']:+.2f}] ({d['clusters']} clusters)")
    return s


def _seed_number(seed_label: str) -> str:
    return seed_label[-2:]                        # 'F0s1' -> 's1'


# --------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------

def report(sized_fields: dict, stage: str, exploration_recorded: bool = False) -> int:
    wf.require_walkforward_era()
    print("=" * 96)
    print(f"§9.6 — X3: PREDICTED-MAGNITUDE SIZING ON THE FOLDS — stage {stage.upper()}")
    print("=" * 96)
    print(wf.registry_state())
    if dumps.missing_runs():
        print(f"\n🔴 refusing: {dumps.missing_runs()} not recorded.")
        return 2
    if stage == "explore":
        folds = EXPLORE_FOLDS
        print("\nF0 and F1 only (§9.0 rule 2): fit on one, score the other. Every key is out-of-fold;")
        print("every entry is the incumbent's. Decides only whether F2/F3 may be read. F2/F3 are not loaded.")
    elif stage == "confirm":
        if not exploration_recorded:
            print("\n🔴 refusing: --stage confirm reads F2+F3. Pass --exploration-recorded only after")
            print("   the exploration table, the MDE forecast and the gate verdict are written into §9.6.")
            return 2
        folds = CONFIRM_FOLDS
        print("\n🔴 F2 + F3 are being read for §9.6. This happens once.")
    else:
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")
    plan = PLAN[stage]
    need = tuple(sorted({f for fs in plan.values() for f in fs} | set(folds)))
    print(f"\ntaker {COST:.0f} bps decides (it cancels in the per-notional contrast); "
          f"{wf.VERIFIED_TAKER_LINE_BPS:.2f} and 5 printed for information")

    print("\n" + "=" * 96)
    print(f"A. THE FRAMES — {len(FEATURES)} observables + target per bar, folds loaded: {', '.join(need)}")
    print("=" * 96)
    frames = build_frames(need)

    print("\n" + "=" * 96)
    print("B. THE FITS — rounds by early stopping on the later calendar half of the TRAINING bars")
    print("=" * 96)
    fits: dict[str, Fit] = {}
    for held in folds:
        train = plan[held]
        tr = pd.concat([frames[f] for f in train], ignore_index=True)
        fits[held] = fit(tr)
        ft = fits[held]
        print(f"  held {held}  <-  fit on {' + '.join(train)}: {ft.n_train:,} complete rows "
              f"(early half {ft.n_early:,}), rounds {ft.rounds}, target winsor {ft.winsor:.3f}")
        top = ft.gain.sort_values(ascending=False)
        print("    gain share: " + ", ".join(f"{k} {v:.1%}" for k, v in top.items()))
        del tr
        gc.collect()
    del frames
    gc.collect()

    print("\n" + "=" * 96)
    print("C. THE ARMS — same dumps, same entries; only the size differs")
    print("=" * 96)
    res: dict[str, dict] = {}
    for held in folds:
        res[held] = score_fold(held, fits[held], sized_fields, with_ablation=(stage == "explore"))
        ok, msg = _check_identical(res[held]["check"], res[held]["incumbent"])
        fb_n, tr_n = res[held]["fallback"]
        print(f"\n  --- {held} ---")
        print(f"  HARNESS CHECK (btc_absret_1d through the overlay path == incumbent SIZED): "
              f"{'PASS' if ok else 'FAIL'} — {msg}")
        if not ok:
            print("  🔴 the harness is wrong; nothing below may be read until this passes.")
            return 3
        share = fb_n / tr_n if tr_n else 0.0
        print(f"  fallback trades (no key -> incumbent size): {fb_n} of {tr_n} ({share:.2%})")
        if share > FALLBACK_MAX:
            print(f"  🔴 exceeds §9.6's {FALLBACK_MAX:.0%}; stop and revisit the registration.")
            return 3
        inc = res[held]["incumbent"]
        print(_arm_line("incumbent SIZED", inc, None))
        print(_arm_line("X3 magsize", res[held]["x3"], inc))
        print(_arm_line("flat (same entries)", res[held]["flat"], inc))
        if "ablation" in res[held]:
            print(_arm_line("ablation: key rv_1d", res[held]["ablation"], inc))

    print("\n" + "=" * 96)
    print(f"D. THE CONTRAST — X3 − incumbent, net bps per unit of notional, day-clustered on exit days "
          f"({'+'.join(folds)} pooled)")
    print("=" * 96)
    inc_all = pd.concat([res[h]["incumbent"] for h in folds], ignore_index=True)
    x3_all = pd.concat([res[h]["x3"] for h in folds], ignore_index=True)
    flat_all = pd.concat([res[h]["flat"] for h in folds], ignore_index=True)
    d = _diff(x3_all, inc_all)
    print(f"  pooled: {d['diff_bps']:+.2f} [{d['lo95_bps']:+.2f}, {d['hi95_bps']:+.2f}]  "
          f"se {d['se_bps']:.2f}  clusters {d['clusters']}   (n {len(x3_all):,} trades on each arm)")
    per_seed = {}
    for s in ("s1", "s2", "s3"):
        a = x3_all[x3_all["seed"].map(_seed_number) == s]
        b = inc_all[inc_all["seed"].map(_seed_number) == s]
        per_seed[s] = _diff(a, b)["diff_bps"]
        print(f"  seed-number {s}: {per_seed[s]:+.2f}  (n {len(a):,})")
    median_seed = float(np.median(list(per_seed.values())))
    e = _diff(inc_all, flat_all)
    print(f"  E, the ladder's own worth here (incumbent − flat, same entries): {e['diff_bps']:+.2f} "
          f"[{e['lo95_bps']:+.2f}, {e['hi95_bps']:+.2f}]")
    pt = wf._rlg_contrast("per trade (information)", x3_all, inc_all, COST)
    print(f"  per trade (information, confounded by mean size): {pt['diff']:+.2f} "
          f"[{pt['lo95']:+.2f}, {pt['hi95']:+.2f}]; mean size X3 {x3_all['size'].mean():.3f} "
          f"vs incumbent {inc_all['size'].mean():.3f}")
    if "ablation" in res[folds[0]]:
        ab_all = pd.concat([res[h]["ablation"] for h in folds], ignore_index=True)
        da = _diff(ab_all, inc_all)
        print(f"  ablation rv_1d − incumbent (information, never selected): {da['diff_bps']:+.2f} "
              f"[{da['lo95_bps']:+.2f}, {da['hi95_bps']:+.2f}]")

    print("\n" + "=" * 96)
    print("E. THE VERDICT, under §9.6 as written")
    print("=" * 96)
    if stage == "explore":
        d_here = d["clusters"]
        se_conf = d["se_bps"] * np.sqrt(d_here / CONFIRM_CLUSTERS) if d_here else float("nan")
        print(f"  forecast for the confirmation shape: SE {se_conf:.2f} -> MDE (1.96σ) {1.96 * se_conf:.2f} "
              f"bps per notional  (clusters here {d_here}, F2+F3 recorded {CONFIRM_CLUSTERS})")
        passed = d["diff_bps"] > 0 and median_seed > 0
        print(f"  exploration gate: pooled > 0 -> {d['diff_bps'] > 0}; median seed-number > 0 "
              f"({median_seed:+.2f}) -> {median_seed > 0}")
        print(f"\n  ==> {'GATE PASSED — record this table in §9.6, then run --stage confirm --exploration-recorded' if passed else 'GATE NOT PASSED — §9.6 closes here; F2/F3 are not read'}")
    else:
        confirmed = d["lo95_bps"] > 0 and median_seed > 0
        print(f"  clustered 95% lower bound > 0 -> {d['lo95_bps'] > 0} ({d['lo95_bps']:+.2f}); "
              f"median seed-number > 0 -> {median_seed > 0} ({median_seed:+.2f})")
        print(f"\n  ==> {'CONFIRMED' if confirmed else 'NOT CONFIRMED'} (read against E above: "
              f"an interval that excludes E is a detected absence, one that contains it is 'not detectable')")
    return 0
