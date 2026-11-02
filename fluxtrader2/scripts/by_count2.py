# BY brainstorm count 2: (a) the funding CAP level change per name from funding_archive (a plateau transition), by fold;
# (b) the leverage-tier titles: single-contract vs Multiple, bundled with a settlement-frequency change or not, cut vs raise words;
# (c) the "Capped Funding Rate" titles. Counts only; no price read.
import glob, json, re, collections, pandas as pd, numpy as np
FOLDS = {"F0": ("2022-08-18","2023-05-01"), "F1": ("2023-05-01","2024-01-01"), "F2": ("2024-01-01","2024-09-01"),
         "F3": ("2024-09-01","2025-05-01"), "F4": ("2025-05-01","2026-01-01"), "F5": ("2026-01-01","2026-09-15")}
def fold(ts):
    for k,(a,b) in FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"): return k
    return "pre" if ts < pd.Timestamp("2022-08-18", tz="UTC") else "post"
ORDER = ["pre","F0","F1","F2","F3","F4","F5","post"]
def byfold(s): return " ".join(f"{k} {v}" for k,v in s.reindex(ORDER, fill_value=0).items())
# (a) cap plateaus: a settlement whose |rate| equals the previous settlement's |rate| to 1e-9 and >= 0.3 %/settlement is "pinned";
# the pinned level per run; a CAP CHANGE = a pinned run at a level different from the name's previous pinned run (within 14 days, same sign)
f = pd.read_parquet("data/funding_archive.parquet"); f["symbol"] = f.symbol.astype(str); f = f.sort_values(["symbol","ts"])
f["first_ts"] = f.groupby("symbol").ts.transform("min")
f["a"] = f.rate.abs().round(9)
f["pin"] = (f.a >= 0.003) & (f.a == f.groupby("symbol").a.shift())
runs = []
for sym, g in f[f.pin].groupby("symbol", observed=True):
    if g.empty: continue
    lvl = None; start = None; last = None
    for ts, a, s, first in zip(g.ts, g.a, np.sign(g.rate), g.first_ts):
        if lvl is None or a != lvl or (last is not None and ts - last > pd.Timedelta(days=14)):
            if lvl is not None: runs.append((sym, lvl, start, last, first))
            lvl, start = a, ts
        last = ts
    runs.append((sym, lvl, start, last, first))
r = pd.DataFrame(runs, columns=["symbol","level","start","end","first_ts"]).sort_values(["symbol","start"])
r["prev_level"] = r.groupby("symbol")["level"].shift(); r["prev_end"] = r.groupby("symbol")["end"].shift()
ch = r[(r.prev_level.notna()) & (r.level != r.prev_level) & ((r.start - r.prev_end) <= pd.Timedelta(days=14))].copy()
ch["age_d"] = (ch.start - ch.first_ts).dt.days; ch["fold"] = ch.start.apply(fold); ch["dir"] = np.where(ch.level > ch.prev_level, "raise", "cut")
ch = ch[ch.age_d >= 30]
print("(a) pinned runs", len(r), "names", r.symbol.nunique(), "| cap-level changes within 14 d, age>=30:", len(ch), "names", ch.symbol.nunique())
print("    by fold:", byfold(ch.groupby("fold").size()), "| raise", (ch.dir=="raise").sum(), "cut", (ch.dir=="cut").sum())
print("    levels (prev -> new) top:", ch.groupby(["prev_level","level"]).size().sort_values(ascending=False).head(8).to_dict())
# coincidence with an interval change of the same name within +-7 days
f["prev_h"] = f.groupby("symbol").interval_h.shift()
ic = f[(f.prev_h.notna()) & (f.prev_h != f.interval_h)][["symbol","ts"]]
def near(row):
    g = ic[ic.symbol == row.symbol]; return bool(((g.ts - row.start).abs() <= pd.Timedelta(days=7)).any())
ch["near_interval_change"] = ch.apply(near, axis=1)
print("    with an interval change of the same name within 7 d:", int(ch.near_interval_change.sum()), "of", len(ch), "| by fold (not near):", byfold(ch[~ch.near_interval_change].groupby("fold").size()))
print("    sample:"); print(ch.sample(min(10,len(ch)), random_state=0)[["symbol","start","prev_level","level","age_d","fold","near_interval_change"]].to_string())
# (b) leverage-tier titles
rows = {}
for p in glob.glob("data/raw/external/binance_cms/list_*.json"):
    cat = p.split("list_")[1].split("_")[0]
    for a in json.load(open(p)): rows[(cat, a["id"])] = (cat, a["id"], a.get("code"), a["title"], pd.Timestamp(a["releaseDate"], unit="ms", tz="UTC"))
df = pd.DataFrame(rows.values(), columns=["cat","id","code","title","release"]); df["fold"] = df.release.apply(fold)
lev = df[df.title.str.contains(r"Leverage.{0,10}Margin Tier|Margin Tier|Leverage Tier|Maximum Leverage", case=False, regex=True)].copy()
lev["multiple"] = lev.title.str.contains("Multiple", case=False)
lev["bundled_freq"] = lev.title.str.contains("Settlement Frequency|Funding Rate", case=False, regex=True)
lev["delist"] = lev.title.str.contains("Delist", case=False)
lev["coinm"] = lev.title.str.contains("Coin-Margined|COIN-M", case=False, regex=True)
lev["sym"] = lev.title.str.extract(r"USDⓈ-M\s+([0-9A-Z]+USDT)\b", expand=False)
lev["raise_word"] = lev.title.str.contains("Increas|Rais|Higher|Up to", case=False, regex=True)
lev["cut_word"] = lev.title.str.contains("Reduc|Lower|Decreas|Cut", case=False, regex=True)
print("\n(b) leverage-tier titles", len(lev), "| Multiple:", byfold(lev[lev.multiple].groupby("fold").size()))
single = lev[~lev.multiple & ~lev.coinm]
print("    single (not coin-m):", len(single), "| bundled with a freq/funding change:", byfold(single[single.bundled_freq].groupby("fold").size()))
print("    single, NOT bundled, not a delisting:", byfold(single[~single.bundled_freq & ~single.delist].groupby("fold").size()), "| with a USDT symbol parsed:", int(single[~single.bundled_freq & ~single.delist].sym.notna().sum()))
print("    raise words", int(lev.raise_word.sum()), "cut words", int(lev.cut_word.sum()), "(titles rarely say the direction)")
print("    sample single not bundled:"); 
for t in single[~single.bundled_freq & ~single.delist].title.sample(min(8,len(single)), random_state=2): print("     ", t[:150])
# (c) capped funding titles
cap = df[df.title.str.contains(r"Capped Funding|Funding Rate Cap|Cap of Funding|Funding Rate Multiplier", case=False, regex=True)]
print("\n(c) capped-funding titles", len(cap), "|", byfold(cap.groupby("fold").size()), "| also naming settlement frequency:", int(cap.title.str.contains("Settlement Frequency", case=False).sum()))
for t in cap.title.sample(min(6,len(cap)), random_state=0): print("     ", t[:150])
