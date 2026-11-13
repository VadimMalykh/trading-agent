"""R96's daily fetch (`scripts/cexflow_live.py`) on a planted file, no network: the body is saved gzipped byte for byte under the minute the
fetch started, the log row carries its size and md5, a second run in the same minute keeps the first file, a short body is an error row."""
import gzip
import hashlib
import importlib.util
import pathlib


def _load(monkeypatch, tmp_path, body: bytes, min_bytes: int):
    src = tmp_path / "src.json"
    src.write_bytes(body)
    monkeypatch.setenv("FT2_CEX_URL", src.as_uri())
    monkeypatch.setenv("FT2_ROOT", str(tmp_path))
    monkeypatch.setenv("FT2_CEX_MIN_BYTES", str(min_bytes))
    spec = importlib.util.spec_from_file_location("cexflow_live", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cexflow_live.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    return m


def test_the_body_is_saved_as_fetched_and_logged_and_never_overwritten(tmp_path, monkeypatch):
    body = b'{"chainTvls": {}}' * 5000
    m = _load(monkeypatch, tmp_path, body, 1000)
    assert m.main() == 0
    files = sorted((tmp_path / "data" / "raw" / "external" / "defillama_cex_live").glob("binance-cex_*Z.json.gz"))
    assert len(files) == 1 and gzip.decompress(files[0].read_bytes()) == body
    rows = (tmp_path / "output" / "cexflow_live" / "fetch_log.csv").read_text().splitlines()
    assert rows[0] == "started_utc,done_utc,file,raw_bytes,raw_md5,status" and len(rows) == 2
    f = rows[1].split(",")
    assert f[2] == files[0].name and int(f[3]) == len(body) and f[4] == hashlib.md5(body).hexdigest() and f[5] == "ok" and f[0][11:16].replace(":", "") == files[0].name[21:25]
    before = files[0].stat().st_mtime_ns
    monkeypatch.setattr(m, "now", lambda: __import__("datetime").datetime.strptime(f[0] + "+0000", "%Y-%m-%d %H:%M:%S%z"))
    assert m.main() == 0 and files[0].stat().st_mtime_ns == before                                  # the same minute: the first file is kept


def test_a_short_body_is_an_error_row_and_no_file(tmp_path, monkeypatch):
    m = _load(monkeypatch, tmp_path, b"<html>busy</html>", 1000)
    assert m.main() == 1
    assert not list((tmp_path / "data" / "raw" / "external" / "defillama_cex_live").glob("*.gz")) and not list((tmp_path / "data" / "raw" / "external" / "defillama_cex_live").glob("*.part"))
    assert (tmp_path / "output" / "cexflow_live" / "fetch_log.csv").read_text().splitlines()[-1].endswith("short body: 17 bytes')")


# ---- ft2/cexlive.py: the usable-file rule and the day's change from one file -----------------------------------------------------------
import gzip as _gz
import json as _json

import numpy as np
import pandas as pd

from ft2 import cexlive

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731


def _file(path, points):
    """points: {day: {chain: {token: amount}}} → the adapter's shape, gzipped."""
    ch = {}
    for day, by in points.items():
        for c, toks in by.items():
            ch.setdefault(c, {"tokens": [], "tokensInUsd": []})
            ch[c]["tokens"].append({"date": int(D(day).timestamp()), "tokens": toks})
            ch[c]["tokensInUsd"].append({"date": int(D(day).timestamp()), "tokens": {k: v * 2.0 for k, v in toks.items()}})
    path.write_bytes(_gz.compress(_json.dumps({"chainTvls": ch}).encode()))


def test_a_file_is_usable_only_when_its_fetch_started_in_the_window_and_the_change_is_the_days_own_file(tmp_path):
    log = pd.DataFrame({"started_utc": ["2026-11-16 06:00:31", "2026-11-17 06:05:00", "2026-11-17 13:00:00", "2026-11-18 05:55:00", "2026-11-18 06:01:00", "2026-11-19 06:00:30", "2026-11-20 06:00:30"],
                        "done_utc": "", "file": ["a.json.gz", "late.json.gz", "noon.json.gz", "c.json.gz", "c2.json.gz", None, "e.json.gz"], "raw_bytes": 1, "raw_md5": "m",
                        "status": ["ok", "ok", "ok", "ok (attempt 2)", "ok", "error: x", "ok"]})
    U = cexlive.usable(log)
    assert U["file"].tolist() == ["a.json.gz", "c.json.gz", "e.json.gz"] and U["day"].tolist() == [D("2026-11-16"), D("2026-11-18"), D("2026-11-20")]   # 06:05:00 is out; the day's first; an error row is none
    _file(tmp_path / "a.json.gz", {"2026-10-01": {"Ethereum": {"AAA": 50.0}}, "2026-11-15": {"Ethereum": {"AAA": 100.0, "BBB": 10.0}, "BSC": {"AAA": 100.0}, "Ethereum-staking": {"AAA": 999.0}},
                                    "2026-11-16": {"Ethereum": {"AAA": 110.0, "BBB": 10.0, "NEW": 5.0}, "BSC": {"AAA": 110.0}, "Ethereum-staking": {"AAA": 1.0}}})
    d = cexlive.day_change(tmp_path / "a.json.gz", D("2026-11-16")).set_index("base")
    assert d.loc["AAA", "amount"] == 220.0 and d.loc["AAA", "prev_amount"] == 200.0 and d.loc["AAA", "change"] == 0.1 - 0 or abs(d.loc["AAA", "change"] - 0.1) < 1e-12   # the staking chain is out
    assert d.loc["BBB", "change"] == 0.0 and np.isnan(d.loc["NEW", "change"]) and d.loc["AAA", "first_stamp"] == D("2026-10-01") and d.loc["NEW", "first_stamp"] == D("2026-11-16")
    assert len(cexlive.day_change(tmp_path / "a.json.gz", D("2026-11-17"))) == 0                              # the file lacks that day's point


def test_a_rewritten_previous_point_is_flagged_and_an_unchecked_one_is_said(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _file(raw / "d16.json.gz", {"2026-11-15": {"Ethereum": {"AAA": 100.0}}, "2026-11-16": {"Ethereum": {"AAA": 100.0, "BBB": 40.0}}})
    _file(raw / "d17.json.gz", {"2026-11-16": {"Ethereum": {"AAA": 90.0, "BBB": 40.1}}, "2026-11-17": {"Ethereum": {"AAA": 99.0, "BBB": 44.0}}})   # AAA's 11-16 point was 100 in its own file
    _file(raw / "d19.json.gz", {"2026-11-18": {"Ethereum": {"AAA": 99.0}}, "2026-11-19": {"Ethereum": {"AAA": 120.0}}})
    _file(raw / "d20.json.gz", {"2026-11-19": {"Ethereum": {"AAA": 120.0}}})                                  # fetched in the window but without its day's point
    log = tmp_path / "fetch_log.csv"
    pd.DataFrame({"started_utc": [f"2026-11-{k} 06:00:30" for k in (16, 17, 19, 20)], "done_utc": "", "file": ["d16.json.gz", "d17.json.gz", "d19.json.gz", "d20.json.gz"], "raw_bytes": 1, "raw_md5": "m", "status": "ok"}).to_csv(log, index=False)
    A, U = cexlive.live_rows(raw, log)
    assert U["has_point"].tolist() == [True, True, True, False]
    a = A.set_index(["day", "base"])
    r = a.loc[(D("2026-11-17"), "AAA")]
    assert r["checked"] and r["rewritten"] and abs(r["change"] - 0.1) < 1e-12                                 # +10 % in the file of the 17th — on a previous point that moved 10 %: flagged
    b = a.loc[(D("2026-11-17"), "BBB")]
    assert b["checked"] and not b["rewritten"] and abs(b["change"] - (44.0 / 40.1 - 1)) < 1e-12              # 0.25 % apart: inside the tolerance
    c = a.loc[(D("2026-11-19"), "AAA")]
    assert not c["checked"] and not c["rewritten"] and abs(c["change"] - (120 / 99 - 1)) < 1e-12              # the 18th has no usable file: unchecked, said
    assert not a.loc[(D("2026-11-16"), "AAA")]["checked"]
