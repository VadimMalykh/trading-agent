"""X14 (NEXT_TRAINING_PLAN §2 X14): the mark–index premium from Binance's public archive.

Three jobs, all CPU, all in `ml_analysis` (scripts/m3.sh), no torch, no DB:

  fetch   — the monthly USDⓈ-M `markPriceKlines` and `indexPriceKlines` 5m files for the
            served pairs, 2022-08 → the archive's last complete month, plus the 1m files over
            the collector overlap (monthly from 2026-07, daily after the last monthly file) for
            the identity check. sha256-verified, cached, resumable (archiveoi's shape). Written
            as four parquets under output/archive/prem/: {mark,index}_{5m,1m}.parquet
            (symbol, open_time, close).
  reduce  — ONE parquet, one row per pair-bar: (symbol, ts, mark_price, index_price,
            premium_bps) with `ts` = the bar's CLOSE (open_time + 5 min) — the registration's
            "as of the bar close" convention, stamped so that the loader's asof at the close is
            exact and no shift knob exists — and premium_bps = (mark ÷ index − 1) × 10⁴.
            Renamed to carry the first 8 hex of its own sha256: output/archive/premium_5m_<sha8>
            .parquet; that sha8 is meta["archive_prem"] and every log's `Archive premium:` line.
  check   — prerequisite 1: the archive's 1m closes against the collector's `funding_rates`
            poll (mark_price, index_price, every ~78 s since 2026-07-17) in the same minute, in
            bps: D = archive premium − collector premium, S = the archive's own change between
            consecutive 1m closes. PASS per pair iff median |D| ≤ median |S|, p99 |D| ≤ 1.5 ×
            p99 |S|, n ≥ 2,000 — X8c′'s series-shaped bar, in bps because the series crosses
            zero. FAIL on any pair → exit 2, X14 void before any run; no trimming, no re-cut.

Archive facts (checked 2026-10-20 on BTC, HYPE): both series are standard 12-column kline
files with a header row, epoch-millisecond stamps, `close` the price, `volume` 0; monthly
files exist through the previous month, daily files to about two days ago.
"""
from __future__ import annotations

import hashlib
import io
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .archiveoi import DEFAULT_PAIRS, DL, _get

OUT_DIR = "output/archive/prem"
CACHE = "output/archive/prem_zips"
REDUCED_OUT = "output/archive/premium_5m.parquet"       # sha8 inserted before .parquet
SERIES = {"mark": "markPriceKlines", "index": "indexPriceKlines"}
FETCH_FROM = "2022-08"
OVERLAP_FROM = "2026-07"                                 # the collector's first mark row is 2026-07-17
BAR_MIN = 5
BPS = 1e4

# the identity bar (X8c′'s shape, in bps)
CHECK_TAIL_MULT = 1.5
CHECK_MIN_N = 2000
CHECK_COLLECTOR_FROM = "2026-07-17"

KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


# --------------------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------------------

def _key(kind: str, sym: str, iv: str, period: str) -> str:
    scope = "daily" if len(period) == 10 else "monthly"
    return f"data/futures/um/{scope}/{kind}/{sym}/{iv}/{sym}-{iv}-{period}.zip"


def _cache_path(key: str, cache: str) -> str:
    """The two series name their zips identically (SYM-5m-YYYY-MM.zip), so the cache file
    carries the series too — without it the index files were 'cached' copies of the mark files."""
    kind = key.split("/")[4]
    return os.path.join(cache, f"{kind}-{os.path.basename(key)}")


def _fetch_one(key: str, cache: str) -> str:
    path = _cache_path(key, cache)
    if os.path.exists(path + ".ok"):
        return "cached"
    if os.path.exists(path + ".missing"):
        return "missing"
    blob = _get(DL + key)
    if blob is None:
        open(path + ".missing", "w").close()
        return "missing"
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
    return "ok"


def parse_klines(raw: bytes, sym: str) -> pd.DataFrame:
    """One kline CSV → (symbol, open_time, close). Header row optional; ms or µs stamps."""
    head = raw[:64].decode(errors="replace")
    df = pd.read_csv(io.BytesIO(raw), header=0 if head.startswith("open_time") else None)
    if df.shape[1] != len(KLINE_COLS):
        raise RuntimeError(f"{sym}: expected {len(KLINE_COLS)} kline columns, got {df.shape[1]}")
    df.columns = KLINE_COLS
    t = df["open_time"].to_numpy(np.int64)
    unit = "us" if (t.size and t.max() > 10 ** 14) else "ms"
    return pd.DataFrame({"symbol": sym, "open_time": pd.to_datetime(t, unit=unit, utc=True),
                         "close": df["close"].astype("float64")})


def _months(a: str, b: str) -> list[str]:
    return [str(p) for p in pd.period_range(pd.Period(a, "M"), pd.Period(b, "M"), freq="M")]


def _days(a: date, b: date) -> list[str]:
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def fetch(pairs: list[str], start: str = FETCH_FROM, end_month: str | None = None,
          overlap_from: str = OVERLAP_FROM, cache: str = CACHE, out_dir: str = OUT_DIR,
          threads: int = 16, through: date | None = None) -> dict[str, str]:
    """Monthly 5m for both series over [start, end_month]; 1m monthly over [overlap_from,
    end_month] and 1m daily from the day after end_month through `through` (default: two days
    ago). Returns the four parquet paths."""
    os.makedirs(cache, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    today = date.today()
    end_month = end_month or str((pd.Period(today, "M") - 1))
    through = through or (today - timedelta(days=2))
    m5 = _months(start, end_month)
    m1 = _months(overlap_from, end_month)
    d0 = (pd.Period(end_month, "M") + 1).start_time.date()
    d1 = _days(d0, through) if through >= d0 else []
    jobs = []
    for kind in SERIES.values():
        for s in pairs:
            jobs += [(kind, s, "5m", m) for m in m5]
            jobs += [(kind, s, "1m", m) for m in m1]
            jobs += [(kind, s, "1m", d) for d in d1]
    print(f"fetch: {len(pairs)} pairs x 2 series: 5m monthly {m5[0]} -> {m5[-1]} ({len(m5)}), "
          f"1m monthly {m1[0]} -> {m1[-1]} ({len(m1)}), 1m daily {d1[0] if d1 else '—'} -> {d1[-1] if d1 else '—'} ({len(d1)}); "
          f"{len(jobs)} files, cache {cache}")
    counts = {"ok": 0, "cached": 0, "missing": 0}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        for i, st in enumerate(ex.map(lambda j: _fetch_one(_key(*j), cache), jobs), 1):
            counts[st] += 1
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)} ({time.time() - t0:.0f}s) {counts}", flush=True)
    print(f"  done: {counts} in {time.time() - t0:.0f}s")

    paths = {}
    for name, kind in SERIES.items():
        for iv, periods in (("5m", m5), ("1m", m1 + d1)):
            frames = []
            for s in pairs:
                for p in periods:
                    z = _cache_path(_key(kind, s, iv, p), cache)
                    if os.path.exists(z + ".ok"):
                        with zipfile.ZipFile(z) as zz:
                            with zz.open(zz.namelist()[0]) as f:
                                frames.append(parse_klines(f.read(), s))
            if not frames:
                raise SystemExit(f"fetch: nothing downloaded for {kind} {iv}")
            df = pd.concat(frames, ignore_index=True)
            n0 = len(df)
            df = df.drop_duplicates(subset=["symbol", "open_time"], keep="last").sort_values(["symbol", "open_time"])
            df = df.reset_index(drop=True)
            path = os.path.join(out_dir, f"{name}_{iv}.parquet")
            df.to_parquet(path, index=False)
            paths[f"{name}_{iv}"] = path
            print(f"\n{kind} {iv}: {len(df):,} rows (dups {n0 - len(df)}) -> {path}")
            for s in pairs:
                g = df[df["symbol"] == s]
                if g.empty:
                    print(f"  {s:<14} NO ROWS")
                    continue
                gaps = int((g["open_time"].diff() > pd.Timedelta(minutes=int(iv[:-1]) * 2)).sum())
                print(f"  {s:<14}{len(g):>9}  {g['open_time'].min():%Y-%m-%d %H:%M} .. {g['open_time'].max():%Y-%m-%d %H:%M}  gaps > 2 bars: {gaps}")
    return paths


# --------------------------------------------------------------------------------------
# reduce
# --------------------------------------------------------------------------------------

def premium_frame(mark: pd.DataFrame, index: pd.DataFrame, bar_min: int = BAR_MIN) -> pd.DataFrame:
    """(symbol, ts, mark_price, index_price, premium_bps) on the bars BOTH series carry; `ts`
    is the bar's close. A non-positive index price drops the bar (never a division by zero)."""
    j = mark.rename(columns={"close": "mark_price"}).merge(
        index.rename(columns={"close": "index_price"}), on=["symbol", "open_time"], how="inner")
    j = j[np.isfinite(j["mark_price"]) & np.isfinite(j["index_price"]) & (j["index_price"] > 0)]
    out = pd.DataFrame({
        "symbol": j["symbol"].astype(str),
        "ts": j["open_time"] + pd.Timedelta(minutes=bar_min),
        "mark_price": j["mark_price"].astype("float64"),
        "index_price": j["index_price"].astype("float64"),
    })
    out["premium_bps"] = (out["mark_price"] / out["index_price"] - 1.0) * BPS
    return out.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)


def reduce(mark_parquet: str | None = None, index_parquet: str | None = None, out: str = REDUCED_OUT) -> str:
    mark = pd.read_parquet(mark_parquet or os.path.join(OUT_DIR, "mark_5m.parquet"))
    index = pd.read_parquet(index_parquet or os.path.join(OUT_DIR, "index_5m.parquet"))
    df = premium_frame(mark, index)
    print(f"premium 5m: {len(df):,} rows, {df['symbol'].nunique()} pairs; ts = the bar's close; "
          f"mark rows {len(mark):,}, index rows {len(index):,}, dropped {len(mark) - len(df):,} mark bars without an index bar")
    print(f"{'symbol':<14}{'rows':>9}  first             last              {'median':>8}{'p99|x|':>8}{'max|x|':>8}{'const':>7}")
    for s, g in df.groupby("symbol", sort=True):
        x = g["premium_bps"]
        print(f"{s:<14}{len(g):>9}  {g['ts'].min():%Y-%m-%d %H:%M}  {g['ts'].max():%Y-%m-%d %H:%M}  "
              f"{x.median():>8.2f}{x.abs().quantile(0.99):>8.2f}{x.abs().max():>8.1f}{'YES' if x.nunique() <= 1 else 'no':>7}")
    tmp = out + ".tmp"
    df.to_parquet(tmp, index=False)
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()[:8]
    root, ext = os.path.splitext(out)
    final = f"{root}_{sha}{ext}"
    os.replace(tmp, final)
    print(f"\nwrote {final}  sha8={sha}  ({os.path.getsize(final) / 1e6:.1f} MB)")
    print("next: upload it with scripts/fetch_archive_prem.sh (it prints the ARCHIVE_PREM value)")
    return final


# --------------------------------------------------------------------------------------
# check — prerequisite 1, the identity in bps
# --------------------------------------------------------------------------------------

def collector_premium(c: pd.DataFrame) -> pd.DataFrame:
    """The collector's (symbol, minute, premium_bps): the LAST poll in each UTC minute."""
    c = c.dropna(subset=["mark_price", "index_price"])
    c = c[c["index_price"] > 0].copy()
    # Postgres omits a zero fractional second, so the export mixes two formats (bookprep's note).
    c["ts"] = pd.to_datetime(c["ts"], utc=True, format="ISO8601")
    c["premium_bps"] = (c["mark_price"].astype(float) / c["index_price"].astype(float) - 1.0) * BPS
    c["minute"] = c["ts"].dt.floor("min")
    c = c.sort_values(["symbol", "ts"], kind="mergesort")
    return c.groupby(["symbol", "minute"], as_index=False).last()[["symbol", "minute", "premium_bps", "ts"]]


def check_pair(a: pd.DataFrame, c: pd.DataFrame) -> dict:
    """`a`: the archive's 1m premium for one pair with `minute` = the kline's open minute (its
    close is the end of that minute); `c`: collector_premium rows for the pair."""
    a = a.sort_values("minute")
    S = a["premium_bps"].diff().abs().to_numpy(np.float64)
    S = S[np.isfinite(S)]
    m = a.merge(c, on="minute", suffixes=("_a", "_c"))
    D = (m["premium_bps_a"] - m["premium_bps_c"]).abs().to_numpy(np.float64)
    D = D[np.isfinite(D)]
    n = int(len(D))
    if n < CHECK_MIN_N or len(S) < CHECK_MIN_N:
        return {"n": n, "ok": False, "why": f"< {CHECK_MIN_N} matched"}
    medD, medS = float(np.median(D)), float(np.median(S))
    p99D, p99S = float(np.quantile(D, 0.99)), float(np.quantile(S, 0.99))
    ok = (medD <= medS) and (p99D <= CHECK_TAIL_MULT * p99S)
    why = "" if ok else ", ".join(w for w, bad in (("spread", medD > medS), ("tail", p99D > CHECK_TAIL_MULT * p99S)) if bad)
    bias = float(np.median(m["premium_bps_a"] - m["premium_bps_c"]))
    return {"n": n, "ok": ok, "why": why, "medD": medD, "medS": medS, "p99D": p99D, "p99S": p99S,
            "maxD": float(D.max()), "bias": bias,
            "first": m["minute"].min(), "last": m["minute"].max()}


def check(collector_csv: str, mark_1m: str | None = None, index_1m: str | None = None,
          pairs: list[str] | None = None) -> int:
    mark = pd.read_parquet(mark_1m or os.path.join(OUT_DIR, "mark_1m.parquet"))
    index = pd.read_parquet(index_1m or os.path.join(OUT_DIR, "index_1m.parquet"))
    a = premium_frame(mark, index, bar_min=1)
    a["minute"] = a["ts"] - pd.Timedelta(minutes=1)
    c = pd.read_csv(collector_csv)
    c = collector_premium(c)
    pairs = pairs or sorted(c["symbol"].unique())
    print(f"archive 1m mark/index closes vs the collector's funding_rates poll in the same minute (the last poll of the minute), "
          f"in bps: D = archive premium − collector premium, S = the archive's own change between consecutive 1m closes. "
          f"PASS per pair iff median |D| <= median |S|, p99 |D| <= {CHECK_TAIL_MULT} x p99 |S|, n >= {CHECK_MIN_N:,}.")
    print(f"{'symbol':<14}{'n':>8}  first             last             {'med|D|':>8}{'med|S|':>8}{'p99|D|':>8}{'p99|S|':>8}{'max|D|':>8}{'bias':>7}  verdict")
    fails = 0
    for s in pairs:
        r = check_pair(a[a["symbol"] == s], c[c["symbol"] == s])
        if "medD" not in r:
            print(f"{s:<14}{r['n']:>8}  FAIL ({r['why']})")
            fails += 1
            continue
        fails += 0 if r["ok"] else 1
        print(f"{s:<14}{r['n']:>8}  {r['first']:%Y-%m-%d %H:%M}  {r['last']:%Y-%m-%d %H:%M} "
              f"{r['medD']:>8.3f}{r['medS']:>8.3f}{r['p99D']:>8.2f}{r['p99S']:>8.2f}{r['maxD']:>8.1f}{r['bias']:>+7.2f}  "
              f"{'ok' if r['ok'] else 'FAIL (' + r['why'] + ')'}")
    if fails:
        print(f"\nIDENTITY FAILED on {fails} pair(s) — X14 is void before it runs (NEXT_TRAINING_PLAN §2 X14, prerequisite 1).")
        return 2
    print("\nIDENTITY PASS — the archive's mark ÷ index − 1 and the collector's are two samplings of one series on every pair; "
          "X14 may be launched once the parquet is uploaded.")
    return 0


# --------------------------------------------------------------------------------------

def add_parser(sub) -> None:
    ap = sub.add_parser("archiveprem", help="X14: the mark–index premium from Binance's archive — fetch the "
                        "mark/index klines, reduce to one sha8-named parquet, run the identity check (exit 2 = void)")
    s2 = ap.add_subparsers(dest="job", required=True)
    f = s2.add_parser("fetch")
    f.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    f.add_argument("--start", default=FETCH_FROM, help="first month of the 5m files")
    f.add_argument("--end-month", default=None, help="last monthly file (default: last month)")
    f.add_argument("--overlap-from", default=OVERLAP_FROM, help="first month of the 1m files")
    f.add_argument("--through", default=None, help="last daily 1m file (default: two days ago)")
    f.add_argument("--threads", type=int, default=16)
    r = s2.add_parser("reduce")
    r.add_argument("--mark", default=None)
    r.add_argument("--index", default=None)
    r.add_argument("--out", default=REDUCED_OUT, help="the sha8 is inserted before the extension")
    c = s2.add_parser("check")
    c.add_argument("--collector", required=True,
                   help="CSV of funding_rates rows (symbol, ts, mark_price, index_price); scripts/archive_prem_check.sh exports it")
    c.add_argument("--pairs", default=None)
    ap.set_defaults(fn=_main)


def _main(args) -> int:
    if args.job == "fetch":
        pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
        fetch(pairs, args.start, args.end_month, args.overlap_from, threads=args.threads,
              through=date.fromisoformat(args.through) if args.through else None)
        return 0
    if args.job == "reduce":
        reduce(args.mark, args.index, args.out)
        return 0
    return check(args.collector, pairs=args.pairs.split(",") if args.pairs else None)
