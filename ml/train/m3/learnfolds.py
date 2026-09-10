"""The learned challenger on the walk-forward folds — WALKFORWARD_PROTOCOL §9.5, in code.

WHAT THIS IS. M3-3's fitting machinery (`learn.py`, `features.py`) re-run with the FOLD as
the unit: a fold's three seeds are pooled into one fit and one held-out scoring, and the
held-out fold's bars come from checkpoints the fit never saw. Every constant is §9.5's;
none is a knob. The registration was written before this file existed.

THE ORDER THIS FILE INSISTS ON (§9.0 rule 2):
  * `explore` reads F0 and F1 only — fit on one, score the other — and chooses ONE of the
    eight configurations by a mechanical rule. It never loads F2 or F3 from disk.
  * `confirm` reads F2 and F3 once, refuses without --exploration-recorded, and takes the
    configuration only from --config, transcribed from §9.5. It fits on the other three
    folds and scores the held-out one, twice.

MEMORY. Twelve fold dumps do not fit the analysis container together (§9.4's gate learned
that), so dumps are loaded one fold at a time, twice: once to build each fold's candidate
pool (a few tens of thousands of rows per seed, kept), once to simulate the held-out fold's
ledgers with the learned overlay and the incumbent side by side.
"""
from __future__ import annotations

import gc

import numpy as np
import pandas as pd

from . import backtest, dumps, features, learn, metrics, regime, universe
from . import walkforward as wf

EXPLORE_FOLDS = ("F0", "F1")                  # §9.5: two-unit leave-one-out
CONFIRM_FOLDS = ("F2", "F3")                  # §9.5: each held out once, trained on the rest
ALL_FOLDS = ("F0", "F1", "F2", "F3")
COST = metrics.TAKER_COST_BPS
MDE_FORECAST_CONFIRM = 24.43                  # §9.4's forecast for the F2+F3 shape, bps/trade

CONFIGS = [features.LearnedConfig(m, e, s)
           for m in ("A", "B") for e in ("R1", "R2") for s in ("S1", "S2")]
ABLATIONS = [features.LearnedConfig("conf", e, s) for e in ("R1", "R2") for s in ("S1", "S2")]


# --------------------------------------------------------------------------------------
# Pass 1 — the candidate pools, one fold at a time
# --------------------------------------------------------------------------------------

def _halves(f: pd.DataFrame) -> pd.Series:
    """§9.5's inner units: the calendar halves of each fold-seed, split at the midpoint of
    its bar timestamps. Labelled '<fold>a' / '<fold>b'."""
    out = pd.Series(index=f.index, dtype="object")
    for seed, g in f.groupby("seed", sort=False):
        t = g["ts"].to_numpy(np.int64)
        mid = (t.min() + t.max()) / 2.0
        fold = dumps.fold_of(seed)
        out.loc[g.index] = np.where(t < mid, f"{fold}a", f"{fold}b")
    return out


def build_pools(folds: tuple[str, ...]) -> tuple[dict, dict, dict]:
    """fold -> its pooled candidate rows; plus R2's bar budgets per (seed, fold) and per
    (seed, half). Only the named folds are read from disk."""
    pools, counts_fold, counts_half = {}, {}, {}
    for fold in folds:
        parts = []
        for seed, rid in _fold_runs(fold):
            d = dumps.load(rid, seed=seed)          # one dump at a time — memory
            f = features.build(d, regime.build(d.df))
            del d
            gc.collect()
            f = f[f["window"].notna()]
            if not (f["window"] == fold).all():
                raise SystemExit(f"{seed}: bars tagged outside {fold}: "
                                 f"{sorted(f['window'].unique())}")
            f = f.assign(half=_halves(f))
            counts_fold[(seed, fold)] = int(len(f))
            for h, n in f["half"].value_counts().items():
                counts_half[(seed, str(h))] = int(n)
            p = features.pool(f)
            print(f"  {seed}  {len(f):>8,} bars  pool {len(p):>7,}  "
                  f"halves {dict(f['half'].value_counts().sort_index())}")
            parts.append(p)
            del f
        pools[fold] = pd.concat(parts, ignore_index=True)
    return pools, counts_fold, counts_half


def _fold_runs(fold: str) -> list[tuple[str, str]]:
    """(seed label, run id) for every recorded seed of `fold`; refuses a partial fold."""
    got = [(seed, rid) for seed, rid in dumps.recorded_runs().items()
           if dumps.fold_of(seed) == fold]
    if len(got) != 3:
        raise SystemExit(f"§9.5 needs every seed of {fold}; have {[s for s, _ in got]}")
    return got


# --------------------------------------------------------------------------------------
# Pass 2 — fit on the training folds, score the held-out one
# --------------------------------------------------------------------------------------

def fit_heldout(pools: dict, train: tuple[str, ...], held: str, model: str,
                counts_fold: dict, counts_half: dict) -> learn.OOF:
    """One fit per model class per held-out fold. λ by leave-one-half-out inside `train`
    (§9.5); the held-out fold is never consulted. Returns an OOF whose pool is the held-out
    fold's rows with `lscore` attached, in the shape `learn.apply_rules` expects."""
    cfg = features.LearnedConfig(model, "R2", "S1")     # only `.model` is read by the fit
    tr = pd.concat([pools[f] for f in train], ignore_index=True)
    inner = tr.assign(window=tr["half"])                 # inner units are halves
    lam, scan = learn.select_lambda(inner, cfg, tuple(sorted(inner["window"].unique())),
                                    counts_half)
    Xtr, names = learn._design(tr, cfg)
    fit = learn.ridge(Xtr, tr["y_bps"].to_numpy(np.float64), lam, names)
    he = pools[held].reset_index(drop=True)
    he = he.assign(lscore=fit.score(learn._design(he, cfg)[0]))
    return learn.OOF(model=model, pool=he, fits={held: fit}, lam_scan={held: scan},
                     train_score={held: tr.assign(lscore=fit.score(Xtr))})


_EMPTY_OVERLAY = {"pair": pd.Series(dtype=object), "ts": pd.Series(dtype="int64"),
                  "entry": pd.Series(dtype="float64"), "lsize": pd.Series(dtype="float64")}


def _overlay(pol: learn.Policy, seeds: list[str]) -> dict[str, pd.DataFrame]:
    """`learn.overlay`, made total: a configuration that enters NO bar on a seed (R1's
    absolute threshold can select nothing, as it did in M3-3's w1/w3) hands the simulator
    an empty frame for that seed, so every bar merges to NaN and is unenterable — a
    zero-trade arm, reported as one, rather than a crash."""
    ov = learn.overlay(pol) if pol.entry.any() else {}
    for s in seeds:
        ov.setdefault(s, pd.DataFrame(_EMPTY_OVERLAY))
    return ov


def _top_terms(fit: learn.Fit, k: int = 5) -> str:
    order = np.argsort(-np.abs(fit.beta[1:]))[:k]
    return ", ".join(f"{fit.names[i]} {fit.beta[1 + i]:+.2f}" for i in order)


def score_fold(held: str, oofs: dict[str, learn.OOF], cfgs: list[features.LearnedConfig],
               counts_fold: dict, sized_fields: dict) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Simulate the held-out fold: the incumbent and every configuration's learned arm on
    the same dumps. Returns (incumbent trades, {label: learned trades})."""
    sized = backtest.PolicySpec(label="incumbent SIZED", **sized_fields)
    seeds = [seed for seed, _ in _fold_runs(held)]
    overlays = {cfg.label: _overlay(learn.apply_rules(oofs[cfg.model], cfg, counts_fold), seeds)
                for cfg in cfgs}
    inc_parts, out = [], {cfg.label: [] for cfg in cfgs}
    for seed, rid in _fold_runs(held):
        d = dumps.load(rid, seed=seed)              # one dump at a time — memory
        inc_parts.append(wf.run_policy([d], sized))
        for cfg in cfgs:
            out[cfg.label].append(
                backtest.run([d], learn.spec_for(cfg), None, overlay=overlays[cfg.label]).trades)
        del d
        gc.collect()
    return (pd.concat(inc_parts, ignore_index=True),
            {k: pd.concat(v, ignore_index=True) for k, v in out.items()})


# --------------------------------------------------------------------------------------
# The statistics
# --------------------------------------------------------------------------------------

def _concat(parts: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate ledgers, skipping empty ones (a zero-trade fold) so pandas does not
    warn about all-NA dtype inference; an all-empty list stays an empty ledger."""
    live = [p for p in parts if len(p)]
    return pd.concat(live, ignore_index=True) if live else parts[0]


def _row(label: str, arm: pd.DataFrame, inc: pd.DataFrame, cost: float = COST) -> dict:
    return wf._rlg_contrast(label, arm, inc, cost)


def _fmt(rows: list[dict]) -> str:
    return wf._rlg_fmt(rows)


def _ledger(t: pd.DataFrame) -> pd.DataFrame:
    size = t["size"].to_numpy(np.float64) if "size" in t else np.ones(len(t))
    day = pd.to_datetime(t["exit_ts"], unit="ns", utc=True).dt.floor("D").to_numpy()
    return wf._ledger(day, t["signed_ret"].to_numpy(np.float64) * size, size, "trade")


def _notional_line(arm: pd.DataFrame, inc: pd.DataFrame) -> str:
    d = wf.paired_notional_diff_bps(_ledger(arm), _ledger(inc))
    return (f"{d['diff_bps']:+.2f} [{d['lo95_bps']:+.2f}, {d['hi95_bps']:+.2f}] bps per unit "
            f"of notional ({d['clusters']} clusters)")


def _print_fits(oofs: dict[str, learn.OOF], held: str) -> None:
    for model, oof in oofs.items():
        fit = oof.fits[held]
        scan = ", ".join(f"{lam:g}:{v:+.1f}" for lam, v in oof.lam_scan[held])
        print(f"    model {model:<4} held {held}: λ = {fit.lam:g}   inner scan [{scan}]")
        print(f"      largest terms: {_top_terms(fit)}")


# --------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------

def report(sized_fields: dict, stage: str, exploration_recorded: bool = False,
           config: str | None = None) -> int:
    wf.require_walkforward_era()
    print("=" * 96)
    print(f"§9.5 — THE LEARNED CHALLENGER ON THE FOLDS — stage {stage.upper()}")
    print("=" * 96)
    print(wf.registry_state())
    if dumps.missing_runs():
        print(f"\n🔴 refusing: {dumps.missing_runs()} not recorded.")
        return 2

    if stage == "explore":
        folds = EXPLORE_FOLDS
        plan = {"F0": ("F1",), "F1": ("F0",)}
        cfgs = CONFIGS + ABLATIONS
        models = ("A", "B", "conf")
        print("\nF0 and F1 only (§9.0 rule 2). Fit on one, score the other; every score is")
        print("out-of-fold and out-of-checkpoint. Chooses ONE configuration by §9.5's rule;")
        print("decides nothing about promotion. F2/F3 are not loaded.")
    elif stage == "confirm":
        if not exploration_recorded:
            print("\n🔴 refusing: --stage confirm reads F2+F3. Pass --exploration-recorded only")
            print("   after the exploration table and the chosen label are written into §9.5.")
            return 2
        chosen = [c for c in CONFIGS if c.label == config]
        if not chosen:
            print(f"\n🔴 refusing: --config must be one of {[c.label for c in CONFIGS]}, "
                  f"transcribed from §9.5; got {config!r}.")
            return 2
        folds = CONFIRM_FOLDS
        plan = {"F2": ("F0", "F1", "F3"), "F3": ("F0", "F1", "F2")}
        cfgs = chosen
        models = (chosen[0].model,)
        print(f"\n🔴 F2 + F3 are being read for §9.5. This happens once. Configuration under "
              f"test (from --config): {config}")
    else:
        raise SystemExit(f"stage must be explore or confirm, got {stage!r}")

    need = tuple(sorted({f for fs in plan.values() for f in fs} | set(folds)))
    print(f"\ntaker {COST:.0f} bps decides; {wf.VERIFIED_TAKER_LINE_BPS:.2f} printed for information")
    print("\n" + "=" * 96)
    print(f"A. THE CANDIDATE POOLS — top {features.POOL_COVERAGE:.0%} by 240m confidence, "
          f"per fold-seed, complete observations only (folds loaded: {', '.join(need)})")
    print("=" * 96)
    pools, counts_fold, counts_half = build_pools(need)
    for f in need:
        print(f"  {f}: pool rows {len(pools[f]):,}")

    print("\n" + "=" * 96)
    print("B. THE FITS — λ by leave-one-half-out inside the training folds (§9.5)")
    print("=" * 96)
    inc_by, arms_by = {}, {}
    for held in folds:
        train = plan[held]
        print(f"  held {held}  <-  fit on {' + '.join(train)}  "
              f"({sum(len(pools[f]) for f in train):,} rows)")
        oofs = {m: fit_heldout(pools, train, held, m, counts_fold, counts_half) for m in models}
        _print_fits(oofs, held)
        inc_by[held], arms_by[held] = score_fold(held, oofs, cfgs, counts_fold, sized_fields)

    print("\n" + "=" * 96)
    print(f"C. THE CONTRAST — diff = learned − incumbent, net bps/trade at taker {COST:.0f}, "
          f"day-clustered on the union of exit days")
    print("=" * 96)
    inc_all = pd.concat(inc_by.values(), ignore_index=True)
    pooled = {}
    for cfg in cfgs:
        rows = []
        for held in folds:
            rows.append(_row(f"{cfg.label} {held}", arms_by[held][cfg.label], inc_by[held]))
        arm_all = _concat([arms_by[h][cfg.label] for h in folds])
        pooled[cfg.label] = _row(f"{cfg.label} {'+'.join(folds)}", arm_all, inc_all)
        rows.append(pooled[cfg.label])
        print(_fmt(rows))
        alt = _row("alt", arm_all, inc_all, wf.VERIFIED_TAKER_LINE_BPS)
        print(f"   at {wf.VERIFIED_TAKER_LINE_BPS:.2f}: {alt['diff']:+.2f} "
              f"[{alt['lo95']:+.2f}, {alt['hi95']:+.2f}];  per notional (information): "
              f"{_notional_line(arm_all, inc_all)}\n")

    print("=" * 96)
    if stage == "explore":
        live = [c for c in CONFIGS if pooled[c.label]["n_arm"] > 0]
        dead = [c.label for c in CONFIGS if pooled[c.label]["n_arm"] == 0]
        if dead:
            print(f"   zero-trade configurations, excluded from the choice: {dead}")
        best = max(live, key=lambda c: pooled[c.label]["diff"])
        d = pooled[best.label]
        abl = pooled[features.LearnedConfig("conf", best.entry, best.sizing).label]
        print(f"§9.5 CHOICE RULE -> {best.label}: pooled F0+F1 out-of-fold diff "
              f"{d['diff']:+.2f} [{d['lo95']:+.2f}, {d['hi95']:+.2f}] "
              f"({d['n_arm']:,} learned vs {d['n_inc']:,} incumbent trades)")
        print(f"   matched C2 ablation {abl['unit'].split()[0]}: diff {abl['diff']:+.2f} "
              f"[{abl['lo95']:+.2f}, {abl['hi95']:+.2f}]  -> the eight extra observations are "
              f"worth {d['diff'] - abl['diff']:+.2f} bps/trade here (information)")
        print("=" * 96)
        if d["diff"] > 0:
            print("  - Exploration gate PASSED (best diff > 0). Record sections B and C and the")
            print("    label in §9.5, then run ONCE:")
            print(f"    m3 learnfolds --stage confirm --exploration-recorded --config {best.label}")
        else:
            print("  - Exploration gate NOT passed (best diff <= 0). §9.5 closes here; F2/F3 are")
            print("    NOT read. Record the table and the closure.")
        return 0

    # confirm: the registered criterion
    cfg = cfgs[0]
    d = pooled[cfg.label]
    arm_all = _concat([arms_by[h][cfg.label] for h in folds])
    print("D. THE SEED RULE (M3_PROTOCOL §8.3) — each seed-number pooled across F2+F3")
    print("=" * 96)
    seed_rows = []
    for s in ("s1", "s2", "s3"):
        a = arm_all[arm_all["seed"].str.endswith(s)]
        i = inc_all[inc_all["seed"].str.endswith(s)]
        seed_rows.append(_row(f"{cfg.label} {s}", a, i))
    print(_fmt(seed_rows))
    med = float(np.median([r["diff"] for r in seed_rows]))
    ok_lb = bool(d["clusters"] >= 2 and d["lo95"] > 0)
    ok_seed = med > 0
    ok = ok_lb and ok_seed
    print("\n" + "=" * 96)
    print(f"§9.5 VERDICT: {'CONFIRMED' if ok else 'NOT CONFIRMED'} — F2+F3 clustered 95% lower "
          f"bound of the diff {d['lo95']:+.2f} ({'>' if ok_lb else '<='} 0); median seed diff "
          f"{med:+.2f} ({'>' if ok_seed else '<='} 0)")
    print("=" * 96)
    se = (d["hi95"] - d["lo95"]) / (2 * 1.96)
    print(f"  - Clustered SE of the difference {se:.2f} bps -> MDE {1.96 * se:.2f} "
          f"(§9.4 forecast {MDE_FORECAST_CONFIRM:.2f}).")
    if ok:
        print("  - Licenses a registration to SERVE the challenger under M3_PROTOCOL §8.3 C1–C5")
        print("    on the served checkpoint's own split. Not itself a change to anything served.")
    else:
        print(f"  - Read against the MDE: an improvement smaller than {1.96 * se:.1f} bps/trade")
        print("    could not have been confirmed. Closed on these folds; no re-choice, no re-run.")
    return 0
