"""Input check of R23 (and, with the tag `r25`, of R25): inputs only, no label and no statistic is touched.
(1) every row the three archive slices held before the ingest is in them after it, value for value (the copies
    data/*_before_<tag>.parquet were taken before the ingest); (2) which members have rows in each source on the days
    read; (3) no row dated at or after the end of the window that was not in the slices before (R25: nothing of F5).
Name by name: the slices do not fit the work VM's memory twice over (the first version, whole frames merged, was killed).
Run on the work VM:  ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/r23_check_inputs.py [r25]'
→ output/horizon/<tag>_inputs.json
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ft2 import universe

TAG = sys.argv[1] if len(sys.argv) > 1 else "r23"
if TAG == "r23":
    A, B, MEM = pd.Timestamp("2021-12-01", tz="UTC"), universe.PRE_END, universe.screen_symbols(universe.PRE_MEMBERS_CSV)
else:                                                      # r25: the members of F3+F4's blocks, the window F3+F4
    A, B, MEM = pd.Timestamp("2024-09-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC"), universe.screen_symbols(universe.F34_MEMBERS_CSV)


def names(path: str) -> list[str]:
    return sorted(pq.read_table(path, columns=["symbol"]).column("symbol").unique().to_pylist())


def one(path: str, sym: str) -> pd.DataFrame:
    d = pd.read_parquet(path, filters=[("symbol", "==", sym)])
    d["symbol"] = d["symbol"].astype(str)
    return d


out = {}
for tab, tcol in (("funding_archive", "ts"), ("metrics", "ts"), ("candles_5m_archive", "open_time")):
    old_p, new_p, k = f"data/{tab}_before_{TAG}.parquet", f"data/{tab}.parquet", ["symbol", tcol]
    n_old, n_new = names(old_p), names(new_p)
    r = {"rows_before": pq.ParquetFile(old_p).metadata.num_rows, "rows_after": pq.ParquetFile(new_p).metadata.num_rows, "names_before": len(n_old), "names_after": len(n_new),
         "columns_equal": pq.ParquetFile(old_p).schema_arrow.names == pq.ParquetFile(new_p).schema_arrow.names, "names_gone": sorted(set(n_old) - set(n_new)),
         "old_rows_missing_after": 0, "old_rows_changed": 0, "duplicate_keys_after": 0, "rows_in_window": 0, "unsorted_names": 0, "new_rows_at_or_after_the_window": 0}
    have = set()
    for i, sym in enumerate(n_new):
        new = one(new_p, sym)
        r["duplicate_keys_after"] += int(new.duplicated(k).sum())
        r["unsorted_names"] += int(not new[tcol].is_monotonic_increasing)
        w = int(((new[tcol] >= A) & (new[tcol] < B)).sum())
        r["rows_in_window"] += w
        if w:
            have.add(sym)
        late = int((new[tcol] >= B).sum())
        if sym in n_old:
            old = one(old_p, sym)
            late -= int((old[tcol] >= B).sum())
            m = old.merge(new, on=k, how="left", suffixes=("", "_new"), indicator=True)
            r["old_rows_missing_after"] += int((m["_merge"] != "both").sum())
            r["old_rows_changed"] += int(sum((~((m[c] == m[c + "_new"]) | (m[c].isna() & m[c + "_new"].isna()))).sum() for c in old.columns if c not in k))
        r["new_rows_at_or_after_the_window"] += late
        if i % 50 == 0:
            print(f"{tab}: {i}/{len(n_new)}", flush=True)
    r["members"], r["members_without_a_row"] = len(MEM), [s for s in MEM if s not in have]
    r["status"] = "PASS" if r["columns_equal"] and not (r["names_gone"] or r["old_rows_missing_after"] or r["old_rows_changed"] or r["duplicate_keys_after"] or r["unsorted_names"]
                                                        or r["members_without_a_row"] or r["new_rows_at_or_after_the_window"]) else "FAIL"
    out[tab] = r
    print(tab, json.dumps(r, indent=1), flush=True)
out["status"] = "PASS" if all(v["status"] == "PASS" for v in out.values()) else "FAIL"
Path("output/horizon").mkdir(parents=True, exist_ok=True)
Path(f"output/horizon/{TAG}_inputs.json").write_text(json.dumps(out, indent=1))
print("status", out["status"])
