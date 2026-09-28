"""R20, described only: why the reference row (R18's forecast) reads -0.032 by the audit's statistic and +0.0002 by R18's.
The same cells, the same forecast, four ways of correlating — a check of the instruments against each other, no new feature.
Run on the work VM:  ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/r20_describe_reference.py' (after `vm.sh push`).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import folds, screen, universe
from ft2.ceiling import day_lags, hac

run_dir = bt.OUT / "r18_transferbook_1d"
meta = json.loads((run_dir / "meta.json").read_text())
p, fold_names = meta["params"], meta["folds"]
hold, latency = int(p["hold"]), int(meta["latency_bars"])
mem = universe.members(p.get("members") or None)
M = bt.market(meta["pairs"], folds.bounds(fold_names[-1])[1])
o = screen.cells(run_dir, M, hold, latency, fold_names, mem)
print("cells", len(o), "columns", list(o.columns))
o = o.assign(day=pd.DatetimeIndex(o["t"]).floor("D"))
g = o.groupby("t")
o["z_dm"], o["zh_dm"] = o["z"] - g["z"].transform("mean"), o["zhat"] - g["zhat"].transform("mean")
o["z_rk"], o["zh_rk"] = g["z"].rank(pct=True) - 0.5, g["zhat"].rank(pct=True) - 0.5
lags = day_lags(hold)


def daily(a: str, b: str, per_bar: bool) -> str:
    if per_bar:                                   # a correlation per bar, averaged per day, mean over days
        x = o.groupby("t").apply(lambda d: np.corrcoef(d[a], d[b])[0, 1] if len(d) >= 5 and d[a].std() > 0 and d[b].std() > 0 else np.nan, include_groups=False)
        s = x.groupby(pd.DatetimeIndex(x.index).floor("D")).mean()
    else:                                         # each day's share of the whole-sample correlation
        den = np.sqrt((o[a] ** 2).sum() * (o[b] ** 2).sum())
        s = (o[a] * o[b]).groupby(o["day"]).sum() / den * o["day"].nunique()
    m, se, n = hac(s.to_numpy(), lags)
    return f"{m:+.4f}  se {se:.4f}  t {m / se:+.2f}  days {n}"


print("pooled, Pearson, demeaned per bar      ", daily("z_dm", "zh_dm", False))
print("pooled, ranks per bar                  ", daily("z_rk", "zh_rk", False))
print("per bar Pearson, averaged              ", daily("z", "zhat", True))
print("per bar Spearman (ranks), averaged     ", daily("z_rk", "zh_rk", True))
n = g["z"].transform("size")
print("members per bar: min %d median %d max %d" % (n.min(), n.median(), n.max()))
# where the rank correlation lives: by the forecast's own decile within the bar
o["dec"] = np.ceil((o["zh_rk"] + 0.5) * 10).clip(1, 10).astype(int)
print(o.groupby("dec").agg(cells=("z", "size"), zhat=("zhat", "mean"), z_dm_mean=("z_dm", "mean"), z_dm_median=("z_dm", "median"), z_rank=("z_rk", "mean")).round(4).to_string())
