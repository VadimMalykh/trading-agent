"""P8 (decision AT2, 2026-10-19) — the Coinbase spot premium per name as a data source: `ft2 coinbase products|fetch|ingest|audit`.

source     Coinbase Exchange's public, keyless REST API (`api.exchange.coinbase.com`): `/products` (the listed products and their
           status) and `/products/<id>/candles?granularity=<s>&start=&end=` — at most 300 candles a call, each
           [time, low, high, open, close, volume] with `time` the bucket's START in seconds UTC, newest first; the bucket in progress
           is served too (its close moves) and is DROPPED on ingest: a bar that starts at H is final at H + 1 h.
products   each of the twelve's `<BASE>-USD` (PEPE-USD against Binance's 1000PEPEUSDT at 1 : 1000) and `USDT-USD`, the control: Binance's
           perpetual is quoted in USDT and Coinbase's spot in USD, so the raw gap carries the USDT rate; the adjusted premium divides it out.
raw        data/raw/external/coinbase/<PRODUCT>/<yyyy-mm>.json (hourly, one file a month; a month already on disk is not fetched again
           unless it is the current one), data/raw/external/coinbase/<PRODUCT>/daily.json (the daily bars from 2015: the first bar),
           data/raw/external/coinbase/products_<YYYYMMDD>.json.
parquet    data/coinbase_1h.parquet: (product, symbol, ts, ts_known, open, high, low, close, volume) — `ts` the bar's start, `ts_known`
           = ts + 1 h the only stamp a feature may read the bar at.
audit      output/coinbase_audit.md (+ a DATA.md row): per product the first bar, the hourly extent, completeness, gaps, F1–F5 cover;
           the premium at each hour's end = Coinbase close ÷ Binance 5m close at the same stamp − 1, bps, raw and USDT-adjusted;
           its level, spread, persistence, hour-of-day shape and cross-name correlation; the serving lag measured live. Nothing priced.
universe   `--universe twelve` (the default, everything above) or `--universe members` (decision AX1 (i), 2026-10-19): the screener's
           members (`ft2/screen_members.csv`, F1+F2; `screen_members_f34.csv`, F3+F4) whose base has a `<BASE>-USD` product — the
           1000× / 1M× contracts (1000SHIBUSDT, 1MBABYDOGEUSDT …) divided by their multiple; a SEPARATE parquet
           `data/coinbase_1h_members.parquet` (the twelve's file, read by R60 / R61, is never rewritten), the raw files shared by
           product id; Binance's closes from the archive klines (`candles_5m_archive`, the collector's bars where both exist);
           `output/coinbase_members_audit.md` / `.json` / `coinbase_members_premium.parquet` with, beside AT2's tables, each name's
           cover of its OWN member hours (the blocks it is a member of), a per-block breadth table (how many members would carry the
           premium in R62's frame) and the VOLUME SHARE per name described (AX2: Coinbase's hourly USD volume over Binance's USDT
           volume in the same hour, its level, its month-deviation's sd and correlation with the premium). Nothing registered.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

import re

from . import data, folds

API = "https://api.exchange.coinbase.com"
RAW = data.RAW / "external" / "coinbase"
PARQUET = data.PROC / "coinbase_1h.parquet"
OUT = Path("output/coinbase_audit.md")
UA = {"User-Agent": "fluxtrader2-research/1.0", "Accept": "application/json"}
PAUSE = 0.15                 # the public limit is 10 requests a second
MAX_BARS = 300
HOUR = pd.Timedelta("1h")
START = "2023-04-01"         # a month before F1
DAILY_START = "2015-01-01"
AUDIT_START = "2023-05-01"   # F1's first day: completeness is counted from here
BASES = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "XRPUSDT": "XRP", "ADAUSDT": "ADA", "AVAXUSDT": "AVAX", "LINKUSDT": "LINK",
         "DOGEUSDT": "DOGE", "ZECUSDT": "ZEC", "1000PEPEUSDT": "PEPE", "WLDUSDT": "WLD", "HYPEUSDT": "HYPE"}
MULT = {"1000PEPEUSDT": 1000.0}          # Binance's contract is 1,000 tokens: its price is 1,000 × Coinbase's
CONTROL = "USDT-USD"
PRODUCTS = {f"{b}-USD": sym for sym, b in BASES.items()} | {CONTROL: None}
BIG = 10.0                   # bps: the share of hours beyond this
MEMBERS_PARQUET = data.PROC / "coinbase_1h_members.parquet"
MEMBERS_OUT = Path("output/coinbase_members_audit.md")
COVER_OK = 0.90              # a member "carries" the premium in a block when this share of its hours has a bar


def base(sym: str) -> str:
    """Binance's contract → Coinbase's base: the quote stripped, the 1000× / 1M× prefix stripped."""
    b = sym[:-4] if sym.endswith("USDT") else sym
    return re.sub(r"^(1000+|1M)(?=[A-Z])", "", b)


def mult_of(sym: str) -> float:
    """Binance's contract multiple: 1000PEPEUSDT is 1,000 tokens, 1MBABYDOGEUSDT 1,000,000; else 1."""
    m = re.match(r"^(1000+|1M)(?=[A-Z])", sym)
    if not m:
        return 1.0
    return 1e6 if m.group(1) == "1M" else float(m.group(1))


def member_symbols() -> pd.DataFrame:
    """Every (block, symbol) row of the two member files, with the file's fold set and the block's end (the next block start, else + 30 d)."""
    from .universe import F34_MEMBERS_CSV, MEMBERS_CSV
    parts = []
    for f, folds_ in ((MEMBERS_CSV, "F1+F2"), (F34_MEMBERS_CSV, "F3+F4")):
        if not Path(f).exists():
            continue
        m = pd.read_csv(f, usecols=["block", "symbol"])
        m["block"] = pd.to_datetime(m["block"], utc=True)
        starts = sorted(m["block"].unique())
        nxt = {a: b for a, b in zip(starts, starts[1:])}
        m["block_end"] = m["block"].map(lambda a: nxt.get(a, a + pd.Timedelta(days=30)))
        m["folds"] = folds_
        parts.append(m)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["block", "symbol", "block_end", "folds"])


def member_products() -> dict[str, str | None]:
    """`<BASE>-USD` → the member's Binance symbol (the first symbol per base), plus the control."""
    out: dict[str, str | None] = {}
    for sym in sorted(set(member_symbols()["symbol"])):
        out.setdefault(f"{base(sym)}-USD", sym)
    return out | {CONTROL: None}


def universe(name: str = "twelve") -> dict:
    """The products, multiples, files and candle slices of a universe; read at call time so a test may move the twelve's paths."""
    if name == "twelve":
        return {"name": name, "products": PRODUCTS, "mult": MULT, "parquet": PARQUET, "out": OUT, "slices": ("candles_5m",), "tag": ""}
    if name == "members":
        prods = member_products()
        return {"name": name, "products": prods, "mult": {sym: mult_of(sym) for sym in prods.values() if sym}, "parquet": MEMBERS_PARQUET,
                "out": MEMBERS_OUT, "slices": ("candles_5m_archive", "candles_5m"), "tag": "members_"}
    raise ValueError(f"coinbase: unknown universe {name}")


def _get(u: str, timeout: int = 60, retries: int = 6):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:                      # noqa: PERF203
            if e.code == 404:
                return None
            last = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(PAUSE * 4 * 2 ** i)
    raise RuntimeError(f"coinbase: {u} failed after {retries} tries: {last}")


# ---- products --------------------------------------------------------------------------------------------------------------
def products(today: pd.Timestamp | None = None, U: dict | None = None) -> pd.DataFrame:
    """The universe's products as Coinbase lists them today (status, trading_disabled), with the ones it does not list marked."""
    U = U or universe()
    today = today or pd.Timestamp.now("UTC")
    RAW.mkdir(parents=True, exist_ok=True)
    lst = _get(f"{API}/products") or []
    by = {p["id"]: p for p in lst}
    rows = [{"product": pid, "symbol": sym, "listed": pid in by, "status": by.get(pid, {}).get("status"), "trading_disabled": by.get(pid, {}).get("trading_disabled"),
             "quote": by.get(pid, {}).get("quote_currency")} for pid, sym in U["products"].items()]
    (RAW / f"products_{U['tag']}{today:%Y%m%d}.json").write_text(json.dumps({"fetched": f"{today:%Y-%m-%d %H:%M} UTC", "rows": rows, "n_listed_usd": sum(p.get("quote_currency") == "USD" for p in lst)}))
    return pd.DataFrame(rows)


def products_file(U: dict | None = None) -> pd.DataFrame | None:
    """The latest saved product listing of the universe, or None."""
    U = U or universe()
    pf = sorted(RAW.glob(f"products_{U['tag']}????????.json"))
    return pd.DataFrame(json.loads(pf[-1].read_text())["rows"]) if pf else None


# ---- candles ----------------------------------------------------------------------------------------------------------------
def _candles(pid: str, a: pd.Timestamp, b: pd.Timestamp, granularity: int) -> list[list[float]]:
    """All candles of `pid` with start in [a, b), `granularity` seconds, in calls of at most MAX_BARS; oldest first; deduplicated."""
    out, s, step = {}, a, pd.Timedelta(seconds=granularity * MAX_BARS)
    while s < b:
        e = min(s + step, b)
        res = _get(f"{API}/products/{pid}/candles?granularity={granularity}&start={s.isoformat()}&end={(e - pd.Timedelta(seconds=granularity)).isoformat()}")
        for row in res or []:
            out[int(row[0])] = [float(x) for x in row]
        s = e
        time.sleep(PAUSE)
    return [out[k] for k in sorted(out)]


def fetch(start: str = START, end: str | None = None, today: pd.Timestamp | None = None, pids=None, daily: bool = True, U: dict | None = None,
          listed_only: bool = False) -> dict:
    """Hourly candles month by month (a month's file on disk is kept unless it is the current month) and the daily bars from 2015.
    `listed_only`: skip the products the saved listing (`products`) does not list — an unlisted product answers 404 on every call."""
    U = U or universe()
    today = today or pd.Timestamp.now("UTC")
    a = pd.Timestamp(start, tz="UTC").floor("D")
    b = pd.Timestamp(end, tz="UTC") if end else today.floor("h")
    report = {}
    pids = list(pids or U["products"])
    if listed_only:
        pf = products_file(U)
        if pf is None:
            raise RuntimeError("coinbase fetch --listed-only: run `products` first")
        listed = set(pf.loc[pf["listed"] == True, "product"])  # noqa: E712
        report["skipped_unlisted"] = sorted(p for p in pids if p not in listed)
        pids = [p for p in pids if p in listed]
    for pid in pids:
        d = RAW / pid
        d.mkdir(parents=True, exist_ok=True)
        if daily:
            rows = _candles(pid, pd.Timestamp(DAILY_START, tz="UTC"), today.floor("D"), 86_400)
            (d / "daily.json").write_text(json.dumps({"product": pid, "fetched": f"{today:%Y-%m-%d %H:%M} UTC", "rows": rows}))
        n_new, n_rows = 0, 0
        for m0 in pd.date_range(a.to_period("M").start_time.tz_localize("UTC"), b, freq="MS"):
            m1 = min((m0 + pd.offsets.MonthBegin(1)), b)
            f = d / f"{m0:%Y-%m}.json"
            if f.exists() and m1 < b:
                continue
            rows = _candles(pid, max(m0, a), m1, 3600)
            f.write_text(json.dumps({"product": pid, "month": f"{m0:%Y-%m}", "fetched": f"{today:%Y-%m-%d %H:%M} UTC", "start": str(max(m0, a)), "end": str(m1), "rows": rows}))
            n_new += 1
            n_rows += len(rows)
        report[pid] = {"months_fetched": n_new, "rows": n_rows}
        print(f"coinbase fetch {pid}: {n_new} month files, {n_rows} hourly bars", flush=True)
    return report


def ingest(today: pd.Timestamp | None = None, pids=None, U: dict | None = None) -> dict:
    """The month files → the universe's parquet; the bar in progress at the fetch (its start + 1 h > fetched) is dropped; duplicates keep the last."""
    U = U or universe()
    parts, report = [], {}
    for pid in (pids or list(U["products"])):
        d = RAW / pid
        files = sorted(d.glob("????-??.json")) if d.exists() else []
        rows, dropped = [], 0
        for f in files:
            j = json.loads(f.read_text())
            fetched = pd.Timestamp(j["fetched"].replace(" UTC", ""), tz="UTC")
            for r in j["rows"]:
                ts = pd.Timestamp(int(r[0]), unit="s", tz="UTC")
                if ts + HOUR > fetched:
                    dropped += 1
                    continue
                rows.append((ts, r[3], r[2], r[1], r[4], r[5]))
        if not rows:
            report[pid] = {"rows": 0, "files": len(files)}
            continue
        g = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts", keep="last").sort_values("ts")
        g.insert(0, "symbol", U["products"][pid])
        g.insert(0, "product", pid)
        g.insert(3, "ts_known", g["ts"] + HOUR)
        parts.append(g)
        report[pid] = {"rows": int(len(g)), "files": len(files), "in_progress_dropped": dropped, "first": str(g["ts"].min()), "last": str(g["ts"].max())}
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["product", "symbol", "ts", "ts_known", "open", "high", "low", "close", "volume"])
    U["parquet"].parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(U["parquet"], index=False)
    print(f"coinbase ingest: {len(out)} rows → {U['parquet']}", flush=True)
    return report


def load(path: Path | str = PARQUET) -> pd.DataFrame:
    d = pd.read_parquet(path)
    for c in ("ts", "ts_known"):
        d[c] = pd.DatetimeIndex(d[c]).tz_convert("UTC") if pd.DatetimeIndex(d[c]).tz is not None else pd.DatetimeIndex(d[c]).tz_localize("UTC")
    return d


def first_daily_bar(pid: str) -> str | None:
    f = RAW / pid / "daily.json"
    if not f.exists():
        return None
    rows = json.loads(f.read_text())["rows"]
    return str(pd.Timestamp(int(min(r[0] for r in rows)), unit="s", tz="UTC").date()) if rows else None


# ---- the premium -----------------------------------------------------------------------------------------------------------
def _binance_5m(symbols: list[str], slices: tuple[str, ...] = ("candles_5m",), volume: bool = False) -> pd.DataFrame:
    """Binance's 5m bars of `symbols` from the slices in order (a later slice's bar replaces an earlier one's at the same key), with
    the bar's END stamp."""
    cols = ["symbol", "open_time", "close"] + (["volume"] if volume else [])
    parts = []
    for sl in slices:
        if (data.PROC / f"{sl}.parquet").exists() or (data.PROC / sl).is_dir():
            try:
                parts.append(data.load(sl, columns=cols, symbols=symbols))
            except ValueError:                      # a slice with none of the symbols
                pass
    c = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)
    c["symbol"] = c["symbol"].astype(str)
    ot = pd.DatetimeIndex(c["open_time"])
    c["end"] = (ot.tz_localize("UTC") if ot.tz is None else ot.tz_convert("UTC")) + pd.Timedelta("5min")
    return c.drop_duplicates(["symbol", "end"], keep="last")


def binance_close_at(symbols: list[str], stamps: pd.DatetimeIndex, slices: tuple[str, ...] = ("candles_5m",)) -> pd.DataFrame:
    """Binance's 5m close whose bar ENDS at each stamp (open_time = stamp − 5 min), wide: stamp × symbol; NaN where no bar."""
    c = _binance_5m(symbols, slices)
    c = c[c["end"].isin(stamps)]
    return c.pivot_table(index="end", columns="symbol", values="close", aggfunc="last").reindex(stamps)


def binance_dvol_hour(symbols: list[str], stamps: pd.DatetimeIndex, slices: tuple[str, ...] = ("candles_5m",)) -> pd.DataFrame:
    """Binance's USDT volume (Σ volume × close over the twelve 5m bars) of the hour ENDING at each stamp, wide; NaN where no bar."""
    c = _binance_5m(symbols, slices, volume=True)
    c["hour_end"] = c["end"].dt.ceil("h")
    c["dv"] = c["volume"] * c["close"]
    return c.pivot_table(index="hour_end", columns="symbol", values="dv", aggfunc="sum").reindex(stamps)


def premium(cb: pd.DataFrame, bn: pd.DataFrame, mult: dict[str, float] | None = None) -> pd.DataFrame:
    """Per (ts_known, symbol): the raw premium Coinbase ÷ Binance − 1 in bps (Binance's price ÷ the contract's multiple) and the
    USDT-adjusted one (÷ the USDT-USD close at the same stamp, where it exists)."""
    mult = MULT if mult is None else mult
    usdt = cb[cb["product"] == CONTROL].set_index("ts_known")["close"]
    rows = []
    for sym, g in cb[cb["symbol"].notna()].groupby("symbol"):
        g = g.set_index("ts_known").sort_index()
        b = bn[sym].reindex(g.index) / mult.get(sym, 1.0) if sym in bn else pd.Series(np.nan, index=g.index)
        raw = (g["close"] / b - 1.0) * 1e4
        u = usdt.reindex(g.index)
        adj = (g["close"] / (b * u) - 1.0) * 1e4
        rows.append(pd.DataFrame({"symbol": sym, "ts_known": g.index, "cb_close": g["close"].to_numpy(), "bn_close": b.to_numpy(), "usdt_usd": u.to_numpy(),
                                  "prem_raw_bps": raw.to_numpy(), "prem_adj_bps": adj.to_numpy()}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["symbol", "ts_known", "cb_close", "bn_close", "usdt_usd", "prem_raw_bps", "prem_adj_bps"])


def _acf(x: pd.Series, lag: int) -> float:
    x = x.dropna()
    return float(x.autocorr(lag)) if len(x) > lag + 10 else np.nan


def live_lag(pid: str = "BTC-USD", now: pd.Timestamp | None = None) -> dict:
    """The serving lag: the last COMPLETE hourly bar served now, and the seconds since its end; whether the bucket in progress is served."""
    now = now or pd.Timestamp.now("UTC")
    res = _get(f"{API}/products/{pid}/candles?granularity=3600&start={(now - 4 * HOUR).isoformat()}&end={now.isoformat()}") or []
    starts = sorted(pd.Timestamp(int(r[0]), unit="s", tz="UTC") for r in res)
    complete = [s for s in starts if s + HOUR <= now]
    return {"now": str(now), "bars_served": len(starts), "in_progress_served": bool(starts and starts[-1] + HOUR > now),
            "last_complete_end": str(complete[-1] + HOUR) if complete else None,
            "seconds_since_last_complete_end": float((now - (complete[-1] + HOUR)).total_seconds()) if complete else np.nan}


def member_cover(cb: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per symbol: its member hours over the blocks it is a member of and the share with a Coinbase bar; per block: the members, those
    with a product and a bar, those covering ≥ COVER_OK of the block — the breadth R62's frame would have)."""
    M = member_symbols()
    have = {sym: pd.DatetimeIndex(g["ts"]) for sym, g in cb[cb["symbol"].notna()].groupby("symbol")}
    per, blocks = {}, []
    for (b0, b1, fl), g in M.groupby(["block", "block_end", "folds"]):
        hrs = pd.date_range(b0.ceil("h"), b1, freq="h", inclusive="left")
        n_prod, n_ok = 0, 0
        for sym in g["symbol"]:
            r = per.setdefault(sym, {"symbol": sym, "member_blocks": 0, "member_hours": 0, "hours_with_bar": 0})
            r["member_blocks"] += 1
            r["member_hours"] += len(hrs)
            if sym in have:
                k = int(hrs.isin(have[sym]).sum())
                r["hours_with_bar"] += k
                n_prod += k > 0                      # a bar inside THIS block
                n_ok += k >= COVER_OK * len(hrs)
        blocks.append({"block": str(b0.date()), "folds": fl, "members": int(len(g)), "with_bars": n_prod, f"cover_ge_{COVER_OK:g}": n_ok})
    P = pd.DataFrame(per.values()) if per else pd.DataFrame(columns=["symbol", "member_blocks", "member_hours", "hours_with_bar"])
    if len(P):
        P["cover_member"] = P["hours_with_bar"] / P["member_hours"]
    return P, pd.DataFrame(blocks)


def volume_share(cb: pd.DataFrame, P: pd.DataFrame, slices: tuple[str, ...], a0: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """AX2, described: per name Coinbase's hourly USD volume over Binance's USDT volume of the same hour — the median share, p10 / p90,
    the sd of the log share's deviation from its trailing 30-day mean, and that deviation's correlation with the adjusted premium."""
    cbv = cb[cb["symbol"].notna()].assign(usd=lambda d: d["volume"] * d["close"]).pivot_table(index="ts_known", columns="symbol", values="usd", aggfunc="last")
    cbv = cbv[(cbv.index > a0) & (cbv.index <= end)]
    if cbv.empty:
        return pd.DataFrame(columns=["symbol", "hours", "share_median", "share_p10", "share_p90", "dev_sd", "corr_dev_prem"])
    bnv = binance_dvol_hour(list(cbv.columns), cbv.index, slices)
    prem = P.pivot_table(index="ts_known", columns="symbol", values="prem_adj_bps").reindex(cbv.index)
    rows = []
    for sym in cbv.columns:
        share = (cbv[sym] / bnv[sym]).replace([np.inf, -np.inf], np.nan) if sym in bnv else pd.Series(np.nan, index=cbv.index)
        share = share.where(share > 0)
        ls = np.log(share)
        dev = ls - ls.rolling(720, min_periods=360).mean()
        ok = dev.notna() & (prem[sym].notna() if sym in prem else False)
        rows.append({"symbol": sym, "hours": int(share.notna().sum()), "share_median": share.median(), "share_p10": share.quantile(0.1), "share_p90": share.quantile(0.9),
                     "dev_sd": dev.std(), "corr_dev_prem": float(dev[ok].corr(prem[sym][ok])) if ok.sum() > 100 else np.nan})
    return pd.DataFrame(rows)


def audit(today: pd.Timestamp | None = None, lag: dict | None = None, path: Path | str | None = None, products_df: pd.DataFrame | None = None,
          U: dict | None = None) -> str:
    U = U or universe()
    path = U["parquet"] if path is None else path
    out_md = U["out"]
    today = today or pd.Timestamp.now("UTC")
    cb = load(path)
    end = min(cb["ts_known"].max(), folds.bounds("F5")[1]) if len(cb) else today
    a0 = pd.Timestamp(AUDIT_START, tz="UTC")
    expected = pd.date_range(a0, end, freq="h", inclusive="left")
    if products_df is None:
        products_df = products_file(U)
        if products_df is None:
            products_df = pd.DataFrame(columns=["product", "symbol", "listed", "status"])
    pinfo = products_df.set_index("product") if len(products_df) else pd.DataFrame()
    lag = lag if lag is not None else live_lag(now=today)
    rows = []
    for pid, sym in U["products"].items():
        g = cb[cb["product"] == pid]
        r = {"product": pid, "symbol": sym or "(control)", "listed": bool(pinfo.loc[pid, "listed"]) if pid in pinfo.index else None,
             "status": pinfo.loc[pid, "status"] if pid in pinfo.index else None, "first_daily_bar": first_daily_bar(pid),
             "hourly_first": str(g["ts"].min()) if len(g) else None, "hourly_last": str(g["ts"].max()) if len(g) else None, "hours": int(len(g))}
        if len(g):
            have = pd.DatetimeIndex(g["ts"])
            inside = have[(have >= a0) & (have < end)]
            r["completeness"] = float(len(inside) / max(len(expected), 1))
            d = np.diff(have.sort_values().asi8) / 3.6e12
            r["gaps_over_1h"] = int((d > 1.0001).sum())
            r["largest_gap_h"] = float(d.max()) if len(d) else 0.0
            for f in ("F1", "F2", "F3", "F4", "F5"):
                fa, fb = folds.bounds(f)
                sh = pd.date_range(fa.ceil("h"), min(fb, end), freq="h", inclusive="left")
                r[f"cover_{f}"] = float(sh.isin(have).mean()) if len(sh) else np.nan
        rows.append(r)
    cov = pd.DataFrame(rows)
    syms = [s for s in U["products"].values() if s and cb["symbol"].eq(s).any()]
    stamps = pd.DatetimeIndex(sorted(cb.loc[cb["symbol"].isin(syms), "ts_known"].unique()))
    bn = binance_close_at(syms, stamps, U["slices"]) if syms else pd.DataFrame()
    P = premium(cb, bn, U["mult"])
    P = P[(P["ts_known"] > a0) & (P["ts_known"] <= end)]            # the bars that START inside [a0, end)
    members = U["name"] == "members"
    mcov, blocks = member_cover(cb) if members else (pd.DataFrame(), pd.DataFrame())
    if members and len(mcov):
        cov = cov.merge(mcov, on="symbol", how="left")
    vshare = volume_share(cb, P, U["slices"], a0, end) if members else pd.DataFrame()
    stat = []
    for sym, g in P.groupby("symbol"):
        g = g.set_index("ts_known").sort_index()
        for col, tag in (("prem_raw_bps", "raw"), ("prem_adj_bps", "adj")):
            x = g[col]
            stat.append({"symbol": sym, "premium": tag, "hours": int(x.notna().sum()), "mean": x.mean(), "median": x.median(), "sd": x.std(), "p10": x.quantile(0.1), "p90": x.quantile(0.9),
                         "acf_1h": _acf(x, 1), "acf_24h": _acf(x, 24), f"share_abs_gt_{BIG:g}": float((x.abs() > BIG).mean()) if x.notna().any() else np.nan,
                         "mean_us_hours_14_21": float(x[(x.index.hour >= 14) & (x.index.hour < 21)].mean()), "mean_asia_hours_0_8": float(x[x.index.hour < 8].mean())})
    stat = pd.DataFrame(stat)
    wide = P.pivot_table(index="ts_known", columns="symbol", values="prem_adj_bps")
    C = wide.corr()
    off = C.where(~np.eye(len(C), dtype=bool)).stack()
    first_pc = np.nan
    if wide.shape[1] >= 3:
        z = wide.dropna()
        if len(z) > 100:
            ev = np.linalg.eigvalsh(np.corrcoef(z.to_numpy().T))
            first_pc = float(ev[-1] / ev.sum())
    hod = wide.groupby(wide.index.hour).mean().mean(axis=1) if len(wide) else pd.Series(dtype=float)
    usdt = cb[cb["product"] == CONTROL].set_index("ts_known")["close"]
    usdt = usdt[(usdt.index > a0) & (usdt.index <= end)]
    who = "decision AX1 (i), the screener's members" if members else "decision AT2"
    L = [f"# Coinbase spot premium — source audit ({who}; `ft2 coinbase audit{' --universe members' if members else ''}`)\n",
         f"generated {today:%Y-%m-%d %H:%M} UTC · {path} · the premium counted over {a0.date()} → {end.date()} at each hour's END (the bar's start + 1 h)\n",
         "\nWords: the *raw* premium is Coinbase's hourly close over Binance's 5m close ending at the same stamp, minus one, in bps (Binance's 1000PEPE price divided by 1,000); the *adjusted* premium "
         "divides Binance's USDT price by the USDT-USD close of the same hour on Coinbase. Nothing is priced here; no fold is read.\n",
         "\n## Products, extent, completeness, cover (hours)\n", cov.round(4).to_markdown(index=False), "\n",
         f"\n## The serving lag, measured live\n- {json.dumps(lag)}\n- Rule: the bar that starts at H is final at H + 1 h (`ts_known`); the bucket in progress is served and is never read.\n",
         *(["\n## The members' cover of their own hours, per block — the breadth R62's frame would have\n", blocks.to_markdown(index=False), "\n",
            f"\nA member counts in `cover_ge_{COVER_OK:g}` when ≥ {COVER_OK:.0%} of the hours of the block it is a member of have a Coinbase bar. "
            f"Per name `cover_member` (in the table above) is the share over all its member blocks.\n",
            "\n## The volume share per name (AX2, described): Coinbase's hourly USD volume over Binance's USDT volume in the same hour\n",
            vshare.round(4).to_markdown(index=False) if len(vshare) else "(no volume)", "\n",
            "`dev_sd` = the sd of the log share's deviation from its trailing 30-day mean; `corr_dev_prem` = that deviation's correlation with the adjusted premium at the same hour.\n"]
           if members else []),
         "\n## The premium per name\n", stat.round(3).to_markdown(index=False) if len(stat) else "(no overlap with Binance's candles)", "\n",
         f"\n## Across names (adjusted premium)\n- mean off-diagonal correlation {off.mean():.3f} (min {off.min():.3f}, max {off.max():.3f}); the first principal component's share {first_pc:.3f} on the hours every name has\n" if len(off) else "\n## Across names\n- fewer than two names\n",
         "- mean by hour of day (UTC), averaged over names: " + ", ".join(f"{h:02d}h {v:+.1f}" for h, v in hod.items()) + "\n" if len(hod) else "",
         f"\n## USDT-USD on Coinbase\n- {len(usdt)} hours; median {usdt.median():.5f}, p1 {usdt.quantile(0.01):.5f}, p99 {usdt.quantile(0.99):.5f}; the raw premium carries (1 − USDT) ≈ {(1 - usdt.median()) * 1e4:+.1f} bps at the median\n" if len(usdt) else ""]
    listed = cov[cov["listed"] == True]  # noqa: E712
    if members:
        with_bars = cov[cov["hours"] > 0]
        row = ("| **coinbase_1h_members** (Coinbase Exchange spot, hourly, the screener's members; decision AX1 (i), §9 #10) | `ft2 coinbase fetch --universe members --listed-only`, raw `data/raw/external/coinbase/` | "
               + f"{len(listed)} of {len(U['products']) - 1} member bases listed, {len(with_bars)} with hourly bars; per block "
               + "; ".join(f"{b['block']} {b[f'cover_ge_{COVER_OK:g}']} of {b['members']}" for _, b in blocks.iterrows())
               + f" | `{MEMBERS_PARQUET}` (the twelve's file untouched); a bar is read at `ts_known` = its start + 1 h |")
    else:
        row = ("| **coinbase_1h** (Coinbase Exchange spot, hourly; decision AT2, §9 #10) | `ft2 coinbase fetch` from `api.exchange.coinbase.com/products/<id>/candles`, raw `data/raw/external/coinbase/` | "
               + f"{len(listed)} of {len(PRODUCTS)} products listed; " + "; ".join(f"{r['product']} from {r['first_daily_bar']} ({r.get('completeness', np.nan):.1%} of hours {a0.date()} →)" for _, r in cov.iterrows() if r.get("hours", 0))
               + " | `data/coinbase_1h.parquet` (product, symbol, ts, ts_known, open, high, low, close, volume); a bar is read at `ts_known` = its start + 1 h |")
    L += ["\n## DATA.md row\n", "\n" + row + "\n"]
    txt = "".join(x if x.endswith("\n") else x + "\n" for x in L)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(txt)
    stem = out_md.stem.replace("_audit", "")
    (out_md.parent / f"{stem}_audit.json").write_text(json.dumps({"cover": cov.to_dict("records"), "stats": stat.to_dict("records"), "corr_mean": float(off.mean()) if len(off) else None,
                                                                   "first_pc": first_pc, "lag": lag, "hod": {int(k): float(v) for k, v in hod.items()},
                                                                   "blocks": blocks.to_dict("records"), "volume_share": vshare.to_dict("records")}, indent=1, default=str))
    P.to_parquet(out_md.parent / f"{stem}_premium.parquet", index=False)
    return txt


def main(action: str, start: str = START, end: str | None = None, pids=None, universe_name: str = "twelve", listed_only: bool = False) -> None:
    U = universe(universe_name)
    if action == "products":
        print(products(U=U).to_string())
    elif action == "fetch":
        print(json.dumps(fetch(start, end, pids=pids, U=U, listed_only=listed_only), indent=1))
    elif action == "ingest":
        print(json.dumps(ingest(pids=pids, U=U), indent=1))
    elif action == "audit":
        print(audit(U=U))
    else:
        sys.exit(f"coinbase: unknown action {action}")
