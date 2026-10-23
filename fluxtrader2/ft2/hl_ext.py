"""R69 (P8 decision BK1, 2026-10-23, docs/PLAN.md §8) — the cross-venue lean at one day: R62's screen on the screener's F1+F2 members with
the HYPERLIQUID source (`data/hl_funding_1h.parquet`, `data/premium_1h.parquet`; DATA.md `hl_funding_1h`).

The registered feature, on the hourly grid of `ts_known` and then P2's 5m panel through R62's `to_panel` (MARGIN one 5m bar, STALE 2 h):
  hl_gap24_dev    the cross-venue gap — the mean of the venue's premium over the last 24 settlement hours (≥ 20 present) minus the mean of
                  Binance's 1h premium index bar closes over the last 24 bars (≥ 20 present), in bps — minus its trailing 30-day mean over
                  its trailing 30-day sd (cb_ext's DEV form on the hourly grid: MONTH 720, MIN_MONTH 360).
The family = the feature × 1d on the RELATIVE bet (ONE cell); the sign fixed NEGATIVE (R69_SIGN); both nulls at DRAWS at 1h / 4h / 1d;
p_family = the larger of the two nulls' p on the one cell; the gate R62's (`verdict_r62`: p_family ≤ 0.05, the sign, both folds, |IC| ≥
BAR_TWELVE 0.0159). The SCORED SAMPLE starts at SCORED_FROM (the block of 2023-08-01): the venue settled 8-hourly until 2023-06-25 and listed
its first members through the summer, so the audit's cover drops the earlier blocks (0, 0, 18 names at ≥ 90 %) before any label.
Described beside, no nulls, no verdict: `hl_prem24_dev`, `hl_fund24_dev` (the venue's own trailing-day premium and funding against their
month — Binance's quantity again), `bn_prem24_dev` (Binance's own, R20's quantity on the members' frame), the LEVEL `hl_gap24`, the
registered feature's correlation with `bn_prem24_dev` on the scored cells.

Validity, read first in the registered order, void (exit 2) on any FAIL: (1) the lists' md5 and the frozen list's self-consistency
(`r69` = listed and rows ≥ R69_MIN_ROWS and the lag-0 correlation ≥ R69_CORR_CUT); (2) R62's saved screen reproduced through `cb_ext.frames`
on the Coinbase source (no nulls); (3) N_CHECK scored cells of kept names recomputed straight from the two parquets' rows by an independent
cumulative-sum construction (the used hour, the 24-row means, the gap, the month's mean and sd) to TOL_HAND; (4) known-at — no cell read
early, none older than STALE; (5) membership and block coverage (R62's `block_coverage` on the scored blocks) and the scored sample's first
bar at or after SCORED_FROM; (6) R60's saved bar within BAR_TOL of 0.0159; (7) the nulls' admissibility (the shifts ≥ 60 > 31, the shuffle
gap ≥ 8). The construction of the feature is the audit's `hl.grids` (the same code the audit measured); R62's helpers are called, none edited.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cb_ext as cx
from . import ceiling, coinbase as cb, folds, hl
from .book_ext import SHIFT_MIN, fold_ics, shift_feature, taker_bar
from .cb_ext import BAR_TOL, BAR_TWELVE, BET, BLOCK_MIN_NAMES, HZ, MARGIN, MEMBERS_SLICES, MEMBERS_START, MIN_MONTH, MONTH, N_CHECK, PRIMARY, STALE
from .ceiling import HORIZONS, MDE_K, NULL_GAP, Z_CLIP, _null_feature
from .spot_ext import GAP_MIN, SHIFT_FLOOR, TOL_HAND, _win_mean_sd, _win_sum

GAP = "hl_gap24_dev"                                     # registered
PREM, FUND, BNP = "hl_prem24_dev", "hl_fund24_dev", "bn_prem24_dev"      # described: the venue's own, Binance's own
GAPL = "hl_gap24"                                        # described: the level
REGISTERED = (GAP,)
GRID_OF = {GAP: "gap24_dev", PREM: "hl_prem24_dev", FUND: "hl_fund24_dev", BNP: "bn_prem24_dev", GAPL: "gap24"}
FAMILY_CELLS = [(GAP, PRIMARY)]
R69_SIGN = -1.0                                          # the venue's crowd leaning longer than Binance's gives it back
R69_CSV = Path(__file__).with_name("hl_members_r69.csv")
R69_MIN_ROWS = 1000                                      # the stamp check's cut: live settlement rows
R69_CORR_CUT = 0.20                                      # the stamp check's cut: the lag-0 correlation with Binance's premium bar
SCORED_FROM = pd.Timestamp("2023-08-01", tz="UTC")       # the first scored bar: the audit's cover (0, 0, 18 names on the blocks before)
DAY, MIN_DAY = hl.DAY, hl.MIN_DAY
OUT_MD = Path("output/ceiling_hl_members.md")
OUT_DIR = Path("output/ceiling_hl_members")
HOUR = pd.Timedelta("1h")


# ---- the list, the frames ------------------------------------------------------------------------------------------------------------
def r69_list(path: Path | str = R69_CSV, min_rows: int = R69_MIN_ROWS, corr_cut: float = R69_CORR_CUT) -> dict:
    raw = Path(path).read_bytes()
    L = pd.read_csv(path)
    corr = pd.to_numeric(L["corr_lag0"], errors="coerce")
    rule = (L["listed"].astype(bool) & (L["rows"] >= min_rows) & (corr >= corr_cut)).fillna(False)
    kept = list(L.loc[L["r69"].astype(bool), "symbol"])
    return {"kept": kept, "md5": hashlib.md5(raw).hexdigest(), "n_kept": len(kept), "n_rows": int(len(L)), "consistent": bool((rule == L["r69"].astype(bool)).all()),
            "coin": dict(zip(L["symbol"], L["coin"].fillna(""))), "with_rows": int((L["rows"] > 0).sum())}


def grids_hl(names: list[str], path: Path | str, bn_path: Path | str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """The audit's grids on the kept names over (start − 2 h, end]: the hourly frames keyed by GRID_OF's values; the live settlement rows and
    Binance's premium bars read."""
    d = hl.load(path)
    d = d[d["symbol"].isin(names)]
    bn = pd.read_parquet(bn_path)
    bn["symbol"] = bn["symbol"].astype(str)
    bn = bn[bn["symbol"].isin(names)]
    G = hl.grids(d, bn, start - 2 * HOUR, end)
    return G, d, bn


def frames_hl(L: dict, path: Path | str, bn_path: Path | str, slices: tuple[str, ...], members_csv: Path | str | None, start: pd.Timestamp = MEMBERS_START,
              end: pd.Timestamp | None = None, scored_from: pd.Timestamp = SCORED_FROM) -> dict:
    """R62's members' frame on the venue's source: the panel on the kept names, the five 5m frames masked to the kept names and to membership,
    the used hours of the registered feature, the hourly grids, the membership mask and rows, the rows read; the scored sample cut to
    `scored_from` onward (D["scored"] replaced — every reader of the sample sees the cut)."""
    kept = L["kept"]
    end = end or ceiling.END
    P = cx.member_panel(kept, start, end, slices)
    D = ceiling.derive(P)
    idx, cols = D["lr"].index, list(D["lr"].columns)
    s = np.asarray(D["scored"], bool) & np.asarray(idx >= scored_from)
    D["scored"] = s
    G, d, bn = grids_hl(kept, path, bn_path, start, end)
    F_all = {k: cx.to_panel(G[g], idx, cols) for k, g in GRID_OF.items()}
    M, m = cx.membership(idx, cols, members_csv)
    F = cx.mask_members(cx.restrict(F_all, kept), M)
    U = {k: cx.used_hours(G[GRID_OF[k]], idx, cols) for k in REGISTERED}
    return {"kept": kept, "P": P, "D": D, "idx": idx, "cols": cols, "s": s, "F_all": F_all, "F": F, "U": U, "G": G, "M": M, "m": m, "rows": d, "bn": bn, "scored_from": scored_from}


# ---- validity (3): the feature by hand -----------------------------------------------------------------------------------------------
def _win_mean(x: np.ndarray, k: int, min_n: int) -> np.ndarray:
    n = _win_sum((~np.isnan(x)).astype(float), k, 1)
    sv = _win_sum(x, k, min_n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isfinite(sv) & (n >= min_n), sv / n, np.nan)


def hand_series(rows: pd.DataFrame, bn_rows: pd.DataFrame, grid: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """One name's registered feature on `grid`, built from its live settlement rows (the premium by ts_known) and Binance's premium bars (the
    close by ts_known) with cumulative sums — not pandas' rolling. Also the level `hl_gap24`."""
    prem = rows.set_index("ts_known")["premium"].reindex(grid).to_numpy(dtype=float) * 1e4
    bnp = bn_rows.set_index("ts_known")["close"].reindex(grid).to_numpy(dtype=float) * 1e4
    gap = _win_mean(prem, DAY, MIN_DAY) - _win_mean(bnp, DAY, MIN_DAY)
    m, sd = _win_mean_sd(gap, MONTH, MIN_MONTH)
    with np.errstate(invalid="ignore", divide="ignore"):
        dev = (gap - m) / sd
    return {GAP: dev, GAPL: gap}


def hand_check(fr: dict, n_check: int = N_CHECK, seed: int = 0, tol: float = TOL_HAND) -> dict:
    """Validity (3): `n_check` random scored MEMBER cells of kept names — the frame's value of the registered feature equals the hand series'
    value at the used hour (the latest hour ≤ t − MARGIN with a value, at most STALE hours before it; NaN = NaN when none)."""
    F, U, s, idx, kept, G, M = fr["F"], fr["U"], fr["s"], fr["idx"], fr["kept"], fr["G"], fr["M"]
    grid = G["gap24_dev"].index
    sidx = idx[s]
    cols = [c for c in kept if c in F[GAP].columns]
    rng = np.random.default_rng(seed)
    Ms = M[s][cols].to_numpy()
    cand_i, cand_j = rng.integers(0, len(sidx), 4 * n_check), rng.integers(0, len(cols), 4 * n_check)
    on = Ms[cand_i, cand_j]
    ii, jj = cand_i[on][:n_check], cand_j[on][:n_check]
    g0 = grid[0]
    series, worst, n_nan, n_val = {}, 0.0, 0, 0
    for i, j in zip(ii, jj):
        c, t = cols[j], sidx[i]
        if c not in series:
            series[c] = hand_series(fr["rows"][fr["rows"]["symbol"] == c], fr["bn"][fr["bn"]["symbol"] == c], grid)
        th = int(((t - MARGIN).floor("h") - g0) / HOUR)                      # the latest grid position whose row may be read at t
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


def known_at_hl(fr: dict) -> dict:
    """Validity (4): on every scored cell with a value the hourly row used has ts_known + MARGIN ≤ t and is at most STALE hours old."""
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
def run_r69(taker_bps: float, maker_bps: float, fee_source: str, draws: int = ceiling.DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN, jobs: int = 1,
            path: Path | str = hl.PARQUET, bn_path: Path | str = hl.BN_PARQUET, cb_path: Path | str = cb.MEMBERS_PARQUET, r62: Path = cx.MEMBERS_OUT_DIR,
            csv: Path | str = R69_CSV, cb_csv: Path | str = cx.R62_CSV, members_csv: Path | str | None = None, slices: tuple[str, ...] = MEMBERS_SLICES,
            mult: dict[str, float] | None = None, n_check: int = N_CHECK, start: pd.Timestamp = MEMBERS_START, end: pd.Timestamp | None = None,
            scored_from: pd.Timestamp = SCORED_FROM, block_min_names: int = BLOCK_MIN_NAMES, r60: Path = cx.OUT_DIR, gap: int = NULL_GAP,
            shift_floor: int = SHIFT_FLOOR, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    from joblib import Parallel, delayed
    from .universe import MEMBERS_CSV
    out_dir.mkdir(parents=True, exist_ok=True)
    end = end or ceiling.END
    L = r69_list(csv)
    kept = L["kept"]
    mcsv = Path(members_csv or MEMBERS_CSV)
    Lcb = cx.r62_list(cb_csv)
    validity = {"registration": "R69", "folds": list(folds.EXPLORATION), "scored_from": {"asked": str(scored_from)}, "draws": draws, "seed": seed, "shift_min": shift_min, "gap": gap,
                "sources": {"hl": str(path), "bn": str(bn_path)},
                "lists": {"universe": {"path": str(csv), "md5": L["md5"], "n_kept": L["n_kept"], "n_rows": L["n_rows"], "with_rows": L["with_rows"], "consistent": L["consistent"]},
                          "members": {"path": str(mcsv), "md5": hashlib.md5(mcsv.read_bytes()).hexdigest()},
                          "r62": {"path": str(cb_csv), "md5": Lcb["md5"], "n_kept": Lcb["n_kept"]},
                          "status": "PASS" if L["consistent"] and L["n_kept"] > 0 else "FAIL"},
                "gate": {"bar_twelve": BAR_TWELVE, "sign": R69_SIGN, "family": FAMILY_CELLS, "p_max": 0.05}}
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

    # the venue's frame; (3) by hand, (4) known-at, (5) membership, coverage and the scored sample's start — before any IC
    print("the members' panel and the venue's frames…", flush=True)
    fr = frames_hl(L, path, bn_path, slices, members_csv, start, end, scored_from)
    D, idx, cols, s, F, M, m = fr["D"], fr["idx"], fr["cols"], fr["s"], fr["F"], fr["M"], fr["m"]
    sidx = idx[s]
    validity["scored_from"] |= {"first": str(sidx[0]) if len(sidx) else None, "status": "PASS" if len(sidx) and sidx[0] >= scored_from else "FAIL"}
    validity |= {"scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))), "names_in_panel": len(cols), "first": str(sidx[0]), "last": str(sidx[-1]),
                 "kept_in_panel": int(sum(c in cols for c in kept)), "kept_with_a_value": int(sum(F[GAP][s][c].notna().any() for c in kept if c in cols))}
    print("validity (3): the feature by hand…", flush=True)
    validity["hand"] = hand_check(fr, n_check, seed)
    validity["known_at"] = known_at_hl(fr)
    off = {k: int((F[k].notna() & ~M).to_numpy().sum()) for k in REGISTERED}
    validity["membership"] = {"status": "PASS" if sum(off.values()) == 0 else "FAIL", "values_off_membership": off,
                              "values_on": {k: int(F[k][s].notna().to_numpy().sum()) for k in REGISTERED}}
    validity["coverage"], B = cx.block_coverage(F[GAP], s, m, kept, block_min_names)
    both = F[GAP][s].notna() & F[BNP][s].notna()
    corr = float(pd.Series(F[GAP][s].to_numpy()[both.to_numpy()]).corr(pd.Series(F[BNP][s].to_numpy()[both.to_numpy()])))
    validity["corr_with_bn_prem24_dev_on_scored_cells"] = {"corr": corr, "cells": int(both.to_numpy().sum())}
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in ("lists", "nulls", "reproduction", "hand", "known_at", "membership", "coverage", "scored_from")) and validity["gate"]["bar_status"] == "PASS" else "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    if validity["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    B.to_parquet(out_dir / "blocks.parquet", index=False)
    head = _head(validity, taker_bps, maker_bps, fee_source)

    # the screen: the registered feature; the venue's own, Binance's own and the level described
    print("screen: the registered feature; the described rows beside…", flush=True)
    sc, daily = ceiling.ic_screen(D, {k: F[k] for k in GRID_OF}, set())
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}
    print(f"nulls on {GAP}: {draws} day shuffles and {draws} whole-day shifts…", flush=True)
    desc = describe_names(fr)
    Freg = {k: F[k] for k in REGISTERED}
    del fr, F
    import gc
    gc.collect()
    jobs_ = [delayed(_null_feature)(k, Freg[k][s], Zs, Zr, draws, seed, gap=gap) for k in REGISTERED] + \
            [delayed(shift_feature)(k, Freg[k], D, s, draws, seed, shift_min) for k in REGISTERED]
    res = Parallel(n_jobs=min(jobs, 2) if jobs > 1 else 1, prefer="threads")(jobs_)
    null_shuffle, null_shift = res[0], res[1]

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
        rows.loc[i, "verdict"] = cx.verdict_r62(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), BAR_TWELVE, R69_SIGN)
    rep = rows["feature"].isin(REGISTERED) & (rows["horizon"] != PRIMARY) & rows["bet"].isin(["directional", "relative"]) & rows["horizon"].isin(HZ)
    rows.loc[rep, "verdict"] = "reported, not gated"
    words = {PREM: "described (the venue's own trailing-day premium against its month — Binance's quantity again, xlvi)",
             FUND: "described (the venue's own trailing-day funding against its month — Binance's quantity again, xlvi)",
             BNP: "described (Binance's own trailing-day premium against its month — R20's quantity on the members' frame)",
             GAPL: "described (the cross-venue gap, the level)"}
    for f_, w in words.items():
        rows.loc[rows["feature"] == f_, "verdict"] = w
    bi = cx.block_ics(daily, m, feature=GAP)

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    pd.DataFrame({"horizon": list(bars_taker), "ic_needed_taker_members": list(bars_taker.values()), "bar_maker_twelve": BAR_TWELVE, "cost_cover": cost_cover}).to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    desc.to_parquet(out_dir / "names.parquet", index=False)
    Bb = B.merge(bi.rename(columns={"ic": "ic_gap24", "se": "se_gap24", "days": "days_gap24"}), on="block", how="left")
    Bb.to_parquet(out_dir / "blocks.parquet", index=False)

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker_twelve", "bar_taker_members", "verdict"]
    g = rows[(rows["feature"] == GAP) & (rows["bet"] == BET) & (rows["horizon"] == PRIMARY)].iloc[0]
    md = head + [f"\n## Verdict by R69's gate — the one cell, {BET}, {PRIMARY}, on the kept members\n",
                 f"\n- **`{GAP}`: {g['verdict']}** — IC {g['ic']:+.4f} (t {g['t']:+.2f}, se {g['ic_se']:.4f}, MDE {g['ic_mde']:.4f}); p_family {g['p_family']:.3f} (day shuffles "
                 f"{g['p_fw_shuffle']:.3f}, whole-day shifts {g['p_fw_shift']:.3f}; single {g['p_single_shuffle']:.3f} / {g['p_single_shift']:.3f}); F1 {g['ic_F1']:+.4f}, F2 {g['ic_F2']:+.4f} "
                 f"({'same sign' if g['folds_same_sign'] else 'signs differ'}); months the same sign {g['months_same_sign']:.2f}; the interval [{g['ic'] - 1.96 * g['ic_se']:+.4f}, {g['ic'] + 1.96 * g['ic_se']:+.4f}] against the bar {BAR_TWELVE}.\n",
                 f"\nThe gate's bar {BAR_TWELVE} (the twelve's maker bar at {PRIMARY}, a number); the members' own taker bar {bars_taker[PRIMARY]:.4f} (the cost proxy covers {cost_cover:.0%} of the scored cells); "
                 f"the registered sign {'positive' if R69_SIGN > 0 else 'negative'}; the registered feature's correlation with `{BNP}` on the scored cells {corr:+.3f}; the scored sample from {validity['scored_from']['first']}.\n"]
    fam = rows["feature"].isin(REGISTERED) & rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])
    md += ["\n## The family (relative, 1d — the registered feature) with 1h / 4h and the directional bet beside\n",
           "`p_fw_*` = the share of a null's draws whose |t| on the ONE cell is at or above the real |t|; `p_single_*` = the same cell at the other horizons; `p_family` = the larger of the two nulls' "
           "p. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. `bar_maker_twelve` = the gate's number; `bar_taker_members` = the members' taker bar from their cost proxy.\n",
           show(rows[fam][cols_show]), "\n",
           "\n## Described beside (no nulls, no verdict): the venue's own premium and funding, Binance's own premium, the level; 15m and the vol bet\n", show(rows[~fam][cols_show[:12] + ["bar_taker_members", "verdict"]]), "\n",
           "\n## The nulls' bars (|t| on the cell, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           f"\n## By block — the kept members present and the relative {PRIMARY} IC of the feature inside the block (described)\n", show(Bb.assign(block=lambda d_: d_["block"].dt.date)), "\n",
           "\n## The kept names on their member cells\n", show(desc), "\n"]
    out_md.write_text("".join(md))
    print(f"{GAP}: {g['verdict']}; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


def describe_names(fr: dict) -> pd.DataFrame:
    F, s, kept = fr["F"], fr["s"], fr["kept"]
    rows = []
    for c in kept:
        if c not in F[GAP].columns:
            continue
        dv, lv = F[GAP][s][c], F[GAPL][s][c]
        rows.append({"symbol": c, "cells": int(dv.notna().sum()), "gap24_mean": lv.mean(), "gap24_sd": lv.std(), "gap24_dev_sd": dv.std(), "cover": float(dv.notna().mean())})
    return pd.DataFrame(rows)


def _head(validity: dict, taker_bps, maker_bps, fee_source) -> list[str]:
    return [f"# R69 — the cross-venue lean at one day: the screener's F1+F2 members (`ft2 ceiling --target pairs --family hl --universe members`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed) on the members' cells (a name's cells while a member of the bar's block) from {validity['scored_from']['asked']}; every source cut at "
            f"{ceiling.END:%Y-%m-%d}. The universe `{validity['lists']['universe']['path']}` (md5 {validity['lists']['universe']['md5']}, {validity['lists']['universe']['n_kept']} kept). "
            f"The quantity: `{GAP}` — the venue's trailing-day premium minus Binance's, against its trailing month. "
            f"Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source):
    validity["status"] = "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head(validity, taker_bps, maker_bps, fee_source) + ["\n**The read is VOID: no row of the registered feature was computed on the members.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)
