"""The archive's depth bands, whole history — the training-side source for a depth-band feature.

Binance's public bookDepth archive (daily files, 30 s rows, quantity within ±0.2 / ±1 / ±2 / ±3
/ ±4 / ±5 % of the mid per side) runs from 2024-05-16/17 on the 2022-listed pairs, 2024-09-16
on 1000PEPE, 2024-12-04 on WLD, 2025-05-30 on HYPE. BOOK_WAVE2_PLAN §L1 measured it to be the
same number the collector's ladder sums (median ratio 1.000), with stale stretches the archive
does not flag. This module fetches it all, one parquet per pair at the archive's own 30 s
resolution (`output/archive/bookdepth/<SYM>.parquet`), sha256-verified and cached as X8's
fetcher does. Nothing here decides anything: the stale-row rule, the 5m reduction and the
feature columns belong to the registration (NEXT_TRAINING_PLAN §2) and are built after it.
"""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import ladderspan as L

OUT_DIR = "output/archive/bookdepth"
LISTED = {"1000PEPEUSDT": "2024-09-16", "WLDUSDT": "2024-12-04", "HYPEUSDT": "2025-05-30"}
DEFAULT_START = "2024-05-16"


def fetch(pairs: list[str], start: str, end: str, cache: str = L.ARCHIVE_CACHE,
          out_dir: str = OUT_DIR, threads: int = 16) -> None:
    os.makedirs(cache, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    d_end = date.fromisoformat(end)
    for sym in pairs:
        d0 = date.fromisoformat(max(start, LISTED.get(sym, start)))
        days = [d0 + timedelta(days=i) for i in range((d_end - d0).days + 1)]
        t0 = time.time()
        counts = {"ok": 0, "cached": 0, "missing": 0}
        with ThreadPoolExecutor(max_workers=threads) as ex:
            for _, _, st in ex.map(lambda d: L._fetch_day(sym, d, cache), days):
                counts[st] += 1
        frames = []
        for d in days:
            p = os.path.join(cache, os.path.basename(L._key(sym, d)))
            if os.path.exists(p + ".ok"):
                frames.append(L._parse_zip(p, sym))
        if not frames:
            print(f"{sym}: nothing downloaded")
            continue
        df = pd.concat(frames, ignore_index=True)
        n0 = len(df)
        df = df.drop_duplicates(subset=["ts"], keep="last").sort_values("ts").reset_index(drop=True)
        path = os.path.join(out_dir, f"{sym}.parquet")
        df.to_parquet(path, index=False)
        gaps = df["ts"].diff().dt.total_seconds()
        print(f"{sym:<14} {len(days):>5} days  {counts}  rows {len(df):,} (dups {n0 - len(df)})  "
              f"{str(df['ts'].min())[:10]} .. {str(df['ts'].max())[:10]}  gap p50 {gaps.median():.0f}s  "
              f"gaps > 5 min: {int((gaps > 300).sum())}  {os.path.getsize(path) / 1e6:.0f} MB  {time.time() - t0:.0f}s",
              flush=True)


# --------------------------------------------------------------------------------------
# reduce — the stale rule and the 5m grid (X8c prerequisite 2)
# --------------------------------------------------------------------------------------

BAND_TAGS = {"0.2": "0_2", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5"}
BAND_BPS = {"0_2": 20.0, "1": 100.0, "2": 200.0, "3": 300.0, "4": 400.0, "5": 500.0}   # width, bps
BAND_LABEL = {"0_2": "±0.2 %", "1": "±1 %", "2": "±2 %", "3": "±3 %", "4": "±4 %", "5": "±5 %"}
REDUCED_OUT = "output/archive/bookdepth_5m.parquet"
GRID_MIN = 5
MAX_AGE_MIN = 5.0


def to_collector_columns(df: pd.DataFrame) -> pd.DataFrame:
    """d_bid_0.2 … d_ask_5 -> bid_band_0_2 … ask_band_5, the collector's names."""
    ren = {f"d_{side}_{a}": f"{side}_band_{b}" for a, b in BAND_TAGS.items() for side in ("bid", "ask")}
    return df.rename(columns={k: v for k, v in ren.items() if k in df.columns})


def stale_mask(df: pd.DataFrame) -> np.ndarray:
    """The registered rule: a row whose six values on the bid side, or on the ask side, all
    equal the previous row's on that side (db.depth_stale_mask, same rule, archive names)."""
    from data.db import depth_stale_mask
    return depth_stale_mask(to_collector_columns(df))


def reduce_pair(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop stale rows, then keep, for every 5-minute grid point, the last row at or before
    it within MAX_AGE_MIN — the row keeps its own timestamp so the loader's age logic sees the
    archive exactly as it sees the collector."""
    df = df.sort_values("ts").reset_index(drop=True)
    st = stale_mask(df)
    kept = df[~st].reset_index(drop=True)
    t0 = kept["ts"].min().floor(f"{GRID_MIN}min")
    t1 = kept["ts"].max().ceil(f"{GRID_MIN}min")
    grid = pd.date_range(t0, t1, freq=f"{GRID_MIN}min", tz="UTC")
    idx = np.searchsorted(kept["ts"].to_numpy(), grid.to_numpy(), side="right") - 1
    ok = idx >= 0
    rows = kept.iloc[idx[ok]].copy()
    age = (grid[ok].tz_convert(None).to_numpy() - rows["ts"].dt.tz_convert(None).to_numpy()) \
        / np.timedelta64(1, "m")
    rows = rows[age <= MAX_AGE_MIN]
    rows = rows.drop_duplicates(subset=["ts"]).reset_index(drop=True)
    stats = {"rows": len(df), "stale": int(st.sum()), "stale_pct": float(st.mean()) if len(df) else 0.0,
             "grid": int(ok.sum()), "kept": len(rows)}
    return to_collector_columns(rows), stats


def reduce(pairs: list[str], in_dir: str = OUT_DIR, out: str = REDUCED_OUT) -> str:
    frames = []
    print(f"{'symbol':<14}{'rows':>10}{'stale':>9}{'stale%':>8}{'5m rows':>9}  first .. last")
    for sym in pairs:
        p = os.path.join(in_dir, f"{sym}.parquet")
        if not os.path.exists(p):
            print(f"{sym:<14} missing {p}")
            continue
        df = pd.read_parquet(p)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        red, st = reduce_pair(df)
        red = red.drop(columns=["symbol"], errors="ignore")  # the per-pair parquet carries it already
        red.insert(0, "symbol", sym)
        frames.append(red)
        print(f"{sym:<14}{st['rows']:>10,}{st['stale']:>9,}{st['stale_pct']:>8.2%}{st['kept']:>9,}  "
              f"{str(red['ts'].min())[:16]} .. {str(red['ts'].max())[:16]}")
        # X8c′ lesson (2026-10-17): a band may be absent for most of the history (Binance added
        # the ±0.2 % band on 2026-01-15); print each band's first row and coverage so a feature
        # registered on it is read against the history it actually has.
        for tag in BAND_TAGS.values():
            cols = [f"bid_band_{tag}", f"ask_band_{tag}"]
            if not all(c in red.columns for c in cols):
                print(f"{'':<14}  band {tag:<4} absent from the archive")
                continue
            has = red[cols].notna().all(axis=1)
            first = str(red.loc[has, "ts"].min())[:16] if has.any() else "—"
            print(f"{'':<14}  band {tag:<4} rows {int(has.sum()):>9,} ({has.mean():6.1%})  first {first}")
    if not frames:
        raise SystemExit("reduce: nothing to reduce")
    allr = pd.concat(frames, ignore_index=True).sort_values(["symbol", "ts"]).reset_index(drop=True)
    tmp = out + ".tmp"
    allr.to_parquet(tmp, index=False)
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()[:8]
    root, ext = os.path.splitext(out)
    final = f"{root}_{sha}{ext}"
    os.replace(tmp, final)
    print(f"\nwrote {final}  sha8={sha}  rows {len(allr):,}  ({os.path.getsize(final) / 1e6:.1f} MB)")
    return final


# --------------------------------------------------------------------------------------
# check — X8c prerequisite 1: the archive vs the collector's live band columns
# --------------------------------------------------------------------------------------

CHECK_TOL_S = 15.0
CHECK_MED_MAX, CHECK_P99_MAX = 0.02, 0.10
CHECK_MIN_MATCHED = 500


SERIES_OFFSETS_S = range(-30, 31, 2)
SERIES_TOL_S = 5.0
SERIES_CENTER = (0.98, 1.02)
SERIES_TAIL_MULT = 1.5
SERIES_MIN_N = 2000
SERIES_SELF_DT = (5.0, 15.0)


def _prep_pair(c: pd.DataFrame, s: str, in_dir: str, tol: pd.Timedelta):
    """Archive rows over the collector's window and the collector's rows for one pair, stale rows
    dropped on both sides (the registered rule); None when either side is empty."""
    from data.db import depth_stale_mask
    p = os.path.join(in_dir, f"{s}.parquet")
    if not os.path.exists(p):
        return None, None
    lo, hi = c["ts"].min(), c["ts"].max()
    a = pd.read_parquet(p)
    a["ts"] = pd.to_datetime(a["ts"], utc=True)
    a = a[(a["ts"] >= lo - tol) & (a["ts"] <= hi + tol)].sort_values("ts").reset_index(drop=True)
    a = to_collector_columns(a)
    a = a[~depth_stale_mask(a)].reset_index(drop=True)
    g = c[c["symbol"] == s].sort_values("ts").reset_index(drop=True)
    g = g[~depth_stale_mask(g)].reset_index(drop=True)
    return a, g


def check_series(collector_csv: str, in_dir: str = OUT_DIR, pairs: list[str] | None = None,
                 band: str = "0_2") -> int:
    """X8c′ prerequisite 1′ (NEXT_TRAINING_PLAN §2 X8c′): the identity as a comparison of two
    samplings of one series. Per pair and side at the archive's best clock offset δ* (scan, 5 s
    tolerance): (1) median c/a within SERIES_CENTER; (2) median |a-c|/c (D) ≤ the median of the
    band's own change between the collector's rows 5–15 s apart (S); (3) p99(D) ≤ 1.5 × p99(S);
    n(D) ≥ 2,000. FAIL on any pair-side → exit 2."""
    from data.features import DEPTH_BANDS
    c = pd.read_csv(collector_csv)
    c["ts"] = pd.to_datetime(c["ts"], utc=True)
    c = c[(c["bid_reach_bps"] >= BAND_BPS[band]) & (c["ask_reach_bps"] >= BAND_BPS[band])
          & (c[f"bid_band_{band}"] > 0) & (c[f"ask_band_{band}"] > 0)].reset_index(drop=True)
    pairs = pairs or sorted(DEPTH_BANDS[band][1])
    tol = pd.Timedelta(seconds=SERIES_TOL_S)
    wide = pd.Timedelta(seconds=max(abs(o) for o in SERIES_OFFSETS_S) + SERIES_TOL_S)
    print(f"archive bookDepth vs collector band columns, series-shaped (X8c′ bar), band {BAND_LABEL[band]}: overlap "
          f"{c['ts'].min():%Y-%m-%d %H:%M} -> {c['ts'].max():%Y-%m-%d %H:%M} UTC; archive clock shifted by δ* "
          f"(scan {min(SERIES_OFFSETS_S):+d}..{max(SERIES_OFFSETS_S):+d} s, nearest row within {SERIES_TOL_S:.0f} s); "
          f"stale rows removed on both sides; served-depth pairs only.")
    print(f"bars per pair and side: centre median c/a in [{SERIES_CENTER[0]}, {SERIES_CENTER[1]}]; median D <= median S; "
          f"p99 D <= {SERIES_TAIL_MULT} x p99 S; n >= {SERIES_MIN_N}  (D = |a-c|/c at δ*, S = the band's own change over "
          f"{SERIES_SELF_DT[0]:.0f}-{SERIES_SELF_DT[1]:.0f} s)")
    print(f"{'symbol':<14}{'side':<5}{'δ*':>4}{'n':>7}{'centre':>8}{'med D':>8}{'med S':>8}{'p99 D':>9}{'p99 S':>9}{'max D':>9}  verdict")
    fails = 0
    offsets = []
    for s in pairs:
        a, g = _prep_pair(c, s, in_dir, wide)
        if a is None or g is None or a.empty or g.empty:
            print(f"{s:<14}{'—':<5}{'—':>4}{0:>7}  FAIL (no archive parquet / no overlap rows)")
            fails += 1
            continue
        gg = g[["ts", f"bid_band_{band}", f"ask_band_{band}"]].rename(columns={f"bid_band_{band}": "c_bid", f"ask_band_{band}": "c_ask"})
        # δ*: the shift of the archive clock minimising the median relative difference on the bid side
        best = None
        for off in SERIES_OFFSETS_S:
            aa = a[["ts", f"bid_band_{band}"]].copy()
            aa["ts"] = aa["ts"] + pd.Timedelta(seconds=off)
            mm = pd.merge_asof(aa, gg[["ts", "c_bid"]], on="ts", direction="nearest", tolerance=tol).dropna(subset=["c_bid"])
            if mm.empty:
                continue
            med = ((mm[f"bid_band_{band}"] - mm["c_bid"]).abs() / mm["c_bid"]).median()
            if best is None or med < best[1]:
                best = (off, med)
        if best is None:
            print(f"{s:<14}{'—':<5}{'—':>4}{0:>7}  FAIL (no match at any offset)")
            fails += 1
            continue
        d_star = best[0]
        offsets.append(d_star)
        aa = a[["ts", f"bid_band_{band}", f"ask_band_{band}"]].copy()
        aa["ts"] = aa["ts"] + pd.Timedelta(seconds=d_star)
        m = pd.merge_asof(aa, gg, on="ts", direction="nearest", tolerance=tol).dropna(subset=["c_bid"])
        gd = g["ts"].diff().dt.total_seconds()
        for side in ("bid", "ask"):
            D = ((m[f"{side}_band_{band}"] - m[f"c_{side}"]).abs() / m[f"c_{side}"]).to_numpy(np.float64)
            centre = (m[f"c_{side}"] / m[f"{side}_band_{band}"]).median()
            sr = (g[f"{side}_band_{band}"].diff().abs() / g[f"{side}_band_{band}"].shift())
            S = sr[(gd >= SERIES_SELF_DT[0]) & (gd <= SERIES_SELF_DT[1])].to_numpy(np.float64)
            S = S[np.isfinite(S)]
            if len(D) < SERIES_MIN_N or len(S) < SERIES_MIN_N:
                print(f"{s:<14}{side:<5}{d_star:>+4d}{len(D):>7}  FAIL (< {SERIES_MIN_N} matched / self rows)")
                fails += 1
                continue
            medD, medS = float(np.median(D)), float(np.median(S))
            p99D, p99S = float(np.quantile(D, 0.99)), float(np.quantile(S, 0.99))
            ok = (SERIES_CENTER[0] <= centre <= SERIES_CENTER[1]) and (medD <= medS) and (p99D <= SERIES_TAIL_MULT * p99S)
            fails += 0 if ok else 1
            why = "" if ok else " (" + ", ".join(w for w, bad in (("centre", not (SERIES_CENTER[0] <= centre <= SERIES_CENTER[1])),
                                                                   ("spread", medD > medS), ("tail", p99D > SERIES_TAIL_MULT * p99S)) if bad) + ")"
            print(f"{s:<14}{side:<5}{d_star:>+4d}{len(D):>7}{centre:>8.3f}{medD:>8.2%}{medS:>8.2%}{p99D:>9.1%}{p99S:>9.1%}{D.max():>9.1%}  "
                  f"{'ok' if ok else 'FAIL'}{why}")
    if offsets:
        print(f"\nδ* across pairs: {sorted(offsets)} s (descriptive)")
    if fails:
        print(f"\nIDENTITY FAILED on {fails} pair-side(s) — X8c′ is void before it runs (NEXT_TRAINING_PLAN §2 X8c′, prerequisite 1′).")
        return 2
    print(f"\nIDENTITY PASS (series-shaped) — the archive's {BAND_LABEL[band]} band and the collector's live band are two samplings of one series; the registration on this band may be launched.")
    return 0


def check(collector_csv: str, in_dir: str = OUT_DIR, pairs: list[str] | None = None,
          band: str = "0_2") -> int:
    from data.db import depth_stale_mask
    from data.features import DEPTH_BANDS
    c = pd.read_csv(collector_csv)
    c["ts"] = pd.to_datetime(c["ts"], utc=True)
    pairs = pairs or sorted(DEPTH_BANDS[band][1])
    lo, hi = c["ts"].min(), c["ts"].max()
    print(f"archive bookDepth vs collector band columns: overlap {lo:%Y-%m-%d %H:%M} -> {hi:%Y-%m-%d %H:%M} UTC, "
          f"nearest row within {CHECK_TOL_S:.0f} s, stale rows removed on both sides, served-depth pairs only; "
          f"PASS = median < {CHECK_MED_MAX:.0%} and p99 < {CHECK_P99_MAX:.0%} on every pair and side")
    print(f"{'symbol':<14}{'side':<6}{'archive':>8}{'matched':>9}{'median':>9}{'p99':>9}{'max':>9}  verdict")
    fails = 0
    tol = pd.Timedelta(seconds=CHECK_TOL_S)
    for s in pairs:
        p = os.path.join(in_dir, f"{s}.parquet")
        if not os.path.exists(p):
            print(f"{s:<14}{'—':<6}{'—':>8}{0:>9}  FAIL (no archive parquet)")
            fails += 1
            continue
        a = pd.read_parquet(p)
        a["ts"] = pd.to_datetime(a["ts"], utc=True)
        a = a[(a["ts"] >= lo - tol) & (a["ts"] <= hi + tol)].sort_values("ts").reset_index(drop=True)
        a = to_collector_columns(a)
        a = a[~depth_stale_mask(a)].reset_index(drop=True)
        g = c[c["symbol"] == s].sort_values("ts").reset_index(drop=True)
        g = g[~depth_stale_mask(g)].reset_index(drop=True)
        if a.empty or g.empty:
            print(f"{s:<14}{'—':<6}{len(a):>8}{0:>9}  FAIL (no overlap rows)")
            fails += 1
            continue
        m = pd.merge_asof(a[["ts", f"bid_band_{band}", f"ask_band_{band}"]],
                          g[["ts", f"bid_band_{band}", f"ask_band_{band}", "bid_reach_bps", "ask_reach_bps"]]
                          .rename(columns={f"bid_band_{band}": "c_bid", f"ask_band_{band}": "c_ask"}),
                          on="ts", direction="nearest", tolerance=tol).dropna(subset=["c_bid"])
        for side in ("bid", "ask"):
            sub = m[(m[f"{side}_reach_bps"] >= BAND_BPS[band]) & (m[f"c_{side}"] > 0)]
            if len(sub) < CHECK_MIN_MATCHED:
                print(f"{s:<14}{side:<6}{len(a):>8}{len(sub):>9}{'—':>9}{'—':>9}{'—':>9}  FAIL (< {CHECK_MIN_MATCHED} matched)")
                fails += 1
                continue
            rel = (sub[f"{side}_band_{band}"] - sub[f"c_{side}"]).abs() / sub[f"c_{side}"]
            med, p99, mx = rel.median(), rel.quantile(0.99), rel.max()
            ok = med < CHECK_MED_MAX and p99 < CHECK_P99_MAX
            fails += 0 if ok else 1
            print(f"{s:<14}{side:<6}{len(a):>8}{len(sub):>9}{med:>9.3%}{p99:>9.2%}{mx:>9.1%}  {'ok' if ok else 'FAIL'}")
    if fails:
        print(f"\nIDENTITY FAILED on {fails} pair-side(s) — X8c is void before it runs (NEXT_TRAINING_PLAN §2 X8c, prerequisite 1).")
        return 2
    print(f"\nIDENTITY PASS — the archive's {BAND_LABEL[band]} band and the collector's live band are the same series; X8c may be launched.")
    return 0


def add_parser(sub) -> None:
    ap = sub.add_parser("archivebook", help="X8c: Binance's public bookDepth archive — fetch the whole history "
                        "(one parquet per pair at 30 s), reduce it to the 5m grid with the registered stale "
                        "rule (sha8-named), and run the identity acceptance against the collector's live bands")
    s2 = ap.add_subparsers(dest="job", required=False)
    f = s2.add_parser("fetch")
    f.add_argument("--pairs", default=",".join(L.PAIRS))
    f.add_argument("--start", default=DEFAULT_START)
    f.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    f.add_argument("--threads", type=int, default=16)
    r = s2.add_parser("reduce")
    r.add_argument("--pairs", default=",".join(L.PAIRS))
    r.add_argument("--out", default=REDUCED_OUT, help="the sha8 is inserted before the extension")
    c = s2.add_parser("check")
    c.add_argument("--collector", required=True, help="CSV of orderbook_snapshots band rows (scripts/archive_depth_check.sh)")
    c.add_argument("--pairs", default=None)
    c.add_argument("--series", action="store_true", help="X8c′ prerequisite 1′: the series-shaped bar (check_series)")
    c.add_argument("--band", default="0_2", choices=list(BAND_TAGS.values()),
                   help="the band checked: 0_2 (X8c/X8c′) or 1 (X8c″); served pairs and the reach floor follow")
    ap.set_defaults(fn=_main)


def _main(args) -> int:
    job = getattr(args, "job", None) or "fetch"
    if job == "fetch":
        fetch(args.pairs.split(","), args.start, args.end, threads=args.threads)
        return 0
    if job == "reduce":
        reduce(args.pairs.split(","), out=args.out)
        return 0
    fn = check_series if getattr(args, "series", False) else check
    return fn(args.collector, pairs=args.pairs.split(",") if args.pairs else None, band=args.band)
