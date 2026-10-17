"""R42 validity (1): the F1+F2 walk made again today (`r42_check_f12`) gives R14's decisions (t, symbol, side, size) exactly
(`backtest._same`) and a taker net equal to §3's actual column for R14 (+39.2) within 0.05 — the code path unchanged since R14,
under today's unit. → output/logs/r42_same_check.json; exit 1 on a failure."""
import json
import sys
from pathlib import Path

import pandas as pd

from ft2 import backtest as bt

R14, CHECK, R14_ACTUAL_NET, TOL = "r14_ridgebook_1d_ho12", "r42_check_f12", 39.2, 0.05
d14, d42 = (pd.read_parquet(bt.OUT / r / "decisions.parquet") for r in (R14, CHECK))
same_all = bt._same(d14, d42)
same_acc = bt._same(d14[d14["accepted"]], d42[d42["accepted"]])
res = pd.read_parquet(bt.OUT / CHECK / "results.parquet")
net = float(res[(res["exec"] == "taker") & (res["scope"] == "all")]["net"].iloc[0])
meta = json.loads((bt.OUT / CHECK / "meta.json").read_text())
out = {"decisions_r14": int(len(d14)), "decisions_check": int(len(d42)), "same_all": bool(same_all), "same_accepted": bool(same_acc),
       "accepted_r14": int(d14["accepted"].sum()), "accepted_check": int(d42["accepted"].sum()), "taker_net_check": net, "r14_actual_net_plan": R14_ACTUAL_NET,
       "d_net": net - R14_ACTUAL_NET, "unit": meta.get("unit"), "charged": meta.get("charged"), "params": meta["params"]}
out["status"] = "PASS" if same_all and same_acc and abs(net - R14_ACTUAL_NET) <= TOL and meta.get("unit") == "actual" and meta.get("charged") == "value" else "FAIL"
Path("output/logs").mkdir(parents=True, exist_ok=True)
Path("output/logs/r42_same_check.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))
sys.exit(0 if out["status"] == "PASS" else 1)
