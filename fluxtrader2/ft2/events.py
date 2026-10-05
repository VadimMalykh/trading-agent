"""P8 (PLAN §9 #8) — scheduled and announced per-name events as a data source: `ft2 events fetch|ingest|inventory`.

unlocks    DefiLlama's dataset bucket (defillama-datasets.llama.fi, free, keyless; the API's own `emissions` routes are paid):
           `emissionsIndex` is one JSON holding every covered token's vesting schedule — past and future events, each a
           cliff (a block of tokens released at one time) or a change of a linear release rate, with the recipient.
known-at   today's file is the schedule as DefiLlama describes it NOW: a token may have been added after its unlocks, and a
           date may have been corrected after the fact. The Wayback Machine's snapshots of defillama.com/unlocks embed the
           same list as it was published that day (2023-03 → today), so `inventory` measures, snapshot by snapshot, how many of
           the cliffs that followed were already there with the same day and size — and `unlock_asof` is the schedule as it
           was known, the only table a registration may build a feature from.
binance    the exchange's announcement lists (www.binance.com/bapi/composite/v1/public/cms; reachable from the work VM, not
           from every network): catalog 48 "New Cryptocurrency Listing" (2017 →), 161 "Delisting" (2022-02 →), 49 "Latest
           Binance News" (the monitoring-tag notices). An article's `releaseDate` is its publication time; the title names
           the contracts or tokens, and where it says "Multiple" the article itself is fetched.
raw        data/raw/external/defillama/emissionsIndex_<YYYYMMDD>.json.gz, …/defillama/wayback/<timestamp>.html.gz,
           data/raw/external/binance_cms/list_<catalog>_<YYYYMMDD>.json, …/binance_cms/detail/<code>.json
parquet    data/unlock_events.parquet  (pid, name, symbol, gecko_id, max_supply, ts, kind, recipient, category, tokens)
           data/unlock_asof.parquet    the same with `asof`, one copy of the schedule a snapshot
           data/binance_events.parquet (catalog, id, code, release, title, kind, symbol, effective), one row a symbol

No price is read anywhere in this module: the inventory counts events and compares dates.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds

RAW_LLAMA = data.RAW / "external" / "defillama"
WAYBACK = RAW_LLAMA / "wayback"
RAW_BN = data.RAW / "external" / "binance_cms"
FIRST = data.RAW / "external" / "binance" / "um_first_month.csv"
UNLOCKS = data.PROC / "unlock_events.parquet"
ASOF = data.PROC / "unlock_asof.parquet"
BINANCE = data.PROC / "binance_events.parquet"
REPORT = Path("output/events_inventory.md")
MEMBERS = {"pre": "screen_members_pre.csv", "f12": "screen_members.csv", "f34": "screen_members_f34.csv"}   # the screener's point-in-time universes
BLOCK = pd.Timedelta(days=30)
INDEX = "https://defillama-datasets.llama.fi/emissionsIndex"
CDX = "http://web.archive.org/cdx/search/cdx?url=defillama.com/unlocks&output=json&fl=timestamp,statuscode&filter=statuscode:200&collapse=timestamp:8"
SNAP = "http://web.archive.org/web/{ts}id_/https://defillama.com/unlocks"
CMS_LIST = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId={c}&pageNo={p}&pageSize=50"
CMS_DETAIL = "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}"
CATALOGS = {48: "listing", 161: "delisting", 49: "news"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36", "clienttype": "web"}
WB_UA = {"User-Agent": "ft2-research/1.0 (a source audit; one request every ten seconds)"}   # the Wayback Machine answers 429 to a browser's User-Agent sent by a script, and serves a plain one
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
REC_RE = (re.compile(r"^.*\bfrom (.+?) on \{timestamp\}", re.S), re.compile(r"of (.+?) tokens (?:were|will be) unlocked"))
QUOTES = ("USDT", "USDC", "BUSD", "USD", "FDUSD")
SYM_RE = re.compile(r"\b([A-Z0-9]{2,15}?)(USDT|USDC|BUSD|USD)\b")
MIN_PCT = 0.1                          # % of the maximum supply: a cliff smaller than this is dust (a tracked treasury transfer, a weekly drip)
DAY_TOL, AMT_TOL, MOVE_DAYS = 1, 0.05, 45   # known-at: the same day ±1, the same size ±5 %; "moved" = the same size within ±45 days
LEAD = pd.Timedelta(days=7)            # point-in-time: the last snapshot at least this long before the event
PERP_KINDS = ("perp_launch", "perp_delist")


def _get(u: str, timeout: int = 90, retries: int = 4, headers: dict = UA) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=headers), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(3 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{u}: {last!r}")


def _text(body: bytes) -> str:
    return (gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body).decode("utf-8", "replace")


# ---- the unlock schedules -----------------------------------------------------------------------------------------------------
def parse_page(body: bytes) -> list[dict]:
    """defillama.com/unlocks as served (gzip or not) → the protocols embedded in the page. Raises when it is not that page."""
    m = NEXT_RE.search(_text(body))
    if not m:
        raise ValueError("no __NEXT_DATA__ on the page")
    d = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("data")
    if not isinstance(d, list) or not d:
        raise ValueError("no protocol list in the page's data")
    return d


def parse_index(body: bytes) -> list[dict]:
    d = json.loads(_text(body)).get("data")
    if not isinstance(d, list) or not d:
        raise ValueError("no protocol list in the index")
    return d


def _symbol(p: dict) -> str:
    s, tp = p.get("tSymbol"), p.get("tokenPrice")
    if not s and isinstance(tp, list) and tp and isinstance(tp[0], dict):
        s = tp[0].get("symbol")
    return str(s).upper() if s else ""


def schedule(protocols: list[dict]) -> pd.DataFrame:
    """One row an event. kind: `cliff` (tokens = the block released) or `linear` (tokens = the new weekly rate). An older page
    has no `unlockType`: there a description that does not begin "Linear unlock" is a cliff."""
    rows = []
    for p in protocols:
        pid, ms = str(p.get("protocolId") or p.get("name")), p.get("maxSupply")
        head = (pid, str(p.get("name") or ""), _symbol(p), str(p.get("gecko_id") or ""), float(ms) if ms else np.nan)
        for e in p.get("events") or []:
            desc = e.get("description") or ""
            kind = "cliff" if (e.get("unlockType") or ("linear" if desc.startswith("Linear unlock") else "cliff")) == "cliff" else "linear"
            n = [float(x) for x in (e.get("noOfTokens") or []) if x is not None]
            rec = next((m.group(1).strip() for m in (r.search(desc) for r in REC_RE) if m), "")
            try:
                ts = float(e.get("timestamp"))
            except (TypeError, ValueError):
                continue
            rows.append((*head, ts, kind, rec, str(e.get("category") or ""), (n[0] if kind == "cliff" else n[-1]) if n else np.nan))
    df = pd.DataFrame(rows, columns=["pid", "name", "symbol", "gecko_id", "max_supply", "ts", "kind", "recipient", "category", "tokens"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df


def cliff_days(sched: pd.DataFrame, by: tuple = ()) -> pd.DataFrame:
    """The cliffs of one protocol on one UTC day as one event: tokens summed, as a % of the maximum supply."""
    c = sched[(sched["kind"] == "cliff") & (sched["tokens"] > 0)].assign(day=lambda x: x["ts"].dt.floor("D"))
    g = c.groupby([*by, "pid", "day"], observed=True, sort=True)
    out = g.agg(tokens=("tokens", "sum"), name=("name", "first"), symbol=("symbol", "first"), max_supply=("max_supply", "first"),
                recipients=("recipient", lambda s: "; ".join(sorted(set(s) - {""})))).reset_index()
    out["pct_max"] = 100 * out["tokens"] / out["max_supply"]
    return out


def base(perp: str) -> str:
    """A perpetual's symbol → the token's ticker: 1000PEPEUSDT → PEPE."""
    return re.sub(r"^(1000000|1000|1M)(?=[A-Z])", "", re.sub(r"(USDT|USDC|BUSD)$", "", perp.upper()))


def align(asof: pd.DataFrame, fin: pd.DataFrame) -> pd.DataFrame:
    """A snapshot's protocols under today's ids. DefiLlama re-keys a protocol over the years (Arbitrum 2785 → 3777, Aave 111 →
    parent#aave), so a snapshot's protocol is found in today's file by its id, else its ticker, else its CoinGecko id, else its
    name; one found by none keeps its own id (it is no longer in the file)."""
    t = fin.drop_duplicates("pid")
    by = [dict(zip(t["pid"], t["pid"])), {k: p for p, k in zip(t["pid"], t["symbol"]) if k}, {k: p for p, k in zip(t["pid"], t["gecko_id"]) if k},
          {k.lower(): p for p, k in zip(t["pid"], t["name"]) if k}]
    key = asof["pid"].map(by[0]).fillna(asof["symbol"].map(by[1])).fillna(asof["gecko_id"].map(by[2])).fillna(asof["name"].str.lower().map(by[3])).fillna(asof["pid"])
    return asof.assign(pid=key)


def fill_symbols(fin: pd.DataFrame, asof: pd.DataFrame) -> pd.DataFrame:
    """Today's file names a ticker only where it has a price; a protocol without one takes the ticker its latest snapshot gave it.
    `asof` aligned."""
    last = asof[asof["symbol"] != ""].sort_values("asof").drop_duplicates("pid", keep="last").set_index("pid")["symbol"]
    return fin.assign(symbol=fin["symbol"].where(fin["symbol"] != "", fin["pid"].map(last).fillna("")))


def _match(ev: pd.DataFrame, pool: pd.DataFrame) -> pd.Series:
    """Each event of `ev` (pid, day, tokens) against the `pool` of the same protocol: `same` (a cliff within ±1 day and ±5 % of
    the size), `amount` (within ±1 day, another size), `moved` (the size within ±45 days), `absent`."""
    dn = lambda x: ((x - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(days=1)).to_numpy()   # noqa: E731 — days as numbers
    by = {k: (dn(g["day"]), g["tokens"].to_numpy()) for k, g in pool.groupby("pid", observed=True)}
    out = []
    for pid, day, tok in zip(ev["pid"], dn(ev["day"]), ev["tokens"].to_numpy()):
        if pid not in by:
            out.append("absent")
            continue
        d, t = by[pid]
        gap = np.abs(d - day)
        size = np.abs(t - tok) <= AMT_TOL * tok
        out.append("same" if (size & (gap <= DAY_TOL)).any() else "amount" if (gap <= DAY_TOL).any() else "moved" if (size & (gap <= MOVE_DAYS)).any() else "absent")
    return pd.Series(out, index=ev.index, dtype=object)


def known_at(asof: pd.DataFrame, final: pd.DataFrame, windows=((0, 30), (30, 90)), min_pct: float = MIN_PCT) -> pd.DataFrame:
    """Per snapshot and window of days after it, on the protocols the snapshot covers: the cliffs of today's schedule dated in
    the window, and how the snapshot had them; and the reverse — the cliffs the snapshot dated there that today's schedule
    does not have as dated (`snap_unmatched`: announced, then moved, resized or dropped). A window the page does not reach is
    left out: from 2025-05-26 the page carries only the next 30 days, before that the whole schedule. `asof`, `final`:
    cliff_days tables, `asof` with the snapshot's time. Pure: no network."""
    rows = []
    for at, snap in asof.groupby("asof", sort=True):
        fin = final[final["pid"].isin(set(snap["pid"]))]
        reach = (snap["day"].max() - at) / pd.Timedelta(days=1)
        for lo, hi in windows:
            if reach < hi - 2:
                continue
            a, b = at + pd.Timedelta(days=lo), at + pd.Timedelta(days=hi)
            f = fin[(fin["day"] > a) & (fin["day"] <= b) & (fin["pct_max"] >= min_pct)]
            s = snap[(snap["day"] > a) & (snap["day"] <= b) & (snap["pct_max"] >= min_pct)]
            st = _match(f, snap).value_counts() if len(f) else pd.Series(dtype=int)
            rows.append({"asof": at, "window": f"{lo}-{hi}d", "protocols": snap["pid"].nunique(), "final": len(f), **{k: int(st.get(k, 0)) for k in ("same", "amount", "moved", "absent")},
                         "snap": len(s), "snap_unmatched": int((_match(s, fin) != "same").sum()) if len(s) else 0})
    return pd.DataFrame(rows, columns=["asof", "window", "protocols", "final", "same", "amount", "moved", "absent", "snap", "snap_unmatched"])


def point_in_time(asof: pd.DataFrame, final: pd.DataFrame, covered: dict, lead: pd.Timedelta = LEAD) -> pd.Series:
    """Each cliff of today's schedule against the LAST snapshot taken at least `lead` before it: `same` / `amount` / `moved` /
    `absent` as in `_match`, `uncovered` when that snapshot does not list the protocol, `out_of_reach` when the event lies
    beyond the last day that page dates anything (a page of 2025-05-26 or later carries 30 days), `no_snapshot` when none is that old.
    `covered`: snapshot time → the protocols on that page (a protocol can be listed with no cliff)."""
    stamps = pd.DatetimeIndex(sorted(covered))
    out = pd.Series("no_snapshot", index=final.index, dtype=object)
    if not len(stamps) or not len(final):
        return out
    pos = stamps.searchsorted(pd.DatetimeIndex(final["day"] - lead), side="right") - 1
    for i in np.unique(pos[pos >= 0]):
        at = stamps[i]
        ev = final[pos == i]
        snap = asof[asof["asof"] == at]
        cov = ev["pid"].isin(covered[at])
        far = cov & (ev["day"] > snap["day"].max() + pd.Timedelta(days=1)) if len(snap) else cov & False
        out.loc[ev.index[~cov]] = "uncovered"
        out.loc[ev.index[far]] = "out_of_reach"
        if (cov & ~far).any():
            out.loc[ev.index[cov & ~far]] = _match(ev[cov & ~far], snap)
    return out


def promised(acd: pd.DataFrame, stamps, lead: pd.Timedelta = LEAD) -> pd.DataFrame:
    """The point-in-time event table: each cliff as the LAST snapshot taken at least `lead` before it dated it — what a feature
    would have been built from, whatever today's schedule says. `acd`: cliff_days by snapshot; `stamps`: every snapshot's time."""
    st = pd.DatetimeIndex(sorted(stamps))
    nxt = pd.Series([*st[1:], pd.Timestamp("2200-01-01", tz="UTC")], index=st)
    cut = acd["day"] - lead
    return acd[(cut >= acd["asof"]) & (cut < acd["asof"].map(nxt))]


# ---- Binance's announcements --------------------------------------------------------------------------------------------------
def _bare(s: str) -> list[str]:
    return [t for t in (x.strip() for x in re.split(r",|&| and ", s)) if re.fullmatch(r"[A-Z0-9]{2,15}", t) and not t.isdigit()]


def _contracts(t: str) -> tuple[list[str], bool]:
    """The USDT-quoted perpetuals a title names, as bases (RAYUSDT → RAY; a bare CELO after "USDT-Margined" → CELO), and
    whether it names any contract with a quote at all (so that a BUSD-only title is not taken for an empty one)."""
    quoted = SYM_RE.findall(t) + [(b, "USDT") for b in re.findall(r"\b([A-Z0-9]{2,15})/USDT\b", t)]
    out = [b for b, q in quoted if q == "USDT"]
    for rx in (r"(?:USDT-Margined|USDⓈ-Margined|USDⓈ-M|USDT-M)\s+(.+?)\s+(?:Perpetual|Contract)", r"(?:Launch|Delist)\s+(.+?)\s+(?:USDT-Margined|USDⓈ-M)", r"USDT-Margined Perpetual Contract.* for ([A-Z0-9]{2,15})$"):
        m = re.search(rx, t)
        for tok in _bare(m.group(1)) if m else []:
            fm = SYM_RE.fullmatch(tok)
            if fm and fm.group(2) == "USDT":
                out.append(fm.group(1))
            elif not fm and tok not in QUOTES:
                out.append(tok)
    return list(dict.fromkeys(out)), bool(quoted)


def parse_title(title: str, catalog: int) -> tuple[str, list[str]]:
    """An announcement's title → (kind, tickers). kind: `perp_launch` / `perp_delist` (a USDT-quoted perpetual), `perp_other`
    (BUSD, USDC or coin-margined only, delivery contracts), `spot_list`, `spot_delist`, `monitoring`, `other`. A perpetual's
    ticker is the contract's base as written (1000PEPE). A heuristic: the inventory says how much of it the archive confirms."""
    t = title
    fut = bool(re.search(r"Futures|Perpetual", t))
    paren = re.findall(r"\(([A-Z0-9]{1,12})\)", t)                 # a date in brackets has hyphens and is not one
    if "Monitoring Tag" in t:
        return "monitoring", list(dict.fromkeys(x for x in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", t.split("Monitoring Tag", 1)[1]) if x not in QUOTES))
    if re.search(r"Cancel|Postpone", t):
        return "other", []
    names, quoted = _contracts(t)
    coin_only = (bool(re.search(r"COIN-M|Coin-Margined|BUSD-Margined|USDC-Margined", t)) and not re.search(r"USDT|USDⓈ", t)) or (quoted and not names)
    delist = catalog == 161 or bool(re.search(r"\bDelist|\bRemov", t))
    if fut and re.search(r"Quarterly|Delivery|Options|TradFi|Equity|Pre-IPO|Index\b|Copy Trading", t):
        return "other", []
    if delist:
        if fut:
            return ("perp_other", []) if coin_only else ("perp_delist", names)
        if re.match(r"Binance Will Delist ", t) and not re.search(r"Margin|Pairs|Alpha|Loan|Earn|Borrow", t):
            return "spot_delist", _bare(re.split(r" on \d| on [A-Z][a-z]| \(\d", t[len("Binance Will Delist "):])[0]) or paren
        return "other", []
    if catalog == 48:
        if fut and re.search(r"Launch|Will Be Available|Will Add|Adds|Will List|Lists", t):
            return ("perp_other", []) if coin_only else ("perp_launch", names or paren)
        if (re.search(r"Binance Will List |Binance Lists ", t) and not re.search(r"Pairs|Margin|Loan|Futures", t)) or re.search(r"^Introducing .*(HODLer Airdrops|Launchpool|Megadrop)", t):
            return "spot_list", paren
    return "other", []


def _effective(title: str):
    m = re.search(r"(20\d\d-\d\d-\d\d)\)?\s*$", title) or re.search(r"\((20\d\d-\d\d-\d\d)", title) or re.search(r" on (20\d\d-\d\d-\d\d)", title)
    return pd.Timestamp(m.group(1), tz="UTC") if m else pd.NaT


def detail_symbols(d: dict) -> list[str]:
    """The USDT contracts an article names: its summary line first (it is the list), the body otherwise."""
    for part in (d.get("seoDesc") or "", d.get("body") or ""):
        s = list(dict.fromkeys(b for b, q in SYM_RE.findall(part) if q == "USDT"))
        if s:
            return s
    return []


def announcements(lists: dict[int, list[dict]], details: dict[str, dict] | None = None) -> pd.DataFrame:
    """The lists → one row a (article, ticker); an article with no ticker keeps one row with symbol ''."""
    rows = []
    for c, arts in lists.items():
        for a in arts:
            kind, syms = parse_title(a["title"], c)
            if kind in PERP_KINDS and not syms and details and a["code"] in details:
                syms = detail_symbols(details[a["code"]])
            for s in syms or [""]:
                rows.append({"catalog": c, "id": int(a["id"]), "code": a["code"], "release": pd.Timestamp(int(a["releaseDate"]), unit="ms", tz="UTC"), "title": a["title"],
                             "kind": kind, "symbol": s, "effective": _effective(a["title"])})
    return pd.DataFrame(rows).drop_duplicates(["catalog", "id", "symbol"]).sort_values(["release", "id", "symbol"]).reset_index(drop=True)


# ---- fetch --------------------------------------------------------------------------------------------------------------------
def _stamp() -> str:
    return pd.Timestamp.now("UTC").strftime("%Y%m%d")


def fetch_llama() -> Path:
    RAW_LLAMA.mkdir(parents=True, exist_ok=True)
    body = _get(INDEX, timeout=300)
    ps = parse_index(body)                                         # it parses, or it is not kept
    dest = RAW_LLAMA / f"emissionsIndex_{_stamp()}.json.gz"
    dest.write_bytes(gzip.compress(_text(body).encode()))
    print(f"defillama: {len(ps)} protocols → {dest}", flush=True)
    return dest


def wayback_list() -> list[str]:
    return [x[0] for x in json.loads(_get(CDX, timeout=180, headers=WB_UA))[1:]]


def by_month_first(stamps: list[str]) -> list[str]:
    """The first snapshot of each calendar month, then the rest: a throttled fetch that is cut short still spans the years."""
    first = list({ts[:6]: ts for ts in sorted(stamps, reverse=True)}.values())[::-1]
    return first + [ts for ts in sorted(stamps) if ts not in set(first)]


def fetch_wayback(pause: float = 10.0, cool: float = 300.0, reverse: bool = False) -> dict:
    """The listed snapshots of the page (one a day at most) → WAYBACK/<ts>.html.gz; cached; a snapshot that is not the page is
    skipped. Measured 2026-10-05: with a browser's User-Agent the Wayback Machine served 6 pages in 90 minutes and answered 429
    to the rest, from two addresses; with a plain one (`WB_UA`) each page comes in two seconds. A 429 is still not retried: the
    fetch waits `cool` seconds and goes on; a second run picks up what was skipped. `reverse`: the months from the newest."""
    WAYBACK.mkdir(parents=True, exist_ok=True)
    n = {"ok": 0, "skip": 0, "err": 0, "throttled": 0}
    stamps = by_month_first(wayback_list())
    k = len({ts[:6] for ts in stamps})
    for ts in (stamps[:k][::-1] + stamps[k:] if reverse else stamps):
        dest = WAYBACK / f"{ts}.html.gz"
        if dest.exists():
            n["skip"] += 1
            continue
        try:
            body = _get(SNAP.format(ts=ts), timeout=180, retries=1, headers=WB_UA)
            parse_page(body)
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(gzip.compress(_text(body).encode()))
            tmp.rename(dest)
            n["ok"] += 1
            print(f"  ok {ts}", flush=True)
        except Exception as e:  # noqa: BLE001
            hot = "429" in repr(e)
            n["throttled" if hot else "err"] += 1
            print(f"  {'429' if hot else 'err'} {ts}" + ("" if hot else f": {e!r}"[:300]), file=sys.stderr, flush=True)
            if hot:
                time.sleep(cool)
        time.sleep(pause)
    print(f"wayback: {n}", flush=True)
    return n


def _latest(d: Path, pattern: str) -> Path | None:
    files = sorted(d.glob(pattern))
    return files[-1] if files else None


def _lists() -> dict[int, list[dict]]:
    out = {}
    for c in CATALOGS:
        f = _latest(RAW_BN, f"list_{c}_*.json")
        if f is None:
            raise SystemExit(f"events: no announcement list for catalog {c} — run `ft2 events fetch --source binance` first")
        out[c] = json.loads(f.read_text())
    return out


def _details() -> dict[str, dict]:
    return {f.stem: json.loads(f.read_text()) for f in (RAW_BN / "detail").glob("*.json")}


def fetch_binance(pause: float = 0.5) -> dict:
    (RAW_BN / "detail").mkdir(parents=True, exist_ok=True)
    n = {}
    for c in CATALOGS:
        arts, p = [], 1
        while True:
            page = json.loads(_get(CMS_LIST.format(c=c, p=p)))["data"]["catalogs"]
            page = page[0]["articles"] if page else []
            if not page:
                break
            arts += [{k: a[k] for k in ("id", "code", "title", "releaseDate")} for a in page]
            p += 1
            time.sleep(pause)
        arts = list({a["id"]: a for a in arts}.values())
        (RAW_BN / f"list_{c}_{_stamp()}.json").write_text(json.dumps(arts))
        n[CATALOGS[c]] = len(arts)
    for c, arts in _lists().items():                               # a perpetual's article that names its contracts only inside
        for a in arts:
            kind, syms = parse_title(a["title"], c)
            dest = RAW_BN / "detail" / f"{a['code']}.json"
            if kind in PERP_KINDS and not syms and not dest.exists():
                d = json.loads(_get(CMS_DETAIL.format(code=a["code"])))["data"]
                dest.write_text(json.dumps({k: d.get(k) for k in ("id", "code", "title", "publishDate", "lastUpdateTime", "seoDesc", "body")}))
                n["details"] = n.get("details", 0) + 1
                time.sleep(pause)
    print(f"binance: {n}", flush=True)
    return n


def fetch_first_months(workers: int = 16) -> pd.DataFrame:
    """The archive's own record of when a contract began: the first monthly 1d-klines file of every USDⓈ-M symbol."""
    from . import archive
    root = "data/futures/um/monthly/klines/"
    syms = [s for s in archive.list_prefixes(root) if re.fullmatch(r"[A-Z0-9]+USDT", s)]      # plain USDT perpetuals; a dated or a non-ASCII symbol is left out

    def one(s):
        ms = sorted(re.findall(r"-1d-(\d{4}-\d{2})\.zip$", "\n".join(archive.list_keys(f"{root}{s}/1d/")), re.M))
        return (s, ms[0] if ms else "", ms[-1] if ms else "")
    with ThreadPoolExecutor(workers) as ex:
        df = pd.DataFrame(list(ex.map(one, syms)), columns=["symbol", "first_month", "last_month"])
    FIRST.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(FIRST, index=False)
    print(f"archive: {len(df)} symbols → {FIRST}", flush=True)
    return df


# ---- ingest -------------------------------------------------------------------------------------------------------------------
def ingest() -> dict:
    f = _latest(RAW_LLAMA, "emissionsIndex_*.json.gz")
    if f is None:
        raise SystemExit("events ingest: no emissionsIndex — run `ft2 events fetch` first")
    fin = schedule(parse_index(f.read_bytes()))
    UNLOCKS.parent.mkdir(parents=True, exist_ok=True)
    fin.to_parquet(UNLOCKS, index=False)
    parts = []
    for w in sorted(WAYBACK.glob("*.html.gz")):
        try:
            ps = parse_page(w.read_bytes())
        except (ValueError, OSError, EOFError):                    # not the page, or a file still being written
            continue
        s = schedule(ps)
        at = pd.Timestamp(pd.to_datetime(w.name[:14], format="%Y%m%d%H%M%S"), tz="UTC")
        listed = pd.DataFrame({"pid": [str(p.get("protocolId") or p.get("name")) for p in ps], "name": [str(p.get("name") or "") for p in ps], "symbol": [_symbol(p) for p in ps], "gecko_id": "", "kind": "listed", "recipient": "", "category": ""})
        parts.append(pd.concat([s, listed[~listed["pid"].isin(set(s["pid"]))]], ignore_index=True).assign(asof=at))   # a protocol on the page with no event still counts as covered
    asof = pd.concat(parts, ignore_index=True) if parts else fin.iloc[:0].assign(asof=pd.Series(dtype="datetime64[ns, UTC]"))
    asof.to_parquet(ASOF, index=False)
    bn = announcements(_lists(), _details())
    bn.to_parquet(BINANCE, index=False)
    r = {"unlock_events": len(fin), "protocols": fin["pid"].nunique(), "unlock_asof": len(asof), "snapshots": asof["asof"].nunique(), "binance_events": len(bn), "articles": bn["id"].nunique()}
    print(f"events {r}", flush=True)
    return r


# ---- inventory ----------------------------------------------------------------------------------------------------------------
def fold_of(ts: pd.Series) -> pd.Series:
    out = pd.Series("before FP", index=ts.index, dtype=object)
    for f in folds.order(folds.FOLDS):
        a, b = folds.bounds(f, embargoed=False)
        out[(ts >= a) & (ts < b)] = f
    out[ts >= folds.bounds("F5", embargoed=False)[1]] = "after F5"
    return out


def members() -> pd.DataFrame:
    """The screener's point-in-time universes as (universe, block, symbol, ticker); a name is a member for the block's 30 days."""
    here = Path(__file__).parent
    parts = [pd.read_csv(here / f, usecols=["block", "symbol"]).assign(universe=u) for u, f in MEMBERS.items()]
    m = pd.concat(parts, ignore_index=True)
    m["block"] = pd.to_datetime(m["block"], utc=True)
    m["ticker"] = m["symbol"].map(base)
    return m


def in_blocks(ev: pd.DataFrame, when: str, mem: pd.DataFrame, on: str = "ticker") -> pd.DataFrame:
    """The events (column `key`) that fall on a name while it is a member. `on`: what the key is — the token's `ticker`
    (PEPE) or the contract, `perp` (1000PEPEUSDT)."""
    m = mem.rename(columns={"symbol": "perp"})[["universe", "block", "perp", "ticker"]].assign(key=lambda x: x[on]).drop(columns="ticker")
    j = ev.merge(m, on="key")
    return j[(j[when] >= j["block"]) & (j[when] < j["block"] + BLOCK)]


def _order(t: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["before FP", *folds.order(folds.FOLDS), "after F5"] if c in t.columns]
    return t[cols]


def inventory(pairs: list[str], out: Path = REPORT, network: bool = True) -> str:
    fin, asof, bn, mem = pd.read_parquet(UNLOCKS), pd.read_parquet(ASOF), pd.read_parquet(BINANCE), members()
    n_blank = int((fin.groupby("pid")["symbol"].first() == "").sum())
    asof = align(asof, fin)
    fin = fill_symbols(fin, asof)
    now = pd.Timestamp.now("UTC")
    md = ["# Scheduled and announced per-name events as fetched (`ft2 events inventory`)\n",
          f"generated {now:%Y-%m-%d %H:%M} UTC · {UNLOCKS}, {ASOF}, {BINANCE} · no price is read here: events are counted and dates compared\n"]

    # 1 — the schedules as they are today
    cd = cliff_days(fin)
    big = cd[cd["pct_max"] >= MIN_PCT]
    md += ["\n## 1. Unlock schedules today (DefiLlama `emissionsIndex`)\n",
           f"\n{fin['pid'].nunique()} protocols, {int((fin.groupby('pid')['symbol'].first() != '').sum())} with a ticker ({n_blank} have none in the file; a snapshot's ticker fills what it can); {len(fin):,} events "
           f"({int((fin['kind'] == 'cliff').sum()):,} cliffs, {int((fin['kind'] == 'linear').sum()):,} linear-rate changes), {fin['ts'].min():%Y-%m-%d} → {fin['ts'].max():%Y-%m-%d}. "
           f"A protocol's cliffs on one UTC day are one event: {len(cd):,} cliff days, {len(big):,} of at least {MIN_PCT} % of the maximum supply.\n",
           "\nCliff days by size (% of the maximum supply) and year:\n",
           pd.crosstab(pd.cut(cd["pct_max"], [0, 0.1, 0.5, 1, 5, np.inf], labels=["<0.1", "0.1–0.5", "0.5–1", "1–5", "≥5"]), cd["day"].dt.year).to_markdown(), "\n"]

    # 2 — which of our names have a schedule
    tick = fin[fin["symbol"] != ""].groupby("symbol")["pid"].nunique()
    rows = []
    unis = {**{u: sorted(set(g["symbol"])) for u, g in mem.groupby("universe")}, "twelve": list(pairs)}
    for u, names in unis.items():
        t = pd.Series({n: base(n) for n in names})
        rows.append({"universe": u, "names": len(t), "with a schedule": int(t.isin(tick.index).sum()), "ticker on 2+ protocols": int(t.map(tick).fillna(0).gt(1).sum())})
    md += ["\n## 2. Our names with a schedule (a perpetual's ticker = a protocol's ticker)\n", pd.DataFrame(rows).to_markdown(index=False), "\n",
           f"\n- the twelve without one: {', '.join(n for n in pairs if base(n) not in tick.index) or 'none'}\n"]

    # 3 — cliffs on our names, by fold
    big = big.assign(key=big["symbol"], fold=fold_of(big["day"]))
    onm = in_blocks(big, "day", mem).drop_duplicates(["universe", "pid", "day"])
    on12 = big[big["key"].isin({base(p) for p in pairs})]
    t3 = _order(pd.concat([pd.crosstab(onm["universe"], onm["fold"]), pd.crosstab(pd.Series("twelve (any time)", index=on12.index), on12["fold"])]).fillna(0).astype(int))
    one = onm[onm["pct_max"] >= 1]
    first = fetch_first_months() if network else (pd.read_csv(FIRST, dtype=str).fillna("") if FIRST.exists() else None)
    if first is not None:                                          # a wider universe than the screener's: any USDT perpetual the archive holds, from its first month
        arch = first[first["symbol"].str.fullmatch(r"[A-Z0-9]+USDT") & (first["first_month"] != "")].assign(key=lambda x: x["symbol"].map(base), since=lambda x: pd.to_datetime(x["first_month"] + "-01", utc=True))
        arch = arch.rename(columns={"symbol": "perp"})[["key", "perp", "since"]]
        anyp = big.merge(arch, on="key")
        anyp = anyp[anyp["day"] >= anyp["since"] + BLOCK].drop_duplicates(["pid", "day"])
        t3 = _order(pd.concat([t3, pd.crosstab(pd.Series("any USDT perpetual, 30 d after its first month began", index=anyp.index), anyp["fold"])]).fillna(0).astype(int))
    md += [f"\n## 3. Cliff days of at least {MIN_PCT} % of the maximum supply on our names, by fold (today's schedule)\n",
           "\nOn a member while it is a member (the 30 days of its block); the twelve at any time:\n", t3.to_markdown(), "\n",
           f"\n- of the members' {len(onm)}: {len(one)} are at least 1 % of the maximum supply; {onm['perp'].nunique()} names, the ten with the most hold {int(onm.groupby('perp').size().nlargest(10).sum())}; median {onm['pct_max'].median():.2f} %\n"]
    if first is not None:
        md += [f"- on any USDT perpetual: {len(anyp)} on {anyp['perp'].nunique()} names, {int((anyp['pct_max'] >= 1).sum())} of at least 1 % (the archive keeps flat bars after a delisting, so a few fall on a contract that had stopped)\n"]

    # 4 — known-at on the Wayback Machine's snapshots
    if len(asof):
        covered = {at: set(g["pid"]) for at, g in asof.groupby("asof")}
        acd = cliff_days(asof[asof["kind"] == "cliff"], by=("asof",))
        k = known_at(acd, cd)
        k.to_csv(out.with_name("events_known_at.csv"), index=False)
        snaps = pd.Series({at: len(p) for at, p in covered.items()}).sort_index()
        reach = ((acd.groupby("asof")["day"].max() - acd.groupby("asof")["day"].max().index) / pd.Timedelta(days=1)).round()
        short = reach[reach < 60]
        md += [f"\n## 4. Known-at: the schedule as the Wayback Machine saw it ({len(snaps)} snapshots of defillama.com/unlocks, {snaps.index.min():%Y-%m-%d} → {snaps.index.max():%Y-%m-%d})\n",
               "\nProtocols on the page, by the snapshot's year (snapshots; fewest → most): " +
               "; ".join(f"{y}: {len(g)} snapshots, {g.min()} → {g.max()}" for y, g in snaps.groupby(snaps.index.year)) + "\n",
               f"\nHow far ahead a page dates its cliffs: {int((reach >= 60).sum())} snapshots carry the whole schedule (years); {len(short)} carry about 30 days"
               + (f", every one from {short.index.min():%Y-%m-%d} on" if len(short) and short.index.min() > reach[reach >= 60].index.max() else "") + " — a window a page does not reach is not counted for it.\n",
               f"\nFor each snapshot, on the protocols it lists: the cliffs (≥ {MIN_PCT} %) that today's schedule dates in the days after it, and how the snapshot had them — "
               f"`same` (±{DAY_TOL} day, ±{AMT_TOL:.0%} size), `amount` (the day, another size), `moved` (the size within ±{MOVE_DAYS} days), `absent`; "
               "and the reverse, the cliffs the snapshot dated there that today's schedule does not have as dated. Pooled over the snapshots, by year:\n"]
        k.insert(k.columns.get_loc("amount") + 1, "day_known", k["same"] + k["amount"])
        cols = ["final", "same", "amount", "day_known", "moved", "absent", "snap", "snap_unmatched"]
        k["year"] = k["asof"].dt.year.astype(str)
        ky = pd.concat([pd.concat([g.groupby("year")[cols].sum(), g[cols].sum().rename("all").to_frame().T]).assign(window=w) for w, g in k.groupby("window", sort=False)])
        ky = ky.rename_axis("snapshots of").reset_index()[["window", "snapshots of", *cols]]
        ky["same %"] = (100 * ky["same"] / ky["final"]).round(1)
        ky["day known %"] = (100 * ky["day_known"] / ky["final"]).round(1)
        ky["snap unmatched %"] = (100 * ky["snap_unmatched"] / ky["snap"]).round(1)
        md += [ky.to_markdown(index=False), "\n"]

        # 5 — what a point-in-time event table would hold
        st = point_in_time(acd, onm.drop_duplicates(["pid", "day"]).reset_index(drop=True), covered)
        ev5 = onm.drop_duplicates(["pid", "day"]).reset_index(drop=True).assign(status=st)
        t5 = _order(pd.crosstab(ev5["status"], ev5["fold"]))
        usable = ", ".join(f"{f} {int(t5.loc['same', f]) if 'same' in t5.index else 0}" for f in t5.columns)
        md += [f"\n## 5. Point-in-time: the members' cliffs against the last snapshot at least {LEAD.days} days before each\n",
               "\n`same` is an event a feature could have used as it happened; `uncovered` = the protocol was not on the page yet (added later, its history filled in); "
               "`out_of_reach` = that page dates nothing so far ahead (from 2025-05-26 it carries 30 days); `no_snapshot` = before the first snapshot:\n", t5.to_markdown(), "\n",
               f"\n- usable (`same`) per fold: {usable}\n"]
        pr = promised(acd[acd["pct_max"] >= MIN_PCT], covered).assign(key=lambda x: x["symbol"], fold=lambda x: fold_of(x["day"]))
        prm = in_blocks(pr, "day", mem).drop_duplicates(["pid", "day"]).reset_index(drop=True)
        if len(prm):
            prm["today"] = _match(prm, cd).replace({"moved": "not as dated", "absent": "not as dated"})
            md += ["\nThe other side — what a feature would have been built from: the cliffs on a member as the last snapshot at least "
                   f"{LEAD.days} days before dated them, and whether today's schedule has them as dated:\n", _order(pd.crosstab(prm["today"], prm["fold"], margins=True, margins_name="promised").drop(columns="promised")).to_markdown(), "\n",
                   f"\n- {prm['perp'].nunique()} names; the ten with the most hold {int(prm.groupby('perp').size().nlargest(10).sum())} of {len(prm)}\n"]
        gaps = snaps.index.to_series().diff().dt.days.dropna()
        if len(gaps):
            md += [f"- days between snapshots: median {gaps.median():.0f}, 90 % under {gaps.quantile(0.9):.0f}, longest {gaps.max():.0f} (ending {gaps.idxmax():%Y-%m-%d})\n"]

    # 6 — Binance's announcements
    art = bn.drop_duplicates(["catalog", "id"])
    md += ["\n## 6. Binance's announcements\n",
           "\n" + "; ".join(f"catalog {c} ({CATALOGS[c]}): {len(g):,} articles {g['release'].min():%Y-%m-%d} → {g['release'].max():%Y-%m-%d}" for c, g in art.groupby("catalog")) + "\n",
           "\nArticles by kind and year (a title read by `parse_title`):\n", pd.crosstab(art["kind"], art["release"].dt.year).to_markdown(), "\n"]
    perp = art[art["kind"].isin(PERP_KINDS)]
    nosym = perp[perp["symbol"] == ""]
    nosym[["release", "kind", "title", "code"]].to_csv(out.with_name("events_binance_unparsed.csv"), index=False)
    md += [f"\n- perpetual launch / delisting articles: {len(perp)}; without a ticker after the title and the article were read: {len(nosym)} (`{out.with_name('events_binance_unparsed.csv').name}`)\n"]
    ev = bn[bn["symbol"] != ""].assign(fold=lambda x: fold_of(x["release"]))
    md += ["\nTickers named, by kind and fold of the release:\n", _order(pd.crosstab(ev["kind"], ev["fold"])).to_markdown(), "\n"]

    # 7 — the launches against the archive
    if first is not None:
        fm = first[first["symbol"].str.fullmatch(r"[A-Z0-9]+USDT") & (first["first_month"] != "")].assign(b=lambda x: x["symbol"].str[:-4])
        fm["y"], fm["mo"] = fm["first_month"].str[:4].astype(int), fm["first_month"].str[:4].astype(int) * 12 + fm["first_month"].str[5:7].astype(int)
        la = bn[(bn["kind"] == "perp_launch") & (bn["symbol"] != "")].assign(rmo=lambda x: x["release"].dt.year * 12 + x["release"].dt.month)
        j = fm.merge(la[["symbol", "rmo", "release"]].rename(columns={"symbol": "b"}), on="b", how="left")
        j["hit"] = (j["mo"] - j["rmo"]).between(0, 1)                # it began in the month of the announcement or the next
        byc = j.groupby("symbol").agg(y=("y", "first"), announced=("release", lambda s: s.notna().any()), hit=("hit", "any"))
        byc = byc[byc["y"] >= 2020]
        conf = j[j["hit"]].drop_duplicates("symbol").assign(fold=lambda x: fold_of(x["release"]))
        nf = _order(conf.groupby("fold").size().rename("contracts").to_frame().T)
        ty = byc.groupby("y").agg(contracts=("hit", "size"), with_announcement=("announced", "sum"), in_the_launch_month=("hit", "sum"))
        md += ["\n## 7. Launches against the archive (the first monthly 1d file of every USDT perpetual)\n",
               "\nA contract by the year it begins in the archive; whether any launch announcement names its base; whether one was released in the month it began or the month before:\n",
               pd.concat([ty, ty.sum().rename("all").to_frame().T]).to_markdown(), "\n",
               "\nThe population of a new-listing question — USDT perpetuals whose launch announcement the archive confirms, by fold of the release:\n", nf.to_markdown(index=False), "\n",
               f"\n- contracts with no announcement at all: {', '.join(byc.index[~byc['announced']][:60])}{' …' if (~byc['announced']).sum() > 60 else ''}\n"]
        try:
            fb = data.load("candles_5m_archive", columns=["symbol", "open_time"]).groupby("symbol", observed=True)["open_time"].min()
            lead = la.assign(perp=la["symbol"] + "USDT").merge(fb.rename("first_bar"), left_on="perp", right_index=True)
            lead["h"] = (lead["first_bar"] - lead["release"]) / pd.Timedelta("1h")
            lead = lead[lead["h"].between(-24, 24 * 30)].sort_values("h").drop_duplicates("perp")
            q = lead["h"].quantile([0.1, 0.5, 0.9]).round(1)
            md += [f"- on the {len(lead)} contracts whose 5m bars we hold from their first day: the first bar comes {q[0.5]} h after the announcement at the median "
                   f"(10 % under {q[0.1]} h, 90 % under {q[0.9]} h); {int((lead['h'] < 0).sum())} begin BEFORE their announcement's release time\n"]
        except Exception as e:  # noqa: BLE001 — the slice is on the work VM only
            md += [f"- first 5m bar against the release time: not measured here ({type(e).__name__})\n"]

    # 8 — announcements on our names while they are members
    ev8 = ev[ev["kind"].isin(["perp_delist", "spot_list", "spot_delist", "monitoring"])]
    wr = in_blocks(ev8[ev8["kind"] == "perp_delist"].assign(key=lambda x: x["symbol"] + "USDT"), "release", mem, on="perp")
    tk = in_blocks(ev8[ev8["kind"] != "perp_delist"].assign(key=lambda x: x["symbol"]), "release", mem)
    on = pd.concat([wr, tk], ignore_index=True).drop_duplicates(["universe", "id", "perp"])
    if len(on):
        md += ["\n## 8. Announcements on a member while it is a member, by fold of the release\n",
               "\nA perpetual's delisting by its contract; a spot listing, a spot delisting and a monitoring tag by the ticker (the name already trades as a perpetual):\n",
               _order(pd.crosstab(on["kind"], on["fold"])).to_markdown(), "\n"]
    if first is not None and len(ev8):
        e2 = ev8.assign(key=lambda x: x["symbol"].where(x["kind"] != "perp_delist", x["symbol"].map(lambda b: base(b + "USDT")))).merge(arch, on="key")
        e2 = e2[e2["release"] >= e2["since"] + BLOCK].drop_duplicates(["id", "perp"])
        md += ["\nThe same on any USDT perpetual the archive holds, from 30 days after its first month began (tickers; a delisted contract's flat bars make a few of these late):\n",
               _order(pd.crosstab(e2["kind"], e2["fold"])).to_markdown(), "\n"]
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(md)
    out.write_text(text)
    return text


def main(action: str, pairs: list[str], sources: list[str] | None = None, cached: bool = False, reverse: bool = False) -> None:
    if action == "fetch":
        for s in sources or ["llama", "binance", "wayback"]:
            {"llama": fetch_llama, "binance": fetch_binance, "wayback": lambda: fetch_wayback(reverse=reverse)}[s]()
    elif action == "ingest":
        ingest()
    elif action == "inventory":
        print(inventory(pairs, network=not cached))
        print(f"wrote {REPORT}")
