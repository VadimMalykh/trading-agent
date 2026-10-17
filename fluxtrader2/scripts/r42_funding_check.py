"""R42 validity (3): after the archive's fundingRate for 2026-09 is ingested, every funding row dated before 2026-09-01 is as it was
(the same count, the same rate at every (symbol, ts)), and the twelve each have ≥ 40 events in 2026-09-01 → 09-15.
Compares data/funding_archive_before_r42.parquet (the chain's copy) with data/funding_archive.parquet → output/logs/r42_funding_check.json; exit 1 on a failure."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ft2.__main__ import PAIRS

CUT, F5_END, MIN_EVENTS = pd.Timestamp("2026-09-01", tz="UTC"), pd.Timestamp("2026-09-15", tz="UTC"), 40
before = pd.read_parquet("data/funding_archive_before_r42.parquet")
after = pd.read_parquet("data/funding_archive.parquet")
for d in (before, after):
    d["symbol"] = d["symbol"].astype(str)
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
b, a = before[before["ts"] < CUT], after[after["ts"] < CUT]
m = b[["symbol", "ts", "rate"]].merge(a[["symbol", "ts", "rate"]], on=["symbol", "ts"], how="outer", suffixes=("_b", "_a"), indicator=True)
only = m[m["_merge"] != "both"]
both = m[m["_merge"] == "both"]
d_rate = float(np.nanmax(np.abs(both["rate_b"].to_numpy() - both["rate_a"].to_numpy()))) if len(both) else 0.0
sept = after[(after["ts"] >= CUT) & (after["ts"] < F5_END) & after["symbol"].isin(PAIRS)].groupby("symbol").size().reindex(PAIRS).fillna(0).astype(int)
out = {"rows_before_cut_before": int(len(b)), "rows_before_cut_after": int(len(a)), "rows_only_on_one_side": int(len(only)), "max_abs_d_rate": d_rate,
       "twelve_events_2026_09_01_to_15": sept.to_dict(), "last_ts_after": str(after["ts"].max()), "last_ts_before": str(before["ts"].max())}
out["status"] = "PASS" if len(b) == len(a) and len(only) == 0 and d_rate == 0.0 and (sept >= MIN_EVENTS).all() else "FAIL"
Path("output/logs").mkdir(parents=True, exist_ok=True)
Path("output/logs/r42_funding_check.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
sys.exit(0 if out["status"] == "PASS" else 1)
