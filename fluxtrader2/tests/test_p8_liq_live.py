"""The all-names liquidation recorder (`scripts/liq_live.py`, decision CX2) on planted frames, no network: the frame reader returns
whole text messages across split reads and fragments, answers a ping with a masked pong of the same payload and raises on a close
frame; every forceOrder event becomes one row with the read's own stamp, anything else none; the days split on the read's clock, a
restart appends a readable member, and the hourly log has a row for an hour without a liquidation."""
import gzip
import importlib.util
import json
import pathlib
import struct

import pytest


@pytest.fixture()
def ll(tmp_path, monkeypatch):
    monkeypatch.setenv("FT2_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location("liq_live", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "liq_live.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def srv(op, payload=b"", fin=True):          # a server frame: unmasked
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | op]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536
                                                 else bytes([127]) + struct.pack(">Q", n))
    return head + payload


def ev(sym, side, e, t, q="1.5", p="10.0"):
    return json.dumps({"e": "forceOrder", "E": e, "o": {"s": sym, "S": side, "o": "LIMIT", "f": "IOC", "q": q, "p": p, "ap": "10.1",
                                                        "X": "FILLED", "l": q, "z": q, "T": t, "ps": sym, "st": 1}})


T0 = 1_794_873_599_000          # 2026-11-16 23:59:59 UTC


def read(p):
    return gzip.open(p, "rt").read().splitlines()


def unmask(fr):                  # a client frame's (opcode, payload)
    n, i = fr[1] & 0x7F, 2
    assert fr[1] & 0x80
    m = fr[i:i + 4]
    return fr[0] & 0x0F, bytes(b ^ m[k % 4] for k, b in enumerate(fr[i + 4:i + 4 + n]))


def test_reader_split_reads_fragments_ping_and_close(ll):
    sent = []
    rd = ll.Reader(sent.append)
    a, b = srv(1, b'{"x":1}'), srv(1, b"y" * 300)                      # a short frame and a 16-bit-length one
    stream = a + b + srv(9, b"hi") + srv(1, b'{"a"', fin=False) + srv(0, b":2}")
    got = []
    for i in range(0, len(stream), 7):                                # arbitrary 7-byte reads
        got += rd.feed(stream[i:i + 7])
    assert got == ['{"x":1}', "y" * 300, '{"a":2}'] and rd.frames == 5
    assert len(sent) == 1 and unmask(sent[0]) == (0xA, b"hi")
    with pytest.raises(ll.Closed):
        rd.feed(srv(8, b"\x03\xe8"))


def test_client_frame_is_masked_and_round_trips(ll):
    fr = ll.frame(0x1, b"z" * 200, mask=b"\x01\x02\x03\x04")
    assert fr[0] == 0x81 and fr[1] == 0x80 | 126 and struct.unpack(">H", fr[2:4])[0] == 200
    assert bytes(b ^ b"\x01\x02\x03\x04"[k % 4] for k, b in enumerate(fr[8:])) == b"z" * 200


def test_rows_days_restart_and_the_empty_hour(ll, tmp_path):
    day, log = ll.DayFile(), ll.HourLog()
    assert ll.take(T0, [ev("AAAUSDT", "SELL", T0 - 3, T0 - 9), '{"result":null,"id":1}', "not json"], day, log) == 1
    both = "[" + ev("BBBUSDT", "BUY", T0 + 900, T0 + 800) + "," + ev("AAAUSDT", "SELL", T0 + 950, T0 + 940, q="2") + "]"
    assert ll.take(T0 + 1_000, [both], day, log) == 2                  # 00:00:00 the next day; a list of two events
    assert ll.take(T0 + 1_000 + 2 * 3_600_000, [], day, log) == 0      # 02:00: hours 00 (2 rows) and — skipped — 01 are behind
    log.at(T0 + 1_000 + 3 * 3_600_000)                                 # 03:00: hour 02 ran with no liquidation
    log.flush(); day.close()

    raw = tmp_path / "data" / "raw" / "external" / "binance_liq_live"
    d1, d2 = read(raw / "liq_20261116.csv.gz"), read(raw / "liq_20261117.csv.gz")
    assert d1 == [ll.HEADER.strip(), f"{T0},{T0 - 3},AAAUSDT,SELL,LIMIT,IOC,1.5,10.0,10.1,FILLED,1.5,1.5,{T0 - 9}"]
    assert d2 == [ll.HEADER.strip(), f"{T0 + 1_000},{T0 + 900},BBBUSDT,BUY,LIMIT,IOC,1.5,10.0,10.1,FILLED,1.5,1.5,{T0 + 800}",
                  f"{T0 + 1_000},{T0 + 950},AAAUSDT,SELL,LIMIT,IOC,2,10.0,10.1,FILLED,2,2,{T0 + 940}"]
    rows = (tmp_path / "output" / "liq_live" / "recv_log.csv").read_text().splitlines()
    assert rows == [ll.LOG_HEADER.strip(), "2026-11-16 23,1,0,0,", "2026-11-17 00,2,0,0,", "2026-11-17 02,0,0,0,", "2026-11-17 03,0,0,0,"]

    day = ll.DayFile()                                                 # a second process appends a member, one header in the file
    ll.take(T0 + 2_000, [ev("CCCUSDT", "BUY", 1, 2)], day, ll.HourLog()); day.close()
    d2 = read(raw / "liq_20261117.csv.gz")
    assert len(d2) == 4 and d2.count(ll.HEADER.strip()) == 1 and d2[-1].split(",")[2] == "CCCUSDT"


def test_a_flushed_stream_is_readable_before_it_is_closed(ll, tmp_path):
    import zlib
    day = ll.DayFile()
    ll.take(T0, [ev("AAAUSDT", "SELL", 5, 7)], day, ll.HourLog()); day.flush()
    p = tmp_path / "data" / "raw" / "external" / "binance_liq_live" / "liq_20261116.csv.gz"
    assert zlib.decompressobj(31).decompress(p.read_bytes()).decode().splitlines()[1].startswith(f"{T0},5,AAAUSDT,SELL")
    day.close()
