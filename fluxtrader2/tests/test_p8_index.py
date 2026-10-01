"""ft2 index (P8 B3, PLAN §9 #7): HistData's zips read with the EST clock moved to UTC; Dukascopy's daily files decoded, the padded
minutes dropped; the inventory's hours and gaps."""
import io
import lzma
import os
import struct
import zipfile
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from ft2 import index

WEEKDAY = {m for m in range(1440) if not 21 * 60 <= m < 22 * 60}      # the break 21:00–22:00 UTC


def _traded(d: date) -> set[int]:
    wd = d.weekday()
    return set() if wd == 5 else ({m for m in range(22 * 60, 1440)} if wd == 6 else WEEKDAY)


def _walk(base: float, n: int, seed: int) -> np.ndarray:
    return base * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 2e-4, n)))


# ---- HistData ------------------------------------------------------------------------------------------------------
def _last_sunday(y: int, m: int) -> date:
    d = date(y, m + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _file_offset(t_utc: datetime) -> timedelta:
    """The measured rule in UTC terms: the file clock is UTC−4 from Monday 00:00 UTC after the last Sunday of March to Monday 00:00 UTC
    after the last Sunday of October, UTC−5 otherwise."""
    a = datetime.combine(_last_sunday(t_utc.year, 3) + timedelta(days=1), datetime.min.time())
    b = datetime.combine(_last_sunday(t_utc.year, 10) + timedelta(days=1), datetime.min.time())
    return timedelta(hours=4) if a <= t_utc < b else timedelta(hours=5)


def _hist_zip(sym: str, days: list[date], seed: int = 0) -> bytes:
    """A zip as the site serves it: DAT_ASCII_<PAIR>_M1_<p>.csv (semicolon rows in EST without DST) and a status .txt."""
    rows, k = [], 0
    for d in days:
        px = _walk(5400.0 if sym == "US500" else 19000.0, 1440, seed + k)
        k += 1
        for m in sorted(_traded(d)):
            o, c = px[m - 1] if m else px[0], px[m]
            hi, lo = max(o, c) * 1.0001, min(o, c) * 0.9999
            t_utc = datetime(d.year, d.month, d.day) + timedelta(minutes=m)
            rows.append(f"{t_utc - _file_offset(t_utc):%Y%m%d %H%M%S};{o:.6f};{hi:.6f};{lo:.6f};{c:.6f};0")
    pair = index.HIST_PAIRS[sym]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"DAT_ASCII_{pair}_M1_2024.csv", "\n".join(rows) + "\n")
        z.writestr(f"DAT_ASCII_{pair}_M1_2024.txt", "HistData.com (c) 2012\nStatus Report\n")
    return buf.getvalue()


def test_hist_read_moves_the_fixed_est_clock_to_utc_and_rejects_a_bad_file():
    days = [date(2024, 6, 10) + timedelta(days=i) for i in range(8)]       # Mon … Mon
    df = index.hist_read(_hist_zip("US500", days), "US500")
    assert df["ts"].iloc[0] == pd.Timestamp("2024-06-10 00:00", tz="UTC") and df["ts"].dt.tz is not None
    per_day = df.groupby(df["ts"].dt.date).size()
    assert per_day[date(2024, 6, 10)] == 1380 and date(2024, 6, 15) not in per_day.index and per_day[date(2024, 6, 16)] == 120
    assert (df["symbol"] == "US500").all() and "volume" not in df.columns and df["ts"].is_monotonic_increasing
    with pytest.raises(Exception):
        index.hist_read(b"<html>no token</html>", "US500")
    rep = io.BytesIO()                                                 # the repeated hour at a daylight-saving change: sorted, the later pass kept, counted
    with zipfile.ZipFile(rep, "w") as z:
        z.writestr("DAT_ASCII_SPXUSD_M1_2020.csv", "20201025 140000;100;101;99;100;0\n20201025 140100;100;101;99;100.5;0\n20201025 140000;100;101;99;100.7;0\n20201025 140200;100;101;99;101;0\n")
    r = index.hist_read(rep.getvalue(), "US500")
    assert list(r["close"]) == [100.7, 100.5, 101.0] and r.attrs == {"backwards": 1, "dup_minutes": 1} and r["ts"].is_monotonic_increasing
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("DAT_ASCII_SPXUSD_M1_2024.csv", "20240610 000000;100;99;101;100;0\n")        # high below the open
    with pytest.raises(ValueError):
        index.hist_read(bad.getvalue(), "US500")


def test_hist_read_follows_the_european_clock_and_splits_the_repeated_october_hour():
    """Across the 2024 October switch (Sun 2024-10-27) and the 2025 March switch (Sun 2025-03-30): the file's clock is UTC−4 before, UTC−5
    after October's Monday 00:00 UTC; the hour 19:00–19:59 of the October Sunday appears twice in the file and maps to two different UTC hours."""
    oct_days = [date(2024, 10, 24) + timedelta(days=i) for i in range(6)]                        # Thu … Tue
    df = index.hist_read(_hist_zip("US500", oct_days), "US500")
    assert df.attrs == {"backwards": 0, "dup_minutes": 0}, df.attrs                               # in UTC nothing goes back and no minute is twice
    assert df["ts"].is_monotonic_increasing and not df["ts"].duplicated().any()
    sun = df[df["ts"].dt.date == date(2024, 10, 27)]
    assert sun["ts"].min() == pd.Timestamp("2024-10-27 22:00", tz="UTC") and len(sun) == 120     # the Sunday open at 22:00 UTC, as the synthetic calendar has it
    mon = df[df["ts"].dt.date == date(2024, 10, 28)]
    assert mon["ts"].min() == pd.Timestamp("2024-10-28 00:00", tz="UTC") and len(mon) == 1380     # every UTC minute of Monday is there once
    mar_days = [date(2025, 3, 27) + timedelta(days=i) for i in range(6)]
    df = index.hist_read(_hist_zip("US500", mar_days), "US500")
    assert df.attrs == {"backwards": 0, "dup_minutes": 0} and df["ts"].is_monotonic_increasing
    assert (df.groupby(df["ts"].dt.date).size().reindex([date(2025, 3, 31), date(2025, 4, 1)]) == 1380).all()       # the Monday after the switch is whole
    o = index.hist_offset(pd.Series(pd.to_datetime(["2025-03-30 19:59", "2025-03-30 20:00", "2025-10-26 18:59", "2025-10-26 19:00", "2025-10-26 19:59", "2025-10-26 19:00", "2025-10-26 20:00"])))
    assert list(o / pd.Timedelta("1h")) == [5, 4, 4, 4, 4, 5, 5]


def test_hist_periods_are_years_then_the_complete_months_of_this_year():
    assert index.hist_periods("2020-05-01", date(2026, 10, 1)) == ["2020", "2021", "2022", "2023", "2024", "2025", "202601", "202602", "202603", "202604", "202605", "202606", "202607", "202608", "202609"]
    assert index.hist_periods("2024-01-01", date(2024, 1, 15)) == []
    assert index.hist_path("US100", "202603").as_posix().endswith("histdata/NSXUSD/DAT_ASCII_NSXUSD_M1_202603.zip")


def test_ingest_builds_the_parquet_from_the_ok_zips_only(tmp_path):
    os.chdir(tmp_path)
    days = [date(2024, 6, 10) + timedelta(days=i) for i in range(14)]
    for sym in index.SYMBOLS:
        p = index.hist_path(sym, "2024")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_hist_zip(sym, days, seed=7))
        p.with_suffix(".zip.ok").touch()
    stray = index.hist_path("US500", "2023")
    stray.write_bytes(_hist_zip("US500", days[:2], seed=1))                  # no .ok: never read
    r = index.ingest()
    x = index.load()
    assert r["rows_out"] == len(x) and set(x["symbol"].cat.categories) == {"US100", "US500"} and x["ts"].min() == pd.Timestamp("2024-06-10", tz="UTC")
    assert len(x[x["symbol"] == "US500"]) == 10 * 1380 + 2 * 120 and list(x.columns) == ["symbol", "ts", "open", "high", "low", "close"]
    md = index.inventory(fetch_live=False)
    assert "days_fetched" not in md and "| Sat" in md and "not fetched" in md and "0 gaps" in md
    lines = [l for l in md.splitlines() if l.startswith("| Wed") or l.startswith("| Sat") or l.startswith("| Sun")]
    wed, sat, sun = (np.array([float(v) for v in l.split("|")[2:-1]]) for l in lines[:3])
    assert (wed[:21] == 60).all() and wed[21] == 0 and (wed[22:] == 60).all() and (sat == 0).all() and (sun[:22] == 0).all() and (sun[22:] == 60).all()


# ---- Dukascopy -----------------------------------------------------------------------------------------------------
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
    assert index.path("USA500IDXUSD", date(2024, 1, 5)).as_posix().endswith("USA500IDXUSD/2024/00/05/BID_candles_min_1.bi5")
    assert index.url("USA500IDXUSD", date(2024, 12, 31)).endswith("/USA500IDXUSD/2024/11/31/BID_candles_min_1.bi5")


def test_duka_ingest_drops_the_padded_minutes(tmp_path):
    os.chdir(tmp_path)
    d0 = date(2024, 6, 10)
    for sym, instr in index.INSTRUMENTS.items():
        for i in range(10):
            d = d0 + timedelta(days=i)
            p = index.path(instr, d)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(_day_file(d, 5400.0 if sym == "US500" else 19000.0, _traded(d), seed=i))
            p.with_suffix(".bi5.ok").touch()
    r = index.duka_ingest()
    x = pd.read_parquet(index.OUT_DUKA)
    g = x[x["symbol"] == "US500"]
    per_day = g.groupby(g["ts"].dt.date).size()
    assert r["rows_in"] == 2 * 10 * 1440 and per_day[d0] == 1380 and d0 + timedelta(days=5) not in per_day.index and per_day[d0 + timedelta(days=6)] == 120
    assert (g["volume"] > 0).all() and g["ts"].is_monotonic_increasing and not g.duplicated(["ts"]).any()
