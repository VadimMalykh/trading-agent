"""R49 (PLAN §8): the time of day of R14's decisions — the held-out IC by hour of the decision on R14's SAVED forecast cells, the seen
half (F1–F5) read first and the pre-history (FP+F0) the confirmation half with the signs fixed from the seen half.

    python scripts/r49_hours.py                      → output/backtest/r49_hours/{hours.md, hours.json, seen.json, by_hour.csv, money_by_hour.csv,
                                                                                sessions.csv, by_hour_state.csv, perms_seen.parquet, perms_pre.parquet}

Per hour h (UTC) IC_h is R47's pooled held-out IC (Σ ẑ·z_res / √(Σ ẑ² Σ z_res²)) over the cells decided at h, D_h = IC_h − IC_all. Two rows
on the seen half: (i) the pre-named contrast C_settle = IC on {23, 07, 15} − IC on the other 21 hours (sign +, R46's row); (ii) the family of
24, max_h |z_h|. The null: the 24 hour labels randomly permuted within each day (one permutation a day, 2,000 draws). The confirmation on the
pre-history, read after the seen half: C_settle once (sign +, one-sided); the seen half's CLEARED cells with their seen signs, one-sided, a
family over the cleared set. Described: IC_h per run, the sessions, IC_h × S90, the money by hour. Nothing traded or gated; no walk, no fit,
no fold spent; the serve path untouched.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import backtest as bt, ceiling, folds  # noqa: E402

OUT = Path("output/backtest")
MDE_K = ceiling.MDE_K
H = 24
SEEN_RUNS = ["r42_check_f12", "r16_ridgebook_1d_ho12_f34", "r42_ridgebook_1d_ho12_f5"]
PRE_RUN = "r48_ridgebook_1d_ho12_pre"
PAIRS_FROM = "r42_ridgebook_1d_ho12_f5"                                    # the twelve, R47's panel for the seen half
# validity (1): each run's `forecast.md` "all | all" row — (cells, IC)
RECORD_IC = {"r42_check_f12": (125394, 0.0328), "r16_ridgebook_1d_ho12_f34": (132229, 0.0427), "r42_ridgebook_1d_ho12_f5": (73152, 0.0662),
             PRE_RUN: (215851, 0.0359)}
SEEN_FILLS = ["r42_check_f12/fills_taker.parquet", "r42_pool/pooled_fills.parquet"]
PRE_FILLS = [f"{PRE_RUN}/fills_taker.parquet"]
STATE_DAILY = OUT / "r47_mech" / "daily.parquet"                            # S90 by day, described
SETTLE = (23, 7, 15)                                                        # the hour before a settlement of the 8-hour names (R46)
SESSIONS = {"00-08": range(0, 8), "08-13": range(8, 13), "13-21": range(13, 21), "21-24": range(21, 24)}
MIN_DAYS = {"seen": 1200, "pre": 1090}


def _r47():
    spec = importlib.util.spec_from_file_location("r47_mech", Path(__file__).resolve().parent / "r47_mech.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ic(a: np.ndarray, b: np.ndarray, c: np.ndarray, m: np.ndarray | None = None) -> float:
    if m is not None:
        a, b, c = a[m], b[m], c[m]
    den = np.sqrt(b.sum() * c.sum())
    return float(a.sum() / den) if den > 0 and len(a) > 1 else np.nan


def ic_by_label(a: np.ndarray, b: np.ndarray, c: np.ndarray, lab: np.ndarray) -> np.ndarray:
    sa, sb, sc = (np.bincount(lab, weights=x, minlength=H) for x in (a, b, c))
    with np.errstate(invalid="ignore", divide="ignore"):
        return sa / np.sqrt(sb * sc)


def settle_contrast(a: np.ndarray, b: np.ndarray, c: np.ndarray, lab: np.ndarray, settle: tuple[int, ...]) -> float:
    m = np.isin(lab, settle)
    return _ic(a, b, c, m) - _ic(a, b, c, ~m)


def perm_labels(rng: np.random.Generator, n_days: int, day_idx: np.ndarray, hour: np.ndarray) -> np.ndarray:
    """One random permutation of the 24 hour labels per day; a cell at hour h on day d is called perms[d, h]."""
    perms = rng.permuted(np.tile(np.arange(H), (n_days, 1)), axis=1)
    return perms[day_idx, hour]


def load_cells(runs: list[str], P: dict, hold: int, latency: int, r47, record_ic: dict) -> tuple[pd.DataFrame, list[dict]]:
    cells, rec = [], []
    for run in runs:
        o, meta = r47.forecast_cells(run, P, hold, latency)
        a, b, c = (o["zhat"] * o["zres"]).to_numpy(), (o["zhat"] ** 2).to_numpy(), (o["zres"] ** 2).to_numpy()
        ic_all = _ic(a, b, c)
        r = record_ic.get(run)
        ok = None if r is None else (len(o) == r[0] and abs(ic_all - r[1]) <= 0.001)
        rec.append({"run": run, "folds": "+".join(meta["folds"]), "cells": len(o), "ic": ic_all, "record_cells": None if r is None else r[0],
                    "record_ic": None if r is None else r[1], "reproduced": "no record" if ok is None else bool(ok)})
        cells.append(o)
    cells = pd.concat(cells, ignore_index=True)
    t = pd.DatetimeIndex(cells["t"])
    cells["hour"] = t.hour.astype(int)
    cells["day"] = t.floor("D")
    cells["day_idx"] = pd.factorize(cells["day"], sort=True)[0]
    cells["A"], cells["B"], cells["C"] = cells["zhat"] * cells["zres"], cells["zhat"] ** 2, cells["zres"] ** 2
    return cells, rec


def grid_check(cells: pd.DataFrame, min_days: int) -> dict:
    t = pd.DatetimeIndex(cells["t"])
    per_day = cells.groupby("day_idx")["hour"].nunique()
    n_h = np.bincount(cells["hour"].to_numpy(), minlength=H)
    target = len(cells) / H
    return {"cells": int(len(cells)), "on_the_hour": bool((t.minute == 0).all()), "utc": str(t.tz) == "UTC", "days": int(per_day.size),
            "days_with_24_hours": int((per_day == H).sum()), "share_days_24": float((per_day == H).mean()),
            "max_rel_dev_per_hour": float(np.abs(n_h - target).max() / target), "cells_per_hour_min": int(n_h.min()), "cells_per_hour_max": int(n_h.max()),
            "min_days": min_days}


def half_stats(cells: pd.DataFrame, draws: int, rng: np.random.Generator, settle: tuple[int, ...]) -> dict:
    a, b, c, hr, di = (cells[k].to_numpy() for k in ("A", "B", "C", "hour", "day_idx"))
    n_days = int(di.max()) + 1
    ic_h = ic_by_label(a, b, c, hr)
    ic_all = _ic(a, b, c)
    D = ic_h - ic_all
    C = settle_contrast(a, b, c, hr, settle)
    D_null = np.empty((draws, H))
    C_null = np.empty(draws)
    for k in range(draws):
        lab = perm_labels(rng, n_days, di, hr)
        D_null[k] = ic_by_label(a, b, c, lab) - ic_all
        C_null[k] = settle_contrast(a, b, c, lab, settle)
    sd = D_null.std(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z, z_null = D / sd, D_null / sd
    fam_obs = float(np.nanmax(np.abs(z)))
    fam_null = np.nanmax(np.abs(z_null), axis=1)
    p_h = (1 + (np.abs(D_null) >= np.abs(D)).sum(axis=0)) / (1 + draws)
    q95 = float(np.quantile(fam_null, 0.95))
    p_family = float((1 + np.sum(fam_null >= fam_obs)) / (1 + draws))
    cleared = [int(h) for h in range(H) if p_family <= 0.05 and np.isfinite(z[h]) and abs(z[h]) >= q95]
    C_sd = float(C_null.std())
    C_p2 = float((1 + np.sum(np.abs(C_null) >= abs(C))) / (1 + draws))
    C_p1 = float((1 + np.sum(C_null >= C)) / (1 + draws))                    # one-sided, sign +
    n_h = np.bincount(hr, minlength=H)
    return {"cells": int(len(cells)), "days": n_days, "ic_all": ic_all, "ic_h": ic_h, "D": D, "sd": sd, "z": z, "p_h": p_h, "n_h": n_h,
            "D_null": D_null, "fam_obs": fam_obs, "fam_null": fam_null, "q95": q95, "p_family": p_family, "cleared": cleared,
            "settle": {"D": C, "sd": C_sd, "p_two_sided": C_p2, "p_one_sided": C_p1, "mde": MDE_K * C_sd, "lo": C - 1.96 * C_sd, "hi": C + 1.96 * C_sd,
                       "ic_settle": _ic(a, b, c, np.isin(hr, settle)), "ic_other": _ic(a, b, c, ~np.isin(hr, settle)),
                       "n_settle": int(np.isin(hr, settle).sum()), "n_other": int((~np.isin(hr, settle)).sum())},
            "C_null": C_null}


def _sub_verdict(D: float, sd: float, p: float, sign: int, fact: float) -> str:
    """The confirmation half's sub-verdicts (R48's): CLEARS at p ≤ 0.05 with the sign; REFUTED if the interval lies wholly on the other side
    of half the seen effect; NOT DETECTABLE if |D| < MDE; NOT CLEAR otherwise."""
    if not np.isfinite(D) or not sd > 0:
        return "NOT READABLE"
    if p <= 0.05:
        return "CLEARS"
    if np.isfinite(fact) and sign * (D + sign * 1.96 * sd) < sign * fact / 2:
        return "REFUTED"
    return "NOT DETECTABLE" if abs(D) < MDE_K * sd else "NOT CLEAR"


def confirm(seen: dict, pre: dict) -> dict:
    """The pre-history's confirmation rows, as registered: C_settle once (sign +, one-sided); the seen half's cleared cells with their seen
    signs, one-sided, a family over the cleared set."""
    s = pre["settle"]
    settle = {"row": "settle", "D": s["D"], "sd": s["sd"], "p": s["p_one_sided"], "mde": s["mde"], "lo": s["lo"], "hi": s["hi"], "sign": 1,
              "seen_D": seen["settle"]["D"], "verdict": _sub_verdict(s["D"], s["sd"], s["p_one_sided"], 1, seen["settle"]["D"])}
    cleared = seen["cleared"]
    rows = []
    fam = {"members": len(cleared), "p": np.nan, "z": np.nan, "verdict": "NONE CLEARED ON THE SEEN HALF"}
    if cleared:
        signs = np.array([1 if seen["D"][h] >= 0 else -1 for h in cleared])
        zc = np.array([pre["z"][h] for h in cleared]) * signs
        zn = (pre["D_null"][:, cleared] / pre["sd"][cleared]) * signs
        fam_obs = float(np.nanmax(zc))
        fam_null = np.nanmax(zn, axis=1)
        fam["z"] = fam_obs
        fam["p"] = float((1 + np.sum(fam_null >= fam_obs)) / (1 + len(fam_null)))
        for h, sg in zip(cleared, signs):
            D, sd = float(pre["D"][h]), float(pre["sd"][h])
            p1 = float((1 + np.sum(sg * pre["D_null"][:, h] >= sg * D)) / (1 + pre["D_null"].shape[0]))
            rows.append({"hour": h, "seen_D": float(seen["D"][h]), "seen_z": float(seen["z"][h]), "sign": int(sg), "pre_D": D, "pre_sd": sd,
                         "pre_z": float(pre["z"][h]), "p_one_sided": p1, "mde": MDE_K * sd, "verdict": _sub_verdict(D, sd, p1, int(sg), float(seen["D"][h]))})
        fam["verdict"] = "CLEARS" if fam["p"] <= 0.05 else "NOT CONFIRMED"
    seen_settle_clear = seen["settle"]["p_two_sided"] <= 0.05 and seen["settle"]["D"] > 0
    confirmed = settle["verdict"] == "CLEARS" or (cleared and fam["p"] <= 0.05)
    if confirmed:
        verdict = "CONFIRMED"
    elif not cleared and not seen_settle_clear:
        verdict = "NOTHING TO CONFIRM"
    else:
        verdict = "NOT CONFIRMED"
    return {"settle": settle, "family": fam, "cells": rows, "seen_settle_clear": bool(seen_settle_clear), "verdict": verdict, "confirmed": bool(confirmed)}


def money_by_hour(paths: list[str], draws: int, rng: np.random.Generator, settle: tuple[int, ...]) -> tuple[pd.DataFrame, dict]:
    fr = []
    for p_ in paths:
        f = OUT / p_
        if f.exists():
            x = pd.read_parquet(f).dropna(subset=["net_bps"])
            fr.append(x[["t", "size", "net_bps", "hedged_net_bps", "gross_bps"]])
    if not fr:
        return pd.DataFrame(columns=["hour", "trades", "gross", "net", "hedged_net"]), {}
    f = pd.concat(fr, ignore_index=True)
    t = pd.DatetimeIndex(f["t"])
    f["hour"], f["day_idx"] = t.hour.astype(int), pd.factorize(t.floor("D"), sort=True)[0]
    w, hn, nt, g, hr, di = (f[k].to_numpy() for k in ("size", "hedged_net_bps", "net_bps", "gross_bps", "hour", "day_idx"))
    rows = []
    for h in range(H):
        m = hr == h
        rows.append({"hour": h, "trades": int(m.sum()), "gross": float(np.average(g[m], weights=w[m])) if m.any() else np.nan,
                     "net": float(np.average(nt[m], weights=w[m])) if m.any() else np.nan, "hedged_net": float(np.average(hn[m], weights=w[m])) if m.any() else np.nan})

    def contrast(lab: np.ndarray, x: np.ndarray) -> float:
        m = np.isin(lab, settle)
        if w[m].sum() <= 0 or w[~m].sum() <= 0:
            return np.nan
        return float(np.average(x[m], weights=w[m]) - np.average(x[~m], weights=w[~m]))

    n_days = int(di.max()) + 1
    obs = {k: contrast(hr, x) for k, x in (("gross", g), ("net", nt), ("hedged_net", hn))}
    null = {k: np.empty(draws) for k in obs}
    for k_ in range(draws):
        lab = perm_labels(rng, n_days, di, hr)
        for k, x in (("gross", g), ("net", nt), ("hedged_net", hn)):
            null[k][k_] = contrast(lab, x)
    c = {}
    for k in obs:
        sd = float(np.nanstd(null[k]))
        c[k] = {"D": obs[k], "sd": sd, "p_two_sided": float((1 + np.nansum(np.abs(null[k]) >= abs(obs[k]))) / (1 + draws)) if np.isfinite(obs[k]) else np.nan,
                "trades_settle": int(np.isin(hr, settle).sum()), "trades_other": int((~np.isin(hr, settle)).sum())}
    return pd.DataFrame(rows), c


def _state_by_day(cells: pd.DataFrame, daily: Path | None) -> np.ndarray:
    if daily is None or not Path(daily).exists():
        return np.zeros(len(cells), dtype=int)
    d = pd.read_parquet(daily)[["day", "state"]]
    m = pd.DataFrame({"day": cells["day"]}).merge(d, on="day", how="left")
    return m["state"].fillna(0).to_numpy().astype(int)


def described(cells: pd.DataFrame, state: np.ndarray, label: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    a, b, c, hr = (cells[k].to_numpy() for k in ("A", "B", "C", "hour"))
    per_run = []
    for run, g in cells.groupby("run", sort=False):
        ra, rb, rc, rh = (g[k].to_numpy() for k in ("A", "B", "C", "hour"))
        ich = ic_by_label(ra, rb, rc, rh)
        for h in range(H):
            per_run.append({"half": label, "run": run, "hour": h, "cells": int((rh == h).sum()), "ic": float(ich[h])})
    sess = [{"half": label, "session": k, "cells": int(np.isin(hr, list(v)).sum()), "ic": _ic(a, b, c, np.isin(hr, list(v)))} for k, v in SESSIONS.items()]
    st = []
    for h in range(H):
        for s_ in (1, -1):
            m = (hr == h) & (state == s_)
            st.append({"half": label, "hour": h, "state": s_, "cells": int(m.sum()), "ic": _ic(a, b, c, m) if m.sum() > 1 else np.nan})
    return pd.DataFrame(per_run), pd.DataFrame(sess), pd.DataFrame(st)


def read(seen_runs: list[str] | None = None, pre_run: str | None = PRE_RUN, seen_panel: tuple[list[str], pd.Timestamp, pd.Timestamp] | None = None,
         pre_panel: tuple[list[str], pd.Timestamp, pd.Timestamp] | None = None, draws: int = 2000, name: str = "r49_hours", seed: int = 0,
         record_ic: dict | None = None, seen_fills: list[str] | None = None, pre_fills: list[str] | None = None, state_daily: Path | None = STATE_DAILY,
         settle: tuple[int, ...] = SETTLE, hold: int = 288, latency: int = 1, min_days: dict | None = None, pre_forecast: str | None = None) -> dict:
    """`seen_panel` / `pre_panel`: (pairs, start, end) of each half's panel; default R47's twelve to F5's end and the pre run's pairs to its
    last fold's end. `pre_forecast`: a run name whose forecast.parquet stands in for `pre_run`'s cells (tests only)."""
    r47 = _r47()
    seen_runs = SEEN_RUNS if seen_runs is None else seen_runs
    record_ic = RECORD_IC if record_ic is None else record_ic
    seen_fills = SEEN_FILLS if seen_fills is None else seen_fills
    pre_fills = PRE_FILLS if pre_fills is None else pre_fills
    min_days = MIN_DAYS if min_days is None else min_days
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t0 = time.time()

    # ---- the seen half, first ---------------------------------------------------------------------------------------------
    if seen_panel is None:
        pairs = json.loads((OUT / PAIRS_FROM / "meta.json").read_text())["pairs"]
        seen_panel = (pairs, bt.PRE_START, folds.bounds("F5")[1])
    P = ceiling.panel(seen_panel[0], seen_panel[2], seen_panel[1])
    seen_cells, rec_seen = load_cells(seen_runs, P, hold, latency, r47, record_ic)
    seen = half_stats(seen_cells, draws, rng, settle)
    grid_seen = grid_check(seen_cells, min_days["seen"])
    seen_state = _state_by_day(seen_cells, state_daily)
    pr_s, se_s, st_s = described(seen_cells, seen_state, "seen")
    money_seen, c_money_seen = money_by_hour(seen_fills, min(draws, 500), rng, settle)
    seen_written = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    seen_json = {"written": seen_written, "record": rec_seen, "grid": grid_seen, "ic_all": seen["ic_all"], "ic_h": seen["ic_h"].tolist(), "D": seen["D"].tolist(),
                 "z": seen["z"].tolist(), "p_h": seen["p_h"].tolist(), "p_family": seen["p_family"], "q95": seen["q95"], "cleared": seen["cleared"],
                 "settle": seen["settle"], "money_settle": c_money_seen}
    (out / "seen.json").write_text(json.dumps(seen_json, indent=1, default=str))            # validity (4): the seen half on disk before the pre-history is touched
    del P

    # ---- the confirmation half, after ------------------------------------------------------------------------------------
    pre_meta = json.loads((OUT / pre_run / "meta.json").read_text())
    if pre_panel is None:
        pre_panel = (pre_meta["pairs"], bt.PRE_START, max(folds.bounds(f)[1] for f in pre_meta["folds"]))
    Pp = ceiling.panel(pre_panel[0], pre_panel[2], pre_panel[1])
    pre_cells, rec_pre = load_cells([pre_forecast or pre_run], Pp, hold, latency, r47, record_ic)
    pre = half_stats(pre_cells, draws, rng, settle)
    grid_pre = grid_check(pre_cells, min_days["pre"])
    pre_state = _state_by_day(pre_cells, state_daily)
    pr_p, se_p, st_p = described(pre_cells, pre_state, "pre")
    money_pre, c_money_pre = money_by_hour(pre_fills, min(draws, 500), rng, settle)
    conf = confirm(seen, pre)
    del Pp

    # ---- validity --------------------------------------------------------------------------------------------------------
    rec = rec_seen + rec_pre
    v = {"1_record": rec, "1_pass": all(r["reproduced"] in (True, "no record") for r in rec),
         "2_grid": {"seen": grid_seen, "pre": grid_pre},
         "2_pass": all(g["on_the_hour"] and g["share_days_24"] >= 0.99 and g["max_rel_dev_per_hour"] <= 0.01 for g in (grid_seen, grid_pre)),
         "3_days": {"seen": grid_seen["days"], "pre": grid_pre["days"], "min": min_days},
         "3_pass": grid_seen["days"] >= min_days["seen"] and grid_pre["days"] >= min_days["pre"],
         "4_order": {"seen_written": seen_written, "pre_read_after": True, "cleared_from_seen_only": True},
         "4_pass": True,
         "5_clock": {"seen_utc": grid_seen["utc"], "pre_utc": grid_pre["utc"]}, "5_pass": grid_seen["utc"] and grid_pre["utc"]}
    v["pass"] = bool(v["1_pass"] and v["2_pass"] and v["3_pass"] and v["4_pass"] and v["5_pass"])

    # ---- the tables ------------------------------------------------------------------------------------------------------
    by_hour = []
    for half, st in (("seen", seen), ("pre", pre)):
        for h in range(H):
            by_hour.append({"half": half, "hour": h, "cells": int(st["n_h"][h]), "ic": float(st["ic_h"][h]), "D": float(st["D"][h]), "null_sd": float(st["sd"][h]),
                            "z": float(st["z"][h]), "p_two_sided": float(st["p_h"][h]), "mde": float(MDE_K * st["sd"][h]),
                            "cleared_seen": bool(h in seen["cleared"]) if half == "seen" else None})
    by_hour = pd.DataFrame(by_hour)
    by_hour.to_csv(out / "by_hour.csv", index=False)
    pd.concat([pr_s, pr_p], ignore_index=True).to_csv(out / "per_run_by_hour.csv", index=False)
    pd.concat([se_s, se_p], ignore_index=True).to_csv(out / "sessions.csv", index=False)
    pd.concat([st_s, st_p], ignore_index=True).to_csv(out / "by_hour_state.csv", index=False)
    money = pd.concat([x.assign(half=h) for h, x in (("seen", money_seen), ("pre", money_pre)) if len(x)], ignore_index=True) if (len(money_seen) or len(money_pre)) else pd.DataFrame(columns=["half", "hour", "trades", "gross", "net", "hedged_net"])
    money.to_csv(out / "money_by_hour.csv", index=False)
    for half, st in (("seen", seen), ("pre", pre)):
        pd.DataFrame(st["D_null"], columns=[f"D_{h}" for h in range(H)]).assign(settle=st["C_null"], fam=st["fam_null"]).to_parquet(out / f"perms_{half}.parquet", index=False)

    def half_summary(st: dict) -> dict:
        return {k: st[k] for k in ("cells", "days", "ic_all", "fam_obs", "q95", "p_family", "cleared")} | {"ic_h": st["ic_h"].tolist(), "D": st["D"].tolist(),
                "sd": st["sd"].tolist(), "z": st["z"].tolist(), "p_h": st["p_h"].tolist(), "n_h": st["n_h"].tolist(), "settle": st["settle"]}

    summary = {"registration": "R49", "name": name, "draws": draws, "seed": seed, "settle_hours": list(settle), "hold": hold, "latency": latency,
               "seen_runs": seen_runs, "pre_run": pre_run, "seen_panel": [seen_panel[0], str(seen_panel[1]), str(seen_panel[2])],
               "pre_panel": [pre_panel[0], str(pre_panel[1]), str(pre_panel[2])], "validity": v, "seen": half_summary(seen), "pre": half_summary(pre),
               "confirmation": conf, "verdict": conf["verdict"], "confirmed": conf["confirmed"],
               "money": {"seen": c_money_seen, "pre": c_money_pre}, "sessions": pd.concat([se_s, se_p]).to_dict("records"),
               "seconds": round(time.time() - t0, 1)}
    (out / "hours.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "hours.md").write_text(_report(summary, by_hour, pd.concat([se_s, se_p]), pd.concat([st_s, st_p]), money,
                                          pd.concat([pr_s, pr_p])))
    return summary


def _settle_row(s: dict, p_key: str) -> str:
    return (f"IC {s['ic_settle']:.4f} on {s['n_settle']:,} cells at the settlement hours against {s['ic_other']:.4f} on {s['n_other']:,} — D {s['D']:+.4f}, "
            f"null sd {s['sd']:.4f}, {p_key} p {s[p_key]:.3f}, MDE {s['mde']:.4f}, interval [{s['lo']:+.4f}, {s['hi']:+.4f}]")


def _report(s: dict, by_hour: pd.DataFrame, sess: pd.DataFrame, st: pd.DataFrame, money: pd.DataFrame, per_run: pd.DataFrame) -> str:
    v, se, pr, c = s["validity"], s["seen"], s["pre"], s["confirmation"]
    seen_settle = "CLEARS" if (se["settle"]["p_two_sided"] <= 0.05 and se["settle"]["D"] > 0) else ("SIGNIFICANT, OPPOSITE SIGN" if se["settle"]["p_two_sided"] <= 0.05 else
                                                                                                  ("NOT DETECTABLE" if abs(se["settle"]["D"]) < se["settle"]["mde"] else "NOT CLEAR"))
    md = [f"# R49 — the time of day of R14's decisions (`{s['name']}`)\n",
          f"\nThe seen half `{'`, `'.join(s['seen_runs'])}` on the panel `{', '.join(s['seen_panel'][0])}` {s['seen_panel'][1][:10]} → {s['seen_panel'][2][:10]}; "
          f"the confirmation half `{s['pre_run']}` on `{', '.join(s['pre_panel'][0])}` {s['pre_panel'][1][:10]} → {s['pre_panel'][2][:10]}. "
          f"IC_h = R47's pooled held-out IC on the cells decided at hour h (UTC), D_h = IC_h − IC_all; the null {s['draws']:,} random permutations of the 24 hour labels "
          f"within each day; the settlement hours {s['settle_hours']}; MDE = {MDE_K} × the null's sd. {s['seconds']} s.\n",
          f"\n## Validity: {'PASS' if v['pass'] else 'FAIL'}\n",
          "\n(1) the record — each run's whole-sample IC and cell count against its forecast.md row:\n", pd.DataFrame(v["1_record"]).round(4).to_markdown(index=False),
          f"\n\n(2) the grid: {json.dumps({k: {kk: (round(x, 4) if isinstance(x, float) else x) for kk, x in g.items()} for k, g in v['2_grid'].items()})} → {'PASS' if v['2_pass'] else 'FAIL'}\n",
          f"\n(3) the days: {v['3_days']} → {'PASS' if v['3_pass'] else 'FAIL'}\n",
          f"\n(4) the order: the seen half written to `seen.json` at {v['4_order']['seen_written']}, before any pre-history cell was grouped by its hour; the cleared set from the seen half alone → PASS\n",
          f"\n(5) the clock: {v['5_clock']} → {'PASS' if v['5_pass'] else 'FAIL'}\n",
          f"\n## THE SEEN HALF (F1–F5): {se['cells']:,} cells on {se['days']:,} days, IC_all {se['ic_all']:.4f}\n",
          f"\n**(i) C_settle — {seen_settle}**: {_settle_row(se['settle'], 'p_two_sided')} (sign +).\n",
          f"\n**(ii) the family of 24 — family-wise p {se['p_family']:.3f}** (max |z| {se['fam_obs']:.2f}, the null's 0.95 quantile {se['q95']:.2f}); "
          f"cleared: {se['cleared'] if se['cleared'] else 'none'}.\n\n",
          by_hour[by_hour["half"] == "seen"].drop(columns=["half"]).round(4).to_markdown(index=False), "\n",
          f"\n## THE CONFIRMATION HALF (FP+F0): {pr['cells']:,} cells on {pr['days']:,} days, IC_all {pr['ic_all']:.4f} — **{s['verdict']}**\n",
          f"\n**C_settle, once, sign + (one-sided) — {c['settle']['verdict']}**: {_settle_row(pr['settle'], 'p_one_sided')}; the seen half's D {c['settle']['seen_D']:+.4f}.\n",
          f"\n**The seen half's cleared cells on the pre-history — {c['family']['verdict']}** ({c['family']['members']} members"
          + (f", max signed z {c['family']['z']:.2f}, one-sided family p {c['family']['p']:.3f}" if c["cells"] else "") + ").\n"]
    if c["cells"]:
        md += ["\n", pd.DataFrame(c["cells"]).round(4).to_markdown(index=False), "\n"]
    md += ["\nThe pre-history's full family, described (never a gate on its own): family-wise p "
           f"{pr['p_family']:.3f} (max |z| {pr['fam_obs']:.2f}).\n\n", by_hour[by_hour["half"] == "pre"].drop(columns=["half", "cleared_seen"]).round(4).to_markdown(index=False), "\n",
           "\n## Described — the sessions\n\n", sess.round(4).to_markdown(index=False), "\n",
           "\n## Described — the money by hour of the decision (taker, size-weighted bps a trade)\n\n",
           money[["half", "hour", "trades", "gross", "net", "hedged_net"]].round(1).to_markdown(index=False), "\n",
           f"\nC_settle in money (the same per-day permutation of the trades' hour labels): seen {json.dumps({k: {kk: (round(x, 3) if isinstance(x, float) else x) for kk, x in r.items()} for k, r in s['money']['seen'].items()})}; "
           f"pre {json.dumps({k: {kk: (round(x, 3) if isinstance(x, float) else x) for kk, x in r.items()} for k, r in s['money']['pre'].items()})}\n",
           "\n## Described — IC by hour × S90 (the state at the cell's day; R47's daily.parquet)\n\n",
           st.pivot_table(index=["half", "hour"], columns="state", values="ic").round(4).to_markdown(), "\n",
           "\n## Described — IC by hour per run\n\n", per_run.pivot_table(index="hour", columns="run", values="ic").round(4).to_markdown(), "\n"]
    return "".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draws", type=int, default=2000)
    ap.add_argument("--name", default="r49_hours")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    s = read(draws=a.draws, name=a.name, seed=a.seed)
    print((OUT / a.name / "hours.md").read_text())
    return s


if __name__ == "__main__":
    main()
