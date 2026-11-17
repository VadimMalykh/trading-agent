"""The all-names quote recorder (`scripts/quotes_live.py`, decision CW2) on planted bodies, no network: every changed quote is written
once with the poll's own stamp, an unchanged one is skipped, a short body or a failed fetch is logged and writes nothing, a restart
appends a readable member to the day's file, and a poll after midnight opens the next day's file."""
import gzip
import importlib.util
import pathlib

import pytest


@pytest.fixture()
def ql(tmp_path, monkeypatch):
    monkeypatch.setenv("FT2_ROOT", str(tmp_path))
    monkeypatch.setenv("FT2_QUOTES_MIN_SYMBOLS", "2")
    spec = importlib.util.spec_from_file_location("quotes_live", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "quotes_live.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def q(sym, bid, ask, t):
    return {"symbol": sym, "bidPrice": bid, "bidQty": "1.5", "askPrice": ask, "askQty": "2.5", "time": t, "lastUpdateId": 1}


T0 = 1_794_873_570_000          # 2026-11-16 23:59:30 UTC


def read(p):
    return gzip.open(p, "rt").read().splitlines()


def test_changed_quotes_once_unchanged_skipped_failures_logged_days_split(ql, tmp_path):
    last, day, log = {}, ql.DayFile(), ql.HourLog()
    a = [q("AAAUSDT", "1.00", "1.01", T0 - 5), q("BBBUSDT", "0.0500", "0.0501", T0 - 900_000)]
    assert ql.poll(T0, last, day, log, lambda: a) == 2
    b = [q("AAAUSDT", "1.02", "1.03", T0 + 29_000), q("BBBUSDT", "0.0500", "0.0501", T0 - 900_000)]      # BBB has not traded: same stamp
    assert ql.poll(T0 + 30_000, last, day, log, lambda: b) == 1                                             # 00:00:00 the next day
    assert ql.poll(T0 + 60_000, last, day, log, lambda: [q("AAAUSDT", "9", "9", 1)]) == 0                   # a short body
    def boom():
        raise OSError("down")
    assert ql.poll(T0 + 90_000, last, day, log, boom) == 0
    log.flush(); day.close()

    raw = tmp_path / "data" / "raw" / "external" / "binance_quotes_live"
    d1, d2 = read(raw / "quotes_20261116.csv.gz"), read(raw / "quotes_20261117.csv.gz")
    assert d1 == [ql.HEADER.strip(), f"{T0},AAAUSDT,1.00,1.5,1.01,2.5,{T0 - 5}",
                  f"{T0},BBBUSDT,0.0500,1.5,0.0501,2.5,{T0 - 900_000}"]
    assert d2 == [ql.HEADER.strip(), f"{T0 + 30_000},AAAUSDT,1.02,1.5,1.03,2.5,{T0 + 29_000}"]
    rows = (tmp_path / "output" / "quotes_live" / "poll_log.csv").read_text().splitlines()
    assert rows[0] == ql.LOG_HEADER.strip()
    assert rows[1] == "2026-11-16 23,1,0,2,"
    assert rows[2].startswith("2026-11-17 00,1,2,1,OSError('down')")


def test_a_restart_appends_a_member_and_writes_the_quote_again(ql, tmp_path):
    a = [q("AAAUSDT", "1.00", "1.01", T0 - 5), q("BBBUSDT", "2", "3", T0 - 7)]
    for _ in range(2):                                  # two processes: the second knows nothing of the first's `last`
        day = ql.DayFile()
        ql.poll(T0, {}, day, ql.HourLog(), lambda: a)
        day.close()
    d = read(tmp_path / "data" / "raw" / "external" / "binance_quotes_live" / "quotes_20261116.csv.gz")
    assert d[0] == ql.HEADER.strip() and len(d) == 5 and d.count(ql.HEADER.strip()) == 1


def test_a_flushed_stream_is_readable_before_it_is_closed(ql, tmp_path):
    day = ql.DayFile()
    ql.poll(T0, {}, day, ql.HourLog(), lambda: [q("AAAUSDT", "1", "2", 5), q("BBBUSDT", "2", "3", 7)])
    p = tmp_path / "data" / "raw" / "external" / "binance_quotes_live" / "quotes_20261116.csv.gz"
    import zlib
    txt = zlib.decompressobj(31).decompress(p.read_bytes()).decode()      # the stream is still open: no trailer yet
    assert txt.splitlines()[1].startswith(f"{T0},AAAUSDT,1,1.5,2,2.5,5")
    day.close()
