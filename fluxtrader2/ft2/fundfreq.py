"""Decision BU1 (2026-11-01; PLAN P8 decision BU) — the FUNDING-SETTLEMENT-FREQUENCY CHANGE of a running perpetual as a per-name RULE
event: the source audit, `ft2 fundfreq events|notices|bars|audit`. Nothing here joins a bar AFTER an event to anything; no fold is read for a
label; nothing is registered. The one price read is the RUN-UP row (the name against its block's members over the 24 h BEFORE t0), a
described validity-of-mechanism row, written into decision BU (i) and read here on purpose.

event      a settlement of `funding_archive` (DATA.md; `(symbol, ts) → rate, interval_h`) whose `interval_h` differs from the previous
           settlement's — t0 = that settlement's stamp, the FIRST settlement at the new interval. A SHORTENING (the interval falls — from
           2025 the exchange's answer to a funding pinned at its floor or cap; the shorts, or the longs, pay the same rate up to eight times as
           often) and a LENGTHENING (the rule's revert: hourly → 4 h after 36 cycles ≤ |0.002 %| from 2025-09-01, 16 cycles ≤ |0.025 %| from
           2026-01-02; before 2025-09 by notice). KNOWN-AT: the settlement is public at its own stamp (the archive's `fundingTime`); a
           registration's decision bar is the first 5m bar that CLOSES after t0 — `ts_known` = t0 here, the bar rule is the registration's.
flags      `dir` (shorter / longer), `prev_h` → `new_h`, the contract's age at t0 (its first 5m bar in `candles_5m_archive`, else the first
           settlement in `funding_archive` — a lower bound of the age), the fold of t0, `member_at_t0` (a member of the screener's block that
           holds t0), the trailing-day funding `fund_1d` (the sum of the settled rates over the 24 h before t0 — the crowded side's sign; a
           negative sum: the shorts paid), `fund_7d`, the trigger row `cap_share_7d` (the share of the name's settlements in the 7 days before t0
           at ≥ CAP_FRAC of the largest |rate| the name ever settled before t0), `at_floor` (fund_1d negative), `pair_of` (a lengthening's
           shortening: the last shortening of the name before it, and the episode's length in hours), and for the notice era the release stamp
           of the notice that named the contract (`notice_release`, `notice_lag_h` = t0 − release).
eligible   the contract ≥ PERP_AGE old at t0 (else it is R28's population), t0 inside F3 … F5 for the FROZEN lists (decision BU3: F3+F4 the
           first read, F5 the confirmation); F1+F2's and F0's events are listed and described — 13 of F1's 20 are the batch of 2023-10-12 at
           zero funding, another population — and not frozen. `batch` flags a day with ≥ BATCH_N shortenings (a policy change, not the rule).
lists      output/fundfreq/events.csv (every change with its `why`), output/fundfreq/fundfreq_f34.csv / _f5.csv (the eligible), frozen by hand
           as ft2/fundfreq_f34.csv / _f5.csv and committed BEFORE any bar after an event is read for anything.
notices    catalog 49's lists on disk (data/raw/external/binance_cms/list_49_*.json, read by `ft2 events` for the monitoring tags only): the
           titles with "Settlement Frequency" or "Funding Rate"; their detail pages fetched from the VM (`ft2 events`' endpoint, one a second,
           cached under data/raw/external/binance_cms/detail/) and the USDT contracts each names, with the effective stamp in the body where it
           says one — joined to the events as `notice_release` where a notice names the contract within NOTICE_WINDOW before t0.
bars       per frozen event the count of the name's 5m bars over WINDOW in `candles_5m_archive` (the slice holds the 598 to 2025-12-31 —
           F3+F4 complete without a fetch; F5's bars are §9 #2's 2026 monthly files, a fetch of its own under decision BV).
audit      the counts by fold × dir × member, the batch days, the trailing funding's sign and size, the trigger row, the ages, the hour of day,
           the notice lag (the notice era against the rule era), the run-up row, the cost rows (`costwide`'s taker round trip on the event day
           and the day before), the 2025-09-18 funding-formula change described → output/fundfreq/audit.md / .json, DATA.md `fund_freq_events`.
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

PERP_AGE = pd.Timedelta(days=30)
WINDOW = (pd.Timedelta(days=-2), pd.Timedelta(days=8))
BAR = pd.Timedelta("5min")
HOUR = pd.Timedelta("1h")
DAY = pd.Timedelta(days=1)
EXPECTED_BARS = int((WINDOW[1] - WINDOW[0]) / BAR)
FROZEN_FOLDS = ("F3", "F4", "F5")
TAGS = {"F3": "f34", "F4": "f34", "F5": "f5"}
CAP_FRAC = 0.95                    # a settlement "at the cap": |rate| ≥ this × the largest |rate| the name settled before t0
BATCH_N = 5                        # ≥ this many shortenings on one UTC day = a policy batch (2023-10-12: 13), not the rule's answer to a funding
NOTICE_WINDOW = pd.Timedelta(days=14)
FORMULA_CHANGE = pd.Timestamp("2025-09-18", tz="UTC")   # "Important Updates on Funding Rate Formula and Mark Price Calculation" (released 2025-09-16)
RULE_START = pd.Timestamp("2025-09-01", tz="UTC")       # the automatic revert rule's first day
OUT = Path("output/fundfreq")
LISTS = {"f34": Path(__file__).with_name("fundfreq_f34.csv"), "f5": Path(__file__).with_name("fundfreq_f5.csv")}
SLICE = "candles_5m_archive"
CMS_DIR = data.RAW / "external" / "binance_cms"
CMS_DETAIL = "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query?articleCode={code}"
NOTICE_RE = re.compile(r"Settlement Frequency|Funding Rate", re.I)
SYM_RE = re.compile(r"\b([A-Z0-9]{2,20})USDT\b")
EFFECTIVE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::\d{2})? ?\(UTC\)")
TAKER_BPS = 4.0                    # the harness's taker fee a leg (PLAN P1); the proxy round trip = 2 × fee + the calibrated spread + 2 × impact
NOTIONAL = 10_000
LIST_COLS = ["symbol", "base", "mult", "t0", "ts_known", "fold", "dir", "prev_h", "new_h", "perp_first", "perp_first_source", "perp_age_days",
             "member_at_t0", "fund_1d", "fund_7d", "n_1d", "at_floor", "cap_share_7d", "batch", "pair_of", "episode_h", "notice_release", "notice_lag_h"]


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


def member_at(M: pd.DataFrame, symbol: str, t: pd.Timestamp) -> bool:
    g = M[(M["symbol"] == symbol) & (M["block"] <= t) & (M["block_end"] > t)]
    return bool(len(g))


# ---- the settlements and the changes ------------------------------------------------------------------------------------------
def settlements() -> pd.DataFrame:
    f = pd.read_parquet(data.PROC / "funding_archive.parquet", columns=["symbol", "ts", "rate", "interval_h"])
    f["symbol"] = f["symbol"].astype(str)
    f["ts"] = _utc(f["ts"])
    return f.sort_values(["symbol", "ts"]).reset_index(drop=True)


def perp_first(symbols: list[str], F: pd.DataFrame) -> pd.DataFrame:
    """Per symbol the contract's first bar: the archive slice's first 5m bar where held (`archive 5m`), else its first settlement (`funding`,
    a lower bound of the age — a contract settles from its first day)."""
    rows = {s: (pd.NaT, "none") for s in symbols}
    if (data.PROC / f"{SLICE}.parquet").exists() or (data.PROC / SLICE).is_dir():
        c = data.load(SLICE, columns=["symbol", "open_time"], symbols=list(symbols))
        if len(c):
            c["open_time"] = _utc(c["open_time"])
            for s, t in c.groupby("symbol", observed=True)["open_time"].min().items():
                rows[str(s)] = (t, "archive 5m")
    for s, t in F.groupby("symbol")["ts"].min().items():
        if rows.get(s, (pd.NaT, "none"))[1] == "none":
            rows[s] = (t, "funding")
    return pd.DataFrame([{"symbol": s, "perp_first": t, "perp_first_source": src} for s, (t, src) in rows.items()])


def changes(F: pd.DataFrame) -> pd.DataFrame:
    """Every settlement whose interval differs from the previous settlement's of the same name, with the trailing funding and the trigger row."""
    F = F.sort_values(["symbol", "ts"]).reset_index(drop=True)
    F["prev_h"] = F.groupby("symbol")["interval_h"].shift()
    ch = F[F["prev_h"].notna() & (F["prev_h"] != F["interval_h"])].copy()
    ch = ch.rename(columns={"ts": "t0", "interval_h": "new_h"})
    by = {s: g for s, g in F.groupby("symbol")}
    rows = []
    for r in ch.itertuples(index=False):
        g = by[r.symbol]
        before = g[g["ts"] < r.t0]
        d1 = before[before["ts"] >= r.t0 - DAY]
        d7 = before[before["ts"] >= r.t0 - 7 * DAY]
        cap = before["rate"].abs().max() if len(before) else np.nan
        cap_share = float((d7["rate"].abs() >= CAP_FRAC * cap).mean()) if len(d7) and cap and cap > 0 else np.nan
        rows.append({"symbol": r.symbol, "t0": r.t0, "prev_h": float(r.prev_h), "new_h": float(r.new_h), "rate_t0": float(r.rate),
                     "dir": "shorter" if r.new_h < r.prev_h else "longer",
                     "fund_1d": float(d1["rate"].sum()) if len(d1) else np.nan, "n_1d": int(len(d1)),
                     "fund_7d": float(d7["rate"].sum()) if len(d7) else np.nan, "cap_share_7d": cap_share, "cap_rate": float(cap) if cap == cap else np.nan})
    C = pd.DataFrame(rows).sort_values(["t0", "symbol"]).reset_index(drop=True)
    if not len(C):
        return C
    C["at_floor"] = C["fund_1d"] < 0
    day = C["t0"].dt.floor("D")
    n_day = C[C["dir"] == "shorter"].groupby(day[C["dir"] == "shorter"]).size()
    C["batch"] = (C["dir"] == "shorter") & day.map(n_day).fillna(0).ge(BATCH_N)
    # a lengthening's shortening: the last shortening of the name before it
    last_short: dict[str, pd.Timestamp] = {}
    pair, ep = [], []
    for r in C.itertuples(index=False):
        if r.dir == "shorter":
            last_short[r.symbol] = r.t0
            pair.append(pd.NaT); ep.append(np.nan)
        elif r.symbol in last_short:
            pair.append(last_short[r.symbol]); ep.append((r.t0 - last_short[r.symbol]) / HOUR)
        else:
            pair.append(pd.NaT); ep.append(np.nan)
    C["pair_of"] = pd.to_datetime(pd.Series(pair, index=C.index), utc=True)
    C["episode_h"] = ep
    return C


def events(write: bool = True, with_notices: bool = True) -> pd.DataFrame:
    F = settlements()
    C = changes(F)
    syms = sorted(set(C["symbol"]))
    pf = perp_first(syms, F).set_index("symbol")
    M = member_symbols()
    C["base"] = C["symbol"].map(cb.base)
    C["mult"] = C["symbol"].map(cb.mult_of)
    C["perp_first"] = C["symbol"].map(pf["perp_first"])
    C["perp_first_source"] = C["symbol"].map(pf["perp_first_source"])
    C["perp_age_days"] = (C["t0"] - C["perp_first"]).dt.days
    C["fold"] = C["t0"].map(fold_of)
    C["ts_known"] = C["t0"]
    C["member_at_t0"] = [member_at(M, s, t) for s, t in zip(C["symbol"], C["t0"])]
    C["notice_release"], C["notice_lag_h"] = pd.NaT, np.nan
    if with_notices:
        N = notices_table(fetch=False)
        if N is not None and len(N):
            C = join_notices(C, N)
    why = []
    for r in C.itertuples(index=False):
        if r.perp_first_source == "none" or pd.isna(r.perp_age_days):
            why.append("no first bar known")
        elif r.perp_age_days < PERP_AGE.days:
            why.append(f"the contract younger than {PERP_AGE.days} days at t0 (a launch, R28's population)")
        elif r.fold not in FROZEN_FOLDS:
            why.append("outside F3 … F5 (listed, described, not frozen)")
        else:
            why.append("eligible")
    C["why"] = why
    C = C[[*LIST_COLS, "rate_t0", "cap_rate", "why"]].sort_values(["t0", "symbol"]).reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        C.to_csv(OUT / "events.csv", index=False)
        el = C[C["why"] == "eligible"]
        for tag in ("f34", "f5"):
            el[el["fold"].map(TAGS) == tag][LIST_COLS].to_csv(OUT / f"fundfreq_{tag}.csv", index=False)
        print(summary(C))
    return C


def summary(C: pd.DataFrame) -> str:
    el = C[C["why"] == "eligible"]
    lines = [f"{len(C)} interval changes on {C['symbol'].nunique()} names; {len(el)} eligible (the contract ≥ {PERP_AGE.days} d old, t0 in F3 … F5)"]
    if len(el):
        lines.append("eligible by fold × dir:\n" + el.groupby(["fold", "dir"]).size().unstack(fill_value=0).to_string())
        sh = el[el["dir"] == "shorter"]
        lines.append("shortenings by fold × at_floor (trailing-day funding negative):\n" + sh.groupby(["fold", "at_floor"]).size().unstack(fill_value=0).to_string())
        lines.append(f"members at t0: {int(el['member_at_t0'].sum())} of {len(el)}; shortenings in a batch day: {int(sh['batch'].sum())}; "
                     f"|fund_1d| median of the shortenings {sh['fund_1d'].abs().median() * 100:.2f} % a day; age median {el['perp_age_days'].median():.0f} d")
    allsh = C[C["dir"] == "shorter"]
    lines.append("every shortening by fold (not only the eligible):\n" + allsh.groupby(["fold", "batch"], dropna=False).size().unstack(fill_value=0).to_string())
    lines.append("not eligible, by reason:\n" + C[C["why"] != "eligible"]["why"].value_counts().to_string())
    return "\n".join(lines)


def frozen(tags=("f34", "f5")) -> pd.DataFrame:
    parts = []
    for tag in tags:
        p = LISTS[tag]
        if p.exists():
            d = pd.read_csv(p)
            for c in ("t0", "ts_known", "perp_first", "pair_of", "notice_release"):
                d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601")
            parts.append(d.assign(list=tag))
    if not parts:
        raise SystemExit(f"fundfreq: no frozen list at {list(LISTS.values())} — run `ft2 fundfreq events`, freeze the lists, commit")
    return pd.concat(parts, ignore_index=True)


# ---- the notices (catalog 49 on disk; the details fetched from the VM) ---------------------------------------------------------
def notice_titles() -> pd.DataFrame:
    rows = []
    for p in sorted(glob.glob(str(CMS_DIR / "list_49_*.json"))):
        for a in json.load(open(p)):
            if isinstance(a, dict) and "title" in a and NOTICE_RE.search(a["title"]):
                rows.append({"id": int(a["id"]), "code": a["code"], "title": a["title"], "release": pd.Timestamp(int(a["releaseDate"]), unit="ms", tz="UTC")})
    if not rows:
        return pd.DataFrame(columns=["id", "code", "title", "release"])
    return pd.DataFrame(rows).drop_duplicates("id").sort_values("release").reset_index(drop=True)


def _detail(code: str, fetch: bool) -> dict | None:
    p = CMS_DIR / "detail" / f"{code}.json"
    if p.exists():
        return json.load(open(p))
    if not fetch:
        return None
    from .events import _get
    d = json.loads(_get(CMS_DETAIL.format(code=code)))["data"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    time.sleep(1.2)
    return d


def _body_text(d: dict) -> str:
    """The article's text: the body is a JSON tree of nodes (2025–26) or HTML (older) — every `text` leaf, else the tags stripped."""
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
        return " ".join(out)
    except (ValueError, TypeError):
        return html.unescape(re.sub(r"<[^>]+>", " ", b))


def notices_table(fetch: bool = False, write: bool = False) -> pd.DataFrame | None:
    """One row a (notice, contract): the release, the title, the contracts named in the summary or the body, the first effective stamp the
    body states. Without a cached detail a notice keeps one row with symbol ''."""
    T = notice_titles()
    if not len(T):
        return None
    rows = []
    for r in T.itertuples(index=False):
        d = _detail(r.code, fetch)
        syms, eff, text = [], pd.NaT, ""
        if d is not None:
            text = (d.get("seoDesc") or "") + " " + _body_text(d)
            syms = list(dict.fromkeys(f"{b}USDT" for b in SYM_RE.findall(text)))
            m = EFFECTIVE_RE.search(text)
            if m:
                eff = pd.Timestamp(f"{m.group(1)} {m.group(2)}", tz="UTC")
        for s in syms or [""]:
            rows.append({"id": r.id, "code": r.code, "release": r.release, "title": r.title, "symbol": s, "effective": eff, "has_detail": d is not None,
                         "kind": ("resume" if re.search(r"Resumed|revert", r.title + " " + text[:400], re.I) else "frequency") if "Frequency" in r.title else "rate"})
    N = pd.DataFrame(rows)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        N.to_csv(OUT / "notices.csv", index=False)
    return N


def join_notices(C: pd.DataFrame, N: pd.DataFrame) -> pd.DataFrame:
    """Per change the last notice that names the contract within NOTICE_WINDOW before t0 (a notice-era event); the rule era has none."""
    N = N[N["symbol"] != ""]
    rel = {s: np.sort(pd.DatetimeIndex(g["release"]).tz_convert("UTC").tz_localize(None).to_numpy().astype("datetime64[ns]")) for s, g in N.groupby("symbol")}
    out_rel, out_lag = [], []
    for r in C.itertuples(index=False):
        t = rel.get(r.symbol)
        if t is None:
            out_rel.append(pd.NaT); out_lag.append(np.nan); continue
        t0 = np.datetime64(r.t0.tz_convert("UTC").tz_localize(None), "ns")
        i = np.searchsorted(t, t0) - 1
        if i >= 0 and (t0 - t[i]) <= np.timedelta64(int(NOTICE_WINDOW / pd.Timedelta("1ns")), "ns"):
            rl = pd.Timestamp(t[i]).tz_localize("UTC")
            out_rel.append(rl); out_lag.append(float((r.t0 - rl) / HOUR))
        else:
            out_rel.append(pd.NaT); out_lag.append(np.nan)
    C = C.copy()
    C["notice_release"] = pd.to_datetime(pd.Series(out_rel, index=C.index), utc=True)
    C["notice_lag_h"] = out_lag
    return C


# ---- the bars (counts) --------------------------------------------------------------------------------------------------------
def coverage(L: pd.DataFrame) -> pd.DataFrame:
    w = L[["symbol", "t0", "fold", "dir"]].copy()
    w["a"], w["b"] = w["t0"] + WINDOW[0], w["t0"] + WINDOW[1]
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
        out.append({"symbol": r.symbol, "t0": r.t0, "fold": r.fold, "dir": r.dir, "bars": n, "expected": EXPECTED_BARS, "share": n / EXPECTED_BARS})
    return pd.DataFrame(out)


def bars(fetch: bool = False, fetch_tags: tuple[str, ...] = ("f34",)) -> dict:
    """The frozen events' bars counted; with `fetch` the (name, month) files missing for the events of `fetch_tags` (F3+F4 by default — the
    slice's non-member names end at 2024-08; F5's 2026 months are decision BV's own fetch) come from the archive's monthly 5m klines and the
    slice is re-ingested whole under krlist's fingerprint (R28's route: every name it held comes back row for row, or the ingest is void)."""
    from . import archive, krlist
    L = frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    cov = coverage(L)
    cov["list"] = L["list"].to_numpy()
    need = krlist.missing_months(cov[cov["list"].isin(fetch_tags)].assign(months=[archive.months_between((t + WINDOW[0]).date(), (t + WINDOW[1] - BAR).date()) for t in cov[cov["list"].isin(fetch_tags)]["t0"]]))
    rep = {"events": int(len(cov)), "complete": int((cov["share"] >= 0.95).sum()),
           "by_fold": {str(k): {"events": int(len(g)), "complete": int((g["share"] >= 0.95).sum()), "median_share": float(g["share"].median())} for k, g in cov.groupby("fold")},
           "missing_symbols": sorted(set(cov[cov["share"] < 0.95]["symbol"])), "missing_months_in_fetch_tags": need}
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
        rep["complete_after"] = int((cov["share"] >= 0.95).sum())
        rep["by_fold_after"] = {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")}
    cov.drop(columns=["list"], errors="ignore").to_csv(OUT / "bars.csv", index=False)
    print(json.dumps(rep, indent=1, default=str))
    return rep


# ---- the audit ----------------------------------------------------------------------------------------------------------------
def runup(L: pd.DataFrame, M: pd.DataFrame) -> pd.DataFrame:
    """The run-up row, described: per event the name's close-to-close return over [t0 − 24 h, t0] from the 5m bars, minus the mean of the same
    over the block's members with bars (the name left out). The bars BEFORE t0 only; nothing after t0 is read."""
    out = []
    syms_all = sorted(set(L["symbol"]) | set(M["symbol"]))
    if not ((data.PROC / f"{SLICE}.parquet").exists() or (data.PROC / SLICE).is_dir()):
        return pd.DataFrame(columns=["symbol", "t0", "own_bps", "peers_bps", "runup_bps", "n_peers"])
    c = data.load(SLICE, columns=["symbol", "open_time", "close"], symbols=syms_all)
    c["symbol"] = c["symbol"].astype(str)
    c["open_time"] = _utc(c["open_time"])
    by = {s: g.set_index("open_time")["close"].sort_index() for s, g in c.groupby("symbol")}

    def ret(s: str, a: pd.Timestamp, b: pd.Timestamp) -> float:
        x = by.get(s)
        if x is None:
            return np.nan
        xa = x[(x.index >= a - HOUR) & (x.index < a)]
        xb = x[(x.index >= b - HOUR) & (x.index < b)]
        if not len(xa) or not len(xb):
            return np.nan
        return float(xb.iloc[-1] / xa.iloc[-1] - 1) * 1e4

    for r in L.itertuples(index=False):
        a, b = r.t0 - DAY, r.t0
        own = ret(r.symbol, a, b)
        peers = M[(M["block"] <= r.t0) & (M["block_end"] > r.t0) & (M["symbol"] != r.symbol)]["symbol"].unique()
        pr = [v for v in (ret(p, a, b) for p in peers) if v == v]
        out.append({"symbol": r.symbol, "t0": r.t0, "own_bps": own, "peers_bps": float(np.mean(pr)) if pr else np.nan,
                    "runup_bps": own - float(np.mean(pr)) if pr and own == own else np.nan, "n_peers": len(pr)})
    return pd.DataFrame(out)


def cost_rows(L: pd.DataFrame) -> pd.DataFrame:
    """`costwide`'s taker round trip on the event day and the day before (2 × fee + the calibrated spread + 2 × the impact at NOTIONAL)."""
    from .cost import DAILY_WIDE
    cols = ["symbol", "t0", "rt_day_before", "rt_day0"]
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
        out.append({"symbol": r.symbol, "t0": r.t0, "rt_day_before": float(k.get((r.symbol, d0 - DAY), np.nan)), "rt_day0": float(k.get((r.symbol, d0), np.nan))})
    return pd.DataFrame(out)


def audit(today: pd.Timestamp | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    L = frozen()
    E = pd.read_csv(OUT / "events.csv", parse_dates=["t0"]) if (OUT / "events.csv").exists() else None
    M = member_symbols()
    cov = coverage(L)
    ru = runup(L, M)
    cr = cost_rows(L)
    OUT.mkdir(parents=True, exist_ok=True)
    ru.to_csv(OUT / "runup.csv", index=False)
    cr.to_csv(OUT / "costs.csv", index=False)
    sh = L[L["dir"] == "shorter"]
    lo = L[L["dir"] == "longer"]
    by_fd = L.groupby(["fold", "dir"]).size().unstack(fill_value=0)
    by_floor = sh.groupby(["fold", "at_floor"]).size().unstack(fill_value=0)
    by_from = sh.groupby(["fold", sh["prev_h"].astype(int).astype(str) + "h>" + sh["new_h"].astype(int).astype(str) + "h"]).size().unstack(fill_value=0)
    q_age = L["perp_age_days"].quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    q_fund = (sh["fund_1d"].abs() * 100).quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(3).to_dict()
    q_cap = sh["cap_share_7d"].quantile([0.1, 0.5, 0.9]).round(3).to_dict()
    hod = pd.DatetimeIndex(sh["t0"]).hour.value_counts().sort_index()
    lag = sh["notice_lag_h"].dropna()
    ru_sh = ru.merge(sh[["symbol", "t0", "fold"]], on=["symbol", "t0"])
    q_ru = ru_sh["runup_bps"].quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    ru_fold = ru_sh.groupby("fold")["runup_bps"].median().round(0).to_dict()
    ru_big = float((ru_sh["runup_bps"] >= 500).mean()) if len(ru_sh) else np.nan
    cr_sh = cr.merge(sh[["symbol", "t0"]], on=["symbol", "t0"])
    q_rt = cr_sh[["rt_day_before", "rt_day0"]].astype(float).median().round(1).to_dict() if len(cr_sh) else {"rt_day_before": None, "rt_day0": None}
    rt_missing = int(cr_sh["rt_day0"].isna().sum()) if len(cr_sh) else int(len(sh))
    ep = lo["episode_h"].dropna()
    J = {"generated": f"{today:%Y-%m-%d %H:%M} UTC", "events": int(len(L)), "shortenings": int(len(sh)), "lengthenings": int(len(lo)),
         "by_fold_dir": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fd.iterrows()},
         "shortenings_by_fold_at_floor": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_floor.iterrows()},
         "shortenings_by_fold_from_to": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_from.iterrows()},
         "members_at_t0": {"shortenings": int(sh["member_at_t0"].sum()), "all": int(L["member_at_t0"].sum())}, "distinct_names": int(L["symbol"].nunique()),
         "batch_shortenings": int(sh["batch"].sum()), "perp_age_days_q10_50_90": q_age, "perp_first_source": L["perp_first_source"].value_counts().to_dict(),
         "fund_1d_abs_pct_quantiles": q_fund, "cap_share_7d_q10_50_90": q_cap, "t0_hour_utc": {int(k): int(v) for k, v in hod.items()},
         "notice_era": {"with_notice": int(len(lag)), "lag_h_median": float(lag.median()) if len(lag) else None, "lag_h_q10_90": lag.quantile([0.1, 0.9]).round(1).tolist() if len(lag) else None,
                        "rule_era_without_notice": int(((sh["t0"] >= RULE_START) & sh["notice_lag_h"].isna()).sum()), "pre_rule_without_notice": int(((sh["t0"] < RULE_START) & sh["notice_lag_h"].isna()).sum())},
         "episode_h_q10_50_90": ep.quantile([0.1, 0.5, 0.9]).round(0).to_dict() if len(ep) else None, "lengthenings_paired": int(lo["pair_of"].notna().sum()),
         "bars_complete": int((cov["share"] >= 0.95).sum()), "bars_by_fold": {str(k): int((g["share"] >= 0.95).sum()) for k, g in cov.groupby("fold")},
         "runup_bps_q10_50_90": q_ru, "runup_median_by_fold": ru_fold, "runup_share_ge_500": ru_big, "runup_n": int(ru_sh["runup_bps"].notna().sum()),
         "taker_rt_median_bps": q_rt, "taker_rt_missing_day0": rt_missing,
         "formula_change": f"{FORMULA_CHANGE.date()}: the funding formula and the mark-price calculation changed (notice released 2025-09-16) — events after it {int((sh['t0'] >= FORMULA_CHANGE).sum())} of the shortenings",
         "candidates": None if E is None else {"n": int(len(E)), "why": E["why"].value_counts().to_dict(), "F1F2_shortenings": int(((E["fold"].isin(["F1", "F2"])) & (E["dir"] == "shorter")).sum()),
                                               "F1F2_batch": int(((E["fold"].isin(["F1", "F2"])) & (E["dir"] == "shorter") & E["batch"]).sum())},
         "known_at": "t0 = the first settlement at the new interval, public at its own stamp (funding_archive's fundingTime); the decision bar of a registration is the first 5m bar that closes after t0; nothing after t0 is read here"}
    (OUT / "audit.json").write_text(json.dumps(J, indent=1, default=str))
    md = [f"# fundfreq — the funding-settlement-frequency change of a running perpetual as a per-name rule event (decision BU1)",
          f"generated {J['generated']} · the frozen lists {', '.join(p.name for p in LISTS.values())}", "",
          f"**{len(L)} eligible events** ({len(sh)} shortenings, {len(lo)} lengthenings) on {J['distinct_names']} names (the contract ≥ {PERP_AGE.days} d old at t0, t0 in F3 … F5); "
          f"members at t0 {J['members_at_t0']['shortenings']} of the shortenings; the contract's age p10 / p50 / p90 {q_age.get(0.1)} / {q_age.get(0.5)} / {q_age.get(0.9)} days; "
          f"the first bar's source {J['perp_first_source']}; shortenings on a batch day {J['batch_shortenings']}.", "",
          "## By fold × direction", by_fd.to_string(), "", "## Shortenings by fold × at_floor (the trailing-day funding negative — the shorts paid)", by_floor.to_string(), "",
          "## Shortenings by fold × interval (from > to)", by_from.to_string(), "",
          "## The trailing-day funding at a shortening, |sum of the rates| in % a day (quantiles)", json.dumps(q_fund), "",
          f"## The trigger row — the share of the 7 days' settlements at ≥ {CAP_FRAC:.0%} of the name's largest |rate| before t0 (q10 / q50 / q90)", json.dumps(q_cap), "",
          "## The hour of day of t0 (UTC)", hod.to_string(), "",
          "## The notice era against the rule era", json.dumps(J["notice_era"]), "",
          "## The lengthenings — the episode's length in hours from the paired shortening (q10 / q50 / q90)", json.dumps(J["episode_h_q10_50_90"]), "",
          f"## Bars in the window (t0 − 2 d → t0 + 8 d, {EXPECTED_BARS} expected)", f"complete (≥ 95 %) {J['bars_complete']} of {len(L)}; by fold {json.dumps(J['bars_by_fold'])}", "",
          "## The run-up row, described — the name against its block's members over the 24 h BEFORE t0 (bps; shortenings)",
          f"q10 / q50 / q90 {json.dumps(q_ru)}; by fold (median) {json.dumps(ru_fold)}; share ≥ +500 bps {ru_big:.2f}; n {J['runup_n']}", "",
          "## The cost rows — `costwide`'s taker round trip on the day before t0 and on t0's day (bps, median; shortenings)", f"{json.dumps(q_rt)}; missing on day 0: {rt_missing}", "",
          "## The funding formula change", J["formula_change"], "",
          "## Candidates not eligible", "" if E is None else E[E["why"] != "eligible"]["why"].value_counts().to_string(),
          "" if E is None else f"F1+F2 shortenings {J['candidates']['F1F2_shortenings']}, of them on a batch day {J['candidates']['F1F2_batch']} — listed, described, not frozen", "",
          "## Known-at", J["known_at"]]
    (OUT / "audit.md").write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, fetch: bool = False) -> None:
    if action == "events":
        events()
    elif action == "notices":
        N = notices_table(fetch=fetch, write=True)
        if N is None:
            sys.exit("fundfreq: no catalog 49 list on disk (data/raw/external/binance_cms/list_49_*.json) — run `ft2 events fetch --source binance`")
        print(f"{N['id'].nunique()} notices, {N[N['has_detail']]['id'].nunique()} with a detail, {(N['symbol'] != '').sum()} (notice, contract) rows; by kind "
              f"{N.drop_duplicates('id')['kind'].value_counts().to_dict()}; without a detail {int((~N['has_detail']).sum())}")
    elif action == "bars":
        bars(fetch=fetch)
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"fundfreq: unknown action {action}")
