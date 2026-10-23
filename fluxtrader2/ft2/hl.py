"""P8 (decision BJ2, 2026-10-23) — Hyperliquid's per-name funding and mark premium as a data source: `ft2 hl symbols|fetch|bnprem|ingest|audit`.

source     Hyperliquid's public info API (`POST https://api.hyperliquid.xyz/info`, free, keyless): `meta` lists the perpetuals (234 on
           2026-10-23, the delisted ones flagged); `fundingHistory` {coin, startTime[, endTime]} returns up to 500 rows {coin,
           fundingRate, premium, time} ascending — ONE ROW PER FUNDING SETTLEMENT: 8-hourly from the venue's start (2023-05-12) until
           2023-06-25, HOURLY since. `premium` is the venue's own mark premium over its oracle (the hour's sample average, a fraction),
           `fundingRate` the rate paid at that settlement (premium + the interest term, clamped; a fraction PER SETTLEMENT — per hour
           since 2023-06-25). The stamp is the settlement time plus a lag (≤ 0.2 s since 2023-07; up to 24 min in the 8-hour weeks).
           The venue's prices are NOT in this source (the candle endpoint serves recent bars only) — nothing here is priced.
symbols    a coin per perpetual: the base (`coinbase.base`, the 1000× / 1M× prefix stripped) when the venue lists it, else `k<BASE>`
           (the venue's thousand-token contracts: kPEPE, kSHIB, kBONK, kFLOKI, kLUNC, kNEIRO, kDOGS), else an ALIAS; the listing is the
           `meta` call, saved once (`symbols_<YYYYMMDD>.json`).
raw        data/raw/external/hyperliquid/funding/<COIN>.json (every row fetched, resumable from the last stamp; `.done` when complete),
           data/raw/external/hyperliquid/symbols_<YYYYMMDD>.json.
parquet    data/hl_funding_1h.parquet: (coin, symbol, ts, ts_known, stamp, lag_s, rate, premium, frozen) — `ts` the settlement HOUR (the
           stamp floored), `ts_known` = ts: the row describes the hour ending at ts and appears a lag after it (`lag_s`; read the row at
           ts plus a minute to be safe). The premium and the rate are fractions (× 1e4 = bps). `frozen`: the row sits in a run of ≥
           FROZEN_RUN settlements whose premium is exactly 0 — a delisted coin keeps emitting such rows for years (32 of our 181 coins;
           up to 805 days of zeros) — and every reader treats it as ABSENT.
bnprem     Binance's own premium index per name at the same hourly grid for the stamp check and the "same quantity?" question: the
           archive's `premiumIndexKlines/<sym>/1h/` month files (the perpetual's price over the spot index, minus one; R20 fetched the
           5m ones to 2024-08) → data/premium_1h.parquet: (symbol, ts, ts_known, open, high, low, close) — a bar starting at H is read
           at `ts_known` = H + 1 h.
audit      output/hl_audit.md (+ .json, hl_quantities.parquet, a DATA.md row): per symbol the first row, the extent, the hourly regime's
           start, completeness, gaps, F1–F5 cover, the member-hours cover and the per-block breadth (R62's frame); the stamp check (the
           venue's hour premium against Binance's premium bar of the same hour: the correlation by lag, the best lag 0 when the stamps
           agree); the funding check (the venue's settlements summed over Binance's funding period against Binance's settled rate — the
           same quantity on two crowds?); the quantities per name — the premium `hl_prem` and the funding `hl_fund` (bps), their
           trailing-day forms `hl_prem24` (mean) and `hl_fund24` (sum), Binance's `bn_prem` and `bn_prem24`, the cross-venue gap
           `gap24` = hl_prem24 − bn_prem24 — each its level, within-name sd, persistence, hour-of-day shape, its deviation from the
           trailing month in sd units (cb_ext's DEV form) and that deviation's correlation with Binance's own premium deviation, with
           `cbprem_dev` and with R68's two spot deviations on R62's kept names; the cross-name correlation of each deviation; the pooled
           crowd lean. Nothing priced, no fold read, nothing registered.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive
from . import coinbase as cb
from . import data, folds
from .spot import dev

API = "https://api.hyperliquid.xyz/info"
UA = {"User-Agent": "fluxtrader2-research/1.0", "Content-Type": "application/json"}
RAW = data.RAW / "external" / "hyperliquid"
PARQUET = data.PROC / "hl_funding_1h.parquet"
BN_PARQUET = data.PROC / "premium_1h.parquet"
BN_KIND = "premiumIndexKlines"
BN_INTERVAL = "1h"
OUT = Path("output/hl_audit.md")
PAGE = 500                   # the API's page
PAUSE = 0.15                 # s between calls on top of ≈ 0.9 s of latency: the info limit is 1,200 weight a minute at weight 20 a call (60 a minute); a 429 sleeps 10 s
RETRIES = 6
HOUR = pd.Timedelta("1h")
START = "2023-04-01"         # a month before F1 (the venue starts 2023-05-12)
AUDIT_START = "2023-05-01"   # F1's first day: completeness is counted from here
MIN_CORR_HOURS = 100
DAY, MIN_DAY = 24, 20        # the trailing-day forms: 24 hourly rows, ≥ 20 present
LAGS = range(-3, 4)          # the stamp check's lags (hours)
CORR_SAME = 0.5              # a deviation is "the same quantity again" when |corr| ≥ this
COVER_OK = cb.COVER_OK
PREMIUM = Path("output/coinbase_members_premium.parquet")   # AX1's audit: prem_adj_bps per (symbol, ts_known) → cbprem_dev
SPOT_RATIOS = Path("output/spot_ratios.parquet")            # BH1's audit: tb24_dev, sr24_dev per (ts_known, symbol) — R68's two
KEPT = Path(__file__).with_name("cb_members_r62.csv")        # R62's kept names (r62 True)
ALIASES = {"JELLYJELLYUSDT": "JELLY"}                        # the venue's name where neither the base nor k<BASE> is it
TWELVE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "1000PEPEUSDT", "WLDUSDT", "ZECUSDT", "HYPEUSDT"]
FROZEN_RUN = 24              # a run of this many consecutive settlements with a premium of exactly 0 is a frozen market (a delisted coin keeps
                             # emitting zero rows for years), not data: the rows are kept in the parquet, flagged `frozen`, and read as absent
COLS = ["coin", "symbol", "ts", "ts_known", "stamp", "lag_s", "rate", "premium", "frozen"]
BN_COLS = ["symbol", "ts", "ts_known", "open", "high", "low", "close"]
QUANTITIES = {"hl_prem": "the venue's hour premium", "hl_fund": "the venue's hourly funding", "hl_prem24": "the trailing-day mean premium",
              "hl_fund24": "the trailing-day funding", "bn_prem": "Binance's hour premium", "bn_prem24": "Binance's trailing-day mean premium",
              "gap24": "the cross-venue gap of the trailing-day premiums"}


# ---- the API ----------------------------------------------------------------------------------------------------------------------
def _post(payload: dict, timeout: int = 60, retries: int = RETRIES):
    body = json.dumps(payload).encode()
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(API, data=body, headers=UA), timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (i + 1))
                continue
            if i == retries - 1:
                raise
            time.sleep(2 ** (i + 1))
        except (urllib.error.URLError, TimeoutError, OSError):
            if i == retries - 1:
                raise
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f"hl: {payload.get('type')} failed after {retries} tries")


def meta() -> pd.DataFrame:
    u = _post({"type": "meta"})["universe"]
    return pd.DataFrame({"coin": [x["name"] for x in u], "delisted": [bool(x.get("isDelisted", False)) for x in u]})


def perp_symbols() -> list[str]:
    """The twelve first, then every member symbol of the two member files, each once."""
    out = list(TWELVE)
    for s in sorted(set(cb.member_symbols()["symbol"])):
        if s not in out:
            out.append(s)
    return out


def candidates(sym: str) -> list[str]:
    """The venue's names a perpetual may trade under, in order: the base, k<BASE>, the alias."""
    b = cb.base(sym)
    c = [b, f"k{b}"]
    return c + [ALIASES[sym]] if sym in ALIASES else c


def symbols_file() -> pd.DataFrame | None:
    files = sorted(RAW.glob("symbols_*.json"))
    return pd.DataFrame(json.load(open(files[-1]))["rows"]) if files else None


def symbols(today: pd.Timestamp | None = None, listing: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row a perpetual: its coin on the venue (the first candidate the listing holds, else None), delisted there or not — saved under RAW."""
    today = today or pd.Timestamp.now("UTC")
    L = meta() if listing is None else listing
    have = dict(zip(L["coin"], L["delisted"]))
    rows = []
    for sym in perp_symbols():
        hit = next((c for c in candidates(sym) if c in have), None)
        rows.append({"symbol": sym, "coin": hit, "listed": hit is not None, "delisted": bool(have[hit]) if hit else False, "mult": cb.mult_of(sym)})
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"symbols_{today:%Y%m%d}.json").write_text(json.dumps({"venue_coins": len(have), "rows": rows}, indent=1))
    return pd.DataFrame(rows)


def universe(only: list[str] | None = None) -> dict[str, str]:
    """coin → perpetual symbol from the saved listing (two contracts on one base: the first, the twelve's, keeps the coin)."""
    sf = symbols_file()
    if sf is None:
        raise SystemExit("hl: no saved listing — run `ft2 hl symbols` first")
    mp: dict[str, str] = {}
    for _, r in sf.iterrows():
        if r["listed"]:
            mp.setdefault(r["coin"], r["symbol"])
    if only:
        mp = {k: v for k, v in mp.items() if v in only or k in only}
    return mp


def _end_ms(end: str | None) -> int:
    e = pd.Timestamp(end, tz="UTC") if end else folds.bounds("F5")[1] + HOUR
    return int(e.timestamp() * 1000)


def fetch_coin(coin: str, start: str = START, end: str | None = None, raw: Path | None = None) -> dict:
    """Every settlement row of `coin` in [start, end], 500 a page, resumed from the saved file's last stamp; `.done` when the last page is short
    or reaches `end`."""
    raw = RAW if raw is None else raw
    p = (raw / "funding" / f"{coin}.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    done = p.with_suffix(".done")
    if done.exists():
        return {"coin": coin, "pages": 0, "rows": 0, "skip": True}
    rows = json.load(open(p))["rows"] if p.exists() else []
    t0 = rows[-1]["time"] + 1 if rows else int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    t1 = _end_ms(end)
    pages = n = 0
    while t0 <= t1:
        page = _post({"type": "fundingHistory", "coin": coin, "startTime": t0, "endTime": t1})
        pages += 1
        if not page:
            break
        page = [r for r in page if r["time"] >= t0]        # the API is inclusive at both ends
        rows += page
        n += len(page)
        p.write_text(json.dumps({"coin": coin, "rows": rows}))
        if len(page) < PAGE or not page:
            break
        t0 = page[-1]["time"] + 1
        time.sleep(PAUSE)
    if not p.exists():
        p.write_text(json.dumps({"coin": coin, "rows": rows}))
    done.touch()
    return {"coin": coin, "pages": pages, "rows": n, "skip": False}


def fetch(start: str = START, end: str | None = None, only: list[str] | None = None) -> dict:
    mp = universe(only)
    tot = {"coins": len(mp), "pages": 0, "rows": 0, "skipped": 0, "err": 0}
    for i, (coin, sym) in enumerate(mp.items()):
        try:
            c = fetch_coin(coin, start, end)
        except Exception as e:                      # noqa: BLE001 — one coin's failure must not end the chain; the re-run resumes it
            tot["err"] += 1
            print(f"{i + 1:>4}/{len(mp)} {coin:<10} {sym:<14} ERROR {e}", flush=True)
            continue
        tot["pages"] += c["pages"]
        tot["rows"] += c["rows"]
        tot["skipped"] += int(c["skip"])
        print(f"{i + 1:>4}/{len(mp)} {coin:<10} {sym:<14} {c}", flush=True)
        if not c["skip"]:
            time.sleep(PAUSE)
    if tot["err"]:
        print(f"hl fetch done with {tot['err']} errors — re-run the same command to pick them up", file=sys.stderr)
    return tot


def read_coin(coin: str, sym: str, raw: Path | None = None) -> pd.DataFrame:
    raw = RAW if raw is None else raw
    p = raw / "funding" / f"{coin}.json"
    if not p.exists():
        return pd.DataFrame(columns=COLS)
    rows = json.load(open(p))["rows"]
    if not rows:
        return pd.DataFrame(columns=COLS)
    stamp = pd.to_datetime([r["time"] for r in rows], unit="ms", utc=True)
    ts = stamp.floor("h")
    out = pd.DataFrame({"coin": coin, "symbol": sym, "ts": ts, "ts_known": ts, "stamp": stamp, "lag_s": (stamp - ts).total_seconds(),
                        "rate": [float(r["fundingRate"]) for r in rows], "premium": [float(r["premium"]) for r in rows]})
    out = out.sort_values("stamp").drop_duplicates("ts", keep="last").reset_index(drop=True)
    out["frozen"] = frozen_mask(out["premium"])
    return out[COLS]


def frozen_mask(premium: pd.Series) -> pd.Series:
    """True inside every run of ≥ FROZEN_RUN consecutive rows whose premium is exactly 0 (the rows in settlement order)."""
    z = premium.to_numpy() == 0.0
    run_id = np.cumsum(~z)                                   # constant inside a run of zeros
    n = pd.Series(z).groupby(run_id).transform("sum").to_numpy()
    return pd.Series(z & (n >= FROZEN_RUN), index=premium.index)


def ingest(only: list[str] | None = None, path: Path = PARQUET) -> dict:
    mp = universe(only)
    parts = [read_coin(coin, sym) for coin, sym in mp.items()]
    df = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame(columns=COLS)
    for c in ("coin", "symbol"):
        df[c] = df[c].astype("category")
    df = df.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return {"coins_asked": len(mp), "coins_with_rows": int(df["coin"].nunique()), "rows": len(df), "frozen_rows": int(df["frozen"].sum()),
            "coins_with_frozen": int(df.loc[df["frozen"], "coin"].nunique()),
            "first": str(df["ts"].min()) if len(df) else None, "last": str(df["ts"].max()) if len(df) else None, "file": str(path)}


def load(path: Path | str = PARQUET, live_only: bool = True) -> pd.DataFrame:
    """The settlement rows; the frozen ones dropped unless `live_only` is False."""
    d = pd.read_parquet(path)
    for c in ("coin", "symbol"):
        d[c] = d[c].astype(str)
    if "frozen" not in d:
        d["frozen"] = False
    return d[~d["frozen"]].reset_index(drop=True) if live_only else d


# ---- Binance's premium index, hourly ------------------------------------------------------------------------------------------------
def bnprem_fetch(start: str = START, end: str | None = None, only: list[str] | None = None, root: Path | None = None) -> dict:
    """The archive's monthly 1h premiumIndexKlines of every symbol of the saved listing (resumable, checksums)."""
    s = pd.Timestamp(start).date()
    e = pd.Timestamp(end).date() if end else folds.bounds("F5")[1].date()
    months = archive.months_between(s, e)
    syms = list(universe(only).values())
    tot = {"symbols": len(syms), "ok": 0, "skip": 0, "bad": 0, "err": 0, "missing": 0}
    for i, sym in enumerate(syms):
        c = archive.fetch_monthly(BN_KIND, sym, sub=BN_INTERVAL, months=months, root=root)
        for k in tot:
            if k != "symbols":
                tot[k] += c.get(k, 0)
        print(f"{i + 1:>4}/{len(syms)} {sym:<14} {c}", flush=True)
    if tot["err"] or tot["bad"]:
        print(f"hl bnprem fetch done with {tot['err'] + tot['bad']} errors — re-run the same command to pick them up", file=sys.stderr)
    return tot


def read_bn_symbol(sym: str, root: Path | None = None) -> pd.DataFrame:
    root = archive.ROOT if root is None else root
    files = [f for f in sorted((root / BN_KIND / sym).glob(f"{sym}-{BN_INTERVAL}-*.zip")) if f.with_suffix(".zip.ok").exists()]
    parts = []
    for f in files:
        with zipfile.ZipFile(f) as z:
            for n in z.namelist():
                parts.append(pd.read_csv(z.open(n), header=None, names=data.KLINE_COLS, dtype=str))
    if not parts:
        return pd.DataFrame(columns=BN_COLS)
    df = pd.concat(parts, ignore_index=True)
    df = df[df["open_time"].str.isdigit()]
    v = df["open_time"].astype("int64").to_numpy()
    ts = pd.DatetimeIndex(np.where(v >= 10**14, v, v * 1000).astype("datetime64[us]")).tz_localize("UTC")     # ms, or µs from 2025-01
    out = pd.DataFrame({"symbol": sym, "ts": ts, "ts_known": ts + HOUR})
    for c in ("open", "high", "low", "close"):
        out[c] = df[c].astype(float).to_numpy()
    return out[BN_COLS].sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)


def bnprem_ingest(only: list[str] | None = None, path: Path = BN_PARQUET, root: Path | None = None) -> dict:
    syms = list(universe(only).values())
    parts = [read_bn_symbol(s, root) for s in syms]
    df = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame(columns=BN_COLS)
    df["symbol"] = df["symbol"].astype("category")
    df = df.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return {"symbols_asked": len(syms), "symbols_with_bars": int(df["symbol"].nunique()), "rows": len(df),
            "first": str(df["ts"].min()) if len(df) else None, "last": str(df["ts"].max()) if len(df) else None, "file": str(path)}


# ---- the quantities -----------------------------------------------------------------------------------------------------------------
def _acf(x: pd.Series, lag: int) -> float:
    return cb._acf(x, lag)


def grids(d: pd.DataFrame, bn: pd.DataFrame, a0: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """On the hourly grid (ts_known × perp symbol), inside (a0, end]: the venue's premium `hl_prem` and funding `hl_fund` (bps), Binance's
    premium bar's close `bn_prem` and its open-high-low-close mean `bn_prem_avg` (bps), the trailing-day forms (`hl_prem24` the mean, `hl_fund24`
    the sum scaled to 24 rows, `bn_prem24` the mean; ≥ MIN_DAY of DAY present), the gap `gap24`, and every quantity's deviation `*_dev`."""
    d = d[(d["ts_known"] > a0) & (d["ts_known"] <= end)]
    grid = pd.date_range(a0.ceil("h") + HOUR, end.floor("h"), freq="h")
    W = lambda df, col: df.pivot_table(index="ts_known", columns="symbol", values=col, aggfunc="last").reindex(grid)
    prem, fund = W(d, "premium") * 1e4, W(d, "rate") * 1e4
    syms = list(prem.columns)
    bn = bn[(bn["ts_known"] > a0) & (bn["ts_known"] <= end) & bn["symbol"].isin(syms)]
    bnp = W(bn, "close").reindex(columns=syms) * 1e4
    bna = (sum(W(bn, c) for c in ("open", "high", "low", "close")) / 4.0).reindex(columns=syms) * 1e4
    n24 = fund.notna().rolling(DAY, min_periods=1).sum()
    G = {"hl_prem": prem, "hl_fund": fund, "bn_prem": bnp, "bn_prem_avg": bna,
         "hl_prem24": prem.rolling(DAY, min_periods=MIN_DAY).mean(),
         "hl_fund24": (fund.rolling(DAY, min_periods=MIN_DAY).sum() * DAY / n24.where(n24 >= MIN_DAY)),
         "bn_prem24": bnp.rolling(DAY, min_periods=MIN_DAY).mean()}
    G["gap24"] = G["hl_prem24"] - G["bn_prem24"]
    for k in list(QUANTITIES):
        G[k + "_dev"] = dev(G[k])
    return G


def cb_dev(path: Path = PREMIUM, grid: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    from .spot import cb_dev as _cb
    return _cb(path, grid)


def spot_devs(path: Path = SPOT_RATIOS, grid: pd.DatetimeIndex | None = None) -> dict[str, pd.DataFrame]:
    """R68's two deviations from BH1's audit parquet, wide on the grid; empty frames when absent."""
    if not Path(path).exists():
        return {k: pd.DataFrame(index=grid) for k in ("tb24_dev", "sr24_dev")}
    R = pd.read_parquet(path, columns=["ts_known", "symbol", "tb24_dev", "sr24_dev"])
    out = {}
    for k in ("tb24_dev", "sr24_dev"):
        Wk = R.pivot_table(index="ts_known", columns="symbol", values=k, aggfunc="last")
        out[k] = Wk.reindex(grid) if grid is not None else Wk
    return out


def kept_names(path: Path = KEPT) -> set[str]:
    if not Path(path).exists():
        return set()
    k = pd.read_csv(path)
    return set(k.loc[k["r62"].astype(bool), "symbol"].astype(str))


def _corr(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    ok = a.notna() & b.notna()
    return (float(a[ok].corr(b[ok])) if ok.sum() >= MIN_CORR_HOURS else np.nan), int(ok.sum())


def stats(G: dict[str, pd.DataFrame], O: dict[str, pd.DataFrame], kept: set[str]) -> pd.DataFrame:
    """Per name and quantity: the level's hours / mean / median / sd / p10 / p90 / acf at 1 h and 24 h; the deviation's sd and acf; the deviation's
    correlation with Binance's premium deviation, with cbprem_dev and with R68's two on the hours both exist (≥ MIN_CORR_HOURS)."""
    rows = []
    for k in QUANTITIES:
        lvl, dv = G[k], G[k + "_dev"]
        for sym in lvl.columns:
            x, z = lvl[sym], dv[sym]
            if not x.notna().any():
                continue
            r = {"symbol": sym, "quantity": k, "kept_r62": sym in kept, "hours": int(x.notna().sum()), "mean": x.mean(), "median": x.median(), "sd": x.std(),
                 "p10": x.quantile(0.1), "p90": x.quantile(0.9), "acf_1h": _acf(x, 1), "acf_24h": _acf(x, 24),
                 "dev_hours": int(z.notna().sum()), "dev_sd": z.std(), "dev_acf_1h": _acf(z, 1), "dev_acf_24h": _acf(z, 24)}
            for name, Wo in O.items():
                o = Wo[sym] if sym in Wo.columns else pd.Series(np.nan, index=z.index)
                r[f"corr_dev_{name}"], r[f"hours_with_{name}"] = _corr(z, o)
            rows.append(r)
    return pd.DataFrame(rows)


def stamp_check(G: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per name: the correlation of the venue's hour premium with Binance's premium bar of the same hour (its open-high-low-close mean) at each
    lag of LAGS (lag L: Binance's bar L hours EARLIER), the best lag by |corr| — 0 when the stamps agree — and the level gap."""
    rows = []
    X, Y = G["hl_prem"], G["bn_prem_avg"]
    for sym in X.columns:
        if sym not in Y.columns or not Y[sym].notna().any():
            continue
        x, y = X[sym], Y[sym]
        r = {"symbol": sym}
        for L in LAGS:
            r[f"corr_lag{L:+d}"], n = _corr(x, y.shift(L))
        r["hours"] = n
        cs = {L: r[f"corr_lag{L:+d}"] for L in LAGS if not np.isnan(r[f"corr_lag{L:+d}"])}
        r["best_lag"] = max(cs, key=lambda L: abs(cs[L])) if cs else np.nan
        r["corr_lag0"] = r["corr_lag+0"]
        r["level_hl_minus_bn_bps"] = float((x - G["bn_prem"][sym]).median())
        rows.append(r)
    return pd.DataFrame(rows)


def funding_check(d: pd.DataFrame, fa: pd.DataFrame, a0: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Per name: Binance's settled rate at each of its funding times against the venue's settlements summed over the same period (≥ 80 % of the
    period's hours present, in the venue's hourly regime): the correlation, the count, both means annualised (% a year)."""
    rows = []
    fa = fa[(fa["ts"] > a0) & (fa["ts"] <= end)]
    for sym, g in d.groupby("symbol"):
        f = fa[fa["symbol"] == sym]
        if len(f) < 10:
            continue
        s = g.set_index("ts")["rate"].sort_index()
        grid = pd.date_range(s.index.min().floor("h"), s.index.max().ceil("h"), freq="h")
        s = s.reindex(grid)
        hl_sum, bn_rate, n_per = [], [], []
        for h, fh in f.groupby("interval_h"):
            win = int(h)
            tot = s.rolling(win, min_periods=max(1, int(np.ceil(0.8 * win)))).sum()
            cnt = s.notna().rolling(win, min_periods=1).sum()
            at = fh["ts"].dt.floor("h")
            hl_sum.append(tot.reindex(at).to_numpy())
            bn_rate.append(fh["rate"].to_numpy())
            n_per.append(np.full(len(fh), win))
        hs, br, npr = (np.concatenate(x) for x in (hl_sum, bn_rate, n_per))
        ok = ~np.isnan(hs)
        if ok.sum() < 10:
            continue
        hs, br, npr = hs[ok], br[ok], npr[ok]
        rows.append({"symbol": sym, "settlements": int(len(br)), "corr": float(np.corrcoef(hs, br)[0, 1]) if len(br) > 2 and np.std(hs) > 0 and np.std(br) > 0 else np.nan,
                     "hl_mean_pct_yr": float(np.mean(hs / npr) * 8760 * 100), "bn_mean_pct_yr": float(np.mean(br / npr) * 8760 * 100),
                     "hl_sd_bps": float(np.std(hs) * 1e4), "bn_sd_bps": float(np.std(br) * 1e4)})
    return pd.DataFrame(rows)


def _off_diag(W: pd.DataFrame) -> pd.Series:
    C = W.corr(min_periods=MIN_CORR_HOURS)
    return C.where(~np.eye(len(C), dtype=bool)).stack() if len(C) else pd.Series(dtype=float)


def _regime(ts: pd.DatetimeIndex) -> tuple[str | None, int]:
    """The venue's first weeks settled every 8 hours: the length of the INITIAL run of rows followed by a gap of 7.5 … 8.5 h, and the first
    stamp after it (from which the hourly regime — and any hole — is counted)."""
    t = ts.sort_values()
    if len(t) < 2:
        return (str(t[0]) if len(t) else None), 0
    dd = pd.Series(t).diff().dt.total_seconds().to_numpy()[1:] / 3600.0
    k = 0
    while k < len(dd) and 7.5 <= dd[k] <= 8.5:
        k += 1
    return str(t[k]), int(k)


def audit(today: pd.Timestamp | None = None, path: Path = PARQUET, bn_path: Path = BN_PARQUET, out: Path = OUT, premium: Path = PREMIUM,
          spot_ratios: Path = SPOT_RATIOS, kept_csv: Path = KEPT, symbols_df: pd.DataFrame | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    full = load(path, live_only=False)
    frozen = full[full["frozen"]].groupby("symbol").agg(frozen_rows=("ts", "size"), frozen_from=("ts", "min"))
    d = full[~full["frozen"]].reset_index(drop=True)
    bn = pd.read_parquet(bn_path) if Path(bn_path).exists() else pd.DataFrame(columns=BN_COLS)
    bn["symbol"] = bn["symbol"].astype(str)
    a0 = pd.Timestamp(AUDIT_START, tz="UTC")
    end = min(d["ts_known"].max(), folds.bounds("F5")[1]) if len(d) else today
    expected = pd.date_range(a0, end, freq="h", inclusive="left")
    sf = symbols_df if symbols_df is not None else symbols_file()
    sf = sf if sf is not None else pd.DataFrame(columns=["symbol", "coin", "listed", "delisted"])
    rows = []
    for _, r0 in sf.iterrows():
        sym = r0["symbol"]
        g = d[d["symbol"] == sym]
        r = {"symbol": sym, "coin": r0["coin"], "listed": bool(r0["listed"]), "delisted": bool(r0.get("delisted", False)),
             "first": str(g["ts"].min()) if len(g) else None, "last": str(g["ts"].max()) if len(g) else None, "rows": int(len(g)),
             "frozen_rows": int(frozen.loc[sym, "frozen_rows"]) if sym in frozen.index else 0,
             "frozen_from": str(frozen.loc[sym, "frozen_from"]) if sym in frozen.index else None}
        if len(g):
            have = pd.DatetimeIndex(g["ts"])
            r["hourly_from"], r["rows_8h"] = _regime(have)
            inside = have[(have >= a0) & (have < end)]
            r["completeness"] = float(len(inside) / max(len(expected), 1))
            hf = pd.Timestamp(r["hourly_from"])
            dd = pd.Series(have[have >= hf].sort_values()).diff().dropna().dt.total_seconds().to_numpy() / 3600.0
            r["gaps_over_1h"] = int((dd > 1.0001).sum())
            r["largest_gap_h"] = float(dd.max()) if len(dd) else 0.0
            r["lag_s_p50"], r["lag_s_max"] = float(g["lag_s"].median()), float(g["lag_s"].max())
            for f in ("F1", "F2", "F3", "F4", "F5"):
                fa_, fb = folds.bounds(f)
                sh = pd.date_range(fa_.ceil("h"), min(fb, end), freq="h", inclusive="left")
                r[f"cover_{f}"] = float(sh.isin(have).mean()) if len(sh) else np.nan
        rows.append(r)
    cov = pd.DataFrame(rows)
    mcov, blocks = cb.member_cover(d.assign(product=d["coin"]))
    if len(mcov):
        cov = cov.merge(mcov, on="symbol", how="left")
    G = grids(d, bn, a0, end)
    grid = G["hl_prem"].index
    O = {"bn_prem_dev": G["bn_prem_dev"], "bn_prem24_dev": G["bn_prem24_dev"], "cb_dev": cb_dev(premium, grid)} | spot_devs(spot_ratios, grid)
    kept = kept_names(kept_csv)
    st = stats(G, O, kept)
    sc = stamp_check(G)
    fa = data.load("funding_archive", symbols=list(G["hl_prem"].columns)) if (data.PROC / "funding_archive.parquet").exists() else pd.DataFrame(columns=["symbol", "ts", "rate", "interval_h"])
    fa["symbol"] = fa["symbol"].astype(str)
    fa["ts"] = pd.DatetimeIndex(fa["ts"]).tz_localize("UTC") if len(fa) and pd.DatetimeIndex(fa["ts"]).tz is None else fa["ts"]
    fc = funding_check(d[(d["ts"] > a0) & (d["ts"] <= end)], fa, a0, end)
    off = {k: _off_diag(G[k + "_dev"]) for k in QUANTITIES}
    hod = {k: G[k].groupby(G[k].index.hour).mean().mean(axis=1) for k in ("hl_prem", "hl_fund", "bn_prem")}
    pooled = G["hl_prem"].mean(axis=1)
    pooled_bn = G["bn_prem"].mean(axis=1)
    kept_st = st[st["kept_r62"]]
    summary = {}
    for k, g in kept_st.groupby("quantity"):
        s = {"names": int(len(g)), "level_mean_median": float(g["mean"].median()), "level_sd_median": float(g["sd"].median()),
             "acf_1h_median": float(g["acf_1h"].median()), "acf_24h_median": float(g["acf_24h"].median()),
             "dev_sd_median": float(g["dev_sd"].median()), "dev_acf_24h_median": float(g["dev_acf_24h"].median())}
        for name in O:
            c = g[f"corr_dev_{name}"].dropna()
            s[f"corr_{name}"] = {"with": int(len(c)), "median": float(c.median()) if len(c) else None, "p10": float(c.quantile(0.1)) if len(c) else None,
                                 "p90": float(c.quantile(0.9)) if len(c) else None, f"share_abs_ge_{CORR_SAME:g}": float((c.abs() >= CORR_SAME).mean()) if len(c) else None}
        summary[k] = s
    listed = cov[cov["listed"] == True]  # noqa: E712
    with_rows = cov[cov["rows"] > 0]
    L = [f"# Hyperliquid's funding and mark premium per member — source audit (decision BJ2; `ft2 hl audit`)\n",
         f"generated {today:%Y-%m-%d %H:%M} UTC · {path} · {bn_path} · counted over {a0.date()} → {end.date()} at each settlement hour\n",
         "\nWords: the venue settles funding every hour (every 8 hours before 2023-06-25) and publishes, at the settlement, the hour's *premium* (its mark over its "
         "oracle, the hour's sample average) and the *funding rate* paid (the premium plus the interest term, clamped). A row stamped T describes the hour ending at T "
         "and is read at `ts_known` = T (it appears a lag after T — `lag_s`). `hl_prem` and `hl_fund` are those two in bps; `hl_prem24` the trailing-day mean "
         f"premium, `hl_fund24` the trailing-day funding paid ({DAY} rows, ≥ {MIN_DAY} present); `bn_prem` Binance's own premium index bar of the same hour "
         "(the archive's 1h premiumIndexKlines, the close; `bn_prem_avg` the bar's open-high-low-close mean) and `bn_prem24` its trailing-day mean; `gap24` = "
         "`hl_prem24` − `bn_prem24`, the cross-venue lean. Each *deviation* is cb_ext's DEV form — the quantity minus its trailing 30-day mean, over the trailing "
         f"30-day sd, ≥ 360 rows present. `cb_dev` is the same form on AX1's adjusted Coinbase premium (`{premium}`), `tb24_dev` / `sr24_dev` R68's two from BH1's "
         f"audit (`{spot_ratios}`); the kept names are R62's (`{kept_csv.name}`). Nothing is priced here; no fold is read.\n",
         "\n## Symbols, extent, the hourly regime, completeness, cover (rows)\n", cov.round(4).to_markdown(index=False), "\n",
         f"\n- {len(listed)} of {len(sf)} perpetuals have a coin on the venue ({int(listed['delisted'].sum()) if len(listed) else 0} delisted there), {len(with_rows)} with live rows in the window; "
         f"{int((cov['frozen_rows'] > 0).sum())} names carry FROZEN rows (a run of ≥ {FROZEN_RUN} settlements at a premium of exactly 0 — a delisted market still emitting; "
         f"{int(cov['frozen_rows'].sum()):,} rows in all), read as absent everywhere here; `last` is the last live row.\n",
         "\n## The stamp check — the venue's hour premium against Binance's premium bar by lag (a positive lag: Binance's bar that many hours EARLIER)\n",
         sc.round(3).to_markdown(index=False) if len(sc) else "(no overlap)", "\n",
         (f"\n- Rule: when the stamps agree the best lag is 0 on nearly every name. Here: best lag 0 on {int((sc['best_lag'] == 0).sum())} of {len(sc)} names; the lag-0 correlation "
          f"median {sc['corr_lag0'].median():.3f}; the level gap (venue − Binance) median {sc['level_hl_minus_bn_bps'].median():.2f} bps.\n") if len(sc) else "",
         "\n## The funding check — Binance's settled rate against the venue's settlements summed over the same period\n",
         fc.round(4).to_markdown(index=False) if len(fc) else "(no overlap with funding_archive)", "\n",
         (f"\n- Pooled: correlation median {fc['corr'].median():.3f} (p10 {fc['corr'].quantile(0.1):.3f}, p90 {fc['corr'].quantile(0.9):.3f}); the venue's mean funding "
          f"{fc['hl_mean_pct_yr'].median():.1f} % a year against Binance's {fc['bn_mean_pct_yr'].median():.1f} (medians across names).\n") if len(fc) else "",
         "\n## The members' cover of their own hours, per block — the breadth R62's frame would have\n", blocks.to_markdown(index=False) if len(blocks) else "(no member rows)", "\n",
         f"\nA member counts in `cover_ge_{COVER_OK:g}` when ≥ {COVER_OK:.0%} of the hours of the block it is a member of have a settlement row.\n",
         "\n## The quantities per name\n", st.round(4).to_markdown(index=False) if len(st) else "(no quantities)", "\n",
         "\n## Summary on R62's kept names\n", "```\n" + json.dumps(summary, indent=1) + "\n```\n",
         f"\n- The questions: does each quantity VARY within a name (`dev_sd`, its persistence `dev_acf_24h`); is it Binance's own premium again (|corr| with "
         f"`bn_prem_dev` ≥ {CORR_SAME:g} — R20 / R21's quantity on another crowd), the Coinbase deviation again (`cb_dev`), or R68's spot flow again (`tb24_dev`, `sr24_dev`)?\n",
         "\n## Across names\n"]
    for k, tag in QUANTITIES.items():
        o = off[k]
        L.append(f"- {tag} (`{k}_dev`): mean off-diagonal correlation {o.mean():.3f} (min {o.min():.3f}, max {o.max():.3f}) on the hours both names have\n" if len(o) else f"- {tag}: fewer than two names\n")
    for k in ("hl_prem", "hl_fund", "bn_prem"):
        h = hod[k]
        L.append(f"- {k} by hour of day (UTC), averaged over names (bps): " + ", ".join(f"{hh:02d}h {val:+.2f}" for hh, val in h.items()) + "\n" if len(h) else "")
    L += [f"\n## Pooled — the crowd's lean\n- the venue's premium's cross-name mean per hour (bps): median {pooled.median():.2f}, p10 {pooled.quantile(0.1):.2f}, p90 {pooled.quantile(0.9):.2f}, sd {pooled.std():.2f}, acf 24 h {_acf(pooled, 24):.3f}\n",
          f"- Binance's premium's cross-name mean per hour (bps): median {pooled_bn.median():.2f}, p10 {pooled_bn.quantile(0.1):.2f}, p90 {pooled_bn.quantile(0.9):.2f}, sd {pooled_bn.std():.2f}, acf 24 h {_acf(pooled_bn, 24):.3f}; "
          f"the two means' correlation {_corr(pooled, pooled_bn)[0]:.3f}\n"]
    row = (f"| **hl_funding_1h** (Hyperliquid's hourly funding and mark premium per name, the twelve's and the screener's members' coins; decision BJ2) | `ft2 hl fetch`, raw `data/raw/external/hyperliquid/` | "
           + f"{len(listed)} of {len(sf)} perpetuals with a coin, {len(with_rows)} with rows; per block "
           + "; ".join(f"{b['block']} {b[f'cover_ge_{COVER_OK:g}']} of {b['members']}" for _, b in blocks.iterrows())
           + f" | `{path}`; a row is read at `ts_known` = its settlement hour (it appears `lag_s` after) |")
    L += ["\n## DATA.md row\n", "\n" + row + "\n"]
    txt = "".join(x if x.endswith("\n") else x + "\n" for x in L)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt)
    (out.parent / "hl_audit.json").write_text(json.dumps({"cover": cov.to_dict("records"), "stats": st.to_dict("records"), "stamp": sc.to_dict("records"),
                                                         "funding": fc.to_dict("records"), "blocks": blocks.to_dict("records"), "summary": summary,
                                                         "corr_mean": {k: (float(v.mean()) if len(v) else None) for k, v in off.items()},
                                                         "hod": {k: {int(h): float(val) for h, val in v.items()} for k, v in hod.items()},
                                                         "pooled": {"median": float(pooled.median()), "sd": float(pooled.std()), "acf_24h": _acf(pooled, 24), "corr_bn": _corr(pooled, pooled_bn)[0]},
                                                         "window": [str(a0), str(end)]}, indent=1, default=str))
    keys = list(QUANTITIES) + [k + "_dev" for k in QUANTITIES] + ["bn_prem_avg"]
    cols = G["hl_prem"].columns
    long = pd.concat([G[k].stack(future_stack=True).rename(k) for k in keys] + [O[n].reindex(columns=cols).stack(future_stack=True).rename(n) for n in O if n not in keys], axis=1)
    long = long.dropna(how="all").reset_index().rename(columns={"level_0": "ts_known", "level_1": "symbol"})
    long.to_parquet(out.parent / "hl_quantities.parquet", index=False)
    return txt


def main(action: str, start: str = START, end: str | None = None, only: list[str] | None = None) -> None:
    if action == "symbols":
        print(symbols().to_string())
    elif action == "fetch":
        print(json.dumps(fetch(start, end, only=only), indent=1))
    elif action == "bnprem":
        print(json.dumps(bnprem_fetch(start, end, only=only), indent=1))
        print(json.dumps(bnprem_ingest(only=only), indent=1))
    elif action == "ingest":
        print(json.dumps(ingest(only=only), indent=1))
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"hl: unknown action {action}")
