"""ft2 index (P8 B3, PLAN §9 #7): the Dukascopy daily one-minute candle files decoded, the padded minutes dropped, the inventory's hours."""
import lzma
import os
import struct
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ft2 import index


def _day_file(day: date, base: float, traded: set[int], seed: int = 0) -> bytes:
    """A feed file: 1,440 records (sec, open, close, low, high × 1000, volume); a minute not in `traded` repeats the last close at zero volume."""
    rng = np.random.default_rng(seed)
    out, last = [], base
    for m in range(1440):
        if m in traded:
            o = last
            c = o * (1 + rng.normal(0, 2e-4))
            hi, lo = max(o, c) * (1 + 1e-4), min(o, c) * (1 - 1e-4)
            out.append(struct.pack(">5if", m * 60, round(o * 1000), round(c * 1000), round(lo * 1000), round(hi * 1000), float(rng.uniform(0.001, 0.01))))
            last = c
        else:
            v = round(last * 1000)
            out.append(struct.pack(">5if", m * 60, v, v, v, v, 0.0))
    return lzma.compress(b"".join(out))


WEEKDAY = {m for m in range(1440) if not 21 * 60 <= m < 22 * 60}      # the break 21:00–22:00 UTC


def _plant(tmp_path, days=10):
    os.chdir(tmp_path)
    d0 = date(2024, 6, 10)                                            # a Monday
    for sym, instr in index.INSTRUMENTS.items():
        base = 5400.0 if sym == "US500" else 19000.0
        for i in range(days):
            d = d0 + timedelta(days=i)
            wd = d.weekday()
            traded = set() if wd == 5 else ({m for m in range(22 * 60, 1440)} if wd == 6 else WEEKDAY)
            p = index.path(instr, d)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(_day_file(d, base, traded, seed=i))
            p.with_suffix(".bi5.ok").touch()
    return d0


def test_decode_reads_the_feeds_records_and_rejects_what_is_not_a_day():
    d = date(2024, 6, 12)
    df = index.decode(_day_file(d, 5400.0, WEEKDAY), d)
    assert len(df) == 1440 and df["ts"].iloc[0] == pd.Timestamp("2024-06-12", tz="UTC") and df["ts"].iloc[-1] == pd.Timestamp("2024-06-12 23:59", tz="UTC")
    assert (df["high"] >= df[["open", "close"]].max(axis=1) - 1e-9).all() and (df["low"] <= df[["open", "close"]].min(axis=1) + 1e-9).all()
    assert 5300 < df["close"].mean() < 5500 and (df.loc[df["ts"].dt.hour == 21, "volume"] == 0).all()
    with pytest.raises(Exception):
        index.decode(b"<html><body><h1>503 Service Unavailable</h1></body></html>", d)
    with pytest.raises(ValueError):
        index.decode(lzma.compress(_day_file(d, 5400.0, WEEKDAY)[:10]), d)


def test_ingest_drops_the_padded_minutes_and_keeps_the_path_month_zero_based(tmp_path):
    d0 = _plant(tmp_path)
    assert index.path("USA500IDXUSD", date(2024, 1, 5)).as_posix().endswith("USA500IDXUSD/2024/00/05/BID_candles_min_1.bi5")
    assert index.url("USA500IDXUSD", date(2024, 12, 31)).endswith("/USA500IDXUSD/2024/11/31/BID_candles_min_1.bi5")
    r = index.ingest()
    x = index.load()
    assert r["rows_in"] == 2 * 10 * 1440 and r["rows_out"] == len(x) and set(x["symbol"].cat.categories) == {"US100", "US500"}
    g = x[x["symbol"] == "US500"]
    per_day = g.groupby(g["ts"].dt.date).size()
    assert per_day[d0] == 1380 and d0 + timedelta(days=5) not in per_day.index and per_day[d0 + timedelta(days=6)] == 120   # Mon full, Sat absent, Sun from 22:00
    assert (g["volume"] > 0).all() and g["ts"].is_monotonic_increasing and not g.duplicated(["ts"]).any()
    assert x["ts"].min() == pd.Timestamp("2024-06-10", tz="UTC")


def test_inventory_reads_the_hours_and_the_gaps(tmp_path):
    _plant(tmp_path, days=14)
    index.ingest()
    md = index.inventory(fetch_live=False)
    assert "days_fetched" in md and "| Sat" in md and "not fetched" in md
    lines = [l for l in md.splitlines() if l.startswith("| Wed") or l.startswith("| Sat") or l.startswith("| Sun")]
    wed, sat, sun = (np.array([float(v) for v in l.split("|")[2:-1]]) for l in lines)
    assert (wed[:21] == 60).all() and wed[21] == 0 and (wed[22:] == 60).all() and (sat == 0).all() and (sun[:22] == 0).all() and (sun[22:] == 60).all()
    assert "0 gaps" in md
