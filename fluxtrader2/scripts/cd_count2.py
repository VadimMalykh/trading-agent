"""Decision CD's seed count 2 (2026-11-04): Binance's "Maintenance Updates" catalog (157; 614 titles, fetched from the work VM the same day
to data/raw/external/binance_cms/list_157_20261104.json) — the scheduled NETWORK UPGRADE / HARD FORK of a name as a per-name event:
titles by fold, the perpetual ≥ 30 days old, distinct bases, the notice's lead, members at the notice, and three detail bodies read for the
upgrade's stated time. Counts only; no bar, no price, no fold read.

    cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/cd_count2.py >> output/by_probe/cd_count.md
"""
import json, re, time
import pandas as pd
from ft2.events import _get, CMS_DETAIL, RAW_BN

F = {"F0": ("2022-08-18", "2023-05-01"), "F1": ("2023-05-01", "2024-01-01"), "F2": ("2024-01-01", "2024-09-01"),
     "F3": ("2024-09-01", "2025-05-01"), "F4": ("2025-05-01", "2026-01-01"), "F5": ("2026-01-01", "2026-09-15")}
O = ["pre", "F0", "F1", "F2", "F3", "F4", "F5", "post"]


def fold(t):
    for k, (a, b) in F.items():
        if pd.Timestamp(a, tz="UTC") <= t < pd.Timestamp(b, tz="UTC"):
            return k
    return "pre" if t < pd.Timestamp("2022-08-18", tz="UTC") else "post"


def byfold(s):
    return " ".join(f"{f} {n}" for f, n in s.reindex(O, fill_value=0).items())


def base_of(s):
    return re.sub(r"^1000+", "", s.replace("USDT", ""))


arts = json.loads((RAW_BN / "list_157_20261104.json").read_text())
e = pd.DataFrame(arts); e["release"] = pd.to_datetime(e.releaseDate, unit="ms", utc=True)
um = pd.read_csv("data/raw/external/binance/um_first_month.csv"); um["base"] = um.symbol.map(base_of)
um["fm"] = pd.to_datetime(um.first_month + "-01", utc=True)
first = um.groupby("base").fm.min()
e["tick"] = e.title.str.extract(r"\(([A-Z0-9]{2,10})\)")[0]
u = e[e.title.str.contains(r"upgrade|hard fork|hardfork", case=False, regex=True) & e.tick.isin(first.index)].copy()
u["fold"] = u.release.map(fold)
u["date_in_title"] = pd.to_datetime(u.title.str.extract(r"(\d{4}-\d{2}-\d{2})")[0], utc=True, errors="coerce")
u["lead_d"] = (u.date_in_title - u.release).dt.total_seconds() / 86400
u["age_ok"] = u.release >= u.tick.map(first) + pd.Timedelta(days=61)   # the first month is an upper bound: ≥ 30 d after its end
print("\n## (7) The scheduled NETWORK UPGRADE / HARD FORK per name (catalog 157 'Maintenance Updates', 614 titles 2022-02-15 → 2026-10-29)")
print(f"Upgrade / hard-fork titles with a ticker of ours: {len(u)}; the perpetual ≥ 30 days old at the notice: {int(u.age_ok.sum())} — "
      + byfold(u[u.age_ok].groupby("fold").size()) + ".")
ok = u[u.age_ok]
print(f"Distinct bases: F1+F2 {ok[ok.fold.isin(['F1', 'F2'])].tick.nunique()}, F3+F4 {ok[ok.fold.isin(['F3', 'F4'])].tick.nunique()}, F5 {ok[ok.fold == 'F5'].tick.nunique()}; "
      f"a date in the title: {int(u.date_in_title.notna().sum())} of {len(u)}; the notice's lead (release → the title's date), days, q10 / q50 / q90: "
      + " / ".join(f"{x:.1f}" for x in u.lead_d.dropna().quantile([.1, .5, .9])) + ".")
print("Most frequent bases: " + ", ".join(f"{k} {v}" for k, v in ok.tick.value_counts().head(15).items()) + ".")
for lab, path in (("F1+F2", "ft2/screen_members.csv"), ("F3+F4", "ft2/screen_members_f34.csv")):
    m = pd.read_csv(path); m["base"] = m.symbol.map(base_of); m["block"] = pd.to_datetime(m.block, utc=True)
    blocks = sorted(m.block.unique())
    uu = ok[ok.fold.isin(lab.split("+"))]
    n_mem = 0
    for r in uu.itertuples():
        b = [x for x in blocks if x <= r.release]
        if b and ((m.block == b[-1]) & (m.base == r.tick)).any():
            n_mem += 1
    print(f"{lab}: {len(uu)} events, the name a member of the block at the notice: {n_mem}.")
ok.sort_values("release")[["code", "release", "fold", "tick", "title", "date_in_title", "lead_d"]].to_csv("output/by_probe/cd_upgrades.csv", index=False)
print("Three detail bodies (the newest), the upgrade's stated time:")
for code in ok.sort_values("release", ascending=False).code.head(3):
    d = json.loads(_get(CMS_DETAIL.format(code=code)))["data"]
    body = json.dumps(d)
    hit = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})? ?\(?UTC\)?|block height[^\"]{0,50}|epoch[^\"]{0,40}", body, flags=re.I)
    print(f"  {d.get('title', '')[:90]} | {hit[:4]}")
    time.sleep(0.5)
