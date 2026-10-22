"""R65 (PLAN §8): two under-bar facts as ONE score on the screener's F1+F2 members — the mean of two cross-sectional percentile ranks,
`cbprem_dev` (R62's deviation of the Coinbase premium from its trailing month, sign +) everywhere, and −`bx_1h` (R50's beta × BTC's last
hour / σ_1h, R63's registered sign made positive) added on the bars where BTC's last completed hour FELL. The family `score` × 4h / 1d on
the relative bet, both nulls, the sign POSITIVE, R62's gate (BAR_TWELVE as the number, the members' taker bar beside).

    ft2 ceiling --target pairs --family score --universe members --draws 200   → output/ceiling_score_members.md, output/ceiling_score_members/

frame      R62's exactly (`cb_ext.frames` on the Coinbase source: the members' panel, P2's `derive`, the kept names masked to membership,
           F1+F2 embargoed as the scored sample, every 5m bar scored). `cbprem_dev` IS that frame's DEV.
bx_1h      R50's feature VERBATIM on the hourly grid (`scripts/r50_btchour.py::features`: beta_btc the 720-hour slope of the name's hourly log
           return on BTC's, ≥ 200 pairs; b_1h BTC's last hour in bps; σ_1h = sig1w × √12 from the frame's own 5m returns), its value and
           BTC's sign CARRIED into the 5m bars from the LAST hourly bar at or before t (`idx.floor("h")`; at most 55 minutes old, never a
           later bar). The fall mask = b_1h < 0 at that hourly bar; b_1h = 0 or unknown belongs to the other half.
score      at a bar t over the cells where `cbprem_dev` has a value (and, on a fall bar, `bx_1h` too): rank_cb = the percentile rank of
           `cbprem_dev`; on a fall bar rank_bx = the percentile rank of −`bx_1h` over the same cells and score = (rank_cb + rank_bx) / 2;
           on the other bars score = rank_cb (its per-bar Spearman with `cbprem_dev` is 1 by construction — a conditioning, not a fit).
described  (no nulls, no verdict) each input alone on the score's cells — `cbprem_dev` (R62's row) and `bx_fall` = −bx_1h on the fall bars
           only; `score_fall` / `score_other` the score on each half; ρ = the per-bar Spearman between `cbprem_dev` and −`bx_1h` over the
           fall bars' cells (rho.parquet); `score3` = the three-rank score with R64's `krprem_dev` as a third rank on the cells where all
           exist (the Korean rank is a quantity of the hours — described at 15m … 1d, no gate).
validity   FIRST, before any score is joined to a label: (1) `frames` on the Coinbase source reproduces R62's saved screen rows (the six
           features; ic, t, every bet × horizon) to TOL (`reproduction_r62`); (2) R63's mask path on R18's F1+F2 frame reproduces R50's
           `reference.csv` rows "bx_1h after a BTC fall / rise" to TOL (the bx code is R50's); (3) known-at — R62's `known_at` on the
           Coinbase frame (every cell; N_CHECK recomputed), the hourly bar used for bx at or before t on every scored cell with a score and
           at most 55 minutes old, N_CHECK random fall cells' score recomputed by hand (beta, b_1h, σ_1h, the two ranks, the mean) to
           1e-9; (4) the construction — on every non-fall scored bar the score's Spearman with `cbprem_dev` is 1, on every fall bar the
           score has a value exactly where both inputs have one; (5) membership and block coverage as R62's; (6) the lists' md5. FAIL on
           any → validity.json says so, exit 2, no row of `score` written (VOID).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import ceiling, coinbase as cb, folds
from .book_ext import SHIFT_MIN, fold_ics, shift_feature, taker_bar
from .cb_ext import (BAR_TOL, BAR_TWELVE, BET, BLOCK_MIN_NAMES, DEV, DRAWS, FAMILY_HZ, HZ, KR_PARQUET, MEMBERS_OUT_DIR, MEMBERS_SLICES, MEMBERS_START,
                     N_CHECK, OUT_DIR as R60_DIR, PRIMARY, R62_CSV, R62_SIGN, R64_CSV, TOL, block_coverage, block_ics, family_p, frames, known_at, r62_list,
                     r64_list, reproduction_r62, screen_frames_r62, single_p, verdict_r62)
from .ceiling import HORIZONS, MDE_K, MIN_PAIRS, Z_CLIP, _null_feature

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCORE, BXF, SCF, SCO, S3 = "score", "bx_fall", "score_fall", "score_other", "score3"
BTC = "BTCUSDT"
H1 = 12                                    # 5m bars in an hour: σ_1h = sig1w × √H1
MAX_AGE = pd.Timedelta(minutes=55)         # the hourly bar used for bx is at most this old at t
REF_CSV = Path("output/audit/r50_btchour/reference.csv")
R65_OUT_MD = Path("output/ceiling_score_members.md")
R65_OUT_DIR = Path("output/ceiling_score_members")
REC_TOL = 1e-9


# ---- R50's and R63's code, loaded from the scripts ------------------------------------------------------------------------------------------
_MODULES: dict[str, object] = {}


def script(name: str):
    """`scripts/<name>.py` as a module (R63's way of reaching R50): r50_btchour's `features`, `_universe`, `_btc`; r63_fall's `half_rows`, `reproduce`."""
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MODULES[name] = m
    return _MODULES[name]


# ---- bx_1h on R62's frame -------------------------------------------------------------------------------------------------------------------
def btc_close(idx: pd.DatetimeIndex, slices: tuple[str, ...] = ("candles_5m",)) -> pd.Series:
    """BTC's 5m close on the frame's index (the collector's candles, as R50 / R63)."""
    from .cb_ext import member_panel
    P = member_panel([BTC], idx[0], idx[-1], slices)
    return P["close"][BTC].reindex(idx)


def bx_frames(D: dict, idx: pd.DatetimeIndex, cols: list[str], btc5: pd.Series) -> dict:
    """R50's `bx_1h` on the hourly grid of the frame (the bars with minute 00), carried into every 5m bar from the last hourly bar at or
    before t; BTC's hour b_1h the same way; the fall mask per 5m bar."""
    r50 = script("r50_btchour")
    hm = (idx.minute == 0) & (idx.second == 0)
    hidx = idx[hm]
    close_h = np.exp(D["lr"].loc[hidx, cols])
    sig_h = (D["sig"]["1w"] * np.sqrt(H1)).loc[hidx, cols]
    F, rb = r50.features(hidx, cols, close_h, btc5.reindex(hidx), sig_h)
    bx_h = F["bx_1h"]
    pos = hidx.get_indexer(idx.floor("h"))                                 # the last hourly bar at or before t; −1 before the first
    ok = pos >= 0
    p0 = np.maximum(pos, 0)
    bx5 = pd.DataFrame(np.where(ok[:, None], bx_h.to_numpy()[p0], np.nan), index=idx, columns=cols)
    b5 = np.where(ok, rb[p0], np.nan)
    used = pd.DatetimeIndex(hidx[p0]).where(ok, pd.NaT)                  # the hourly bar each 5m bar's bx came from
    fall = np.isfinite(b5) & (b5 < 0)
    return {"bx5": bx5, "b5": b5, "fall": fall, "hour_used": used, "bx_h": bx_h, "beta_h": F["beta_btc"], "rb_h": rb, "hidx": hidx}


def pct_rank(X: pd.DataFrame) -> pd.DataFrame:
    return X.rank(axis=1, pct=True)


def score_frames(cb_dev: pd.DataFrame, bx5: pd.DataFrame, fall: np.ndarray) -> dict[str, pd.DataFrame]:
    """The score and its parts on the score's cells: on a fall bar the cells where both inputs have a value, on the other bars the cells
    where `cb_dev` has one."""
    f = np.broadcast_to(fall[:, None], cb_dev.shape)
    base = cb_dev.notna()
    neg = (-bx5).where(base)
    cells = np.where(f, (base & neg.notna()).to_numpy(), base.to_numpy())
    C, N = cb_dev.where(cells), neg.where(cells)
    r_cb, r_bx = pct_rank(C).to_numpy(), pct_rank(N).to_numpy()
    sc = pd.DataFrame(np.where(f, (r_cb + r_bx) / 2, r_cb), index=cb_dev.index, columns=cb_dev.columns)
    return {SCORE: sc, BXF: N.where(f), SCF: sc.where(f), SCO: sc.where(~f)}


def score3_frame(cb_dev: pd.DataFrame, bx5: pd.DataFrame, kr_dev: pd.DataFrame, fall: np.ndarray) -> pd.DataFrame:
    """The described three-rank score: the Korean deviation as a third rank, on the cells where every input present has a value."""
    f = np.broadcast_to(fall[:, None], cb_dev.shape)
    kr = kr_dev.reindex(index=cb_dev.index, columns=cb_dev.columns)
    cells = (cb_dev.notna() & kr.notna()).to_numpy() & (~f | bx5.notna().to_numpy())
    C, K, N = cb_dev.where(cells), kr.where(cells), (-bx5).where(cells)
    rc, rk, rn = (pct_rank(x).to_numpy() for x in (C, K, N))
    return pd.DataFrame(np.where(f, (rc + rk + rn) / 3, (rc + rk) / 2), index=cb_dev.index, columns=cb_dev.columns)


def _spearman_rows(X: pd.DataFrame, Y: pd.DataFrame) -> np.ndarray:
    """Per row the Spearman over the cells where both are present (NaN under MIN_PAIRS) — `ceiling._ic_xs` without the day average."""
    ok = X.notna() & Y.notna()
    rx, ry = X.where(ok).rank(axis=1).to_numpy(), Y.where(ok).rank(axis=1).to_numpy()
    n = ok.sum(axis=1).to_numpy().astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mx, my = np.nansum(rx, 1) / n, np.nansum(ry, 1) / n
        cov = np.nansum(rx * ry, 1) / n - mx * my
        vx, vy = np.nansum(rx * rx, 1) / n - mx ** 2, np.nansum(ry * ry, 1) / n - my ** 2
        r = cov / np.sqrt(vx * vy)
    r[(n < MIN_PAIRS) | ~np.isfinite(r)] = np.nan
    return r


def rho(cb_dev: pd.DataFrame, bx5: pd.DataFrame, fall: np.ndarray, s: np.ndarray) -> tuple[dict, pd.DataFrame]:
    """ρ: the per-bar Spearman between `cbprem_dev` and −`bx_1h` over the scored fall bars' cells — the arithmetic's input; per day beside."""
    on = s & fall
    idx = cb_dev.index[on]
    r = _spearman_rows(cb_dev[on], (-bx5)[on])
    day = idx.floor("D")
    per_day = pd.Series(r, index=idx).groupby(day).mean().rename("rho").reset_index().rename(columns={"index": "day"})
    fin = r[np.isfinite(r)]
    return {"rho_mean": float(fin.mean()) if len(fin) else np.nan, "rho_median": float(np.median(fin)) if len(fin) else np.nan,
            "rho_sd": float(fin.std(ddof=1)) if len(fin) > 1 else np.nan, "bars": int(len(fin)), "bars_fall_scored": int(on.sum()),
            "days": int(per_day["rho"].notna().sum())}, per_day


# ---- validity -----------------------------------------------------------------------------------------------------------------------------
def reproduce_r50(ref_csv: Path | str = REF_CSV, A: dict | None = None, run: str | None = None, members: str | None = None) -> tuple[dict, pd.DataFrame]:
    """Validity (2): R63's mask path on R50's stage-1 frame (R18's F1+F2 cells; `A` given in the tests) against R50's reference rows."""
    r50, r63 = script("r50_btchour"), script("r63_fall")
    from . import audit
    ref = pd.read_csv(ref_csv)
    run = run or r50.RUN_F12
    A = A if A is not None else audit.frame(run, members)
    u = r50._universe("outside", A, r63.HOLDS, r50._btc(A, A))
    got = r63.half_rows(u, r63.HOLDS)
    return {"run": run, "reference": str(ref_csv), **r63.reproduce(got, ref)}, got


def hour_check(hour_used: pd.DatetimeIndex, idx: pd.DatetimeIndex, s: np.ndarray, score: pd.DataFrame, max_age: pd.Timedelta = MAX_AGE) -> dict:
    """Validity (3): on every scored bar with a score the hourly bar bx was taken from is at or before t and at most `max_age` old."""
    has = score[s].notna().any(axis=1).to_numpy()
    t, u = idx[s], hour_used[s]
    known = np.asarray(u.notna())
    late = has & known & np.asarray(u > t)
    old = has & known & np.asarray((t - u) > max_age)
    missing = has & ~known
    return {"status": "PASS" if not late.any() and not old.any() and not missing.any() else "FAIL", "bars_with_a_score": int(has.sum()),
            "bars_hour_after_t": int(late.sum()), "bars_hour_older_than_max_age": int(old.sum()), "bars_without_an_hour": int(missing.sum()), "max_age": str(max_age)}


def _rank_avg(v: np.ndarray) -> np.ndarray:
    return pd.Series(v).rank(pct=True).to_numpy()


def recompute_fall_cells(D: dict, cols: list[str], btc5: pd.Series, cb_dev: pd.DataFrame, bx5: pd.DataFrame, score: pd.DataFrame, fall: np.ndarray,
                         s: np.ndarray, n_check: int = N_CHECK, seed: int = 0, tol: float = REC_TOL, window: int = 720, min_n: int = 200) -> dict:
    """Validity (3): `n_check` random scored fall cells with a score, recomputed by hand — beta from the last `window` hourly log returns at
    or before the hourly bar used (≥ `min_n` finite pairs, least squares), b_1h from BTC's two hourly closes, σ_1h from the frame's sig1w,
    then the two percentile ranks over the bar's cells and their mean — against the frame's bx and score."""
    idx = D["lr"].index
    hm = (idx.minute == 0) & (idx.second == 0)
    hidx = idx[hm]
    rc = (D["lr"].loc[hidx, cols].diff() * 1e4).to_numpy()
    lb = np.log(btc5.reindex(hidx).to_numpy(dtype=float))
    rb = np.concatenate([[np.nan], np.diff(lb)]) * 1e4
    sig_h = (D["sig"]["1w"] * np.sqrt(H1)).loc[hidx, cols].to_numpy()
    on = np.flatnonzero(s & fall)
    rng = np.random.default_rng(seed)
    S, Cv, Bv = score.to_numpy(), cb_dev.to_numpy(), bx5.to_numpy()
    worst_bx, worst_sc, n_done = 0.0, 0.0, 0
    for i in rng.choice(on, size=min(n_check, len(on)), replace=len(on) < n_check):
        present = np.flatnonzero(np.isfinite(S[i]))
        if not len(present):
            continue
        j = int(rng.choice(present))
        k = hidx.get_loc(idx[i].floor("h"))
        lo = max(0, k - window + 1)
        x, y = rb[lo:k + 1], rc[lo:k + 1, j]
        ok = np.isfinite(x) & np.isfinite(y)
        beta = np.polyfit(x[ok], y[ok], 1)[0] if ok.sum() >= min_n and k - lo + 1 == window else np.nan
        bx_hand = beta * rb[k] / sig_h[k, j]
        row_bx = Bv[i].copy()
        row_bx[j] = bx_hand
        cells = np.isfinite(Cv[i]) & np.isfinite(row_bx)
        r_cb, r_bx = _rank_avg(Cv[i][cells]), _rank_avg(-row_bx[cells])
        sc_hand = ((r_cb + r_bx) / 2)[np.flatnonzero(np.flatnonzero(cells) == j)[0]]
        d_bx = abs(bx_hand - Bv[i, j]) if np.isfinite(bx_hand) and np.isfinite(Bv[i, j]) else (0.0 if np.isnan(bx_hand) and np.isnan(Bv[i, j]) else np.inf)
        worst_bx, worst_sc, n_done = max(worst_bx, d_bx), max(worst_sc, abs(sc_hand - S[i, j])), n_done + 1
    ok_all = n_done > 0 and worst_sc <= tol and worst_bx <= 1e-6
    return {"status": "PASS" if ok_all else "FAIL", "recomputed": n_done, "max_abs_diff_score": float(worst_sc), "max_abs_diff_bx": float(worst_bx), "tol_score": tol, "tol_bx": 1e-6}


def construction(score: pd.DataFrame, cb_dev: pd.DataFrame, bx5: pd.DataFrame, fall: np.ndarray, s: np.ndarray) -> dict:
    """Validity (4): on the non-fall scored bars the score's per-bar Spearman with `cbprem_dev` is 1; on the fall bars the score has a value
    exactly where both inputs do; the halves' bar counts."""
    other, on = s & ~fall, s & fall
    r = _spearman_rows(score[other], cb_dev[other])
    fin = np.isfinite(r)
    under = int((r[fin] < 1 - 1e-9).sum())
    expect = (cb_dev[on].notna() & bx5[on].notna()).to_numpy()
    got = score[on].notna().to_numpy()
    v = {"bars_scored": int(s.sum()), "bars_fall": int(on.sum()), "bars_other": int(other.sum()), "fall_share": float(on.sum() / max(s.sum(), 1)),
         "other_bars_with_a_spearman": int(fin.sum()), "spearman_min_other": float(np.nanmin(r)) if fin.any() else np.nan, "other_bars_under_one": under,
         "fall_cells_mismatching_the_inputs": int((expect != got).sum()), "fall_cells_without_bx": int((cb_dev[on].notna() & bx5[on].isna()).to_numpy().sum()),
         "cells_with_a_score": int(score[s].notna().to_numpy().sum()), "cells_fall": int(got.sum()), "cells_other": int(score[other].notna().to_numpy().sum())}
    v["status"] = "PASS" if on.sum() > 0 and other.sum() > 0 and under == 0 and v["fall_cells_mismatching_the_inputs"] == 0 else "FAIL"
    return v


def _md5(path: Path | str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ---- the run ------------------------------------------------------------------------------------------------------------------------------
def run_r65(taker_bps: float, maker_bps: float, fee_source: str, draws: int = DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN, jobs: int = 1,
            cb_path: Path | str = cb.MEMBERS_PARQUET, r62: Path = MEMBERS_OUT_DIR, csv: Path | str = R62_CSV, members_csv: Path | str | None = None,
            slices: tuple[str, ...] = MEMBERS_SLICES, btc_slices: tuple[str, ...] = ("candles_5m",), mult: dict[str, float] | None = None, n_check: int = N_CHECK,
            start: pd.Timestamp = MEMBERS_START, end: pd.Timestamp | None = None, block_min_names: int = BLOCK_MIN_NAMES, r60: Path = R60_DIR,
            ref_csv: Path | str = REF_CSV, f12_frame: dict | None = None, f12_run: str | None = None, kr_csv: Path | str | None = R64_CSV,
            kr_path: Path | str | None = KR_PARQUET, out_md: Path = R65_OUT_MD, out_dir: Path = R65_OUT_DIR) -> str:
    """R65. Validity (1) R62's frame reproduced, (2) R50's reference rows reproduced, then bx on the frame, (3) known-at, (4) the
    construction, (5) membership and coverage, (6) the lists — then the screen, the nulls on the score, the described rows."""
    from joblib import Parallel, delayed
    from .universe import MEMBERS_CSV
    out_dir.mkdir(parents=True, exist_ok=True)
    end = end or ceiling.END
    L = r62_list(csv)
    kept = L["kept"]
    mpath = members_csv or MEMBERS_CSV
    validity = {"registration": "R65", "folds": list(folds.EXPLORATION), "draws": draws, "seed": seed, "shift_min": shift_min, "source": str(cb_path),
                "universe_file": {"path": str(csv), "md5": L["md5"], "n_kept": L["n_kept"], "n_rows": L["n_rows"], "consistent": L["consistent"],
                                  "status": "PASS" if L["consistent"] and L["n_kept"] > 0 else "FAIL"},
                "members_file": {"path": str(mpath), "md5": _md5(mpath)},
                "gate": {"bar_twelve": BAR_TWELVE, "sign": R62_SIGN, "family": [(SCORE, h) for h in FAMILY_HZ]}}

    # validity (1) FIRST: R62's frame — the same call R64 made — against R62's saved screen; this frame IS the score's
    print(f"validity (1): R62's frame on the Coinbase members — the six features against {r62}/screen.parquet…", flush=True)
    fr = frames(L, "coinbase", cb_path, slices, mult, members_csv, start, end)
    sc_cb, _ = ceiling.ic_screen(fr["D"], screen_frames_r62(fr), set())
    validity["reproduction"] = reproduction_r62(sc_cb, r62)
    saved_mv = pd.read_parquet(r60 / "move_vs_cost.parquet") if (r60 / "move_vs_cost.parquet").exists() else None
    if saved_mv is not None:
        sm = saved_mv[(saved_mv["bet"] == BET) & (saved_mv["horizon"] == PRIMARY)]
        validity["gate"]["bar_r60_saved"] = float(sm["ic_needed_maker"].iloc[0]) if len(sm) else np.nan
        validity["gate"]["bar_status"] = "PASS" if len(sm) and abs(float(sm["ic_needed_maker"].iloc[0]) - BAR_TWELVE) <= BAR_TOL else "FAIL"
    else:
        validity["gate"]["bar_status"] = "MISSING"
    if validity["reproduction"]["status"] != "PASS" or validity["universe_file"]["status"] != "PASS" or validity["gate"]["bar_status"] != "PASS":
        return _void_r65(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    del sc_cb

    # validity (2): the bx code is R50's — R63's mask path on R50's stage-1 frame against the reference rows
    print(f"validity (2): R50's reference rows through R63's mask path ({ref_csv})…", flush=True)
    validity["r50_reproduction"], got = reproduce_r50(ref_csv, f12_frame, f12_run, None)
    got.to_csv(out_dir / "validity_r50.csv", index=False)
    if validity["r50_reproduction"]["status"] != "PASS":
        return _void_r65(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # the frame; bx on it; the score
    D, idx, cols, s, F, M, m = fr["D"], fr["idx"], fr["cols"], fr["s"], fr["F"], fr["M"], fr["m"]
    sidx = idx[s]
    validity |= {"scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))), "names_in_panel": len(cols), "first": str(sidx[0]), "last": str(sidx[-1]),
                 "kept_in_panel": int(sum(c in cols for c in kept))}
    print("bx_1h on the hourly grid, carried into the 5m bars; the score…", flush=True)
    btc5 = btc_close(idx, btc_slices)
    bxf = bx_frames(D, idx, cols, btc5)
    bx5, fall = bxf["bx5"], bxf["fall"]
    cb_dev = F[DEV]
    SF = score_frames(cb_dev, bx5, fall)
    score = SF[SCORE]

    # validity (3) known-at on both inputs, (4) the construction, (5) membership and coverage — before any IC
    print("validity (3) … (5)…", flush=True)
    validity["known_at"] = known_at(fr["F_kept"], fr["U"], fr["G"], s, kept, n_check, seed)
    validity["hour_check"] = hour_check(bxf["hour_used"], idx, s, score)
    validity["recompute"] = recompute_fall_cells(D, cols, btc5, cb_dev, bx5, score, fall, s, n_check, seed)
    validity["construction"] = construction(score, cb_dev, bx5, fall, s)
    validity["membership"] = {"status": "PASS" if bool((score.notna() & ~M).to_numpy().sum() == 0) else "FAIL",
                              "values_off_membership": int((score.notna() & ~M).to_numpy().sum()), "values_on": int(score[s].notna().to_numpy().sum())}
    validity["coverage"], B = block_coverage(score, s, m, kept, block_min_names)
    checks = ("reproduction", "r50_reproduction", "universe_file", "known_at", "hour_check", "recompute", "construction", "membership", "coverage")
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in checks) else "FAIL"
    if validity["status"] != "PASS":
        return _void_r65(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    del fr["F_all"], fr["F_kept"], fr["F_desc"]

    # ρ and the described rows; score3 on R64's Korean frame where it exists
    rho_v, rho_daily = rho(cb_dev, bx5, fall, s)
    validity["rho"] = rho_v
    feats = {SCORE: score, DEV: cb_dev, BXF: SF[BXF], SCF: SF[SCF], SCO: SF[SCO]}
    if kr_csv is not None and kr_path is not None and Path(kr_csv).exists() and Path(kr_path).exists():
        print("score3: R64's Korean frame as a third rank (described)…", flush=True)
        L64 = r64_list(kr_csv)
        frk = frames(L64, "krw", kr_path, slices, mult, members_csv, start, end)
        kr_dev = frk["F"][DEV]
        del frk
        feats[S3] = score3_frame(cb_dev, bx5, kr_dev, fall)
        validity["score3"] = {"kr_list": {"path": str(kr_csv), "md5": L64["md5"], "n_kept": L64["n_kept"]}, "cells": int(feats[S3][s].notna().to_numpy().sum()),
                              "names": int(feats[S3][s].notna().any().sum())}
        del kr_dev
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    B.to_parquet(out_dir / "blocks.parquet", index=False)
    head = _head_r65(validity, taker_bps, maker_bps, fee_source)

    # the screen; the nulls on the score
    print("screen: the score; each input alone, the halves apart, score3…", flush=True)
    sc, daily = ceiling.ic_screen(D, feats, set())
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}
    print(f"nulls on {SCORE}: {draws} day shuffles and {draws} whole-day shifts…", flush=True)
    null_shuffle, null_shift = Parallel(n_jobs=min(jobs, 2) if jobs > 1 else 1)(
        [delayed(_null_feature)(SCORE, score[s], Zs, Zr, draws, seed), delayed(shift_feature)(SCORE, score, D, s, draws, seed, shift_min)])

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
        if r["feature"] == SCORE and r["bet"] in ("directional", "relative") and r["horizon"] in HZ:
            rows.loc[i, "p_single_shuffle"] = single_p(null_shuffle, r["bet"], SCORE, r["horizon"], r["t"])
            rows.loc[i, "p_single_shift"] = single_p(null_shift, r["bet"], SCORE, r["horizon"], r["t"])
    cells = [(SCORE, h) for h in FAMILY_HZ]
    fam_rows = rows[(rows["bet"] == BET) & (rows["feature"] == SCORE) & rows["horizon"].isin(FAMILY_HZ)]
    t_real = {(r["feature"], r["horizon"]): r["t"] for _, r in fam_rows.iterrows()}
    pf1, b1 = family_p(null_shuffle, cells, t_real)
    pf2, b2 = family_p(null_shift, cells, t_real)
    for i, r in fam_rows.iterrows():
        rows.loc[i, ["p_fw_shuffle", "p_fw_shift"]] = [pf1[r["feature"], r["horizon"]], pf2[r["feature"], r["horizon"]]]
    rows["p_family"] = rows[["p_fw_shuffle", "p_fw_shift"]].max(axis=1)
    rows["verdict"] = ""
    for i, r in rows.loc[fam_rows.index].iterrows():
        v = verdict_r62(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]))
        rows.loc[i, "verdict"] = v if r["horizon"] == PRIMARY else v + " (reported, not gated)"
    cons = validity["construction"]
    words = {DEV: "described (R62's input alone — the same frame, R62's row)",
             BXF: f"described (−bx_1h alone on the fall bars only, {cons['bars_fall']:,} of {cons['bars_scored']:,} scored bars; R50 / R63's sign made positive)",
             SCF: "described (the score on the fall bars only)", SCO: "described (the score on the other bars only — cbprem_dev's rank there)",
             S3: "described (the three-rank score with R64's Korean deviation; the Korean quantity has no reachable bar at its horizon)"}
    for f_, w in words.items():
        rows.loc[rows["feature"] == f_, "verdict"] = w
    bi = block_ics(daily, m, feature=SCORE)

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    pd.DataFrame({"horizon": list(bars_taker), "ic_needed_taker_members": list(bars_taker.values()), "bar_maker_twelve": BAR_TWELVE, "cost_cover": cost_cover}).to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    rho_daily.to_parquet(out_dir / "rho.parquet", index=False)
    names = pd.DataFrame({"symbol": cols, "cells_score": score[s].notna().sum().to_numpy(), "cells_fall": SF[SCF][s].notna().sum().to_numpy(),
                          "score_mean": score[s].mean().to_numpy(), "bx_fall_mean": SF[BXF][s].mean().to_numpy()})
    names[names["cells_score"] > 0].to_parquet(out_dir / "names.parquet", index=False)
    B.merge(bi, on="block", how="left").to_parquet(out_dir / "blocks.parquet", index=False)

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker_twelve", "bar_taker_members", "verdict"]
    g = rows[(rows["feature"] == SCORE) & (rows["bet"] == BET) & (rows["horizon"] == PRIMARY)].iloc[0]
    md = head + [f"\n## Verdict by R65's gate — `{SCORE}`, {BET}, {PRIMARY}, on the kept members: **{g['verdict']}**\n",
                 f"\nIC {g['ic']:+.4f} (t {g['t']:+.2f}, se {g['ic_se']:.4f}, MDE {g['ic_mde']:.4f}); p_family {g['p_family']:.3f} (day shuffles {g['p_fw_shuffle']:.3f}, whole-day "
                 f"shifts {g['p_fw_shift']:.3f}; single {g['p_single_shuffle']:.3f} / {g['p_single_shift']:.3f}); F1 {g['ic_F1']:+.4f}, F2 {g['ic_F2']:+.4f} "
                 f"({'same sign' if g['folds_same_sign'] else 'signs differ'}); months the same sign {g['months_same_sign']:.2f}; the gate's bar {BAR_TWELVE} (the twelve's "
                 f"maker bar at {PRIMARY}, a number); the members' own taker bar {bars_taker[PRIMARY]:.4f} (the cost proxy covers {cost_cover:.0%} of the scored cells); "
                 f"the registered sign {'positive' if R62_SIGN > 0 else 'negative'}. ρ (the inputs' per-bar rank correlation on the fall bars) {rho_v['rho_mean']:+.3f} "
                 f"(median {rho_v['rho_median']:+.3f}, sd {rho_v['rho_sd']:.3f}, {rho_v['bars']:,} bars); the fall half {cons['fall_share']:.1%} of the scored bars.\n"]
    fam = (rows["feature"] == SCORE) & rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])
    inputs = rows["feature"].isin([DEV, BXF, SCF, SCO]) & rows["bet"].isin(["directional", "relative"]) & rows["horizon"].isin(HZ)
    md += ["\n## The family (relative, 4h / 1d) with the directional bet and 1h beside — the registered feature\n",
           "`p_fw_*` = the share of a null's draws whose largest |t| over the TWO family cells is at or above the real |t|; `p_single_*` = the cell alone; `p_family` = the larger "
           "of the two nulls' family-wise p. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. `bar_maker_twelve` = the gate's number; `bar_taker_members` = "
           "the members' taker bar from their cost proxy at the horizon.\n", show(rows[fam][cols_show]), "\n",
           "\n## Each input alone on the score's cells, and the score on each half (described, no nulls)\n", show(rows[inputs][cols_show[:12] + ["bar_taker_members", "verdict"]]), "\n",
           "\n## The construction and ρ\n", "```\n", json.dumps({"construction": cons, "rho": rho_v}, indent=1, default=str), "\n```\n",
           "\n## Described beside: score3 (the Korean rank as a third), 15m and the vol bet of every row\n",
           show(rows[~fam & ~inputs][cols_show[:12] + ["bar_taker_members", "verdict"]]), "\n",
           "\n## The nulls' family bars (largest |t| over the two cells, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           f"\n## By block — the kept members present and the relative {PRIMARY} IC of the score inside the block (described)\n",
           show(B.merge(bi, on="block", how="left").assign(block=lambda d: d["block"].dt.date)), "\n"]
    out_md.write_text("".join(md))
    print(f"{SCORE} {BET} {PRIMARY} on the members: {g['verdict']}; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


def _head_r65(validity: dict, taker_bps, maker_bps, fee_source) -> list[str]:
    return [f"# R65 — two under-bar facts as one score: `cbprem_dev` and −`bx_1h` after a BTC fall on the screener's F1+F2 members (`ft2 ceiling --target pairs --family score --universe members`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed) on the members' cells — R62's frame; every source cut at {ceiling.END:%Y-%m-%d}. The universe "
            f"`{validity['universe_file']['path']}` (md5 {validity['universe_file']['md5']}, {validity['universe_file']['n_kept']} kept); the members "
            f"`{validity['members_file']['path']}` (md5 {validity['members_file']['md5']}). Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void_r65(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source):
    validity["status"] = "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head_r65(validity, taker_bps, maker_bps, fee_source) + ["\n**The read is VOID: no row of the score was computed on the members.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)
