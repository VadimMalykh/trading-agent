"""X8 (NEXT_TRAINING_PLAN §2): open-interest history from Binance's public archive.

Two jobs, both CPU, both in the `ml_analysis` image (scripts/m3.sh), no torch, no DB:

  fetch  — download the USDⓈ-M `metrics` daily files (data.binance.vision) for the traded
           pairs over a date range, verify each file's published sha256, and write ONE
           parquet at 5-minute cadence: (symbol, ts, open_interest, oi_value, top_ls_count,
           top_ls_sum, global_ls, taker_ratio). All seven archive columns are kept so the
           same file serves X8b (the ratios) without a second download. The file is renamed
           to carry the first 8 hex of its own sha256 — that sha is the file's identity and
           goes into every training run's meta as `archive_oi`.

  check  — the identity acceptance X8's registration requires BEFORE its first launch: over
           the overlap where the collector's own `open_interest` table exists, join every
           archive row to the nearest collector row within 5 minutes and report, per pair,
           the median and 99th-percentile relative difference and the matched count.
           PASS = median < 0.5% and p99 < 2% on every pair. A FAIL voids X8 before it runs:
           the checkpoint would be trained on one series and served on another.

Archive facts this relies on (measured 2026-09-15 on the same files): one daily zip per
symbol at data/futures/um/daily/metrics/{SYM}/{SYM}-metrics-{YYYY-MM-DD}.zip, exactly
5-minute rows, columns create_time, symbol, sum_open_interest, sum_open_interest_value,
count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio,
sum_taker_long_short_vol_ratio; the archive lags ~2 days; a few whole days are missing
(WLD and ZEC one each) and there are 4–6 gaps over 10 minutes per pair. Missing days are
reported, not fabricated.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd

DL = "https://data.binance.vision/"
KIND = "metrics"
COLS = {
    "create_time": "ts",
    "sum_open_interest": "open_interest",
    "sum_open_interest_value": "oi_value",
    "count_toptrader_long_short_ratio": "top_ls_count",
    "sum_toptrader_long_short_ratio": "top_ls_sum",
    "count_long_short_ratio": "global_ls",
    "sum_taker_long_short_vol_ratio": "taker_ratio",
}
DEFAULT_PAIRS = ["1000PEPEUSDT", "ADAUSDT", "AVAXUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT",
                 "HYPEUSDT", "LINKUSDT", "SOLUSDT", "WLDUSDT", "XRPUSDT", "ZECUSDT"]


# ---------------------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------------------

def _key(sym: str, d: date) -> str:
    return f"data/futures/um/daily/{KIND}/{sym}/{sym}-{KIND}-{d.isoformat()}.zip"


def _get(url: str, tries: int = 6) -> bytes | None:
    """GET with exponential backoff. None on a 404 (the day does not exist in the archive)."""
    delay = 1.0
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            err = e
        if i == tries - 1:
            raise RuntimeError(f"{url}: {err}")
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return None


def _fetch_day(sym: str, d: date, cache: str) -> tuple[str, date, str]:
    """Download one day's zip into the cache (skipped when its .ok marker exists).
    Returns (sym, d, status) with status in {'ok', 'cached', 'missing'}."""
    key = _key(sym, d)
    path = os.path.join(cache, os.path.basename(key))
    if os.path.exists(path + ".ok"):
        return sym, d, "cached"
    if os.path.exists(path + ".missing"):
        return sym, d, "missing"
    blob = _get(DL + key)
    if blob is None:
        open(path + ".missing", "w").close()
        return sym, d, "missing"
    chk = _get(DL + key + ".CHECKSUM")
    if chk is None:
        raise RuntimeError(f"{key}: zip exists but its .CHECKSUM does not")
    want = chk.decode().split()[0].lower()
    got = hashlib.sha256(blob).hexdigest()
    if want != got:
        raise RuntimeError(f"{key}: sha256 mismatch (published {want[:12]}…, got {got[:12]}…)")
    with open(path, "wb") as f:
        f.write(blob)
    open(path + ".ok", "w").close()
    return sym, d, "ok"


def _parse_zip(path: str, sym: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        with z.open(names[0]) as f:
            df = pd.read_csv(io.BytesIO(f.read()))
    missing = [c for c in COLS if c not in df.columns]
    if missing:
        raise RuntimeError(f"{os.path.basename(path)}: columns {missing} missing "
                           f"(have {list(df.columns)})")
    df = df[list(COLS)].rename(columns=COLS)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df.insert(0, "symbol", sym)
    return df


def fetch(pairs: list[str], start: date, end: date, cache: str, out: str,
          threads: int = 16) -> str:
    os.makedirs(cache, exist_ok=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    jobs = [(s, d) for s in pairs for d in days]
    print(f"fetch: {len(pairs)} pairs x {len(days)} days = {len(jobs)} daily files, "
          f"{start} -> {end}, cache {cache}")
    counts = {"ok": 0, "cached": 0, "missing": 0}
    missing: dict[str, list[date]] = {s: [] for s in pairs}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        for i, (s, d, st) in enumerate(ex.map(lambda j: _fetch_day(j[0], j[1], cache), jobs), 1):
            counts[st] += 1
            if st == "missing":
                missing[s].append(d)
            if i % 2000 == 0:
                print(f"  {i}/{len(jobs)} ({time.time() - t0:.0f}s) {counts}")
    print(f"  done: {counts} in {time.time() - t0:.0f}s")

    frames = []
    for s in pairs:
        for d in days:
            p = os.path.join(cache, os.path.basename(_key(s, d)))
            if os.path.exists(p + ".ok"):
                frames.append(_parse_zip(p, s))
    if not frames:
        raise SystemExit("fetch: nothing downloaded")
    df = pd.concat(frames, ignore_index=True)
    n0 = len(df)
    df = df.drop_duplicates(subset=["symbol", "ts"], keep="last").sort_values(["symbol", "ts"])
    df = df.reset_index(drop=True)
    print(f"\nrows {len(df)} (dropped {n0 - len(df)} duplicate keys)")
    print(f"{'symbol':<14}{'rows':>9}  first                 last                  "
          f"missing days (first run of the listing, then count)")
    for s in pairs:
        g = df[df["symbol"] == s]
        m = missing[s]
        # days before a pair's listing are 'missing' too; report the first present day and
        # only the holes after it
        first_present = g["ts"].min()
        holes = [d for d in m if first_present is not pd.NaT and
                 pd.Timestamp(d, tz="UTC") > first_present] if len(g) else m
        print(f"{s:<14}{len(g):>9}  {str(first_present)[:19]:<21} {str(g['ts'].max())[:19]:<21} "
              f"listed {str(first_present)[:10]}; holes after listing: {len(holes)}"
              + (f" ({', '.join(d.isoformat() for d in holes[:6])}{'…' if len(holes) > 6 else ''})"
                 if holes else ""))

    tmp = out + ".tmp"
    df.to_parquet(tmp, index=False)
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()[:8]
    root, ext = os.path.splitext(out)
    final = f"{root}_{sha}{ext}"
    os.replace(tmp, final)
    print(f"\nwrote {final}  sha8={sha}  ({os.path.getsize(final) / 1e6:.1f} MB)")
    print("next: upload it with scripts/fetch_archive_metrics.sh (it prints the ARCHIVE_OI value)")
    return final


# ---------------------------------------------------------------------------------------
# check — the identity acceptance
# ---------------------------------------------------------------------------------------

def check(parquet: str, collector_csv: str, tol_min: float = 5.0,
          med_max: float = 0.005, p99_max: float = 0.02, shift_min: float = 0.0) -> int:
    a = pd.read_parquet(parquet)[["symbol", "ts", "open_interest"]]
    a["ts"] = pd.to_datetime(a["ts"], utc=True)
    if shift_min:
        a["ts"] = a["ts"] + pd.Timedelta(minutes=shift_min)
        print(f"archive timestamps shifted by +{shift_min:g} min (db.ARCHIVE_OI_SHIFT_MIN convention)")
    c = pd.read_csv(collector_csv)
    c["ts"] = pd.to_datetime(c["ts"], utc=True)
    c = c.rename(columns={"open_interest": "oi_collector"})[["symbol", "ts", "oi_collector"]]
    c = c.dropna().sort_values("ts")
    lo, hi = c["ts"].min(), c["ts"].max()
    print(f"archive-vs-collector open interest: overlap {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M} UTC, "
          f"nearest collector row within {tol_min:g} min; PASS = median < {med_max:.1%} and "
          f"p99 < {p99_max:.0%} on every pair")
    print(f"{'symbol':<14}{'archive':>8}{'matched':>9}{'median':>9}{'p99':>9}{'max':>9}  verdict")
    fails = 0
    tol = pd.Timedelta(minutes=tol_min)
    for s in sorted(a["symbol"].unique()):
        ga = a[(a["symbol"] == s) & (a["ts"] >= lo) & (a["ts"] <= hi)].sort_values("ts")
        gc = c[c["symbol"] == s]
        if ga.empty or gc.empty:
            print(f"{s:<14}{len(ga):>8}{0:>9}{'—':>9}{'—':>9}{'—':>9}  FAIL (no overlap rows)")
            fails += 1
            continue
        m = pd.merge_asof(ga, gc, on="ts", direction="nearest", tolerance=tol)
        m = m.dropna(subset=["oi_collector"])
        m = m[m["oi_collector"] > 0]
        if len(m) < 100:
            print(f"{s:<14}{len(ga):>8}{len(m):>9}{'—':>9}{'—':>9}{'—':>9}  FAIL (< 100 matched)")
            fails += 1
            continue
        rel = (m["open_interest"] - m["oi_collector"]).abs() / m["oi_collector"]
        med, p99, mx = rel.median(), rel.quantile(0.99), rel.max()
        ok = med < med_max and p99 < p99_max
        fails += 0 if ok else 1
        print(f"{s:<14}{len(ga):>8}{len(m):>9}{med:>9.4%}{p99:>9.3%}{mx:>9.2%}  {'ok' if ok else 'FAIL'}")
    if fails:
        print(f"\nIDENTITY FAILED on {fails} pair(s) — X8 is void before it runs "
              f"(NEXT_TRAINING_PLAN §2 X8, prerequisite 4).")
        return 2
    print("\nIDENTITY PASS — the archive and the collector carry the same open-interest series; "
          "X8 may be launched.")
    return 0


# ---------------------------------------------------------------------------------------
# check_flow — X8b's identity acceptance for the three ratio series
# ---------------------------------------------------------------------------------------
# The collector's `long_short_ratios` (exchange 5m buckets since 2026-07-26) against the
# archive's same three series: global long/short ACCOUNT ratio, top-trader long/short ACCOUNT
# ratio (the collector polls topLongShortAccountRatio — the archive's `count_*` column, not
# the `sum_*` position ratio) and taker buy/sell volume ratio. Both sides carry the exchange's
# bucket timestamp, so the match is nearest-within-5-min like `check`, and the pass bar is
# the same: median relative difference < 0.5 % and p99 < 2 %, per series, per pair.

# Must equal data/db.py's ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN (not imported: this module runs in the
# torch-free, driver-free ml_analysis image). The loader's test pins the two to each other.
ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN = 5.0

FLOW_SERIES = {
    "global_ls": "global_long_short_ratio",
    "top_ls_count": "top_long_short_ratio",
    "taker_ratio": "taker_buy_sell_ratio",
}


def check_flow(parquet: str, collector_csv: str, tol_min: float = 5.0,
               med_max: float = 0.005, p99_max: float = 0.02, raw: bool = False) -> int:
    a = pd.read_parquet(parquet)[["symbol", "ts", *FLOW_SERIES]]
    a["ts"] = pd.to_datetime(a["ts"], utc=True)
    if not raw:
        # Mirror db._archive_flow: the two account series are re-labelled +5 min onto the
        # collector's (exchange) convention; the taker ratio is not. `--raw` shows the
        # unshifted comparison, which is the one that FAILED on 2026-09-24 and led here.
        acct = a[["symbol", "ts", "global_ls", "top_ls_count"]].copy()
        acct["ts"] = acct["ts"] + pd.Timedelta(minutes=ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN)
        a = acct.merge(a[["symbol", "ts", "taker_ratio"]], on=["symbol", "ts"], how="outer")
        print(f"archive account-ratio timestamps shifted by +{ARCHIVE_FLOW_ACCOUNT_SHIFT_MIN:g} min "
              f"(db._archive_flow convention); taker unshifted")
    c = pd.read_csv(collector_csv)
    c["ts"] = pd.to_datetime(c["ts"], utc=True)
    c = c.sort_values("ts")
    lo, hi = c["ts"].min(), c["ts"].max()
    print(f"archive-vs-collector flow ratios: overlap {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M} UTC, "
          f"nearest collector row within {tol_min:g} min; PASS = median < {med_max:.1%} and "
          f"p99 < {p99_max:.0%} on every series of every pair")
    print(f"{'symbol':<14}{'series':<14}{'archive':>8}{'matched':>9}{'median':>9}{'p99':>9}{'max':>9}  verdict")
    fails = 0
    tol = pd.Timedelta(minutes=tol_min)
    for s in sorted(a["symbol"].unique()):
        ga = a[(a["symbol"] == s) & (a["ts"] >= lo) & (a["ts"] <= hi)].sort_values("ts")
        gc = c[c["symbol"] == s]
        for acol, ccol in FLOW_SERIES.items():
            gcs = gc[["ts", ccol]].dropna()
            gas = ga[["ts", acol]].dropna()
            if gas.empty or gcs.empty:
                print(f"{s:<14}{acol:<14}{len(gas):>8}{0:>9}{'—':>9}{'—':>9}{'—':>9}  FAIL (no overlap rows)")
                fails += 1
                continue
            m = pd.merge_asof(gas, gcs, on="ts", direction="nearest", tolerance=tol)
            m = m.dropna(subset=[ccol])
            m = m[m[ccol] > 0]
            if len(m) < 100:
                print(f"{s:<14}{acol:<14}{len(gas):>8}{len(m):>9}{'—':>9}{'—':>9}{'—':>9}  FAIL (< 100 matched)")
                fails += 1
                continue
            rel = (m[acol] - m[ccol]).abs() / m[ccol]
            med, p99, mx = rel.median(), rel.quantile(0.99), rel.max()
            ok = med < med_max and p99 < p99_max
            fails += 0 if ok else 1
            print(f"{s:<14}{acol:<14}{len(gas):>8}{len(m):>9}{med:>9.4%}{p99:>9.3%}{mx:>9.2%}  {'ok' if ok else 'FAIL'}")
    if fails:
        print(f"\nIDENTITY FAILED on {fails} series — X8b is void before it runs "
              f"(NEXT_TRAINING_PLAN §2 X8b, its identity prerequisite).")
        return 2
    print("\nIDENTITY PASS — the archive and the collector carry the same three ratio series; "
          "X8b may be launched.")
    return 0


# ---------------------------------------------------------------------------------------

def add_parser(sub) -> None:
    ap = sub.add_parser("archiveoi", help="X8: fetch open-interest history from Binance's "
                        "public archive into one parquet, and run the archive-vs-collector "
                        "identity acceptance (NEXT_TRAINING_PLAN §2 X8, prerequisites 1 and 4)")
    s2 = ap.add_subparsers(dest="job", required=True)
    f = s2.add_parser("fetch")
    f.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    f.add_argument("--start", default="2022-08-01")
    f.add_argument("--end", default="2026-09-13", help="the pinned snapshot's date")
    f.add_argument("--cache", default="output/archive/metrics_zips")
    f.add_argument("--out", default="output/archive/metrics_um_5m.parquet",
                   help="the sha8 is inserted before the extension")
    f.add_argument("--threads", type=int, default=16)
    c = s2.add_parser("check")
    c.add_argument("--shift-min", type=float, default=0.0,
                   help="shift the archive's timestamps by this many minutes before matching "
                        "(5 = the collector's convention; db.ARCHIVE_OI_SHIFT_MIN)")
    c.add_argument("--parquet", required=True)
    c.add_argument("--collector", required=True,
                   help="CSV of the collector's open_interest rows (symbol, ts, open_interest); "
                        "scripts/archive_oi_check.sh exports it from fluxtrader-1")
    cf = s2.add_parser("check-flow", help="X8b: the same acceptance for the three ratio series")
    cf.add_argument("--raw", action="store_true",
                    help="compare the archive's account ratios UNshifted (the 2026-09-24 FAIL)")
    cf.add_argument("--parquet", required=True)
    cf.add_argument("--collector", required=True,
                    help="CSV of the collector's long_short_ratios rows (symbol, ts, "
                         "top_long_short_ratio, global_long_short_ratio, taker_buy_sell_ratio); "
                         "scripts/archive_flow_check.sh exports it from fluxtrader-1")
    ap.set_defaults(fn=_main)


def _main(args) -> int:
    if args.job == "fetch":
        pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
        fetch(pairs, date.fromisoformat(args.start), date.fromisoformat(args.end),
              args.cache, args.out, args.threads)
        return 0
    if args.job == "check-flow":
        return check_flow(args.parquet, args.collector, raw=args.raw)
    return check(args.parquet, args.collector, shift_min=args.shift_min)
