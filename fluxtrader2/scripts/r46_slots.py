"""R46 (PLAN §8): execution timing on R14's own historical decisions — the entry at each 5-minute slot of its hour, a described row.

    python scripts/r46_slots.py [--run r42_check_f12 --slots 12 --name r46_slots]   → output/backtest/r46_slots/{slots.md, slots.json, slots.csv, cuts.csv}

The run's SAVED decisions re-priced by `backtest.price` at latency k = 1 … `slots` (the entry at the close of the k-th 5-minute bar
after the decision bar, the exit `hold` bars after the entry, every cost the harness's). k = 1 is the registered execution and must
reproduce the run's saved taker fills (validity (1)). Per slot the size-weighted mean gross / net / hedged net and the PAIRED
difference per trade against k = 1 with a day-clustered se (`backtest.trade_stats`). Two described cuts: (a) the hourly-reversal
cut — the trades whose side has the sign of the name's own last-hour move against its peers at t ("with") and the others ("against");
(b) the settlement cut — the trades whose entry hour holds a funding settlement of the name, the slots before it against the slots
at and after it. No gate: a slot whose net difference has an interval above zero AND ≥ 3 bps is "an entry worth writing" into a
successor's registration; anything less is "nothing to write". No fold is read; the guard is not involved.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import backtest as bt, ceiling, data, folds  # noqa: E402

OUT = Path("output/backtest")
BAR = pd.Timedelta("5min")
WORTH = 3.0          # bps a round trip: the bar for "an entry worth writing"
ROWS = ("gross_bps", "net_bps", "hedged_net_bps")


def _wmean(x, w) -> float:
    return float(np.average(x, weights=w)) if len(x) else np.nan


def _diff_stats(f1: pd.DataFrame, fk: pd.DataFrame, days: pd.DatetimeIndex, lags: int) -> dict:
    m = f1.merge(fk, on="id", suffixes=("_1", "_k"))
    out = {"paired": len(m)}
    for r in ROWS:
        d = (m[f"{r}_k"] - m[f"{r}_1"]).to_numpy()
        st = bt.trade_stats(d, m["size_1"].to_numpy(), pd.DatetimeIndex(m["t_1"]).floor("D"), days, lags)
        out.update({f"d_{r}": st["mean"], f"d_{r}_se": st["se"], f"d_{r}_lo": st["lo"], f"d_{r}_hi": st["hi"]})
    return out


def read(run: str = "r42_check_f12", slots: int = 12, name: str = "r46_slots") -> dict:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((OUT / run / "meta.json").read_text())
    pairs, fold_names, hold = list(meta["pairs"]), list(meta["folds"]), int(meta["params"]["hold"])
    end = folds.bounds(fold_names[-1])[1]
    start = bt.PRE_START if "FP" in fold_names else ceiling.START
    M = bt.market(pairs, end, start)
    C = bt.load_costs(M.index, M.columns, end, float(meta.get("cost_mult", 1.0)), M.close)
    dec = pd.read_parquet(OUT / run / "decisions.parquet")
    saved = pd.read_parquet(OUT / run / "fills_taker.parquet").dropna(subset=["net_bps"])
    days, lags = bt.scored_days(fold_names, M.index[-1]), ceiling.day_lags(hold)
    fills = {k: bt.price(dec, M, C, "taker", float(meta["taker_bps"]), float(meta["maker_bps"]), latency=k).dropna(subset=["net_bps"]) for k in range(1, slots + 1)}

    # validity (1): k = 1 reproduces the saved fills; (2) every slot prices nearly every trade; (3) the run's meta
    m = saved.merge(fills[1], on="id", suffixes=("_s", "_1"))
    dmax = {c: float(np.nanmax(np.abs(m[f"{c}_s"].to_numpy() - m[f"{c}_1"].to_numpy()))) for c in ("entry_px", "exit_px", "net_bps")}
    same_t = bool((m["entry_t_s"] == m["entry_t_1"]).all() and (m["exit_t_s"] == m["exit_t_1"]).all())
    validity = {"1_saved_trades": len(saved), "1_slot1_trades": len(fills[1]), "1_matched": len(m), "1_max_abs_diff": dmax, "1_same_times": same_t,
                "1_pass": bool(len(m) == len(saved) == len(fills[1]) and same_t and max(dmax.values()) <= 1e-6),
                "2_trades_per_slot": {k: len(f) for k, f in fills.items()}, "2_pass": bool(min(len(f) for f in fills.values()) >= len(saved) - 20),
                "3_meta": {"unit": meta.get("unit"), "charged": meta.get("charged"), "folds": fold_names, "strategy": meta["strategy"], "hold": hold},
                "3_pass": bool(meta.get("unit") == "actual" and meta.get("charged") == "value")}
    validity["pass"] = bool(validity["1_pass"] and validity["2_pass"] and validity["3_pass"])

    # per slot: the summary and the paired difference against k = 1
    rows = []
    for k, f in fills.items():
        s = bt.summarize(f, days, hold)
        r = {"slot": k, "minutes": 5 * k, "trades": s["trades"], "gross": s["gross"], "net": s["net"], "net_lo": s["net_lo"], "net_hi": s["net_hi"],
             "hedged_net": s["hedged_net"], "fee": s["fee"], "other_cost": s["other_cost"], "funding": s["funding"]}
        r.update(_diff_stats(fills[1], f, days, lags) if k > 1 else {"paired": len(f), **{f"d_{c}": 0.0 for c in ROWS}, **{f"d_{c}_se": 0.0 for c in ROWS},
                                                                     **{f"d_{c}_lo": 0.0 for c in ROWS}, **{f"d_{c}_hi": 0.0 for c in ROWS}})
        rows.append(r)
    slots_df = pd.DataFrame(rows)
    slots_df.to_csv(out / "slots.csv", index=False)
    best = slots_df[slots_df["slot"] > 1].sort_values("d_net_bps", ascending=False).iloc[0]
    worth = bool(best["d_net_bps_lo"] > 0 and best["d_net_bps"] >= WORTH)
    verdict = ("AN ENTRY WORTH WRITING" if worth else "NOTHING TO WRITE") + f" — the best slot is a maximum of {slots - 1}, not a finding"

    # cut (a): the name's own last-hour move against its peers at t, with or against the side
    lr = np.log(M.close)
    m1h = (lr - lr.shift(12)) * 1e4
    rel = m1h.sub(ceiling.basket(m1h), axis=0)
    d = dec[dec["accepted"]]
    pos, j = M.index.get_indexer(d["t"]), M.columns.get_indexer(d["symbol"])
    own = np.where(pos >= 0, rel.to_numpy()[np.maximum(pos, 0), j], np.nan)
    side_sign = np.sign(own) * d["side"].to_numpy()
    cut_a = pd.Series(np.where(side_sign > 0, "with", np.where(side_sign < 0, "against", "none")), index=d.index)
    # cut (b): a funding settlement of the name inside the entry hour (t, t + 60 min]
    fa = data.load("funding_archive", columns=["symbol", "ts", "rate"], symbols=pairs)
    fa["symbol"] = fa["symbol"].astype(str)
    ev = {s: np.sort(pd.DatetimeIndex(g["ts"]).as_unit("ns").asi8) for s, g in fa.groupby("symbol")}
    tns = pd.DatetimeIndex(d["t"]).as_unit("ns").asi8
    settle = np.full(len(d), np.nan)
    for i, (s, t0) in enumerate(zip(d["symbol"].to_numpy(), tns)):
        e = ev.get(s)
        if e is None or not len(e):
            continue
        q = np.searchsorted(e, t0, "right")
        if q < len(e) and e[q] <= t0 + 3600 * 10**9:
            settle[i] = e[q]
    cut_b = pd.Series(settle, index=d.index)

    cuts = []
    for k, f in fills.items():
        f1 = fills[1]
        for lab in ("with", "against"):
            ids = cut_a.index[cut_a == lab]
            fk, f1k = f[f["id"].isin(ids)], f1[f1["id"].isin(ids)]
            r = {"cut": "reversal", "group": lab, "slot": k, "trades": len(fk), "gross": _wmean(fk["gross_bps"], fk["size"]), "net": _wmean(fk["net_bps"], fk["size"])}
            r.update(_diff_stats(f1k, fk, days, lags) if k > 1 else {})
            cuts.append(r)
        ids = cut_b.index[cut_b.notna()]
        fk = f[f["id"].isin(ids)].merge(pd.DataFrame({"id": ids, "settle": pd.to_datetime(cut_b.loc[ids].to_numpy(), utc=True)}), on="id")
        if len(fk):
            before = fk["entry_t"] < fk["settle"]
            for lab, msk in (("before", before), ("at/after", ~before)):
                g = fk[msk]
                cuts.append({"cut": "settlement", "group": lab, "slot": k, "trades": len(g), "gross": _wmean(g["gross_bps"], g["size"]),
                             "net": _wmean(g["net_bps"], g["size"]), "funding": _wmean(g["funding_bps"], g["size"])})
    cuts_df = pd.DataFrame(cuts)
    cuts_df.to_csv(out / "cuts.csv", index=False)
    pooled_b = []
    for lab in ("before", "at/after"):
        g = cuts_df[(cuts_df["cut"] == "settlement") & (cuts_df["group"] == lab)]
        if len(g):
            w = g["trades"].to_numpy()
            pooled_b.append({"group": lab, "slot_trades": int(w.sum()), "gross": _wmean(g["gross"], w), "net": _wmean(g["net"], w), "funding": _wmean(g["funding"], w)})

    summary = {"registration": "R46", "name": name, "run": run, "slots": slots, "hold": hold, "pairs": pairs, "folds": fold_names, "validity": validity,
               "best_slot": {"slot": int(best["slot"]), "d_net": float(best["d_net_bps"]), "lo": float(best["d_net_bps_lo"]), "hi": float(best["d_net_bps_hi"])},
               "worth": worth, "verdict": verdict, "settlement_hours": int(cut_b.notna().sum()),
               "reversal_counts": cut_a.value_counts().to_dict(), "settlement_pooled": pooled_b, "slots_table": slots_df.to_dict("records")}
    (out / "slots.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "slots.md").write_text(_report(summary, slots_df, cuts_df))
    return summary


def _report(s: dict, sl: pd.DataFrame, cuts: pd.DataFrame) -> str:
    v = s["validity"]
    L = [f"# R46 — execution timing on {s['run']}'s saved decisions (`{s['name']}`)", "",
         f"Hold {s['hold']} bars, {len(s['pairs'])} pairs, folds {'+'.join(s['folds'])}; the entry at the close of the k-th 5-minute bar after the decision, k = 1 … {s['slots']}.", "",
         f"**Validity: {'PASS' if v['pass'] else 'FAIL'}** — (1) k = 1 against the saved fills: {v['1_matched']} / {v['1_saved_trades']} matched, "
         f"max |Δ| entry {v['1_max_abs_diff']['entry_px']:.2e}, exit {v['1_max_abs_diff']['exit_px']:.2e}, net {v['1_max_abs_diff']['net_bps']:.2e}, "
         f"times {'same' if v['1_same_times'] else 'DIFFER'}; (2) trades per slot {min(v['2_trades_per_slot'].values())} … {max(v['2_trades_per_slot'].values())}; "
         f"(3) unit {v['3_meta']['unit']}, charged {v['3_meta']['charged']}.", "",
         f"**{s['verdict']}**: slot {s['best_slot']['slot']} nets {s['best_slot']['d_net']:+.2f} [{s['best_slot']['lo']:+.2f}, {s['best_slot']['hi']:+.2f}] against k = 1 (bar {WORTH:.0f} with the interval above zero).", "",
         "## The slot curve (bps a trade; d = the paired difference against k = 1, day-clustered)", "",
         "| k | min | trades | gross | net | hedged net | funding | d gross | se | d net | [lo, hi] | d hedged net |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in sl.iterrows():
        L.append(f"| {r['slot']} | {r['minutes']} | {r['trades']} | {r['gross']:+.2f} | {r['net']:+.2f} | {r['hedged_net']:+.2f} | {r['funding']:+.2f} | "
                 f"{r['d_gross_bps']:+.2f} | {r['d_gross_bps_se']:.2f} | {r['d_net_bps']:+.2f} | [{r['d_net_bps_lo']:+.2f}, {r['d_net_bps_hi']:+.2f}] | {r['d_hedged_net_bps']:+.2f} |")
    L += ["", f"## Cut (a): the hour's own move against the peers — with / against the side ({s['reversal_counts']})", "",
          "| group | k | trades | gross | net | d gross | se | d net |", "|---|---|---|---|---|---|---|---|"]
    for _, r in cuts[cuts["cut"] == "reversal"].iterrows():
        dg = f"{r['d_gross_bps']:+.2f}" if pd.notna(r.get("d_gross_bps", np.nan)) else "—"
        se = f"{r['d_gross_bps_se']:.2f}" if pd.notna(r.get("d_gross_bps_se", np.nan)) else "—"
        dn = f"{r['d_net_bps']:+.2f}" if pd.notna(r.get("d_net_bps", np.nan)) else "—"
        L.append(f"| {r['group']} | {r['slot']} | {r['trades']} | {r['gross']:+.2f} | {r['net']:+.2f} | {dg} | {se} | {dn} |")
    L += ["", f"## Cut (b): a settlement inside the entry hour ({s['settlement_hours']} decisions) — the slots before it against the slots at and after it", "",
          "| group | slot-trades | gross | net | funding |", "|---|---|---|---|---|"]
    for r in s["settlement_pooled"]:
        L.append(f"| {r['group']} | {r['slot_trades']} | {r['gross']:+.2f} | {r['net']:+.2f} | {r['funding']:+.2f} |")
    L += ["", "| group | k | trades | gross | net | funding |", "|---|---|---|---|---|---|"]
    for _, r in cuts[cuts["cut"] == "settlement"].iterrows():
        L.append(f"| {r['group']} | {r['slot']} | {r['trades']} | {r['gross']:+.2f} | {r['net']:+.2f} | {r['funding']:+.2f} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="r42_check_f12")
    ap.add_argument("--slots", type=int, default=12)
    ap.add_argument("--name", default="r46_slots")
    a = ap.parse_args(argv)
    s = read(a.run, a.slots, a.name)
    print((OUT / a.name / "slots.md").read_text())
    return s


if __name__ == "__main__":
    main()
