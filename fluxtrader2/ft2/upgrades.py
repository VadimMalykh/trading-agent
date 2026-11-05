"""Decision CD1 (2026-11-04; PLAN P8 decision CD) — the scheduled NETWORK UPGRADE / HARD FORK of a name, dated by the exchange to the
minute, as a per-name EVENT: the source audit, `ft2 upgrades list|details|events|bars|audit`. Nothing here joins a bar AFTER an event to
anything; no price is read; no fold is read for a label; nothing is registered.

source     Binance's CMS catalog 157 "Maintenance Updates" (www.binance.com/bapi/composite/v1/public/cms; reachable from the work VM, not
           from every network): the titles "Binance Will Support the <Name> (<TICKER>) Network Upgrade & Hard Fork [- YYYY-MM-DD]" and the
           "… Upgrade" variants. `list` saves the catalog (data/raw/external/binance_cms/list_157_<stamp>.json, `--fetch`), `details` the
           upgrade titles' article bodies (…/binance_cms/detail/<code>.json, one every PAUSE seconds, cached).
event      the UPGRADE's stated time t0, parsed from the body: the stamp of the sentence that names the block height or the upgrade itself
           ("the network upgrade and hard fork will take place at block height 6,470,279, or at approximately 2026-10-19 12:59 (UTC)"), NOT the
           deposit suspension's stamp an hour earlier (kept beside as `t_suspend`); an upgrade dated by a block height alone, or a body
           without a stamp, is OUT and described. A two-chain notice ("the MANTRA (OM) and MultiversX (EGLD) Network Upgrades") is one row a
           chain, each parsed from the sentences naming it (`multi`). KNOWN-AT: the
           notice's `releaseDate` (`ts_known` = release) — the hour is public from then; a registration's decision bar is the first 5m bar
           that CLOSES after t0. A notice released AFTER its stated time is OUT (the event was not known ahead; counted). One cell a name per
           COLLAPSE days (a multi-day upgrade's follow-up notices collapsed onto the first).
flags      the fold of t0, `block` (the screener's block holding t0, where one does), `member_at_t0`, `lead_d` (t0 − release, days),
           `hardfork` (the title says "Hard Fork"), `repeat_n` (the name's earlier events in the whole catalog, any fold), the perpetual's
           first bar (`candles_5m_archive` where held, else the first day of the month after `um_first_month.csv`'s first month — an upper
           bound of the start → the age a lower bound) and its age at t0, `title_date`, `stated_how`.
eligible   the perpetual ≥ PERP_AGE old at t0 AND t0 inside F1 … F4. F5's events are listed and NOT frozen.
lists      output/upgrades/events.csv (every candidate with its `why`), output/upgrades/upgrades_f12.csv / _f34.csv (the eligible), frozen by
           hand as ft2/upgrades_f12.csv / _f34.csv and committed BEFORE any bar after a t0 is read for anything.
bars       per frozen event the count of the name's 5m bars over [min(release, t0 − 2 d), t0 + 8 d) in `candles_5m_archive` — COUNTS; with
           --fetch the F1+F2 events' missing (name, month) files are fetched (R28's route) and the slice re-ingested whole under krlist's
           fingerprint (a name that changes is a void).
audit      the counts by fold × hardfork × member, the repeats, the lead, the stated-time rule's distribution, the hour of day, the ages, the
           bars, the cost rows (`costwide`'s taker round trip on t0's day) → output/upgrades/audit.md / .json, DATA.md `upgrade_events`.
"""
from __future__ import annotations

import glob
import html
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds
from . import coinbase as cb

CATALOG = 157
PAUSE = 3.0
COOL = 120.0                      # the wait after a 429, times the attempt
PERP_AGE = pd.Timedelta(days=30)
COLLAPSE = pd.Timedelta(days=7)
WINDOW = (pd.Timedelta(days=-2), pd.Timedelta(days=8))
BAR = pd.Timedelta("5min")
HOUR = pd.Timedelta("1h")
DAY = pd.Timedelta(days=1)
FROZEN_FOLDS = ("F1", "F2", "F3", "F4")
TAGS = {"F1": "f12", "F2": "f12", "F3": "f34", "F4": "f34"}
F5_LISTED = "outside F1 … F4 (F5: listed, not frozen)"       # the `why` of an F5 row that passed every other check — the rows R82's list freezes
OUT = Path("output/upgrades")
LISTS = {"f12": Path(__file__).with_name("upgrades_f12.csv"), "f34": Path(__file__).with_name("upgrades_f34.csv"),
         "f5": Path(__file__).with_name("upgrades_f5.csv")}       # f5: the F5 rows listed by the same rule, frozen 2026-11-06 for R82 (decision CF2)
CMS_DIR = data.RAW / "external" / "binance_cms"
FIRST = data.RAW / "external" / "binance" / "um_first_month.csv"
CMS_LIST = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId={c}&pageNo={p}&pageSize=50"
CMS_DETAIL = "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}"
SLICE = "candles_5m_archive"
UPGRADE_RE = re.compile(r"upgrade|hard ?fork", re.I)
TICK_RE = re.compile(r"\(([A-Z0-9]{2,10})\)")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})? ?\(?UTC\)?")
SENT_RE = re.compile(r"(?<=[.;!?])\s+|\n+")
UPGRADE_SENT = re.compile(r"upgrade|hard ?fork|block height|epoch|mainnet|take place|will occur|is scheduled", re.I)
NAME_RE = re.compile(r"([^()]+?)\s*\(([A-Z0-9]{2,10})\)")
SUSPEND_SENT = re.compile(r"suspend|deposit|withdraw|resume|reopen", re.I)
TAKER_BPS = 4.0
NOTIONAL = 10_000
LIST_COLS = ["symbol", "base", "mult", "t0", "ts_known", "release", "code", "fold", "block", "perp_first", "perp_first_source", "perp_age_days",
             "member_at_t0", "lead_d", "hardfork", "multi", "repeat_n", "t_suspend", "stated_how", "title_date", "title"]


def _utc(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s)
    return pd.Series(idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC"), index=s.index)


def fold_of(ts: pd.Timestamp) -> str | None:
    for f in folds.FOLDS:
        a, b = folds.bounds(f, embargoed=False)
        if a <= ts < b:
            return f
    return None


def member_symbols() -> pd.DataFrame:
    """(block, block_end, symbol, folds) — the screener's point-in-time members; an indirection the tests replace."""
    return cb.member_symbols()


def block_at(M: pd.DataFrame, t: pd.Timestamp) -> pd.Timestamp:
    """The start of the screener's block holding t (NaT where no file holds it)."""
    g = M[(M["block"] <= t) & (M["block_end"] > t)]
    return pd.Timestamp(g["block"].iloc[0]) if len(g) else pd.NaT


def member_at(M: pd.DataFrame, symbol: str, t: pd.Timestamp) -> bool:
    g = M[(M["symbol"] == symbol) & (M["block"] <= t) & (M["block_end"] > t)]
    return bool(len(g))


# ---- the catalog and the details ------------------------------------------------------------------------------------------------
def _get(u: str) -> bytes:
    from .events import _get as get
    return get(u)


def fetch_list(pause: float = 0.5) -> Path:
    """Every article of catalog 157 (id, code, title, releaseDate), saved under CMS_DIR as list_157_<YYYYMMDD>.json."""
    arts, p = [], 1
    while True:
        page = json.loads(_get(CMS_LIST.format(c=CATALOG, p=p)))["data"]["catalogs"]
        page = page[0]["articles"] if page else []
        if not page:
            break
        arts += [{k: a[k] for k in ("id", "code", "title", "releaseDate")} for a in page]
        p += 1
        time.sleep(pause)
    arts = list({a["id"]: a for a in arts}.values())
    CMS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CMS_DIR / f"list_{CATALOG}_{pd.Timestamp.now('UTC'):%Y%m%d}.json"
    dest.write_text(json.dumps(arts))
    return dest


def titles() -> pd.DataFrame:
    """The latest catalog-157 list on disk, one row an article (id, code, title, release); the upgrade / hard-fork titles flagged with their ticker."""
    files = sorted(glob.glob(str(CMS_DIR / f"list_{CATALOG}_*.json")))
    if not files:
        raise SystemExit(f"upgrades: no catalog {CATALOG} list on disk ({CMS_DIR}/list_{CATALOG}_*.json) — run `ft2 upgrades list --fetch` on the VM")
    arts = json.load(open(files[-1]))
    T = pd.DataFrame([{"id": int(a["id"]), "code": a["code"], "title": a["title"], "release": pd.Timestamp(int(a["releaseDate"]), unit="ms", tz="UTC")} for a in arts])
    T = T.drop_duplicates("id").sort_values("release").reset_index(drop=True)
    T["upgrade"] = T["title"].map(lambda s: bool(UPGRADE_RE.search(s)))
    T["tick"] = T["title"].str.extract(TICK_RE)[0]
    T["hardfork"] = T["title"].str.contains(r"hard ?fork", case=False, regex=True)
    T["title_date"] = pd.to_datetime(T["title"].str.extract(DATE_RE)[0], utc=True, errors="coerce")
    T["list_file"] = Path(files[-1]).name
    return T


def _detail(code: str, fetch: bool) -> dict | None:
    p = CMS_DIR / "detail" / f"{code}.json"
    if p.exists():
        return json.load(open(p))
    if not fetch:
        return None
    for attempt in range(6):                                   # the CMS answers 429 after ≈ 250 pages at 2 s: wait it out, do not give up the run
        try:
            d = json.loads(_get(CMS_DETAIL.format(code=code)))["data"]
            break
        except RuntimeError as e:
            if "429" not in str(e) or attempt == 5:
                raise
            print(f"429 on {code}; waiting {COOL * (attempt + 1):.0f} s", flush=True)
            time.sleep(COOL * (attempt + 1))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    time.sleep(PAUSE)
    return d


def body_text(d: dict) -> str:
    """The article's text: the body is a JSON tree of nodes (2025–26) or HTML (older) — every `text` leaf joined with a space, else the tags
    stripped; the entities unescaped (`&nbsp;` glued a stamp to the next sentence); the seoDesc first."""
    b = d.get("body") or ""
    try:
        tree = json.loads(b)
        out: list[str] = []

        def walk(o):
            if isinstance(o, dict):
                if o.get("node") == "text":
                    out.append(str(o.get("text", "")))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(tree)
        text = " ".join(out)                               # a bold span is its own leaf mid-sentence: leaves join with a space, not a line
    except (ValueError, TypeError):
        text = re.sub(r"<[^>]+>", " ", b)
    text = html.unescape(text).replace("\xa0", " ")
    return (html.unescape(d.get("seoDesc") or "").replace("\xa0", " ") + "\n" + text).strip()


def sentences(text: str) -> list[str]:
    return [x.strip() for x in SENT_RE.split(text) if x.strip()]


def stated_time(text: str | list[str]) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """(t_upgrade, t_suspend, how) from the body's sentences. The UPGRADE's stamp: the first stamp in a sentence naming the upgrade / the hard
    fork / the block height / "take place" and NOT the deposit suspension (`upgrade_sentence`). A sentence naming both ("Starting at X Binance
    will suspend … to support its network upgrade") is the suspension's. No upgrade stamp but a suspension stamp: `suspension_only` (the
    upgrade dated by a block height alone — t0 unknown to the hour, the event OUT); no stamp at all: `none`."""
    t_up, t_sus = pd.NaT, pd.NaT
    for sent in (sentences(text) if isinstance(text, str) else text):
        for m in STAMP_RE.finditer(sent):
            ts = pd.Timestamp(f"{m.group(1)} {m.group(2)}", tz="UTC")
            up, sus = bool(UPGRADE_SENT.search(sent)), bool(SUSPEND_SENT.search(sent))
            if sus and pd.isna(t_sus):
                t_sus = ts
            if up and not sus and pd.isna(t_up):
                t_up = ts
    how = "upgrade_sentence" if pd.notna(t_up) else ("suspension_only" if pd.notna(t_sus) else "none")
    return t_up, t_sus, how


def name_pairs(title: str) -> list[tuple[str, str]]:
    """"Binance Will Support the MANTRA (OM) and MultiversX (EGLD) Network Upgrades" → [(MANTRA, OM), (MultiversX, EGLD)]."""
    t = re.sub(r"^Binance Will Support (the )?", "", title)
    out = []
    for m in NAME_RE.finditer(t):
        name = re.sub(r"^(and|the|,|&)\s+", "", m.group(1).strip(" ,&"), flags=re.I).strip()
        out.append((name, m.group(2)))
    return out


def per_name(text: str, title: str) -> dict[str, list[str]]:
    """A multi-name notice ("the MANTRA (OM) and MultiversX (EGLD) Network Upgrades") holds each chain's own sentences: per ticker the
    sentences naming it or its name; a one-name notice keeps the whole body. A sentence naming none ("the aforementioned network") is nobody's."""
    pairs = name_pairs(title)
    if len(pairs) <= 1:
        return {(pairs[0][1] if pairs else ""): sentences(text)}
    out = {}
    for name, tick in pairs:
        pat = re.compile(r"\(" + re.escape(tick) + r"\)|\b" + re.escape(name) + r"\b", re.I)
        out[tick] = [x for x in sentences(text) if pat.search(x)]
    return out


def details(fetch: bool = False, write: bool = True) -> pd.DataFrame:
    """One row an upgrade / hard-fork title with a ticker: the stated time parsed from its cached detail (fetched with --fetch)."""
    T = titles()
    U = T[T["upgrade"] & T["tick"].notna()].copy()
    rows = []
    for r in U.itertuples(index=False):
        d = _detail(r.code, fetch)
        parts = {r.tick: []} if d is None else per_name(body_text(d), r.title)
        for tick, sents in parts.items():
            t_up, t_sus, how = (pd.NaT, pd.NaT, "no_detail") if d is None else stated_time(sents)
            rows.append({"id": r.id, "code": r.code, "release": r.release, "title": r.title, "tick": tick, "hardfork": bool(r.hardfork), "title_date": r.title_date,
                         "multi": len(parts) > 1, "t0": t_up, "t_suspend": t_sus, "stated_how": how, "has_detail": d is not None})
    D = pd.DataFrame(rows)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        D.to_csv(OUT / "details.csv", index=False)
        print(f"{len(T)} titles in {T['list_file'].iloc[0]}; {int(T['upgrade'].sum())} upgrade / hard-fork, {len(U)} with a ticker ({int(D['multi'].sum())} rows of multi-name notices), "
              f"{len(D)} (notice, name) rows, {int(D['has_detail'].sum())} with a detail; the stated time by rule {D['stated_how'].value_counts().to_dict()}; "
              f"t0 − t_suspend (h) {((D['t0'] - D['t_suspend']) / HOUR).describe()[['min', '50%', 'max']].round(2).to_dict()}", flush=True)
    return D


# ---- the contracts and the events --------------------------------------------------------------------------------------------
def contracts() -> pd.DataFrame:
    """`um_first_month.csv` with the base and the months as periods: (symbol, base, first_month, last_month)."""
    if not FIRST.exists():
        raise SystemExit(f"upgrades: {FIRST} missing — `ft2 events fetch --source first_months` on the VM")
    fm = pd.read_csv(FIRST, dtype=str).fillna("")
    fm = fm[fm["first_month"] != ""].copy()
    fm["base"] = fm["symbol"].map(cb.base)
    fm["fm"] = fm["first_month"].map(lambda m: pd.Period(m, freq="M"))
    fm["lm"] = fm["last_month"].map(lambda m: pd.Period(m, freq="M") if m else pd.Period("2099-12", freq="M"))
    return fm


def contract_for(fm: pd.DataFrame, tick: str, t0: pd.Timestamp) -> str | None:
    """The perpetual of `tick` listed in t0's month (its first month ≤ t0's ≤ its last); several → the plain name over a 1000× one, else the oldest.
    A ticker whose every contract is dead at t0 takes the exchange's relaunch `<TICK>2USDT` where that one is live (Terra's LUNA → LUNA2USDT
    from 2022-09; the old LUNAUSDT ended 2022-05 — found 2026-11-04 by two frozen rows with no bars)."""
    c = fm[fm["base"] == tick]
    if not len(c):
        return None
    pm = pd.Period(t0.tz_convert("UTC").tz_localize(None), freq="M")
    live = c[(c["fm"] <= pm) & (c["lm"] >= pm)]
    if not len(live):
        c2 = fm[(fm["base"] == tick + "2") & (fm["fm"] <= pm) & (fm["lm"] >= pm)]
        if len(c2):
            return str(c2["symbol"].iloc[0])
    pool = live if len(live) else c[c["fm"] <= pm]
    if not len(pool):
        pool = c
    pool = pool.assign(plain=pool["symbol"] == pool["base"] + "USDT").sort_values(["plain", "fm"], ascending=[False, True])
    return str(pool["symbol"].iloc[0])


def perp_first(symbols: list[str], fm: pd.DataFrame) -> pd.DataFrame:
    """Per symbol the perpetual's first bar: the EARLIER of the archive slice's first 5m bar where held (`archive 5m`) and the first day of the
    month after `um_first_month.csv`'s first month (`first_month`). Both are upper bounds of the start — the slice's where a fetch put only an
    event's window into it (BTSUSDT after this audit's fetch: one month of 2023-11 for a 2021 contract, found 2026-11-04) — so the earlier is
    the tighter bound and the age a lower bound either way; else NaT."""
    rows = {s: (pd.NaT, "none") for s in symbols}
    if (data.PROC / f"{SLICE}.parquet").exists() or (data.PROC / SLICE).is_dir():
        c = data.load(SLICE, columns=["symbol", "open_time"], symbols=list(symbols))
        if len(c):
            c["open_time"] = _utc(c["open_time"])
            for s, t in c.groupby("symbol", observed=True)["open_time"].min().items():
                rows[str(s)] = (t, "archive 5m")
    k = fm.set_index("symbol")["fm"]
    for s in symbols:
        if s in k.index:
            t = pd.Timestamp((k[s] + 1).start_time, tz="UTC")
            if rows[s][1] == "none" or t < rows[s][0]:
                rows[s] = (t, "first_month")
    return pd.DataFrame([{"symbol": s, "perp_first": t, "perp_first_source": src} for s, (t, src) in rows.items()])


def events(write: bool = True) -> pd.DataFrame:
    """Every upgrade / hard-fork notice with a ticker of ours, its flags and `why`; the eligible ones written as the lists to freeze."""
    D = details(fetch=False, write=False)
    fm = contracts()
    D["symbol"] = [contract_for(fm, t, t0 if pd.notna(t0) else r) for t, t0, r in zip(D["tick"], D["t0"], D["release"])]
    D = D[D["symbol"].notna()].copy()
    syms = sorted(set(D["symbol"]))
    pf = perp_first(syms, fm).set_index("symbol")
    M = member_symbols()
    D["base"] = D["symbol"].map(cb.base)
    D["mult"] = D["symbol"].map(cb.mult_of)
    D["perp_first"] = D["symbol"].map(pf["perp_first"])
    D["perp_first_source"] = D["symbol"].map(pf["perp_first_source"])
    D["ts_known"] = D["release"]
    D["lead_d"] = (D["t0"] - D["release"]) / DAY
    D = D.sort_values(["release", "symbol"]).reset_index(drop=True)
    D["repeat_n"] = D.groupby("symbol").cumcount()
    D["perp_age_days"] = (D["t0"] - D["perp_first"]).dt.days
    D["fold"] = D["t0"].map(lambda t: fold_of(t) if pd.notna(t) else None)
    D["block"] = [block_at(M, t) if pd.notna(t) else pd.NaT for t in D["t0"]]
    D["member_at_t0"] = [member_at(M, s, t) if pd.notna(t) else False for s, t in zip(D["symbol"], D["t0"])]
    why, last_kept = [], {}
    for r in D.sort_values(["t0", "release"]).itertuples():
        if not r.has_detail:
            w = "no detail body on disk (run `ft2 upgrades details --fetch` on the VM)"
        elif r.stated_how == "suspension_only":
            w = "the upgrade's time stated as a block height only (the suspension's stamp is not the event's)"
        elif pd.isna(r.t0):
            w = "no stated time in the body"
        elif r.release > r.t0:
            w = "released after its stated time (not known ahead)"
        elif r.symbol in last_kept and r.t0 - last_kept[r.symbol] < COLLAPSE:
            w = f"a follow-up within {COLLAPSE.days} days of the name's previous event"
        elif r.perp_first_source == "none" or pd.isna(r.perp_age_days):
            w = "no perpetual first bar known"
        elif r.perp_age_days < PERP_AGE.days:
            w = f"the perpetual younger than {PERP_AGE.days} days at t0 (a launch, R28's population)"
        elif r.fold not in FROZEN_FOLDS:
            w = F5_LISTED if r.fold == "F5" else "outside F1 … F4"
        else:
            w = "eligible"
        if w == "eligible" or w.startswith("outside") or w.startswith("the perpetual younger"):
            last_kept[r.symbol] = r.t0
        why.append((r.Index, w))
    D["why"] = pd.Series(dict(why))
    E = D[[*LIST_COLS, "tick", "has_detail", "why"]].sort_values(["t0", "symbol"], na_position="first").reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        E.to_csv(OUT / "events.csv", index=False)
        el = E[E["why"] == "eligible"]
        for tag in ("f12", "f34"):
            el[el["fold"].map(TAGS) == tag][LIST_COLS].to_csv(OUT / f"upgrades_{tag}.csv", index=False)
        E[E["why"] == F5_LISTED][LIST_COLS].to_csv(OUT / "upgrades_f5.csv", index=False)       # the F5 rows by the same rule (decision CF2: frozen for R82)
        print(summary(E))
    return E


def summary(E: pd.DataFrame) -> str:
    el = E[E["why"] == "eligible"]
    lines = [f"{len(E)} upgrade / hard-fork notices with a perpetual of ours; {len(el)} eligible (the perpetual ≥ {PERP_AGE.days} d old at t0, t0 in F1 … F4)"]
    if len(el):
        lines.append("eligible by fold × hardfork:\n" + el.groupby(["fold", "hardfork"]).size().unstack(fill_value=0).to_string())
        lines.append(f"distinct names by fold set: F1+F2 {el[el['fold'].isin(['F1', 'F2'])]['symbol'].nunique()}, F3+F4 {el[el['fold'].isin(['F3', 'F4'])]['symbol'].nunique()}; "
                     f"members at t0 {int(el['member_at_t0'].sum())} of {len(el)}; first-of-a-name {int((el['repeat_n'] == 0).sum())}; "
                     f"the lead (days) q10 / q50 / q90 {' / '.join(f'{x:.2f}' for x in el['lead_d'].quantile([.1, .5, .9]))}; the stated time by rule {el['stated_how'].value_counts().to_dict()}")
    lines.append(f"F5: {int(((E['fold'] == 'F5') & E['why'].str.startswith('outside')).sum())} listed, not frozen")
    lines.append("not eligible, by reason:\n" + E[E["why"] != "eligible"]["why"].value_counts().to_string())
    return "\n".join(lines)


def frozen(tags=("f12", "f34")) -> pd.DataFrame:
    parts = []
    for tag in tags:
        p = LISTS[tag]
        if p.exists():
            d = pd.read_csv(p)
            for c in ("t0", "ts_known", "release", "block", "perp_first", "t_suspend", "title_date"):
                d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601")
            parts.append(d.assign(list=tag))
    if not parts:
        raise SystemExit(f"upgrades: no frozen list at {list(LISTS.values())} — run `ft2 upgrades events`, freeze the lists, commit")
    return pd.concat(parts, ignore_index=True)


# ---- the bars (counts) --------------------------------------------------------------------------------------------------------
def windows(L: pd.DataFrame) -> pd.DataFrame:
    """[min(release, t0 − 2 d) floored to the hour, t0 + 8 d) — the INTO row starts at the notice, the AFTER row ends a day past the 7d hold."""
    w = L[["symbol", "t0", "release", "fold"]].copy()
    w["a"] = pd.concat([w["release"], w["t0"] + WINDOW[0]], axis=1).min(axis=1).dt.floor("h")
    w["b"] = w["t0"] + WINDOW[1]
    w["expected"] = ((w["b"] - w["a"]) / BAR).astype(int)
    return w


def coverage(L: pd.DataFrame) -> pd.DataFrame:
    from . import archive
    w = windows(L)
    syms = sorted(set(w["symbol"]))
    have = pd.DataFrame(columns=["symbol", "open_time"])
    if (data.PROC / f"{SLICE}.parquet").exists() or (data.PROC / SLICE).is_dir():
        have = data.load(SLICE, columns=["symbol", "open_time"], symbols=syms)
        have["open_time"] = _utc(have["open_time"])
    by = {str(s): np.sort(g["open_time"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")) for s, g in have.groupby("symbol", observed=True)}
    out = []
    for r in w.itertuples(index=False):
        t = by.get(r.symbol, np.array([], dtype="datetime64[ns]"))
        a, b = np.datetime64(r.a.tz_convert("UTC").tz_localize(None), "ns"), np.datetime64(r.b.tz_convert("UTC").tz_localize(None), "ns")
        n = int(np.searchsorted(t, b) - np.searchsorted(t, a))
        out.append({"symbol": r.symbol, "t0": r.t0, "fold": r.fold, "bars": n, "expected": int(r.expected), "share": n / int(r.expected),
                    "months": archive.months_between(r.a.date(), (r.b - BAR).date())})
    return pd.DataFrame(out)


def bars(fetch: bool = False, fetch_tags: tuple[str, ...] = ("f12",)) -> dict:
    """The frozen events' bars counted; with `fetch` the (name, month) files missing for the events of `fetch_tags` (F1+F2 by default — the
    confirmation's F3+F4 names are decision CE's own Data line) come from the archive's monthly 5m klines and the slice is re-ingested whole
    under krlist's fingerprint (R28's route: every name it held comes back row for row, or the ingest is void)."""
    from . import archive, krlist
    L = frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    cov = coverage(L)
    cov["list"] = L["list"].to_numpy()
    need = krlist.missing_months(cov[cov["list"].isin(fetch_tags)])
    rep = {"events": int(len(cov)), "complete": int((cov["share"] >= 0.95).sum()),
           "by_fold": {str(k): {"events": int(len(g)), "complete": int((g["share"] >= 0.95).sum()), "median_share": float(g["share"].median())} for k, g in cov.groupby("fold")},
           "missing_symbols": sorted(set(cov[cov["share"] < 0.95]["symbol"])), "missing_months_in_fetch_tags": need,
           "missing_files_in_fetch_tags": int(sum(len(m) for m in need.values()))}
    if fetch and need:
        fp = krlist.fingerprint()
        fp.to_csv(OUT / "fingerprint_before.csv", index=False)
        rep["fetch"] = {sym: archive.fetch_monthly("klines", sym, sub="5m", months=months) for sym, months in need.items()}
        rep["ingest"] = {k: str(v) for k, v in data.ingest_klines(krlist.ingest_symbols(sorted(need))).items()}
        chk = krlist.fingerprint_check(fp)
        (OUT / "fingerprint_check.json").write_text(json.dumps(chk, indent=1, default=str))
        rep["fingerprint"] = {"pass": chk["pass"], "changed": chk["changed"][:10], "names_before": chk["names_before"], "names_after": chk["names_after"]}
        if not chk["pass"]:
            print(json.dumps(rep, indent=1, default=str))
            raise SystemExit(2)
        cov = coverage(L)
        cov["list"] = L["list"].to_numpy()
        rep["complete_after"] = int((cov["share"] >= 0.95).sum())
        rep["by_fold_after"] = {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")}
        rep["missing_after"] = krlist.missing_months(cov[cov["list"].isin(fetch_tags)])
    cov.drop(columns=["months", "list"], errors="ignore").to_csv(OUT / "bars.csv", index=False)
    print(json.dumps(rep, indent=1, default=str))
    return rep


# ---- the audit (counts and costs; no price of an event's name) -----------------------------------------------------------------
def cost_rows(L: pd.DataFrame) -> pd.DataFrame:
    """`costwide`'s taker round trip on t0's day and the day after (2 × fee + the calibrated spread + 2 × the impact at NOTIONAL)."""
    from .cost import DAILY_WIDE
    cols = ["symbol", "t0", "rt_day0", "rt_day1"]
    if not Path(DAILY_WIDE).exists():
        return pd.DataFrame(columns=cols)
    w = pd.read_parquet(DAILY_WIDE)
    w["symbol"] = w["symbol"].astype(str)
    w["day"] = _utc(w["day"]).dt.floor("D")
    imp = f"imp_{NOTIONAL}"
    if imp not in w.columns or "spread_cal_bps" not in w.columns:
        return pd.DataFrame(columns=cols)
    w["rt"] = 2 * TAKER_BPS + w["spread_cal_bps"] + 2 * w[imp]
    k = w.set_index(["symbol", "day"])["rt"]
    out = []
    for r in L.itertuples(index=False):
        d0 = r.t0.floor("D")
        out.append({"symbol": r.symbol, "t0": r.t0, "rt_day0": float(k.get((r.symbol, d0), np.nan)), "rt_day1": float(k.get((r.symbol, d0 + DAY), np.nan))})
    return pd.DataFrame(out)


def eligible_cells(L: pd.DataFrame, cov: pd.DataFrame, hold: pd.Timedelta = pd.Timedelta(days=7)) -> dict:
    """0o (i): the cells a registration on the frozen lists can read — t0 + hold inside the fold set's market (F1+F2 ends at F2's end, F3+F4
    at F4's) AND the window's bars ≥ 95 % — counted BEFORE any threshold is written."""
    out = {}
    ends = {"f12": folds.bounds("F2", embargoed=False)[1], "f34": folds.bounds("F4", embargoed=False)[1]}
    c = cov.set_index(["symbol", "t0"])["share"]
    for tag, g in L.groupby("list"):
        inside = g["t0"] + hold + BAR * 2 < ends[tag]
        full = pd.Series([c.get((s, t), 0.0) >= 0.95 for s, t in zip(g["symbol"], g["t0"])], index=g.index)
        out[tag] = {"frozen": int(len(g)), "hold_inside_market": int(inside.sum()), "bars_complete": int(full.sum()), "cells": int((inside & full).sum()),
                    "dropped_by_market_end": sorted(f"{s} {t:%Y-%m-%d}" for s, t in zip(g[~inside]["symbol"], g[~inside]["t0"]))}
    return out


def audit(today: pd.Timestamp | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    L = frozen()
    E = pd.read_csv(OUT / "events.csv") if (OUT / "events.csv").exists() else None
    cov = coverage(L)
    cr = cost_rows(L)
    OUT.mkdir(parents=True, exist_ok=True)
    cr.to_csv(OUT / "costs.csv", index=False)
    by_fh = L.groupby(["fold", "hardfork"]).size().unstack(fill_value=0)
    by_fm = L.groupby(["fold", "member_at_t0"]).size().unstack(fill_value=0)
    by_fr = L.groupby(["fold", L["repeat_n"].eq(0).map({True: "first", False: "repeat"})]).size().unstack(fill_value=0)
    q_age = L["perp_age_days"].quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    q_lead = L["lead_d"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2).to_dict()
    hod = pd.DatetimeIndex(L["t0"]).hour.value_counts().sort_index()
    dow = pd.DatetimeIndex(L["t0"]).dayofweek.value_counts().sort_index()
    gap = ((L["t0"] - L["t_suspend"]) / HOUR).dropna()
    names = L.groupby("symbol").size().sort_values(ascending=False)
    cells = eligible_cells(L, cov)
    q_rt = cr[["rt_day0", "rt_day1"]].astype(float).median().round(1).to_dict() if len(cr) else {"rt_day0": None, "rt_day1": None}
    rt_missing = int(cr["rt_day0"].isna().sum()) if len(cr) else int(len(L))
    J = {"generated": f"{today:%Y-%m-%d %H:%M} UTC", "events": int(len(L)), "distinct_names": int(L["symbol"].nunique()),
         "by_fold_hardfork": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fh.iterrows()},
         "by_fold_member": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fm.iterrows()},
         "by_fold_first_repeat": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fr.iterrows()},
         "names_by_fold_set": {tag: int(g["symbol"].nunique()) for tag, g in L.groupby("list")},
         "most_frequent_names": {k: int(v) for k, v in names.head(12).items()},
         "members_at_t0": int(L["member_at_t0"].sum()), "perp_age_days_q10_50_90": q_age, "perp_first_source": L["perp_first_source"].value_counts().to_dict(),
         "lead_d_quantiles": q_lead, "lead_negative": int((L["lead_d"] < 0).sum()), "stated_how": L["stated_how"].value_counts().to_dict(),
         "t0_minus_suspend_h": {"n": int(len(gap)), "q10_50_90": gap.quantile([0.1, 0.5, 0.9]).round(2).tolist() if len(gap) else None},
         "title_date_equals_t0_day": int((L["title_date"].dt.floor("D") == L["t0"].dt.floor("D")).sum()), "title_date_present": int(L["title_date"].notna().sum()),
         "t0_hour_utc": {int(k): int(v) for k, v in hod.items()}, "t0_dow": {int(k): int(v) for k, v in dow.items()},
         "bars_complete": int((cov["share"] >= 0.95).sum()), "bars_by_fold": {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")},
         "bars_median_share": float(cov["share"].median()), "cells_0o": cells,
         "taker_rt_median_bps": q_rt, "taker_rt_missing_day0": rt_missing,
         "candidates": None if E is None else {"n": int(len(E)), "why": E["why"].value_counts().to_dict(), "F5_listed_not_frozen": int(((E["fold"] == "F5") & E["why"].str.startswith("outside")).sum())},
         "known_at": "the notice's releaseDate (ts_known) — the upgrade's hour is public from then, a day ahead at the median; t0 = the upgrade's stated time; the decision bar of a registration is the first 5m bar that closes after t0; nothing after t0 is read here"}
    (OUT / "audit.json").write_text(json.dumps(J, indent=1, default=str))
    md = [f"# upgrades — the scheduled network upgrade / hard fork of a name as a per-name event (decision CD1)",
          f"generated {J['generated']} · the frozen lists {', '.join(p.name for p in LISTS.values())}", "",
          f"**{len(L)} eligible events** on {J['distinct_names']} names (the perpetual ≥ {PERP_AGE.days} d old at t0, t0 in F1 … F4; one a name per {COLLAPSE.days} days); "
          f"names by fold set {json.dumps(J['names_by_fold_set'])}; members at t0 {J['members_at_t0']}; the perpetual's age p10 / p50 / p90 "
          f"{q_age.get(0.1)} / {q_age.get(0.5)} / {q_age.get(0.9)} days; the first bar's source {J['perp_first_source']}.", "",
          "## By fold × hardfork (the title says 'Hard Fork')", by_fh.to_string(), "", "## By fold × member_at_t0", by_fm.to_string(), "",
          "## By fold × first-of-a-name / repeat", by_fr.to_string(), "", "## The most frequent names", json.dumps(J["most_frequent_names"]), "",
          "## The lead — t0 − release, days (quantiles)", f"{json.dumps(q_lead)}; negative {J['lead_negative']}", "",
          "## The stated time — the rule that found it, and t0 − the deposit suspension's stamp (hours)", f"{json.dumps(J['stated_how'])}; {json.dumps(J['t0_minus_suspend_h'])}; "
          f"the title's date equals t0's day on {J['title_date_equals_t0_day']} of {J['title_date_present']} with a date", "",
          "## The hour of day of t0 (UTC)", hod.to_string(), "", "## The day of week of t0 (0 = Monday)", dow.to_string(), "",
          "## Bars in the window (min(release, t0 − 2 d) → t0 + 8 d)", f"complete (≥ 95 %) {J['bars_complete']} of {len(L)}; by fold {json.dumps(J['bars_by_fold'])}; median share {J['bars_median_share']:.3f}", "",
          "## The cells a registration can read (0o (i): t0 + 7 d inside the fold set's market AND the bars complete)", json.dumps(cells, default=str), "",
          "## The cost rows — `costwide`'s taker round trip on t0's day and the day after (bps, median)", f"{json.dumps(q_rt)}; missing on day 0: {rt_missing}", "",
          "## Candidates not eligible", "" if E is None else E[E["why"] != "eligible"]["why"].value_counts().to_string(),
          "" if E is None else f"F5: {J['candidates']['F5_listed_not_frozen']} listed, not frozen", "",
          "## Known-at", J["known_at"]]
    (OUT / "audit.md").write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, fetch: bool = False, tags: tuple[str, ...] = ("f12",)) -> None:
    if action == "list":
        if fetch:
            print(f"saved {fetch_list()}")
        T = titles()
        print(f"{len(T)} titles in {T['list_file'].iloc[0]} ({T['release'].min():%Y-%m-%d} → {T['release'].max():%Y-%m-%d}); upgrade / hard-fork {int(T['upgrade'].sum())}, "
              f"with a ticker {int((T['upgrade'] & T['tick'].notna()).sum())}")
    elif action == "details":
        details(fetch=fetch)
    elif action == "events":
        events()
    elif action == "bars":
        bars(fetch=fetch, fetch_tags=tags)
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"upgrades: unknown action {action}")
