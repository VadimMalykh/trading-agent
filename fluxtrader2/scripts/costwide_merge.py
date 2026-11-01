"""Merge a `costwide --symbols …` run (NEW, the event names only — `costwide` writes its parquet whole) into the parquet it replaced (OLD):
every old (symbol, day) row kept, the new rows added, and where both hold a row the two must agree to 1e-9 on the spread and the impacts
(the pooled fit is the twelve's tape days, unchanged by a wider slice) — else VOID. Usage: costwide_merge.py OLD NEW OUT."""
import sys
import numpy as np
import pandas as pd

old, new = (pd.read_parquet(p) for p in sys.argv[1:3])
for d in (old, new):
    d["symbol"] = d["symbol"].astype(str)
cols = [c for c in old.columns if c.startswith(("spread_cal", "imp_")) and c in new.columns]
both = old.merge(new, on=["symbol", "day"], how="inner", suffixes=("_o", "_n"))
worst = max((float(np.nanmax(np.abs(both[f"{c}_o"] - both[f"{c}_n"]))) if len(both) else 0.0) for c in cols)
if not worst < 1e-9:
    sys.exit(f"costwide_merge: {len(both):,} overlapping rows differ by up to {worst:.3e} — VOID")
out = pd.concat([old.merge(new[["symbol", "day"]], on=["symbol", "day"], how="left", indicator=True).query("_merge == 'left_only'").drop(columns="_merge"), new], ignore_index=True)
out = out.sort_values(["symbol", "day"]).reset_index(drop=True)
assert len(out) == len(old) + len(new) - len(both)
out.to_parquet(sys.argv[3], index=False)
print(f"old rows {len(old):,} ({old['symbol'].nunique()} names) + new rows {len(new):,} ({new['symbol'].nunique()} names), overlap {len(both):,} identical to {worst:.1e} → "
      f"{len(out):,} rows ({out['symbol'].nunique()} names) at {sys.argv[3]}; costwide_merge: PASS")
