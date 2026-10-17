"""R48 (PLAN §8): the candle ridge on the pre-history, once — R45's and R47's state hypotheses on bars the ridge never saw.

    python scripts/r48_pre.py                        → output/backtest/r48_pre/{pre.md, pre.json, shifts.parquet, by_year.csv, by_state.csv, known_at.csv}

The walk itself is the harness's (`ft2 backtest ridgebook --param hold=288 --folds FP F0 --registration R48 …`, scripts/r48_chain.sh); this
script reads its SAVED files. S90 at each decision / cell is R45's state on the run's own panel (`ceiling.panel(the twelve, F0's end,
PRE_START)`). Two primary rows with their signs fixed: (i) D_hedged = the size-weighted mean hedged net of the taker trades decided in state
+1 minus state −1 (sign +, R45's fact +58); (ii) D_IC = the pooled held-out IC of the run's forecast cells in state +1 minus −1 (sign +,
R47's fact +0.073). The null: every admissible whole-day circular shift of the state series on the run's span; a family of two. Described:
D_net, the maker fills' D_hedged, by-year × state, side × state, and R14's unconditional pre-history rows from the run's own results and
nulls — described, not a gate.
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
from ft2 import backtest as bt, ceiling, folds  # noqa: E402

OUT = Path("output/backtest")
PER_DAY = 288
MDE_K = ceiling.MDE_K
RUN = "r48_ridgebook_1d_ho12_pre"
R14_PARAMS = {"hold": 288, "min_bps": 15.0, "cap": 2.0, "groups": 4, "grid": 12, "min_pairs": 5, "holdout": True}
FACTS = {"hedged": 58.1, "ic": 0.073}                        # the seen-bar facts (R45's hedged D, R47's IC D): the registered signs are theirs
REF_DAILY = OUT / "r47_mech" / "daily.parquet"              # validity (2): R47's state by day
READS = OUT / "confirmation_reads.csv"
YEARS = ((2020, "2020 (May on)"), (2021, "2021"), (2022, "2022"), (2023, "2023-Q1"))


def _mod(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _d(x: np.ndarray, w: np.ndarray, s: np.ndarray) -> float:
    up, dn = s > 0, s < 0
    if w[up].sum() <= 0 or w[dn].sum() <= 0:
        return np.nan
    return float(np.average(x[up], weights=w[up]) - np.average(x[dn], weights=w[dn]))


def _verdict(D: float, sd: float, p: float, sign: int, fact: float) -> str:
    if not np.isfinite(D) or not sd > 0:
        return "NOT READABLE"
    if p <= 0.05 and np.sign(D) == sign:
        return "CLEARS"
    if p <= 0.05:
        return "SIGNIFICANT, OPPOSITE SIGN"
    if sign * (D + sign * 1.96 * sd) < abs(fact) / 2:         # the interval lies wholly below half the fact
        return "REFUTED"
    return "NOT DETECTABLE" if abs(D) < MDE_K * sd else "NOT CLEAR"


def read(run: str = RUN, days: int = 90, min_shift: int | None = None, name: str = "r48_pre", known_at_draws: int = 20, seed: int = 0,
         start: pd.Timestamp | None = None, end: pd.Timestamp | None = None, expect_params: dict | None = R14_PARAMS,
         expect_folds: list[str] | None = None, registration: str | None = "R48", ref_daily: Path | None = REF_DAILY, facts: dict | None = None,
         hold: int = 288, latency: int = 1, min_pairs: int = ceiling.MIN_PAIRS) -> dict:
    r45, r47 = _mod("r45_state"), _mod("r47_mech")
    facts = FACTS if facts is None else facts
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    d = OUT / run
    meta = json.loads((d / "meta.json").read_text())
    pairs = meta["pairs"]
    expect_folds = ["FP", "F0"] if expect_folds is None else expect_folds
    start = bt.PRE_START if start is None else start
    end = max(folds.bounds(f)[1] for f in meta["folds"]) if end is None else end
    P = ceiling.panel(pairs, end, start)
    idx = P["close"].index
    s = r47.s90(P, days)
    n = len(idx)
    span_days = int(np.ceil((idx[-1] - idx[0]) / pd.Timedelta(1, "D")))
    min_shift = days if min_shift is None else min_shift
    shifts = np.arange(min_shift, span_days - min_shift + 1)
    if len(shifts) < 10:
        raise SystemExit(f"r48: {len(shifts)} admissible shifts on a span of {span_days} days — not a null")
    validity: dict = {}

    # ---- validity (1): the run's meta --------------------------------------------------------------------------------------
    v1 = {"folds": meta["folds"], "folds_ok": list(meta["folds"]) == list(expect_folds), "registration": meta.get("registration"),
          "registration_ok": registration is None or meta.get("registration") == registration, "draws": meta.get("draws"), "params": meta["params"]}
    v1["params_ok"] = expect_params is None or all(meta["params"].get(k) == v for k, v in expect_params.items())
    if registration is not None and READS.exists():
        rd = pd.read_csv(READS)
        got = sorted(rd.loc[rd["registration"] == registration, "fold"].astype(str))
        v1["reads_logged"] = got
        v1["reads_ok"] = all(f in got for f in expect_folds)
    else:
        v1["reads_logged"], v1["reads_ok"] = "not checked", True
    validity["1_meta"] = v1
    validity["1_pass"] = bool(v1["folds_ok"] and v1["registration_ok"] and v1["params_ok"] and v1["reads_ok"])

    # ---- the trades and the cells -----------------------------------------------------------------------------------------
    F = {}
    for ex in ("taker", "maker"):
        f = d / f"fills_{ex}.parquet"
        if f.exists():
            x = pd.read_parquet(f).dropna(subset=["net_bps"]).copy()
            pos = idx.get_indexer(pd.DatetimeIndex(x["t"]))
            x = x[pos >= 0].copy()
            x["pos"] = pos[pos >= 0]
            x["state"] = s[x["pos"].to_numpy()]
            F[ex] = x.reset_index(drop=True)
    ft = F["taker"]
    cells, _ = r47.forecast_cells(run, P, hold, latency)
    pos_c = cells["pos"].to_numpy()
    cells["state"] = s[pos_c]
    A, B, C = (cells["zhat"] * cells["zres"]).to_numpy(), (cells["zhat"] ** 2).to_numpy(), (cells["zres"] ** 2).to_numpy()

    def d_ic(st: np.ndarray) -> float:
        return r47._pooled_ic(A, B, C, st > 0) - r47._pooled_ic(A, B, C, st < 0)

    # ---- validity (2): the state equals R47's by day; (3) known-at; (4) the names; (5) the counts --------------------------
    at = idx[(idx.hour == 0) & (idx.minute == 0)]
    mine = pd.DataFrame({"day": at, "state": s[idx.get_indexer(at)]})
    if ref_daily is not None and Path(ref_daily).exists():
        ref = pd.read_parquet(ref_daily)[["day", "state"]]
        m = mine.merge(ref, on="day", suffixes=("", "_ref"))
        validity["2_state"] = {"shared_days": len(m), "differences": int((m["state"] != m["state_ref"]).sum())}
        validity["2_pass"] = bool(len(m) > 0 and (m["state"] == m["state_ref"]).all())
    else:
        validity["2_state"], validity["2_pass"] = "no reference", True
    rng = np.random.default_rng(seed)
    upos = np.unique(ft["pos"].to_numpy())
    pick = rng.choice(upos, size=min(known_at_draws, len(upos)), replace=False)
    ka = []
    for p_ in sorted(pick):
        sc = r47.s90({k: v.iloc[: p_ + 1] for k, v in P.items()}, days)
        ka.append({"t": str(idx[p_]), "full": int(s[p_]), "cut": int(sc[-1]), "same": int(s[p_]) == int(sc[-1])})
    pd.DataFrame(ka).to_csv(out / "known_at.csv", index=False)
    validity["3_known_at"] = ka
    validity["3_pass"] = all(r["same"] for r in ka)
    names_at = P["close"].notna().sum(axis=1).to_numpy()[ft["pos"].to_numpy()]
    validity["4_names"] = {"min_at_a_decision": int(names_at.min()) if len(names_at) else 0, "at_first_decision": int(names_at[np.argmin(ft["pos"].to_numpy())]) if len(names_at) else 0,
                           "max": int(names_at.max()) if len(names_at) else 0}
    validity["4_pass"] = bool(len(names_at) and names_at.min() >= min_pairs)
    lo, hi = int(ft["pos"].min()), int(ft["pos"].max())
    ed, runs = r45.episodes_daily(s[lo: hi + 1])
    validity["5_counts"] = {"trades_taker": int(len(ft)), "trades_maker": int(len(F["maker"])) if "maker" in F else None, "cells": int(len(cells)),
                            "days": int(np.ceil((idx[hi] - idx[lo]) / pd.Timedelta(1, "D"))), "episodes_daily": ed, "runs_7d": runs,
                            "share_up_trades": float((ft["state"][ft["state"] != 0] > 0).mean()), "cover_trades": float((ft["state"] != 0).mean()),
                            "cover_cells": float((cells["state"] != 0).mean())}
    validity["5_pass"] = bool(len(ft) > 0 and len(cells) > 0 and validity["5_counts"]["cover_trades"] >= 0.95)
    validity["pass"] = bool(validity["1_pass"] and validity["2_pass"] and validity["3_pass"] and validity["4_pass"] and validity["5_pass"])

    # ---- the statistics and the null --------------------------------------------------------------------------------------
    wt, ht, nt, st = ft["size"].to_numpy(), ft["hedged_net_bps"].to_numpy(), ft["net_bps"].to_numpy(), ft["state"].to_numpy()
    obs = {"hedged": _d(ht, wt, st), "ic": d_ic(cells["state"].to_numpy()), "net": _d(nt, wt, st)}
    if "maker" in F:
        fm = F["maker"]
        wm, hm, sm, pm = fm["size"].to_numpy(), fm["hedged_net_bps"].to_numpy(), fm["state"].to_numpy(), fm["pos"].to_numpy()
        obs["hedged_maker"] = _d(hm, wm, sm)
    pos_t = ft["pos"].to_numpy()
    rows_null = []
    for dd in shifts:
        s_t = s[(pos_t - dd * PER_DAY) % n]
        r = {"shift": int(dd), "hedged": _d(ht, wt, s_t), "net": _d(nt, wt, s_t), "ic": d_ic(s[(pos_c - dd * PER_DAY) % n])}
        if "maker" in F:
            r["hedged_maker"] = _d(hm, wm, s[(pm - dd * PER_DAY) % n])
        rows_null.append(r)
    null = pd.DataFrame(rows_null)
    null.to_parquet(out / "shifts.parquet", index=False)
    rows, zs = [], {}
    for r in obs:
        nk, D = null[r].to_numpy(), obs[r]
        sd = float(np.nanstd(nk))
        p = float((1 + np.sum(np.abs(nk) >= abs(D))) / (1 + len(nk))) if np.isfinite(D) else np.nan
        primary = r in ("hedged", "ic")
        fact = facts["hedged"] if r in ("hedged", "net", "hedged_maker") else facts["ic"]
        if r == "ic":
            mu, md_ = r47._pooled_ic(A, B, C, cells["state"].to_numpy() > 0), r47._pooled_ic(A, B, C, cells["state"].to_numpy() < 0)
            nu, nd = int((cells["state"] > 0).sum()), int((cells["state"] < 0).sum())
        else:
            x, w, s_ = (hm, wm, sm) if r == "hedged_maker" else ((nt, wt, st) if r == "net" else (ht, wt, st))
            mu = float(np.average(x[s_ > 0], weights=w[s_ > 0])) if (s_ > 0).any() else np.nan
            md_ = float(np.average(x[s_ < 0], weights=w[s_ < 0])) if (s_ < 0).any() else np.nan
            nu, nd = int((s_ > 0).sum()), int((s_ < 0).sum())
        rows.append({"row": r, "kind": "primary" if primary else "described", "sign": 1, "fact": fact, "D": D, "null_sd": sd, "p": p, "mde": MDE_K * sd,
                     "lo": D - 1.96 * sd, "hi": D + 1.96 * sd, "n_up": nu, "n_dn": nd, "mean_up": mu, "mean_dn": md_, "verdict": _verdict(D, sd, p, 1, fact)})
        if primary and np.isfinite(D) and sd > 0:
            zs[r] = (abs(D) / sd, np.abs(nk) / sd)
    res = pd.DataFrame(rows)
    if zs:
        zo = max(v[0] for v in zs.values())
        zn = np.max(np.vstack([v[1] for v in zs.values()]), axis=0)
        family = {"members": len(zs), "z": float(zo), "p_family": float((1 + np.sum(zn >= zo)) / (1 + len(zn))),
                  "carried_by": max(zs, key=lambda k: zs[k][0])}
    else:
        family = {"members": 0, "z": np.nan, "p_family": np.nan, "carried_by": None}
    rv = res.set_index("row")["verdict"]
    confirmed = bool(family["members"] and family["p_family"] <= 0.05 and rv[family["carried_by"]] == "CLEARS")
    verdict = "CONFIRMED ON THE PRE-HISTORY" if confirmed else "NOT CONFIRMED"

    # ---- described: by year × state, side × state, the unconditional rows ------------------------------------------------
    ft["year"] = pd.DatetimeIndex(ft["t"]).year
    cells["year"] = pd.DatetimeIndex(cells["t"]).year
    by_year = []
    for y, label in YEARS:
        g, c = ft[ft["year"] == y], cells[cells["year"] == y]
        for st_ in (1, -1):
            gg, cc = g[g["state"] == st_], c[c["state"] == st_]
            a, b, c_ = (cc["zhat"] * cc["zres"]).to_numpy(), (cc["zhat"] ** 2).to_numpy(), (cc["zres"] ** 2).to_numpy()
            by_year.append({"year": label, "state": st_, "trades": len(gg), "net": float(np.average(gg["net_bps"], weights=gg["size"])) if len(gg) else np.nan,
                            "hedged_net": float(np.average(gg["hedged_net_bps"], weights=gg["size"])) if len(gg) else np.nan,
                            "cells": len(cc), "ic": r47._pooled_ic(a, b, c_, np.ones(len(cc), dtype=bool)) if len(cc) > 1 else np.nan})
    by_year = pd.DataFrame(by_year)
    by_year.to_csv(out / "by_year.csv", index=False)
    by_state = []
    for (st_, side), g in ft[ft["state"] != 0].groupby(["state", "side"]):
        by_state.append({"state": int(st_), "side": int(side), "trades": len(g), "net": float(np.average(g["net_bps"], weights=g["size"])),
                         "hedged_net": float(np.average(g["hedged_net_bps"], weights=g["size"]))})
    by_state = pd.DataFrame(by_state)
    by_state.to_csv(out / "by_state.csv", index=False)
    results = pd.read_parquet(d / "results.parquet")
    nul = pd.read_parquet(d / "null.parquet") if (d / "null.parquet").exists() else pd.DataFrame(columns=["kind", "exec", "net"])
    uncond = []
    for ex in ("taker", "maker"):
        r = results[(results["exec"] == ex) & (results["scope"] == "all")]
        if r.empty:
            continue
        r = r.iloc[0]
        row = {"exec": ex, "trades": int(r["trades"]), "net": float(r["net"]), "net_lo": float(r["net_lo"]), "net_hi": float(r["net_hi"]),
               "hedged_net": float(r["hedged_net"]), "hedged_lo": float(r["hedged_net_lo"]), "hedged_hi": float(r["hedged_net_hi"])}
        for kind in ("shuffle", "flip"):
            x = nul[(nul["kind"] == kind) & (nul["exec"] == ex)]["net"].to_numpy()
            row[f"{kind}_p"] = float((1 + np.sum(x >= r["net"])) / (1 + len(x))) if len(x) else np.nan
            row[f"{kind}_draws"] = int(len(x))
        uncond.append(row)
    uncond = pd.DataFrame(uncond)

    summary = {"registration": registration, "name": name, "run": run, "pairs": pairs, "start": str(start), "end": str(end), "days": days,
               "span_days": span_days, "shifts": int(len(shifts)), "min_shift": int(min_shift), "facts": facts, "validity": validity,
               "results": res.to_dict("records"), "family": family, "verdict": verdict, "confirmed": confirmed, "by_year": by_year.to_dict("records"),
               "by_state": by_state.to_dict("records"), "unconditional": uncond.to_dict("records")}
    (out / "pre.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "pre.md").write_text(_report(summary, res, by_year, by_state, uncond))
    return summary


def _report(s: dict, res: pd.DataFrame, by_year: pd.DataFrame, by_state: pd.DataFrame, uncond: pd.DataFrame) -> str:
    v = s["validity"]
    md = [f"# R48 — the candle ridge on the pre-history, once (`{s['name']}` on `{s['run']}`)\n",
          f"\nS90 (the basket's trailing {s['days']}-day sign) on `{'`, `'.join(s['pairs'])}` from {s['start'][:10]} to {s['end'][:10]} ({s['span_days']} days); "
          f"the null {s['shifts']} whole-day circular shifts ({s['min_shift']} ≤ d ≤ span − {s['min_shift']}); the seen-bar facts: hedged D +{s['facts']['hedged']}, IC D +{s['facts']['ic']}.\n",
          f"\n## Validity: {'PASS' if v['pass'] else 'FAIL'}\n",
          f"\n(1) the run's meta: {json.dumps(v['1_meta'], default=str)} → {'PASS' if v['1_pass'] else 'FAIL'}\n",
          f"\n(2) the state against R47's by day: {v['2_state']} → {'PASS' if v['2_pass'] else 'FAIL'}\n",
          f"\n(3) known-at on {len(v['3_known_at'])} drawn decisions: {'PASS' if v['3_pass'] else 'FAIL'}\n",
          f"\n(4) the names: {v['4_names']} → {'PASS' if v['4_pass'] else 'FAIL'}\n",
          f"\n(5) the counts: {json.dumps({k: (round(x, 4) if isinstance(x, float) else x) for k, x in v['5_counts'].items()})} → {'PASS' if v['5_pass'] else 'FAIL'}\n",
          f"\n## **{s['verdict']}** — family-wise p {s['family']['p_family']:.3f} (max z {s['family']['z']:.2f}, carried by `{s['family']['carried_by']}`)\n",
          "\nD = the row in state +1 (after a rising quarter) minus state −1; p two-sided against the shifts; a primary row clears at p ≤ 0.05 with its "
          "registered sign (+); REFUTED when the interval lies wholly below half the seen fact; MDE = 2.8 × the null's sd.\n\n", res.round(4).to_markdown(index=False), "\n",
          "\n## By year × state (described)\n\n", by_year.round(3).to_markdown(index=False), "\n",
          "\n## By side × state (taker, size-weighted; described)\n\n", by_state.round(2).to_markdown(index=False), "\n",
          "\n## R14's unconditional rows on the pre-history (the run's own results and nulls; described, NOT a gate)\n\n",
          uncond.round(3).to_markdown(index=False) if len(uncond) else "(none)", "\n"]
    return "".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=RUN)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-shift", type=int, default=None)
    ap.add_argument("--known-at-draws", type=int, default=20)
    ap.add_argument("--name", default="r48_pre")
    a = ap.parse_args(argv)
    s = read(a.run, a.days, a.min_shift, a.name, a.known_at_draws)
    print((OUT / a.name / "pre.md").read_text())
    return s


if __name__ == "__main__":
    main()
