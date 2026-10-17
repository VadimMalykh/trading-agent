"""R42's pooled row (PLAN §8 R42): the SAVED decisions of several `backtest` runs of one strategy, re-priced by `backtest.price`
on ONE market under today's unit, summarised together, with the flip null on the union. `ft2 pool <run> <run> … --draws 2000`
→ output/backtest/<name>/pool.md

A re-pricing of saved trades, as §3's actual-vs-log table was: no walk, no fit, no fold read again — the guard is not involved.
Each run is first re-priced alone and its summary set beside the run's own results.parquet row (validity: the re-pricing is the
harness's own; a run priced in an older unit differs by the unit, and the difference is written down). Then the union: the
pooled summary over the union's scored days (`backtest.summarize`), and the flip null — `backtest.flip_days` on the union (every
decision of a UTC day × one random sign), re-priced on the real path, `draws` times, seed fixed — its sd, p95 and the one-sided p.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import ceiling, folds

COLS = ["trades", "net", "net_lo", "net_hi", "net_mde", "hedged_net", "hedged_net_lo", "hedged_net_hi", "gross", "fee", "other_cost", "funding"]


def _summ(f: pd.DataFrame, days: pd.DatetimeIndex, hold: int) -> dict:
    s = bt.summarize(f, days, hold)
    return {k: s[k] for k in COLS}


def pool(runs: list[str], exec_: str = "taker", draws: int = 2000, seed: int = 0, name: str = "pool", split: str | None = None,
         taker_bps: float = 5.0, maker_bps: float = 2.0, cost_mult: float = 1.0) -> str:
    metas = {r: json.loads((bt.OUT / r / "meta.json").read_text()) for r in runs}
    holds = {int(m["params"]["hold"]) for m in metas.values()}
    if len(holds) != 1:
        raise SystemExit(f"pool: one hold, not {sorted(holds)}")
    if len({m["strategy"] for m in metas.values()}) != 1:
        raise SystemExit("pool: one strategy")
    hold = holds.pop()
    pairs = list(dict.fromkeys(p for m in metas.values() for p in m["pairs"]))
    fold_names = folds.order({f for m in metas.values() for f in m["folds"]})
    end = folds.bounds(fold_names[-1])[1]
    M = bt.market(pairs, end, bt.PRE_START if "FP" in fold_names else ceiling.START)
    C = bt.load_costs(M.index, M.columns, end, cost_mult, M.close)
    last = M.index[-1]
    dec = {r: pd.read_parquet(bt.OUT / r / "decisions.parquet") for r in runs}
    rows, halves = [], []
    for r, d in dec.items():
        f = bt.price(d, M, C, exec_, taker_bps, maker_bps)
        days = bt.scored_days(metas[r]["folds"], last)
        res = pd.read_parquet(bt.OUT / r / "results.parquet")
        own = res[(res["exec"] == exec_) & (res["scope"] == "all")].iloc[0]
        s = _summ(f, days, hold)
        rows.append({"run": r, "folds": "+".join(metas[r]["folds"]), **s, "run_trades": int(own["trades"]), "run_net": float(own["net"]), "run_net_lo": float(own["net_lo"]),
                     "run_net_hi": float(own["net_hi"]), "run_unit": metas[r].get("unit", "log"), "run_charged": metas[r].get("charged", "size"),
                     "d_net_vs_run": s["net"] - float(own["net"]), "d_trades_vs_run": s["trades"] - int(own["trades"])})
        if split:
            cut = pd.Timestamp(split, tz="UTC")
            t = pd.DatetimeIndex(f["t"])
            for lab, fm, dm in (("before", t < cut, days < cut), ("from", t >= cut, days >= cut)):
                halves.append({"run": r, "half": f"{lab} {cut:%Y-%m-%d}", **_summ(f[fm], days[dm], hold)})
    runs_tab = pd.DataFrame(rows)

    union = pd.concat(dec.values(), ignore_index=True)
    fu = bt.price(union, M, C, exec_, taker_bps, maker_bps)
    days = bt.scored_days(fold_names, last)
    pooled = {"scope": "all", **_summ(fu, days, hold)}
    per_fold = [{"scope": fo, **_summ(fu[fu["fold"] == fo], bt.scored_days([fo], last), hold)} for fo in fold_names]
    print(f"pool: {len(runs)} runs, {pooled['trades']:,} trades over {'+'.join(fold_names)}; the flip null, {draws} draws…", flush=True)
    nets, hnets = [], []
    w_all = None
    for draw in range(1, draws + 1):
        fl = bt.flip_days(union, np.random.default_rng([seed, draw, 1]))
        f = bt.price(fl, M, C, exec_, taker_bps, maker_bps).dropna(subset=["net_bps"])
        w_all = f["size"].to_numpy()
        nets.append(float(np.average(f["net_bps"], weights=w_all)))
        hnets.append(float(np.average(f["hedged_net_bps"], weights=w_all)))
        if draw % 200 == 0:
            print(f"flip null: {draw}/{draws}", flush=True)
    nets, hnets = np.asarray(nets), np.asarray(hnets)
    real_w = fu.dropna(subset=["net_bps"])
    real_net = float(np.average(real_w["net_bps"], weights=real_w["size"]))          # the size-weighted mean, the null's own statistic (= summarize's ratio estimator)
    real_h = float(np.average(real_w["hedged_net_bps"], weights=real_w["size"]))
    flip = {"draws": int(draws), "seed": seed, "null_mean": float(nets.mean()), "null_sd": float(nets.std()), "null_p95": float(np.quantile(nets, 0.95)),
            "p": (1 + int((nets >= real_net).sum())) / (draws + 1), "hedged_null_sd": float(hnets.std()), "hedged_p": (1 + int((hnets >= real_h).sum())) / (draws + 1),
            "real_net": real_net, "real_hedged_net": real_h}

    out = bt.OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fu.to_parquet(out / "pooled_fills.parquet", index=False)
    pd.DataFrame({"draw": np.arange(1, draws + 1), "net": nets, "hedged_net": hnets}).to_parquet(out / "flip_null.parquet", index=False)
    runs_tab.to_csv(out / "runs.csv", index=False)
    summary = {"runs": runs, "exec": exec_, "hold": hold, "folds": fold_names, "pairs": pairs, "unit": bt.UNIT, "charged": bt.CHARGED, "taker_bps": taker_bps, "maker_bps": maker_bps,
               "pooled": pooled, "per_fold": per_fold, "flip": flip, "runs_table": rows, "halves": halves, "generated": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC"}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    show = lambda df, k=2: pd.DataFrame(df).round(k).to_markdown(index=False)          # noqa: E731
    md = [f"# Pooled row — {', '.join(runs)} re-priced on one market ({exec_}, hold {hold}) (`ft2 pool`)\n",
          f"generated {summary['generated']} · folds {'+'.join(fold_names)} · {len(pairs)} pairs · unit {bt.UNIT}, charged {bt.CHARGED} · flip null {draws} draws, seed {seed}\n",
          "\nWords: each run's saved decisions are priced again by the harness on one market under today's unit — *net* etc. are that re-pricing; *run_net* is what the run's own "
          "report said (an older unit differs by the unit, `d_net_vs_run`). *pooled*: the union's trades over the union's scored days. *flip*: the union's decisions with every UTC "
          "day's sides × one random sign, re-priced on the real path; *p* is the share of draws at or above the real size-weighted net.\n",
          "\n## Each run alone (validity: the re-pricing against the run's own row)\n", show(runs_tab, 3), "\n",
          *(["\n## Halves\n", show(halves, 2), "\n"] if halves else []),
          "\n## Pooled\n", show([pooled, *per_fold], 2), "\n",
          f"\n## The flip null on the union\n\nreal net {real_net:+.2f} (hedged {real_h:+.2f}); null mean {flip['null_mean']:+.2f}, sd {flip['null_sd']:.2f}, p95 {flip['null_p95']:+.2f}; "
          f"**flip p {flip['p']:.4f}** (hedged p {flip['hedged_p']:.4f}, hedged null sd {flip['hedged_null_sd']:.2f}).\n"]
    (out / "pool.md").write_text("\n".join(md))
    print(f"wrote {out}/", flush=True)
    return "\n".join(md)
