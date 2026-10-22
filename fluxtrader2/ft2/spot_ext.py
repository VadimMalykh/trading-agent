"""R68 (P8 decision BI1, 2026-10-22, docs/PLAN.md §8) — Binance's own spot flow per member at one day: R62's screen on the screener's
F1+F2 members with the SPOT source (`data/spot_1h.parquet`, DATA.md `spot_1h`).

The registered features, on the hourly grid of `ts_known` and then P2's 5m panel through R62's `to_panel` (MARGIN one 5m bar, STALE 2 h):
  spot_tb24_dev   the trailing-day taker-buy share (Σ taker-buy quote over Σ quote of the last 24 hourly bars, ≥ 20 present) minus its
                  trailing 30-day mean over its trailing 30-day sd (cb_ext's DEV form on the hourly grid: MONTH 720, MIN_MONTH 360);
  spot_sr24_dev   the log of the spot quote volume over the perpetual's (Σ volume × close over the 5m bars of the hour), both summed
                  over the same 24 bars, in the same DEV form.
The family = the two features × 1d on the RELATIVE bet (two cells); both signs fixed POSITIVE (R68_SIGN); both nulls at DRAWS on each
feature at 1h / 4h / 1d; p_family = the larger of the two nulls' family-wise p over the two 1d cells; the gate R62's (`verdict_r62`:
p_family ≤ 0.05, the sign, both folds, |IC| ≥ BAR_TWELVE 0.0159). Described beside, no nulls, no verdict: the hourly forms `spot_tb_dev`
/ `spot_sr_dev`, the trailing-day levels `spot_tb24` / `spot_sr24`, the two features' correlation on the scored cells.

Validity, read first in the registered order, void (exit 2) on any FAIL: (1) the lists' md5 and the frozen list's self-consistency
(`r68` = hours > 0 and the stamp share ≤ R68_SHARE_CUT); (2) R62's saved screen reproduced through `cb_ext.frames` on the Coinbase
source (no nulls); (3) N_CHECK scored cells of kept names recomputed straight from the spot rows and the panel's volume by an
independent numpy construction (the used hour, the 24-bar sums, the month's mean and sd) to TOL_HAND; (4) known-at — no cell read early,
none older than STALE; (5) membership and block coverage (R62's `block_coverage`); (6) R60's saved bar within BAR_TOL of 0.0159;
(7) the nulls' admissibility (the shifts ≥ 60 > 31, the shuffle gap ≥ 8).
The construction of the features is the audit's `spot.grids` (the same code the audit measured); R62's helpers are called, none edited.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cb_ext as cx
from . import ceiling, coinbase as cb, folds, spot
from .book_ext import SHIFT_MIN, fold_ics, shift_feature, taker_bar
from .cb_ext import BAR_TOL, BAR_TWELVE, BET, BLOCK_MIN_NAMES, HZ, MARGIN, MEMBERS_SLICES, MEMBERS_START, MIN_MONTH, MONTH, N_CHECK, PRIMARY, STALE, TOL
from .ceiling import HORIZONS, MDE_K, NULL_GAP, Z_CLIP, _null_feature

TB24, SR24 = "spot_tb24_dev", "spot_sr24_dev"            # registered
TB, SR = "spot_tb_dev", "spot_sr_dev"                    # described: the hourly forms
TB24L, SR24L = "spot_tb24", "spot_sr24"                  # described: the trailing-day levels
REGISTERED = (TB24, SR24)
GRID_OF = {TB24: "tb24_dev", SR24: "sr24_dev", TB: "tb_dev", SR: "sr_dev", TB24L: "tb24", SR24L: "sr24"}
FAMILY_CELLS = [(TB24, PRIMARY), (SR24, PRIMARY)]
R68_SIGN = +1.0                                          # spot buying continues; unlevered participation rising continues
R68_CSV = Path(__file__).with_name("spot_members_r68.csv")
R68_SHARE_CUT = 0.10                                     # the stamp check: |spot − perp| > 50 bps on more than this share of a name's hours → dropped
DAY, MIN_DAY = spot.DAY, spot.MIN_DAY
TOL_HAND = 1e-9
GAP_MIN = 1 + 7                                          # the day shuffles' gap must cover the 1d label and the 1w lookback
SHIFT_FLOOR = 30 + 1                                     # the whole-day shifts must exceed the trailing month + the 1d label
OUT_MD = Path("output/ceiling_spot_members.md")
OUT_DIR = Path("output/ceiling_spot_members")
HOUR = pd.Timedelta("1h")


# ---- the list, the frames ------------------------------------------------------------------------------------------------------------
def r68_list(path: Path | str = R68_CSV, cut: float = R68_SHARE_CUT) -> dict:
    raw = Path(path).read_bytes()
    L = pd.read_csv(path)
    share = pd.to_numeric(L["share_abs_basis_gt_50"], errors="coerce")
    rule = ((L["hours"] > 0) & (share <= cut)).fillna(False)
    kept = list(L.loc[L["r68"].astype(bool), "symbol"])
    return {"kept": kept, "md5": hashlib.md5(raw).hexdigest(), "n_kept": len(kept), "n_rows": int(len(L)), "consistent": bool((rule == L["r68"].astype(bool)).all()),
            "spot_symbol": dict(zip(L["symbol"], L["spot_symbol"].fillna(""))), "with_series": int((L["hours"] > 0).sum())}


def grids_spot(names: list[str], path: Path | str, slices: tuple[str, ...], start: pd.Timestamp, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """The audit's grids on the kept names over (start − 2 h, end]: the hourly frames keyed by GRID_OF's values; and the spot rows read."""
    d = spot.load(path)
    d = d[d["symbol"].isin(names)]
    G = spot.grids(d, start - 2 * HOUR, end, slices)
    return G, d


def frames_spot(L: dict, path: Path | str, slices: tuple[str, ...], members_csv: Path | str | None, start: pd.Timestamp = MEMBERS_START,
                end: pd.Timestamp | None = None) -> dict:
    """R62's members' frame on the spot source: the panel on the kept names, the six 5m frames masked to the kept names and to membership,
    the used hours per registered feature, the hourly grids, the membership mask and rows, the raw rows and the panel's dv."""
    kept = L["kept"]
    end = end or ceiling.END
    P = cx.member_panel(kept, start, end, slices)
    D = ceiling.derive(P)
    idx, cols, s = D["lr"].index, list(D["lr"].columns), D["scored"]
    G, d = grids_spot(kept, path, slices, start, end)
    F_all = {k: cx.to_panel(G[g], idx, cols) for k, g in GRID_OF.items()}
    M, m = cx.membership(idx, cols, members_csv)
    F = cx.mask_members(cx.restrict(F_all, kept), M)
    U = {k: cx.used_hours(G[GRID_OF[k]], idx, cols) for k in REGISTERED}
    return {"kept": kept, "P": P, "D": D, "idx": idx, "cols": cols, "s": s, "F_all": F_all, "F": F, "U": U, "G": G, "M": M, "m": m, "rows": d}


# ---- validity (3): the features by hand ----------------------------------------------------------------------------------------------
def _win_sum(x: np.ndarray, k: int, min_n: int) -> np.ndarray:
    """The sum of the last k values (NaN skipped) at each position, NaN where fewer than min_n are present — by cumulative sums."""
    v = np.where(np.isnan(x), 0.0, x)
    n = (~np.isnan(x)).astype(float)
    cv, cn = np.concatenate([[0.0], np.cumsum(v)]), np.concatenate([[0.0], np.cumsum(n)])
    i = np.arange(len(x))
    lo = np.maximum(i + 1 - k, 0)
    sv, sn = cv[i + 1] - cv[lo], cn[i + 1] - cn[lo]
    return np.where(sn >= min_n, sv, np.nan)


def _win_mean_sd(x: np.ndarray, k: int, min_n: int) -> tuple[np.ndarray, np.ndarray]:
    v = np.where(np.isnan(x), 0.0, x)
    n = (~np.isnan(x)).astype(float)
    cv, cn, cq = (np.concatenate([[0.0], np.cumsum(a)]) for a in (v, n, v * v))
    i = np.arange(len(x))
    lo = np.maximum(i + 1 - k, 0)
    sv, sn, sq = cv[i + 1] - cv[lo], cn[i + 1] - cn[lo], cq[i + 1] - cq[lo]
    ok = sn >= min_n
    mean = np.where(ok, sv / np.where(sn > 0, sn, 1), np.nan)
    var = np.where(ok & (sn > 1), (sq - sv * sv / np.where(sn > 0, sn, 1)) / np.where(sn > 1, sn - 1, 1), np.nan)
    return mean, np.sqrt(np.maximum(var, 0.0))


def perp_hour_volumes(syms: list[str], slices: tuple[str, ...], grid: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Per name the perpetual's quote volume of the hour ending at each grid stamp, read straight from the candle slices (the later
    slice's bar winning): Σ volume × close over the 5m bars whose end lies in (stamp − 1 h, stamp]. One read of the slices for all names."""
    from . import data
    parts = []
    for sl in slices:
        if (data.PROC / f"{sl}.parquet").exists() or (data.PROC / sl).is_dir():
            try:
                parts.append(data.load(sl, columns=["symbol", "open_time", "close", "volume"], symbols=syms))
            except ValueError:
                pass
    if not parts:
        return {c: np.full(len(grid), np.nan) for c in syms}
    c = pd.concat(parts, ignore_index=True)
    c["symbol"] = c["symbol"].astype(str)
    c = c.drop_duplicates(["symbol", "open_time"], keep="last")
    ot = pd.DatetimeIndex(c["open_time"])
    c["hour_end"] = ((ot.tz_localize("UTC") if ot.tz is None else ot.tz_convert("UTC")) + ceiling.BAR).ceil("h")
    c["dv"] = c["volume"] * c["close"]
    g = c.groupby(["symbol", "hour_end"])["dv"].sum(min_count=1)
    return {sym: (g.loc[sym].reindex(grid).to_numpy(dtype=float) if sym in g.index.get_level_values(0) else np.full(len(grid), np.nan)) for sym in syms}


def hand_series(rows: pd.DataFrame, pvh: np.ndarray, grid: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """One name's two registered features on `grid`, built from its spot rows (qv, tbq by ts_known) and the perpetual's hourly quote
    volume with cumulative sums — not pandas' rolling. Also tb24 / sr24 (the levels)."""
    r = rows.set_index("ts_known")
    qv = r["quote_volume"].reindex(grid).to_numpy(dtype=float)
    tbq = r["taker_buy_quote_volume"].reindex(grid).to_numpy(dtype=float)
    qv24, tbq24, pv24 = _win_sum(qv, DAY, MIN_DAY), _win_sum(tbq, DAY, MIN_DAY), _win_sum(pvh, DAY, MIN_DAY)
    with np.errstate(divide="ignore", invalid="ignore"):
        tb24 = np.where(qv24 > 0, tbq24 / qv24, np.nan)
        ratio = np.where(pv24 > 0, qv24 / pv24, np.nan)
        sr24 = np.where(ratio > 0, np.log(ratio), np.nan)
        out = {}
        for k, x in ((TB24, tb24), (SR24, sr24)):
            m, sd = _win_mean_sd(x, MONTH, MIN_MONTH)
            out[k] = (x - m) / sd
    return out | {TB24L: tb24, SR24L: sr24}


def hand_check(fr: dict, n_check: int = N_CHECK, seed: int = 0, tol: float = TOL_HAND, slices: tuple[str, ...] = MEMBERS_SLICES) -> dict:
    """Validity (3): `n_check` random scored MEMBER cells of kept names — the frame's value of each registered feature equals the hand
    series' value at the used hour (the latest hour ≤ t − MARGIN with a value, at most STALE hours before it; NaN = NaN when none)."""
    F, U, s, idx, kept, G, M = fr["F"], fr["U"], fr["s"], fr["idx"], fr["kept"], fr["G"], fr["M"]
    grid = G["tb24_dev"].index
    sidx = idx[s]
    cols = [c for c in kept if c in F[TB24].columns]
    rng = np.random.default_rng(seed)
    Ms = M[s][cols].to_numpy()
    cand_i, cand_j = rng.integers(0, len(sidx), 4 * n_check), rng.integers(0, len(cols), 4 * n_check)
    on = Ms[cand_i, cand_j]
    ii, jj = cand_i[on][:n_check], cand_j[on][:n_check]
    g0 = grid[0]
    need = sorted({cols[j] for j in jj})
    pv = perp_hour_volumes(need, slices, grid)
    series, worst, n_nan, n_val = {}, 0.0, 0, 0
    for i, j in zip(ii, jj):
        c, t = cols[j], sidx[i]
        if c not in series:
            series[c] = hand_series(fr["rows"][fr["rows"]["symbol"] == c], pv[c], grid)
        th = int(((t - MARGIN).floor("h") - g0) / HOUR)                      # the latest grid position whose bar may be read at t
        for k in REGISTERED:
            got = float(F[k][c].loc[t])
            x = series[c][k]
            cand = [p for p in range(th, max(th - STALE, 0) - 1, -1) if 0 <= p < len(x) and np.isfinite(x[p])]
            exp = x[cand[0]] if cand else np.nan
            u = float(U[k][c].loc[t])
            if cand:
                exp_u = float((grid[cand[0]] - pd.Timestamp(0, tz="UTC")) / HOUR)
                worst = max(worst, abs(u - exp_u) if np.isfinite(u) else np.inf)
            else:
                worst = max(worst, 0.0 if np.isnan(u) else np.inf)
            if np.isnan(got) and np.isnan(exp):
                n_nan += 1
                continue
            n_val += 1
            worst = max(worst, abs(got - exp) if np.isfinite(got) and np.isfinite(exp) else np.inf)
    return {"status": "PASS" if worst <= tol and len(ii) == n_check else "FAIL", "recomputed": int(len(ii)), "cells_with_a_value": n_val, "cells_nan_both": n_nan, "max_abs_diff": float(worst),
            "names_checked": len(series), "tol": tol}


def known_at_spot(fr: dict) -> dict:
    """Validity (4): on every scored cell with a value the hourly bar used has ts_known + MARGIN ≤ t and is at most STALE hours old."""
    F, U, s, idx, kept = fr["F"], fr["U"], fr["s"], fr["idx"], fr["kept"]
    sidx = idx[s]
    th = ((sidx - MARGIN).asi8 // 3_600_000_000_000).astype(float)
    out = {"status": "PASS"}
    for k in REGISTERED:
        cols = [c for c in kept if c in F[k].columns]
        Us = U[k][s][cols].to_numpy()
        has = F[k][s][cols].notna().to_numpy()
        late = has & ~(Us <= th[:, None])
        stale = has & (th[:, None] - Us > STALE)
        out[k] = {"cells_with_a_value": int(has.sum()), "cells_read_too_early": int(late.sum()), "cells_older_than_stale": int(stale.sum())}
        if late.any() or stale.any():
            out["status"] = "FAIL"
    return out | {"margin": str(MARGIN), "stale_hours": STALE}


# ---- the run ------------------------------------------------------------------------------------------------------------------------
def run_r68(taker_bps: float, maker_bps: float, fee_source: str, draws: int = ceiling.DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN, jobs: int = 1,
            path: Path | str = spot.PARQUET, cb_path: Path | str = cb.MEMBERS_PARQUET, r62: Path = cx.MEMBERS_OUT_DIR, csv: Path | str = R68_CSV,
            cb_csv: Path | str = cx.R62_CSV, members_csv: Path | str | None = None, slices: tuple[str, ...] = MEMBERS_SLICES, mult: dict[str, float] | None = None,
            n_check: int = N_CHECK, start: pd.Timestamp = MEMBERS_START, end: pd.Timestamp | None = None, block_min_names: int = BLOCK_MIN_NAMES,
            r60: Path = cx.OUT_DIR, gap: int = NULL_GAP, shift_floor: int = SHIFT_FLOOR, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    from joblib import Parallel, delayed
    from .universe import MEMBERS_CSV
    out_dir.mkdir(parents=True, exist_ok=True)
    end = end or ceiling.END
    L = r68_list(csv)
    kept = L["kept"]
    mcsv = Path(members_csv or MEMBERS_CSV)
    Lcb = cx.r62_list(cb_csv)
    validity = {"registration": "R68", "folds": list(folds.EXPLORATION), "draws": draws, "seed": seed, "shift_min": shift_min, "gap": gap, "source": str(path),
                "lists": {"universe": {"path": str(csv), "md5": L["md5"], "n_kept": L["n_kept"], "n_rows": L["n_rows"], "with_series": L["with_series"], "consistent": L["consistent"]},
                          "members": {"path": str(mcsv), "md5": hashlib.md5(mcsv.read_bytes()).hexdigest()},
                          "r62": {"path": str(cb_csv), "md5": Lcb["md5"], "n_kept": Lcb["n_kept"]},
                          "status": "PASS" if L["consistent"] and L["n_kept"] > 0 else "FAIL"},
                "gate": {"bar_twelve": BAR_TWELVE, "sign": R68_SIGN, "family": FAMILY_CELLS, "p_max": 0.05}}
    # (7) the nulls' admissibility, known before anything is read
    validity["nulls"] = {"status": "PASS" if shift_min > shift_floor and gap >= GAP_MIN else "FAIL", "shift_min": shift_min, "shift_floor": shift_floor, "gap": gap, "gap_min": GAP_MIN}
    if validity["lists"]["status"] != "PASS" or validity["nulls"]["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # (2) R62's frame reproduced through cb_ext.frames on the Coinbase source, no nulls; (6) R60's saved bar
    print(f"validity (2): R62's frame on the Coinbase members — the six features against {r62}/screen.parquet…", flush=True)
    frc = cx.frames(Lcb, "coinbase", cb_path, slices, mult, members_csv, start, end)
    sc_cb, _ = ceiling.ic_screen(frc["D"], cx.screen_frames_r62(frc), set())
    validity["reproduction"] = cx.reproduction_r62(sc_cb, r62)
    del frc, sc_cb
    saved_mv = pd.read_parquet(r60 / "move_vs_cost.parquet") if (r60 / "move_vs_cost.parquet").exists() else None
    if saved_mv is not None:
        sm = saved_mv[(saved_mv["bet"] == BET) & (saved_mv["horizon"] == PRIMARY)]
        validity["gate"]["bar_r60_saved"] = float(sm["ic_needed_maker"].iloc[0]) if len(sm) else np.nan
        validity["gate"]["bar_status"] = "PASS" if len(sm) and abs(float(sm["ic_needed_maker"].iloc[0]) - BAR_TWELVE) <= BAR_TOL else "FAIL"
    else:
        validity["gate"]["bar_status"] = "MISSING"
    if validity["reproduction"]["status"] != "PASS" or validity["gate"]["bar_status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # the spot frame; (3) by hand, (4) known-at, (5) membership and coverage — before any IC
    print("the spot members' panel and frames…", flush=True)
    fr = frames_spot(L, path, slices, members_csv, start, end)
    D, idx, cols, s, F, M, m = fr["D"], fr["idx"], fr["cols"], fr["s"], fr["F"], fr["M"], fr["m"]
    sidx = idx[s]
    validity |= {"scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))), "names_in_panel": len(cols), "first": str(sidx[0]), "last": str(sidx[-1]),
                 "kept_in_panel": int(sum(c in cols for c in kept)), "kept_with_a_value": int(sum(F[TB24][s][c].notna().any() for c in kept if c in cols))}
    print("validity (3): the features by hand…", flush=True)
    validity["hand"] = hand_check(fr, n_check, seed, slices=slices)
    validity["known_at"] = known_at_spot(fr)
    off = {k: int((F[k].notna() & ~M).to_numpy().sum()) for k in REGISTERED}
    validity["membership"] = {"status": "PASS" if sum(off.values()) == 0 else "FAIL", "values_off_membership": off,
                              "values_on": {k: int(F[k][s].notna().to_numpy().sum()) for k in REGISTERED}}
    validity["coverage"], B = cx.block_coverage(F[TB24], s, m, kept, block_min_names)
    cov2, _ = cx.block_coverage(F[SR24], s, m, kept, block_min_names)
    validity["coverage_sr24"] = cov2
    both = F[TB24][s].notna() & F[SR24][s].notna()
    corr = float(pd.Series(F[TB24][s].to_numpy()[both.to_numpy()]).corr(pd.Series(F[SR24][s].to_numpy()[both.to_numpy()])))
    validity["features_corr_on_scored_cells"] = {"corr": corr, "cells": int(both.to_numpy().sum())}
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in ("lists", "nulls", "reproduction", "hand", "known_at", "membership", "coverage", "coverage_sr24")) and validity["gate"]["bar_status"] == "PASS" else "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    if validity["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    B.to_parquet(out_dir / "blocks.parquet", index=False)
    head = _head(validity, taker_bps, maker_bps, fee_source)

    # the screen: the two registered features; the hourly forms and the levels described
    print("screen: the two registered features; the hourly forms and the levels beside…", flush=True)
    sc, daily = ceiling.ic_screen(D, {k: F[k] for k in GRID_OF}, set())
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}
    print(f"nulls on {TB24} and {SR24}: {draws} day shuffles and {draws} whole-day shifts each…", flush=True)
    # memory: the first run (2026-10-22 14:14 UTC) was killed by the kernel at 15.9 GB — four loky workers each took a copy of the panel.
    # The raw inputs, the hourly grids, the used hours and the described frames are dropped first; the workers are THREADS sharing memory.
    desc = describe_names(fr)
    Freg = {k: F[k] for k in REGISTERED}
    del fr, F
    import gc
    gc.collect()
    jobs_ = [delayed(_null_feature)(k, Freg[k][s], Zs, Zr, draws, seed, gap=gap) for k in REGISTERED] + \
            [delayed(shift_feature)(k, Freg[k], D, s, draws, seed, shift_min) for k in REGISTERED]
    res = Parallel(n_jobs=min(jobs, 4) if jobs > 1 else 1, prefer="threads")(jobs_)
    null_shuffle, null_shift = pd.concat(res[:2], ignore_index=True), pd.concat(res[2:], ignore_index=True)

    print("the bars…", flush=True)
    ct, _ = ceiling.bar_cost(idx, cols, taker_bps, maker_bps)
    bars_taker = {h: taker_bar(D, ct, h) for h in HORIZONS}
    cost_cover = float(ct[s].notna().to_numpy().mean())

    rows = sc.merge(fold_ics(daily), on=["bet", "horizon", "feature"], how="left")
    rows["ic_se"] = rows["ic_mde"] / MDE_K
    rows["bar_maker_twelve"] = np.where(rows["horizon"] == PRIMARY, BAR_TWELVE, np.nan)
    rows["bar_taker_members"] = rows["horizon"].map(bars_taker)
    for c in ("p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift"):
        rows[c] = np.nan
    for i, r in rows.iterrows():
        if r["feature"] in REGISTERED and r["bet"] in ("directional", "relative") and r["horizon"] in HZ:
            rows.loc[i, "p_single_shuffle"] = cx.single_p(null_shuffle, r["bet"], r["feature"], r["horizon"], r["t"])
            rows.loc[i, "p_single_shift"] = cx.single_p(null_shift, r["bet"], r["feature"], r["horizon"], r["t"])
    fam_rows = rows[(rows["bet"] == BET) & rows["feature"].isin(REGISTERED) & (rows["horizon"] == PRIMARY)]
    t_real = {(r["feature"], r["horizon"]): r["t"] for _, r in fam_rows.iterrows()}
    pf1, b1 = cx.family_p(null_shuffle, FAMILY_CELLS, t_real)
    pf2, b2 = cx.family_p(null_shift, FAMILY_CELLS, t_real)
    for i, r in fam_rows.iterrows():
        rows.loc[i, ["p_fw_shuffle", "p_fw_shift"]] = [pf1[r["feature"], r["horizon"]], pf2[r["feature"], r["horizon"]]]
    rows["p_family"] = rows[["p_fw_shuffle", "p_fw_shift"]].max(axis=1)
    rows["verdict"] = ""
    for i, r in rows.loc[fam_rows.index].iterrows():
        rows.loc[i, "verdict"] = cx.verdict_r62(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), BAR_TWELVE, R68_SIGN)
    rep = rows["feature"].isin(REGISTERED) & (rows["horizon"] != PRIMARY) & rows["bet"].isin(["directional", "relative"]) & rows["horizon"].isin(HZ)
    rows.loc[rep, "verdict"] = "reported, not gated"
    words = {TB: "described (the HOURLY taker-buy share's deviation — R37's quantity on the spot book)", SR: "described (the HOURLY spot/perp ratio's deviation)",
             TB24L: "described (the trailing-day taker-buy share, the level)", SR24L: "described (the trailing-day spot/perp log ratio, the level)"}
    for f_, w in words.items():
        rows.loc[rows["feature"] == f_, "verdict"] = w
    bi = {k: cx.block_ics(daily, m, feature=k) for k in REGISTERED}

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    pd.DataFrame({"horizon": list(bars_taker), "ic_needed_taker_members": list(bars_taker.values()), "bar_maker_twelve": BAR_TWELVE, "cost_cover": cost_cover}).to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    desc.to_parquet(out_dir / "names.parquet", index=False)
    Bb = B.merge(bi[TB24].rename(columns={"ic": "ic_tb24", "se": "se_tb24", "days": "days_tb24"}), on="block", how="left").merge(bi[SR24].rename(columns={"ic": "ic_sr24", "se": "se_sr24", "days": "days_sr24"}), on="block", how="left")
    Bb.to_parquet(out_dir / "blocks.parquet", index=False)

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker_twelve", "bar_taker_members", "verdict"]
    md = head + [f"\n## Verdict by R68's gate — the two cells, {BET}, {PRIMARY}, on the kept members\n"]
    for k in REGISTERED:
        g = rows[(rows["feature"] == k) & (rows["bet"] == BET) & (rows["horizon"] == PRIMARY)].iloc[0]
        md.append(f"\n- **`{k}`: {g['verdict']}** — IC {g['ic']:+.4f} (t {g['t']:+.2f}, se {g['ic_se']:.4f}, MDE {g['ic_mde']:.4f}); p_family {g['p_family']:.3f} (day shuffles "
                  f"{g['p_fw_shuffle']:.3f}, whole-day shifts {g['p_fw_shift']:.3f}; single {g['p_single_shuffle']:.3f} / {g['p_single_shift']:.3f}); F1 {g['ic_F1']:+.4f}, F2 {g['ic_F2']:+.4f} "
                  f"({'same sign' if g['folds_same_sign'] else 'signs differ'}); months the same sign {g['months_same_sign']:.2f}; the interval [{g['ic'] - 1.96 * g['ic_se']:+.4f}, {g['ic'] + 1.96 * g['ic_se']:+.4f}] against the bar {BAR_TWELVE}.\n")
    md.append(f"\nThe gate's bar {BAR_TWELVE} (the twelve's maker bar at {PRIMARY}, a number); the members' own taker bar {bars_taker[PRIMARY]:.4f} (the cost proxy covers {cost_cover:.0%} of the scored cells); "
              f"the registered sign {'positive' if R68_SIGN > 0 else 'negative'} on both; the two features' correlation on the scored cells {corr:+.3f}.\n")
    fam = rows["feature"].isin(REGISTERED) & rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])
    md += ["\n## The family (relative, 1d — the two registered features) with 1h / 4h and the directional bet beside\n",
           "`p_fw_*` = the share of a null's draws whose largest |t| over the TWO 1d cells is at or above the real |t|; `p_single_*` = the cell alone; `p_family` = the larger of the two nulls' "
           "family-wise p. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. `bar_maker_twelve` = the gate's number; `bar_taker_members` = the members' taker bar from their cost proxy.\n",
           show(rows[fam][cols_show]), "\n",
           "\n## Described beside (no nulls, no verdict): the hourly forms, the trailing-day levels; 15m and the vol bet\n", show(rows[~fam][cols_show[:12] + ["bar_taker_members", "verdict"]]), "\n",
           "\n## The nulls' family bars (largest |t| over the two cells, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           f"\n## By block — the kept members present and the relative {PRIMARY} IC of each feature inside the block (described)\n", show(Bb.assign(block=lambda d_: d_["block"].dt.date)), "\n",
           "\n## The kept names on their member cells\n", show(desc), "\n"]
    out_md.write_text("".join(md))
    print("; ".join(f"{k}: {rows[(rows['feature'] == k) & (rows['bet'] == BET) & (rows['horizon'] == PRIMARY)].iloc[0]['verdict']}" for k in REGISTERED) + f"; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


def describe_names(fr: dict) -> pd.DataFrame:
    F, s, kept = fr["F"], fr["s"], fr["kept"]
    rows = []
    for c in kept:
        if c not in F[TB24].columns:
            continue
        tb, sr, tbl, srl = (F[k][s][c] for k in (TB24, SR24, TB24L, SR24L))
        rows.append({"symbol": c, "cells": int(tb.notna().sum()), "tb24_mean": tbl.mean(), "tb24_sd": tbl.std(), "sr24_mean": srl.mean(), "sr24_sd": srl.std(),
                     "tb24_dev_sd": tb.std(), "sr24_dev_sd": sr.std(), "cover_tb24": float(tb.notna().mean()), "cover_sr24": float(sr.notna().mean())})
    return pd.DataFrame(rows)


def _head(validity: dict, taker_bps, maker_bps, fee_source) -> list[str]:
    return [f"# R68 — Binance's own spot flow per member at one day: the screener's F1+F2 members (`ft2 ceiling --target pairs --family spot --universe members`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed) on the members' cells (a name's cells while a member of the bar's block); every source cut at "
            f"{ceiling.END:%Y-%m-%d}. The universe `{validity['lists']['universe']['path']}` (md5 {validity['lists']['universe']['md5']}, {validity['lists']['universe']['n_kept']} kept). "
            f"The quantities: `{TB24}` the trailing-day taker-buy share of the spot quote volume against its trailing month; `{SR24}` the trailing-day log spot/perp quote-volume ratio against its trailing month. "
            f"Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source):
    validity["status"] = "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head(validity, taker_bps, maker_bps, fee_source) + ["\n**The read is VOID: no row of a registered feature was computed on the members.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)
