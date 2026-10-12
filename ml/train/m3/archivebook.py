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

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

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


def add_parser(sub) -> None:
    ap = sub.add_parser("archivebook", help="fetch Binance's public bookDepth archive, whole history, "
                        "one parquet per pair at 30 s (the training-side source for a depth-band feature)")
    ap.add_argument("--pairs", default=",".join(L.PAIRS))
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--threads", type=int, default=16)
    ap.set_defaults(fn=lambda a: fetch(a.pairs.split(","), a.start, a.end, threads=a.threads) or 0)
