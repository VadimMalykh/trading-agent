"""The validity of a re-execution `actual` (PLAN §3): the read made again is the first read's — the same trades, or the same
cells — and only the unit of money differs. Run where both outputs are (the work VM):
  python scripts/actual_check.py trades <first run> <re-executed run>     → output/backtest/<re-executed run>/same_as_first_read.json
  python scripts/actual_check.py cells  <first dir> <re-executed dir>     → output/horizon/<re-executed dir>/same_as_first_read.json
trades   the decisions are identical, row by row; per execution, every fill has the same id, times, prices, fees, spread and
         impact, and funding; the first read's gross is side × log(exit / entry) and this one's side × (exit / entry − 1);
         the net of the first read's fills re-priced with the actual return is this run's net.
cells    per signal × hold: the same number of cells and days, and the same rank IC (it is computed on the vol-standardised
         log label, which the correction does not touch) — the cells, the signals and the label windows are the first read's."""
import json
import sys

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import horizon

TOL = 1e-9
SAME = ["id", "t", "symbol", "fold", "side", "size", "exec", "entry_t", "exit_t", "entry_px", "exit_px", "fee_bps", "other_cost_bps", "p_fill", "funding_bps"]


def trades(old: str, new: str) -> dict:
    a, b = bt.OUT / old, bt.OUT / new
    ma, mb = (json.loads((x / "meta.json").read_text()) for x in (a, b))
    da, db = (pd.read_parquet(x / "decisions.parquet") for x in (a, b))
    v = {"first": old, "re_executed": new, "unit_first": ma.get("unit", "log"), "unit_re_executed": mb.get("unit", "log"), "decisions": len(db),
         "decisions_identical": bool(da.equals(db)), "params_identical": ma["params"] == mb["params"] and ma["folds"] == mb["folds"] and ma["pairs"] == mb["pairs"], "execs": {}}
    ok = v["decisions_identical"] and v["params_identical"] and v["unit_first"] == "log" and v["unit_re_executed"] == "actual"
    for e in bt.EXECS:
        if not ((a / f"fills_{e}.parquet").exists() and (b / f"fills_{e}.parquet").exists()):
            continue
        fa, fb = (pd.read_parquet(x / f"fills_{e}.parquet") for x in (a, b))
        same = len(fa) == len(fb) and all(fa[c].equals(fb[c]) for c in SAME)
        pa, pb = fa.dropna(subset=["net_bps"]), fb.dropna(subset=["net_bps"])
        s, r = pb["side"].to_numpy(float), (pb["exit_px"] / pb["entry_px"]).to_numpy()
        log_ok = bool(np.allclose(pa["side"] * np.log(pa["exit_px"] / pa["entry_px"]) * 1e4, pa["gross_bps"], rtol=0, atol=1e-6))
        act_ok = bool(np.allclose(s * (r - 1) * 1e4, pb["gross_bps"], rtol=0, atol=1e-6))
        w = pa["size"].to_numpy()
        repriced = float(np.average(pa["side"] * (pa["exit_px"] / pa["entry_px"] - 1) * 1e4 - pa["fee_bps"] - pa["other_cost_bps"] + pa["funding_bps"], weights=w))
        net_new = float(pd.read_parquet(b / "results.parquet").query("exec == @e and scope == 'all'")["net"].iloc[0])
        x = {"fills": len(fb), "priced": len(pb), "fills_identical_but_the_gross": bool(same), "first_gross_is_the_log": log_ok, "this_gross_is_the_actual_return": act_ok,
             "net_first_read": float(np.average(pa["net_bps"], weights=w)), "net_first_read_repriced": repriced, "net_re_executed": net_new,
             "abs_diff_repriced_vs_re_executed": abs(repriced - net_new)}
        ok = ok and same and log_ok and act_ok and len(pa) == len(pb) and x["abs_diff_repriced_vs_re_executed"] <= 1e-6
        v["execs"][e] = x
    v["status"] = "PASS" if ok and v["execs"] else "FAIL"
    (b / "same_as_first_read.json").write_text(json.dumps(v, indent=1))
    return v


def cells(old: str, new: str) -> dict:
    a, b = (pd.read_csv(horizon.OUT / x / "signals.csv").set_index(["signal", "hold"]) for x in (old, new))
    cols = [c for c in ("cells", "days", "ic", "ic_t", "kept_by_a_shift", "family") if c in a.columns]
    ua, ub = (json.loads((horizon.OUT / x / "validity.json").read_text()) for x in (old, new))
    d = {c: float((a[c].astype(float) - b[c].reindex(a.index).astype(float)).abs().max()) for c in cols} if a.index.equals(b.index) else {}
    sa, sb = (pd.read_parquet(horizon.OUT / x / "shifts.parquet") for x in (old, new))
    v = {"first": old, "re_executed": new, "unit_first": ua.get("unit", "log"), "unit_re_executed": ub.get("unit", "log"), "rows": len(b), "rows_identical": bool(a.index.equals(b.index)),
         "cells": int(ub["cells"]), "cells_first": int(ua["cells"]), "shifts": int(sb["shift"].nunique() - 1), "shifts_first": int(sa["shift"].nunique() - 1), "max_abs_diff": d,
         "validity_re_executed": ub["status"]}
    ok = (v["rows_identical"] and v["cells"] == v["cells_first"] and v["shifts"] == v["shifts_first"] and d and max(d.values()) <= TOL and ub["status"] == "PASS"
          and v["unit_first"] == "log" and v["unit_re_executed"] == "actual")
    v["status"] = "PASS" if ok else "FAIL"
    (horizon.OUT / new / "same_as_first_read.json").write_text(json.dumps(v, indent=1))
    return v


if __name__ == "__main__":
    out = {"trades": trades, "cells": cells}[sys.argv[1]](sys.argv[2], sys.argv[3])
    print(json.dumps(out, indent=1))
    sys.exit(0 if out["status"] == "PASS" else 1)
