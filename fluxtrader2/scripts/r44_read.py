"""R44's read (docs/PLAN.md §8): the validity lines of a `mombook` run that the harness does not print, the clipped row, the per-fold
line, the sides and the gate applied line by line. Run where the run's output and the market are (the work VM):
  python scripts/r44_read.py r44_mombook_28d_f12 [r44_mombook_14d_f12]      → output/backtest/r44_read[_<tag>].md, .json
The first run is the one gated; the second (the 14-day hold) is described. The verdict is stage 1's PASS / FAIL for an exploration run and
stage 2's CONFIRMED / NOT CONFIRMED for a run under the registration (meta["registration"] == "R44")."""
import json
import re
import sys

import numpy as np
import pandas as pd

from ft2 import audit, backtest as bt, ceiling, folds, universe
from ft2.horizon import mom_signals

REG, CLIP, MIN_FOLD_TRADES, TOL = "R44", 3000.0, 100, 1e-9


def clipped_row(f: pd.DataFrame, days: pd.DatetimeIndex, hold: int, clip: float = CLIP) -> dict:
    """The size-weighted net over the priced trades with every trade's gross clipped at ±clip, its costs and funding unchanged;
    clip = ∞ is the harness's own net (validity (5))."""
    f = f.dropna(subset=["net_bps"])
    g = f["gross_bps"].to_numpy()
    x = np.clip(g, -clip, clip) + (f["net_bps"].to_numpy() - g)
    return bt.trade_stats(x, f["size"].to_numpy(), pd.DatetimeIndex(f["t"]).floor("D"), days, bt.day_lags(hold))


def read(run: str, M: bt.Market | None = None) -> tuple[dict, bt.Market]:
    rd = bt.OUT / run
    meta = json.loads((rd / "meta.json").read_text())
    p = meta["params"]
    dec = pd.read_parquet(rd / "decisions.parquet")
    fills = pd.read_parquet(rd / "fills_taker.parquet")
    res = pd.read_parquet(rd / "results.parquet")
    res = res[res["exec"] == "taker"].set_index("scope")
    nul = pd.read_parquet(rd / "null.parquet")
    last = folds.bounds(meta["folds"][-1])[1]
    if M is None:
        M = bt.market(meta["pairs"], last, bt.PRE_START if "FP" in meta["folds"] else ceiling.START)
    hold = int(p["hold"])
    v: dict = {"run": run, "registration": meta.get("registration"), "folds": meta["folds"], "params": p}
    # (1) the book's shape
    v["book_check"] = audit.book_check(run, members=p.get("members") or None)
    # (2) the decisions carry the audit's signal and the audit's tenth
    S = mom_signals(M.close, {"mom": int(p["window"])})["mom"]
    t, j = M.index.get_indexer(dec["t"]), M.columns.get_indexer(dec["symbol"])
    v["max_abs_d_signal"] = float(np.nanmax(np.abs(dec["signal"].to_numpy() - S.to_numpy()[t, j]))) if len(dec) else 0.0
    mem = universe.members(p.get("members") or None)
    ts = pd.DatetimeIndex(sorted(set(dec["t"])))
    ok = M.close.loc[ts].notna() & S.loc[ts].notna() & audit.member_mask(mem, np.asarray(list(M.columns), dtype=str), ts)
    n = ok.sum(axis=1)
    k_exp = pd.Series(np.where(n >= int(p["min_cells"]), np.maximum(np.rint(n * float(p["tenth"])).astype(int), 1), 0), index=ts)
    per_bar = dec.groupby("t")["side"].agg(longs=lambda x: int((x > 0).sum()), shorts=lambda x: int((x < 0).sum()))
    v["bars_decided"], v["bars_k_wrong"] = int(len(per_bar)), int(((per_bar["longs"] != k_exp.loc[per_bar.index]) | (per_bar["shorts"] != k_exp.loc[per_bar.index])).sum())
    v["k_min"], v["k_max"], v["n_min"], v["n_max"] = int(k_exp.loc[per_bar.index].min()), int(k_exp.loc[per_bar.index].max()), int(n.loc[per_bar.index].min()), int(n.loc[per_bar.index].max())
    # (3) meta
    v["meta"] = {k: meta.get(k) for k in ("unit", "charged", "folds", "registration", "pairs_on_proxy_cost", "decisions", "accepted", "max_open", "avg_open")}
    v["meta"]["pairs_on_proxy_cost"] = len(meta.get("pairs_on_proxy_cost", [])), len(meta["pairs"])
    # (4) unpriced = exits after the last bar only
    un = fills[fills["net_bps"].isna()]
    beyond = M.index.get_indexer(un["t"]) + bt.LATENCY + hold >= len(M.index)
    v["unpriced"], v["unpriced_not_beyond_last_bar"] = int(len(un)), int((~beyond).sum())
    # (5) the clipped row's arithmetic at clip ∞ is the harness's
    days = bt.scored_days(meta["folds"], M.index[-1])
    inf = clipped_row(fills, days, hold, np.inf)
    v["max_abs_d_clip_inf"] = float(max(abs(inf["mean"] - res.loc["all", "net"]), abs(inf["lo"] - res.loc["all", "net_lo"]), abs(inf["hi"] - res.loc["all", "net_hi"])))
    fl = nul[(nul["kind"] == "flip") & (nul["exec"] == "taker")]["net"].dropna()
    real = float(res.loc["all", "net"])
    v["flip"] = {"draws": int(len(fl)), "null_mean": float(fl.mean()), "null_sd": float(fl.std()), "null_p95": float(fl.quantile(0.95)), "p": (1 + int((fl >= real).sum())) / (len(fl) + 1)}
    rep = (rd / "report.md").read_text()
    m = re.search(r"\*\*taker:.*?flip null .*?, p = ([0-9]+(?:\.[0-9]+)?)", rep, re.S)
    v["flip_p_report"] = float(m.group(1)) if m else None
    # (6) trades per fold
    v["per_fold"] = {fo: {"trades": int(res.loc[fo, "trades"]), "net": float(res.loc[fo, "net"]), "net_lo": float(res.loc[fo, "net_lo"]), "net_hi": float(res.loc[fo, "net_hi"]),
                          "hedged_net": float(res.loc[fo, "hedged_net"])} for fo in meta["folds"]}
    v["validity"] = {"(1) book_check": v["book_check"]["status"] == "PASS", "(2) signal and tenth": v["max_abs_d_signal"] <= TOL and v["bars_k_wrong"] == 0,
                     "(3) meta": meta.get("unit") == "actual" and meta.get("charged") == "value" and v["meta"]["pairs_on_proxy_cost"][0] == v["meta"]["pairs_on_proxy_cost"][1],
                     "(4) unpriced": v["unpriced_not_beyond_last_bar"] == 0, "(5) clip inf": v["max_abs_d_clip_inf"] <= TOL and abs(v["flip"]["p"] - (v["flip_p_report"] or -1)) < 5e-4,
                     "(6) trades a fold": all(x["trades"] >= MIN_FOLD_TRADES for x in v["per_fold"].values())}
    v["validity_status"] = "PASS" if all(v["validity"].values()) else "FAIL"
    # the money
    v["all"] = {k: float(res.loc["all", k]) for k in ("trades", "trades_per_day", "hit", "gross", "hedged", "fee", "other_cost", "funding", "net", "net_lo", "net_hi", "net_mde", "hedged_net", "hedged_net_lo", "hedged_net_hi")}
    v["sides"] = {s: {k: float(res.loc[s, k]) for k in ("trades", "gross", "hedged", "net", "net_lo", "net_hi", "hedged_net")} for s in ("long", "short") if s in res.index}
    v["clipped"] = clipped_row(fills, days, hold)
    v["clipped"]["share_clipped"] = float((fills["gross_bps"].abs() > CLIP).mean()) if len(fills) else 0.0
    sh = nul[(nul["kind"] == "shuffle") & (nul["exec"] == "taker")]["net"].dropna()
    v["shuffle"] = {"draws": int(len(sh)), "null_sd": float(sh.std()) if len(sh) > 1 else None, "note": "uninformative for a rule without a fit (the decisions do not depend on the labels); decides nothing"}
    g = {"(i) net > 0": v["all"]["net"] > 0, "(ii) hedged net > 0": v["all"]["hedged_net"] > 0, "(iii) flip p <= 0.05": v["flip"]["p"] <= 0.05,
         "(iv) net > 0 in each fold": all(x["net"] > 0 for x in v["per_fold"].values()), "(v) clipped row > 0": v["clipped"]["mean"] > 0}
    v["gate"] = g
    stage2 = meta.get("registration") == REG
    if v["validity_status"] != "PASS":
        v["verdict"] = "VOID (validity)"
    elif all(g.values()):
        v["verdict"] = "CONFIRMED" if stage2 else "PASS — stage 2 licensed (Vadim's go)"
    else:
        v["verdict"] = ("NOT CONFIRMED" if stage2 else "FAIL — parked") + ": " + ", ".join(k for k, x in g.items() if not x)
    return v, M


def md(v: dict, d: dict | None) -> str:
    a, c, f = v["all"], v["clipped"], v["flip"]
    out = [f"# R44 read — `{v['run']}` (folds {'+'.join(v['folds'])}{', registration ' + v['registration'] if v['registration'] else ', exploration'})\n",
           f"\n## Validity — read first: **{v['validity_status']}**\n", "```\n" + json.dumps({k: v[k] for k in ("validity", "book_check", "max_abs_d_signal", "bars_decided", "bars_k_wrong", "k_min", "k_max", "n_min", "n_max", "meta", "unpriced", "unpriced_not_beyond_last_bar", "max_abs_d_clip_inf", "flip_p_report")}, indent=1, default=str) + "\n```\n",
           f"\n## The book, taker (bps per unit of notional)\n",
           f"\n{a['trades']:.0f} trades ({a['trades_per_day']:.2f} a day), hit {a['hit']:.1%}; gross {a['gross']:+.2f} (hedged {a['hedged']:+.2f}), fee {a['fee']:.2f}, other {a['other_cost']:.2f}, funding {a['funding']:+.2f} → "
           f"**net {a['net']:+.2f} [{a['net_lo']:+.2f}, {a['net_hi']:+.2f}]**, MDE {a['net_mde']:.1f}; **hedged net {a['hedged_net']:+.2f} [{a['hedged_net_lo']:+.2f}, {a['hedged_net_hi']:+.2f}]**; "
           f"**flip null** ({f['draws']} draws) mean {f['null_mean']:+.2f}, sd {f['null_sd']:.2f}, p95 {f['null_p95']:+.2f} → **p {f['p']:.4f}**; shuffle {v['shuffle']['note']}.\n",
           f"\nPer fold: " + "; ".join(f"{k} {x['trades']} trades net {x['net']:+.2f} [{x['net_lo']:+.2f}, {x['net_hi']:+.2f}], hedged net {x['hedged_net']:+.2f}" for k, x in v["per_fold"].items()) + "\n",
           f"\nSides: " + "; ".join(f"{k} {x['trades']:.0f} trades gross {x['gross']:+.2f}, hedged {x['hedged']:+.2f}, net {x['net']:+.2f} [{x['net_lo']:+.2f}, {x['net_hi']:+.2f}], hedged net {x['hedged_net']:+.2f}" for k, x in v["sides"].items()) + "\n",
           f"\n**The clipped row** (every trade's gross at ±{CLIP:.0f} bps, costs and funding unchanged; {c['share_clipped']:.1%} of the trades clipped): net {c['mean']:+.2f} [{c['lo']:+.2f}, {c['hi']:+.2f}].\n",
           "\n## The gate\n", "\n" + "\n".join(f"- {k}: **{'PASS' if x else 'FAIL'}**" for k, x in v["gate"].items()) + f"\n\n**VERDICT: {v['verdict']}**\n"]
    if d:
        a2, c2, f2 = d["all"], d["clipped"], d["flip"]
        out += [f"\n## Described — the 14-day hold (`{d['run']}`, no gate; validity {d['validity_status']})\n",
                f"\n{a2['trades']:.0f} trades, net {a2['net']:+.2f} [{a2['net_lo']:+.2f}, {a2['net_hi']:+.2f}], hedged net {a2['hedged_net']:+.2f}, flip p {f2['p']:.4f}; per fold "
                + "; ".join(f"{k} {x['net']:+.2f}" for k, x in d["per_fold"].items()) + f"; clipped {c2['mean']:+.2f} [{c2['lo']:+.2f}, {c2['hi']:+.2f}].\n"]
    return "\n".join(out)


if __name__ == "__main__":
    runs = sys.argv[1:]
    v, M = read(runs[0])
    d = read(runs[1], M)[0] if len(runs) > 1 else None
    tag = "" if not v["registration"] else "_f34"
    (bt.OUT / f"r44_read{tag}.json").write_text(json.dumps({"gated": v, "described": d}, indent=1, default=str))
    text = md(v, d)
    (bt.OUT / f"r44_read{tag}.md").write_text(text)
    print(text)
