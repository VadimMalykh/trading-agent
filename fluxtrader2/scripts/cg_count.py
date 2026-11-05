"""Decision CG's seed counts (2026-11-06) — the brainstorm CF1 asked for, BM's method with the two rules of decision CF: every candidate
KIND grepped in the record first (0 hits, or the hit named) and then COUNTED before it is named; the COST BAR of the names a kind would
read taken from their own cost rows on the fold to be read (rule (a)). Runs on the work VM (the CMS and hub.snapshot.org are reachable
there; `cost_daily_wide.parquet`, the frozen lists and the catalog lists are on disk). No bar after an event is joined to a label, no
price read, no fold read. `python -u`; every section writes its CSV before the next starts (0v (ii)).

    cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python -u scripts/cg_count.py > output/by_probe/cg_count.md

Counts: (1) rule (a) applied to the record — the names' own doubled taker round trip B_i = 4 × (5 + taker_leg) per (name, day) on
`costwide`'s proxy, by fold: members against non-members, the share of names under 60 / 120 bps; the frozen event lists' names on their
own t0 day (upgrades f12 / f34 / f5, krlistings f12 / f34) — what any per-name event rule must clear on each fold; (2) the CMS catalog 93
"Latest Activities" (3,219 titles, never fetched before) by family, the ticker's perpetual ≥ 30 days old at the release, by fold;
(3) the catalog-48 lists on disk — the SPOT listing of a name whose perpetual is ≥ 30 days old (the §9 #8 audit's "7 spot listings" on
F1+F2, re-counted on every fold); (4) governance votes — Snapshot's spaces joined to our bases by their voting-token symbol, the
proposals' END stamps (known at the proposal's creation, to the second) by fold on names ≥ 30 days old.
"""
import glob
import json
import re
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

FOLDS = {"F0": ("2022-08-18", "2023-05-01"), "F1": ("2023-05-01", "2024-01-01"), "F2": ("2024-01-01", "2024-09-01"),
         "F3": ("2024-09-01", "2025-05-01"), "F4": ("2025-05-01", "2026-01-01"), "F5": ("2026-01-01", "2026-09-15")}
ORDER = ["pre", "F0", "F1", "F2", "F3", "F4", "F5", "post"]
OUT = "output/by_probe"
CMS_LIST = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId={c}&pageNo={p}&pageSize=50"
SNAP = "https://hub.snapshot.org/graphql"
UA = {"User-Agent": "Mozilla/5.0 (ft2-count/1)", "Accept": "application/json", "Content-Type": "application/json"}
PERP_AGE = 30
TAKER_BPS, NOTIONAL = 5.0, 10_000
t_start = time.time()


def say(*a):
    print(*a, flush=True)


def fold(ts):
    for k, (a, b) in FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"):
            return k
    return "pre" if ts < pd.Timestamp("2022-08-18", tz="UTC") else "post"


def byfold(s):
    s = pd.Series(s) if not isinstance(s, pd.Series) else s
    return " ".join(f"{k} {int(v)}" for k, v in s.reindex(ORDER, fill_value=0).items())


def http(url, body=None, tries=4, timeout=90):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=(json.dumps(body).encode() if body is not None else None), headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            err = e
            w = 5 + 20 * i + (120 if "429" in str(e) else 0)
            say(f"<!-- {url[:80]} attempt {i + 1}: {e!r}; wait {w}s -->")
            time.sleep(w)
    say(f"<!-- GET failed {url}: {err!r} -->")
    return None


def base_of(sym):
    return re.sub(r"^1000+", "", str(sym).replace("USDT", ""))


# --- the universe: the archive's perpetuals, their first month; the member blocks
um = pd.read_csv("data/raw/external/binance/um_first_month.csv")
symcol = [c for c in um.columns if "sym" in c.lower()][0]
mcol = [c for c in um.columns if "first" in c.lower()][0]
um["base"] = um[symcol].map(base_of)
um["first_month"] = pd.to_datetime(um[mcol].astype(str).str[:7] + "-01", utc=True)
um["perp_first_ub"] = um["first_month"] + pd.offsets.MonthBegin(1)          # the first day of the month after the first month: an upper bound
first_ub = um.sort_values("perp_first_ub").groupby("base")["perp_first_ub"].first()  # the earliest contract of the base
bases = sorted(set(um.base))
m12 = pd.read_csv("ft2/screen_members.csv")
m34 = pd.read_csv("ft2/screen_members_f34.csv")
for m in (m12, m34):
    m["base"] = m.symbol.map(base_of)
    m["block"] = pd.to_datetime(m.block, utc=True)
    m["block_end"] = pd.to_datetime(m.block_end, utc=True) if "block_end" in m else m["block"] + pd.Timedelta(days=28)
members = pd.concat([m12, m34], ignore_index=True)


def member_at(base, ts):
    g = members[(members.base == base) & (members.block <= ts) & (members.block_end > ts)]
    return bool(len(g))


def eligible_age(base, ts):
    """The perpetual ≥ 30 days old at ts, by the first-month upper bound (a lower bound of the age, as the audits count)."""
    if base not in first_ub.index:
        return None
    return (ts - first_ub[base]).days >= PERP_AGE


say(f"# Decision CG's seed counts (2026-11-06; `scripts/cg_count.py` on the work VM; no bar after an event joined to a label, no price read, no fold read)\n")
say(f"The universe: {len(bases)} bases of {len(um)} USDT perpetuals (`um_first_month.csv`); member blocks F1+F2 {m12.block.nunique()} "
    f"({m12.base.nunique()} bases), F3+F4 {m34.block.nunique()} ({m34.base.nunique()} bases).\n")

# --- (1) rule (a): the cost bar by fold from the names' own cost rows
say("## (1) Rule (a) — the cost bar B_i = 4 × (5 + taker_leg) on `costwide`'s proxy, per (name, day), by fold")
try:
    W = pd.read_parquet("data/cost_daily_wide.parquet", columns=["symbol", "day", "spread_cal_bps", f"imp_{NOTIONAL}"])
    W["symbol"] = W["symbol"].astype(str)
    W["day"] = pd.to_datetime(W["day"], utc=True)
    W["base"] = W.symbol.map(base_of)
    W["B_i"] = 4.0 * (TAKER_BPS + W["spread_cal_bps"] / 2 + W[f"imp_{NOTIONAL}"])
    W["fold"] = W.day.map(fold)
    W = W[W.fold.isin(["F1", "F2", "F3", "F4", "F5"])]
    W["member"] = [member_at(b, t) for b, t in zip(W.base, W.day)]
    rows = []
    for (f, mem), g in W.groupby(["fold", "member"]):
        per_name = g.groupby("symbol")["B_i"].median()
        rows.append({"fold": f, "member": mem, "names": int(per_name.size), "name_days": int(len(g)),
                     "B_q25": round(float(per_name.quantile(0.25)), 1), "B_median": round(float(per_name.median()), 1),
                     "B_q75": round(float(per_name.quantile(0.75)), 1), "B_mean_over_days": round(float(g["B_i"].mean()), 1),
                     "names_B_le_60": int((per_name <= 60).sum()), "names_B_le_120": int((per_name <= 120).sum())})
    T1 = pd.DataFrame(rows).sort_values(["fold", "member"])
    T1.to_csv(f"{OUT}/cg_costbar_by_fold.csv", index=False)
    say(T1.to_markdown(index=False))
    say("\nThe frozen event lists' names on their own t0 day (the entry day's row, else the last within 7 days; a name without one is counted `none`):")
    rows = []
    for p in sorted(glob.glob("ft2/upgrades_f*.csv") + glob.glob("ft2/krlistings_f*.csv")):
        L = pd.read_csv(p)
        if "t0" not in L or "symbol" not in L:
            continue
        L["t0"] = pd.to_datetime(L["t0"], utc=True)
        Bs, none = [], 0
        for s, t in zip(L.symbol.astype(str), L.t0):
            g = W[(W.symbol == s) & (W.day <= t.floor("D")) & (W.day >= t.floor("D") - pd.Timedelta(days=7))]
            if len(g):
                Bs.append(float(g.sort_values("day")["B_i"].iloc[-1]))
            else:
                none += 1
        Bs = pd.Series(Bs)
        rows.append({"list": p.split("/")[-1], "rows": len(L), "priced": int(Bs.size), "none": none, "B_median": round(float(Bs.median()), 1) if Bs.size else np.nan,
                     "B_mean": round(float(Bs.mean()), 1) if Bs.size else np.nan, "B_q90": round(float(Bs.quantile(0.9)), 1) if Bs.size else np.nan})
    T1b = pd.DataFrame(rows)
    T1b.to_csv(f"{OUT}/cg_costbar_lists.csv", index=False)
    say(T1b.to_markdown(index=False))
except Exception as e:  # noqa: BLE001
    say(f"<!-- (1) failed: {e!r} -->")
say(f"\n(section 1 done, {time.time() - t_start:.0f} s)\n")

# --- (2) catalog 93 "Latest Activities"
say("## (2) The CMS catalog 93 \"Latest Activities\" — the titles by family, the ticker's perpetual ≥ 30 days old at the release, by fold")
arts, p = [], 1
while True:
    d = http(CMS_LIST.format(c=93, p=p))
    page = (d or {}).get("data", {}).get("catalogs") or []
    page = page[0]["articles"] if page else []
    if not page:
        break
    arts += [{k: a.get(k) for k in ("id", "code", "title", "releaseDate")} for a in page]
    if p == 1:
        say(f"<!-- page 1: {len(page)} articles, first {page[0]['title'][:80]!r} at {pd.Timestamp(int(page[0]['releaseDate']), unit='ms', tz='UTC')} -->")
    p += 1
    time.sleep(3.0)
arts = list({a["id"]: a for a in arts}.values())
if arts:
    json.dump(arts, open(f"data/raw/external/binance_cms/list_93_{pd.Timestamp.now('UTC'):%Y%m%d}.json", "w"))
A = pd.DataFrame(arts)
if len(A):
    A["release"] = pd.to_datetime(A["releaseDate"].astype("int64"), unit="ms", utc=True)
    A["fold"] = A.release.map(fold)
    A["ticks"] = A.title.map(lambda s: re.findall(r"\(([A-Z0-9]{2,10})\)", s))
    fam = {
        "launchpool_megadrop_hodler": r"Launchpool|Megadrop|HODLer Airdrop|Launchpad",
        "alpha_or_premarket": r"Binance Alpha|Pre-Market|Pre Market",
        "competition_promo_per_name": r"Trading Competition|Tournament|Carnival|Trade-to-Earn|Trade to Earn|Bonus|Challenge|Giveaway|Promotion|Token Vouchers|Rewards",
        "futures_launch": r"Futures Will Launch|Futures Will List|Perpetual Contract",
        "earn_adds": r"Simple Earn|Earn.{0,20}(Add|Launch)|Staking|Locked Products|Dual Investment|Auto-Invest",
        "margin_adds": r"Margin.{0,40}(Add|Enable|Support)|Isolated Margin|Cross Margin",
        "spot_listing": r"Will List|Will Add|Listing",
        "delist": r"Delist|Remov",
        "token_swap_rename": r"Token Swap|Rename|Redenomination|Rebrand|Migration",
        "vote_to_list": r"Vote to List|Vote to Delist",
        "convert_buy_crypto": r"Convert|Buy Crypto|Fiat|P2P|Pay",
    }
    rows = []
    for k, pat in fam.items():
        m = A[A.title.str.contains(pat, case=False, regex=True)]
        ev = []
        for r in m.itertuples():
            for t in dict.fromkeys(r.ticks):
                b = re.sub(r"^1000+", "", t)
                if b in first_ub.index:
                    ok = eligible_age(b, r.release)
                    ev.append({"family": k, "id": r.id, "title": r.title, "release": r.release, "fold": r.fold, "base": b, "perp_ge_30d": ok, "member_at_release": member_at(b, r.release)})
        E = pd.DataFrame(ev)
        el = E[E.perp_ge_30d == True] if len(E) else E  # noqa: E712
        rows.append({"family": k, "titles": len(m), "titles_with_a_ticker_of_ours": int(E.id.nunique()) if len(E) else 0,
                     "events_perp_ge_30d": len(el), "bases": int(el.base.nunique()) if len(el) else 0,
                     "by_fold": byfold(el.groupby("fold").size()) if len(el) else "-", "members_at_release": int(el.member_at_release.sum()) if len(el) else 0,
                     "sample": " | ".join(m.title.head(3).str[:70])})
        if len(E):
            E.to_csv(f"{OUT}/cg_cat93_{k}.csv", index=False)
    T2 = pd.DataFrame(rows)
    T2.to_csv(f"{OUT}/cg_cat93_families.csv", index=False)
    say(f"{len(A)} articles {A.release.min().date()} → {A.release.max().date()}; by fold of release: {byfold(A.groupby('fold').size())}\n")
    say(T2.drop(columns=["sample"]).to_markdown(index=False))
    say("\nSamples:\n" + "\n".join(f"- {r.family}: {r.sample}" for r in T2.itertuples()))
    unmatched = A[~A.title.str.contains("|".join(fam.values()), case=False, regex=True)]
    say(f"\nTitles matching no family: {len(unmatched)}; a sample:\n" + "\n".join(f"- {t[:110]}" for t in unmatched.title.sample(min(25, len(unmatched)), random_state=6)))
else:
    say("<!-- catalog 93: nothing fetched -->")
say(f"\n(section 2 done, {time.time() - t_start:.0f} s)\n")

# --- (3) catalog 48 on disk: the SPOT listing of a name whose perpetual is ≥ 30 days old
say("## (3) Catalog 48 on disk — the Binance SPOT listing of a name whose perpetual is ≥ 30 days old at the notice (the §9 #8 audit's count, every fold)")
rows = {}
for p in glob.glob("data/raw/external/binance_cms/list_48_*.json"):
    for a in json.load(open(p)):
        rows[a["id"]] = (a["id"], a.get("code"), a["title"], pd.Timestamp(int(a["releaseDate"]), unit="ms", tz="UTC"))
C = pd.DataFrame(rows.values(), columns=["id", "code", "title", "release"])
if len(C):
    C["fold"] = C.release.map(fold)
    L = C[C.title.str.contains(r"Will List|Will Add .{0,40}\(", case=False, regex=True) & ~C.title.str.contains(r"Futures|Perpetual|Margin|Earn|Alpha|Pre-Market|Trading Pair|Pairs|Convert|Pay", case=False, regex=True)]
    ev = []
    for r in L.itertuples():
        for t in dict.fromkeys(re.findall(r"\(([A-Z0-9]{2,10})\)", r.title)):
            b = re.sub(r"^1000+", "", t)
            if b in first_ub.index:
                ev.append({"id": r.id, "title": r.title, "release": r.release, "fold": r.fold, "base": b, "perp_ge_30d": eligible_age(b, r.release), "member_at_release": member_at(b, r.release)})
    E3 = pd.DataFrame(ev)
    el = E3[E3.perp_ge_30d == True] if len(E3) else E3  # noqa: E712
    E3.to_csv(f"{OUT}/cg_cat48_spot_listings.csv", index=False)
    say(f"catalog-48 titles on disk {len(C)} ({C.release.min().date()} → {C.release.max().date()}); spot-listing titles {len(L)}; with a ticker of ours {E3.id.nunique() if len(E3) else 0}; "
        f"the perpetual ≥ 30 d old at the notice: {len(el)} on {el.base.nunique() if len(el) else 0} bases — {byfold(el.groupby('fold').size()) if len(el) else '-'}; members at the release {int(el.member_at_release.sum()) if len(el) else 0}")
    if len(el):
        say("\n".join(f"- {r.base} {r.release.date()} {r.fold}: {r.title[:90]}" for r in el.sort_values("release").itertuples()))
else:
    say("<!-- no catalog-48 list on disk -->")
say(f"\n(section 3 done, {time.time() - t_start:.0f} s)\n")

# --- (4) governance votes: Snapshot
say("## (4) Governance votes — Snapshot's spaces joined to our bases by the voting token's symbol; the proposals' END stamps by fold")
spaces = []
# the `ranking` query (spaces by activity; 72,273 in all) answers 20 a page at any skip (probed 2026-11-06: first ≤ 20, skip 10,000 fine; the explore
# endpoint answers an empty dict, `spaces(orderBy: …)` ignores the order) — paged to skip 14,000, where a page's proposalsCount is ≈ 3
for skip in range(0, 14000, 20):
    d = http(SNAP, {"query": 'query { ranking(first: 20, skip: %d, where: {}) { items { id name symbol verified proposalsCount followersCount } } }' % skip})
    page = (((d or {}).get("data") or {}).get("ranking") or {}).get("items") or []
    if not page:
        say(f"<!-- ranking: empty page at skip {skip} -->")
        break
    spaces += [{"id": s["id"], "name": s.get("name"), "symbol": str(s.get("symbol") or "").upper(), "proposals": s.get("proposalsCount") or 0, "followers": s.get("followersCount") or 0, "verified": s.get("verified")} for s in page]
    if skip % 2000 == 0:
        say(f"<!-- ranking skip {skip}: {page[0]['id']} {page[0].get('proposalsCount')} … {page[-1]['id']} {page[-1].get('proposalsCount')} ({time.time() - t_start:.0f} s) -->")
    time.sleep(0.6)
say(f"<!-- ranking: {len(spaces)} spaces paged -->")
S = pd.DataFrame(spaces)
if len(S):
    S = S[S.symbol.isin(bases) & (S.proposals >= 5)].sort_values("proposals", ascending=False)
    S = S.drop_duplicates("symbol", keep="first")       # one space a base: the busiest; the others counted beside
    S.to_csv(f"{OUT}/cg_snapshot_spaces.csv", index=False)
    say(f"spaces with a symbol of ours and ≥ 5 proposals (one a base, the busiest): {len(S)} on {S.symbol.nunique()} bases; verified {int(S.verified.fillna(False).astype(bool).sum())}; "
        f"proposals in all {int(S.proposals.sum())}; the busiest: " + ", ".join(f"{r.symbol} {r.id} {r.proposals}" for r in S.head(12).itertuples()))
    props, ids = [], list(S.id)
    probe = http(SNAP, {"query": 'query { proposals(first: 5, where: {space_in: %s}, orderBy: "created", orderDirection: asc) { id created start end votes scores_total state space { id } title } }' % json.dumps(ids[:3])})
    say(f"<!-- probe: {json.dumps(((probe or {}).get('data') or {}).get('proposals', [])[:2])[:400]} -->")
    for i in range(0, len(ids), 25):
        batch, cur = ids[i:i + 25], 0
        while True:
            d = http(SNAP, {"query": 'query { proposals(first: 1000, where: {space_in: %s, created_gt: %d}, orderBy: "created", orderDirection: asc) { id created start end votes scores_total state space { id } title } }' % (json.dumps(batch), cur)})
            page = ((d or {}).get("data") or {}).get("proposals") or []
            if not page:
                break
            props += [{"space": q["space"]["id"], "id": q["id"], "created": q["created"], "start": q["start"], "end": q["end"], "votes": q.get("votes") or 0, "scores_total": q.get("scores_total") or 0, "state": q.get("state"), "title": (q.get("title") or "")[:100]} for q in page]
            cur = max(q["created"] for q in page)
            time.sleep(1.2)
            if len(page) < 1000:
                break
    P = pd.DataFrame(props)
    if len(P):
        P["symbol"] = P.space.map(S.set_index("id").symbol)
        for c in ("created", "start", "end"):
            P[c] = pd.to_datetime(P[c].astype("int64"), unit="s", utc=True)
        P["fold"] = P.end.map(fold)
        P["perp_ge_30d"] = [eligible_age(b, t) for b, t in zip(P.symbol, P.end)]
        P["member_at_end"] = [member_at(b, t) for b, t in zip(P.symbol, P.end)]
        P["duration_d"] = (P.end - P.start).dt.total_seconds() / 86400
        P["lead_d"] = (P.end - P.created).dt.total_seconds() / 86400
        P.to_csv(f"{OUT}/cg_snapshot_proposals.csv", index=False)
        el = P[(P.perp_ge_30d == True) & (P.state == "closed")]  # noqa: E712
        say(f"\nproposals fetched {len(P)} on {P.symbol.nunique()} bases; closed with the perpetual ≥ 30 d old at the END: {len(el)} on {el.symbol.nunique()} bases — {byfold(el.groupby('fold').size())}")
        say(f"members at the end: {int(el.member_at_end.sum())} — {byfold(el[el.member_at_end].groupby('fold').size())}")
        say(f"the vote's duration, days, q10 / q50 / q90: {el.duration_d.quantile(0.1):.1f} / {el.duration_d.quantile(0.5):.1f} / {el.duration_d.quantile(0.9):.1f}; "
            f"the end known ahead (end − created), days: {el.lead_d.quantile(0.1):.1f} / {el.lead_d.quantile(0.5):.1f} / {el.lead_d.quantile(0.9):.1f}")
        for thr in (50, 200, 1000):
            g = el[el.votes >= thr]
            say(f"with ≥ {thr} votes: {len(g)} on {g.symbol.nunique()} bases — {byfold(g.groupby('fold').size())}; members {int(g.member_at_end.sum())}")
        pm = el.groupby("symbol").size().sort_values(ascending=False)
        say("per base (the top 15): " + ", ".join(f"{k} {v}" for k, v in pm.head(15).items()))
        say("(the 7-day collapse, the name-months and the end's hour: `scripts/cg_count_tail.py` on the pulled CSV — the first run's last line raised on a pandas typing slip after every CSV was written)")
    else:
        say("<!-- no proposals fetched -->")
else:
    say("<!-- no spaces fetched -->")
say(f"\n(section 4 done, {time.time() - t_start:.0f} s)\n")
say(f"(run {time.time() - t_start:.0f} s)")
