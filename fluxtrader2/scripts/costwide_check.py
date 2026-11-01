"""After a `costwide --universe all` re-run: every (symbol, day) row the old parquet held comes back with the same spread and impact
(the pooled fit is the twelve's tape days, unchanged by a wider slice), else the re-run is void. Usage: costwide_check.py OLD NEW."""
import sys
import numpy as np
import pandas as pd

old, new = (pd.read_parquet(p) for p in sys.argv[1:3])
for d in (old, new):
    d["symbol"] = d["symbol"].astype(str)
cols = [c for c in old.columns if c.startswith(("spread_cal", "imp_")) and c in new.columns]
m = old.merge(new, on=["symbol", "day"], how="left", suffixes=("_o", "_n"))
missing = int(m[f"{cols[0]}_n"].isna().sum())
worst = max(float(np.nanmax(np.abs(m[f"{c}_o"] - m[f"{c}_n"]))) for c in cols)
print(f"old rows {len(old):,} new rows {len(new):,} names {old['symbol'].nunique()} → {new['symbol'].nunique()}; old rows missing in new {missing}; worst |diff| over {cols} {worst:.3e}")
if missing or not worst < 1e-9:
    sys.exit("costwide_check: the old rows did not come back — VOID")
print("costwide_check: PASS")
