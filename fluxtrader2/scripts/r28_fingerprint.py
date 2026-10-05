"""R28's validity (2): the ingest rewrites the archive slices whole; every name they held before must come back unchanged.
A fingerprint per name instead of a copy of the slices (they are 6 GB): rows, first and last bar, the sums of close and volume
for the klines; rows, first and last event and the sum of rates for funding. No label, no trade. On the work VM, from
~/fluxtrader2, in the venv:
    PYTHONPATH=. python scripts/r28_fingerprint.py save      (BEFORE the ingest)  → output/listing/r28_fingerprint_before.csv
    PYTHONPATH=. python scripts/r28_fingerprint.py check     (after it)           → output/listing/r28_fingerprint_check.json"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("output/listing")
SLICES = {"candles_5m_archive": ("open_time", ["close", "volume"]), "funding_archive": ("ts", ["rate"])}


def fingerprint() -> pd.DataFrame:
    parts = []
    for s, (tcol, vals) in SLICES.items():
        d = pd.read_parquet(f"data/{s}.parquet", columns=["symbol", tcol, *vals])
        g = d.groupby("symbol", observed=True)
        f = g.agg(rows=(tcol, "size"), first=(tcol, "min"), last=(tcol, "max"), **{f"sum_{v}": (v, "sum") for v in vals}).reset_index()
        f["symbol"] = f["symbol"].astype(str)
        parts.append(f.assign(slice=s))
    return pd.concat(parts, ignore_index=True)


def compare(old: pd.DataFrame, new: pd.DataFrame) -> dict:
    k = ["slice", "symbol"]
    m = old.merge(new, on=k, how="left", suffixes=("", "_new"), indicator=True)
    both = m[m["_merge"] == "both"]
    sums = [c for c in old.columns if c.startswith("sum_")]
    exact = bool((both["rows"] == both["rows_new"]).all() and (both["first"] == both["first_new"]).all() and (both["last"] == both["last_new"]).all())
    rel = {c: float(np.nanmax(np.abs(both[c] - both[c + "_new"]) / np.maximum(np.abs(both[c]), 1e-12))) if both[c].notna().any() else 0.0 for c in sums}
    nan_same = bool(all((both[c].isna() == both[c + "_new"].isna()).all() for c in sums))
    r = {"names_before": int(len(old)), "names_after": int(len(new)), "names_missing_after": int((m["_merge"] != "both").sum()), "rows_first_last_identical": exact,
         "max_relative_diff_of_sums": rel, "nan_pattern_same": nan_same, "new_names": int(len(new) - len(both))}
    r["status"] = "PASS" if not r["names_missing_after"] and exact and nan_same and max(rel.values(), default=0.0) <= 1e-12 else "FAIL"
    return r


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == "save":
        fingerprint().to_csv(OUT / "r28_fingerprint_before.csv", index=False)
        print(f"saved {OUT / 'r28_fingerprint_before.csv'}")
    else:
        old = pd.read_csv(OUT / "r28_fingerprint_before.csv")
        new = fingerprint()
        for d in (old, new):
            for c in ("first", "last"):
                d[c] = pd.to_datetime(d[c], utc=True)
        r = compare(old, new)
        (OUT / "r28_fingerprint_check.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))
