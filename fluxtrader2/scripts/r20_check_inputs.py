"""R20 pre-run check: inputs only, no label and no IC is touched.
(1) the twelve's metrics rows are the ones of the pre-R20 file; (2) which names each source holds, on F1+F2.
Run on the work VM:  ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/r20_check_inputs.py' (after `vm.sh push`).
"""
import pandas as pd

old = pd.read_parquet("data/metrics_before_r20.parquet")
twelve = sorted(old["symbol"].astype(str).unique())
new = pd.read_parquet("data/metrics.parquet", filters=[("symbol", "in", twelve)])
for d in (old, new):
    d["symbol"] = d["symbol"].astype(str)
k = ["symbol", "ts"]
old, new = old.sort_values(k).reset_index(drop=True), new.sort_values(k).reset_index(drop=True)
print("twelve:", len(twelve), "old rows", len(old), "new rows", len(new), "columns equal", list(old.columns) == list(new.columns))
if len(old) == len(new):
    same = all(((old[c] == new[c]) | (old[c].isna() & new[c].isna())).all() for c in old.columns)
    print("twelve's rows unchanged:", bool(same))
else:
    m = old[k].merge(new[k], how="outer", indicator=True)
    print(m["_merge"].value_counts().to_dict())
    print(m[m["_merge"] != "both"].groupby(["symbol", "_merge"], observed=True).size().head(30))

import json
import pathlib

meta = json.loads(pathlib.Path("output/backtest/r18_transferbook_1d/meta.json").read_text())
names = sorted(set(map(str, meta["pairs"])))
print("run pairs:", len(names), "folds", meta["folds"])
a, b = pd.Timestamp("2023-04-01", tz="UTC"), pd.Timestamp("2024-09-01", tz="UTC")
for tab, tcol in (("metrics", "ts"), ("premium", "open_time"), ("funding_archive", "ts")):
    d = pd.read_parquet(f"data/{tab}.parquet", columns=["symbol", tcol])
    d["symbol"] = d["symbol"].astype(str)
    d = d[(d[tcol] >= a) & (d[tcol] < b)]
    have = set(d["symbol"].unique())
    miss = [n for n in names if n not in have]
    print(f"{tab:16s} rows in window {len(d):>11,}  names {len(have):>4}  run pairs without a row: {len(miss)} {miss[:20]}")
