"""Decision CK's seed counts (2026-11-06) — the brainstorm CJ1 asked for, with rule (a) as step 0.

Runs on the laptop with the standard library alone (decision BM (l)'s precedent): the frozen lists and the
pulled audits in git, plus keyless probes of api.llama.fi and api.github.com. No bar after a t0 is joined to
a label, nothing is priced, no fold is read. Each section writes its CSV before the next starts (0v (ii));
the markdown `output/by_probe/ck_count.md` is appended section by section.

    python3 -I scripts/ck_count.py            # from fluxtrader2/
"""
import csv, json, re, sys, time, datetime as dt, statistics as st, urllib.request
from collections import Counter, defaultdict

OUT = "output/by_probe"
MD = f"{OUT}/ck_count.md"
F = {"F1": ("2023-05-01", "2024-01-01"), "F2": ("2024-01-01", "2024-09-01"), "F3": ("2024-09-01", "2025-05-01"),
     "F4": ("2025-05-01", "2026-01-01"), "F5": ("2026-01-01", "2026-09-15")}
T0 = time.time()


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    with open(MD, "a") as f:
        f.write(s + "\n")


def get(url, accept=None):
    h = {"User-Agent": "ft2-probe/0.1"}
    if accept:
        h["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=180).read()


def fold(d):
    for k, (a, b) in F.items():
        if a <= d < b:
            return k
    return "pre" if d < "2023-05-01" else "post"


def base(s):
    s = s[:-4] if s.endswith("USDT") else s
    return re.sub(r"^(1000000|1000|1M)", "", s)


# the member blocks (block, symbol, age_days → the perpetual's first day = block − age)
mem_sym, mem_base, perp_first = defaultdict(set), defaultdict(set), {}
for fn in ("ft2/screen_members.csv", "ft2/screen_members_f34.csv"):
    for r in csv.DictReader(open(fn)):
        b = dt.date.fromisoformat(r["block"])
        mem_sym[b].add(r["symbol"]); mem_base[b].add(base(r["symbol"]))
        pf = b - dt.timedelta(days=int(float(r["age_days"])))
        for k in (r["symbol"], base(r["symbol"])):
            perp_first[k] = min(perp_first.get(k, pf), pf)
blocks = sorted(mem_sym)
bases = set().union(*mem_base.values())


def member_at(key, day, table):
    d = dt.date.fromisoformat(day[:10]); prev = [b for b in blocks if b <= d]
    if not prev or (d - prev[-1]).days > 45:
        return None
    return key in table[prev[-1]]


open(MD, "w").write(f"# Decision CK's seed counts ({dt.date.today().isoformat()}; `scripts/ck_count.py` on the laptop, the standard "
                    "library alone; the frozen lists and the pulled audits in git + keyless probes of api.llama.fi / api.github.com; "
                    "no bar after a t0 joined to a label, nothing priced, no fold read)\n\n")
say(f"blocks {len(blocks)} ({blocks[0]} → {blocks[-1]}), member symbols {len(set().union(*mem_sym.values()))}, bases {len(bases)}")

# ---------------------------------------------------------------- (1) the crowd's arrivals re-counted: Coinbase, Hyperliquid
say("\n## (1) The record check on two listings the record left not proposed — re-counted from the pulled audits (decision BM (l)'s numbers)")


def count_listing(name, rows, csvname):
    out = []
    for sym, t0 in rows:
        pf = perp_first.get(sym)
        if pf is None:
            continue
        age = (dt.date.fromisoformat(t0[:10]) - pf).days
        if age < 30:
            continue
        out.append((sym, t0[:10], fold(t0[:10]), age, member_at(sym, t0, mem_sym)))
    with open(f"{OUT}/{csvname}", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["symbol", "t0", "fold", "perp_age_days", "member_at_t0"]); w.writerows(out)
    c = Counter(x[2] for x in out); m = Counter(x[2] for x in out if x[4])
    say(f"- **{name}**: {len(rows)} dated markets, {len(out)} with the perpetual ≥ 30 d old; by fold "
        f"{dict(sorted(c.items()))}; members at t0 by fold {dict(sorted(m.items()))}; F1+F2 {c['F1'] + c['F2']} "
        f"(members {m['F1'] + m['F2']}), F3+F4 {c['F3'] + c['F4']} (members {m['F3'] + m['F4']}), F5 {c['F5']} (`{csvname}`)")
    return out


cb = json.load(open("output/coinbase_members_audit.json"))["cover"]
count_listing("Coinbase SPOT listing of an existing Binance perpetual (`first_daily_bar`, the members audit)",
              [(x["symbol"], x["first_daily_bar"]) for x in cb if x.get("listed") and x.get("first_daily_bar")], "ck_coinbase_listings.csv")
hl = json.load(open("output/hl_audit.json"))["cover"]
rows = [(x["symbol"], x["first"]) for x in hl if x.get("listed") and x.get("first")]
batch = sum(1 for _, t in rows if t.startswith("2023-05-12"))
count_listing(f"Hyperliquid listing of an existing Binance perpetual (`first` funding row; the venue's 2023-05-12 start batch of {batch} out)",
              [(s, t) for s, t in rows if not t.startswith("2023-05-12")], "ck_hl_listings.csv")
say(f"(section 1 done, {time.time() - T0:.0f} s)")

# ---------------------------------------------------------------- (2) the exchange's own on-chain balance per token (DefiLlama's CEX adapters)
say("\n## (2) THE KIND — the exchange's OWN on-chain balance per token: DefiLlama's CEX adapters (`api.llama.fi/protocol/<cex>`, free, keyless)")


def series(slug):
    b = get(f"https://api.llama.fi/protocol/{slug}")
    d = json.loads(b); agg = {}
    for ch, v in d["chainTvls"].items():
        if ch.endswith("-staking") or ch.endswith("-borrowed"):
            continue
        for row in v.get("tokens", []):
            day = dt.datetime.fromtimestamp(row["date"], dt.timezone.utc).date().isoformat()
            a = agg.setdefault(day, Counter())
            for tok, amt in row["tokens"].items():
                a[tok] += amt
    return agg, len(b), list(d["chainTvls"])


t = time.time()
agg, nbytes, chains = series("binance-cex")
days = sorted(agg)
dd = [dt.date.fromisoformat(x) for x in days]
gaps = [(days[i], (dd[i + 1] - dd[i]).days) for i in range(len(dd) - 1) if (dd[i + 1] - dd[i]).days > 1]
alltok = set().union(*(set(agg[d]) for d in days))
say(f"- `binance-cex`: {nbytes / 1e6:.1f} MB in {time.time() - t:.1f} s; {len(days)} days {days[0]} → {days[-1]}, gaps > 1 d {len(gaps)} {gaps[:6]}; "
    f"chains {len([c for c in chains if not c.endswith(('-staking', '-borrowed'))])}; tokens ever {len(alltok)}, of the {len(bases)} member bases {len(bases & alltok)}")
missing = sorted(bases - alltok)
say(f"- member bases ABSENT from the adapter (chains it does not read): {len(missing)} — {' '.join(missing)}")
with open(f"{OUT}/ck_cex_balance_members.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["day", "base", "amount"])
    for day in days:
        for tok in sorted(bases & set(agg[day])):
            if agg[day][tok] > 0:
                w.writerow([day, tok, agg[day][tok]])


def cover_rows(aggs, label):
    rows = []
    for blk in blocks:
        bs = blk.isoformat(); d30 = (blk - dt.timedelta(days=30)).isoformat()

        def has(a, tok, upto):
            day = max((x for x in a if x <= upto), default=None)
            return day is not None and a[day].get(tok, 0) > 0
        have = [tok for tok in mem_base[blk] if any(has(a, tok, bs) for a in aggs)]
        have30 = [tok for tok in have if any(has(a, tok, d30) for a in aggs)]
        rows.append((bs, len(mem_base[blk]), len(have), len(have30)))
    f12 = [r[2] for r in rows if fold(r[0]) in ("F1", "F2")]; f34 = [r[2] for r in rows if fold(r[0]) in ("F3", "F4")]
    say(f"- breadth, {label}: members of the block with a positive balance on the block's day — F1+F2 {min(f12)} … {max(f12)} (median {st.median(f12):.0f}) of 60, "
        f"F3+F4 {min(f34)} … {max(f34)} (median {st.median(f34):.0f}); with one 30 days before too: F1+F2 median {st.median([r[3] for r in rows if fold(r[0]) in ('F1', 'F2')]):.0f}")
    return rows


rows = cover_rows([agg], "Binance alone")
with open(f"{OUT}/ck_cex_balance_cover.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["block", "members", "with_balance", "with_balance_30d_before"]); w.writerows(rows)

# the daily change per member token (the series' first 30 days out, consecutive days only)
ser = defaultdict(list)
for day in days:
    for tok in bases:
        if agg[day].get(tok, 0) > 0:
            ser[tok].append((day, agg[day][tok]))
chg = []
for tok, s in ser.items():
    for i in range(1, len(s)):
        d0, a0 = s[i - 1]; d1, a1 = s[i]
        if (dt.date.fromisoformat(d1) - dt.date.fromisoformat(s[0][0])).days < 30 or (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days != 1:
            continue
        chg.append((tok, d1, (a1 - a0) / a0))
vals = sorted(abs(c) for *_, c in chg)
q = lambda p: vals[int(p * (len(vals) - 1))]


def acf1(xs):
    m = sum(xs) / len(xs); v = sum((x - m) ** 2 for x in xs)
    return sum((xs[i] - m) * (xs[i + 1] - m) for i in range(len(xs) - 1)) / v if v > 0 else float("nan")


ac = [acf1([c for tt, _, c in chg if tt == tok]) for tok, s in ser.items() if len(s) > 130]
say(f"- the daily change of a member token's balance: {len(chg)} name-days on {len(ser)} bases; |change| q50 {q(.5):.4f} q90 {q(.9):.4f} q95 {q(.95):.4f} "
    f"q99 {q(.99):.3f} q999 {q(.999):.2f}; acf(1) per name median {st.median(ac):.3f} ({len(ac)} names) — WHITE: a flow's form (0a (viii))")
say("- the EVENT counts (one a name per 7 days, the series' first 30 days out; MEMBERS at t0 = the registered population by rule (a); the non-member cells beside):")
say("\n| side | threshold | events | names | by fold (all) | MEMBERS at t0: F1 / F2 / F3 / F4 / F5 | F1+F2 / F3+F4 members | top member names F1–F4 |\n|---|---|---|---|---|---|---|---|")
for thr in (0.05, 0.10, 0.20):
    for side, name in ((1, "INFLOW"), (-1, "OUTFLOW")):
        ev, last = [], {}
        for tok, day, c in sorted(chg):
            if side * c >= thr:
                if tok in last and (dt.date.fromisoformat(day) - dt.date.fromisoformat(last[tok])).days < 7:
                    continue
                last[tok] = day; ev.append((tok, day, fold(day), member_at(tok, day, mem_base), c))
        cf = Counter(e[2] for e in ev); cm = Counter(e[2] for e in ev if e[3])
        top = Counter(e[0] for e in ev if e[3] and e[2] in ("F1", "F2", "F3", "F4")).most_common(6)
        fn = f"ck_cex_events_{'in' if side > 0 else 'out'}_{int(thr * 100)}.csv"
        with open(f"{OUT}/{fn}", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["base", "day", "fold", "member_at_t0", "change"]); w.writerows(ev)
        say(f"| {name} | ≥ {int(thr * 100)} % of the holding in a day | {len(ev)} | {len({e[0] for e in ev})} | "
            f"{' '.join(f'{k} {cf[k]}' for k in ('pre', 'F1', 'F2', 'F3', 'F4', 'F5', 'post'))} | "
            f"{' / '.join(str(cm[k]) for k in ('F1', 'F2', 'F3', 'F4', 'F5'))} | {cm['F1'] + cm['F2']} / {cm['F3'] + cm['F4']} | "
            f"{', '.join(f'{a} {b}' for a, b in top)} | (`{fn}`)")
say(f"\n(section 2 done, {time.time() - T0:.0f} s)")

# ---------------------------------------------------------------- (3) the other exchanges, Robinhood, the known-at routes
say("\n## (3) The other tracked exchanges' balances, Robinhood's custody, and the known-at routes")
S = {}
for slug in ("robinhood", "okx", "bybit", "bitget", "gate", "htx", "kucoin", "bitfinex", "mexc", "crypto-com", "kraken", "coinbase", "upbit", "bithumb"):
    try:
        a, nb, _ = series(slug); S[slug] = a; dd = sorted(a); toks = set().union(*(set(a[d]) for d in dd))
        say(f"- `{slug}`: {len(dd)} days {dd[0]} → {dd[-1]}, tokens {len(toks)}, of our bases {len(toks & bases)}")
    except Exception as e:
        say(f"- `{slug}`: not an adapter ({type(e).__name__})")
rows2 = cover_rows([S["robinhood"]], "Robinhood alone") if "robinhood" in S else []
rows3 = cover_rows([agg] + list(S.values()), "every tracked exchange together")
with open(f"{OUT}/ck_cex_others_cover.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["block", "members", "robinhood_with_balance", "any_tracked_cex_with_balance"])
    w.writerows([(a[0], a[1], b[2] if rows2 else None, c[2]) for a, b, c in zip(rows3, rows2 or rows3, rows3)])
try:
    snaps = json.loads(get("http://web.archive.org/cdx/search/cdx?url=api.llama.fi/protocol/binance-cex&output=json&fl=timestamp&collapse=timestamp:8"))
    say(f"- Wayback snapshots of `api.llama.fi/protocol/binance-cex`: {max(len(snaps) - 1, 0)} — the known-at is NOT measurable backward from the archive")
except Exception as e:
    say(f"- Wayback probe failed: {e}")
try:
    for fn in ("config.js", "index.js"):
        c = json.loads(get(f"https://api.github.com/repos/DefiLlama/DefiLlama-Adapters/commits?path=projects/binance/{fn}&per_page=100", "application/vnd.github+json"))
        dates = [x["commit"]["committer"]["date"][:10] for x in c]
        say(f"- the adapter's wallet list `DefiLlama-Adapters/projects/binance/{fn}`: {len(c)} commits (the last 100) {dates[-1]} → {dates[0]}; "
            f"by year {dict((y, sum(1 for d in dates if d.startswith(y))) for y in ('2022', '2023', '2024', '2025', '2026'))} — the git log dates every wallet's addition")
        with open(f"{OUT}/ck_adapter_commits_{fn.split('.')[0]}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["date", "sha", "message"]); w.writerows([(x["commit"]["committer"]["date"], x["sha"][:10], x["commit"]["message"].splitlines()[0][:120]) for x in c])
except Exception as e:
    say(f"- GitHub probe failed: {e}")
say(f"\n(section 3 done, {time.time() - T0:.0f} s)")
