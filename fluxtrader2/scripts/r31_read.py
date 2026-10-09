"""R31 — stage 1 read from the pulled fills (`output/backtest/ixhour4h/`, the described rows `r31_lag0`, `r31_lag12`, `r31_theta2`):
the gate's per-calendar-year nets with the harness's own `summarize` (the report has folds, not years), long and short apart, the net by the
hour block of the hour read, the sizing row (the basket's |4h move| on the rule's entries by year) and the described rows' bottom lines.
Run: docker run --rm -v "$PWD/fluxtrader2:/workspace/ft2" -w /workspace/ft2 -e PYTHONPATH=/workspace/ft2 fluxtrader2-analysis:latest python scripts/r31_read.py"""

import json, numpy as np, pandas as pd
from ft2 import backtest as bt
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.float_format", lambda v: f"{v:+.2f}")
B = "output/backtest"
def fills(run, ex): return pd.read_parquet(f"{B}/{run}/fills_{ex}.parquet")
def days_of(f): return pd.DatetimeIndex(sorted(pd.DatetimeIndex(f["entry_t"]).floor("D").unique()))
def row(f, label):
    f = f.dropna(subset=["net_bps"]); s = bt.summarize(f, days_of(f), 48)
    return {"scope": label, "trades": s["trades"], "days": s["days"], "t/day": round(s["trades_per_day"], 1), "hit": round(s["hit"], 3), "gross": s["gross"], "fee": s["fee"], "other": s["other_cost"], "fund": s["funding"],
            "net": s["net"], "lo": s["net_lo"], "hi": s["net_hi"], "mde": s["net_mde"], "p_fill": s["p_fill"]}
print("=== meta ==="); m = json.load(open(f"{B}/ixhour4h/meta.json")); print({k: m[k] for k in m if k in ("params", "folds", "registration", "unit", "charged", "decisions", "taken", "trades")})
res = pd.read_parquet(f"{B}/ixhour4h/results.parquet")
print("\n=== stage 1: per fold and long/short (results.parquet) ===")
print(res[res["scope"].isin(["all", "FP", "F0", "F1", "F2", "long", "short"])][["exec", "scope", "trades", "trades_per_day", "hit", "gross", "hedged", "fee", "other_cost", "funding", "net", "net_lo", "net_hi", "net_mde", "p_fill"]].to_string(index=False))
nul = pd.read_parquet(f"{B}/ixhour4h/null.parquet"); print("\nnull columns:", list(nul.columns)[:12]); 
try: print(nul.groupby("exec")["net"].describe()[["mean", "std", "min", "max"]])
except Exception as e: print(nul.head())
for ex in ("maker", "taker"):
    f = fills("ixhour4h", ex); f["year"] = pd.DatetimeIndex(f["entry_t"]).year
    print(f"\n=== stage 1 by calendar year — {ex} ===")
    print(pd.DataFrame([row(g, y) for y, g in f.groupby("year")]).to_string(index=False))
    if ex == "maker":
        f["H"] = pd.DatetimeIndex(f["entry_t"]) - 4 * bt.BAR
        f["blk"] = pd.cut(f["H"].dt.hour, [-1, 7, 12, 19, 23], labels=["00-08 UTC", "08-13", "13-20 (US cash)", "20-24"])
        print("\n=== maker net by the hour block of H (the hour read) ===")
        print(pd.DataFrame([row(g, str(k)) for k, g in f.groupby("blk", observed=True)]).to_string(index=False))
        f12 = f[f["fold"].isin(["F1", "F2"])]; print("\n=== primary on F1+F2 only (for the described rows) ==="); print(pd.DataFrame([row(f12, "F1+F2 maker lag3 θ1")]).to_string(index=False))
        # sizing row: the basket's |4h move| on entry bars, by year, against all bars
        e = f.groupby("entry_t").apply(lambda g: (g["side"] * g["gross_bps"]).mean(), include_groups=False)
        print("\n=== sizing: mean |4h basket move| on the rule's entries (bps), by year ===")
        print(e.abs().groupby(pd.DatetimeIndex(e.index).year).agg(["mean", "count"]).T.to_string())
        print("baskets a day:", round(len(e) / f["entry_t"].dt.floor("D").nunique(), 2), " entries at the top of the hour + 4 bars:", bool(((pd.DatetimeIndex(e.index) - 4 * bt.BAR).minute == 0).all()))
try:
    sv = pd.read_parquet("output/market_index/size_view.parquet"); print("\n=== size_view (R30) ==="); print(sv.head(12).to_string())
except Exception as ex: print("size_view:", ex)
print("\n=== described rows on F1+F2 (results scope all) ===")
rows = []
for run in ("r31_lag0", "r31_lag12", "r31_theta2"):
    r = pd.read_parquet(f"{B}/{run}/results.parquet"); p = json.load(open(f"{B}/{run}/meta.json"))["params"]
    for ex in ("taker", "maker", "maker_ev"):
        x = r[(r["scope"] == "all") & (r["exec"] == ex)].iloc[0]
        rows.append({"run": run, "params": p, "exec": ex, "trades": x["trades"], "t/day": round(x["trades_per_day"], 1), "hit": round(x["hit"], 3), "gross": x["gross"], "net": x["net"], "lo": x["net_lo"], "hi": x["net_hi"], "mde": x["net_mde"]})
print(pd.DataFrame(rows).to_string(index=False))
for run in ("r31_lag0", "r31_lag12", "r31_theta2"):
    t = open(f"{B}/{run}/report.md").read(); i = t.find("## Bottom line"); print("\n", run, t[i:i+900].replace("\n\n", "\n"))
