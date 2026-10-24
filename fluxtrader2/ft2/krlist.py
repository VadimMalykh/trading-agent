"""Decision BM1 (2026-10-24; PLAN P8 decision BM) — the KOREAN LISTING of an existing perpetual as a per-name EVENT: the source audit,
`ft2 krlist events|bars|audit`. Nothing here reads a price of an event's name against anything; no fold is read; nothing is registered.

event      a KRW market of Upbit or Bithumb (DATA.md `krw_1h_upbit, krw_1h_bithumb`) whose first hourly bar t0 lies at least MARGIN after the
           fetch's start (a first bar in the fetch's first days is a thin market's late first trade — BNT 01:00, OGN 03:00 UTC on 2023-04-01 —
           not a listing), for a name whose Binance perpetual is at least PERP_AGE old at t0 (else it is R28's population, a launch). The
           perpetual's first bar: `candles_5m_archive` where the name is held, else the first day of the month AFTER `um_first_month.csv`'s
           first month (an upper bound of the start → the age a lower bound). KNOWN-AT: the bar that starts at t0 is final at t0 + 1 h
           (DATA.md's rule for both venues) — the only stamp a registration may use; no announcement board is read (Bithumb's API serves its
           latest five notices only, Upbit's board refuses a script; the probe of 2026-10-24 in PLAN P8 decision BM's DECIDED tail).
flags      `first_korean` — the other venue has no bar before t0 (in or before the window); `other_venue_t0`; `member_at_t0` — the name is a
           member of the screener's block that holds t0; the fold of t0; the base and the contract multiple.
eligible   the perpetual old enough AND t0 inside F1 … F4. F5's events are listed and NOT frozen (F5 has no member blocks and is the last fold).
lists      output/krlist/events.csv (every candidate with its `why`), output/krlist/krlistings_f12.csv / _f34.csv (the eligible), frozen by
           hand as ft2/krlistings_f12.csv / _f34.csv and committed BEFORE any bar of an event's name is read for anything.
bars       per frozen event the 5m bars of its name over WINDOW in `candles_5m_archive` — COUNTS; with --fetch the (name, month) files missing
           are fetched from the archive's monthly klines and the slice re-ingested whole (R28's route) with every name it held plus the
           event names, guarded by a fingerprint per name (rows, first, last, the sums of close and volume on the OLD extent) saved before
           and checked after (the row count exact, the sums to 1e-12 relative — the same rows in the same order sum to the same float) —
           a name that changes is a void.
audit      the counts by fold × venue × first_korean, the member share, the perpetual's age, the first bar's hour (KST), the arriving crowd's
           size — the venue's KRW volume over the first 24 bars in USDT against Binance's quote volume on the perpetual over the same hours,
           and over days 2 … 7 (volumes, not prices; the FX through KRW-USDT where the venue lists it, else KRW-BTC over BTCUSDT) →
           output/krlist/audit.md / .json and a DATA.md section `krw_listings`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data, folds, krw
from . import coinbase as cb

VENUES = ("upbit", "bithumb")
START = pd.Timestamp(krw.START, tz="UTC")
MARGIN = pd.Timedelta(days=7)
PERP_AGE = pd.Timedelta(days=30)
WINDOW = (pd.Timedelta(days=-2), pd.Timedelta(days=8))
BAR = pd.Timedelta("5min")
HOUR = pd.Timedelta("1h")
EXPECTED_BARS = int((WINDOW[1] - WINDOW[0]) / BAR)
FROZEN_FOLDS = ("F1", "F2", "F3", "F4")
TAGS = {"F1": "f12", "F2": "f12", "F3": "f34", "F4": "f34"}
OUT = Path("output/krlist")
LISTS = {"f12": Path(__file__).with_name("krlistings_f12.csv"), "f34": Path(__file__).with_name("krlistings_f34.csv")}
FIRST = data.RAW / "external" / "binance" / "um_first_month.csv"
SLICE = "candles_5m_archive"
LIST_COLS = ["venue", "market", "symbol", "base", "mult", "t0", "ts_known", "fold", "perp_first", "perp_first_source", "perp_age_days",
             "first_korean", "other_venue_t0", "member_at_t0"]
CONTROL = krw.CONTROL
BTC = krw.BTC
KST = pd.Timedelta(hours=9)


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


# ---- the venues' first bars (no price) ---------------------------------------------------------------------------------------
def first_bars(venue: str) -> pd.DataFrame:
    """Per KRW market of `venue`: its symbol, first bar t0 and row count. The control is left out. Columns read: market, symbol, ts."""
    d = pd.read_parquet(krw.parquet_path(venue), columns=["market", "symbol", "ts"])
    d["ts"] = _utc(d["ts"])
    d = d[d["market"] != CONTROL]
    g = d.groupby("market", observed=True).agg(symbol=("symbol", "first"), t0=("ts", "min"), rows=("ts", "size")).reset_index()
    g.insert(0, "venue", venue)
    return g


def perp_first(symbols: list[str]) -> pd.DataFrame:
    """Per symbol the perpetual's first bar: the archive slice's first 5m bar where held (`archive 5m`), else the first day of the month after
    `um_first_month.csv`'s first month (`first_month`, an upper bound of the start), else NaT."""
    rows = {s: (pd.NaT, "none") for s in symbols}
    if (data.PROC / f"{SLICE}.parquet").exists():
        c = data.load(SLICE, columns=["symbol", "open_time"], symbols=list(symbols))
        if len(c):
            c["open_time"] = _utc(c["open_time"])
            for s, t in c.groupby("symbol", observed=True)["open_time"].min().items():
                rows[str(s)] = (t, "archive 5m")
    if FIRST.exists():
        fm = pd.read_csv(FIRST, dtype=str).fillna("")
        fm = fm[fm["first_month"] != ""].set_index("symbol")["first_month"]
        for s in symbols:
            if rows[s][1] == "none" and s in fm.index:
                m = pd.Period(fm[s], freq="M") + 1
                rows[s] = (pd.Timestamp(m.start_time, tz="UTC"), "first_month")
    return pd.DataFrame([{"symbol": s, "perp_first": t, "perp_first_source": src} for s, (t, src) in rows.items()])


def member_at(M: pd.DataFrame, symbol: str, t: pd.Timestamp) -> bool:
    g = M[(M["symbol"] == symbol) & (M["block"] <= t) & (M["block_end"] > t)]
    return bool(len(g))


def events(write: bool = True) -> pd.DataFrame:
    """Every candidate listing on both venues with its flags and `why`; the eligible ones written as the lists to freeze."""
    fb = pd.concat([first_bars(v) for v in VENUES], ignore_index=True)
    fb = fb[fb["symbol"].notna() & (fb["t0"] > START)].copy()
    syms = sorted(set(fb["symbol"].astype(str)))
    pf = perp_first(syms).set_index("symbol")
    M = member_symbols()
    other = {v: fb[fb["venue"] == v].set_index("symbol")["t0"] for v in VENUES}
    rows = []
    for r in fb.itertuples(index=False):
        sym, t0 = str(r.symbol), pd.Timestamp(r.t0)
        p, src = pf.loc[sym, "perp_first"], pf.loc[sym, "perp_first_source"]
        age = (t0 - p).days if pd.notna(p) else np.nan
        ov = [v for v in VENUES if v != r.venue][0]
        ot = other[ov].get(sym, pd.NaT)
        fold = fold_of(t0)
        if t0 < START + MARGIN:
            why = "before the window's margin (a thin market's late first trade, not a listing)"
        elif src == "none":
            why = "no perpetual first bar known"
        elif age < PERP_AGE.days:
            why = f"the perpetual younger than {PERP_AGE.days} days at t0 (a launch, R28's population)"
        elif fold not in FROZEN_FOLDS:
            why = "outside F1 … F4" + (" (F5: listed, not frozen)" if fold == "F5" else "")
        else:
            why = "eligible"
        rows.append({"venue": r.venue, "market": r.market, "symbol": sym, "base": cb.base(sym), "mult": cb.mult_of(sym), "t0": t0, "ts_known": t0 + HOUR,
                     "fold": fold, "perp_first": p, "perp_first_source": src, "perp_age_days": age,
                     "first_korean": bool(pd.isna(ot) or ot > t0), "other_venue_t0": ot, "member_at_t0": member_at(M, sym, t0), "rows": int(r.rows), "why": why})
    E = pd.DataFrame(rows).sort_values(["t0", "venue", "market"]).reset_index(drop=True)
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        E.to_csv(OUT / "events.csv", index=False)
        el = E[E["why"] == "eligible"]
        for tag in ("f12", "f34"):
            sub = el[el["fold"].map(TAGS) == tag][LIST_COLS]
            sub.to_csv(OUT / f"krlistings_{tag}.csv", index=False)
        print(summary(E))
    return E


def summary(E: pd.DataFrame) -> str:
    el = E[E["why"] == "eligible"]
    lines = [f"{len(E)} candidate first bars after {START.date()}; {len(el)} eligible (the perpetual ≥ {PERP_AGE.days} d old, t0 in F1 … F4)"]
    if len(el):
        t = el.groupby(["fold", "venue"], observed=True).size().unstack(fill_value=0)
        lines.append("eligible by fold × venue:\n" + t.to_string())
        fk = el.groupby(["fold", "first_korean"], observed=True).size().unstack(fill_value=0)
        lines.append("eligible by fold × first_korean:\n" + fk.to_string())
        lines.append(f"members at t0: {int(el['member_at_t0'].sum())} of {len(el)}; perpetual age median {el['perp_age_days'].median():.0f} d")
    lines.append("not eligible, by reason:\n" + E[E["why"] != "eligible"]["why"].value_counts().to_string())
    return "\n".join(lines)


def frozen(tags=("f12", "f34")) -> pd.DataFrame:
    parts = []
    for tag in tags:
        p = LISTS[tag]
        if p.exists():
            d = pd.read_csv(p)
            for c in ("t0", "ts_known", "perp_first", "other_venue_t0"):
                d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601")
            parts.append(d.assign(list=tag))
    if not parts:
        raise SystemExit(f"krlist: no frozen list at {list(LISTS.values())} — run `ft2 krlist events`, freeze the lists, commit")
    return pd.concat(parts, ignore_index=True)


# ---- the bars (counts) and the fingerprint ---------------------------------------------------------------------------------------
def windows(L: pd.DataFrame) -> pd.DataFrame:
    w = L[["venue", "market", "symbol", "t0"]].copy()
    w["a"], w["b"] = w["t0"] + WINDOW[0], w["t0"] + WINDOW[1]
    return w


def coverage(L: pd.DataFrame) -> pd.DataFrame:
    """Per frozen event the count of the name's 5m bars inside [t0 − 2 d, t0 + 8 d) in the archive slice, and the months the window spans."""
    w = windows(L)
    syms = sorted(set(w["symbol"]))
    have = pd.DataFrame(columns=["symbol", "open_time"])
    if (data.PROC / f"{SLICE}.parquet").exists():
        have = data.load(SLICE, columns=["symbol", "open_time"], symbols=syms)
        have["open_time"] = _utc(have["open_time"])
    by = {str(s): np.sort(g["open_time"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")) for s, g in have.groupby("symbol", observed=True)}
    out = []
    for r in w.itertuples(index=False):
        t = by.get(r.symbol, np.array([], dtype="datetime64[ns]"))
        a, b = np.datetime64(r.a.tz_convert("UTC").tz_localize(None), "ns"), np.datetime64(r.b.tz_convert("UTC").tz_localize(None), "ns")
        n = int(np.searchsorted(t, b) - np.searchsorted(t, a))
        out.append({"venue": r.venue, "market": r.market, "symbol": r.symbol, "t0": r.t0, "bars": n, "expected": EXPECTED_BARS, "share": n / EXPECTED_BARS,
                    "months": archive.months_between(r.a.date(), (r.b - BAR).date())})
    return pd.DataFrame(out)


def missing_months(cov: pd.DataFrame, min_share: float = 0.95) -> dict[str, list[str]]:
    """(symbol → months) for the events whose window is short of bars."""
    need: dict[str, set[str]] = {}
    for r in cov[cov["share"] < min_share].itertuples(index=False):
        need.setdefault(r.symbol, set()).update(r.months)
    return {s: sorted(m) for s, m in sorted(need.items())}


def fingerprint(extent: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per name of the archive slice: rows, first, last, the sums of close and volume. With `extent` (symbol, first, last): those names on the
    rows inside their OLD extent — a name that gained months is compared on what it held before (R28's rule)."""
    d = data.load(SLICE, columns=["symbol", "open_time", "close", "volume"])
    d["open_time"] = _utc(d["open_time"])
    d["symbol"] = d["symbol"].astype(str)
    if extent is not None:
        d = d.merge(extent[["symbol", "first", "last"]], on="symbol")
        d = d[(d["open_time"] >= d["first"]) & (d["open_time"] <= d["last"])].drop(columns=["first", "last"])
    g = d.groupby("symbol", observed=True)
    return g.agg(rows=("open_time", "size"), first=("open_time", "min"), last=("open_time", "max"), sum_close=("close", "sum"), sum_volume=("volume", "sum")).reset_index()


def fingerprint_check(before: pd.DataFrame, after_fn=fingerprint) -> dict:
    """Every name of `before` comes back with the same rows and sums on its old extent, or the ingest is void."""
    b = before.copy()
    b["first"], b["last"] = _utc(b["first"]), _utc(b["last"])
    a = after_fn(b).set_index("symbol")
    bad = []
    for r in b.itertuples(index=False):
        if r.symbol not in a.index:
            bad.append({"symbol": r.symbol, "why": "missing after"})
            continue
        x = a.loc[r.symbol]
        if int(x["rows"]) != int(r.rows) or not np.isclose(x["sum_close"], r.sum_close, rtol=1e-12, atol=1e-6) or not np.isclose(x["sum_volume"], r.sum_volume, rtol=1e-12, atol=1e-3):
            bad.append({"symbol": r.symbol, "why": "changed", "rows": [int(r.rows), int(x["rows"])], "sum_close": [float(r.sum_close), float(x["sum_close"])]})
    return {"names_before": int(len(b)), "names_after": int(len(a)), "changed": bad, "pass": not bad}


def ingest_symbols(event_symbols: list[str]) -> list[str]:
    """Every name the slice holds now plus the event names — the slice is rewritten whole."""
    held = data.load(SLICE, columns=["symbol"])["symbol"].astype(str).unique().tolist() if (data.PROC / f"{SLICE}.parquet").exists() else []
    return list(dict.fromkeys([*krw.TWELVE, *held, *event_symbols]))


def bars(fetch: bool = False) -> dict:
    L = frozen()
    OUT.mkdir(parents=True, exist_ok=True)
    cov = coverage(L)
    need = missing_months(cov)
    report = {"events": int(len(cov)), "complete_before": int((cov["share"] >= 0.95).sum()), "missing_before": need}
    if fetch and need:
        fp = fingerprint()
        fp.to_csv(OUT / "fingerprint_before.csv", index=False)
        counts = {}
        for sym, months in need.items():
            counts[sym] = archive.fetch_monthly("klines", sym, sub="5m", months=months)
        report["fetch"] = counts
        report["ingest"] = {k: str(v) for k, v in data.ingest_klines(ingest_symbols(sorted(need))).items()}
        chk = fingerprint_check(fp)
        (OUT / "fingerprint_check.json").write_text(json.dumps(chk, indent=1, default=str))
        report["fingerprint"] = {"pass": chk["pass"], "changed": chk["changed"][:10], "names_before": chk["names_before"], "names_after": chk["names_after"]}
        if not chk["pass"]:
            print(json.dumps(report, indent=1, default=str))
            raise SystemExit(2)
        cov = coverage(L)
        report["complete_after"] = int((cov["share"] >= 0.95).sum())
        report["missing_after"] = missing_months(cov)
    cov.drop(columns=["months"]).to_csv(OUT / "bars.csv", index=False)
    print(json.dumps(report, indent=1, default=str))
    return report


# ---- the audit (volumes, not prices) -----------------------------------------------------------------------------------------
def _hourly_binance(symbols: list[str], cols: tuple[str, ...]) -> pd.DataFrame:
    """The archive slice's 5m bars of `symbols` as hourly rows keyed by the hour's END (ts_known): quote_volume summed, close the last."""
    if not (data.PROC / f"{SLICE}.parquet").exists():
        return pd.DataFrame(columns=["symbol", "ts_known", *cols])
    d = data.load(SLICE, columns=["symbol", "open_time", *cols], symbols=symbols)
    d["open_time"] = _utc(d["open_time"])
    d["ts_known"] = d["open_time"].dt.floor("h") + HOUR
    agg = {c: ("sum" if c == "quote_volume" else "last") for c in cols}
    return d.sort_values("open_time").groupby(["symbol", "ts_known"], observed=True).agg(agg).reset_index()


def fx_krw_per_usdt(venue: str) -> pd.Series:
    """KRW per USDT by the hour's END: KRW-USDT's close where the venue lists it, else KRW-BTC's close over BTCUSDT's 5m close ending at the
    same stamp (the FX and the market-wide premium together — the audit's crowd-size row needs a scale, not a premium)."""
    d = pd.read_parquet(krw.parquet_path(venue), columns=["market", "ts_known", "close"])
    d["ts_known"] = _utc(d["ts_known"])
    usdt = d[d["market"] == CONTROL].set_index("ts_known")["close"].sort_index()
    btc = d[d["market"] == f"KRW-{cb.base(BTC)}"].set_index("ts_known")["close"].sort_index()
    bn = _hourly_binance([BTC], ("close",))
    bn = bn[bn["symbol"].astype(str) == BTC].set_index("ts_known")["close"]
    via_btc = (btc / bn.reindex(btc.index)).dropna()
    fx = via_btc.copy()
    fx.loc[usdt.index.intersection(fx.index)] = usdt.loc[usdt.index.intersection(fx.index)]
    fx = pd.concat([fx, usdt[~usdt.index.isin(fx.index)]]).sort_index()
    return fx[~fx.index.duplicated(keep="last")]


def crowd_size(L: pd.DataFrame) -> pd.DataFrame:
    """Per event: the venue's KRW volume in USDT over the first 24 bars from t0 and over days 2 … 7, Binance's quote volume on the perpetual
    over the same hours, and the shares. Volumes only."""
    out = []
    bn = _hourly_binance(sorted(set(L["symbol"])), ("quote_volume",))
    bn["symbol"] = bn["symbol"].astype(str)
    for venue, g in L.groupby("venue"):
        kr = pd.read_parquet(krw.parquet_path(venue), columns=["market", "ts_known", "volume_krw"])
        kr["ts_known"] = _utc(kr["ts_known"])
        fx = fx_krw_per_usdt(venue)
        for r in g.itertuples(index=False):
            k = kr[kr["market"] == r.market].set_index("ts_known")["volume_krw"].sort_index()
            b = bn[bn["symbol"] == r.symbol].set_index("ts_known")["quote_volume"].sort_index()
            row = {"venue": venue, "market": r.market, "symbol": r.symbol, "t0": r.t0, "t0_hour_kst": int(((r.t0 + KST).hour))}
            for tag, (a, z) in (("d1", (r.t0 + HOUR, r.t0 + HOUR + pd.Timedelta(days=1))), ("d2_7", (r.t0 + HOUR + pd.Timedelta(days=1), r.t0 + HOUR + pd.Timedelta(days=7)))):
                kk = k[(k.index >= a) & (k.index < z)]
                f = fx.reindex(kk.index).ffill().bfill()
                v_usdt = float((kk / f).sum()) if len(kk) and f.notna().any() else np.nan
                bb = b[(b.index >= a) & (b.index < z)]
                v_bn = float(bb.sum()) if len(bb) else np.nan
                row[f"venue_usdt_{tag}"] = v_usdt
                row[f"binance_quote_{tag}"] = v_bn
                row[f"share_{tag}"] = v_usdt / v_bn if (v_bn and v_bn > 0 and np.isfinite(v_usdt)) else np.nan
            out.append(row)
    return pd.DataFrame(out)


def audit(today: pd.Timestamp | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    L = frozen()
    E = pd.read_csv(OUT / "events.csv") if (OUT / "events.csv").exists() else None
    cov = coverage(L)
    cs = crowd_size(L)
    OUT.mkdir(parents=True, exist_ok=True)
    cs.to_csv(OUT / "crowd_size.csv", index=False)
    by_fv = L.groupby(["fold", "venue"]).size().unstack(fill_value=0)
    by_fk = L.groupby(["fold", "first_korean"]).size().unstack(fill_value=0)
    q = L["perp_age_days"].quantile([0.1, 0.5, 0.9]).round(0).to_dict()
    hod = ((pd.DatetimeIndex(L["t0"]) + KST).hour).value_counts().sort_index()
    med = cs[["share_d1", "share_d2_7", "venue_usdt_d1", "binance_quote_d1"]].median(numeric_only=True).to_dict()
    med_v = cs.groupby("venue")[["share_d1", "share_d2_7"]].median().to_dict("index")
    J = {"generated": f"{today:%Y-%m-%d %H:%M} UTC", "events": int(len(L)), "by_fold_venue": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fv.iterrows()},
         "by_fold_first_korean": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fk.iterrows()},
         "members_at_t0": int(L["member_at_t0"].sum()), "perp_age_days_q10_50_90": q, "perp_first_source": L["perp_first_source"].value_counts().to_dict(),
         "t0_hour_kst": {int(k): int(v) for k, v in hod.items()}, "bars_complete": int((cov["share"] >= 0.95).sum()), "bars_median_share": float(cov["share"].median()),
         "crowd_share_median": med, "crowd_share_by_venue": med_v,
         "candidates": None if E is None else {"n": int(len(E)), "why": E["why"].value_counts().to_dict(), "F5_listed_not_frozen": int(((E["fold"] == "F5") & E["why"].str.startswith("outside")).sum())},
         "known_at": "the bar that starts at t0 is final at t0 + 1 h; no announcement board read (Bithumb's API serves its latest five notices, Upbit's board refuses a script)"}
    (OUT / "audit.json").write_text(json.dumps(J, indent=1, default=str))
    md = [f"# krlist — the Korean listing of an existing perpetual as a per-name event (decision BM1)", f"generated {J['generated']} · the frozen lists {', '.join(str(p) for p in LISTS.values())}", "",
          f"**{len(L)} eligible events** (the perpetual ≥ {PERP_AGE.days} d old at t0, t0 in F1 … F4); members at t0 {J['members_at_t0']}; the perpetual's age at t0 p10 / p50 / p90 "
          f"{q.get(0.1)} / {q.get(0.5)} / {q.get(0.9)} days; the first bar's source {J['perp_first_source']}.", "",
          "## By fold × venue", by_fv.to_string(), "", "## By fold × first_korean (no earlier bar on the other venue)", by_fk.to_string(), "",
          "## The first bar's hour of day (KST)", hod.to_string(), "",
          f"## Bars in the window (t0 − 2 d → t0 + 8 d, {EXPECTED_BARS} expected)", f"complete (≥ 95 %) {J['bars_complete']} of {len(L)}; median share {J['bars_median_share']:.3f}", "",
          "## The arriving crowd (volumes, not prices)",
          f"the venue's volume in USDT over the first 24 bars against Binance's quote volume on the perpetual: median share {med.get('share_d1', float('nan')):.3f} "
          f"(days 2 … 7: {med.get('share_d2_7', float('nan')):.3f}); by venue {json.dumps(med_v, default=str)}; the venue's median first-day volume "
          f"{med.get('venue_usdt_d1', float('nan')):,.0f} USDT against Binance's {med.get('binance_quote_d1', float('nan')):,.0f}", "",
          "## Candidates not eligible", "" if E is None else E[E["why"] != "eligible"]["why"].value_counts().to_string(), "",
          f"## Known-at", J["known_at"]]
    (OUT / "audit.md").write_text("\n".join(md))
    return "\n".join(md)


def main(action: str, fetch: bool = False) -> None:
    if action == "events":
        events()
    elif action == "bars":
        bars(fetch=fetch)
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"krlist: unknown action {action}")
