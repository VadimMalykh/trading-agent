# BU brainstorm probe: (1) funding-interval changes per name from funding_archive (data in hand, no price read);
# (2) grep the raw Binance CMS lists already on disk for futures rule announcements; (3) one catalog probe.
import glob, json, re, sys, collections
import pandas as pd
FOLDS = {"F0": ("2022-08-18","2023-05-01"), "F1": ("2023-05-01","2024-01-01"), "F2": ("2024-01-01","2024-09-01"),
         "F3": ("2024-09-01","2025-05-01"), "F4": ("2025-05-01","2026-01-01"), "F5": ("2026-01-01","2026-09-15")}
def fold(ts):
    for k,(a,b) in FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"): return k
    return "pre" if ts < pd.Timestamp("2022-08-18", tz="UTC") else "post"
f = pd.read_parquet("data/funding_archive.parquet")
print("funding_archive rows", len(f), "symbols", f.symbol.nunique(), "cols", list(f.columns), "ts", f.ts.min(), "->", f.ts.max())
f = f.sort_values(["symbol","ts"])
f["prev"] = f.groupby("symbol").interval_h.shift()
f["first_ts"] = f.groupby("symbol").ts.transform("min")
ch = f[(f.prev.notna()) & (f.prev != f.interval_h)].copy()
ch["age_d"] = (ch.ts - ch.first_ts).dt.days
ch["fold"] = ch.ts.apply(fold)
ch["dir"] = ch.apply(lambda r: "shorter" if r.interval_h < r.prev else "longer", axis=1)
# the funding over the trailing day before the change (sign of the crowded side) and the share of settlements at a cap in the trailing week
def trail(r):
    g = f[(f.symbol==r.symbol) & (f.ts < r.ts) & (f.ts >= r.ts - pd.Timedelta(days=7))]
    d = g[g.ts >= r.ts - pd.Timedelta(days=1)]
    cap = (g.rate.abs() >= 0.0074).mean() if len(g) else float("nan")
    return pd.Series({"rate_1d": d.rate.sum() if len(d) else float("nan"), "n_1d": len(d), "cap_share_7d": cap, "mean_rate_7d": g.rate.mean() if len(g) else float("nan")})
ch = pd.concat([ch, ch.apply(trail, axis=1)], axis=1)
print("\n== interval changes (all):", len(ch), " by prev->new:"); print(ch.groupby(["prev","interval_h"]).size().to_string())
print("\n== by fold x dir (age >= 30 d):"); e = ch[ch.age_d >= 30]; print(e.groupby(["fold","dir"]).size().unstack(fill_value=0).to_string())
print("\n== by fold x dir, sign of trailing-day funding (shorter only, age>=30):")
s = e[e.dir=="shorter"].copy(); s["sign"] = s.rate_1d.apply(lambda x: "pos" if x > 0 else ("neg" if x < 0 else "zero"))
print(s.groupby(["fold","sign"]).size().unstack(fill_value=0).to_string())
print("\n== shorter: |trailing-day funding| quantiles (per day, in %):"); print((s.rate_1d.abs()*100).describe(percentiles=[.1,.25,.5,.75,.9]).to_string())
print("\n== shorter: cap_share_7d quantiles:"); print(s.cap_share_7d.describe(percentiles=[.1,.25,.5,.75,.9]).to_string())
print("\n== distinct symbols with a shorter change, by fold:"); print(s.groupby("fold").symbol.nunique().to_string())
print("\n== changes per calendar month (shorter):"); print(s.groupby(s.ts.dt.strftime("%Y-%m")).size().to_string())
print("\n== the twelve's changes:")
tw = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOGEUSDT","ZECUSDT","1000PEPEUSDT","WLDUSDT","HYPEUSDT"]
print(ch[ch.symbol.isin(tw)][["symbol","ts","prev","interval_h","rate_1d"]].to_string())
print("\n== sample of 15 shorter changes:"); print(s.sample(min(15,len(s)), random_state=0)[["symbol","ts","prev","interval_h","age_d","rate_1d","cap_share_7d"]].to_string())
# also: how many symbols ever change at all, and the per-symbol number of changes
print("\n== changes per symbol (count of symbols with k changes):"); print(ch.groupby("symbol").size().value_counts().sort_index().to_string())
ch.to_csv("output/bu_probe_interval_changes.csv", index=False)
# (2) CMS raw lists on disk
titles = []
for p in glob.glob("data/raw/external/binance_cms/list_*.json"):
    try:
        j = json.load(open(p))
        for c in j["data"]["catalogs"]:
            for a in c.get("articles", []): titles.append((c.get("catalogId"), a["title"], a.get("releaseDate")))
    except Exception as ex: print("skip", p, ex)
tt = pd.DataFrame(titles, columns=["catalog","title","release"]).drop_duplicates()
print("\n== CMS titles on disk:", len(tt), "by catalog:", tt.catalog.value_counts().to_dict())
for pat in ["Leverage", "Margin Tier", "Funding Rate", "Settlement Frequency", "Funding Rate Cap", "Tick Size", "Contract Multiplier", "Seed Tag", "Delist", "Will List", "Alpha", "Pre-Market", "Position Limit"]:
    m = tt[tt.title.str.contains(pat, case=False, regex=False)]
    print(f"  {pat!r}: {len(m)}  " + " | ".join(m.title.head(3).str.slice(0,90)))
