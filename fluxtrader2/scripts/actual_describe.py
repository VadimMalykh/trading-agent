"""Described beside a re-execution `actual` of an `oibook` read (PLAN §3); decides nothing. On the taker fills of the named
runs, each apart and pooled, three rows:
  as counted    the corrected harness: gross = side × (exit / entry − 1); fees, spread and impact in bps of the size at
                entry on both legs; funding = the signed sum of the rates.
  capped        the same with every short closed at the loss of its whole size at most — a different rule (a stop), shown
                because R25's first read showed it.
  in full       what the harness still rounds: the exit leg's fee, spread and impact are paid on the position's value at
                the exit (× exit / entry), and each funding payment on its value at that moment (× the close at the
                funding time / entry). Both are nothing on small moves.
The flip null is drawn again on each row (`backtest.flip_days`' rule: every decision of a day × one random sign).
Run where the data is (the work VM): python scripts/actual_describe.py <output name> <run> [<run> …]
→ output/backtest/<output name>/described.md, described.csv"""
import json
import sys

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import ceiling, data, folds

DRAWS, CAP = 200, -1e4


def load(run: str) -> tuple[pd.DataFrame, pd.DatetimeIndex, int]:
    rd = bt.OUT / run
    meta = json.loads((rd / "meta.json").read_text())
    assert meta.get("unit") == "actual", f"{run} was counted in logs: re-execute it first"
    fo = meta["folds"]
    end = folds.bounds(fo[-1])[1]
    f = pd.read_parquet(rd / "fills_taker.parquet").dropna(subset=["net_bps"]).copy()
    s, r = f["side"].to_numpy(float), (f["exit_px"] / f["entry_px"]).to_numpy()
    assert np.allclose(s * (r - 1) * 1e4, f["gross_bps"], rtol=0, atol=1e-6)
    f["capped"] = np.where(s < 0, np.maximum(f["gross_bps"], CAP), f["gross_bps"])
    f["cost"] = f["fee_bps"] + f["other_cost_bps"]

    M = bt.market(meta["pairs"], end, bt.PRE_START if "FP" in fo else ceiling.START)
    C = bt.load_costs(M.index, M.columns, end, meta["cost_mult"])
    j, d = M.columns.get_indexer(f["symbol"]), C.days.get_indexer(pd.DatetimeIndex(f["exit_t"]).floor("D"))
    f["cost_full"] = f["cost"] + (meta["taker_bps"] + C.taker_leg[d, j]) * (r - 1)          # the exit leg, on the exit's size

    ev = data.load("funding_archive", columns=["symbol", "ts", "rate"], symbols=sorted(f["symbol"].unique()))
    ev = ev[ev["ts"] < end].assign(symbol=lambda x: x["symbol"].astype(str))
    full, plain = np.zeros(len(f)), np.zeros(len(f))
    for sym, g in f.groupby("symbol"):
        e = ev[ev["symbol"] == sym].sort_values("ts")
        ts, rate = bt._ns(e["ts"]), e["rate"].to_numpy() * 1e4
        at = M.close[sym].ffill().to_numpy()[np.clip(np.searchsorted(bt._ns(M.index), ts, "right") - 1, 0, None)]      # the close at or before the funding time
        c0, c1 = (np.concatenate([[0.0], np.cumsum(x)]) for x in (rate, np.nan_to_num(rate * at)))
        a, b = np.searchsorted(ts, bt._ns(g["entry_t"]), "right"), np.searchsorted(ts, bt._ns(g["exit_t"]), "right")
        k = f.index.get_indexer(g.index)
        sd, pe = g["side"].to_numpy(float), g["entry_px"].to_numpy()
        plain[k], full[k] = -sd * (c0[b] - c0[a]), -sd * (c1[b] - c1[a]) / pe
    assert np.allclose(plain, f["funding_bps"], rtol=0, atol=1e-6), "the funding rebuilt here is not the harness's"
    f["funding_full"], f["run"] = full, run
    return f, bt.scored_days(fo, folds.bounds(fo[-1])[1] - bt.BAR), int(meta["params"]["hold"])


def read(f: pd.DataFrame, days: pd.DatetimeIndex, hold: int, gross: str, fund: str, cost: str, seed: int = 0) -> dict:
    day, w, lags = pd.DatetimeIndex(f["t"]).floor("D"), f["size"].to_numpy(), bt.day_lags(hold)
    g, fu, c = f[gross].to_numpy(), f[fund].to_numpy(), f[cost].to_numpy()
    net = bt.trade_stats(g + fu - c, w, day, days, lags)
    ud, pos = np.unique(day, return_inverse=True)
    null = np.array([np.average(np.random.default_rng([seed, d, 1]).choice([-1, 1], len(ud))[pos] * (g + fu) - c, weights=w) for d in range(1, DRAWS + 1)])
    sides = {f"net_{k}": float(np.average((g + fu - c)[f["side"].to_numpy() == v], weights=w[f["side"].to_numpy() == v])) for k, v in bt.SIDES.items()}
    return {"trades": len(f), "gross": float(np.average(g, weights=w)), "cost": float(np.average(c, weights=w)), "funding": float(np.average(fu, weights=w)),
            "net": net["mean"], "net_lo": net["lo"], "net_hi": net["hi"], "net_se": net["se"], **sides, "flip_mean": float(null.mean()), "flip_sd": float(null.std()),
            "flip_p": (1 + int((null >= net["mean"]).sum())) / (DRAWS + 1)}


if __name__ == "__main__":
    name, runs = sys.argv[1], sys.argv[2:]
    parts = {k: load(k) for k in runs}
    hold = {h for _, _, h in parts.values()}.pop()
    samples = dict(parts)
    if len(parts) > 1:
        days = [d for _, d, _ in parts.values()]
        samples["pooled"] = (pd.concat([f for f, _, _ in parts.values()], ignore_index=True), days[0].append(days[1:]).unique().sort_values(), hold)
    rows = []
    for what, (g, fu, c) in {"as counted": ("gross_bps", "funding_bps", "cost"), "capped: a short's loss at most its size": ("capped", "funding_bps", "cost"),
                             "in full: exit costs and funding on the position's value": ("gross_bps", "funding_full", "cost_full")}.items():
        rows += [{"counted": what, "sample": k, **read(f, days, hold, g, fu, c)} for k, (f, days, _) in samples.items()]
    tab = pd.DataFrame(rows)
    big = pd.concat([f for f, _, _ in parts.values()], ignore_index=True)
    big["net_bps_full"] = big["gross_bps"] + big["funding_full"] - big["cost_full"]
    big["d_full"] = big["net_bps_full"] - big["net_bps"]
    ex = big.assign(move_pct=(big["exit_px"] / big["entry_px"] - 1) * 100, day=pd.DatetimeIndex(big["t"]).date)
    cols = ["run", "day", "symbol", "side", "entry_px", "exit_px", "move_pct", "gross_bps", "funding_bps", "funding_full", "cost", "cost_full", "net_bps", "net_bps_full"]
    md = [f"# Beside the re-execution: {', '.join(f'`{r}`' for r in runs)} (described, decides nothing; `scripts/actual_describe.py`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · the taker fills, {len(big):,} priced trades · flip null drawn again on each row, {DRAWS} draws\n",
          "\nWords: *as counted* — the corrected harness: a trade earns side × (exit / entry − 1); costs and funding in bps of the size at entry. *capped* — every short closed "
          "with the loss of its whole size at most: a different rule. *in full* — the exit leg's fee, spread and impact paid on the position's value at the exit, and each "
          "funding payment on its value at that moment: what the harness rounds away. bps per trade: 1 bps is 1 USDT on 10,000.\n",
          "\n## The books\n", tab.round(2).to_markdown(index=False), "\n",
          f"\n## What the rounding is worth\n\nPer trade, *in full* minus *as counted*: mean {big['d_full'].mean():+.2f} bps (longs {big.loc[big['side'] > 0, 'd_full'].mean():+.2f}, shorts "
          f"{big.loc[big['side'] < 0, 'd_full'].mean():+.2f}); of it the exit costs {-(big['cost_full'] - big['cost']).mean():+.2f}, the funding {(big['funding_full'] - big['funding_bps']).mean():+.2f}. "
          f"The ten trades it moves most carry {big['d_full'].abs().nlargest(10).sum() / max(big['d_full'].abs().sum(), 1e-12):.0%} of the absolute difference.\n",
          "\n## The ten trades the rounding moves most\n", ex.reindex(ex["d_full"].abs().nlargest(10).index)[cols].round(4).to_markdown(index=False), "\n",
          "\n## The ten trades with the largest loss\n", ex.sort_values("net_bps").head(10)[cols].round(4).to_markdown(index=False), "\n"]
    out = bt.OUT / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "described.md").write_text("\n".join(md))
    tab.to_csv(out / "described.csv", index=False)
    print("\n".join(md))
