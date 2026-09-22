"""The wider universe (PLAN §9 #2, registration R10): which USDⓈ-M perpetuals beyond the collector's twelve,
chosen by one rule written before any of them was looked at.

Selection (`ft2 universe`): every symbol the public archive lists under monthly klines, quoted in USDT and not
a dated contract, ranked by its MEDIAN daily quote volume over SELECT_WINDOW — the four months before F0 — and
required to have a 1d bar on every day of that window (listed before it, not delisted inside it). The top
SELECT_N are the universe. Nothing after 2022-08-18 enters the choice, so F0, F1 … are untouched by it; the
pre-history FP carries one mild bias (a pair delisted before 2022-04 cannot be in the universe). A pair that
is delisted later simply stops having bars: the harness trades the pairs present at each bar.

The chosen list is frozen in WIDE below (written by hand from output/universe_wide.md, once) so that every
later run reads the same universe; the selection command is kept so that the choice can be reproduced.
"""
from __future__ import annotations

import io
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from . import archive

SELECT_WINDOW = (date(2022, 4, 18), date(2022, 8, 17))     # the four months before F0 (2022-08-18)
SELECT_N = 40
OUT_MD = Path("output/universe_wide.md")
EXCLUDE = {"BTCDOMUSDT", "DEFIUSDT", "BTCSTUSDT", "USDCUSDT", "BTCUSDT_", "FOOTBALLUSDT", "BLUEBIRDUSDT"}   # indices / stables: not a pair in the sense used here

# Frozen 2026-09-22 from output/universe_wide.md (see that file for the ranking); the twelve are inside it where they qualify.
WIDE: list[str] = []


def candidates() -> list[str]:
    syms = archive.list_prefixes("data/futures/um/monthly/klines/")
    return sorted(s for s in syms if s.endswith("USDT") and "_" not in s and s not in EXCLUDE)


def _daily_1d(sym: str, months: list[str]) -> pd.DataFrame:
    """The symbol's 1d klines over `months`, read straight from the monthly zips (kept under ROOT/klines/<sym>/)."""
    archive.fetch_monthly("klines", sym, sub="1d", months=months)
    parts = []
    for m in months:
        f = archive.ROOT / "klines" / sym / f"{sym}-1d-{m}.zip"
        if not (f.exists() and f.with_suffix(".zip.ok").exists()):
            continue
        with zipfile.ZipFile(f) as z:
            raw = z.read(z.namelist()[0])
        df = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
        df = df[df[0].str.isdigit()]
        parts.append(pd.DataFrame({"day": pd.to_datetime(df[0].astype("int64"), unit="ms", utc=True).dt.floor("D"),
                                   "quote_volume": df[7].astype(float)}))
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["day", "quote_volume"])
    out.insert(0, "symbol", sym)
    return out


def select(n: int = SELECT_N, window: tuple[date, date] = SELECT_WINDOW) -> pd.DataFrame:
    a, b = (pd.Timestamp(d, tz="UTC") for d in window)
    months = archive.months_between(window[0], window[1])
    syms = candidates()
    print(f"{len(syms)} USDT perpetuals listed by the archive; reading 1d klines {months[0]} .. {months[-1]}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        frames = list(ex.map(lambda s: _daily_1d(s, months), syms))
    d = pd.concat(frames, ignore_index=True)
    d = d[(d["day"] >= a) & (d["day"] <= b)]
    need = (b - a).days + 1
    g = d.groupby("symbol")
    r = pd.DataFrame({"days": g.size(), "median_quote_volume": g["quote_volume"].median(), "first_day": g["day"].min()}).reset_index()
    r["complete"] = r["days"] >= need
    r = r.sort_values("median_quote_volume", ascending=False).reset_index(drop=True)
    r["rank"] = r.index + 1
    r["selected"] = False
    r.loc[r[r["complete"]].index[:n], "selected"] = True
    chosen = r[r["selected"]]["symbol"].tolist()
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    txt = "\n".join([f"# The wider universe (`ft2 universe`) — top {n} USDT perpetuals by median daily quote volume, {window[0]} → {window[1]}\n",
                     f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(syms)} candidates, {int(r['complete'].sum())} with a bar on all {need} days\n",
                     "\nWIDE = " + repr(chosen) + "\n", "\n" + r.assign(median_quote_volume=(r["median_quote_volume"] / 1e6).round(2)).rename(
                         columns={"median_quote_volume": "median_quote_volume_musd"}).to_markdown(index=False), "\n"])
    OUT_MD.write_text(txt)
    print(txt)
    return r
