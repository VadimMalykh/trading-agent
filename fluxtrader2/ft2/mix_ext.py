"""R73 (P8 decision BR1, 2026-11-01, docs/PLAN.md §8) — the participant MIX per member at one day: R62's screen on the screener's F1+F2
members with the trade COUNT and the mean trade SIZE of the perpetual and Binance spot TOGETHER (`data/perp_mix_1h.parquet`, DATA.md
`perp_mix_1h`; `data/spot_1h.parquet`, DATA.md `spot_1h`), on R68's frozen list of names with both markets.

The registered features, on the hourly grid of `ts_known` and then P2's 5m panel through R62's `to_panel` (MARGIN one 5m bar, STALE 2 h):
  mix_cnt24_dev    DEV(log cnt24), cnt24 = Σ over the last 24 hourly bars (≥ 20 present) of the hour's perp count + spot count (NaN where
                   either market's bar is missing); DEV = cb_ext's form on the hourly grid (MONTH 720, MIN_MONTH 360);
  mix_size24_dev   DEV(log size24), size24 = qv24 / cnt24 with qv24 = Σ (perp quote volume + spot quote volume) over the same bars.
ONE mechanism, TWO signs: a swarm of small trades is MORE trades and SMALLER trades and the name GIVES BACK — the count's sign NEGATIVE,
the size's POSITIVE (SIGN). The family = the two features × 1d on the RELATIVE bet (two cells); both nulls at DRAWS on each feature at
1h / 4h / 1d; p_family = the larger of the two nulls' family-wise p over the two 1d cells; the gate R62's (`verdict_r62` with each cell's
sign). Described beside, no nulls, no verdict: each market alone (`*_perp`, `*_spot`), the magnitude control `mix_qv24_dev` (the two
markets' trailing-day dollar volume against its month), the hourly forms `mix_cnt_dev` / `mix_size_dev`, the levels `mix_cnt24` /
`mix_size24` (log), the correlations on the scored cells.

Validity, read first in the registered order, void (exit 2) on any FAIL: (1) the lists' md5 and the frozen list's self-consistency, the
perp table's fingerprint against DATA.md (PERP_FP), the spot table's rows and symbols (SPOT_FP); (7) the nulls' admissibility; (2) R62's
saved screen reproduced through `cb_ext.frames` on the Coinbase source (no nulls) and R60's saved bar; (3) N_CHECK scored member cells
recomputed straight from the two tables' rows by cumulative sums; (4) known-at — no cell read early, none older than STALE; (5)
membership and block coverage on EACH feature; (6) the bar. R62's and R68's helpers are called, none edited.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cb_ext as cx
from . import ceiling, coinbase as cb, folds, mix, spot
from .book_ext import SHIFT_MIN, fold_ics, shift_feature, taker_bar
from .cb_ext import BAR_TOL, BAR_TWELVE, BET, BLOCK_MIN_NAMES, HZ, MARGIN, MEMBERS_SLICES, MEMBERS_START, MIN_MONTH, MONTH, N_CHECK, PRIMARY, STALE
from .ceiling import HORIZONS, MDE_K, NULL_GAP, Z_CLIP, _null_feature
from .spot_ext import GAP_MIN, SHIFT_FLOOR, TOL_HAND, _win_mean_sd, _win_sum, r68_list

CNT, SIZE = "mix_cnt24_dev", "mix_size24_dev"                       # registered
REGISTERED = (CNT, SIZE)
SIGN = {CNT: -1.0, SIZE: +1.0}                                       # a swarm of small trades gives back: more trades → −, smaller trades → + (size low → fall)
QV = "mix_qv24_dev"                                                  # described: the magnitude control (the two markets' dollar volume against its month)
PERP = {CNT: "mix_cnt24_dev_perp", SIZE: "mix_size24_dev_perp"}     # described: each market alone
SPOT = {CNT: "mix_cnt24_dev_spot", SIZE: "mix_size24_dev_spot"}
HOURLY = {CNT: "mix_cnt_dev", SIZE: "mix_size_dev"}                 # described: the hour's own count / size against the month
LEVEL = {CNT: "mix_cnt24", SIZE: "mix_size24"}                      # described: the trailing-day levels (log)
DESCRIBED = [QV, PERP[CNT], PERP[SIZE], SPOT[CNT], SPOT[SIZE], HOURLY[CNT], HOURLY[SIZE], LEVEL[CNT], LEVEL[SIZE]]
ALL = list(REGISTERED) + DESCRIBED
FAMILY_CELLS = [(CNT, PRIMARY), (SIZE, PRIMARY)]
DAY, MIN_DAY = spot.DAY, spot.MIN_DAY
HOUR = pd.Timedelta("1h")
R68_CSV = Path(__file__).with_name("spot_members_r68.csv")
OUT_MD = Path("output/ceiling_mix_members.md")
OUT_DIR = Path("output/ceiling_mix_members")
# the tables as audited BEFORE this module (DATA.md `perp_mix_1h` / `spot_1h`): validity (1) compares the run's tables with these
PERP_FP = {"rows": 5_005_729, "symbols": 310, "first": "2021-11-01 00:00:00+00:00", "last": "2025-12-31 23:00:00+00:00", "count_sum": 85_595_190_688,
           "quote_volume_sum": 22_598_540_430_854.01}            # the VM audit 2026-11-01 (output/perp_mix_audit.md; DATA.md `perp_mix_1h`)
SPOT_FP = {"rows": 6_279_915, "symbols": 272}


# ---- the grids and the frames ----------------------------------------------------------------------------------------------------------
def _pivot(d: pd.DataFrame, col: str, grid: pd.DatetimeIndex, names: list[str]) -> pd.DataFrame:
    return d.pivot_table(index="ts_known", columns="symbol", values=col, aggfunc="last").reindex(index=grid, columns=names)


def grids_mix(names: list[str], perp_path: Path | str, spot_path: Path | str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """On the hourly grid (ts_known × name) inside (start − 2 h, end]: the two markets' counts and quote volumes, their sum, the trailing-day
    sums (≥ 20 of 24), the log levels and every DEV form, keyed by the feature names; and the raw rows per table (for the hand check)."""
    a0 = start - 2 * HOUR
    P = mix.load(perp_path)
    P = P[P["symbol"].isin(names) & (P["ts_known"] > a0) & (P["ts_known"] <= end)]
    S = spot.load(spot_path)
    S = S[S["symbol"].isin(names) & (S["ts_known"] > a0) & (S["ts_known"] <= end)]
    grid = pd.date_range(a0.ceil("h") + HOUR, end.floor("h"), freq="h")
    pc, pq = _pivot(P, "count", grid, names).astype(float), _pivot(P, "quote_volume", grid, names)
    sc, sq = _pivot(S, "count", grid, names).astype(float), _pivot(S, "quote_volume", grid, names)
    cnt, qv = pc + sc, pq + sq                                          # NaN where either market's bar is missing (the two together)
    roll = lambda x: x.rolling(DAY, min_periods=MIN_DAY).sum()          # noqa: E731
    pos = lambda x: x.where(x > 0)                                      # noqa: E731
    cnt24, qv24 = roll(cnt), roll(qv)
    pc24, pq24, sc24, sq24 = roll(pc), roll(pq), roll(sc), roll(sq)
    G = {CNT: spot.dev(np.log(pos(cnt24))), SIZE: spot.dev(np.log(pos(qv24 / pos(cnt24)))), QV: spot.dev(np.log(pos(qv24))),
         PERP[CNT]: spot.dev(np.log(pos(pc24))), PERP[SIZE]: spot.dev(np.log(pos(pq24 / pos(pc24)))),
         SPOT[CNT]: spot.dev(np.log(pos(sc24))), SPOT[SIZE]: spot.dev(np.log(pos(sq24 / pos(sc24)))),
         HOURLY[CNT]: spot.dev(np.log(pos(cnt))), HOURLY[SIZE]: spot.dev(np.log(pos(qv / pos(cnt)))),
         LEVEL[CNT]: np.log(pos(cnt24)), LEVEL[SIZE]: np.log(pos(qv24 / pos(cnt24)))}
    return G, {"perp": P, "spot": S}


def frames_mix(L: dict, perp_path: Path | str, spot_path: Path | str, slices: tuple[str, ...], members_csv: Path | str | None,
               start: pd.Timestamp = MEMBERS_START, end: pd.Timestamp | None = None) -> dict:
    """R62's members' frame on the mix source: the panel on the kept names, every frame on P2's 5m cells masked to the kept names and to
    membership, the used hours per registered feature, the hourly grids, the membership mask and rows, the raw rows."""
    kept = L["kept"]
    end = end or ceiling.END
    Pn = cx.member_panel(kept, start, end, slices)
    D = ceiling.derive(Pn)
    idx, cols, s = D["lr"].index, list(D["lr"].columns), D["scored"]
    G, rows = grids_mix(kept, perp_path, spot_path, start, end)
    F_all = {k: cx.to_panel(G[k], idx, cols) for k in ALL}
    M, m = cx.membership(idx, cols, members_csv)
    F = cx.mask_members(cx.restrict(F_all, kept), M)
    U = {k: cx.used_hours(G[k], idx, cols) for k in REGISTERED}
    return {"kept": kept, "P": Pn, "D": D, "idx": idx, "cols": cols, "s": s, "F_all": F_all, "F": F, "U": U, "G": G, "M": M, "m": m, "rows": rows}


# ---- validity (3): the features by hand ----------------------------------------------------------------------------------------------
def hand_series(perp_rows: pd.DataFrame, spot_rows: pd.DataFrame, grid: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """One name's two registered features on `grid` from its rows in the two tables, by cumulative sums — not pandas' rolling."""
    p, s_ = perp_rows.set_index("ts_known"), spot_rows.set_index("ts_known")
    pc, pq = p["count"].reindex(grid).to_numpy(dtype=float), p["quote_volume"].reindex(grid).to_numpy(dtype=float)
    sc, sq = s_["count"].reindex(grid).to_numpy(dtype=float), s_["quote_volume"].reindex(grid).to_numpy(dtype=float)
    cnt, qv = pc + sc, pq + sq
    cnt24, qv24 = _win_sum(cnt, DAY, MIN_DAY), _win_sum(qv, DAY, MIN_DAY)
    with np.errstate(divide="ignore", invalid="ignore"):
        lc = np.where(cnt24 > 0, np.log(cnt24), np.nan)
        size = np.where((cnt24 > 0) & (qv24 > 0), qv24 / cnt24, np.nan)
        ls = np.where(size > 0, np.log(size), np.nan)
        out = {}
        for k, x in ((CNT, lc), (SIZE, ls)):
            m, sd = _win_mean_sd(x, MONTH, MIN_MONTH)
            out[k] = (x - m) / sd
    return out


def hand_check(fr: dict, n_check: int = N_CHECK, seed: int = 0, tol: float = TOL_HAND) -> dict:
    """Validity (3): `n_check` random scored MEMBER cells of kept names — the frame's value of each registered feature equals the hand
    series' value at the used hour (the latest hour ≤ t − MARGIN with a value, at most STALE hours before it; NaN = NaN when none)."""
    F, U, s, idx, kept, G, M = fr["F"], fr["U"], fr["s"], fr["idx"], fr["kept"], fr["G"], fr["M"]
    grid = G[CNT].index
    sidx = idx[s]
    cols = [c for c in kept if c in F[CNT].columns]
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
            series[c] = hand_series(fr["rows"]["perp"][fr["rows"]["perp"]["symbol"] == c], fr["rows"]["spot"][fr["rows"]["spot"]["symbol"] == c], grid)
        th = int(((t - MARGIN).floor("h") - g0) / HOUR)
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
    return {"status": "PASS" if worst <= tol and len(ii) == n_check else "FAIL", "recomputed": int(len(ii)), "cells_with_a_value": n_val, "cells_nan_both": n_nan,
            "max_abs_diff": float(worst), "names_checked": len(series), "tol": tol}


def known_at(fr: dict) -> dict:
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


def table_check(perp_path: Path | str, spot_path: Path | str, perp_fp: dict | None, spot_fp: dict | None) -> dict:
    """Validity (1), the tables: the perp table's fingerprint equals the audited one (DATA.md `perp_mix_1h`); the spot table's rows and
    symbols equal DATA.md `spot_1h`'s. A missing expectation is a FAIL (the audit must come first)."""
    fp = mix.fingerprint(mix.load(perp_path))
    sd = pd.read_parquet(spot_path, columns=["symbol"])
    sfp = {"rows": int(len(sd)), "symbols": int(sd["symbol"].astype(str).nunique())}
    ok_p = perp_fp is not None and all(fp.get(k) == perp_fp.get(k) for k in ("rows", "symbols", "first", "last", "count_sum")) and abs(fp["quote_volume_sum"] - perp_fp["quote_volume_sum"]) <= 1.0
    ok_s = spot_fp is not None and sfp == {k: spot_fp[k] for k in ("rows", "symbols")}
    return {"status": "PASS" if ok_p and ok_s else "FAIL", "perp": {"path": str(perp_path), "fingerprint": fp, "expected": perp_fp},
            "spot": {"path": str(spot_path), "fingerprint": sfp, "expected": spot_fp}}


# ---- the run ------------------------------------------------------------------------------------------------------------------------
def describe_names(fr: dict) -> pd.DataFrame:
    F, s, kept, G, rows = fr["F"], fr["s"], fr["kept"], fr["G"], fr["rows"]
    out = []
    for c in kept:
        if c not in F[CNT].columns:
            continue
        p, sp = rows["perp"][rows["perp"]["symbol"] == c], rows["spot"][rows["spot"]["symbol"] == c]
        j = p[["ts_known", "count", "quote_volume"]].merge(sp[["ts_known", "count", "quote_volume"]], on="ts_known", suffixes=("_p", "_s"))
        tot = j["count_p"] + j["count_s"]
        out.append({"symbol": c, "cells": int(F[CNT][s][c].notna().sum()), "cover_cnt": float(F[CNT][s][c].notna().mean()), "cover_size": float(F[SIZE][s][c].notna().mean()),
                    "hours_both": int(len(j)), "perp_count_per_hour_median": float(p["count"].median()) if len(p) else np.nan, "spot_count_per_hour_median": float(sp["count"].median()) if len(sp) else np.nan,
                    "spot_share_of_count_median": float((j["count_s"] / tot.where(tot > 0)).median()) if len(j) else np.nan,
                    "size_usdt_median": float(((j["quote_volume_p"] + j["quote_volume_s"]) / tot.where(tot > 0)).median()) if len(j) else np.nan,
                    "cnt24_dev_sd": float(F[CNT][s][c].std()), "size24_dev_sd": float(F[SIZE][s][c].std()), "cnt24_log_mean": float(F[LEVEL[CNT]][s][c].mean()), "size24_log_mean": float(F[LEVEL[SIZE]][s][c].mean())})
    return pd.DataFrame(out)


def _head(validity: dict, taker_bps, maker_bps, fee_source) -> list[str]:
    u = validity["lists"]["universe"]
    return [f"# R73 — the participant mix per member at one day: the screener's F1+F2 members (`ft2 ceiling --target pairs --family mix --universe members`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed) on the members' cells (a name's cells while a member of the bar's block); every source cut at "
            f"{ceiling.END:%Y-%m-%d}. The universe `{u['path']}` (md5 {u['md5']}, {u['n_kept']} kept — a spot market beside the perpetual). "
            f"The quantities: `{CNT}` the trailing-day trade COUNT of the perpetual and the spot market together, log, against its trailing month (sign {SIGN[CNT]:+.0f}); "
            f"`{SIZE}` the trailing-day mean trade SIZE (quote volume ÷ count), log, against its trailing month (sign {SIGN[SIZE]:+.0f}). "
            f"Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source):
    validity["status"] = "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head(validity, taker_bps, maker_bps, fee_source) + ["\n**The read is VOID: no row of a registered feature was computed on the members.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)


def run_r73(taker_bps: float, maker_bps: float, fee_source: str, draws: int = ceiling.DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN, jobs: int = 1,
            perp_path: Path | str = mix.PARQUET, spot_path: Path | str = spot.PARQUET, cb_path: Path | str = cb.MEMBERS_PARQUET, r62: Path = cx.MEMBERS_OUT_DIR,
            csv: Path | str = R68_CSV, cb_csv: Path | str = cx.R62_CSV, members_csv: Path | str | None = None, slices: tuple[str, ...] = MEMBERS_SLICES,
            mult: dict[str, float] | None = None, n_check: int = N_CHECK, start: pd.Timestamp = MEMBERS_START, end: pd.Timestamp | None = None,
            block_min_names: int = BLOCK_MIN_NAMES, r60: Path = cx.OUT_DIR, gap: int = NULL_GAP, shift_floor: int = SHIFT_FLOOR, perp_fp: dict | None = None,
            spot_fp: dict | None = None, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    from joblib import Parallel, delayed
    from .universe import MEMBERS_CSV
    out_dir.mkdir(parents=True, exist_ok=True)
    end = end or ceiling.END
    perp_fp = PERP_FP if perp_fp is None else perp_fp
    spot_fp = SPOT_FP if spot_fp is None else spot_fp
    L = r68_list(csv)
    kept = L["kept"]
    mcsv = Path(members_csv or MEMBERS_CSV)
    Lcb = cx.r62_list(cb_csv)
    validity = {"registration": "R73", "folds": list(folds.EXPLORATION), "draws": draws, "seed": seed, "shift_min": shift_min, "gap": gap, "sources": {"perp": str(perp_path), "spot": str(spot_path)},
                "lists": {"universe": {"path": str(csv), "md5": L["md5"], "n_kept": L["n_kept"], "n_rows": L["n_rows"], "with_series": L["with_series"], "consistent": L["consistent"]},
                          "members": {"path": str(mcsv), "md5": hashlib.md5(mcsv.read_bytes()).hexdigest()},
                          "r62": {"path": str(cb_csv), "md5": Lcb["md5"], "n_kept": Lcb["n_kept"]},
                          "status": "PASS" if L["consistent"] and L["n_kept"] > 0 else "FAIL"},
                "gate": {"bar_twelve": BAR_TWELVE, "sign": SIGN, "family": FAMILY_CELLS, "p_max": 0.05}}
    # (1) the tables' fingerprints; (7) the nulls' admissibility — both known before anything is read
    validity["tables"] = table_check(perp_path, spot_path, perp_fp, spot_fp)
    validity["nulls"] = {"status": "PASS" if shift_min > shift_floor and gap >= GAP_MIN else "FAIL", "shift_min": shift_min, "shift_floor": shift_floor, "gap": gap, "gap_min": GAP_MIN}
    if validity["lists"]["status"] != "PASS" or validity["tables"]["status"] != "PASS" or validity["nulls"]["status"] != "PASS":
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

    # the mix frame; (3) by hand, (4) known-at, (5) membership and coverage — before any IC
    print("the members' panel and the mix frames…", flush=True)
    fr = frames_mix(L, perp_path, spot_path, slices, members_csv, start, end)
    D, idx, cols, s, F, M, m = fr["D"], fr["idx"], fr["cols"], fr["s"], fr["F"], fr["M"], fr["m"]
    sidx = idx[s]
    validity |= {"scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))), "names_in_panel": len(cols), "first": str(sidx[0]), "last": str(sidx[-1]),
                 "kept_in_panel": int(sum(c in cols for c in kept)), "kept_with_a_value": int(sum(F[CNT][s][c].notna().any() for c in kept if c in cols))}
    print("validity (3): the features by hand…", flush=True)
    validity["hand"] = hand_check(fr, n_check, seed)
    validity["known_at"] = known_at(fr)
    off = {k: int((F[k].notna() & ~M).to_numpy().sum()) for k in REGISTERED}
    validity["membership"] = {"status": "PASS" if sum(off.values()) == 0 else "FAIL", "values_off_membership": off,
                              "values_on": {k: int(F[k][s].notna().to_numpy().sum()) for k in REGISTERED}}
    validity["coverage"], B = cx.block_coverage(F[CNT], s, m, kept, block_min_names)
    cov2, _ = cx.block_coverage(F[SIZE], s, m, kept, block_min_names)
    validity["coverage_size"] = cov2
    corr = {}
    for a, b in ((CNT, SIZE), (CNT, QV), (SIZE, QV)):
        both = (F[a][s].notna() & F[b][s].notna()).to_numpy()
        corr[f"{a}_x_{b}"] = {"corr": float(pd.Series(F[a][s].to_numpy()[both]).corr(pd.Series(F[b][s].to_numpy()[both]))) if both.sum() > 2 else np.nan, "cells": int(both.sum())}
    validity["features_corr_on_scored_cells"] = corr
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in ("lists", "tables", "nulls", "reproduction", "hand", "known_at", "membership", "coverage", "coverage_size")) \
        and validity["gate"]["bar_status"] == "PASS" else "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    if validity["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    B.to_parquet(out_dir / "blocks.parquet", index=False)
    head = _head(validity, taker_bps, maker_bps, fee_source)

    print("screen: the two registered features; each market alone, the volume, the hourly forms and the levels beside…", flush=True)
    sc, daily = ceiling.ic_screen(D, {k: F[k] for k in ALL}, set())
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}
    print(f"nulls on {CNT} and {SIZE}: {draws} day shuffles and {draws} whole-day shifts each…", flush=True)
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
        rows.loc[i, "verdict"] = cx.verdict_r62(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), BAR_TWELVE, SIGN[r["feature"]])
    rep = rows["feature"].isin(REGISTERED) & (rows["horizon"] != PRIMARY) & rows["bet"].isin(["directional", "relative"]) & rows["horizon"].isin(HZ)
    rows.loc[rep, "verdict"] = "reported, not gated"
    words = {QV: "described (the magnitude control: the two markets' trailing-day quote volume against its month — the record's dvol at a day)",
             PERP[CNT]: "described (the perpetual's count alone)", PERP[SIZE]: "described (the perpetual's mean size alone)",
             SPOT[CNT]: "described (the spot market's count alone)", SPOT[SIZE]: "described (the spot market's mean size alone)",
             HOURLY[CNT]: "described (the HOURLY count against its month)", HOURLY[SIZE]: "described (the HOURLY mean size against its month)",
             LEVEL[CNT]: "described (the trailing-day count, log — the level)", LEVEL[SIZE]: "described (the trailing-day mean size, log — the level)"}
    for f_, w in words.items():
        rows.loc[rows["feature"] == f_, "verdict"] = w
    bi = {k: cx.block_ics(daily, m, feature=k) for k in REGISTERED}

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    pd.DataFrame({"horizon": list(bars_taker), "ic_needed_taker_members": list(bars_taker.values()), "bar_maker_twelve": BAR_TWELVE, "cost_cover": cost_cover}).to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    desc.to_parquet(out_dir / "names.parquet", index=False)
    Bb = B.merge(bi[CNT].rename(columns={"ic": "ic_cnt24", "se": "se_cnt24", "days": "days_cnt24"}), on="block", how="left") \
          .merge(bi[SIZE].rename(columns={"ic": "ic_size24", "se": "se_size24", "days": "days_size24"}), on="block", how="left")
    Bb.to_parquet(out_dir / "blocks.parquet", index=False)

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker_twelve", "bar_taker_members", "verdict"]
    md = head + [f"\n## Verdict by R73's gate — the two cells, {BET}, {PRIMARY}, on the kept members\n"]
    for k in REGISTERED:
        g = rows[(rows["feature"] == k) & (rows["bet"] == BET) & (rows["horizon"] == PRIMARY)].iloc[0]
        md.append(f"\n- **`{k}` (sign {SIGN[k]:+.0f}): {g['verdict']}** — IC {g['ic']:+.4f} (t {g['t']:+.2f}, se {g['ic_se']:.4f}, MDE {g['ic_mde']:.4f}); p_family {g['p_family']:.3f} (day shuffles "
                  f"{g['p_fw_shuffle']:.3f}, whole-day shifts {g['p_fw_shift']:.3f}; single {g['p_single_shuffle']:.3f} / {g['p_single_shift']:.3f}); F1 {g['ic_F1']:+.4f}, F2 {g['ic_F2']:+.4f} "
                  f"({'same sign' if g['folds_same_sign'] else 'signs differ'}); months the same sign {g['months_same_sign']:.2f}; the interval [{g['ic'] - 1.96 * g['ic_se']:+.4f}, {g['ic'] + 1.96 * g['ic_se']:+.4f}] against the bar {BAR_TWELVE}.\n")
    md.append(f"\nThe gate's bar {BAR_TWELVE} (the twelve's maker bar at {PRIMARY}, a number); the members' own taker bar {bars_taker[PRIMARY]:.4f} (the cost proxy covers {cost_cover:.0%} of the scored cells); "
              f"the registered signs count {SIGN[CNT]:+.0f} / size {SIGN[SIZE]:+.0f}; the correlations on the scored cells: " + ", ".join(f"{k} {v['corr']:+.3f}" for k, v in corr.items()) + ".\n")
    fam = rows["feature"].isin(REGISTERED) & rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])
    md += ["\n## The family (relative, 1d — the two registered features) with 1h / 4h and the directional bet beside\n",
           "`p_fw_*` = the share of a null's draws whose largest |t| over the TWO 1d cells is at or above the real |t|; `p_single_*` = the cell alone; `p_family` = the larger of the two nulls' "
           "family-wise p. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. `bar_maker_twelve` = the gate's number; `bar_taker_members` = the members' taker bar from their cost proxy.\n",
           show(rows[fam][cols_show]), "\n",
           "\n## Described beside (no nulls, no verdict): each market alone, the volume control, the hourly forms, the levels; 15m and the vol bet\n", show(rows[~fam][cols_show[:12] + ["bar_taker_members", "verdict"]]), "\n",
           "\n## The nulls' family bars (largest |t| over the two cells, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           f"\n## By block — the kept members present and the relative {PRIMARY} IC of each feature inside the block (described)\n", show(Bb.assign(block=lambda d_: d_["block"].dt.date)), "\n",
           "\n## The kept names on their member cells\n", show(desc), "\n"]
    out_md.write_text("".join(md))
    print("; ".join(f"{k}: {rows[(rows['feature'] == k) & (rows['bet'] == BET) & (rows['horizon'] == PRIMARY)].iloc[0]['verdict']}" for k in REGISTERED) + f"; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)
