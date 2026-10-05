"""R28's validity (2): the ingest rewrites the archive slices whole; every name they held before must come back unchanged.
A fingerprint per name instead of a copy of the slices (they are 6 GB): rows, first and last bar, the sums of close and volume
for the klines; rows, first and last event and the sum of rates for funding. A name that was held on a shorter window and
has gained months (a launch of F1 held until now only as a member of F3+F4) is compared on its OLD extent: the rows between
its old first and last bar, read again from the new slice. No label, no trade. On the work VM, from
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


def fingerprint(extent: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per slice and name. With `extent` (slice, symbol, first, last): only those names, each on the rows inside [first, last]."""
    parts = []
    for s, (tcol, vals) in SLICES.items():
        d = pd.read_parquet(f"data/{s}.parquet", columns=["symbol", tcol, *vals])
        if extent is not None:
            e = extent[extent["slice"] == s]
            d = d[d["symbol"].isin(set(e["symbol"]))]
            d = d.assign(symbol=d["symbol"].astype(str)).merge(e[["symbol", "first", "last"]], on="symbol")
            d = d[(d[tcol] >= d["first"]) & (d[tcol] <= d["last"])].drop(columns=["first", "last"])
            if not len(d):
                continue
        g = d.groupby("symbol", observed=True)
        f = g.agg(rows=(tcol, "size"), first=(tcol, "min"), last=(tcol, "max"), **{f"sum_{v}": (v, "sum") for v in vals}).reset_index()
        f["symbol"] = f["symbol"].astype(str)
        parts.append(f.assign(slice=s))
    return pd.concat(parts, ignore_index=True)


def extended(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """The names whose slice now reaches further back or forward and holds no fewer rows: (slice, symbol, the OLD first and last)."""
    m = old.merge(new, on=["slice", "symbol"], suffixes=("", "_new"))
    x = m[((m["first_new"] < m["first"]) | (m["last_new"] > m["last"])) & (m["first_new"] <= m["first"]) & (m["last_new"] >= m["last"]) & (m["rows_new"] >= m["rows"])]
    return x[["slice", "symbol", "first", "last"]]


def compare(old: pd.DataFrame, new: pd.DataFrame, on_old_extent: pd.DataFrame | None = None) -> dict:
    """`on_old_extent`: the fingerprints of the extended names taken on their old extent — they stand in for those names' rows of `new`."""
    k = ["slice", "symbol"]
    n_ext, n_all = 0, len(new)
    if on_old_extent is not None and len(on_old_extent):
        keys = set(map(tuple, on_old_extent[k].to_numpy()))
        new = pd.concat([new[[t not in keys for t in map(tuple, new[k].to_numpy())]], on_old_extent], ignore_index=True)
        n_ext = len(keys)
    m = old.merge(new, on=k, how="left", suffixes=("", "_new"), indicator=True)
    both = m[m["_merge"] == "both"]
    sums = [c for c in old.columns if c.startswith("sum_")]
    exact = bool((both["rows"] == both["rows_new"]).all() and (both["first"] == both["first_new"]).all() and (both["last"] == both["last_new"]).all())
    rel = {c: float(np.nanmax(np.abs(both[c] - both[c + "_new"]) / np.maximum(np.abs(both[c]), 1e-12))) if both[c].notna().any() else 0.0 for c in sums}
    nan_same = bool(all((both[c].isna() == both[c + "_new"].isna()).all() for c in sums))
    r = {"names_before": int(len(old)), "names_after": int(len(new)), "names_missing_after": int((m["_merge"] != "both").sum()), "rows_first_last_identical": exact,
         "max_relative_diff_of_sums": rel, "nan_pattern_same": nan_same, "new_names": int(n_all - len(both)), "names_compared_on_their_old_extent": n_ext}
    r["status"] = "PASS" if not r["names_missing_after"] and exact and nan_same and max(rel.values(), default=0.0) <= 1e-12 else "FAIL"
    return r


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    TAG = sys.argv[2] if len(sys.argv) > 2 else "r28"           # r29: the same check before and after R29's ingest
    if sys.argv[1] == "save":
        fingerprint().to_csv(OUT / f"{TAG}_fingerprint_before.csv", index=False)
        print(f"saved {OUT / f'{TAG}_fingerprint_before.csv'}")
    else:
        old = pd.read_csv(OUT / f"{TAG}_fingerprint_before.csv")
        new = fingerprint()
        for d in (old, new):
            for c in ("first", "last"):
                d[c] = pd.to_datetime(d[c], utc=True)
        ext = extended(old, new)
        r = compare(old, new, fingerprint(ext) if len(ext) else None)
        r["extended"] = sorted(f"{a}:{b}" for a, b in ext[["slice", "symbol"]].to_numpy())
        r["latest_bar"] = str(new.loc[new["slice"] == "candles_5m_archive", "last"].max())
        (OUT / f"{TAG}_fingerprint_check.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))
