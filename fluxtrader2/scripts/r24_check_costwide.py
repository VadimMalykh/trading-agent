"""R24's validity (1): `costwide` was re-run from 2021-12-01; every row of the file as it was is in the new one, unchanged.
Costs only — no price move, no label, no trade is touched. Run on the work VM, from ~/fluxtrader2, in the venv:
    cp data/cost_daily_wide.parquet data/cost_daily_wide_before_r24.parquet          (BEFORE the re-run)
    python -m ft2 costwide --universe all --start 2021-12-01
    PYTHONPATH=. python scripts/r24_check_costwide.py                                  → output/backtest/r24_costwide_check.json"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import universe

k = ["symbol", "day"]
old, new = (pd.read_parquet(f"data/cost_daily_wide{s}.parquet") for s in ("_before_r24", ""))
for d in (old, new):
    d["symbol"] = d["symbol"].astype(str)
m = old.merge(new, on=k, how="left", suffixes=("", "_new"), indicator=True)
num = [c for c in old.columns if c not in k and pd.api.types.is_numeric_dtype(old[c])]
diff = {c: float(np.nanmax(np.abs(m[c] - m[c + "_new"]))) if m[c].notna().any() else 0.0 for c in num}
nan_same = bool(all((m[c].isna() == m[c + "_new"].isna()).all() for c in num))
mem = universe.screen_symbols(universe.PRE_MEMBERS_CSV)
w = new[(new["day"] >= pd.Timestamp("2021-12-10", tz="UTC")) & (new["day"] < universe.PRE_END) & new["symbol"].isin(mem)]
leg = w["spread_cal_bps"] / 2 + w["imp_10000"]
r = {"rows_before": len(old), "rows_after": len(new), "first_day_before": str(old["day"].min()), "first_day_after": str(new["day"].min()), "names_before": int(old["symbol"].nunique()),
     "names_after": int(new["symbol"].nunique()), "old_rows_missing_after": int((m["_merge"] != "both").sum()), "max_abs_diff": max(diff.values()), "nan_pattern_same": nan_same,
     "duplicate_keys_after": int(new.duplicated(k).sum()), "members": len(mem), "members_priced_on_r23s_days": int(w["symbol"].nunique()),
     "members_without_a_cost": sorted(set(mem) - set(w["symbol"])), "member_days_priced": len(w), "member_days_without_impact": int(w["imp_10000"].isna().sum()),
     "taker_leg_other_bps_p50": float(leg.median()), "taker_leg_other_bps_p95": float(leg.quantile(0.95))}
r["status"] = "PASS" if not r["old_rows_missing_after"] and r["max_abs_diff"] <= 1e-9 and nan_same and not r["duplicate_keys_after"] and not r["members_without_a_cost"] else "FAIL"
Path("output/backtest").mkdir(parents=True, exist_ok=True)
Path("output/backtest/r24_costwide_check.json").write_text(json.dumps(r, indent=1))
print(json.dumps(r, indent=1))
