"""P8 (decision BP1, 2026-10-29) — attention per name from OUTSIDE every exchange: Wikipedia's daily pageviews of the token's article.
`ft2 wiki names|articles|probe|fetch|ingest|audit` — the SOURCE AUDIT; nothing priced, no fold read, no view joined to a label.

names      the token's NAME per base (the twelve's and the screener's members' bases, `coinbase.base`): the Korean venues' `english_name`
           from the saved market lists (`krw.markets_file`) and CoinGecko's keyless `/coins/list` + `/coins/markets` (the rank orders the
           coins that share a ticker) → output/wiki_names.csv; the raw answers under data/raw/external/wikipedia/.
articles   every candidate title per base resolved on en.wikipedia (redirects followed; the intro's first sentences and a crypto hint —
           the words cryptocurrency / blockchain / token / protocol in them) plus the search API's top hits for "<name> cryptocurrency"
           → output/wiki_candidates.csv and a PROPOSED pick per base, output/wiki_pick.csv. The pick is checked BY HAND and frozen as
           `ft2/wiki_articles.csv` (base, article, source, note) — the audit's and the fetch's list; nothing is fetched before it exists.
probe      the known-at: Bitcoin's last days from the pageviews API against the response's `Date` header — which UTC day is the last one
           present at this hour → data/raw/external/wikipedia/probe_<stamp>.json. Measured, not assumed (two probes at different hours).
           The REST API is cached (Varnish: the same URL answers with the first response's `Date` for hours), so the asked start carries the
           current hour to make the URL new; `Age` is recorded beside `Date`.
fetch      per frozen article the DAILY per-article pageviews (the Wikimedia REST API, `all-access` / `user`, keyless, a User-Agent required)
           from START to today in one request each → data/raw/external/wikipedia/pageviews/<title>.json, for the article AND EVERY TITLE
           THAT REDIRECTS TO IT (`prop=redirects`; redirects.json) — pageviews are counted under the title of the day, so a renamed article
           ('Ripple (payment protocol)' → 'XRP Ledger', 'Chainlink (blockchain)' → '… (blockchain oracle)') has its history under its old
           names, which stay as redirects; the first run without them showed 55 … 65 % empty days on DOT, HBAR, LINK, NEO, TON, TRX, XRP.
           The article's creation stamp (the first revision, which follows a move) → created.json. Resumable (a file whose asked range
           covers the asked one is kept); the titles are fetched on THREADS threads.
parquet    data/wiki_views.parquet: (base, symbol, article, day, views, present, ts_known) — `day` the UTC day's start, `views` the sum over
           the article and its redirects, `present` whether the API returned the day for any of them (it omits days without data: zeros
           are filled from the later of START and the article's creation), `ts_known` = day + KNOWN_AT_H hours — the only stamp a feature
           may read the day at (48 h until the probes say otherwise). redirect_share.json: per article the share of views that came in
           under a redirect's title.
audit      output/wiki_audit.md (+ .json): the covered bases by set (the twelve, F1+F2's members, F3+F4's members), the members with an
           article per block (R62's breadth), per article the creation, the extent, the level and the share of zero days, F1–F5 cover,
           the DEV form on log views (the deviation from the trailing month in sd units): within-name sd, persistence, and the cross-name
           correlation of the deviation (one attention factor or many), the probes' known-at. The registration (the next decision) reads
           its counts; this module reads no price.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import coinbase as cb
from . import data, folds, krw

RAW = data.RAW / "external" / "wikipedia"
PARQUET = data.PROC / "wiki_views.parquet"
ARTICLES = Path(__file__).with_name("wiki_articles.csv")       # frozen by hand after `articles`, committed
OUT = Path("output/wiki_audit.md")
NAMES_CSV = Path("output/wiki_names.csv")
CANDIDATES_CSV = Path("output/wiki_candidates.csv")
PICK_CSV = Path("output/wiki_pick.csv")
PV_API = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{article}/daily/{a}/{b}"
WP_API = "https://en.wikipedia.org/w/api.php"
CG_LIST = "https://api.coingecko.com/api/v3/coins/list"
CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={p}"
CG_PAGES = 8                 # the 2,000 largest coins ranked; a ticker shared by several coins is read by rank
UA = {"User-Agent": "fluxtrader2-research/1.0 (source audit; python-urllib)", "Accept": "application/json"}
PAUSE = 0.15                 # Wikimedia asks for ≤ 100 req/s on the REST API and politeness on the action API; CoinGecko's free tier ≈ 30/min
CG_PAUSE = 2.5
START = "2021-12-01"         # F0's first month; daily data exists from 2015-07
KNOWN_AT_H = 36              # ts_known = the day's start + 36 h (D+1 12:00 UTC): R72's two UTC-morning probes (2026-10-30, 2026-11-01, 06:00 UTC, Age 0) both held the previous day; was 48 before them
MONTH_D = 30
THREADS = 3                  # 8 threads tripped the REST API's 429 on 14 of 406 titles (2026-10-29); 3 do not
MIN_MONTH_D = 15
TWELVE = krw.TWELVE
CRYPTO = re.compile(r"cryptocurrenc|blockchain|\btoken\b|crypto|decentrali[sz]ed|\bDeFi\b|smart contract|stablecoin|\bcoin\b|proof[- ]of|layer[- ]?[12]\b|\bNFT\b|meme", re.I)
EXTRACT_CHARS = 240
COLS = ["base", "symbol", "article", "day", "views", "present", "ts_known"]
DAY = pd.Timedelta("1D")


# ---- the universe ----------------------------------------------------------------------------------------------------------------
def bases() -> pd.DataFrame:
    """One row per base: its Binance symbols, whether it is one of the twelve, and the member fold sets it belongs to."""
    rows: dict[str, dict] = {}
    for sym in TWELVE:
        rows.setdefault(cb.base(sym), {"symbols": set(), "twelve": True, "F1+F2": False, "F3+F4": False})["symbols"].add(sym)
    m = cb.member_symbols()
    for sym, fs in zip(m["symbol"], m["folds"]):
        r = rows.setdefault(cb.base(sym), {"symbols": set(), "twelve": False, "F1+F2": False, "F3+F4": False})
        r["symbols"].add(sym)
        r[fs] = True
    out = pd.DataFrame([{"base": b, "symbols": " ".join(sorted(r["symbols"])), "twelve": r["twelve"], "F1+F2": r["F1+F2"], "F3+F4": r["F3+F4"]}
                        for b, r in rows.items()]).sort_values("base").reset_index(drop=True)
    return out


# ---- http --------------------------------------------------------------------------------------------------------------------------
def _get(u: str, timeout: int = 60, retries: int = 6, headers: dict | None = None, raw: bool = False):
    """GET → parsed JSON (None on 404); `raw=True` → (body, headers) for the probe's `Date`."""
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=headers or UA), timeout=timeout) as r:
                body = r.read()
                return (json.loads(body), dict(r.headers)) if raw else json.loads(body)
        except urllib.error.HTTPError as e:                      # noqa: PERF203
            if e.code == 404:
                return (None, dict(e.headers)) if raw else None
            if e.code == 429:
                time.sleep(5.0 * 2 ** i)
                continue
            last = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(PAUSE * 4 * 2 ** i)
    raise RuntimeError(f"wiki: {u} failed after {retries} tries: {last}")


def _wp(params: dict) -> dict:
    q = urllib.parse.urlencode({"format": "json", "formatversion": "2", **params})
    time.sleep(PAUSE)
    return _get(f"{WP_API}?{q}") or {}


# ---- names ---------------------------------------------------------------------------------------------------------------------------
def venue_names() -> pd.DataFrame:
    """(base, name, source) from the saved Korean market lists — `english_name` where the venue lists the base."""
    rows = []
    for v in ("upbit", "bithumb"):
        mf = krw.markets_file(krw.universe(v))
        if mf is None:
            continue
        for sym, nm in zip(mf["symbol"], mf["english_name"]):
            if isinstance(sym, str) and isinstance(nm, str) and nm.strip():
                rows.append({"base": cb.base(sym), "name": nm.strip(), "source": v})
    return pd.DataFrame(rows, columns=["base", "name", "source"]).drop_duplicates()


def coingecko(today: pd.Timestamp | None = None) -> pd.DataFrame:
    """(base, name, source='coingecko', rank) — every CoinGecko coin whose ticker is a base, the 2,000 largest ranked first; raw answers saved."""
    today = today or pd.Timestamp.now("UTC")
    RAW.mkdir(parents=True, exist_ok=True)
    lst = _get(CG_LIST) or []
    (RAW / f"coingecko_list_{today:%Y%m%d}.json").write_text(json.dumps(lst))
    ranked = []
    for p in range(1, CG_PAGES + 1):
        time.sleep(CG_PAUSE)
        page = _get(CG_MARKETS.format(p=p)) or []
        ranked.extend(page)
        if len(page) < 250:
            break
    (RAW / f"coingecko_markets_{today:%Y%m%d}.json").write_text(json.dumps(ranked))
    rank = {c["id"]: int(c.get("market_cap_rank") or 10**6) for c in ranked if isinstance(c, dict) and "id" in c}
    want = set(bases()["base"])
    rows = [{"base": c["symbol"].upper(), "name": c["name"], "source": "coingecko", "rank": rank.get(c["id"], 10**6), "gecko_id": c["id"]}
            for c in lst if isinstance(c, dict) and c.get("symbol", "").upper() in want]
    return pd.DataFrame(rows, columns=["base", "name", "source", "rank", "gecko_id"]).sort_values(["base", "rank", "name"]).reset_index(drop=True)


def names(today: pd.Timestamp | None = None, out: Path | None = None) -> pd.DataFrame:
    """The venues' names first, then CoinGecko's by rank (the unranked kept behind the ranked); one row per (base, name)."""
    out = Path(out) if out else NAMES_CSV            # resolved at the call (a default bound at import defeats a test's monkeypatch — R70's lesson)
    v = venue_names()
    v["rank"] = -1
    v["gecko_id"] = None
    g = coingecko(today)
    allr = pd.concat([v, g], ignore_index=True)
    allr["source_order"] = allr["source"].map({"upbit": 0, "bithumb": 1, "coingecko": 2})
    allr = allr.sort_values(["base", "source_order", "rank", "name"]).drop_duplicates(["base", "name"]).drop(columns="source_order")
    B = bases()
    allr = B[["base", "symbols", "twelve", "F1+F2", "F3+F4"]].merge(allr, on="base", how="left")
    out.parent.mkdir(parents=True, exist_ok=True)
    allr.to_csv(out, index=False)
    return allr.reset_index(drop=True)


# ---- articles ------------------------------------------------------------------------------------------------------------------------
def resolve(titles: list[str]) -> dict[str, dict]:
    """Each title → {'title': the page's title after redirects, 'exists': bool, 'extract': the intro's first sentences}; 20 a call."""
    out: dict[str, dict] = {}
    titles = list(dict.fromkeys(t for t in titles if t))
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        r = _wp({"action": "query", "titles": "|".join(chunk), "redirects": "1", "prop": "extracts", "exintro": "1", "explaintext": "1",
                 "exsentences": "2", "exlimit": "max"})
        q = r.get("query", {})
        red = {x["from"]: x["to"] for x in q.get("redirects", [])}
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in chunk:
            t2 = norm.get(t, t)
            t2 = red.get(t2, t2)
            p = pages.get(t2, {})
            out[t] = {"title": t2, "exists": bool(p) and "missing" not in p, "extract": (p.get("extract") or "")[:EXTRACT_CHARS].replace("\n", " ")}
    return out


def search(query: str, n: int = 3) -> list[str]:
    r = _wp({"action": "query", "list": "search", "srsearch": query, "srlimit": str(n)})
    return [x["title"] for x in r.get("query", {}).get("search", [])]


def articles(names_df: pd.DataFrame | None = None, out: Path | None = None, pick_out: Path | None = None) -> pd.DataFrame:
    """Every candidate title per base resolved, a crypto hint on the intro, and a PROPOSED pick per base (checked by hand afterwards)."""
    out, pick_out = (Path(out) if out else CANDIDATES_CSV), (Path(pick_out) if pick_out else PICK_CSV)
    N = names_df if names_df is not None else (pd.read_csv(NAMES_CSV) if NAMES_CSV.exists() else names())
    B = bases()
    cands: list[dict] = []
    for _, b in B.iterrows():
        nm = N[(N["base"] == b["base"]) & N["name"].notna()]
        seen: list[tuple[str, str]] = []
        for name, src in zip(nm["name"], nm["source"]):
            for t in (name, f"{name} (cryptocurrency)", f"{name} (blockchain)"):
                if t not in {x[0] for x in seen}:
                    seen.append((t, src if t == name else f"{src}+suffix"))
        first = nm["name"].iloc[0] if len(nm) else b["base"]
        for t in search(f"{first} cryptocurrency"):
            if t not in {x[0] for x in seen}:
                seen.append((t, "search"))
        for t, src in seen:
            cands.append({"base": b["base"], "symbols": b["symbols"], "candidate": t, "how": src})
    C = pd.DataFrame(cands)
    res = resolve(C["candidate"].tolist()) if len(C) else {}
    C["title"] = C["candidate"].map(lambda t: res.get(t, {}).get("title", t))
    C["exists"] = C["candidate"].map(lambda t: bool(res.get(t, {}).get("exists", False)))
    C["extract"] = C["candidate"].map(lambda t: res.get(t, {}).get("extract", ""))
    C["crypto_hint"] = C["extract"].map(lambda s: bool(CRYPTO.search(s or "")))
    C["order"] = C["how"].map(lambda h: 0 if h in ("upbit", "bithumb") else 1 if h == "coingecko" else 2 if h.endswith("+suffix") else 3)
    out.parent.mkdir(parents=True, exist_ok=True)
    C.to_csv(out, index=False)
    picks = []
    for _, b in B.iterrows():                      # every base a row, with or without a candidate
        g = C[C["base"] == b["base"]] if len(C) else C
        ok = g[g["exists"] & g["crypto_hint"]].sort_values("order") if len(g) else g
        if len(ok):
            r = ok.iloc[0]
            picks.append({"base": b["base"], "symbols": b["symbols"], "pick": r["title"], "how": r["how"], "extract": r["extract"], "n_candidates": len(g)})
        else:
            any_ = g[g["exists"]].sort_values("order") if len(g) else g
            picks.append({"base": b["base"], "symbols": b["symbols"], "pick": "", "how": "none" if not len(any_) else "exists-no-hint",
                          "extract": any_["extract"].iloc[0] if len(any_) else "", "n_candidates": len(g)})
    P = pd.DataFrame(picks)
    P.to_csv(pick_out, index=False)
    return C


def frozen(path: Path | None = None) -> pd.DataFrame:
    """The hand-checked list (base, article, source, note); bases without an article carry an empty article and stay in the audit."""
    path = Path(path) if path else ARTICLES
    if not Path(path).exists():
        raise FileNotFoundError(f"wiki: {path} is not there — run `articles`, check output/wiki_pick.csv by hand, freeze the list")
    A = pd.read_csv(path, dtype=str).fillna("")
    assert set(["base", "article"]) <= set(A.columns), "wiki_articles.csv needs base, article"
    return A


# ---- the probe -------------------------------------------------------------------------------------------------------------------------
def _pv_title(article: str) -> str:
    return urllib.parse.quote(article.replace(" ", "_"), safe="")


def probe(article: str = "Bitcoin", days: int = 6, now: pd.Timestamp | None = None) -> dict:
    """Which UTC day is the last one the API holds at this hour — the known-at's evidence, saved with the server's own `Date`."""
    now = now or pd.Timestamp.now("UTC")
    a, b = (now - pd.Timedelta(days=days)).strftime("%Y%m%d%H"), now.strftime("%Y%m%d00")     # the hour in `a` makes the URL new to the cache
    body, hdr = _get(PV_API.format(article=_pv_title(article), a=a, b=b), raw=True)
    items = (body or {}).get("items", [])
    last = max((x["timestamp"] for x in items), default=None)
    H = {k.lower(): v for k, v in hdr.items()}
    server = H.get("date")
    st = pd.Timestamp(server).tz_convert("UTC") if server and pd.Timestamp(server).tzinfo else (pd.Timestamp(server, tz="UTC") if server else now)
    last_day = pd.Timestamp(last[:8], tz="UTC") if last else None
    lag_h = float((st - (last_day + DAY)) / pd.Timedelta("1h")) if last_day is not None else None
    rec = {"article": article, "asked": [a, b], "server_date": str(st), "cache_age_s": H.get("age"), "last_day_present": str(last_day.date()) if last_day is not None else None,
           "hours_after_that_day_ended": lag_h, "days_returned": len(items), "views": {x["timestamp"][:8]: x["views"] for x in items}}
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"probe_{st:%Y%m%dT%H%M}.json").write_text(json.dumps(rec, indent=1))
    return rec


def probes() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(RAW.glob("probe_*.json"))]


# ---- fetch -----------------------------------------------------------------------------------------------------------------------------
def _pv_file(article: str) -> Path:
    return RAW / "pageviews" / f"{_pv_title(article)}.json"


def redirects(arts: list[str]) -> dict[str, list[str]]:
    """Every title that redirects to each article (the old names after a move among them); cached in redirects.json."""
    out: dict[str, list[str]] = {}
    rj = RAW / "redirects.json"
    if rj.exists():
        out.update(json.loads(rj.read_text()))
    for art in arts:
        if art in out:
            continue
        titles: list[str] = []
        params = {"action": "query", "titles": art, "redirects": "1", "prop": "redirects", "rdlimit": "max", "rdnamespace": "0"}
        while True:
            r = _wp(params)
            for p in r.get("query", {}).get("pages", []):
                titles.extend(x["title"] for x in p.get("redirects", []))
            if "continue" in r:
                params = {**params, **r["continue"]}
            else:
                break
        out[art] = sorted(set(titles) - {art})
    RAW.mkdir(parents=True, exist_ok=True)
    rj.write_text(json.dumps(out, indent=1))
    return out


def _fetch_title(title: str, a_: str, b_: str) -> str:
    """One title's daily views into its file; 'ok' / 'empty' / 'skip' / 'err'."""
    f = _pv_file(title)
    if f.exists():
        try:
            old = json.loads(f.read_text())
            if old.get("asked", ["", ""])[1] >= b_ and old.get("asked", ["", ""])[0] <= a_:
                return "skip"
        except json.JSONDecodeError:
            pass
    time.sleep(PAUSE)
    try:
        body = _get(PV_API.format(article=_pv_title(title), a=a_, b=b_))
    except RuntimeError as ex:
        print(f"{title}: {ex}", file=sys.stderr, flush=True)
        return "err"
    items = (body or {}).get("items", [])
    f.write_text(json.dumps({"article": title, "asked": [a_, b_], "fetched": str(pd.Timestamp.now('UTC')), "items": [{"t": x["timestamp"][:8], "v": x["views"]} for x in items]}))
    return "ok" if items else "empty"


def fetch(start: str = START, end: str | None = None, path: Path | None = None, threads: int = THREADS) -> dict:
    """Every frozen article's daily views from `start` to `end` (today's previous day when None) — the article and each of its redirects one
    request each, on threads; the creation stamps."""
    A = frozen(path)
    arts = [a for a in A["article"].tolist() if a]
    arts = list(dict.fromkeys(arts))
    e = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now("UTC").normalize() - DAY
    a_, b_ = pd.Timestamp(start, tz="UTC").strftime("%Y%m%d00"), e.strftime("%Y%m%d00")
    (RAW / "pageviews").mkdir(parents=True, exist_ok=True)
    rd = redirects(arts)
    titles = list(dict.fromkeys([t for art in arts for t in (art, *rd.get(art, []))]))
    tot = {"articles": len(arts), "redirect_titles": len(titles) - len(arts), "ok": 0, "skip": 0, "empty": 0, "err": 0}
    with ThreadPoolExecutor(max_workers=max(1, threads)) as ex:
        for i, (t, res) in enumerate(zip(titles, ex.map(lambda t: _fetch_title(t, a_, b_), titles))):
            tot[res] += 1
            if res != "skip" and (i < 80 or i % 50 == 0):
                print(f"{i + 1:>5}/{len(titles)} {t[:50]:<50} {res}", flush=True)
    created = creation(arts)
    (RAW / "created.json").write_text(json.dumps(created, indent=1))
    tot["created"] = sum(v is not None for v in created.values())
    return tot


def creation(arts: list[str]) -> dict[str, str | None]:
    """The first revision's stamp per article (the page's creation; a renamed page keeps its history)."""
    out: dict[str, str | None] = {}
    cj = RAW / "created.json"
    if cj.exists():
        out.update(json.loads(cj.read_text()))
    for art in arts:
        if out.get(art):
            continue
        r = _wp({"action": "query", "titles": art, "redirects": "1", "prop": "revisions", "rvlimit": "1", "rvdir": "newer", "rvprop": "timestamp"})
        pages = r.get("query", {}).get("pages", [])
        rev = (pages[0].get("revisions") or [{}])[0] if pages else {}
        out[art] = rev.get("timestamp")
    return out


# ---- ingest ------------------------------------------------------------------------------------------------------------------------------
def _title_series(title: str) -> pd.Series | None:
    f = _pv_file(title)
    if not f.exists():
        return None
    j = json.loads(f.read_text())
    return pd.Series({pd.Timestamp(x["t"], tz="UTC"): int(x["v"]) for x in j["items"]}, dtype="int64")


def read_article(art: str, start: pd.Timestamp, end: pd.Timestamp, created: pd.Timestamp | None, redirect_titles: list[str] | None = None) -> tuple[pd.DataFrame, float | None]:
    """The day grid from the later of `start` and the creation: views = the article's + its redirects' (the old names), present = any
    title had the day; the second value the share of views that came in under a redirect."""
    own = _title_series(art)
    if own is None:
        return pd.DataFrame(columns=["day", "views", "present"]), None
    parts = [own] + [x for x in (_title_series(t) for t in (redirect_titles or [])) if x is not None]
    tot = pd.concat(parts, axis=1).sum(axis=1, min_count=1).sort_index() if len(parts) > 1 else own
    a0 = max(start, created.normalize()) if created is not None else start
    idx = pd.date_range(a0, end, freq="D", inclusive="left")
    if len(tot):
        idx = idx.union(tot.index[(tot.index >= a0) & (tot.index < end)])
    v = tot.reindex(idx)
    inside = v.dropna()
    own_in = own.reindex(inside.index).fillna(0)
    share = float(1.0 - own_in.sum() / inside.sum()) if inside.sum() > 0 else None
    return pd.DataFrame({"day": idx, "views": v.fillna(0).astype("int64").to_numpy(), "present": v.notna().to_numpy()}), share


def ingest(start: str = START, end: str | None = None, path: Path | None = None, out: Path | None = None, known_at_h: int | None = None) -> dict:
    out, known_at_h = (Path(out) if out else PARQUET), (KNOWN_AT_H if known_at_h is None else known_at_h)
    A = frozen(path)
    B = bases().set_index("base")
    cj = RAW / "created.json"
    created = json.loads(cj.read_text()) if cj.exists() else {}
    rj = RAW / "redirects.json"
    rd = json.loads(rj.read_text()) if rj.exists() else {}
    s0 = pd.Timestamp(start, tz="UTC")
    e = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now("UTC").normalize()
    parts = []
    shares: dict[str, float | None] = {}
    for base, art in zip(A["base"], A["article"]):
        if not art or base not in B.index:
            continue
        c = created.get(art)
        d, shares[art] = read_article(art, s0, e, pd.Timestamp(c).tz_convert("UTC") if c else None, rd.get(art))
        if not len(d):
            continue
        for sym in B.loc[base, "symbols"].split():
            p = d.copy()
            p.insert(0, "article", art)
            p.insert(0, "symbol", sym)
            p.insert(0, "base", base)
            parts.append(p)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS[:-1])
    df["ts_known"] = pd.DatetimeIndex(df["day"]) + pd.Timedelta(hours=known_at_h) if len(df) else pd.DatetimeIndex([], tz="UTC")
    for c in ("base", "symbol", "article"):
        df[c] = df[c].astype("category")
    df = df.sort_values(["symbol", "day"], kind="mergesort").reset_index(drop=True)[COLS]
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    (RAW / "redirect_share.json").write_text(json.dumps(shares, indent=1))
    return {"articles": int(df["article"].nunique()), "symbols": int(df["symbol"].nunique()), "rows": len(df), "first": str(df["day"].min()) if len(df) else None,
            "last": str(df["day"].max()) if len(df) else None, "known_at_h": known_at_h, "redirect_titles": int(sum(len(v) for v in rd.values())),
            "redirect_share_median": float(np.nanmedian([v for v in shares.values() if v is not None])) if any(v is not None for v in shares.values()) else None, "file": str(out)}


def load(path: Path | str | None = None) -> pd.DataFrame:
    d = pd.read_parquet(path or PARQUET)
    for c in ("base", "symbol", "article"):
        d[c] = d[c].astype(str)
    return d


# ---- the deviation form -----------------------------------------------------------------------------------------------------------------
def dev(V: pd.DataFrame) -> pd.DataFrame:
    """cb_ext's DEV form on a daily grid of log(1 + views): the deviation from the trailing month over its sd, ≥ MIN_MONTH_D days present."""
    X = np.log1p(V)
    m = X.rolling(MONTH_D, min_periods=MIN_MONTH_D).mean()
    sd = X.rolling(MONTH_D, min_periods=MIN_MONTH_D).std()
    return (X - m) / sd.where(sd > 0)


# ---- audit -----------------------------------------------------------------------------------------------------------------------------
def audit(today: pd.Timestamp | None = None, path: Path | None = None, out: Path | None = None, articles_csv: Path | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    path, out, articles_csv = (Path(path) if path else PARQUET), (Path(out) if out else OUT), (Path(articles_csv) if articles_csv else ARTICLES)
    A = frozen(articles_csv)
    B = bases()
    d = load(path) if Path(path).exists() else pd.DataFrame(columns=COLS)
    cj = RAW / "created.json"
    created = json.loads(cj.read_text()) if cj.exists() else {}
    rj, sj = RAW / "redirects.json", RAW / "redirect_share.json"
    rd = json.loads(rj.read_text()) if rj.exists() else {}
    rshare = json.loads(sj.read_text()) if sj.exists() else {}
    cover = B.merge(A[["base", "article"] + [c for c in ("source", "note") if c in A.columns]], on="base", how="left").fillna({"article": ""})
    cover["has_article"] = cover["article"].astype(bool)
    cover["strict"] = cover["has_article"] & (cover["source"] != "proxy") if "source" in cover.columns else cover["has_article"]   # a meme's namesake is attention to the thing, not the coin
    # per base: the extent and the level
    rows = []
    one = d.drop_duplicates(["base", "day"])
    for _, r0 in cover.iterrows():
        g = one[one["base"] == r0["base"]]
        r = {"base": r0["base"], "symbols": r0["symbols"], "article": r0["article"], "created": (created.get(r0["article"]) or "")[:10] if r0["article"] else "",
             "days": int(len(g)), "first_day": str(g["day"].min().date()) if len(g) else None, "last_day": str(g["day"].max().date()) if len(g) else None,
             "median_views": float(g["views"].median()) if len(g) else None, "share_zero": float((g["views"] == 0).mean()) if len(g) else None,
             "share_present": float(g["present"].mean()) if len(g) else None,
             "redirects": len(rd.get(r0["article"], [])) if r0["article"] else None, "redirect_share": rshare.get(r0["article"]) if r0["article"] else None}
        for f in ("F1", "F2", "F3", "F4", "F5"):
            fa, fb = folds.bounds(f, embargoed=False)
            n_days = (fb - fa).days
            inside = g[(g["day"] >= fa) & (g["day"] < fb)]
            r[f"cover_{f}"] = float(len(inside) / n_days) if n_days else None
        rows.append(r)
    per = pd.DataFrame(rows)
    # the sets
    sets = {}
    for nm, mask in (("twelve", cover["twelve"]), ("F1+F2 members", cover["F1+F2"]), ("F3+F4 members", cover["F3+F4"]), ("all bases", cover["base"].notna())):
        sub = cover[mask]
        sets[nm] = {"bases": int(len(sub)), "with_article": int(sub["has_article"].sum()), "share": float(sub["has_article"].mean()) if len(sub) else None,
                    "strict": int(sub["strict"].sum()), "share_strict": float(sub["strict"].mean()) if len(sub) else None}
    # the members with an article per block (R62's breadth)
    m = cb.member_symbols()
    m["base"] = m["symbol"].map(cb.base)
    art_of = dict(zip(cover["base"], cover["article"]))
    strict_of = dict(zip(cover["base"], cover["strict"]))
    first_day = {b: pd.Timestamp(v, tz="UTC") for b, v in zip(per["base"], per["first_day"]) if v}
    blk = []
    for (blk_start, fs), g in m.groupby(["block", "folds"], sort=True):
        n = len(g)
        with_art = sum(bool(art_of.get(b)) for b in g["base"])
        live = sum(bool(art_of.get(b)) and b in first_day and first_day[b] <= blk_start for b in g["base"])
        blk.append({"block": str(blk_start.date()), "folds": fs, "members": n, "with_article": with_art, "strict": int(sum(bool(strict_of.get(b)) for b in g["base"])),
                    "article_live_at_block_start": live})
    blocks = pd.DataFrame(blk)
    # the DEV form, within name and across names
    stats = {}
    if len(one):
        V = one.pivot(index="day", columns="base", values="views").sort_index()
        D = dev(V)
        within = {}
        for b in D.columns:
            x = D[b].dropna()
            if len(x) >= 60:
                within[b] = {"sd": float(x.std()), "acf1": float(x.autocorr(1)), "acf7": float(x.autocorr(7)), "share_abs_ge_2": float((x.abs() >= 2).mean())}
        W = pd.DataFrame(within).T
        corr = D.corr(min_periods=120)
        offd = corr.where(~np.eye(len(corr), dtype=bool)).stack()
        # the first principal share of the cross-name correlation: one attention factor or many
        c2 = corr.dropna(how="all").dropna(axis=1, how="all").fillna(0)
        ev = np.linalg.eigvalsh(c2.to_numpy()) if len(c2) else np.array([])
        stats = {"names_with_60_days": int(len(W)), "within_sd_median": float(W["sd"].median()) if len(W) else None,
                 "acf1_median": float(W["acf1"].median()) if len(W) else None, "acf7_median": float(W["acf7"].median()) if len(W) else None,
                 "share_abs_ge_2_median": float(W["share_abs_ge_2"].median()) if len(W) else None,
                 "cross_name_corr_mean": float(offd.mean()) if len(offd) else None, "cross_name_corr_median": float(offd.median()) if len(offd) else None,
                 "first_eigen_share": float(ev[-1] / ev.sum()) if len(ev) and ev.sum() > 0 else None,
                 "views_median_of_medians": float(per["median_views"].median()) if per["median_views"].notna().any() else None,
                 "share_zero_median": float(per["share_zero"].median()) if per["share_zero"].notna().any() else None}
        W_out = W.reset_index().rename(columns={"index": "base"})
    else:
        W_out = pd.DataFrame()
    pr = probes()
    md = [f"# Wikipedia pageviews per name — the source audit (`ft2 wiki audit`)\n\ngenerated {today:%Y-%m-%d %H:%M} UTC · articles frozen in `{articles_csv}` "
          f"· {len(d):,} rows in `{path}` · ts_known = day + {KNOWN_AT_H} h\n",
          "\n## The covered bases, by set — the registration's counts\n", pd.DataFrame(sets).T.reset_index().rename(columns={"index": "set"}).to_markdown(index=False),
          "\n\n## The members with an article per block (R62's breadth; `article_live_at_block_start` = created and with a day of views by the block's start)\n",
          blocks.to_markdown(index=False) if len(blocks) else "(no members)",
          "\n\n## The known-at — the probes (the server's `Date` against the last day the API holds)\n",
          pd.DataFrame([{k: v for k, v in p.items() if k != "views"} for p in pr]).to_markdown(index=False) if pr else "(no probe yet)",
          "\n\n## The deviation from the trailing month on log views (the DEV form), within and across names\n", "```\n" + json.dumps(stats, indent=1) + "\n```\n",
          "\n## The redirects — pageviews are counted under the title of the day; a renamed article's history sits under its old names, summed in\n",
          f"titles fetched beside the articles: {sum(len(v) for v in rd.values())}; the share of views that came in under a redirect — median "
          f"{per['redirect_share'].median():.3f}, max {per['redirect_share'].max():.3f} ({per.loc[per['redirect_share'].idxmax(), 'base'] if per['redirect_share'].notna().any() else '—'}); "
          f"days present (any title) — median {per['share_present'].median():.3f}, min {per['share_present'].min():.3f}\n" if per["redirect_share"].notna().any() else "(no redirects fetched)\n",
          "\n## Per base\n", per.to_markdown(index=False, floatfmt=".2f"),
          "\n\n## Within-name statistics of the deviation\n", W_out.to_markdown(index=False, floatfmt=".3f") if len(W_out) else "(none)", "\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(md))
    (out.with_suffix(".json")).write_text(json.dumps({"sets": sets, "blocks": blocks.to_dict("records"), "stats": stats, "probes": [{k: v for k, v in p.items() if k != "views"} for p in pr],
                                                        "per_base": per.to_dict("records"), "known_at_h": KNOWN_AT_H, "generated": str(today)}, indent=1, default=str))
    return str(out)


def main(action: str, start: str = START, end: str | None = None) -> None:
    if action == "names":
        n = names()
        print(f"wrote {NAMES_CSV}: {n['base'].nunique()} bases, {n['name'].notna().sum()} names ({(n['source'] == 'coingecko').sum()} CoinGecko, {n['source'].isin(['upbit', 'bithumb']).sum()} the venues')")
    elif action == "articles":
        C = articles()
        P = pd.read_csv(PICK_CSV)
        print(f"wrote {CANDIDATES_CSV} ({len(C)} candidates, {C['exists'].sum()} exist) and {PICK_CSV}: {P['pick'].astype(bool).sum()} of {len(P)} bases with a proposed article")
    elif action == "probe":
        print(json.dumps({k: v for k, v in probe().items() if k != "views"}, indent=1))
    elif action == "fetch":
        print(json.dumps(fetch(start, end)))
    elif action == "ingest":
        print(json.dumps(ingest(start, end)))
    elif action == "audit":
        print(f"wrote {audit()}")
    else:
        raise SystemExit(f"wiki: unknown action {action}")
