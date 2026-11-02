# BY brainstorm count 3: the EXTREME-FUNDING episode per name from funding_archive, without the exchange's flag — the trailing-day funding
# sum beyond a threshold, one episode per name per 14 days, names >= 30 days old; by fold and sign; beside a flagged shortening or not;
# the 5m bars in hand for the episode's week. Counts only; no price read.
import pandas as pd, numpy as np, os
FOLDS = {"F0": ("2022-08-18","2023-05-01"), "F1": ("2023-05-01","2024-01-01"), "F2": ("2024-01-01","2024-09-01"),
         "F3": ("2024-09-01","2025-05-01"), "F4": ("2025-05-01","2026-01-01"), "F5": ("2026-01-01","2026-09-15")}
def fold(ts):
    for k,(a,b) in FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"): return k
    return "pre" if ts < pd.Timestamp("2022-08-18", tz="UTC") else "post"
ORDER = ["pre","F0","F1","F2","F3","F4","F5","post"]
def byfold(s): return " ".join(f"{k} {v}" for k,v in s.reindex(ORDER, fill_value=0).items())
f = pd.read_parquet("data/funding_archive.parquet"); f["symbol"] = f.symbol.astype(str); f = f.sort_values(["symbol","ts"]).reset_index(drop=True)
f["first_ts"] = f.groupby("symbol").ts.transform("min")
# trailing-day sum per row
out = []
for sym, g in f.groupby("symbol", observed=True):
    s = g.set_index("ts").rate
    out.append(s.rolling("24h").sum().rename("fund_1d").reset_index().assign(symbol=sym))
r = pd.concat(out); f = f.merge(r, on=["symbol","ts"])
f["prev_h"] = f.groupby("symbol").interval_h.shift()
ic = f[(f.prev_h.notna()) & (f.interval_h < f.prev_h)][["symbol","ts"]].rename(columns={"ts":"t_short"})
bars = None
if os.path.exists("data/candles_5m_archive.parquet"):
    import pyarrow.parquet as pq
    t = pq.read_table("data/candles_5m_archive.parquet", columns=["symbol","open_time"]).to_pandas()
    t["symbol"] = t.symbol.astype(str); t["day"] = t.open_time.dt.floor("D")
    bars = t.groupby(["symbol","day"], observed=True).size().reset_index(name="n")
for thr in (0.01, 0.02, 0.03):
    ep = []
    for sym, g in f.groupby("symbol", observed=True):
        hit = g[(g.fund_1d.abs() >= thr) & ((g.ts - g.first_ts) >= pd.Timedelta(days=30))]
        last = None
        for ts, v in zip(hit.ts, hit.fund_1d):
            if last is None or ts - last > pd.Timedelta(days=14):
                ep.append((sym, ts, v)); 
            last = ts
    e = pd.DataFrame(ep, columns=["symbol","t0","fund_1d"]); e["fold"] = e.t0.apply(fold); e["side"] = np.where(e.fund_1d < 0, "shorts_pay(buy)", "longs_pay(sell)")
    m = e.merge(ic, on="symbol", how="left"); m["near"] = (m.t_short - m.t0).abs() <= pd.Timedelta(days=7)
    e["near_shortening"] = m.groupby(["symbol","t0"]).near.any().reindex(pd.MultiIndex.from_frame(e[["symbol","t0"]])).values
    print(f"\n== |fund_1d| >= {thr*100:.0f} %/day: episodes {len(e)} names {e.symbol.nunique()} | by fold: {byfold(e.groupby('fold').size())}")
    for side, g in e.groupby("side"): print(f"   {side}: {len(g)} | {byfold(g.groupby('fold').size())} | beside a shortening within 7 d: {int(g.near_shortening.sum())}")
    f12 = e[e.fold.isin(["F1","F2"])]
    print(f"   F1+F2: {len(f12)} on {f12.symbol.nunique()} names; F3+F4: {int(e.fold.isin(['F3','F4']).sum())}; F5: {int((e.fold=='F5').sum())}")
    if bars is not None and len(f12):
        def cov(row):
            w = bars[(bars.symbol == row.symbol) & (bars.day >= row.t0.floor("D") - pd.Timedelta(days=1)) & (bars.day <= row.t0.floor("D") + pd.Timedelta(days=8))]
            return w.n.sum() / (10 * 288)
        c = f12.apply(cov, axis=1)
        print(f"   F1+F2 episodes with >= 95 % of the week's 5m bars in hand: {int((c >= 0.95).sum())} of {len(f12)}; names lacking bars: {f12[c < 0.95].symbol.nunique()}")
    if thr == 0.02:
        print("   per month (F1+F2):", f12.groupby(f12.t0.dt.strftime("%Y-%m")).size().to_dict())
        print("   |fund_1d| quantiles at t0 (%/day):", (e.fund_1d.abs()*100).quantile([.1,.5,.9]).round(2).to_dict())
        print("   sample:"); print(e.sample(min(10,len(e)), random_state=0).to_string())
