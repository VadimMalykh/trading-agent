"""Binance public archive (data.binance.vision) — list and fetch daily/monthly files.

Coverage measured 2026-09-15 for our pairs (USDⓈ-M futures, `data/futures/um/`):
  daily/bookDepth   1-minute book depth at ± price levels     2023-01-01 → today   ~0.5 MB/day/pair
  daily/metrics     5m open interest, long/short, taker ratios  2020-09 → today      ~10 KB/day/pair
  daily/aggTrades   the full tape                               2019-12 → today      ~5 MB/day (BTC)
  monthly/fundingRate                                           2020-01 → today      tiny
  daily/bookTicker  best bid/ask — DISCONTINUED (2023-05 → 2024); bookDepth covers it
  daily/klines/<sym>/1m                                         2019-12 → today (we hold 2022-08 → from the collector)

Files land under data/raw/external/binance/<type>/<symbol>/<file>.zip, unchanged, with their
CHECKSUM verified (sha256). Fetching is resumable: existing verified files are skipped.
"""
from __future__ import annotations

import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
ROOT = Path("data/raw/external/binance")
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def list_keys(prefix: str) -> list[str]:
    """Every key under prefix (paginated; the listing returns at most 1000 keys per page)."""
    keys, marker = [], ""
    while True:
        url = f"{LIST}?delimiter=/&prefix={prefix}&marker={marker}"
        with urllib.request.urlopen(url, timeout=60) as r:
            root = ET.fromstring(r.read())
        page = [c.find(NS + "Key").text for c in root.findall(NS + "Contents")]
        keys += page
        if root.find(NS + "IsTruncated").text != "true" or not page:
            return keys
        marker = page[-1]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(key: str, dest: Path) -> str:
    """Download one archive file and its CHECKSUM; return 'ok' | 'skip' | 'bad'."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.with_suffix(".zip.ok").exists():
        return "skip"
    urllib.request.urlretrieve(DL + key, dest)
    with urllib.request.urlopen(DL + key + ".CHECKSUM", timeout=60) as r:
        want = r.read().decode().split()[0]
    if _sha256(dest) != want:
        dest.unlink(missing_ok=True)
        return "bad"
    dest.with_suffix(".zip.ok").touch()
    return "ok"


def fetch_daily(kind: str, symbol: str, start: date, end: date, sub: str = "") -> dict:
    """Daily files of `kind` (bookDepth, metrics, aggTrades, klines/<interval>) for [start, end]."""
    prefix = f"data/futures/um/daily/{kind}/{symbol}/{sub + '/' if sub else ''}"
    have = {k.rsplit("/", 1)[1]: k for k in list_keys(prefix) if k.endswith(".zip")}
    counts = {"ok": 0, "skip": 0, "bad": 0, "missing": 0}
    jobs = []
    d = start
    while d <= end:
        name = f"{symbol}-{sub or kind}-{d:%Y-%m-%d}.zip"
        key = have.get(name)
        if key is None:
            counts["missing"] += 1
        else:
            jobs.append((key, ROOT / kind / symbol / name))
        d += timedelta(days=1)
    # The archive serves small files with high latency; 8 parallel fetches keep the link busy
    # without hammering it. Each fetch is independent and idempotent (checksum + .ok marker).
    with ThreadPoolExecutor(max_workers=8) as ex:
        for status in ex.map(lambda j: _fetch(*j), jobs):
            counts[status] += 1
    return counts


def fetch_monthly(kind: str, symbol: str) -> dict:
    prefix = f"data/futures/um/monthly/{kind}/{symbol}/"
    counts = {"ok": 0, "skip": 0, "bad": 0}
    for key in list_keys(prefix):
        if key.endswith(".zip") and f"{symbol}-{kind}-" in key:
            counts[_fetch(key, ROOT / kind / symbol / key.rsplit("/", 1)[1])] += 1
    return counts


def main(kinds: list[str], symbols: list[str], start: str, end: str | None) -> None:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else date.today() - timedelta(days=2)
    for kind in kinds:
        for sym in symbols:
            if kind == "fundingRate":
                c = fetch_monthly(kind, sym)
            elif kind.startswith("klines/"):
                c = fetch_daily("klines", sym, s, e, sub=kind.split("/", 1)[1])
            else:
                c = fetch_daily(kind, sym, s, e)
            print(f"{kind:<12} {sym:<13} {c}", flush=True)
    print("archive fetch done", file=sys.stderr)
