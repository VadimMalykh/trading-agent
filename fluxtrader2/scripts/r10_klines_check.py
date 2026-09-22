"""R10: per-pair extent and gaps of the archive 5m klines for the wider universe → output/r10_klines_check.md (run on the VM)."""
import pandas as pd
from ft2 import data
from ft2.universe import NEW

c = data.load("candles_5m_archive", columns=["symbol", "open_time", "close"])
c = c[c["symbol"].astype(str).isin(NEW)]
rows = []
for sym, g in c.groupby(c["symbol"].astype(str)):
    t = g["open_time"].sort_values()
    gaps = t.diff().dropna()
    big = gaps[gaps > pd.Timedelta("10min")]
    rows.append({"symbol": sym, "rows": len(g), "first": t.iloc[0].date(), "last": t.iloc[-1].date(), "gaps_gt_10min": len(big),
                 "largest_gap": str(big.max()) if len(big) else "", "in_F1F2": int(((t >= "2023-05-01") & (t < "2024-09-01")).sum())})
r = pd.DataFrame(rows).sort_values("symbol")
txt = "# R10 — archive 5m klines of the 32 new pairs (`scripts/r10_klines_check.py`)\n\n" + r.to_markdown(index=False) + "\n"
open("output/r10_klines_check.md", "w").write(txt)
print(txt)
