"""R21, described only, computed after the read: did the book trade what R20 measured?
(1) the three features and the book's score by R20's statistic (`ceiling._ic_xs`) on the book's own cells;
(2) the move that followed, by the score's decile within the bar — mean and median, in bps against the cells' mean;
(3) the same for the trades the book took; (4) which names carry the net.
Run on the work VM:  ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/r21_describe_score.py' (after `vm.sh push`).
"""
import json

import numpy as np
import pandas as pd

from ft2 import audit, folds, universe
from ft2 import backtest as bt
from ft2.ceiling import Z_CLIP, _ic_xs, day_lags, hac
from ft2.forecast import _derive

pd.set_option("display.width", 220)
run = bt.OUT / "r21_oibook_1d"
meta = json.loads((run / "meta.json").read_text())
fold_names, hold, latency = meta["folds"], 288, int(meta["latency_bars"])
end = folds.bounds(fold_names[-1])[1]
M = bt.market(meta["pairs"], end, needs=("oi",))
book = audit.OIBook(hold=hold, k=6)
a0 = folds.bounds(fold_names[0])[0]
s = book.score(M, a0, end)
t = pd.Series(s.index, index=s.index)
scored = np.zeros(len(s), dtype=bool)
for f in fold_names:
    scored |= folds.mask(t, f).to_numpy()
s = s[scored]
grid, cols = s.index, list(s.columns)
y = bt.labels(M, hold, latency).loc[grid, cols]
sig = _derive(M.close)["sig"]["1w"].loc[grid, cols] * np.sqrt(hold)
z = (y / sig.where(sig > 0)).clip(-Z_CLIP, Z_CLIP)
cell = s.notna() & z.notna()
day = (grid.floor("D") - grid[0].floor("D")).days.to_numpy()
lags = day_lags(hold)
print(f"cells {int(cell.to_numpy().sum()):,} on {len(grid):,} bars, names per bar median {int(cell.sum(axis=1).median())}")


def ic(x: pd.DataFrame, name: str) -> None:
    m, se, n = hac(_ic_xs(x.where(cell), z.where(cell), day), lags)
    print(f"  {name:12s} IC {m:+.4f}  se {se:.4f}  t {m / se:+.2f}  days {n}")


print("R20's statistic on the book's cells:")
X = M.extra["oi"]
for k in audit.OI:
    ic(X[k].reindex(index=grid, columns=cols), k)
ic(s, "score")

rel = y.where(cell)
rel = rel.sub(rel.mean(axis=1), axis=0)                       # the move against the cells' mean at the bar, bps
zr = z.where(cell)
zr = zr.sub(zr.mean(axis=1), axis=0)
r = s.where(cell).rank(axis=1, pct=True)
dec = np.ceil(r * 10).clip(1, 10)
L = pd.DataFrame({"dec": dec.stack(), "rel": rel.stack(), "z": zr.stack(), "sig": sig.where(cell).stack()}).dropna()
print("\nthe move over the next day against the other cells, by the score's decile within the bar (10 = what the book buys):")
print(L.groupby("dec").agg(cells=("rel", "size"), mean_bps=("rel", "mean"), median_bps=("rel", "median"), mean_z=("z", "mean"), median_z=("z", "median"),
                           sigma_1d=("sig", "median")).round(3).to_string())
top, bot = L[L["dec"] == 10]["rel"], L[L["dec"] == 1]["rel"]
print(f"\ntop tenth minus bottom tenth, per leg: mean {(top.mean() - bot.mean()) / 2:+.2f} bps, median {(top.median() - bot.median()) / 2:+.2f} bps")

f = pd.read_parquet(run / "fills_taker.parquet").dropna(subset=["net_bps"])
print(f"\nthe trades taken: {len(f):,}; gross {f['gross_bps'].mean():+.2f}, hedged {f['hedged_bps'].mean():+.2f}; "
      f"median gross {f['gross_bps'].median():+.2f}, median hedged {f['hedged_bps'].median():+.2f}; hit {np.mean(f['gross_bps'] > 0):.3f}, hedged hit {np.mean(f['hedged_bps'] > 0):.3f}")
hrs = pd.DatetimeIndex(f["t"]).hour
print("entries by hour of day (UTC):", pd.Series(hrs).value_counts().sort_index().to_dict())
by = f.groupby("symbol")["net_bps"].agg(["size", "sum", "mean"]).sort_values("sum")
print(f"\nnet summed over trades: {f['net_bps'].sum():+,.0f} bps on {by.shape[0]} names; names with a positive sum: {(by['sum'] > 0).sum()}")
print("five worst:\n", by.head(5).round(1).to_string())
print("five best:\n", by.tail(5).round(1).to_string())
g = f.groupby("symbol")["hedged_bps"].agg(["size", "sum"]).sort_values("sum")
print(f"\nhedged gross summed: {f['hedged_bps'].sum():+,.0f}; five best names {g['sum'].tail(5).sum():+,.0f}, five worst {g['sum'].head(5).sum():+,.0f}")
