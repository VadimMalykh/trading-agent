"""R28, described — decides nothing. The gate's se (a 6-week moving-block bootstrap over weeks) came out SMALLER than the plain
and the week-clustered se at 1, 3 and 7 days. Is that the instrument or the sample? The same launches and weeks with the labels
dealt again at random among the launches (which breaks any tie between a label and its week): the bootstrap's se on each deal,
against the se on the real order. And the cost proxy's coverage of a contract's first days. Reads output/listing/r28/launches.csv
only. On the work VM: PYTHONPATH=. python scripts/r28_describe_se.py → output/listing/r28/described_se.md"""
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import listing

out = Path("output/listing/r28")
E = pd.read_csv(out / "launches.csv")
t = pd.DatetimeIndex(pd.to_datetime(E["t"], utc=True))
cols = [f"y_{h // 288}d" for h in listing.HOLDS]
Y = E[cols].to_numpy()
wk, W = listing.weeks(t)
real = listing.bootstrap(Y, wk, W)
rng = np.random.default_rng(2801)
deals = np.array([listing.bootstrap(Y[rng.permutation(len(Y))], wk, W, draws=2000, seed=int(s))["se"] for s in rng.integers(0, 1 << 30, 300)])
rows = []
for k, c in enumerate(cols):
    one = listing.bootstrap(Y, wk, W, block=1)
    rows.append({"hold": c[2:], "M": real["m"][k], "se_gate": real["se"][k], "se_plain": real["se_plain"][k], "se_week": real["se_week"][k], "se_blocks_of_1_week": one["se"][k],
                 "dealt: mean se": deals[:, k].mean(), "dealt: sd of se": deals[:, k].std(ddof=1), "share of deals with an se at or under the gate's": float((deals[:, k] <= real["se"][k]).mean()),
                 "u_gate": real["u"][k], "u by se_week": real["m"][k] / real["se_week"][k], "u by se_plain": real["m"][k] / real["se_plain"][k], "u by the deals' mean se": real["m"][k] / deals[:, k].mean()})
tab = pd.DataFrame(rows)
md = ["# R28 described: the gate's se against the same launches with the labels dealt again (decides nothing)\n",
      f"\n{len(E)} launches in {W} weeks; 300 deals, 2,000 draws each; the gate's own numbers are the run's (10,000 draws, seed {listing.SEED}).\n", tab.round(3).to_markdown(index=False), "\n"]
(out / "described_se.md").write_text("\n".join(md))
print("\n".join(md))
