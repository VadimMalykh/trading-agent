#!/usr/bin/env python3
"""R96's daily fetch (PLAN §8 R96, decision CT1) — runs ON the serve host from the systemd timer ft2-cexlive at 06:00:30 UTC.

Saves DefiLlama's Binance CEX adapter file AS FETCHED, gzipped, under data/raw/external/defillama_cex_live/binance-cex_<YYYYMMDD>T<HHMM>Z.json.gz
(the name carries the minute the fetch STARTED; a file is never overwritten) and appends one row to output/cexflow_live/fetch_log.csv:
started_utc, done_utc, file, raw_bytes, raw_md5, status. Standard library only and streamed — nothing is parsed here, so the host's hourly
P7 runs keep their memory. A failed attempt is retried twice, 20 s apart; a failure leaves a log row with status `error: …` and exit 1.
The registration uses a day's file only if its fetch started 05:55:00 … 06:04:59 UTC of that day (checked at the read from the name and the log)."""
import datetime as dt
import gzip
import hashlib
import os
import pathlib
import sys
import time
import urllib.request

URL = os.environ.get("FT2_CEX_URL", "https://api.llama.fi/protocol/binance-cex")
ROOT = pathlib.Path(os.environ.get("FT2_ROOT", pathlib.Path(__file__).resolve().parent.parent))
RAW = ROOT / "data" / "raw" / "external" / "defillama_cex_live"
LOG = ROOT / "output" / "cexflow_live" / "fetch_log.csv"
MIN_BYTES = int(os.environ.get("FT2_CEX_MIN_BYTES", 10_000_000))          # the file is ≈ 47 MB; a short body is an error page


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def fetch(dest: pathlib.Path) -> tuple[int, str]:
    part = dest.with_suffix(dest.suffix + ".part")
    h, n = hashlib.md5(), 0
    req = urllib.request.Request(URL, headers={"User-Agent": "ft2-cexflow/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r, gzip.open(part, "wb", compresslevel=6) as g:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            h.update(b); n += len(b); g.write(b)
    if n < MIN_BYTES:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"short body: {n} bytes")
    part.replace(dest)
    return n, h.hexdigest()


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not LOG.exists():
        LOG.write_text("started_utc,done_utc,file,raw_bytes,raw_md5,status\n")
    t0 = now()
    dest = RAW / f"binance-cex_{t0:%Y%m%dT%H%M}Z.json.gz"
    if dest.exists():
        print(f"{dest} exists — kept"); return 0
    err = ""
    for attempt in range(3):
        try:
            n, md5 = fetch(dest)
            with LOG.open("a") as f:
                f.write(f"{t0:%Y-%m-%d %H:%M:%S},{now():%Y-%m-%d %H:%M:%S},{dest.name},{n},{md5},ok{'' if attempt == 0 else f' (attempt {attempt + 1})'}\n")
            print(f"saved {dest.name}: {n} bytes, md5 {md5}"); return 0
        except Exception as e:  # noqa: BLE001
            err = repr(e)[:160].replace(",", ";")
            time.sleep(20)
    with LOG.open("a") as f:
        f.write(f"{t0:%Y-%m-%d %H:%M:%S},{now():%Y-%m-%d %H:%M:%S},,0,,error: {err}\n")
    print(f"FAILED: {err}", file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
