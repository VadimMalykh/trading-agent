"""R47 (PLAN §8): the mechanism behind R45 — is the state's switch in the forecast's skill or in the cross-section's dispersion?

    python scripts/r47_mech.py                       → output/backtest/r47_mech/{mech.md, mech.json, shifts.parquet, daily.parquet,
                                                                               features.csv, by_state.csv, known_at.csv}

Three mechanism rows, each with R45's null (the state series S90 — the sign of the twelve's basket's trailing 90-day move, `market.derive`'s
blr — circularly shifted by every admissible whole-day shift) and a registered sign:
  (a) D_IC   = the held-out forecast's pooled IC (Σ ẑ·z_res / √(Σ ẑ² Σ z_res²), `ceiling._ic_pooled`'s correlation) on R14's SAVED
               forecast cells (`forecast.parquet` of the three runs, no walk, no fit) decided in state +1 minus the same in state −1; sign +.
  (b1) D_disp = the mean cross-sectional sd of the names' next-day move (bps, on the 00:00 UTC daily grid) in state +1 minus −1; sign +.
  (b2) D_ρ    = the mean pairwise correlation of the names' daily moves over the next 30 days in state +1 minus −1; sign −.
Described beside: the dispersion in vol units (the name's move over its trailing-week σ) and the basket's next-day |move| by state; the
IC by state per run; (c) the ceiling's saved daily ICs (`output/ceiling/ic_daily.parquet`, the `relative` bet at 1d) by state, a family
of features with a family-wise p (the `directional` bet described); (d) R45's set A side × state table in R45's weighting and one table
of hedged net / IC / dispersion / correlation by state. Nothing traded or gated, no fold spent, the serve path untouched.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import backtest as bt, ceiling, folds, market as mk  # noqa: E402

OUT = Path("output/backtest")
PER_DAY = 288
MDE_K = ceiling.MDE_K
Z_CLIP = 5.0
# the registered runs (PLAN §8 R47 "Cells"): the saved held-out forecasts of R14's three reads
RUNS = ["r42_check_f12", "r16_ridgebook_1d_ho12_f34", "r42_ridgebook_1d_ho12_f5"]
# validity (1): each run's `forecast.md` "all | all" row — (cells, IC)
RECORD_IC = {"r42_check_f12": (125394, 0.0328), "r16_ridgebook_1d_ho12_f34": (132229, 0.0427), "r42_ridgebook_1d_ho12_f5": (73152, 0.0662)}
SET_A = ["r42_check_f12", "r42_pool/pooled_fills.parquet"]                 # R45's set A, for the described table and validity (2)
BY_STATE_REF = OUT / "r45_state" / "by_state.csv"
CEILING_FILE = Path("output/ceiling/ic_daily.parquet")
FAMILY_BET, DESCRIBED_BET, HORIZON = "relative", "directional", "1d"
SIGNS = {"ic": +1, "disp": +1, "rho": -1}                                   # the registered signs of the mechanism rows
DESCRIBED_ROWS = ("zdisp", "absm")


def _r45():
    spec = importlib.util.spec_from_file_location("r45_state", Path(__file__).resolve().parent / "r45_state.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def s90(P: dict, days: int) -> np.ndarray:
    """R45's S90 on the panel's 5m grid: +1 / −1, 0 where undefined."""
    blr = mk.derive(P)["blr"]
    return np.sign((blr - blr.shift(days * PER_DAY)).fillna(0.0)).to_numpy().astype(int)


def _pooled_ic(a: np.ndarray, b: np.ndarray, c: np.ndarray, m: np.ndarray) -> float:
    if m.sum() < 2:
        return np.nan
    den = np.sqrt(b[m].sum() * c[m].sum())
    return float(a[m].sum() / den) if den > 0 else np.nan


def forecast_cells(run: str, P: dict, hold: int, latency: int) -> tuple[pd.DataFrame, dict]:
    """R14's saved held-out forecast cells of one run with the realised residual z, as `forecast.forecast_report` builds them."""
    d = OUT / run
    o = pd.read_parquet(d / "forecast.parquet")
    meta = json.loads((d / "meta.json").read_text())
    lr = np.log(P["close"])
    y = (lr.shift(-(latency + hold)) - lr.shift(-latency)) * 1e4
    idx, cols = P["close"].index, P["close"].columns
    i, j = idx.get_indexer(pd.DatetimeIndex(o["t"])), cols.get_indexer(o["symbol"].astype(str))
    o = o[(i >= 0) & (j >= 0)].copy()
    i, j = i[(i >= 0) & (j >= 0)], j[(i >= 0) & (j >= 0)]
    o["y_bps"] = y.to_numpy()[i, j]
    o["z"] = np.clip(o["y_bps"] / o["sigma_h"], -Z_CLIP, Z_CLIP)
    o["zhat"] = o["f_bps"] / o["sigma_h"]
    t = pd.DatetimeIndex(o["t"])
    o["fold"] = ""
    for f in meta["folds"]:
        o.loc[folds.mask(pd.Series(t, index=o.index), f).to_numpy(), "fold"] = f
    # the run's own panel ended at its last fold's end (`ceiling.panel` keeps t ≤ end), so a cell whose label window ran past it had no
    # label there and is not in its record: the same cut here, or the record's cell count is missed by one day of the grid (R47's first read)
    run_end = max(folds.bounds(f)[1] for f in meta["folds"])
    o = o[t <= run_end - pd.Timedelta(minutes=5 * (latency + hold))].copy()
    o = o[o["f_bps"].notna() & o["z"].notna() & (o["fold"] != "")].copy()
    o["zres"] = o["z"] - o.groupby("t")["z"].transform("mean")
    o["run"] = run
    o["pos"] = idx.get_indexer(pd.DatetimeIndex(o["t"]))
    return o.reset_index(drop=True), meta


def daily_rows(P: dict, s: np.ndarray, rho_days: int, min_pairs: int) -> pd.DataFrame:
    """The daily grid (00:00 UTC closes): the state at the day's start, the next-day cross-sectional dispersion (bps and vol units), the
    basket's next-day |move|, and the mean pairwise correlation of the names' daily moves over the next `rho_days` days."""
    idx = P["close"].index
    at = idx[(idx.hour == 0) & (idx.minute == 0)]
    pos = idx.get_indexer(at)
    C = P["close"].loc[at]
    lr = np.log(C)
    r = (lr.shift(-1) - lr) * 1e4                                                   # the next day's move, bps
    sig = (np.log(P["close"]).diff() * 1e4).rolling(ceiling.W["1w"], min_periods=int(ceiling.W["1w"] * 0.8)).std().loc[at] * np.sqrt(PER_DAY)
    n = r.notna().sum(axis=1)
    ok = n >= min_pairs
    mean = r.mean(axis=1).where(ok)
    disp = r.sub(mean, axis=0).std(axis=1, ddof=1).where(ok)
    zr = (r / sig).where(sig > 0)
    nz = zr.notna().sum(axis=1)
    zdisp = zr.sub(zr.mean(axis=1), axis=0).std(axis=1, ddof=1).where(nz >= min_pairs)
    R = r.to_numpy()
    rho = np.full(len(at), np.nan)
    for k in range(len(at) - rho_days):
        w = R[k + 1: k + 1 + rho_days]
        full = ~np.isnan(w).any(axis=0)
        if full.sum() >= min_pairs:
            c = np.corrcoef(w[:, full].T)
            m = c.shape[0]
            rho[k] = (c.sum() - np.trace(c)) / (m * (m - 1))
    return pd.DataFrame({"day": at, "pos": pos, "state": s[pos], "names": n.to_numpy(), "disp": disp.to_numpy(), "zdisp": zdisp.to_numpy(),
                         "absm": mean.abs().to_numpy(), "rho": rho})


def _dmean(x: np.ndarray, st: np.ndarray) -> float:
    up, dn = (st > 0) & ~np.isnan(x), (st < 0) & ~np.isnan(x)
    if up.sum() == 0 or dn.sum() == 0:
        return np.nan
    return float(x[up].mean() - x[dn].mean())


def _verdict(D: float, sd: float, p: float, sign: int | None) -> str:
    if not np.isfinite(D) or not sd > 0:
        return "NOT READABLE"
    mde = MDE_K * sd
    if p <= 0.05:
        return "CLEARS" if sign is None or np.sign(D) == sign else "SIGNIFICANT, OPPOSITE SIGN"
    if abs(D) + 1.96 * sd < mde:
        return "CLOSED"
    return "NOT DETECTABLE" if abs(D) < mde else "NOT CLEAR"


def read(runs: list[str], pairs: list[str], start: pd.Timestamp, end: pd.Timestamp, days: int = 90, min_shift: int | None = None,
         name: str = "r47_mech", known_at_draws: int = 20, seed: int = 0, record_ic: dict | None = None, by_state_ref: Path | None = BY_STATE_REF,
         set_a: list[str] | None = None, ceiling_file: Path | None = CEILING_FILE, rho_days: int = 30, hold: int = 288, latency: int = 1,
         min_pairs: int = ceiling.MIN_PAIRS, grid_min: tuple[int, int] = (2300, 2200)) -> dict:
    record_ic = RECORD_IC if record_ic is None else record_ic
    set_a = SET_A if set_a is None else set_a
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    r45 = _r45()
    P = ceiling.panel(pairs, end, start)
    idx = P["close"].index
    s = s90(P, days)
    n = len(idx)
    span_days = int(np.ceil((idx[-1] - idx[0]) / pd.Timedelta(1, "D")))
    min_shift = days if min_shift is None else min_shift
    shifts = np.arange(min_shift, span_days - min_shift + 1)
    if len(shifts) < 10:
        raise SystemExit(f"r47: {len(shifts)} admissible shifts on a span of {span_days} days — not a null")
    validity: dict = {}

    # ---- (a) the forecast cells, validity (1) -------------------------------------------------------------------------------
    cells, rec_rows = [], []
    for run in runs:
        o, meta = forecast_cells(run, P, hold, latency)
        a, b, c = (o["zhat"] * o["zres"]).to_numpy(), (o["zhat"] ** 2).to_numpy(), (o["zres"] ** 2).to_numpy()
        ic_all = _pooled_ic(a, b, c, np.ones(len(o), dtype=bool))
        rec = record_ic.get(run)
        ok = None if rec is None else (len(o) == rec[0] and abs(ic_all - rec[1]) <= 0.001)
        rec_rows.append({"run": run, "folds": "+".join(meta["folds"]), "cells": len(o), "ic": ic_all, "record_cells": None if rec is None else rec[0],
                         "record_ic": None if rec is None else rec[1], "reproduced": "no record" if ok is None else bool(ok)})
        cells.append(o)
    cells = pd.concat(cells, ignore_index=True)
    validity["1_record"] = rec_rows
    validity["1_pass"] = all(r["reproduced"] in (True, "no record") for r in rec_rows)
    pos_c = cells["pos"].to_numpy()
    cells["state"] = s[pos_c]
    A, B, C = (cells["zhat"] * cells["zres"]).to_numpy(), (cells["zhat"] ** 2).to_numpy(), (cells["zres"] ** 2).to_numpy()

    def d_ic(st: np.ndarray) -> float:
        return _pooled_ic(A, B, C, st > 0) - _pooled_ic(A, B, C, st < 0)

    # ---- (b) the daily grid ------------------------------------------------------------------------------------------------
    daily = daily_rows(P, s, rho_days, min_pairs)
    daily.to_parquet(out / "daily.parquet", index=False)
    pos_d = daily["pos"].to_numpy()
    X = {r: daily[r].to_numpy() for r in ("disp", "rho", "zdisp", "absm")}

    # ---- (c) the ceiling's saved daily ICs ----------------------------------------------------------------------------------
    feats = {}
    if ceiling_file is not None and Path(ceiling_file).exists():
        ic = pd.read_parquet(ceiling_file)
        ic = ic[ic["horizon"] == HORIZON]
        for bet in (FAMILY_BET, DESCRIBED_BET):
            x = ic[ic["bet"] == bet]
            if x.empty:
                continue
            piv = x.pivot_table(index="feature", columns="day", values="ic", aggfunc="mean")
            dpos = idx.get_indexer(pd.DatetimeIndex(piv.columns))
            keep = dpos >= 0
            feats[bet] = {"features": list(piv.index), "ic": piv.to_numpy()[:, keep], "pos": dpos[keep], "days": int(keep.sum())}

    def d_feat(bet: str, st: np.ndarray) -> np.ndarray:
        M, up, dn = feats[bet]["ic"], st > 0, st < 0
        if up.sum() == 0 or dn.sum() == 0:
            return np.full(M.shape[0], np.nan)
        return np.nanmean(M[:, up], axis=1) - np.nanmean(M[:, dn], axis=1)

    # ---- validity (2): R45's set A table reproduced; (d) the described tables ---------------------------------------------
    fa = pd.concat([r45._fills(p_) for p_ in set_a], ignore_index=True)
    pa = idx.get_indexer(pd.DatetimeIndex(fa["t"]))
    fa["pos"] = pa
    fa["S90"] = np.where(pa >= 0, s[np.maximum(pa, 0)], 0)
    by = []
    for (st_, fold, side), g in fa[fa["S90"] != 0].groupby([fa["S90"], "fold", "side"]):
        w = g["size"].to_numpy()
        by.append({"S90": int(st_), "fold": fold, "side": int(side), "trades": len(g), "net": float(np.average(g["net_bps"], weights=w)),
                   "hedged_net": float(np.average(g["hedged_net_bps"], weights=w))})
    by = pd.DataFrame(by)
    side_state = []
    for (st_, side), g in fa[fa["S90"] != 0].groupby([fa["S90"], "side"]):
        w = g["size"].to_numpy()
        side_state.append({"S90": int(st_), "side": int(side), "trades": len(g), "net": float(np.average(g["net_bps"], weights=w)),
                           "hedged_net": float(np.average(g["hedged_net_bps"], weights=w))})
    side_state = pd.DataFrame(side_state)
    pd.concat([by.assign(table="by_fold"), side_state.assign(table="side_state")], ignore_index=True).to_csv(out / "by_state.csv", index=False)
    if by_state_ref is not None and Path(by_state_ref).exists():
        ref = pd.read_csv(by_state_ref)
        ref = ref[ref["set"] == "A"][["S90", "fold", "side", "trades", "net", "hedged_net"]].reset_index(drop=True)
        m = ref.merge(by, on=["S90", "fold", "side"], how="outer", suffixes=("_ref", ""))
        same = (len(m) == len(ref) == len(by) and m["trades_ref"].eq(m["trades"]).all()
                and (m["net_ref"] - m["net"]).abs().max() <= 0.01 and (m["hedged_net_ref"] - m["hedged_net"]).abs().max() <= 0.01)
        validity["2_reference"] = {"rows_ref": len(ref), "rows": len(by), "max_abs_diff_net": float((m["net_ref"] - m["net"]).abs().max()),
                                   "max_abs_diff_hedged": float((m["hedged_net_ref"] - m["hedged_net"]).abs().max()), "reproduced": bool(same)}
        validity["2_pass"] = bool(same)
    else:
        validity["2_reference"] = "no reference"
        validity["2_pass"] = True

    # ---- validity (3): known-at on drawn cells; (4) cover; (5) the grid -----------------------------------------------------
    rng = np.random.default_rng(seed)
    pick = rng.choice(np.unique(pos_c), size=min(known_at_draws, len(np.unique(pos_c))), replace=False)
    ka = []
    for p_ in sorted(pick):
        sc = s90({k: v.iloc[: p_ + 1] for k, v in P.items()}, days)
        ka.append({"t": str(idx[p_]), "full": int(s[p_]), "cut": int(sc[-1]), "same": int(s[p_]) == int(sc[-1])})
    pd.DataFrame(ka).to_csv(out / "known_at.csv", index=False)
    validity["3_known_at"] = ka
    validity["3_pass"] = all(r["same"] for r in ka)
    dok = ~np.isnan(X["disp"])
    cover = {"a_cells": float((cells["state"] != 0).mean()), "b_days": float((daily["state"][dok] != 0).mean()) if dok.any() else np.nan}
    for bet in feats:
        cover[f"c_{bet}"] = float((s[feats[bet]["pos"]] != 0).mean())
    validity["4_cover"] = cover
    validity["4_pass"] = all(v >= 0.95 for v in cover.values() if np.isfinite(v))
    validity["5_grid"] = {"days": int(dok.sum()), "rho_windows": int((~np.isnan(X["rho"])).sum())}
    validity["5_pass"] = bool(dok.sum() >= grid_min[0] and (~np.isnan(X["rho"])).sum() >= grid_min[1])
    validity["pass"] = bool(validity["1_pass"] and validity["2_pass"] and validity["3_pass"] and validity["4_pass"] and validity["5_pass"])

    # ---- the statistics and the null ------------------------------------------------------------------------------------
    obs = {"ic": d_ic(cells["state"].to_numpy())}
    obs |= {r: _dmean(X[r], daily["state"].to_numpy()) for r in X}
    fobs = {bet: d_feat(bet, s[feats[bet]["pos"]]) for bet in feats}
    null_rows, fnull = [], {bet: [] for bet in feats}
    for d in shifts:
        sc = s[(pos_c - d * PER_DAY) % n]
        sd_ = s[(pos_d - d * PER_DAY) % n]
        null_rows.append({"shift": int(d), "ic": d_ic(sc), **{r: _dmean(X[r], sd_) for r in X}})
        for bet in feats:
            fnull[bet].append(d_feat(bet, s[(feats[bet]["pos"] - d * PER_DAY) % n]))
    null = pd.DataFrame(null_rows)
    null.to_parquet(out / "shifts.parquet", index=False)

    rows, zs = [], {}
    for r in ("ic", "disp", "rho") + DESCRIBED_ROWS:
        nk, D = null[r].to_numpy(), obs[r]
        sd = float(np.nanstd(nk))
        p = float((1 + np.sum(np.abs(nk) >= abs(D))) / (1 + len(nk))) if np.isfinite(D) else np.nan
        st = cells["state"].to_numpy() if r == "ic" else daily["state"].to_numpy()
        x = None if r == "ic" else X[r]
        mean_up = _pooled_ic(A, B, C, st > 0) if r == "ic" else float(np.nanmean(x[st > 0])) if (st > 0).any() else np.nan
        mean_dn = _pooled_ic(A, B, C, st < 0) if r == "ic" else float(np.nanmean(x[st < 0])) if (st < 0).any() else np.nan
        n_up = int((st > 0).sum()) if r == "ic" else int(((st > 0) & ~np.isnan(x)).sum())
        n_dn = int((st < 0).sum()) if r == "ic" else int(((st < 0) & ~np.isnan(x)).sum())
        sign = SIGNS.get(r)
        rows.append({"row": r, "kind": "mechanism" if r in SIGNS else "described", "sign": sign, "D": D, "null_sd": sd, "p": p, "mde": MDE_K * sd,
                     "n_up": n_up, "n_dn": n_dn, "mean_up": mean_up, "mean_dn": mean_dn, "verdict": _verdict(D, sd, p, sign)})
        if r in SIGNS and np.isfinite(D) and sd > 0:
            zs[r] = (abs(D) / sd, np.abs(nk) / sd)
    res = pd.DataFrame(rows)
    if zs:
        zo = max(v[0] for v in zs.values())
        zn = np.max(np.vstack([v[1] for v in zs.values()]), axis=0)
        family = {"members": len(zs), "z": float(zo), "p_family": float((1 + np.sum(zn >= zo)) / (1 + len(zn)))}
    else:
        family = {"members": 0, "z": np.nan, "p_family": np.nan}

    frows, ffam = [], {}
    for bet in feats:
        N = np.vstack(fnull[bet])                                                    # shifts × features
        sd = np.nanstd(N, axis=0)
        D = fobs[bet]
        with np.errstate(invalid="ignore", divide="ignore"):
            z_obs = np.abs(D) / sd
            z_null = np.abs(N) / sd
        fin = np.isfinite(z_obs) & (sd > 0)
        for k_, f in enumerate(feats[bet]["features"]):
            p = float((1 + np.sum(np.abs(N[:, k_]) >= abs(D[k_]))) / (1 + N.shape[0])) if np.isfinite(D[k_]) else np.nan
            frows.append({"bet": bet, "feature": f, "days": feats[bet]["days"], "D": float(D[k_]), "null_sd": float(sd[k_]), "p": p,
                          "mde": float(MDE_K * sd[k_]), "verdict": _verdict(float(D[k_]), float(sd[k_]), p, None)})
        if fin.any():
            zo = float(np.max(z_obs[fin]))
            zn = np.nanmax(z_null[:, fin], axis=1)
            ffam[bet] = {"members": int(fin.sum()), "z": zo, "p_family": float((1 + np.sum(zn >= zo)) / (1 + len(zn))),
                         "top": feats[bet]["features"][int(np.argmax(np.where(fin, z_obs, -1)))]}
        pd.DataFrame(N, columns=[f"{bet}:{f}" for f in feats[bet]["features"]]).assign(shift=shifts).to_parquet(out / f"shifts_{bet}.parquet", index=False)
    frows = pd.DataFrame(frows)
    frows.to_csv(out / "features.csv", index=False)

    # per run IC by state (described)
    per_run = []
    for run, g in cells.groupby("run", sort=False):
        a, b, c, st = (g["zhat"] * g["zres"]).to_numpy(), (g["zhat"] ** 2).to_numpy(), (g["zres"] ** 2).to_numpy(), g["state"].to_numpy()
        per_run.append({"run": run, "cells": len(g), "ic_all": _pooled_ic(a, b, c, np.ones(len(g), dtype=bool)), "ic_up": _pooled_ic(a, b, c, st > 0),
                        "ic_dn": _pooled_ic(a, b, c, st < 0), "n_up": int((st > 0).sum()), "n_dn": int((st < 0).sum())})
    per_run = pd.DataFrame(per_run)

    # the one table by state
    r_ = res.set_index("row")
    hed = {int(st_): float(np.average(g["hedged_net_bps"], weights=g["size"])) for st_, g in fa[fa["S90"] != 0].groupby("S90")}
    table = pd.DataFrame([{"state": +1, "hedged_net_A": hed.get(1, np.nan), **{r: r_.loc[r, "mean_up"] for r in r_.index}},
                          {"state": -1, "hedged_net_A": hed.get(-1, np.nan), **{r: r_.loc[r, "mean_dn"] for r in r_.index}}])

    v = r_["verdict"]
    market_ = v["disp"] == "CLEARS" or v["rho"] == "CLEARS"
    forecast_ = v["ic"] == "CLEARS"
    reading = ("THE MARKET'S AND THE FORECAST'S" if market_ and forecast_ else "THE MARKET'S" if market_ else "THE FORECAST'S" if forecast_
               else "NOT DETECTABLE AT THIS POWER")
    summary = {"registration": "R47", "name": name, "pairs": pairs, "start": str(start), "end": str(end), "days": days, "span_days": span_days,
               "shifts": int(len(shifts)), "min_shift": int(min_shift), "runs": runs, "rho_days": rho_days, "hold": hold, "latency": latency,
               "validity": validity, "results": res.to_dict("records"), "family": family, "features": {"families": ffam, "rows": len(frows)},
               "per_run": per_run.to_dict("records"), "table": table.to_dict("records"), "side_state": side_state.to_dict("records"),
               "reading": reading}
    (out / "mech.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "mech.md").write_text(_report(summary, res, frows, per_run, table, side_state))
    return summary


def _report(s: dict, res: pd.DataFrame, frows: pd.DataFrame, per_run: pd.DataFrame, table: pd.DataFrame, side_state: pd.DataFrame) -> str:
    v = s["validity"]
    md = [f"# R47 — the mechanism behind R45 (`{s['name']}`)\n",
          f"\nS90 (the basket's trailing {s['days']}-day sign) on `{'`, `'.join(s['pairs'])}` from {s['start'][:10]} to {s['end'][:10]} "
          f"({s['span_days']} days); the null {s['shifts']} whole-day circular shifts ({s['min_shift']} ≤ d ≤ span − {s['min_shift']}); "
          f"the forecast cells of `{'`, `'.join(s['runs'])}` (hold {s['hold']}, latency {s['latency']}); ρ over the next {s['rho_days']} days.\n",
          f"\n## Validity: {'PASS' if v['pass'] else 'FAIL'}\n",
          "\n(1) the record — each run's whole-sample IC against its forecast.md row:\n", pd.DataFrame(v["1_record"]).round(4).to_markdown(index=False),
          f"\n\n(2) R45's set A table: {v['2_reference']}\n",
          f"\n(3) known-at on {len(v['3_known_at'])} drawn cells: {'PASS' if v['3_pass'] else 'FAIL'}\n",
          f"\n(4) cover: {json.dumps({k: round(x, 4) for k, x in v['4_cover'].items()})} → {'PASS' if v['4_pass'] else 'FAIL'}\n",
          f"\n(5) the daily grid: {v['5_grid']} → {'PASS' if v['5_pass'] else 'FAIL'}\n",
          f"\n## The mechanism rows — **{s['reading']}** (family-wise p {s['family']['p_family']:.3f}, max z {s['family']['z']:.2f}, {s['family']['members']} members)\n",
          "\nD = the row in state +1 (after a rising quarter) minus state −1; p two-sided against the shifts; MDE = 2.8 × the null's sd; "
          "a mechanism row clears at p ≤ 0.05 with its registered sign.\n\n", res.round(4).to_markdown(index=False), "\n",
          "\n## The one table by state\n\n", table.round(4).to_markdown(index=False), "\n",
          "\n## R14's held-out IC by state, per run (described)\n\n", per_run.round(4).to_markdown(index=False), "\n",
          "\n## R45's set A by side × state (size-weighted, bps a trade; described)\n\n", side_state.round(2).to_markdown(index=False), "\n"]
    if len(frows):
        for bet, fam in s["features"]["families"].items():
            x = frows[frows["bet"] == bet].sort_values("p")
            md += [f"\n## The ceiling's `{bet}` features at {HORIZON} by state — family-wise p {fam['p_family']:.3f} (max z {fam['z']:.2f} on `{fam['top']}`, "
                   f"{fam['members']} members{'' if bet == FAMILY_BET else '; described'})\n\n", x.round(4).to_markdown(index=False), "\n"]
    return "".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", default=None, help="a run directory under output/backtest with a forecast.parquet; default the registered three")
    ap.add_argument("--pairs", nargs="*", default=None, help="the panel's pairs; default the twelve from r42_ridgebook_1d_ho12_f5/meta.json")
    ap.add_argument("--start", default=None, help="panel start (default backtest.PRE_START)")
    ap.add_argument("--end", default=None, help="panel end (default F5's end)")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-shift", type=int, default=None, help="days; default --days")
    ap.add_argument("--known-at-draws", type=int, default=20)
    ap.add_argument("--name", default="r47_mech")
    ap.add_argument("--no-record", action="store_true", help="validity (1) and (2) without the record (tests)")
    a = ap.parse_args(argv)
    runs = RUNS if a.run is None else a.run
    pairs = a.pairs or json.loads((OUT / "r42_ridgebook_1d_ho12_f5" / "meta.json").read_text())["pairs"]
    start = bt.PRE_START if a.start is None else pd.Timestamp(a.start, tz="UTC")
    end = folds.bounds("F5")[1] if a.end is None else pd.Timestamp(a.end, tz="UTC")
    s = read(runs, pairs, start, end, a.days, a.min_shift, a.name, a.known_at_draws, record_ic={} if a.no_record else None,
             by_state_ref=None if a.no_record else BY_STATE_REF)
    print((OUT / a.name / "mech.md").read_text())
    return s


if __name__ == "__main__":
    main()
