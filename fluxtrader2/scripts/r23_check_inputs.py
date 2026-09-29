"""R23 input check: inputs only, no label and no statistic is touched.
(1) every row the three archive slices held before R23's ingest is in them after it, value for value (the copies
    data/*_before_r23.parquet were taken before the ingest); (2) which members have rows in each source on R23's days.
Run on the work VM:  ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/r23_check_inputs.py'
→ output/horizon/r23_inputs.json
"""
import json
from pathlib import Path

import pandas as pd

from ft2 import universe

out = {}
for tab, tcol in (("funding_archive", "ts"), ("metrics", "ts"), ("candles_5m_archive", "open_time")):
    k = ["symbol", tcol]
    old = pd.read_parquet(f"data/{tab}_before_r23.parquet")
    new = pd.read_parquet(f"data/{tab}.parquet")
    cols = list(old.columns)
    r = {"rows_before": len(old), "rows_after": len(new), "names_before": int(old["symbol"].nunique()), "names_after": int(new["symbol"].nunique()),
         "columns_equal": cols == list(new.columns), "sorted_by_key": bool(new[k].astype({"symbol": str}).equals(new[k].astype({"symbol": str}).sort_values(k, kind="mergesort").reset_index(drop=True)))
         if tab == "funding_archive" else None}
    old["symbol"], new["symbol"] = old["symbol"].astype(str), new["symbol"].astype(str)
    m = old.merge(new, on=k, how="left", suffixes=("", "_new"), indicator=True)
    r["old_rows_missing_after"] = int((m["_merge"] != "both").sum())
    r["old_rows_changed"] = {c: int((~((m[c] == m[c + "_new"]) | (m[c].isna() & m[c + "_new"].isna()))).sum()) for c in cols if c not in k}
    r["duplicate_keys_after"] = int(new.duplicated(k).sum())
    del m, old
    a, b = pd.Timestamp("2021-12-01", tz="UTC"), universe.PRE_END
    w = new[(new[tcol] >= a) & (new[tcol] < b)]
    mem = universe.screen_symbols(universe.PRE_MEMBERS_CSV)
    have = set(w["symbol"].unique())
    r["rows_in_window"], r["members"], r["members_without_a_row"] = len(w), len(mem), [s for s in mem if s not in have]
    r["status"] = "PASS" if r["columns_equal"] and not r["old_rows_missing_after"] and not any(r["old_rows_changed"].values()) and not r["duplicate_keys_after"] \
        and not r["members_without_a_row"] else "FAIL"
    out[tab] = r
    print(tab, json.dumps(r, indent=1), flush=True)
    del new, w
out["status"] = "PASS" if all(v["status"] == "PASS" for v in out.values()) else "FAIL"
Path("output/horizon").mkdir(parents=True, exist_ok=True)
Path("output/horizon/r23_inputs.json").write_text(json.dumps(out, indent=1))
print("status", out["status"])
