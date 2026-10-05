"""R29's validity (3): R28 comes back. After R29's ingest and with the code as changed for it, `ft2 listing run --name
r28_recheck` must give R28's family to 1e-9 — numbers already read; nothing of F3+F4 is touched. On the work VM:
    PYTHONPATH=. python -m ft2 listing run --name r28_recheck
    PYTHONPATH=. python scripts/r29_check_r28.py                 → output/listing/r29_r28_check.json"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

out = Path("output/listing")
a, b = pd.read_csv(out / "r28" / "holds.csv"), pd.read_csv(out / "r28_recheck" / "holds.csv")
num = [c for c in a.columns if pd.api.types.is_numeric_dtype(a[c])]
la, lb = pd.read_csv(out / "r28" / "launches.csv"), pd.read_csv(out / "r28_recheck" / "launches.csv")
ycols = [c for c in la.columns if c.startswith(("y_", "a_", "b_"))]
r = {"holds_same_shape": bool(a.shape == b.shape), "max_abs_diff_family": float(np.nanmax(np.abs(a[num].to_numpy() - b[num].to_numpy()))) if a.shape == b.shape else None,
     "verdicts_same": bool((a["verdict"] == b["verdict"]).all()) if a.shape == b.shape else False, "launches_same": bool(la["contract"].tolist() == lb["contract"].tolist()),
     "max_abs_diff_labels": float(np.nanmax(np.abs(la[ycols].to_numpy() - lb[ycols].to_numpy()))) if la.shape == lb.shape else None}
r["status"] = "PASS" if r["holds_same_shape"] and r["verdicts_same"] and r["launches_same"] and r["max_abs_diff_family"] is not None and r["max_abs_diff_family"] <= 1e-9 and r["max_abs_diff_labels"] is not None and r["max_abs_diff_labels"] <= 1e-9 else "FAIL"
(out / "r29_r28_check.json").write_text(json.dumps(r, indent=1))
print(json.dumps(r, indent=1))
