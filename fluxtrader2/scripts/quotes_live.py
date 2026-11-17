#!/usr/bin/env python3
"""The all-names quote recorder (PLAN P8 decision CW2, 2026-11-17) — runs ON the serve host as the systemd service ft2-quotes.

Every 30 s on the clock (hh:mm:00 and hh:mm:30 UTC) it asks Binance's USDⓈ-M futures for EVERY symbol's best bid / ask in one call
(`/fapi/v1/ticker/bookTicker` without a symbol: 808 symbols, 122 KB, weight 5 — probed from the host 2026-11-17) and appends the rows
whose exchange `time` changed since the previous poll to data/raw/external/binance_quotes_live/quotes_<YYYYMMDD>.csv.gz:

    poll_ms,symbol,bid,bid_qty,ask,ask_qty,time_ms

`poll_ms` is the host's clock when the request was SENT; `time_ms` the exchange's stamp of that symbol's quote. The prices are written as
the exchange's own strings. A row is skipped only when its (symbol, time_ms) equals the last one written for that symbol, so the file is
lossless for the polls made. One log row an hour in output/quotes_live/poll_log.csv: hour_utc, polls_ok, polls_failed, rows, last_error.

Why (decision CW (cxxviii)): the archive holds no quotes (`bookTicker` is discontinued), so a resting order's fill on these names is
inferred from the prints and bracketed; a day not recorded cannot be had later. Nothing here reads a price for a decision: the files are
a fetch log until a registration names them. Standard library only, ≈ 20 MB of memory — it cannot starve P7's hourly runs.

A failed poll is not retried (the next one is 30 s away); the gzip stream is flushed after every poll, and a restart appends a new gzip
member to the day's file (a concatenation of members is a valid .gz)."""
import datetime as dt
import gzip
import json
import os
import pathlib
import signal
import sys
import time
import urllib.request
import zlib

URL = os.environ.get("FT2_QUOTES_URL", "https://fapi.binance.com/fapi/v1/ticker/bookTicker")
ROOT = pathlib.Path(os.environ.get("FT2_ROOT", pathlib.Path(__file__).resolve().parent.parent))
RAW = ROOT / "data" / "raw" / "external" / "binance_quotes_live"
LOG = ROOT / "output" / "quotes_live" / "poll_log.csv"
STEP = int(os.environ.get("FT2_QUOTES_STEP", 30))                 # seconds between polls, on the clock
MIN_SYMBOLS = int(os.environ.get("FT2_QUOTES_MIN_SYMBOLS", 300))  # a shorter list is an error page or a partial answer
HEADER = "poll_ms,symbol,bid,bid_qty,ask,ask_qty,time_ms\n"
LOG_HEADER = "hour_utc,polls_ok,polls_failed,rows,last_error\n"


def fetch() -> list:
    req = urllib.request.Request(URL, headers={"User-Agent": "ft2-quotes/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def lines(poll_ms: int, body: list, last: dict) -> list[str]:
    """The CSV lines of one poll; `last` (symbol → time_ms written) is updated in place. Raises on a body that is not the full list."""
    if not isinstance(body, list) or len(body) < MIN_SYMBOLS:
        raise ValueError(f"short list: {len(body) if isinstance(body, list) else type(body).__name__}")
    out = []
    for x in body:
        s, t = x["symbol"], int(x["time"])
        if last.get(s) == t:
            continue
        last[s] = t
        out.append(f"{poll_ms},{s},{x['bidPrice']},{x['bidQty']},{x['askPrice']},{x['askQty']},{t}\n")
    return out


class DayFile:
    """The day's gzip stream, kept open and sync-flushed after every poll; a new day (or a restart) opens a new member."""

    def __init__(self):
        self.day, self.g = None, None

    def write(self, poll_ms: int, rows: list[str]) -> None:
        day = dt.datetime.fromtimestamp(poll_ms / 1000, dt.timezone.utc).strftime("%Y%m%d")
        if day != self.day:
            self.close()
            RAW.mkdir(parents=True, exist_ok=True)
            p = RAW / f"quotes_{day}.csv.gz"
            new = not p.exists()
            self.g, self.day = gzip.open(p, "ab", compresslevel=6), day
            if new:
                self.g.write(HEADER.encode())
        self.g.write("".join(rows).encode())
        self.g.flush(zlib.Z_SYNC_FLUSH)

    def close(self) -> None:
        if self.g is not None:
            self.g.close()
        self.g = None


class HourLog:
    def __init__(self):
        self.hour, self.ok, self.bad, self.rows, self.err = None, 0, 0, 0, ""

    def add(self, poll_ms: int, n_rows: int, err: str) -> None:
        hour = dt.datetime.fromtimestamp(poll_ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H")
        if hour != self.hour:
            self.flush()
            self.hour = hour
        if err:
            self.bad += 1; self.err = err
        else:
            self.ok += 1; self.rows += n_rows

    def flush(self) -> None:
        if self.hour is not None and self.ok + self.bad:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            if not LOG.exists():
                LOG.write_text(LOG_HEADER)
            with LOG.open("a") as f:
                f.write(f"{self.hour},{self.ok},{self.bad},{self.rows},{self.err}\n")
        self.ok, self.bad, self.rows, self.err = 0, 0, 0, ""


def poll(poll_ms: int, last: dict, day: DayFile, log: HourLog, fetcher=fetch) -> int:
    """One poll: fetch, write, log. Returns the rows written (0 on a failure, which is logged and never raised)."""
    try:
        rows = lines(poll_ms, fetcher(), last)
        day.write(poll_ms, rows)
        log.add(poll_ms, len(rows), "")
        return len(rows)
    except Exception as e:  # noqa: BLE001
        log.add(poll_ms, 0, repr(e)[:120].replace(",", ";").replace("\n", " "))
        return 0


def main() -> int:
    last, day, log = {}, DayFile(), HourLog()

    def stop(*_):
        log.flush(); day.close(); sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        now = time.time()
        time.sleep(STEP - now % STEP)          # to the next hh:mm:00 / hh:mm:30
        poll(int(time.time() * 1000), last, day, log)


if __name__ == "__main__":
    sys.exit(main())
