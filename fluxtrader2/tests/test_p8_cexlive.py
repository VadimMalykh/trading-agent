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
