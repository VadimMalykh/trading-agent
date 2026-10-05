"""R24's validity (1): `costwide` was re-run from 2021-12-01; every row of the file as it was is in the new one, unchanged.
Costs only — no price move, no label, no trade is touched. Run on the work VM, from ~/fluxtrader2, in the venv:
    cp data/cost_daily_wide.parquet data/cost_daily_wide_before_r24.parquet          (BEFORE the re-run)
    python -m ft2 costwide --universe all --start 2021-12-01
    PYTHONPATH=. python scripts/r24_check_costwide.py                                  → output/backtest/r24_costwide_check.json"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import universe

TAG = sys.argv[1] if len(sys.argv) > 1 else "r24"          # r25: the copy is *_before_r25, the members F3+F4's, the days F3+F4's
k = ["symbol", "day"]
old, new = (pd.read_parquet(f"data/cost_daily_wide{s}.parquet") for s in (f"_before_{TAG}", ""))
for d in (old, new):
    d["symbol"] = d["symbol"].astype(str)
m = old.merge(new, on=k, how="left", suffixes=("", "_new"), indicator=True)
num = [c for c in old.columns if c not in k and pd.api.types.is_numeric_dtype(old[c])]
diff = {c: float(np.nanmax(np.abs(m[c] - m[c + "_new"]))) if m[c].notna().any() else 0.0 for c in num}
nan_same = bool(all((m[c].isna() == m[c + "_new"].isna()).all() for c in num))
if TAG in ("r28", "r29"):                                    # R28 / R29: the names are the launches of F1+F2 / F3+F4, the days those folds' from each contract's first day
    from ft2 import listing
    from ft2.__main__ import PAIRS
    csv, fl = (listing.LAUNCHES_CSV, listing.FOLDS) if TAG == "r28" else (listing.LAUNCHES34_CSV, listing.CONF_FOLDS)
    mem, (lo, hi) = [x for x in listing.launch_symbols(csv) if x not in PAIRS], listing.window(fl)      # a launch that is one of the twelve is priced from the tape (cost_daily), never in the wide file
else:
    mem = universe.screen_symbols(universe.PRE_MEMBERS_CSV if TAG == "r24" else universe.F34_MEMBERS_CSV)
    lo, hi = (pd.Timestamp("2021-12-10", tz="UTC"), universe.PRE_END) if TAG == "r24" else (pd.Timestamp("2024-09-03", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC"))
w = new[(new["day"] >= lo) & (new["day"] < hi) & new["symbol"].isin(mem)]
leg = w["spread_cal_bps"] / 2 + w["imp_10000"]
r = {"rows_before": len(old), "rows_after": len(new), "first_day_before": str(old["day"].min()), "first_day_after": str(new["day"].min()), "names_before": int(old["symbol"].nunique()),
     "names_after": int(new["symbol"].nunique()), "old_rows_missing_after": int((m["_merge"] != "both").sum()), "max_abs_diff": max(diff.values()), "nan_pattern_same": nan_same,
     "duplicate_keys_after": int(new.duplicated(k).sum()), "members": len(mem), "members_priced_on_the_days_read": int(w["symbol"].nunique()),
     "members_without_a_cost": sorted(set(mem) - set(w["symbol"])), "member_days_priced": len(w), "member_days_without_impact": int(w["imp_10000"].isna().sum()),
     "taker_leg_other_bps_p50": float(leg.median()), "taker_leg_other_bps_p95": float(leg.quantile(0.95))}
r["status"] = "PASS" if not r["old_rows_missing_after"] and r["max_abs_diff"] <= 1e-9 and nan_same and not r["duplicate_keys_after"] and not r["members_without_a_cost"] else "FAIL"
Path("output/backtest").mkdir(parents=True, exist_ok=True)
Path(f"output/backtest/{TAG}_costwide_check.json").write_text(json.dumps(r, indent=1))
print(json.dumps(r, indent=1))
