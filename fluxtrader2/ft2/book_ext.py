"""R33 — the ±1 % book imbalance DEMEANED by the pair's own trailing month, as a ceiling screen in P2's frame (PLAN §8 R33).

`ft2 ceiling --target pairs --family depth` → output/ceiling_depth.md, output/ceiling_depth/.

Three bar × pair features from ONE source, `ceiling.depth_frames`' imb1 — the ±1 % imbalance, (bid − ask notional within ±1 % of
mid) / their sum, from the archive book's last ~30 s sample strictly before t; the definition the P2 screen and the rules share:
    depth_imb_1        the raw imbalance, P2's feature — the VALIDITY row: its screen rows and its day-shuffle null must reproduce
                       P2's saved `output/ceiling/ic.parquet` and `noise_ic.parquet` to 1e-6, else the run is VOID (exit 2);
    depth_imb_1_lvl30  its trailing-month mean — the mean over the MONTH = 8,640 bars ending at t (≥ MIN_MONTH of them present),
                       the SLOW part; described, not gated (a feature this slow is flattered by a day-shuffle null, R6);
    depth_imb_1_dm     = depth_imb_1 − depth_imb_1_lvl30, the FAST part — THE registered feature. raw = lvl30 + dm exactly
                       wherever both exist (asserted in `validity`).
The frame is P2's exactly: `ceiling.panel` on the twelve, `derive`, F1+F2 embargoed as the scored sample (`D["scored"]`),
`ceiling.ic_screen`'s statistics (the directional pooled IC on per-pair ranks, the relative cross-sectional Spearman, the vol IC)
and its `_null_feature` with P2's day shuffles (seed 0 — the same draws P2 made). A SECOND null, R6's: the labels rolled by whole
days over the panel (≥ SHIFT_MIN days, `shifts`), the feature in place — the time of day kept, every link to the feature broken,
and a slow feature not flattered. Per null the family-wise p over the feature's three horizons (NULL_HORIZONS: 1h, 4h, 1d) is the
share of draws whose largest |t| over the three is at or above the real |t|; `p_family` is the LARGER of the two nulls' p_fw.
Gate (R33), on depth_imb_1_dm, directional, 1d: CLEARS if p_family ≤ 0.05 AND the IC has the registered sign (negative: a
bid-heavy book precedes a fall) AND the same sign in F1 and in F2 AND |IC| ≥ P2's #7 maker bar at 1d (recomputed here from
`ceiling.bar_cost` / `move_vs_cost`); CLOSED if |IC| + 1.96 se < that bar; else NOT DETECTABLE. The same with the opposite sign is
"CLEARS WITH THE OPPOSITE SIGN" — a hypothesis of its own, nothing licensed. Nothing here reads a confirmation fold.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import ceiling, folds
from .ceiling import HORIZONS, MDE_K, NULL_HORIZONS, Z_CLIP, _ic_pooled, _ic_xs, _null_feature, _pair_rank, day_lags, hac

OUT_MD = Path("output/ceiling_depth.md")
OUT_DIR = Path("output/ceiling_depth")
SAVED = ceiling.OUT_DIR                   # P2's output/ceiling/: ic.parquet, noise_ic.parquet, move_vs_cost.parquet
R33_BAR = 0.0106                          # R34: the size condition as a NUMBER — P2's / R33's 1d maker bar on the twelve (the outside names have no maker measurement)


def out_paths(universe: str | None) -> tuple[Path, Path]:
    """R33's paths for the twelve; `output/ceiling_depth_<universe>*` for a breadth read (R34), so R33's outputs are never overwritten."""
    tag = f"_{universe}" if universe else ""
    return Path(f"output/ceiling_depth{tag}.md"), Path(f"output/ceiling_depth{tag}")
RAW, LVL, DM = "depth_imb_1", "depth_imb_1_lvl30", "depth_imb_1_dm"
MONTH = 30 * 288                          # the trailing month, in 5m bars (§7 (b): "the pair's trailing-month mean")
MIN_MONTH = MONTH // 2                    # bars of book the mean needs before it exists
HZ = NULL_HORIZONS                        # 1h, 4h, 1d — the family
PRIMARY = "1d"
BET = "directional"
SIGN = -1.0                               # the registered sign of the IC: a bid-heavy book (imb > 0) precedes a fall
SHIFT_MIN = 60                            # R6's smallest circular shift, in days
DRAWS = ceiling.DRAWS
TOL = 1e-6
PER_DAY = 288


# ---- the features ------------------------------------------------------------------------------------------------------------------
def features_depth(idx: pd.DatetimeIndex, cols: list[str], end: pd.Timestamp = ceiling.END) -> dict[str, pd.DataFrame]:
    """The three frames on `idx`: raw (P2's definition, one call), its trailing-month mean, and their difference. The mean at t
    includes the bar t (whose sample is strictly before t), so every value is known at t."""
    imb1 = ceiling.depth_frames(idx, cols, end)[0]
    lvl = imb1.rolling(MONTH, min_periods=MIN_MONTH).mean()
    return {RAW: imb1, LVL: lvl, DM: imb1 - lvl}


# ---- R6's null: whole-day circular shifts of the labels -----------------------------------------------------------------------------
def shifts(n_days: int, draws: int, seed: int, shift_min: int = SHIFT_MIN) -> np.ndarray:
    """Draw 0 is the real data; the others are uniform whole-day shifts in [shift_min, n_days − shift_min]."""
    assert n_days > 3 * shift_min, "too short for the shift null"
    return np.concatenate([[0], np.random.default_rng(seed).integers(shift_min, n_days - shift_min + 1, draws)])


def shift_feature(name: str, f: pd.DataFrame, D: dict, s: np.ndarray, draws: int, seed: int, shift_min: int = SHIFT_MIN,
                  horizons: tuple[str, ...] = HZ, k_of: dict[str, int] = HORIZONS) -> pd.DataFrame:
    """One feature under the shift null — `_null_feature`'s statistics (directional pooled, relative) on the scored bars, the
    labels rolled by whole days over the panel trimmed to a whole number of days: the leading partial day is dropped (the panel
    starts where the collector's first bar is, inside F0's warm-up, never scored — asserted), so that a roll by k × 288 rows keeps
    every row's time of day, the wrapped rows included. The feature stays in place. `k_of`: bars per horizon (HORIZONS unless R67's holds are read)."""
    idx = f.index
    n0 = len(idx) % PER_DAY
    assert not s[:n0].any(), "a scored bar inside the panel's leading partial day"
    sn, sidx = s[n0:], idx[n0:][s[n0:]]
    n = len(idx) - n0
    fs = f.iloc[n0:][sn]
    day1 = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    dayc = np.repeat(day1, fs.shape[1])
    fv = _pair_rank(fs).to_numpy().ravel()
    Z = {h: np.clip(D["z"][h].to_numpy()[n0:], -Z_CLIP, Z_CLIP) for h in horizons}
    Zr = {h: D["zres"][h].to_numpy()[n0:] for h in horizons}
    rows = []
    for draw, nd in enumerate(shifts(n // PER_DAY, draws, seed, shift_min)):
        for h in horizons:
            zf = np.roll(Z[h], int(nd) * PER_DAY, axis=0)[sn]
            zr = np.roll(Zr[h], int(nd) * PER_DAY, axis=0)[sn]
            series = {"directional": _ic_pooled(fv, zf.ravel(), dayc),
                      "relative": _ic_xs(fs, pd.DataFrame(zr, index=sidx, columns=fs.columns), day1)}
            for bet, ic in series.items():
                mean, se, _ = hac(ic, day_lags(k_of[h]))
                rows.append({"bet": bet, "horizon": h, "feature": name, "draw": draw, "shift_days": int(nd), "ic": mean, "t": mean / se if se else np.nan})
    return pd.DataFrame(rows)


def family_p(null: pd.DataFrame, bet: str, feature: str, t_real: dict[str, float], horizons: tuple[str, ...] = HZ) -> tuple[dict[str, float], dict[str, float], dict]:
    """(p_fw per horizon, p_single per horizon, the null's bar): per draw the largest |t| over the feature's horizons."""
    nz = null[(null["draw"] > 0) & (null["bet"] == bet) & (null["feature"] == feature) & null["horizon"].isin(horizons)].dropna(subset=["t"])
    mx = nz.assign(a=nz["t"].abs()).groupby("draw")["a"].max()
    pf = {h: (1 + int((mx >= abs(t)).sum())) / (len(mx) + 1) for h, t in t_real.items()}
    ps = {}
    for h, t in t_real.items():
        own = nz[nz["horizon"] == h]["t"].abs()
        ps[h] = (1 + int((own >= abs(t)).sum())) / (len(own) + 1)
    return pf, ps, {"bar_t_mean": float(mx.mean()), "bar_t_p95": float(mx.quantile(0.95)), "draws": int(len(mx))}


# ---- validity --------------------------------------------------------------------------------------------------------------------------
def reproduction(sc_raw: pd.DataFrame, null_raw: pd.DataFrame, saved: Path = SAVED, tol: float = TOL) -> dict:
    """The raw row against P2's saved screen: every bet × horizon's ic and t (`ic.parquet`), and the day-shuffle null's ic and t per
    draw (`noise_ic.parquet`, the draws this run made)."""
    if not (saved / "ic.parquet").exists() or not (saved / "noise_ic.parquet").exists():
        return {"status": "MISSING", "note": f"{saved}/ic.parquet or noise_ic.parquet not found"}
    key = ["bet", "horizon", "feature"]
    old = pd.read_parquet(saved / "ic.parquet")
    old = old[old["feature"] == RAW].set_index(key)
    new = sc_raw[sc_raw["feature"] == RAW].set_index(key)
    j = new[["ic", "t"]].join(old[["ic", "t"]], rsuffix="_p2", how="inner")
    diff = {c: float((j[c] - j[f"{c}_p2"]).abs().max()) if len(j) else np.nan for c in ("ic", "t")}
    oldn = pd.read_parquet(saved / "noise_ic.parquet")
    oldn = oldn[(oldn["feature"] == RAW) & (oldn["draw"] > 0)].set_index([*key, "draw"])
    newn = null_raw[null_raw["draw"] > 0].set_index([*key, "draw"])
    jn = newn[["ic", "t"]].join(oldn[["ic", "t"]], rsuffix="_p2", how="inner").dropna()
    diff |= {f"null_{c}": float((jn[c] - jn[f"{c}_p2"]).abs().max()) if len(jn) else np.nan for c in ("ic", "t")}
    ok = len(j) == len(old) > 0 and len(jn) == len(newn.dropna()) > 0 and all(np.isfinite(v) and v <= tol for v in diff.values())
    return {"status": "PASS" if ok else "FAIL", "rows_compared": int(len(j)), "rows_p2": int(len(old)), "null_rows_compared": int(len(jn)),
            "null_rows_this_run": int(len(newn.dropna())), "max_abs_diff": diff}


def reproduction_r33(sc_twelve: pd.DataFrame, saved: Path = OUT_DIR, tol: float = TOL) -> dict:
    """R34's validity (1): the frame is R33's — the three features' screen rows on the twelve, computed in this run without nulls,
    against R33's saved `screen.parquet` (ic, t on every bet × horizon × feature)."""
    if not (saved / "screen.parquet").exists():
        return {"status": "MISSING", "note": f"{saved}/screen.parquet not found"}
    key = ["bet", "horizon", "feature"]
    old = pd.read_parquet(saved / "screen.parquet").set_index(key)
    new = sc_twelve.set_index(key)
    j = new[["ic", "t"]].join(old[["ic", "t"]], rsuffix="_r33", how="inner").dropna()
    diff = {c: float((j[c] - j[f"{c}_r33"]).abs().max()) if len(j) else np.nan for c in ("ic", "t")}
    ok = len(j) == len(old.dropna(subset=["ic", "t"])) > 0 and all(np.isfinite(v) and v <= tol for v in diff.values())
    return {"status": "PASS" if ok else "FAIL", "rows_compared": int(len(j)), "rows_r33": int(len(old)), "max_abs_diff": diff}


def decomposition(F: dict[str, pd.DataFrame], s: np.ndarray) -> dict:
    """raw = lvl30 + dm on every scored cell where both exist; the coverage of each feature on the scored cells."""
    both = F[LVL][s].notna() & F[DM][s].notna()
    gap = float((F[RAW][s] - F[LVL][s] - F[DM][s]).abs().where(both).max().max()) if both.any().any() else np.nan
    cov = {k: float(v[s].notna().to_numpy().mean()) for k, v in F.items()}
    by_name = {c: round(float(F[DM][s][c].notna().mean()), 4) for c in F[DM].columns}
    return {"status": "PASS" if np.isfinite(gap) and gap <= 1e-9 else "FAIL", "max_abs_gap": gap, "cells_with_both": int(both.to_numpy().sum()), "coverage": cov,
            "coverage_by_name": by_name, "names_under_half": [c for c, v in by_name.items() if v < 0.5]}


# ---- the verdict ---------------------------------------------------------------------------------------------------------------------
def verdict(ic: float, se: float, p_family: float, same_sign_folds: bool, bar: float) -> str:
    if p_family <= 0.05 and same_sign_folds and abs(ic) >= bar:
        return "CLEARS" if ic * SIGN > 0 else "CLEARS WITH THE OPPOSITE SIGN"
    if abs(ic) + 1.96 * se < bar:
        return "CLOSED"
    return "NOT DETECTABLE"


def fold_ics(daily: pd.DataFrame, fold_names=folds.EXPLORATION, k_of: dict[str, int] = HORIZONS) -> pd.DataFrame:
    """The HAC mean of the daily IC series inside each fold, per (bet, horizon, feature). `k_of`: bars per horizon (R67 adds holds)."""
    rows = []
    for (bet, h, name), g in daily.groupby(["bet", "horizon", "feature"], sort=False):
        d = pd.DatetimeIndex(g["day"])
        r = {"bet": bet, "horizon": h, "feature": name}
        for f in fold_names:
            a, b = folds.bounds(f)
            m = np.asarray((d >= a) & (d < b))
            r[f"ic_{f}"] = hac(g["ic"].to_numpy()[m], day_lags(k_of[h]))[0] if m.any() else np.nan
        vals = [r[f"ic_{f}"] for f in fold_names]
        r["folds_same_sign"] = bool(all(np.isfinite(v) for v in vals) and len({np.sign(v) for v in vals}) == 1)
        rows.append(r)
    return pd.DataFrame(rows)


def variance_share(F: dict[str, pd.DataFrame], s: np.ndarray) -> pd.DataFrame:
    """Per pair on the scored cells: the sd of the raw, the slow and the fast part — how much of the imbalance moves within a month."""
    rows = []
    for c in F[RAW].columns:
        both = F[LVL][s][c].notna() & F[DM][s][c].notna()
        r, l, d = (F[k][s][c][both] for k in (RAW, LVL, DM))
        rows.append({"symbol": c, "cells": int(both.sum()), "sd_raw": r.std(), "sd_lvl30": l.std(), "sd_dm": d.std(),
                     "fast_share_of_var": float(d.var() / r.var()) if r.var() else np.nan, "mean_raw": r.mean()})
    return pd.DataFrame(rows)


def taker_bar(D: dict, ct: pd.DataFrame, h: str) -> float:
    """P2's #7 `ic_needed_taker` on the scored cells that have a taker cost: the mean round trip over Z_TOP × 1.2533 × the mean |move|
    (`ceiling.move_vs_cost`'s formula, without requiring a maker cost on the cell — the cost proxy has none)."""
    s = D["scored"]
    a, t = D["fwd"][h][s].abs().to_numpy(), ct[s].to_numpy()
    ok = ~np.isnan(a) & ~np.isnan(t)
    return float(t[ok].mean() / (ceiling.Z_TOP * 1.2533 * a[ok].mean())) if ok.any() else np.nan


# ---- the run ----------------------------------------------------------------------------------------------------------------------------
def frame(symbols: list[str]) -> tuple[dict, dict, dict[str, pd.DataFrame]]:
    """P2's panel and derived labels on `symbols` (names the collector never recorded come from the archive klines), and the three
    book frames on its index."""
    P = ceiling.panel(symbols)
    D = ceiling.derive(P)
    F = features_depth(D["lr"].index, list(D["lr"].columns), ceiling.END)
    return P, D, F


def run(taker_bps: float, maker_bps: float, fee_source: str, symbols: list[str], draws: int = DRAWS, seed: int = 0,
        shift_min: int = SHIFT_MIN, saved: Path = SAVED, jobs: int = 1, universe: str | None = None, twelve: list[str] | None = None,
        saved_r33: Path = OUT_DIR) -> str:
    """The twelve (universe None): R33 — validity against P2's saved screen, the bar P2's #7 recomputed. A breadth read (R34,
    `universe` set, e.g. "new"): the same screen on `symbols`; validity (1) = this run's rows on `twelve` (no nulls) against R33's
    saved screen; the gate's size bar = R33_BAR as a number, the universe's own taker bar from the cost proxy reported beside."""
    from joblib import Parallel, delayed
    out_md, out_dir = out_paths(universe)
    out_dir.mkdir(parents=True, exist_ok=True)
    reg = "R34" if universe else "R33"
    print("panel…", flush=True)
    P, D, F = frame(symbols)
    idx, cols, s = D["lr"].index, list(D["lr"].columns), D["scored"]
    sidx = idx[s]
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}

    # validity FIRST: the raw row and its null against P2's saved screen (the twelve) — or R33's rows reproduced on the twelve (a breadth
    # read); raw = lvl + dm; the panel
    validity = {"registration": reg, "universe": universe or "the twelve", "folds": list(folds.EXPLORATION), "scored_bars": int(s.sum()),
                "days": int(len(np.unique(sidx.floor("D")))), "pairs": cols, "first": str(sidx[0]), "last": str(sidx[-1]), "draws": draws,
                "seed": seed, "shift_min": shift_min}
    if universe is None:
        print(f"validity: the raw row, its {draws} day shuffles, against {saved}/…", flush=True)
        sc_raw, daily_raw = ceiling.ic_screen(D, {RAW: F[RAW]}, set())
        null_raw = _null_feature(RAW, F[RAW][s], Zs, Zr, draws, seed)
        validity["reproduction"] = reproduction(sc_raw, null_raw, saved)
    else:
        print(f"validity: R33's rows on the twelve, this run, against {saved_r33}/screen.parquet…", flush=True)
        _, D12, F12 = frame(list(twelve or []))
        sc12, _ = ceiling.ic_screen(D12, F12, set())
        validity["reproduction"] = reproduction_r33(sc12, saved_r33)
    validity["decomposition"] = decomposition(F, s)
    validity["status"] = "PASS" if validity["reproduction"]["status"] == "PASS" and validity["decomposition"]["status"] == "PASS" else "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    who = "the twelve" if universe is None else f"the {len(cols)} names of `{universe}`"
    head = [f"# {reg} — the demeaned ±1 % book imbalance, a ceiling screen on {who} (`ft2 ceiling --target pairs --family depth{' --universe ' + universe if universe else ''}`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed), P2's cells; every source cut at {ceiling.END:%Y-%m-%d}. Scored bars "
            f"{sidx[0]:%Y-%m-%d} → {sidx[-1]:%Y-%m-%d} ({int(s.sum()):,} × {len(cols)} pairs). Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity['status']}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]
    if validity["status"] != "PASS":
        out_md.write_text("".join(head + ["\n**The read is VOID: nothing of the registered feature was computed.**\n"]))
        print(f"validity {validity['status']} — the read is void; wrote {out_md}", flush=True)
        raise SystemExit(2)

    # the registered feature and the slow part: the screen, both nulls
    if universe is None:
        print("screen: the slow part and the fast part…", flush=True)
        sc_new, daily_new = ceiling.ic_screen(D, {LVL: F[LVL], DM: F[DM]}, set())
        sc, daily = pd.concat([sc_raw, sc_new], ignore_index=True), pd.concat([daily_raw, daily_new], ignore_index=True)
        print(f"nulls: {draws} day shuffles (P2's) and {draws} whole-day shifts (R6's) on three features…", flush=True)
        null_shuffle = pd.concat([null_raw, *Parallel(n_jobs=jobs)(delayed(_null_feature)(k, F[k][s], Zs, Zr, draws, seed) for k in (LVL, DM))], ignore_index=True)
    else:
        print("screen: the raw, the slow part and the fast part…", flush=True)
        sc, daily = ceiling.ic_screen(D, F, set())
        print(f"nulls: {draws} day shuffles (P2's) and {draws} whole-day shifts (R6's) on three features…", flush=True)
        null_shuffle = pd.concat(Parallel(n_jobs=jobs)(delayed(_null_feature)(k, F[k][s], Zs, Zr, draws, seed) for k in (RAW, LVL, DM)), ignore_index=True)
    null_shift = pd.concat(Parallel(n_jobs=jobs)(delayed(shift_feature)(k, F[k], D, s, draws, seed, shift_min) for k in (RAW, LVL, DM)), ignore_index=True)

    # the bar: P2's #7, recomputed on these names (a name without a tape takes the cost proxy: a taker bar only — P2's routine needs
    # both costs on a cell, so the taker-only bar is computed here with its formula on the cells that have a taker cost)
    print("#7 the bar…", flush=True)
    ct, cm = ceiling.bar_cost(idx, cols, taker_bps, maker_bps)
    mv, _ = ceiling.move_vs_cost(D, ct, cm)
    bars = mv[mv["bet"] == BET].set_index("horizon")
    if universe is not None:
        bars = bars.assign(ic_needed_taker=[taker_bar(D, ct, h) for h in bars.index])
    saved_mv = pd.read_parquet(saved / "move_vs_cost.parquet") if universe is None and (saved / "move_vs_cost.parquet").exists() else None

    # the rows
    fi = fold_ics(daily)
    rows = sc.merge(fi, on=["bet", "horizon", "feature"], how="left")
    rows["ic_se"] = rows["ic_mde"] / MDE_K
    rows["bar_maker"] = rows["horizon"].map(bars["ic_needed_maker"])
    rows["bar_taker"] = rows["horizon"].map(bars["ic_needed_taker"])
    rows["bar_gate"] = rows["bar_maker"] if universe is None else np.where(rows["horizon"] == PRIMARY, R33_BAR, np.nan)   # R34: the number, at 1d
    fam = {}
    for k in (RAW, LVL, DM):
        for bet in ("directional", "relative"):
            sub = rows[(rows["feature"] == k) & (rows["bet"] == bet) & rows["horizon"].isin(HZ)]
            t_real = dict(zip(sub["horizon"], sub["t"]))
            pf1, ps1, b1 = family_p(null_shuffle, bet, k, t_real)
            pf2, ps2, b2 = family_p(null_shift, bet, k, t_real)
            fam[k, bet] = {"shuffle": b1, "shift": b2}
            for i, h in zip(sub.index, sub["horizon"]):
                rows.loc[i, ["p_single_shuffle", "p_fw_shuffle", "p_single_shift", "p_fw_shift"]] = [ps1[h], pf1[h], ps2[h], pf2[h]]
    rows["p_family"] = rows[["p_fw_shuffle", "p_fw_shift"]].max(axis=1)
    rows["verdict"] = ""
    gate = (rows["feature"] == DM) & (rows["bet"] == BET) & rows["horizon"].isin(HZ)
    rows.loc[gate, "verdict"] = [verdict(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), r["bar_gate"]) for _, r in rows[gate].iterrows()]
    rows.loc[gate & (rows["horizon"] != PRIMARY), "verdict"] = rows.loc[gate & (rows["horizon"] != PRIMARY), "verdict"] + " (reported, not gated)"
    rows.loc[(rows["feature"] == LVL), "verdict"] = "described (the slow part)"
    rows.loc[(rows["feature"] == RAW), "verdict"] = "validity (P2's row)" if universe is None else "described (the raw imbalance)"
    vs = variance_share(F, s)

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    mv.to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    vs.to_parquet(out_dir / "variance_share.parquet", index=False)

    g = rows[gate & (rows["horizon"] == PRIMARY)].iloc[0]
    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_fw_shuffle", "p_single_shift", "p_fw_shift", "p_family", "bar_gate", "bar_maker", "bar_taker", "verdict"]
    bar_txt = (f"the bar {g['bar_maker']:.4f} maker / {g['bar_taker']:.4f} taker" if universe is None else
               f"the gate's bar {R33_BAR:.4f} (R33's maker bar on the twelve, a number); these names' own taker bar {g['bar_taker']:.4f} from the cost proxy (no maker measurement)")
    md = head + [
        f"\n## Verdict by {reg}'s gate — `{DM}`, {BET}, {PRIMARY}: **{g['verdict']}**\n",
        f"\nIC {g['ic']:+.4f} (t {g['t']:+.2f}, se {g['ic_se']:.4f}, MDE {g['ic_mde']:.4f}); p_family {g['p_family']:.3f} (day shuffles {g['p_fw_shuffle']:.3f}, "
        f"whole-day shifts {g['p_fw_shift']:.3f}; single {g['p_single_shuffle']:.3f} / {g['p_single_shift']:.3f}); F1 {g['ic_F1']:+.4f}, F2 {g['ic_F2']:+.4f} "
        f"({'same sign' if g['folds_same_sign'] else 'signs differ'}); months the same sign {g['months_same_sign']:.2f}; {bar_txt}; the registered sign "
        f"{'negative' if SIGN < 0 else 'positive'}.\n",
        "\n## The registered feature, the slow part and the raw imbalance — directional and relative, the family's horizons\n",
        "`p_fw_*` = the share of a null's draws whose largest |t| over the feature's three horizons is at or above the real |t|; `p_family` = the larger of the "
        "two nulls'. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. Bars: P2's #7 `ic_needed` at the horizon, recomputed on these names; "
        "`bar_gate` is what the verdict compares |IC| with.\n",
        show(rows[rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])][cols_show]), "\n",
        "\n## The vol bet and 15m (reported)\n", show(rows[~(rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"]))][cols_show[:9] + ["verdict"]]), "\n",
        "\n## The nulls' bars (largest |t| over the three horizons, per draw)\n", "```\n", json.dumps({f"{k} / {b}": v for (k, b), v in fam.items()}, indent=1), "\n```\n",
        "\n## How much of the imbalance moves within a month — per pair, scored cells\n", show(vs), "\n",
        "\n## #7 the bar, recomputed (directional)\n", show(mv[mv["bet"] == BET][["horizon", "cells", "abs_move_mean", "taker_rt", "maker_rt", "ic_needed_taker", "ic_needed_maker"]]), "\n"]
    if saved_mv is not None:
        sm = saved_mv[(saved_mv["bet"] == BET) & (saved_mv["horizon"] == PRIMARY)].iloc[0]
        md += [f"\nP2's saved bar at {PRIMARY}: maker {sm['ic_needed_maker']:.4f}, taker {sm['ic_needed_taker']:.4f} (this run: {bars.loc[PRIMARY, 'ic_needed_maker']:.4f} / {bars.loc[PRIMARY, 'ic_needed_taker']:.4f}).\n"]
    out_md.write_text("".join(md))
    print(f"{DM} {BET} {PRIMARY}: {g['verdict']}; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)
