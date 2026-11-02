# BY brainstorm count: catalog titles on disk by rule-event pattern and fold of release; the F1+F2 bar population. No price read.
import glob, json, re, collections, pandas as pd
FOLDS = {"F0": ("2022-08-18","2023-05-01"), "F1": ("2023-05-01","2024-01-01"), "F2": ("2024-01-01","2024-09-01"),
         "F3": ("2024-09-01","2025-05-01"), "F4": ("2025-05-01","2026-01-01"), "F5": ("2026-01-01","2026-09-15")}
def fold(ts):
    for k,(a,b) in FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"): return k
    return "pre" if ts < pd.Timestamp("2022-08-18", tz="UTC") else "post"
rows = {}
for p in glob.glob("data/raw/external/binance_cms/list_*.json"):
    cat = p.split("list_")[1].split("_")[0]
    for a in json.load(open(p)):
        rows[(cat, a["id"])] = (cat, a["id"], a.get("code"), a["title"], pd.Timestamp(a["releaseDate"], unit="ms", tz="UTC"))
df = pd.DataFrame(rows.values(), columns=["cat","id","code","title","release"]); df["fold"] = df.release.apply(fold)
print("articles", len(df), df.groupby("cat").size().to_dict(), "release", df.release.min().date(), "->", df.release.max().date())
pats = {
 "levtier": r"Leverage.{0,10}Margin Tier|Margin Tier|Leverage Tier|Maximum Leverage",
 "price_index": r"Price Index|Index Component|Index Composition|Index Price",
 "funding_rate_any": r"Funding Rate",
 "funding_cap": r"Funding Rate (Cap|Floor|Limit)|Cap/Floor|Cap and Floor",
 "settle_freq": r"Settlement Frequency",
 "position_limit": r"Position Limit|Open Interest Limit|Max.{0,10}Position",
 "tick_size": r"Tick Size|Price Precision|Minimum Order|Order Size",
 "contract_rename": r"Contract Multiplier|Rename|Renaming|Ticker Change|Token Swap|Redenomination|Will Update the .* Contract",
 "delist_any": r"Delist",
 "adl_insurance": r"ADL|Auto-Deleverag|Insurance Fund",
 "maint_margin": r"Maintenance Margin",
 "trading_rules": r"Trading Rules|Risk Control|Price Limit|Price Protection",
 "launch_any": r"Will Launch|Launches",
 "multi_asset": r"Multi-Assets|Multi Assets",
 "trading_bots_copy": r"Copy Trading|Trading Bot|Grid",
 "promo_competition": r"Trading Competition|Tournament|Launchpool|Launchpad|Airdrop|Alpha",
 "seed_monitor": r"Seed Tag|Monitoring Tag",
 "unification": r"Unified|Portfolio Margin|Cross Margin",
 "spot_margin": r"Margin.{0,30}(Add|Remove|Delist)|Isolated Margin",
}
for k, pat in pats.items():
    m = df[df.title.str.contains(pat, case=False, regex=True)]
    byf = m.groupby("fold").size().reindex(["pre","F0","F1","F2","F3","F4","F5","post"], fill_value=0)
    mult = m.title.str.contains("Multiple", case=False).sum()
    print(f"\n== {k}: {len(m)} (Multiple {mult}) cat {m.groupby('cat').size().to_dict()} | " + " ".join(f"{a} {b}" for a,b in byf.items()))
    for t in m.title.sample(min(6,len(m)), random_state=1): print("   ", t[:140])
# the F1+F2 bar population: symbols with 5m bars covering 2023-05 .. 2024-08
try:
    import pyarrow.parquet as pq, os
    p = "data/candles_5m_archive.parquet" if os.path.exists("data/candles_5m_archive.parquet") else None
    if p is None:
        cands = glob.glob("data/candles_5m_archive*"); print("\ncandles_5m_archive paths:", cands[:5])
    else:
        t = pq.read_table(p, columns=["symbol","open_time"]).to_pandas()
        t["m"] = t.open_time.dt.to_period("M")
        f12 = t[(t.open_time >= "2023-05-01") & (t.open_time < "2024-09-01")].groupby("symbol").m.nunique()
        print("\nF1+F2 months per symbol in candles_5m_archive: symbols", len(f12), "with all 16 months", (f12==16).sum(), ">=8", (f12>=8).sum())
except Exception as e: print("bars count:", e)
fa = pd.read_parquet("data/funding_archive.parquet", columns=["symbol","ts"])
f12 = fa[(fa.ts >= "2023-05-01") & (fa.ts < "2024-09-01")].groupby("symbol").ts.count()
print("funding_archive symbols with F1+F2 rows", len(f12))
