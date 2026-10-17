"""R45 (PLAN §8): the market's state as a pre-registered observable, read on the SAVED fills of R14, R32 and R44.

    python scripts/r45_state.py                      → output/backtest/r45_state/{state.md, state.json, shifts.parquet, by_state.csv, episodes.csv}

The state S90 at a decision bar t is the sign of the twelve's basket's move over the trailing `--days` (90) days — `market.derive`'s
`blr` (the cumulative equal-weight 5m basket move, MIN_PAIRS 5) on `backtest.market(PAIRS, end, start)`. Described beside: S30 (the
30-day sign) and V30 (the basket's 30-day realised 5m volatility above / below the median of its own trailing 365 days). Nothing in a
state uses a bar after t.

Each set's trades (the harness's saved taker fills; the unpriced dropped) are joined to the state at their decision time. The statistic
per set and row (net, hedged net): D = the size-weighted mean on the trades decided in state +1 minus the same in state −1. The null:
the state series circularly shifted by every admissible whole-day shift d (min_shift ≤ d ≤ span − min_shift); per set the two-sided
p = (1 + #{|D(d)| ≥ |D|}) / (1 + #shifts); the family-wise p over the sets on one row = the same count on max_k |D_k(d)| / sd_k, sd_k the
sd of D_k over the shifts. A re-reading of saved fills: no walk, no fit, no fold read; the guard is not involved.
"""
from __future__ import annotations

import argparse
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
# the registered sets (PLAN §8 R45 "Cells"): name → the files, relative to output/backtest (a run directory → its fills_taker.parquet)
SETS = {"A": ["r42_check_f12", "r42_pool/pooled_fills.parquet"], "B": ["trend1d"], "C": ["r44_mombook_28d_f12", "r44_mombook_28d_f34"]}
# validity (1): the record's size-weighted taker net on each file (trades, net); a file without a row is reported as "no record"
RECORD = {"r42_check_f12": (1896, 39.16), "r42_pool/pooled_fills.parquet": (2669, 25.31), "trend1d": (14672, 10.67),
          "r44_mombook_28d_f12": (334, 331.0), "r44_mombook_28d_f34": (315, -66.1)}
ROWS = {"net": "net_bps", "hedged": "hedged_net_bps"}
STATES = ("S90", "S30", "V30")


def _fills(path: str) -> pd.DataFrame:
    p = OUT / path
    f = pd.read_parquet(p / "fills_taker.parquet" if p.is_dir() else p)
    f = f.dropna(subset=["net_bps"]).copy()
    f["file"] = path
    return f


def states(P: dict, days: int, s30_days: int, vol_days: int, vol_ref_days: int) -> pd.DataFrame:
    """The three state series on the panel's 5m grid: +1 / −1, 0 where undefined (not enough history)."""
    D = mk.derive(P)
    blr, b1 = D["blr"], D["b1"]
    sgn = lambda x: np.sign(x.fillna(0.0)).astype(int)                                 # noqa: E731
    s90 = sgn(blr - blr.shift(days * PER_DAY))
    s30 = sgn(blr - blr.shift(s30_days * PER_DAY))
    sig = b1.rolling(vol_days * PER_DAY, min_periods=int(vol_days * PER_DAY * 0.8)).std()
    ref = sig.rolling(vol_ref_days * PER_DAY, min_periods=int(vol_ref_days * PER_DAY * 0.5)).median()
    v30 = sgn((sig - ref).where(sig.notna() & ref.notna()))
    return pd.DataFrame({"S90": s90, "S30": s30, "V30": v30}, index=P["close"].index)


def episodes(s: np.ndarray) -> int:
    """Sign changes of a ±1 / 0 series, the zeros skipped."""
    x = s[s != 0]
    return int((np.diff(x) != 0).sum()) if len(x) > 1 else 0


def _d(x: np.ndarray, w: np.ndarray, s: np.ndarray) -> float:
    up, dn = s > 0, s < 0
    if w[up].sum() <= 0 or w[dn].sum() <= 0:
        return np.nan
    return float(np.average(x[up], weights=w[up]) - np.average(x[dn], weights=w[dn]))


def read(sets: dict[str, list[str]], pairs: list[str], start: pd.Timestamp, end: pd.Timestamp, days: int = 90, s30_days: int = 30,
         vol_days: int = 30, vol_ref_days: int = 365, min_shift: int | None = None, name: str = "r45_state", known_at_draws: int = 20,
         seed: int = 0, record: dict | None = None) -> dict:
    record = RECORD if record is None else record
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    P = ceiling.panel(pairs, end, start)
    idx = P["close"].index
    S = states(P, days, s30_days, vol_days, vol_ref_days)
    n = len(idx)
    span_days = int(np.ceil((idx[-1] - idx[0]) / pd.Timedelta(1, "D")))
    min_shift = days if min_shift is None else min_shift
    shifts = np.arange(min_shift, span_days - min_shift + 1)
    if len(shifts) < 10:
        raise SystemExit(f"r45: {len(shifts)} admissible shifts on a span of {span_days} days — not a null")

    # the sets, their validity (1) and the join to the state at t
    F, validity, val_rows = {}, {}, []
    for k, files in sets.items():
        parts = []
        for path in files:
            f = _fills(path)
            w = f["size"].to_numpy()
            net = float(np.average(f["net_bps"], weights=w)) if len(f) else np.nan
            rec = record.get(path)
            ok = None if rec is None else (len(f) == rec[0] and abs(net - rec[1]) <= 0.05)
            val_rows.append({"set": k, "file": path, "trades": len(f), "net": net, "record_trades": None if rec is None else rec[0],
                             "record_net": None if rec is None else rec[1], "reproduced": "no record" if ok is None else bool(ok)})
            parts.append(f)
        f = pd.concat(parts, ignore_index=True)
        pos = idx.get_indexer(pd.DatetimeIndex(f["t"]))
        f["pos"] = pos
        for st in STATES:
            f[st] = np.where(pos >= 0, S[st].to_numpy()[np.maximum(pos, 0)], 0)
        F[k] = f
    validity["1_record"] = val_rows
    validity["1_pass"] = all(r["reproduced"] in (True, "no record") for r in val_rows)

    # validity (2): the state exists on ≥ 95 % of each set's decision bars; (4) each state ≥ 10 % of the set's trades (per state series)
    cover = {k: float((f["S90"] != 0).mean()) for k, f in F.items()}
    validity["2_cover_S90"] = cover
    validity["2_pass"] = all(v >= 0.95 for v in cover.values())
    readable = {st: {k: bool(min((f[st] > 0).mean(), (f[st] < 0).mean()) >= 0.10) for k, f in F.items()} for st in STATES}
    validity["4_readable"] = readable
    validity["4_share_up"] = {st: {k: float((f[st][f[st] != 0] > 0).mean()) if (f[st] != 0).any() else np.nan for k, f in F.items()} for st in STATES}

    # validity (3): known-at — S90 on the panel cut at t equals the full-panel S90, on decision bars drawn at random
    rng = np.random.default_rng(seed)
    allpos = np.unique(np.concatenate([f["pos"].to_numpy() for f in F.values()]))
    allpos = allpos[allpos >= 0]
    pick = rng.choice(allpos, size=min(known_at_draws, len(allpos)), replace=False)
    ka = []
    for p_ in sorted(pick):
        Pc = {k: v.iloc[: p_ + 1] for k, v in P.items()}
        sc = states(Pc, days, s30_days, vol_days, vol_ref_days)
        ka.append({"t": str(idx[p_]), "full": int(S["S90"].iloc[p_]), "cut": int(sc["S90"].iloc[-1]), "same": int(S["S90"].iloc[p_]) == int(sc["S90"].iloc[-1])})
    validity["3_known_at"] = ka
    validity["3_pass"] = all(r["same"] for r in ka)

    # validity (5): the episodes
    ep = [{"series": st, "scope": "span", "episodes": episodes(S[st].to_numpy()), "share_up": float((S[st][S[st] != 0] > 0).mean()),
           "first": str(idx[0]), "last": str(idx[-1])} for st in STATES]
    for k, f in F.items():
        a, b = f["pos"].min(), f["pos"].max()
        for st in STATES:
            ep.append({"series": st, "scope": k, "episodes": episodes(S[st].to_numpy()[a: b + 1]), "share_up": validity["4_share_up"][st][k],
                       "first": str(idx[a]), "last": str(idx[b])})
    ep = pd.DataFrame(ep)
    ep.to_csv(out / "episodes.csv", index=False)
    validity["5_episodes"] = ep.to_dict("records")

    # the statistic and the null
    Sarr = {st: S[st].to_numpy() for st in STATES}
    obs, null = {}, []
    for st in STATES:
        for k, f in F.items():
            pos, w = f["pos"].to_numpy(), f["size"].to_numpy()
            x = {r: f[c].to_numpy() for r, c in ROWS.items()}
            s0 = f[st].to_numpy()
            for r in ROWS:
                obs[(st, k, r)] = _d(x[r], w, s0)
            for d in shifts:
                sd_ = Sarr[st][(pos - d * PER_DAY) % n]
                sd_ = np.where(pos >= 0, sd_, 0)
                null.append({"state": st, "set": k, "shift": int(d), **{r: _d(x[r], w, sd_) for r in ROWS}})
    null = pd.DataFrame(null)
    null.to_parquet(out / "shifts.parquet", index=False)

    rows = []
    fam = {}
    for st in STATES:
        for r in ROWS:
            z_obs, z_null = [], []
            for k in F:
                nk = null[(null["state"] == st) & (null["set"] == k)][r].to_numpy()
                D = obs[(st, k, r)]
                sd = float(np.nanstd(nk))
                p = float((1 + np.sum(np.abs(nk) >= abs(D))) / (1 + len(nk))) if np.isfinite(D) else np.nan
                mde = MDE_K * sd
                f = F[k]
                up, dn = f[st] > 0, f[st] < 0
                rows.append({"state": st, "set": k, "row": r, "D": D, "null_sd": sd, "p": p, "mde": mde, "readable": readable[st][k],
                             "n_up": int(up.sum()), "n_dn": int(dn.sum()),
                             "mean_up": float(np.average(f.loc[up, ROWS[r]], weights=f.loc[up, "size"])) if up.any() else np.nan,
                             "mean_dn": float(np.average(f.loc[dn, ROWS[r]], weights=f.loc[dn, "size"])) if dn.any() else np.nan,
                             "verdict": ("NOT READABLE" if not readable[st][k] else "CLEARS" if p <= 0.05 else
                                         "CLOSED" if abs(D) + 1.96 * sd < mde else "NOT DETECTABLE" if abs(D) < mde else "NOT CLEAR")})
                if readable[st][k] and np.isfinite(D) and sd > 0:
                    z_obs.append(abs(D) / sd)
                    z_null.append(np.abs(nk) / sd)
            if z_obs:
                zo, zn = max(z_obs), np.max(np.vstack(z_null), axis=0)
                fam[(st, r)] = {"members": sum(1 for _ in z_obs), "z": float(zo), "p_family": float((1 + np.sum(zn >= zo)) / (1 + len(zn)))}
            else:
                fam[(st, r)] = {"members": 0, "z": np.nan, "p_family": np.nan}
    res = pd.DataFrame(rows)

    # the described table: set × S90 state × fold × side
    by = []
    for k, f in F.items():
        for (st_, fold, side), g in f[f["S90"] != 0].groupby([f["S90"], "fold", "side"]):
            w = g["size"].to_numpy()
            by.append({"set": k, "S90": int(st_), "fold": fold, "side": int(side), "trades": len(g),
                       "net": float(np.average(g["net_bps"], weights=w)), "hedged_net": float(np.average(g["hedged_net_bps"], weights=w))})
    by = pd.DataFrame(by)
    by.to_csv(out / "by_state.csv", index=False)

    pf = {f"{st}/{r}": v for (st, r), v in fam.items()}
    verdict = {"net": "CLEARS on the net" if pf["S90/net"]["p_family"] <= 0.05 else "NOT CLEAR on the net",
               "hedged": "CLEARS on the hedged" if pf["S90/hedged"]["p_family"] <= 0.05 else "NOT CLEAR on the hedged"}
    validity["pass"] = bool(validity["1_pass"] and validity["2_pass"] and validity["3_pass"])
    summary = {"registration": "R45", "name": name, "pairs": pairs, "start": str(start), "end": str(end), "days": days, "s30_days": s30_days,
               "vol_days": vol_days, "vol_ref_days": vol_ref_days, "span_days": span_days, "shifts": int(len(shifts)), "min_shift": int(min_shift),
               "sets": sets, "validity": validity, "families": pf, "verdict": verdict, "results": res.to_dict("records")}
    (out / "state.json").write_text(json.dumps(summary, indent=1, default=str))
    md = _report(summary, res, by, ep)
    (out / "state.md").write_text(md)
    return summary


def _report(s: dict, res: pd.DataFrame, by: pd.DataFrame, ep: pd.DataFrame) -> str:
    v = s["validity"]
    L = [f"# R45 — the market's state on saved decisions (`{s['name']}`)", "",
         f"Panel {len(s['pairs'])} pairs, {s['start'][:10]} → {s['end'][:10]} ({s['span_days']} days); S90 = the basket's {s['days']}-day sign, "
         f"S30 the {s['s30_days']}-day sign, V30 the {s['vol_days']}-day vol against its trailing {s['vol_ref_days']}-day median; "
         f"{s['shifts']} whole-day circular shifts (≥ {s['min_shift']} from the ends) as the null.", "",
         f"**Validity: {'PASS' if v['pass'] else 'FAIL'}** — (1) the record {'reproduced' if v['1_pass'] else 'NOT reproduced'}; "
         f"(2) S90 covers {', '.join(f'{k} {c:.3f}' for k, c in v['2_cover_S90'].items())} of the decision bars; "
         f"(3) known-at {sum(r['same'] for r in v['3_known_at'])} / {len(v['3_known_at'])} same; "
         f"(4) readable at S90: {', '.join(f'{k} {r}' for k, r in v['4_readable']['S90'].items())}.", "",
         "## Validity (1): the files", "", "| set | file | trades | net | record | reproduced |", "|---|---|---|---|---|---|"]
    for r in v["1_record"]:
        rec = "—" if r["record_trades"] is None else f"{r['record_trades']} / {r['record_net']:+.2f}"
        L.append(f"| {r['set']} | `{r['file']}` | {r['trades']} | {r['net']:+.2f} | {rec} | {r['reproduced']} |")
    L += ["", "## Validity (5): the episodes", "", "| series | scope | episodes | share in +1 | first | last |", "|---|---|---|---|---|---|"]
    for _, r in ep.iterrows():
        L.append(f"| {r['series']} | {r['scope']} | {r['episodes']} | {r['share_up']:.3f} | {r['first'][:10]} | {r['last'][:10]} |")
    L += ["", f"## The verdict: **{s['verdict']['net']}** (family-wise p {s['families']['S90/net']['p_family']:.3f}), "
          f"**{s['verdict']['hedged']}** (p {s['families']['S90/hedged']['p_family']:.3f})", "",
          "| state | row | members | max |D| / sd | family-wise p |", "|---|---|---|---|---|"]
    for key, f in s["families"].items():
        st, r = key.split("/")
        L.append(f"| {st} | {r} | {f['members']} | {f['z']:.2f} | {f['p_family']:.3f} |")
    L += ["", "## Per set and row (bps a trade; D = state +1 minus state −1; p two-sided over the shifts; MDE = 2.8 × the null's sd)", "",
          "| state | set | row | n +1 | n −1 | mean +1 | mean −1 | D | null sd | p | MDE | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in res.iterrows():
        L.append(f"| {r['state']} | {r['set']} | {r['row']} | {r['n_up']} | {r['n_dn']} | {r['mean_up']:+.1f} | {r['mean_dn']:+.1f} | {r['D']:+.1f} | "
                 f"{r['null_sd']:.1f} | {r['p']:.3f} | {r['mde']:.0f} | {r['verdict']} |")
    L += ["", "## Described: set × S90 × fold × side (net / hedged net, bps a trade)", "", "| set | S90 | fold | side | trades | net | hedged net |", "|---|---|---|---|---|---|---|"]
    for _, r in by.iterrows():
        L.append(f"| {r['set']} | {r['S90']:+d} | {r['fold']} | {r['side']:+d} | {r['trades']} | {r['net']:+.1f} | {r['hedged_net']:+.1f} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", action="append", default=None, help="NAME=path[,path…] (relative to output/backtest); default the registered sets")
    ap.add_argument("--pairs", nargs="*", default=None, help="the panel's pairs; default the twelve from r42_ridgebook_1d_ho12_f5/meta.json")
    ap.add_argument("--start", default=None, help="panel start (default backtest.PRE_START)")
    ap.add_argument("--end", default=None, help="panel end (default F5's end)")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--s30-days", type=int, default=30)
    ap.add_argument("--vol-days", type=int, default=30)
    ap.add_argument("--vol-ref-days", type=int, default=365)
    ap.add_argument("--min-shift", type=int, default=None, help="days; default --days")
    ap.add_argument("--known-at-draws", type=int, default=20)
    ap.add_argument("--name", default="r45_state")
    ap.add_argument("--no-record", action="store_true", help="validity (1) without the record (tests)")
    a = ap.parse_args(argv)
    sets = SETS if a.set is None else {kv.split("=")[0]: kv.split("=")[1].split(",") for kv in a.set}
    pairs = a.pairs or json.loads((OUT / "r42_ridgebook_1d_ho12_f5" / "meta.json").read_text())["pairs"]
    start = bt.PRE_START if a.start is None else pd.Timestamp(a.start, tz="UTC")
    end = folds.bounds("F5")[1] if a.end is None else pd.Timestamp(a.end, tz="UTC")
    s = read(sets, pairs, start, end, a.days, a.s30_days, a.vol_days, a.vol_ref_days, a.min_shift, a.name, a.known_at_draws, record={} if a.no_record else None)
    print((OUT / a.name / "state.md").read_text())
    return s


if __name__ == "__main__":
    main()
