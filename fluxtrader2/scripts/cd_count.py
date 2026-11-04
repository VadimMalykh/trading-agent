"""Decision CD's seed counts (2026-11-04) — the brainstorm CC1 asked for, BM's method: every candidate KIND of per-name information
grepped in the record (0 hits) and then COUNTED before it is named. Runs on the work VM (api.llama.fi and the Wayback CDX are reachable
there; the frozen member lists and the archive's first-month table are on disk). No bar, no price, no fold read.

    cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/cd_count.py > output/by_probe/cd_count.md

Counts: (1) DefiLlama's protocol FEES / REVENUE daily histories joined to the 322 bases — the breadth per F1+F2 / F3+F4 block;
(2) DefiLlama's TVL histories, the same join; (3) DefiLlama's HACKS as a per-name event on bases with a perpetual ≥ 30 days old, by fold;
(4) DefiLlama's RAISES as a per-name event, by fold; (5) the Wayback CDX's snapshots of the fees endpoints (can a rewrite be checked?);
(6) the coin-margined liquidationSnapshot's names against the member blocks (the archive probe's list, pasted).
"""
import json, re, sys, time, urllib.request, urllib.parse
import pandas as pd

FOLDS = {"F0": ("2022-08-18", "2023-05-01"), "F1": ("2023-05-01", "2024-01-01"), "F2": ("2024-01-01", "2024-09-01"),
         "F3": ("2024-09-01", "2025-05-01"), "F4": ("2025-05-01", "2026-01-01"), "F5": ("2026-01-01", "2026-09-15")}
ORDER = ["pre", "F0", "F1", "F2", "F3", "F4", "F5", "post"]


def fold(ts):
    for k, (a, b) in FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"):
            return k
    return "pre" if ts < pd.Timestamp("2022-08-18", tz="UTC") else "post"


def byfold(s):
    return " ".join(f"{k} {v}" for k, v in s.reindex(ORDER, fill_value=0).items())


def get(url, tries=3, timeout=60):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ft2-count/1"}), timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa
            err = e
            time.sleep(2 + 3 * i)
    print(f"<!-- GET failed {url}: {err} -->")
    return None


def base_of(sym):
    b = sym.replace("USDT", "")
    return re.sub(r"^1000+", "", b)


t_start = time.time()
# --- the universe: the archive's perpetuals and their first month; the member blocks
um = pd.read_csv("data/raw/external/binance/um_first_month.csv")
symcol = [c for c in um.columns if "sym" in c.lower()][0]
mcol = [c for c in um.columns if c != symcol][0]
um["base"] = um[symcol].map(base_of)
um["first_month"] = pd.to_datetime(um[mcol].astype(str).str[:7] + "-01", utc=True)
bases = sorted(set(um.base))
m12 = pd.read_csv("ft2/screen_members.csv"); m34 = pd.read_csv("ft2/screen_members_f34.csv")
for m in (m12, m34):
    m["base"] = m.symbol.map(base_of); m["block"] = pd.to_datetime(m.block, utc=True)
print(f"# Decision CD's seed counts (2026-11-04; `scripts/cd_count.py` on the work VM; no bar, no price, no fold read)\n")
print(f"The universe: {len(bases)} bases of {len(um)} USDT perpetuals (`um_first_month.csv`); member blocks F1+F2 {m12.block.nunique()} "
      f"({m12.base.nunique()} bases), F3+F4 {m34.block.nunique()} ({m34.base.nunique()} bases).\n")

# --- (1) DefiLlama protocols and the symbol join
prots = get("https://api.llama.fi/protocols") or []
P = pd.DataFrame(prots)
P["sym"] = P.get("symbol", pd.Series(dtype=str)).fillna("-").astype(str).str.upper()
P = P[P.sym.isin(bases)]
print(f"## (1) DefiLlama protocols joined on the token symbol: {len(P)} protocols on {P.sym.nunique()} of {len(bases)} bases "
      f"(categories: " + ", ".join(f"{k} {v}" for k, v in P.category.value_counts().head(12).items()) + ")\n")
# fees overview
fo = get("https://api.llama.fi/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyFees") or {}
F = pd.DataFrame(fo.get("protocols", []))
if len(F):
    F["slugm"] = F.get("slug", F.get("module", pd.Series(dtype=str))).astype(str)
    P2 = P.merge(F[["slugm", "name", "category", "total24h", "totalAllTime"]].rename(columns={"name": "fname", "category": "fcat"}),
                 left_on="slug", right_on="slugm", how="inner") if "slug" in P.columns else pd.DataFrame()
    # also join by name where slug differs
    byname = P[~P.slug.isin(P2.slug)].merge(F[["slugm", "name"]].rename(columns={"name": "fname"}), left_on="name", right_on="fname", how="inner") \
        if "slug" in P.columns else pd.DataFrame()
    FP = pd.concat([P2, byname], ignore_index=True)
    print(f"Fee adapters (`/overview/fees`): {len(F)} protocols; joined to our bases: {len(FP)} protocols on {FP.sym.nunique()} bases "
          f"(by slug {len(P2)}, by name {len(byname)}).\n")
    # per matched base, the fees history's first day and daily coverage per fold; revenue beside
    rows = []
    for r in FP.drop_duplicates("sym").itertuples():
        for dt in ("dailyFees", "dailyRevenue"):
            s = get(f"https://api.llama.fi/summary/fees/{r.slugm}?dataType={dt}", timeout=90)
            ch = (s or {}).get("totalDataChart") or []
            d = pd.DataFrame(ch, columns=["ts", "v"]) if ch else pd.DataFrame(columns=["ts", "v"])
            d["ts"] = pd.to_datetime(d.ts, unit="s", utc=True)
            d = d[d.v.notna() & (d.v > 0)]
            rows.append({"base": r.sym, "slug": r.slugm, "dtype": dt, "first": d.ts.min() if len(d) else pd.NaT,
                         "days": len(d), **{f: int(d.ts.map(fold).eq(f).sum()) for f in ORDER}})
            time.sleep(0.2)
    H = pd.DataFrame(rows)
    H.to_csv("output/by_probe/cd_fees_hist.csv", index=False)
    for dt in ("dailyFees", "dailyRevenue"):
        h = H[(H.dtype == dt) & (H.days > 0)]
        print(f"**{dt}** histories with a positive day: {len(h)} bases; first day q10 / q50 / q90: "
              + " / ".join(str(x.date()) for x in h["first"].quantile([.1, .5, .9]) ) + f"; days per fold (sum): "
              + byfold(h[ORDER].sum()) + ".")
        # breadth per member block: members with ≥ 90 % of the block's trailing 30 days covered — approximated: history's first ≤ block − 30 d
        for lab, m in (("F1+F2", m12), ("F3+F4", m34)):
            cov = []
            for b, g in m.groupby("block"):
                hb = h[h.base.isin(g.base)]
                cov.append(int((hb["first"] <= b - pd.Timedelta(days=30)).sum()))
            print(f"  members a block with a {dt} history ≥ 30 days old at the block's start, {lab}: min {min(cov)} / median {pd.Series(cov).median():.0f} / max {max(cov)} of {m.groupby('block').size().median():.0f}.")
    print()
else:
    print("fees overview: no data\n")

# --- (2) TVL histories for the joined protocols (one call per base's largest protocol)
rows = []
if "slug" in P.columns:
    top = P.sort_values("tvl", ascending=False).drop_duplicates("sym")
    for r in top.itertuples():
        s = get(f"https://api.llama.fi/protocol/{r.slug}", timeout=120)
        tv = (s or {}).get("tvl") or []
        d = pd.DataFrame(tv)
        if len(d):
            d["ts"] = pd.to_datetime(d.date, unit="s", utc=True)
            d = d[d.totalLiquidityUSD > 0]
        rows.append({"base": r.sym, "slug": r.slug, "first": d.ts.min() if len(d) else pd.NaT, "days": len(d),
                     **{f: int(d.ts.map(fold).eq(f).sum()) if len(d) else 0 for f in ORDER}})
        time.sleep(0.2)
T = pd.DataFrame(rows); T.to_csv("output/by_probe/cd_tvl_hist.csv", index=False)
t = T[T.days > 0] if len(T) else T
print(f"## (2) TVL histories (`/protocol/<slug>`, the base's largest protocol): {len(t)} bases with a positive day; first day q10 / q50 / q90: "
      + (" / ".join(str(x.date()) for x in t["first"].quantile([.1, .5, .9])) if len(t) else "—") + ".")
for lab, m in (("F1+F2", m12), ("F3+F4", m34)):
    cov = [int((t[t.base.isin(g.base)]["first"] <= b - pd.Timedelta(days=30)).sum()) for b, g in m.groupby("block")]
    print(f"  members a block with a TVL history ≥ 30 days old, {lab}: min {min(cov)} / median {pd.Series(cov).median():.0f} / max {max(cov)}.")
print()

# --- (3) hacks as a per-name event
hk = get("https://api.llama.fi/hacks") or []
Hk = pd.DataFrame(hk)
if len(Hk):
    Hk["ts"] = pd.to_datetime(Hk.date, unit="s", utc=True)
    nm = {str(n).lower(): s for n, s in zip(P.name, P.sym)} if "name" in P.columns else {}
    Hk["base"] = Hk.name.astype(str).str.lower().map(nm)
    # a second join: the hack's name containing the base
    for i, r in Hk[Hk.base.isna()].iterrows():
        for b in bases:
            if len(b) >= 3 and re.search(rf"\b{re.escape(b.lower())}\b", str(r["name"]).lower()):
                Hk.at[i, "base"] = b; break
    Hk = Hk.merge(um.drop_duplicates("base")[["base", "first_month"]], on="base", how="left")
    on = Hk[Hk.base.notna()].copy()
    on["age_ok"] = on.ts >= on.first_month + pd.Timedelta(days=61)   # the first month is an upper bound of the start: ≥ 30 d after its END
    on["fold"] = on.ts.map(fold)
    print(f"## (3) Hacks (`/hacks`): {len(Hk)} events; on a base of ours {len(on)} ({on.base.nunique()} bases); with the perpetual ≥ 30 days old: "
          f"{int(on.age_ok.sum())} — by fold " + byfold(on[on.age_ok].groupby('fold').size()) + "; amount q50 "
          f"{on[on.age_ok].amount.median() / 1e6:.1f} M USD; stamp resolution: a DATE (the hour is not in the file).")
    print("  " + "; ".join(f"{r.base} {r.ts.date()} {r.fold} {r.amount / 1e6:.0f}M" for r in on[on.age_ok].sort_values("ts").itertuples()) + "\n")
    on.to_csv("output/by_probe/cd_hacks.csv", index=False)

# --- (4) raises as a per-name event
rz = get("https://api.llama.fi/raises") or {}
R = pd.DataFrame(rz.get("raises", []))
if len(R):
    R["ts"] = pd.to_datetime(R.date, unit="s", utc=True)
    nm = {str(n).lower(): s for n, s in zip(P.name, P.sym)} if "name" in P.columns else {}
    R["base"] = R.name.astype(str).str.lower().map(nm)
    R = R.merge(um.drop_duplicates("base")[["base", "first_month"]], on="base", how="left")
    on = R[R.base.notna()].copy(); on["age_ok"] = on.ts >= on.first_month + pd.Timedelta(days=61); on["fold"] = on.ts.map(fold)
    print(f"## (4) Raises (`/raises`): {len(R)} rounds; on a base of ours {len(on)} ({on.base.nunique()} bases); the perpetual ≥ 30 days old: "
          f"{int(on.age_ok.sum())} — by fold " + byfold(on[on.age_ok].groupby('fold').size()) + "; stamp resolution: a DATE.\n")

# --- (5) can a rewrite be checked? Wayback CDX snapshots of the fees endpoints
for u in ("api.llama.fi/overview/fees*", "api.llama.fi/summary/fees/*", "api.llama.fi/protocols", "api.llama.fi/hacks", "api.llama.fi/protocol/*"):
    c = None
    try:
        q = "https://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(u) + "&output=json&fl=timestamp,original&filter=statuscode:200&limit=5000"
        with urllib.request.urlopen(q, timeout=120) as r:
            c = json.loads(r.read().decode())
    except Exception as e:  # noqa
        print(f"## (5) Wayback CDX `{u}`: unreachable ({e})")
        continue
    rows = c[1:] if c else []
    ts = sorted(r[0][:6] for r in rows)
    print(f"## (5) Wayback CDX `{u}`: {len(rows)} snapshots" + (f", {ts[0]} → {ts[-1]}, months " + ", ".join(sorted(set(ts)))[:400] if rows else ""))
print()

# --- (6) the coin-margined liquidationSnapshot's names (the archive probe 2026-11-04: cm/daily/liquidationSnapshot, BTCUSD_PERP 2023-06-25 → 2024-10-14)
CM = "AAVE ADA ALGO APE APT ATOM AVAX AXS BCH BNB BTC CHZ DOGE DOGS DOT EGLD ENS EOS ETC ETH FIL FTM GMT ICX KNC LINK LTC MANA MATIC NEAR OP ROSE RUNE SAND SOL SUI THETA TRX UNI WIF WLD XLM XMR XRP XTZ".split()
for lab, m in (("F1+F2", m12), ("F3+F4", m34)):
    per = m[m.base.isin(CM)].groupby("block").size()
    print(f"## (6) coin-margined perpetuals with a liquidation file: {len(CM)} names; of them members a block, {lab}: "
          f"min {per.min()} / median {per.median():.0f} / max {per.max()} of {m.groupby('block').size().median():.0f}; the file's span 2023-06-25 → 2024-10-14 (F1, F2 and 6 weeks of F3).")
print(f"\n(run {time.time() - t_start:.0f} s)")
