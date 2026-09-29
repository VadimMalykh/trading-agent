"""Described after R25's read (decides nothing by itself): the harness measures a trade's gross as side × log(exit / entry).
A position of fixed size earns side × (exit / entry − 1). On small moves the two agree; on the moves of these names over 7
days they do not: the log overstates every short and understates every long by about half the squared move, and the book's
shorts are its most violent names. This re-prices the saved fills of R24's and R25's runs with the actual return — the
decisions, the prices, the costs and the funding are the runs' own — and draws the flip null again on it.
Run anywhere the runs' output is (locally: ./scripts/ft2.sh is `python -m ft2`; use
  docker run --rm -v "$PWD:/workspace/ft2" -w /workspace/ft2 fluxtrader2-analysis:latest python scripts/r25_describe_simple.py)
→ output/backtest/r25_read/simple.md, simple.csv"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import folds

RUNS = {"r24_oibook_7d_pre": "R24 PRE (2021-12 → 2023-04)", "r24_oibook_7d_f12": "R24 F12 (F1+F2)", "r25_oibook_7d_f34": "R25 (F3+F4)"}
DRAWS, CAP = 200, -1e4          # CAP: a short closed by the exchange when it has lost its whole size (described)


def load(run: str) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    f = pd.read_parquet(bt.OUT / run / "fills_taker.parquet").dropna(subset=["net_bps"]).copy()
    fo = json.loads((bt.OUT / run / "meta.json").read_text())["folds"]
    s, r = f["side"].to_numpy(float), (f["exit_px"] / f["entry_px"]).to_numpy()
    assert np.allclose(s * np.log(r) * 1e4, f["gross_bps"])
    f["simple"] = s * (r - 1) * 1e4
    f["capped"] = np.where(s < 0, np.maximum(f["simple"], CAP), f["simple"])
    f["cost"] = f["fee_bps"] + f["other_cost_bps"]
    f["run"] = run
    return f, bt.scored_days(fo, folds.bounds(fo[-1])[1] - bt.BAR)


def read(f: pd.DataFrame, days: pd.DatetimeIndex, col: str, seed: int = 0) -> dict:
    day, w, lags = pd.DatetimeIndex(f["t"]).floor("D"), f["size"].to_numpy(), bt.day_lags(int(2016))
    g, fund, cost = f[col].to_numpy(), f["funding_bps"].to_numpy(), f["cost"].to_numpy()
    net = bt.trade_stats(g + fund - cost, w, day, days, lags)
    ud, pos = np.unique(day, return_inverse=True)
    null = np.array([np.average(np.random.default_rng([seed, d, 1]).choice([-1, 1], len(ud))[pos] * (g + fund) - cost, weights=w) for d in range(1, DRAWS + 1)])
    return {"trades": len(f), "gross": float(np.average(g, weights=w)), "cost": float(np.average(cost, weights=w)), "funding": float(np.average(fund, weights=w)),
            "net": net["mean"], "net_lo": net["lo"], "net_hi": net["hi"], "net_se": net["se"], "flip_mean": float(null.mean()), "flip_sd": float(null.std()),
            "flip_p": (1 + int((null >= net["mean"]).sum())) / (DRAWS + 1)}


parts = {k: load(k) for k in RUNS if (bt.OUT / k / "fills_taker.parquet").exists()}
rows = []
for col, what in (("gross_bps", "log (the harness)"), ("simple", "actual return"), ("capped", "actual return, a short's loss capped at its size")):
    for k, (f, days) in parts.items():
        rows.append({"measured as": what, "sample": RUNS[k], **read(f, days, col)})
        for s, nm in ((1, "long"), (-1, "short")):
            q = f[f["side"] == s]
            rows.append({"measured as": what, "sample": RUNS[k] + " — " + nm, "trades": len(q), "gross": float(q[col].mean()), "cost": float(q["cost"].mean()), "funding": float(q["funding_bps"].mean()),
                         "net": float((q[col] + q["funding_bps"] - q["cost"]).mean())})
    r24 = [k for k in parts if k.startswith("r24")]
    if len(r24) == 2:
        f = pd.concat([parts[k][0] for k in r24], ignore_index=True)
        days = parts[r24[0]][1].append(parts[r24[1]][1]).unique().sort_values()
        rows.append({"measured as": what, "sample": "R24 pooled", **read(f, days, col)})
tab = pd.DataFrame(rows)
big = pd.concat([f for f, _ in parts.values()], ignore_index=True)
mv = np.abs(np.log(big["exit_px"] / big["entry_px"])) * 100
ex = big.assign(move_pct=(big["exit_px"] / big["entry_px"] - 1) * 100, day=pd.DatetimeIndex(big["t"]).date).sort_values("simple")
md = ["# R24 and R25 re-priced with the actual return of a position (described; `scripts/r25_describe_simple.py`)\n",
      f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · the saved taker fills of {', '.join(parts)} · flip null drawn again, {DRAWS} draws\n",
      "\nWords: *log* — the harness's gross, side × log(exit / entry). *actual return* — what a position of fixed size earns, side × (exit / entry − 1). A name that falls "
      "from 4.9 to 1.0 is −159 % in logs and −80 % in fact: a short of 10,000 USDT made 7,960, not 15,900. A name that rises from 1.1 to 18.0 is +277 % in logs and "
      "+1,536 % in fact: a short of 10,000 lost 153,600 unless the exchange closed it first. *capped*: every short closed with the loss of its whole size at most.\n",
      "\n## The books\n", tab.round(2).to_markdown(index=False), "\n",
      f"\n## How large the moves are\n\nOver the 7 days of a trade the price moved by {mv.median():.1f} % in the median, more than 25 % in {float((mv > 25).mean()):.1%} of the trades, more than "
      f"50 % in {float((mv > 50).mean()):.1%}, more than 100 % (in logs) in {float((mv > 100).mean()):.2%}.\n",
      "\n## The ten trades with the largest loss in fact\n", ex.head(10)[["run", "day", "symbol", "side", "entry_px", "exit_px", "move_pct", "gross_bps", "simple"]].round(4).to_markdown(index=False), "\n"]
out = bt.OUT / "r25_read"
out.mkdir(parents=True, exist_ok=True)
(out / "simple.md").write_text("\n".join(md))
tab.to_csv(out / "simple.csv", index=False)
print("\n".join(md))
