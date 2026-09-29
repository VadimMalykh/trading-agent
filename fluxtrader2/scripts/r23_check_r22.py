"""R23's validity (2): R22 comes back after the ingest. Run on the work VM, from ~/fluxtrader2, in the venv:
    cp -r output/horizon/r18_transferbook_1d output/horizon/r22_saved          (BEFORE the ingest)
    python -m ft2 ingest klines funding_archive metrics --universe all
    python -m ft2 horizon r18_transferbook_1d --holds 864 2016
    python scripts/r23_check_r22.py                                             → output/horizon/r22_check.json
It compares numbers R22 has already read with themselves; it reads nothing new."""
import json
from pathlib import Path

import pandas as pd

OUT, TOL, COLS = Path("output/horizon"), 1e-9, ["m", "centre", "se", "m_after_first", "funding_part", "ic"]
key = ["signal", "hold"]
a, b = (pd.read_csv(OUT / d / "signals.csv").set_index(key).sort_index() for d in ("r22_saved", "r18_transferbook_1d"))
va, vb = (json.loads((OUT / d / "validity.json").read_text()) for d in ("r22_saved", "r18_transferbook_1d"))
same_rows = a.index.equals(b.index)
d = (a[COLS] - b.loc[a.index, COLS]).abs().max() if same_rows else None
cells = bool(same_rows and (a["cells"] == b.loc[a.index, "cells"]).all() and (a[COLS].isna() == b.loc[a.index, COLS].isna()).all().all())
r = {"rows": len(a), "same_rows": same_rows, "same_cells": cells, "max_abs_diff": None if d is None else {k: float(x) for k, x in d.items()}, "tol": TOL,
     "validity_saved": va["status"], "validity_rerun": vb["status"], "cells_saved": va["cells"], "cells_rerun": vb["cells"],
     "generated_saved": (OUT / "r22_saved" / "horizon.md").read_text().splitlines()[2][:40], "generated_rerun": (OUT / "r18_transferbook_1d" / "horizon.md").read_text().splitlines()[2][:40]}
r["status"] = "PASS" if same_rows and cells and float(d.fillna(0).max()) <= TOL and va["status"] == vb["status"] == "PASS" and va["cells"] == vb["cells"] \
    and r["generated_saved"] != r["generated_rerun"] else "FAIL"
(OUT / "r22_check.json").write_text(json.dumps(r, indent=1))
print(json.dumps(r, indent=1))
