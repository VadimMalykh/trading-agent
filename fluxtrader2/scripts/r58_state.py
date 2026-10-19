"""R58 (PLAN §8; decision AQ1): the state audit on the parked market-wide rules — which measured state, known at the decision, names
R8's (`trendfall4h`) and R32's (`trend1d`) losing periods in advance? Read on their SAVED taker fills; R45's frame generalised.

    python scripts/r58_state.py        → output/backtest/r58_state/{state.md, state.json, shifts.parquet, by_state.csv, halfyears.csv, episodes.csv}

Five states at a decision bar t (+1 / −1 / 0 undefined), each a function of information at or before t:
  S90      R45's: the sign of the twelve's basket's move over the trailing 90 days (+1 rising).
  V90      the basket's realised 5m volatility over the trailing 90 days BELOW the median of its own trailing 365 days (+1 calm).
  DVOL     BTC's DVOL open of t's UTC day BELOW the median of the opens of the trailing 365 days, ≥ 90 present (+1 low implied).
  PREM     BTC's DVOL open of t's UTC day ABOVE BTC's trailing 30-day realised vol at t, annualised % (+1 a positive premium).
  SESSION  the US100 index futures trading at t — R30's `ix_open`, R26's Minutes (+1 open, −1 closed).
Per rule k and state s: D = the size-weighted mean net on the trades decided in state +1 minus the same in −1; each half's mean with a
day-clustered 95 % interval. The null: the state series circularly shifted by every admissible whole-day shift, the SAME shift on every
state at once; per member the two-sided p; the family (5 on R8 + 4 on R32 — S90 on R32 is R45's number) by the min-P rule (amended
2026-10-19 before any read, after the planted test: a persistent state's |D| / sd under its own shift null is capped near 2 whatever
the effect, so a max-z family is biased toward the fast states) — each shift's value is ranked within its own member's null, the
family's statistic per shift is the smallest of the members' ranks, and a member's family-wise p = the share of shifts whose smallest
rank is at or under that member's own p. The gate per member: CLEARS if
its family-wise p ≤ 0.05 AND the worse half's net ≤ 0 AND the better half's lower bound > 0 (the state names a LOSING half); SPLITS
WITHOUT A LOSING HALF at p ≤ 0.05 otherwise; else NOT DETECTABLE / CLOSED / NOT CLEAR by the MDE. A re-reading of saved fills: no walk,
no fit, no fold read; the guard is not involved.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import audit_index, backtest as bt, ceiling, dvol as dvol_mod, folds, market as mk  # noqa: E402

OUT = Path("output/backtest")
PER_DAY = 288
MDE_K = ceiling.MDE_K
STATES = ("S90", "V90", "DVOL", "PREM", "SESSION")
# the registered rule sets (PLAN §8 R58 "Cells"): name → (the run directory under output/backtest, the record's priced trades, net)
RULES = {"R8": ("trendfall4h", 3384, 51.91), "R32": ("trend1d", 14672, 10.67)}
NOT_IN_FAMILY = {("R32", "S90")}          # R45's number (+38.2, p 0.152), not read again
COVER_FLOOR, HALF_FLOOR, P_BAR = 0.50, 0.10, 0.05
PARAMS = dict(s90_days=90, v_days=90, v_ref_days=365, dvol_ref_days=365, dvol_min_days=90, prem_days=30, prem_symbol="BTCUSDT", index="US100")
ANNUAL = np.sqrt(PER_DAY * 365) * 100     # a 5m sd of log moves → an annualised vol in %


def _fills(path: str) -> pd.DataFrame:
    p = OUT / path
    f = pd.read_parquet(p / "fills_taker.parquet" if p.is_dir() else p)
    f = f.dropna(subset=["net_bps"]).copy()
    f["file"] = path
    return f


def _sgn(x: pd.Series) -> np.ndarray:
    return np.sign(x.fillna(0.0).to_numpy()).astype(int)


def state_dvol(days: pd.DatetimeIndex, dv: pd.DataFrame, ref_days: int, min_days: int) -> pd.Series:
    """Per UTC day: +1 where the day's open is below the median of the trailing `ref_days` opens (the day itself excluded)."""
    o = dv.set_index("day")["open"].astype(float).sort_index()
    o = o[~o.index.duplicated()]
    ref = o.shift(1).rolling(ref_days, min_periods=min_days).median()
    s = pd.Series(np.where(o < ref, 1, np.where(o > ref, -1, 0)), index=o.index).where(ref.notna(), 0)
    return s.reindex(days).fillna(0).astype(int)


def states(P: dict, dv: pd.DataFrame | None, mi: audit_index.Minutes | None, **kw) -> pd.DataFrame:
    """The five state series on the panel's 5m grid: +1 / −1, 0 where undefined."""
    q = {**PARAMS, **kw}
    D = mk.derive(P)
    blr, b1 = D["blr"], D["b1"]
    idx = P["close"].index
    S = pd.DataFrame(index=idx)
    S["S90"] = _sgn(blr - blr.shift(q["s90_days"] * PER_DAY))
    sig = b1.rolling(q["v_days"] * PER_DAY, min_periods=int(q["v_days"] * PER_DAY * 0.8)).std()
    ref = sig.rolling(q["v_ref_days"] * PER_DAY, min_periods=int(q["v_ref_days"] * PER_DAY * 0.5)).median()
    S["V90"] = np.where(sig.notna() & ref.notna(), np.where(sig < ref, 1, np.where(sig > ref, -1, 0)), 0)
    day = idx.floor("D")
    if dv is not None and len(dv):
        dvc = dv[dv["currency"].astype(str) == "BTC"] if "currency" in dv else dv
        sd = state_dvol(pd.DatetimeIndex(sorted(set(day))), dvc, q["dvol_ref_days"], q["dvol_min_days"])
        S["DVOL"] = sd.reindex(day).to_numpy()
        o = dvc.set_index("day")["open"].astype(float)
        o = o[~o.index.duplicated()].reindex(day).to_numpy()
        sym = q["prem_symbol"]
        if sym in P["close"].columns:
            lr = np.log(P["close"][sym]).diff() * 1.0
            rv = lr.rolling(q["prem_days"] * PER_DAY, min_periods=int(q["prem_days"] * PER_DAY * 0.8)).std().to_numpy() * ANNUAL
            S["PREM"] = np.where(np.isfinite(o) & np.isfinite(rv), np.where(o > rv, 1, np.where(o < rv, -1, 0)), 0)
        else:
            S["PREM"] = 0
    else:
        S["DVOL"], S["PREM"] = 0, 0
    if mi is not None:
        at = mi.at(idx)
        S["SESSION"] = np.where(at["row"] >= 0, np.where(at["open"], 1, -1), 0)
    else:
        S["SESSION"] = 0
    return S.astype(int)


def episodes_daily(s: np.ndarray, min_run_days: int = 7) -> tuple[int, int]:
    x = s[::PER_DAY]
    x = x[x != 0]
    if len(x) < 2:
        return 0, int(len(x) > 0)
    ch = np.flatnonzero(np.diff(x) != 0)
    runs = np.diff(np.concatenate([[0], ch + 1, [len(x)]]))
    return int(len(ch)), int((runs >= min_run_days).sum())


def _wmean(x: np.ndarray, w: np.ndarray) -> float:
    return float(np.average(x, weights=w)) if w.sum() > 0 else np.nan


def _d(x: np.ndarray, w: np.ndarray, s: np.ndarray) -> float:
    up, dn = s > 0, s < 0
    if w[up].sum() <= 0 or w[dn].sum() <= 0:
        return np.nan
    return _wmean(x[up], w[up]) - _wmean(x[dn], w[dn])


def clustered(x: np.ndarray, w: np.ndarray, day: np.ndarray) -> tuple[float, float, float]:
    """(the size-weighted mean, its se clustered by decision day, the 95 % lower bound)."""
    if len(x) == 0 or w.sum() <= 0:
        return np.nan, np.nan, np.nan
    m = _wmean(x, w)
    u = pd.Series(w * (x - m)).groupby(day).sum().to_numpy()
    g = len(u)
    var = float((u ** 2).sum()) / w.sum() ** 2 * (g / (g - 1) if g > 1 else np.nan)
    se = float(np.sqrt(var)) if np.isfinite(var) else np.nan
    return m, se, m - 1.96 * se


def _halfyear(t: pd.Series) -> pd.Series:
    return t.dt.year.astype(str) + np.where(t.dt.month <= 6, "-H1", "-H2")


def read(rules: dict[str, tuple[str, int | None, float | None]], pairs: list[str], start: pd.Timestamp, end: pd.Timestamp,
         min_shift: int | None = None, name: str = "r58_state", known_at_draws: int = 20, seed: int = 0, dv: pd.DataFrame | None = None,
         index_symbol: str | None = PARAMS["index"], not_in_family=NOT_IN_FAMILY, **kw) -> dict:
    q = {**PARAMS, **kw}
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    P = ceiling.panel(pairs, end, start)
    idx = P["close"].index
    n = len(idx)
    if dv is None and dvol_mod.PARQUET.exists():
        dv = dvol_mod.load()
    mi = None
    if index_symbol is not None:
        try:
            mi = audit_index.load_minutes(index_symbol, end)
        except FileNotFoundError:
            mi = None
    S = states(P, dv, mi, **q)
    span_days = int(np.ceil((idx[-1] - idx[0]) / pd.Timedelta(1, "D")))
    min_shift = q["s90_days"] if min_shift is None else min_shift
    shifts = np.arange(min_shift, span_days - min_shift + 1)
    if len(shifts) < 10:
        raise SystemExit(f"r58: {len(shifts)} admissible shifts on a span of {span_days} days — not a null")

    # the rules: validity (1) and the join to every state at t
    F, validity, val_rows = {}, {}, []
    for k, (path, rec_n, rec_net) in rules.items():
        f = _fills(path)
        w = f["size"].to_numpy()
        net = _wmean(f["net_bps"].to_numpy(), w) if len(f) else np.nan
        ok = None if rec_n is None else (len(f) == rec_n and abs(net - rec_net) <= 0.05)
        val_rows.append({"rule": k, "file": path, "trades": len(f), "net": net, "record_trades": rec_n, "record_net": rec_net,
                         "reproduced": "no record" if ok is None else bool(ok)})
        pos = idx.get_indexer(pd.DatetimeIndex(f["t"]))
        f["pos"] = pos
        f["day"] = pd.DatetimeIndex(f["t"]).floor("D")
        f["halfyear"] = _halfyear(pd.to_datetime(f["t"], utc=True))
        for st in STATES:
            f[st] = np.where(pos >= 0, S[st].to_numpy()[np.maximum(pos, 0)], 0)
        F[k] = f
    validity["1_record"] = val_rows
    validity["1_pass"] = all(r["reproduced"] in (True, "no record") for r in val_rows)

    # validity (2): coverage and the halves' floors → readable
    cover, readable, share_up = {}, {}, {}
    for k, f in F.items():
        for st in STATES:
            s = f[st].to_numpy()
            c = float((s != 0).mean())
            cover[f"{k}/{st}"] = c
            up = float((s > 0).sum() / max((s != 0).sum(), 1))
            share_up[f"{k}/{st}"] = up
            readable[f"{k}/{st}"] = bool(c >= COVER_FLOOR and min(up, 1 - up) >= HALF_FLOOR)
    validity["2_cover"], validity["2_share_up"], validity["2_readable"] = cover, share_up, readable

    # validity (3): known-at — every state recomputed on the inputs cut at t, on decision bars drawn at random
    rng = np.random.default_rng(seed)
    allpos = np.unique(np.concatenate([f["pos"].to_numpy() for f in F.values()]))
    allpos = allpos[allpos >= 0]
    pick = rng.choice(allpos, size=min(known_at_draws, len(allpos)), replace=False)
    ka = []
    for p_ in sorted(pick):
        t = idx[p_]
        Pc = {kk: v.iloc[: p_ + 1] for kk, v in P.items()}
        dvc = None if dv is None else dv[pd.DatetimeIndex(dv["day"]).floor("D") <= t.floor("D")]
        mic = None if (mi is None or index_symbol is None) else audit_index.load_minutes(index_symbol, t)
        sc = states(Pc, dvc, mic, **q).iloc[-1]
        row = {"t": str(t)}
        for st in STATES:
            row[st] = int(S[st].iloc[p_]), int(sc[st])
        row["same"] = all(row[st][0] == row[st][1] for st in STATES)
        ka.append(row)
    validity["3_known_at"] = ka
    validity["3_pass"] = all(r["same"] for r in ka)

    # validity (4): the episodes
    def _ep(st, lo, hi, scope):
        arr = S[st].to_numpy()[lo: hi + 1]
        ed, runs = episodes_daily(arr)
        nz = arr[arr != 0]
        return {"series": st, "scope": scope, "episodes_daily": ed, "runs_7d": runs, "share_up": float((nz > 0).mean()) if len(nz) else np.nan,
                "cover": float((arr != 0).mean()), "first": str(idx[lo]), "last": str(idx[hi])}
    ep = [_ep(st, 0, n - 1, "span") for st in STATES]
    for k, f in F.items():
        a, b = int(f["pos"].min()), int(f["pos"].max())
        ep += [_ep(st, a, b, k) for st in STATES]
    ep = pd.DataFrame(ep)
    ep.to_csv(out / "episodes.csv", index=False)
    validity["4_episodes"] = ep.to_dict("records")

    # the statistic and the null — the same shift on every state at once
    members = [(k, st) for k in F for st in STATES if (k, st) not in not_in_family and readable[f"{k}/{st}"]]
    Sarr = {st: S[st].to_numpy() for st in STATES}
    obs = {}
    for k, f in F.items():
        x, w = f["net_bps"].to_numpy(), f["size"].to_numpy()
        for st in STATES:
            obs[(k, st)] = _d(x, w, f[st].to_numpy())
    null = {(k, st): np.full(len(shifts), np.nan) for k in F for st in STATES}
    for j, d in enumerate(shifts):
        for k, f in F.items():
            pos, w, x = f["pos"].to_numpy(), f["size"].to_numpy(), f["net_bps"].to_numpy()
            for st in STATES:
                sd_ = Sarr[st][(pos - d * PER_DAY) % n]
                sd_ = np.where(pos >= 0, sd_, 0)
                null[(k, st)][j] = _d(x, w, sd_)
    long = pd.DataFrame([{"rule": k, "state": st, "shift": int(d), "D": null[(k, st)][j]} for (k, st) in null for j, d in enumerate(shifts)])
    long.to_parquet(out / "shifts.parquet", index=False)

    sd = {m: float(np.nanstd(null[m])) for m in null}
    z_obs = {m: abs(obs[m]) / sd[m] if sd[m] > 0 and np.isfinite(obs[m]) else np.nan for m in null}
    # the min-P family: each shift's |D| ranked within its own member's null (p_m(d)), the family's statistic per shift = min over the members
    def _ranks(v: np.ndarray) -> np.ndarray:
        a = np.abs(v)
        srt = np.sort(a[np.isfinite(a)])
        return np.where(np.isfinite(a), (1 + len(srt) - np.searchsorted(srt, a, side="left")) / (1 + len(srt)), np.nan)
    pmat = np.vstack([_ranks(null[m]) for m in members]) if members else np.zeros((0, len(shifts)))
    qmin = np.nanmin(pmat, axis=0) if len(members) else np.full(len(shifts), np.nan)
    rows, half_rows = [], []
    for k, f in F.items():
        x, w, day = f["net_bps"].to_numpy(), f["size"].to_numpy(), f["day"].to_numpy()
        for st in STATES:
            s = f[st].to_numpy()
            up, dn = s > 0, s < 0
            m_up, se_up, lo_up = clustered(x[up], w[up], day[up])
            m_dn, se_dn, lo_dn = clustered(x[dn], w[dn], day[dn])
            D, s_ = obs[(k, st)], sd[(k, st)]
            nk = null[(k, st)]
            p = float((1 + np.sum(np.abs(nk) >= abs(D))) / (1 + len(nk))) if np.isfinite(D) else np.nan
            in_fam = (k, st) in members
            p_fam = float((1 + np.sum(qmin <= p)) / (1 + len(qmin))) if in_fam and np.isfinite(p) else np.nan
            mde = MDE_K * s_
            better, worse = ("+1", "-1") if (np.isfinite(D) and D >= 0) else ("-1", "+1")
            m_b, lo_b = (m_up, lo_up) if better == "+1" else (m_dn, lo_dn)
            m_w = m_dn if better == "+1" else m_up
            names_losing = bool(np.isfinite(m_w) and m_w <= 0 and np.isfinite(lo_b) and lo_b > 0)
            if not readable[f"{k}/{st}"]:
                v = "NOT READABLE"
            elif not in_fam:
                v = "NOT IN THE FAMILY (R45's number)"
            elif p_fam <= P_BAR and names_losing:
                v = "CLEARS"
            elif p_fam <= P_BAR:
                v = "SPLITS WITHOUT A LOSING HALF"
            elif abs(D) + 1.96 * s_ < mde:
                v = "CLOSED"
            elif abs(D) < mde:
                v = "NOT DETECTABLE"
            else:
                v = "NOT CLEAR"
            rows.append({"rule": k, "state": st, "in_family": in_fam, "n_up": int(up.sum()), "n_dn": int(dn.sum()), "mean_up": m_up, "lo_up": lo_up, "se_up": se_up,
                         "mean_dn": m_dn, "lo_dn": lo_dn, "se_dn": se_dn, "D": D, "null_sd": s_, "z": z_obs[(k, st)], "p": p, "p_family": p_fam, "mde": mde,
                         "better": better, "worse_net": m_w, "better_lo": lo_b, "names_losing_half": names_losing, "verdict": v})
            # the half-year table: the net by calendar half-year inside each half
            for hy, g in f.groupby("halfyear"):
                for lab, mask in (("+1", g[st] > 0), ("-1", g[st] < 0)):
                    gg = g[mask]
                    half_rows.append({"rule": k, "state": st, "half": lab, "halfyear": hy, "trades": len(gg),
                                      "net": _wmean(gg["net_bps"].to_numpy(), gg["size"].to_numpy()) if len(gg) else np.nan})
    res = pd.DataFrame(rows)
    hy = pd.DataFrame(half_rows)
    hy.to_csv(out / "halfyears.csv", index=False)

    # the described table: rule × state × fold × half
    by = []
    for k, f in F.items():
        for st in STATES:
            for (s_, fold), g in f[f[st] != 0].groupby([f[st], "fold"]):
                by.append({"rule": k, "state": st, "half": int(s_), "fold": fold, "trades": len(g), "net": _wmean(g["net_bps"].to_numpy(), g["size"].to_numpy())})
    by = pd.DataFrame(by)
    by.to_csv(out / "by_state.csv", index=False)

    # the licensed member per rule: the smallest per-member p among the family's members on that rule (the larger |z| on a tie)
    licensed = {}
    for k in F:
        cand = res[(res["rule"] == k) & res["in_family"]].dropna(subset=["p"])
        if len(cand):
            top = cand.sort_values(["p", "z"], ascending=[True, False]).iloc[0]
            licensed[k] = {"state": top["state"], "verdict": top["verdict"], "p_family": top["p_family"], "D": top["D"]}
    fam_p = float(min(res.loc[res["in_family"], "p_family"].min(), 1.0)) if res["in_family"].any() else np.nan
    cleared = res[res["verdict"] == "CLEARS"]
    verdict = ("CLEARS: " + ", ".join(f"{r.rule} at {r.state}" for r in cleared.itertuples())) if len(cleared) else "NOTHING CLEARS"
    validity["pass"] = bool(validity["1_pass"] and validity["3_pass"])
    summary = {"registration": "R58", "name": name, "pairs": pairs, "start": str(start), "end": str(end), "params": q, "span_days": span_days,
               "shifts": int(len(shifts)), "min_shift": int(min_shift), "rules": {k: v[0] for k, v in rules.items()}, "members": [f"{k}/{st}" for k, st in members],
               "validity": validity, "family_p_min": fam_p, "licensed": licensed, "verdict": verdict, "results": res.to_dict("records")}
    (out / "state.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "state.md").write_text(_report(summary, res, by, hy, ep))
    return summary


def _report(s: dict, res: pd.DataFrame, by: pd.DataFrame, hy: pd.DataFrame, ep: pd.DataFrame) -> str:
    v = s["validity"]
    q = s["params"]
    L = [f"# R58 — the state audit on the parked market-wide rules (`{s['name']}`)", "",
         f"Panel {len(s['pairs'])} pairs, {s['start'][:10]} → {s['end'][:10]} ({s['span_days']} days); S90 the basket's {q['s90_days']}-day sign; V90 its "
         f"{q['v_days']}-day vol against its trailing {q['v_ref_days']}-day median; DVOL BTC's open against its trailing {q['dvol_ref_days']}-day median "
         f"(≥ {q['dvol_min_days']}); PREM the open against {q['prem_symbol']}'s trailing {q['prem_days']}-day realised; SESSION {q['index']} open at t. "
         f"{s['shifts']} whole-day circular shifts (≥ {s['min_shift']} from the ends), the same shift on every state, as the null.", "",
         f"**Validity: {'PASS' if v['pass'] else 'FAIL'}** — (1) the record {'reproduced' if v['1_pass'] else 'NOT reproduced'}; (2) readable: "
         + ", ".join(f"{k} {'yes' if r else 'no'} (cover {v['2_cover'][k]:.2f}, +1 {v['2_share_up'][k]:.2f})" for k, r in v['2_readable'].items())
         + f"; (3) known-at {sum(r['same'] for r in v['3_known_at'])} / {len(v['3_known_at'])} same.", "",
         f"**The family: {len(s['members'])} members ({', '.join(s['members'])}); the smallest family-wise p {s['family_p_min']:.3f}. VERDICT: {s['verdict']}.**", "",
         "## Validity (1): the files", "", "| rule | file | trades | net | record | reproduced |", "|---|---|---|---|---|---|"]
    for r in v["1_record"]:
        rec = "—" if r["record_trades"] is None else f"{r['record_trades']} / {r['record_net']:+.2f}"
        L.append(f"| {r['rule']} | `{r['file']}` | {r['trades']} | {r['net']:+.2f} | {rec} | {r['reproduced']} |")
    L += ["", "## Validity (4): the episodes (sampled daily at 00:00 UTC; runs ≥ 7 days)", "",
          "| series | scope | changes (daily) | runs ≥ 7 d | share in +1 | cover | first | last |", "|---|---|---|---|---|---|---|---|"]
    for _, r in ep.iterrows():
        L.append(f"| {r['series']} | {r['scope']} | {r['episodes_daily']} | {r['runs_7d']} | {r['share_up']:.3f} | {r['cover']:.3f} | {r['first'][:10]} | {r['last'][:10]} |")
    L += ["", "## Per rule and state (net, bps a trade; D = state +1 minus −1; p two-sided over the shifts; p_fam = the family-wise (min-P) p; MDE = 2.8 × the null's sd; lo = the half's day-clustered 95 % lower bound)", "",
          "| rule | state | family | n +1 | n −1 | mean +1 [lo] | mean −1 [lo] | D | null sd | z | p | p_fam | MDE | worse half net | better half lo | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in res.iterrows():
        L.append(f"| {r['rule']} | {r['state']} | {'yes' if r['in_family'] else 'no'} | {r['n_up']} | {r['n_dn']} | {r['mean_up']:+.1f} [{r['lo_up']:+.1f}] | "
                 f"{r['mean_dn']:+.1f} [{r['lo_dn']:+.1f}] | {r['D']:+.1f} | {r['null_sd']:.1f} | {r['z']:.2f} | {r['p']:.3f} | {r['p_family']:.3f} | {r['mde']:.0f} | "
                 f"{r['worse_net']:+.1f} | {r['better_lo']:+.1f} | **{r['verdict']}** |")
    L += ["", "## The licensed member per rule (the smallest per-member p in the family)", ""]
    for k, l in s["licensed"].items():
        L.append(f"- {k}: {l['state']} — {l['verdict']} (D {l['D']:+.1f}, family-wise p {l['p_family']:.3f})")
    L += ["", "## Described: the net by calendar half-year inside each half (bps a trade; trades)", ""]
    for (k, st), g in hy.groupby(["rule", "state"]):
        piv = g.pivot(index="halfyear", columns="half", values="net")
        cnt = g.pivot(index="halfyear", columns="half", values="trades")
        L += [f"**{k} × {st}**", "", "| half-year | +1 net (n) | −1 net (n) |", "|---|---|---|"]
        for hyr in piv.index:
            cell = lambda c: (f"{piv.loc[hyr, c]:+.1f} ({int(cnt.loc[hyr, c])})" if c in piv.columns and np.isfinite(piv.loc[hyr, c]) else "—")   # noqa: E731
            L.append(f"| {hyr} | {cell('+1')} | {cell('-1')} |")
        L.append("")
    L += ["## Described: rule × state × fold × half (net, bps a trade)", "", "| rule | state | half | fold | trades | net |", "|---|---|---|---|---|---|"]
    for _, r in by.iterrows():
        L.append(f"| {r['rule']} | {r['state']} | {r['half']:+d} | {r['fold']} | {r['trades']} | {r['net']:+.1f} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", nargs="*", default=None, help="the panel's pairs; default the twelve from r42_ridgebook_1d_ho12_f5/meta.json")
    ap.add_argument("--start", default=None, help="panel start (default backtest.PRE_START)")
    ap.add_argument("--end", default=None, help="panel end (default F5's end)")
    ap.add_argument("--min-shift", type=int, default=None, help="days; default 90")
    ap.add_argument("--known-at-draws", type=int, default=20)
    ap.add_argument("--name", default="r58_state")
    a = ap.parse_args(argv)
    pairs = a.pairs or json.loads((OUT / "r42_ridgebook_1d_ho12_f5" / "meta.json").read_text())["pairs"]
    start = bt.PRE_START if a.start is None else pd.Timestamp(a.start, tz="UTC")
    end = folds.bounds("F5")[1] if a.end is None else pd.Timestamp(a.end, tz="UTC")
    s = read(RULES, pairs, start, end, a.min_shift, a.name, a.known_at_draws)
    print((OUT / a.name / "state.md").read_text())
    return s


if __name__ == "__main__":
    main()
