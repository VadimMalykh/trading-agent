"""R20, described only: the shape of the registered null per feature, and which feature holds the family's max per draw.
Reads output/audit/<run>/draws.parquet as written by the registered run; computes nothing new on the cells.
Run on the work VM:  ./fluxtrader2/scripts/vm.sh ssh 'cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/r20_describe_null.py' (after `vm.sh push`).
"""
import pandas as pd

pd.set_option("display.width", 200)
d = pd.read_parquet("output/audit/r18_transferbook_1d/draws.parquet")
real, null = d[d.draw == 0].set_index("feature"), d[d.draw > 0]
g = null.groupby("feature", sort=False)
t = pd.DataFrame({"t_real": real["t"], "ic_real": real["ic"], "null_t_mean": g["t"].mean(), "null_t_sd": g["t"].std(), "null_t_q05": g["t"].quantile(0.05),
                  "null_t_q95": g["t"].quantile(0.95), "null_ic_mean": g["ic"].mean(), "null_ic_sd": g["ic"].std(), "se_real": real["se"]})
t["t_centred"] = (t["t_real"] - t["null_t_mean"]) / t["null_t_sd"]
t["ic_minus_null"] = t["ic_real"] - t["null_ic_mean"]
t["p_centred"] = [(1 + int(((null[null.feature == k]["t"] - t.loc[k, "null_t_mean"]).abs() >= abs(t.loc[k, "t_real"] - t.loc[k, "null_t_mean"])).sum())) / 201 for k in t.index]
print(t.round(4).to_string())
a = null.assign(a=null["t"].abs())
top = a.loc[a.groupby("draw")["a"].idxmax()]
print("\nwho holds the family max |t|, 200 draws:\n", top["feature"].value_counts().to_string())
print("\ndraws with max |t| >= 3.98:\n", top[top.a >= 3.98]["feature"].value_counts().to_string())
mx = a.groupby("draw")["a"].max()
print("\nfamily max |t|: mean %.2f  q50 %.2f  q95 %.2f" % (mx.mean(), mx.median(), mx.quantile(0.95)))
