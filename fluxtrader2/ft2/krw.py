"""P8 (decision BB1, 2026-10-20) — the Korean premium per name as a data source: `ft2 krw markets|fetch|ingest|audit --venue upbit|bithumb`.

source     Upbit's and Bithumb's public, keyless quotation APIs, the same shape on both (`api.upbit.com/v1`, `api.bithumb.com/v1`):
           `/market/all` (the listed markets) and `/candles/minutes/60?market=KRW-<BASE>&to=<stamp>&count=200` — at most 200 candles a call,
           NEWEST first, every candle strictly before `to`; `candle_date_time_utc` is the bar's START (no zone, UTC), `trade_price` its
           close, `candle_acc_trade_price` its KRW volume, `timestamp` the last tick's ms. An hour without a trade has no candle. The
           bucket in progress is served (its close moves) and is DROPPED on ingest: a bar that starts at H is final at H + 1 h. Upbit's `to`
           takes the `Z` suffix and is UTC; Bithumb's refuses a zone and reads the bare stamp as KST (so it is written +9 h), and its
           `timestamp` on a finished bar is the bar's END, not a tick; Upbit's API refuses TLS from some networks (the laptop), answers from GCP.
markets    KRW-<BASE> for every base of the twelve and of the screener's members (`ft2/screen_members.csv`, `screen_members_f34.csv`; a
           1000× / 1M× contract's base with the multiple divided, as `coinbase.base` / `mult_of`), plus KRW-USDT, the control: Binance's
           perpetual is quoted in USDT and the venue in KRW, so the raw ratio is a KRW/USDT rate times the premium; the ADJUSTED premium
           divides by KRW-USDT's close at the same hour, the BTC-RELATIVE premium divides by BTC's own ratio at the same hour (no control
           needed; the market-wide "kimchi premium" and the FX removed together — the quantity a within-hour rank screen reads).
raw        data/raw/external/<venue>/<MARKET>/<yyyy-mm>.json (hourly, one file a month; a month on disk is kept unless it is the current
           one), data/raw/external/<venue>/markets_<YYYYMMDD>.json (the listing).
parquet    data/krw_1h_<venue>.parquet: (venue, market, symbol, ts, ts_known, open, high, low, close, volume_krw, volume, last_tick) —
           `ts` the bar's start, `ts_known` = ts + 1 h the only stamp a feature may read the bar at, `last_tick` the last trade's stamp.
audit      output/krw_<venue>_audit.md (+ .json, krw_<venue>_premium.parquet, a DATA.md row): per market the first bar, the extent,
           completeness, gaps, F1–F5 cover, the member-hours cover and the per-block breadth (R62's frame); the alignment check (the
           share of bars whose last tick lies inside [ts, ts + 1 h) — the evidence that `candle_date_time_utc` is the start); the premium
           at each hour's END against Binance's 5m close ending at the same stamp — raw ratio, KRW-USDT-adjusted bps, BTC-relative bps —
           its level, within-name sd, persistence, hour-of-day shape, cross-name correlation; the KRW volume share (AX2's form); the
           serving lag measured live. Nothing priced, no fold read, nothing registered.
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

from . import coinbase as cb
from . import data, folds

VENUES = {"upbit": {"api": "https://api.upbit.com/v1", "to_suffix": "Z", "to_offset_h": 0},
          "bithumb": {"api": "https://api.bithumb.com/v1", "to_suffix": "", "to_offset_h": 9}}     # Bithumb reads a bare `to` as KST (UTC+9)
UA = {"User-Agent": "fluxtrader2-research/1.0", "Accept": "application/json"}
PAUSE = 0.12                 # both venues publish ≈ 10 quotation requests a second an IP
MAX_BARS = 200
HOUR = pd.Timedelta("1h")
START = "2023-04-01"         # a month before F1
AUDIT_START = "2023-05-01"   # F1's first day: completeness is counted from here
CONTROL = "KRW-USDT"
BTC = "BTCUSDT"
BIG = 50.0                   # bps: the share of hours beyond this (Coinbase's bar was 10; the Korean premium is wider)
COVER_OK = cb.COVER_OK
TWELVE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "1000PEPEUSDT", "WLDUSDT", "ZECUSDT", "HYPEUSDT"]


def raw_dir(venue: str) -> Path:
    return data.RAW / "external" / venue


def parquet_path(venue: str) -> Path:
    return data.PROC / f"krw_1h_{venue}.parquet"


def out_path(venue: str) -> Path:
    return Path("output") / f"krw_{venue}_audit.md"


def markets_of() -> dict[str, str | None]:
    """KRW-<BASE> → the Binance symbol (the twelve's first, then the first member symbol per base), plus the control."""
    out: dict[str, str | None] = {}
    for sym in [*TWELVE, *sorted(set(cb.member_symbols()["symbol"]))]:
        out.setdefault(f"KRW-{cb.base(sym)}", sym)
    return out | {CONTROL: None}


def universe(venue: str) -> dict:
    if venue not in VENUES:
        raise ValueError(f"krw: unknown venue {venue}")
    mk = markets_of()
    return {"venue": venue, **VENUES[venue], "markets": mk, "mult": {sym: cb.mult_of(sym) for sym in mk.values() if sym}, "raw": raw_dir(venue),
            "parquet": parquet_path(venue), "out": out_path(venue), "slices": ("candles_5m_archive", "candles_5m")}


def _get(u: str, timeout: int = 60, retries: int = 6):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:                      # noqa: PERF203
            if e.code == 404:
                return None
            if e.code == 429:
                time.sleep(2.0 * 2 ** i)
                continue
            last = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(PAUSE * 4 * 2 ** i)
    raise RuntimeError(f"krw: {u} failed after {retries} tries: {last}")


# ---- markets -----------------------------------------------------------------------------------------------------------------
def markets(U: dict, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """The universe's markets as the venue lists them today, the unlisted marked."""
    today = today or pd.Timestamp.now("UTC")
    U["raw"].mkdir(parents=True, exist_ok=True)
    lst = _get(f"{U['api']}/market/all?isDetails=false") or []
    by = {m["market"]: m for m in lst if isinstance(m, dict) and "market" in m}
    rows = [{"market": mk, "symbol": sym, "listed": mk in by, "english_name": by.get(mk, {}).get("english_name")} for mk, sym in U["markets"].items()]
    (U["raw"] / f"markets_{today:%Y%m%d}.json").write_text(json.dumps({"fetched": f"{today:%Y-%m-%d %H:%M} UTC", "rows": rows,
                                                                        "n_krw_markets": sum(k.startswith("KRW-") for k in by)}))
    return pd.DataFrame(rows)


def markets_file(U: dict) -> pd.DataFrame | None:
    pf = sorted(U["raw"].glob("markets_????????.json"))
    return pd.DataFrame(json.loads(pf[-1].read_text())["rows"]) if pf else None


# ---- candles -----------------------------------------------------------------------------------------------------------------
def _stamp(ts: pd.Timestamp, suffix: str, offset_h: int = 0) -> str:
    """`to` in the venue's own convention: Upbit reads `…Z` as UTC; Bithumb refuses a zone and reads the bare stamp as KST, so the UTC
    instant is written shifted by +9 h (found 2026-10-20: the first fetch lost the 9 newest bars of every 200-bar page — 4.5 % of hours)."""
    return f"{ts.tz_convert('UTC') + pd.Timedelta(hours=offset_h):%Y-%m-%dT%H:%M:%S}{suffix}"


def _parse_start(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def _candles(U: dict, market: str, a: pd.Timestamp, b: pd.Timestamp) -> list[dict]:
    """Every hourly candle of `market` with start in [a, b), walking BACKWARDS from `b` in calls of MAX_BARS (the venue serves the
    candles strictly before `to`, newest first); oldest first, deduplicated by start."""
    out: dict[str, dict] = {}
    to = b
    while to > a:
        res = _get(f"{U['api']}/candles/minutes/60?market={market}&to={_stamp(to, U['to_suffix'], U.get('to_offset_h', 0))}&count={MAX_BARS}")
        if not res or not isinstance(res, list):
            break
        starts = [_parse_start(r["candle_date_time_utc"]) for r in res]
        for r, s in zip(res, starts):
            if a <= s < b:
                out[r["candle_date_time_utc"]] = r
        oldest = min(starts)
        if oldest <= a or len(res) < MAX_BARS:
            break
        to = oldest
        time.sleep(PAUSE)
    time.sleep(PAUSE)
    return [out[k] for k in sorted(out)]


def fetch(U: dict, start: str = START, end: str | None = None, today: pd.Timestamp | None = None, mkts=None, listed_only: bool = False) -> dict:
    """Hourly candles month by month (a month's file on disk is kept unless it is the current month). `listed_only`: skip the markets the saved
    listing does not hold (an unlisted market answers an error or nothing on every call)."""
    today = today or pd.Timestamp.now("UTC")
    a = pd.Timestamp(start, tz="UTC").floor("D")
    b = pd.Timestamp(end, tz="UTC") if end else today.floor("h")
    report: dict = {}
    mkts = list(mkts or U["markets"])
    if listed_only:
        mf = markets_file(U)
        if mf is None:
            raise RuntimeError("krw fetch --listed-only: run `markets` first")
        listed = set(mf.loc[mf["listed"] == True, "market"])  # noqa: E712
        report["skipped_unlisted"] = sorted(m for m in mkts if m not in listed)
        mkts = [m for m in mkts if m in listed]
    for mk in mkts:
        d = U["raw"] / mk
        d.mkdir(parents=True, exist_ok=True)
        n_new, n_rows = 0, 0
        for m0 in pd.date_range(a.to_period("M").start_time.tz_localize("UTC"), b, freq="MS"):
            m1 = min(m0 + pd.offsets.MonthBegin(1), b)
            f = d / f"{m0:%Y-%m}.json"
            if f.exists() and m1 < b:
                continue
            rows = _candles(U, mk, max(m0, a), m1)
            f.write_text(json.dumps({"venue": U["venue"], "market": mk, "month": f"{m0:%Y-%m}", "fetched": f"{today:%Y-%m-%d %H:%M} UTC", "start": str(max(m0, a)), "end": str(m1), "rows": rows}))
            n_new += 1
            n_rows += len(rows)
        report[mk] = {"months_fetched": n_new, "rows": n_rows}
        print(f"krw {U['venue']} fetch {mk}: {n_new} month files, {n_rows} hourly bars", flush=True)
    return report


COLS = ["venue", "market", "symbol", "ts", "ts_known", "open", "high", "low", "close", "volume_krw", "volume", "last_tick"]


def ingest(U: dict, mkts=None) -> dict:
    """The month files → the venue's parquet; the bar in progress at the fetch (its start + 1 h > fetched) is dropped; duplicates keep the last."""
    parts, report = [], {}
    for mk in (mkts or list(U["markets"])):
        d = U["raw"] / mk
        files = sorted(d.glob("????-??.json")) if d.exists() else []
        rows, dropped = [], 0
        for f in files:
            j = json.loads(f.read_text())
            fetched = pd.Timestamp(j["fetched"].replace(" UTC", ""), tz="UTC")
            for r in j["rows"]:
                ts = _parse_start(r["candle_date_time_utc"])
                if ts + HOUR > fetched:
                    dropped += 1
                    continue
                rows.append((ts, float(r["opening_price"]), float(r["high_price"]), float(r["low_price"]), float(r["trade_price"]), float(r.get("candle_acc_trade_price", np.nan)),
                             float(r.get("candle_acc_trade_volume", np.nan)), pd.Timestamp(int(r["timestamp"]), unit="ms", tz="UTC") if r.get("timestamp") else pd.NaT))
        if not rows:
            report[mk] = {"rows": 0, "files": len(files)}
            continue
        g = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume_krw", "volume", "last_tick"]).drop_duplicates("ts", keep="last").sort_values("ts")
        g.insert(0, "symbol", U["markets"][mk])
        g.insert(0, "market", mk)
        g.insert(0, "venue", U["venue"])
        g.insert(4, "ts_known", g["ts"] + HOUR)
        parts.append(g)
        report[mk] = {"rows": int(len(g)), "files": len(files), "in_progress_dropped": dropped, "first": str(g["ts"].min()), "last": str(g["ts"].max())}
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
    U["parquet"].parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(U["parquet"], index=False)
    print(f"krw {U['venue']} ingest: {len(out)} rows → {U['parquet']}", flush=True)
    return report


def load(path: Path | str) -> pd.DataFrame:
    d = pd.read_parquet(path)
    for c in ("ts", "ts_known", "last_tick"):
        if c in d:
            idx = pd.DatetimeIndex(d[c])
            d[c] = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return d


# ---- the premium -------------------------------------------------------------------------------------------------------------
def premium(kr: pd.DataFrame, bn: pd.DataFrame, mult: dict[str, float]) -> pd.DataFrame:
    """Per (ts_known, symbol): the raw ratio KRW close ÷ Binance's USDT close (÷ the contract's multiple) — a KRW per USDT rate times the
    premium; the ADJUSTED premium in bps (÷ KRW-USDT's close at the same stamp, where it exists); the BTC-RELATIVE premium in bps (the name's
    ratio over BTC's ratio at the same stamp − 1: the FX and the market-wide premium removed without a control)."""
    fx = kr[kr["market"] == CONTROL].set_index("ts_known")["close"]
    ratio = {}
    for sym, g in kr[kr["symbol"].notna()].groupby("symbol"):
        g = g.set_index("ts_known").sort_index()
        b = bn[sym].reindex(g.index) / mult.get(sym, 1.0) if sym in bn else pd.Series(np.nan, index=g.index)
        ratio[sym] = (g["close"] / b, g["close"], b)
    btc = ratio[BTC][0] if BTC in ratio else pd.Series(dtype=float)
    rows = []
    for sym, (r, kc, b) in ratio.items():
        u = fx.reindex(r.index)
        rb = btc.reindex(r.index) if len(btc) else pd.Series(np.nan, index=r.index)
        rows.append(pd.DataFrame({"symbol": sym, "ts_known": r.index, "krw_close": kc.to_numpy(), "bn_close": b.to_numpy(), "ratio_krw_usdt": r.to_numpy(), "fx_krw_usdt": u.to_numpy(),
                                  "prem_adj_bps": ((r / u) - 1.0).to_numpy() * 1e4, "prem_btc_bps": ((r / rb) - 1.0).to_numpy() * 1e4}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["symbol", "ts_known", "krw_close", "bn_close", "ratio_krw_usdt", "fx_krw_usdt", "prem_adj_bps", "prem_btc_bps"])


def alignment(kr: pd.DataFrame) -> dict:
    """The share of bars whose last tick lies inside [ts, ts + 1 h): the evidence that `candle_date_time_utc` is the bar's START."""
    g = kr[kr["last_tick"].notna()]
    if g.empty:
        return {"bars": 0}
    d = (g["last_tick"] - g["ts"]).dt.total_seconds()
    return {"bars": int(len(g)), "share_tick_inside_hour": float(((d >= 0) & (d < 3600)).mean()), "share_tick_before_start": float((d < 0).mean()),
            "share_tick_at_end": float((d == 3600).mean()), "share_tick_after_end": float((d > 3600).mean()), "median_tick_offset_s": float(d.median())}


def live_lag(U: dict, market: str = "KRW-BTC", now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now("UTC")
    res = _get(f"{U['api']}/candles/minutes/60?market={market}&count=3") or []
    starts = sorted(_parse_start(r["candle_date_time_utc"]) for r in res if isinstance(r, dict) and "candle_date_time_utc" in r)
    complete = [s for s in starts if s + HOUR <= now]
    return {"venue": U["venue"], "now": str(now), "bars_served": len(starts), "in_progress_served": bool(starts and starts[-1] + HOUR > now),
            "last_complete_end": str(complete[-1] + HOUR) if complete else None,
            "seconds_since_last_complete_end": float((now - (complete[-1] + HOUR)).total_seconds()) if complete else np.nan}


def volume_share(kr: pd.DataFrame, P: pd.DataFrame, slices: tuple[str, ...], a0: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """AX2's form, described: the venue's hourly KRW volume ÷ KRW-USDT over Binance's USDT volume of the same hour — the median share, p10 / p90,
    the sd of the log share's deviation from its trailing 30-day mean, and that deviation's correlation with the BTC-relative premium."""
    fx = kr[kr["market"] == CONTROL].set_index("ts_known")["close"]
    kv = kr[kr["symbol"].notna()].pivot_table(index="ts_known", columns="symbol", values="volume_krw", aggfunc="last")
    kv = kv[(kv.index > a0) & (kv.index <= end)]
    if kv.empty or fx.empty:
        return pd.DataFrame(columns=["symbol", "hours", "share_median", "share_p10", "share_p90", "dev_sd", "corr_dev_prem"])
    usd = kv.div(fx.reindex(kv.index), axis=0)
    bnv = cb.binance_dvol_hour(list(kv.columns), kv.index, slices)
    prem = P.pivot_table(index="ts_known", columns="symbol", values="prem_btc_bps").reindex(kv.index)
    rows = []
    for sym in kv.columns:
        share = (usd[sym] / bnv[sym]).replace([np.inf, -np.inf], np.nan) if sym in bnv else pd.Series(np.nan, index=kv.index)
        share = share.where(share > 0)
        ls = np.log(share)
        dev = ls - ls.rolling(720, min_periods=360).mean()
        ok = dev.notna() & (prem[sym].notna() if sym in prem else False)
        rows.append({"symbol": sym, "hours": int(share.notna().sum()), "share_median": share.median(), "share_p10": share.quantile(0.1), "share_p90": share.quantile(0.9),
                     "dev_sd": dev.std(), "corr_dev_prem": float(dev[ok].corr(prem[sym][ok])) if ok.sum() > 100 else np.nan})
    return pd.DataFrame(rows)


def audit(U: dict, today: pd.Timestamp | None = None, lag: dict | None = None, markets_df: pd.DataFrame | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    kr = load(U["parquet"])
    end = min(kr["ts_known"].max(), folds.bounds("F5")[1]) if len(kr) else today
    a0 = pd.Timestamp(AUDIT_START, tz="UTC")
    expected = pd.date_range(a0, end, freq="h", inclusive="left")
    if markets_df is None:
        markets_df = markets_file(U)
        if markets_df is None:
            markets_df = pd.DataFrame(columns=["market", "symbol", "listed"])
    minfo = markets_df.set_index("market") if len(markets_df) else pd.DataFrame()
    lag = lag if lag is not None else live_lag(U, now=today)
    rows = []
    for mk, sym in U["markets"].items():
        g = kr[kr["market"] == mk]
        r = {"market": mk, "symbol": sym or "(control)", "listed": bool(minfo.loc[mk, "listed"]) if mk in minfo.index else None,
             "hourly_first": str(g["ts"].min()) if len(g) else None, "hourly_last": str(g["ts"].max()) if len(g) else None, "hours": int(len(g))}
        if len(g):
            have = pd.DatetimeIndex(g["ts"])
            inside = have[(have >= a0) & (have < end)]
            r["completeness"] = float(len(inside) / max(len(expected), 1))
            d = np.diff(have.sort_values().asi8) / 3.6e12
            r["gaps_over_1h"] = int((d > 1.0001).sum())
            r["largest_gap_h"] = float(d.max()) if len(d) else 0.0
            r["share_unchanged_close"] = float((g.sort_values("ts")["close"].diff() == 0).mean())
            for f in ("F1", "F2", "F3", "F4", "F5"):
                fa, fb = folds.bounds(f)
                sh = pd.date_range(fa.ceil("h"), min(fb, end), freq="h", inclusive="left")
                r[f"cover_{f}"] = float(sh.isin(have).mean()) if len(sh) else np.nan
        rows.append(r)
    cov = pd.DataFrame(rows)
    syms = [s for s in U["markets"].values() if s and kr["symbol"].eq(s).any()]
    stamps = pd.DatetimeIndex(sorted(kr.loc[kr["symbol"].isin(syms), "ts_known"].unique()))
    bn = cb.binance_close_at(syms, stamps, U["slices"]) if syms else pd.DataFrame()
    P = premium(kr, bn, U["mult"])
    P = P[(P["ts_known"] > a0) & (P["ts_known"] <= end)]
    kr_cb = kr.rename(columns={"market": "product"})                       # coinbase.member_cover reads (product, symbol, ts)
    mcov, blocks = cb.member_cover(kr_cb)
    if len(mcov):
        cov = cov.merge(mcov, on="symbol", how="left")
    vshare = volume_share(kr, P, U["slices"], a0, end)
    align = alignment(kr[(kr["ts"] >= a0)])
    stat = []
    for sym, g in P.groupby("symbol"):
        g = g.set_index("ts_known").sort_index()
        for col, tag in (("prem_adj_bps", "adj"), ("prem_btc_bps", "btc_rel")):
            x = g[col]
            if not x.notna().any():
                continue
            stat.append({"symbol": sym, "premium": tag, "hours": int(x.notna().sum()), "mean": x.mean(), "median": x.median(), "sd": x.std(), "p10": x.quantile(0.1), "p90": x.quantile(0.9),
                         "acf_1h": cb._acf(x, 1), "acf_24h": cb._acf(x, 24), f"share_abs_gt_{BIG:g}": float((x.abs() > BIG).mean()),
                         "mean_kst_day_0_9": float(x[x.index.hour < 9].mean()), "mean_us_hours_14_21": float(x[(x.index.hour >= 14) & (x.index.hour < 21)].mean())})
    stat = pd.DataFrame(stat)
    wide = P.pivot_table(index="ts_known", columns="symbol", values="prem_btc_bps")
    C = wide.corr()
    off = C.where(~np.eye(len(C), dtype=bool)).stack() if len(C) else pd.Series(dtype=float)
    hod = wide.groupby(wide.index.hour).mean().mean(axis=1) if len(wide) else pd.Series(dtype=float)
    fx = kr[kr["market"] == CONTROL].set_index("ts_known")["close"]
    fx = fx[(fx.index > a0) & (fx.index <= end)]
    adj_wide = P.pivot_table(index="ts_known", columns="symbol", values="prem_adj_bps")
    mkt_prem = adj_wide.median(axis=1) if len(adj_wide) else pd.Series(dtype=float)        # the market-wide kimchi premium: the median adjusted premium across names
    v = U["venue"]
    L = [f"# The Korean premium — source audit, {v} (decision BB1 step (i); `ft2 krw audit --venue {v}`)\n",
         f"generated {today:%Y-%m-%d %H:%M} UTC · {U['parquet']} · the premium counted over {a0.date()} → {end.date()} at each hour's END (the bar's start + 1 h)\n",
         f"\nWords: the *ratio* is {v}'s hourly KRW close over Binance's 5m USDT close ending at the same stamp (a 1000× contract's price divided) — KRW per USDT times the premium; "
         "the *adjusted* premium divides it by KRW-USDT's close on the venue at the same hour, in bps; the *BTC-relative* premium divides it by BTC's ratio at the same hour, in bps "
         "(the FX and the market-wide premium removed without a control — the quantity a within-hour rank screen reads). Nothing is priced here; no fold is read.\n",
         "\n## Markets, extent, completeness, cover (hours)\n", cov.round(4).to_markdown(index=False), "\n",
         f"\n## The alignment of the stamp — the last tick against the bar's start\n- {json.dumps(align)}\n- Rule: `candle_date_time_utc` is the bar's START when the last tick lies inside [start, start + 1 h); a bar is read at `ts_known` = start + 1 h and nothing earlier.\n",
         f"\n## The serving lag, measured live\n- {json.dumps(lag)}\n- Rule: the bucket in progress is served and is never read.\n",
         "\n## The members' cover of their own hours, per block — the breadth R62's frame would have\n", blocks.to_markdown(index=False) if len(blocks) else "(no member bars)", "\n",
         f"\nA member counts in `cover_ge_{COVER_OK:g}` when ≥ {COVER_OK:.0%} of the hours of the block it is a member of have a bar on {v}. Per name `cover_member` (in the table above) is the share over all its member blocks.\n",
         "\n## The premium per name\n", stat.round(3).to_markdown(index=False) if len(stat) else "(no overlap with Binance's candles)", "\n",
         f"\n## Across names (BTC-relative premium)\n- mean off-diagonal correlation {off.mean():.3f} (min {off.min():.3f}, max {off.max():.3f}) on the hours both names have\n" if len(off) else "\n## Across names\n- fewer than two names\n",
         "- mean by hour of day (UTC), averaged over names: " + ", ".join(f"{h:02d}h {val:+.1f}" for h, val in hod.items()) + "\n" if len(hod) else "",
         f"\n## The market-wide premium (the median adjusted premium across names, bps)\n- {len(mkt_prem.dropna())} hours; median {mkt_prem.median():+.1f}, p10 {mkt_prem.quantile(0.1):+.1f}, p90 {mkt_prem.quantile(0.9):+.1f}, sd {mkt_prem.std():.1f}; autocorrelation at 24 h {cb._acf(mkt_prem, 24):.3f}\n" if len(mkt_prem.dropna()) else "",
         f"\n## KRW-USDT on {v}\n- {len(fx)} hours from {fx.index.min()} ; median {fx.median():.1f} KRW, p1 {fx.quantile(0.01):.1f}, p99 {fx.quantile(0.99):.1f}\n" if len(fx) else f"\n## KRW-USDT on {v}\n- no bars in the window: the adjusted premium is empty, the BTC-relative one stands\n",
         "\n## The volume share per name (AX2's form, described): the venue's hourly volume in USDT over Binance's USDT volume in the same hour\n",
         vshare.round(4).to_markdown(index=False) if len(vshare) else "(no KRW-USDT rate, or no volume)", "\n",
         "`dev_sd` = the sd of the log share's deviation from its trailing 30-day mean; `corr_dev_prem` = that deviation's correlation with the BTC-relative premium at the same hour.\n"]
    listed = cov[(cov["listed"] == True) & (cov["market"] != CONTROL)]  # noqa: E712
    with_bars = cov[(cov["hours"] > 0) & (cov["market"] != CONTROL)]
    row = (f"| **krw_1h_{v}** ({v} KRW spot, hourly, the twelve's and the screener's members' KRW-<BASE> markets; decision BB1 (i)) | `ft2 krw fetch --venue {v} --listed-only`, raw `data/raw/external/{v}/` | "
           + f"{len(listed)} of {len(U['markets']) - 1} bases listed, {len(with_bars)} with hourly bars; per block "
           + "; ".join(f"{b['block']} {b[f'cover_ge_{COVER_OK:g}']} of {b['members']}" for _, b in blocks.iterrows())
           + f" | `{U['parquet']}`; a bar is read at `ts_known` = its start + 1 h |")
    L += ["\n## DATA.md row\n", "\n" + row + "\n"]
    txt = "".join(x if x.endswith("\n") else x + "\n" for x in L)
    U["out"].parent.mkdir(parents=True, exist_ok=True)
    U["out"].write_text(txt)
    (U["out"].parent / f"krw_{v}_audit.json").write_text(json.dumps({"cover": cov.to_dict("records"), "stats": stat.to_dict("records"), "corr_mean": float(off.mean()) if len(off) else None,
                                                                    "lag": lag, "alignment": align, "hod": {int(k): float(val) for k, val in hod.items()}, "blocks": blocks.to_dict("records"),
                                                                    "volume_share": vshare.to_dict("records"),
                                                                    "market_premium": {"hours": int(mkt_prem.notna().sum()), "median": float(mkt_prem.median()) if len(mkt_prem) else None,
                                                                                       "sd": float(mkt_prem.std()) if len(mkt_prem) else None}}, indent=1, default=str))
    P.to_parquet(U["out"].parent / f"krw_{v}_premium.parquet", index=False)
    return txt


def main(action: str, venue: str, start: str = START, end: str | None = None, mkts=None, listed_only: bool = False) -> None:
    U = universe(venue)
    if action == "markets":
        print(markets(U).to_string())
    elif action == "fetch":
        print(json.dumps(fetch(U, start, end, mkts=mkts, listed_only=listed_only), indent=1))
    elif action == "ingest":
        print(json.dumps(ingest(U, mkts=mkts), indent=1))
    elif action == "audit":
        print(audit(U))
    else:
        sys.exit(f"krw: unknown action {action}")
