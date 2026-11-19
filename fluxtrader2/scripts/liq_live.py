#!/usr/bin/env python3
"""The all-names liquidation recorder (PLAN P8 decision CX2, 2026-11-19) — runs ON the serve host as the systemd service ft2-liq.

It holds ONE websocket to Binance's USDⓈ-M futures stream `!forceOrder@arr` (every symbol's forced orders; the exchange pushes at most
the latest one a symbol a second; the path is `/market/ws/` — probed from the host 2026-11-19: the legacy `/ws/` and `/stream` paths
accept the socket and send nothing, `/market/ws/` gave 25 events in 100 s) and appends every event to data/raw/external/binance_liq_live/liq_<YYYYMMDD>.csv.gz:

    recv_ms,event_ms,symbol,side,type,tif,qty,price,avg_price,status,last_qty,cum_qty,trade_ms

`recv_ms` is the host's clock when the frame was read; `event_ms` (E) and `trade_ms` (o.T) the exchange's stamps; the numbers are the
exchange's own strings. `side` is the side of the FORCED ORDER (SELL = a long liquidated). The day of a row is its `recv_ms` day.
One log row an hour in output/liq_live/recv_log.csv: hour_utc, rows, connects, errors, last_error — written for every hour the
service ran, also an hour with no liquidation.

Why (decision CX (cxxxii)): the archive has no liquidation file for USDT-margined contracts, so a day not recorded cannot be had
later. Nothing here reads a price for a decision: the files are a fetch log until a registration names them. Standard library only
(the websocket client is the eighty lines below: RFC 6455 text frames, ping → pong, fragments), a few MB of memory.

What is NOT in the file: a liquidation the exchange did not push (more than one a symbol within a second), and everything while the
socket was down — `connects` > 1 or `errors` > 0 in an hour marks it. The socket is re-opened every 23 h (the exchange closes at 24 h),
after any error (5 s later) and after 10 min without a frame (the exchange pings every 3 min)."""
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import pathlib
import signal
import socket
import ssl
import struct
import sys
import time
import urllib.parse
import zlib

URL = os.environ.get("FT2_LIQ_URL", "wss://fstream.binance.com/market/ws/!forceOrder@arr")
ROOT = pathlib.Path(os.environ.get("FT2_ROOT", pathlib.Path(__file__).resolve().parent.parent))
RAW = ROOT / "data" / "raw" / "external" / "binance_liq_live"
LOG = ROOT / "output" / "liq_live" / "recv_log.csv"
TICK = float(os.environ.get("FT2_LIQ_TICK", 5))             # the socket's read timeout: flush and clock checks happen at least this often
SILENCE = float(os.environ.get("FT2_LIQ_SILENCE", 600))     # seconds without any frame before the socket is re-opened
MAX_AGE = float(os.environ.get("FT2_LIQ_MAX_AGE", 23 * 3600))
HEADER = "recv_ms,event_ms,symbol,side,type,tif,qty,price,avg_price,status,last_qty,cum_qty,trade_ms\n"
LOG_HEADER = "hour_utc,rows,connects,errors,last_error\n"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---- the websocket client (RFC 6455, what this stream needs) -----------------------------------
class Closed(Exception):
    pass


def connect(url: str = URL, timeout: float = 15):
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "wss" else 80)
    s = socket.create_connection((u.hostname, port), timeout=timeout)
    if u.scheme == "wss":
        s = ssl.create_default_context().wrap_socket(s, server_hostname=u.hostname)
    key = base64.b64encode(os.urandom(16)).decode()
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: ft2-liq/1\r\n\r\n").encode())
    head = b""
    while b"\r\n\r\n" not in head:
        c = s.recv(4096)
        if not c:
            raise Closed("closed in the handshake")
        head += c
        if len(head) > 65536:
            raise Closed("handshake too long")
    head, rest = head.split(b"\r\n\r\n", 1)
    lines_ = head.decode("latin-1").split("\r\n")
    if " 101 " not in lines_[0] + " ":
        raise Closed(f"handshake: {lines_[0][:80]}")
    hdr = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines_[1:] if ":" in ln)}
    if hdr.get("sec-websocket-accept") != base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode():
        raise Closed("handshake: wrong accept key")
    return s, rest


def frame(opcode: int, payload: bytes = b"", mask: bytes | None = None) -> bytes:
    """A client frame (always masked, FIN set)."""
    mask = mask or os.urandom(4)
    n = len(payload)
    head = bytes([0x80 | opcode]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                     else bytes([0x80 | 127]) + struct.pack(">Q", n))
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class Reader:
    """Frames out of a byte stream. feed(bytes) → the list of complete TEXT messages; control frames are answered through `send`
    (a ping by a pong with the same payload) and a close frame raises Closed. `frames` counts every frame seen (liveness)."""

    def __init__(self, send):
        self.buf, self.parts, self.send, self.frames = b"", [], send, 0

    def feed(self, data: bytes) -> list[str]:
        self.buf += data
        out = []
        while True:
            b = self.buf
            if len(b) < 2:
                return out
            fin, op, masked, n, i = b[0] & 0x80, b[0] & 0x0F, b[1] & 0x80, b[1] & 0x7F, 2
            if n == 126:
                if len(b) < 4:
                    return out
                n, i = struct.unpack(">H", b[2:4])[0], 4
            elif n == 127:
                if len(b) < 10:
                    return out
                n, i = struct.unpack(">Q", b[2:10])[0], 10
            if masked:
                i += 4
            if len(b) < i + n:
                return out
            p = b[i:i + n]
            if masked:
                m = b[i - 4:i]
                p = bytes(x ^ m[k % 4] for k, x in enumerate(p))
            self.buf = b[i + n:]
            self.frames += 1
            if op == 0x9:
                self.send(frame(0xA, p))
            elif op == 0x8:
                raise Closed(f"close frame {p[:2].hex()}")
            elif op in (0x0, 0x1, 0x2):
                self.parts.append(p)
                if fin:
                    out.append(b"".join(self.parts).decode("utf-8", "replace"))
                    self.parts = []


# ---- rows, files, log --------------------------------------------------------------------------
def _f(x) -> str:
    return str(x).replace(",", ";").replace("\n", " ")


def rows(recv_ms: int, text: str) -> list[str]:
    """The CSV lines of one message (an event, or a list of events); anything that is not a forceOrder event gives no row."""
    try:
        body = json.loads(text)
    except ValueError:
        return []
    out = []
    for ev in body if isinstance(body, list) else [body]:
        if isinstance(ev, dict) and "stream" in ev and "data" in ev:      # the combined-stream wrapper
            ev = ev["data"]
        o = ev.get("o") if isinstance(ev, dict) else None
        if not isinstance(o, dict) or ev.get("e") != "forceOrder":
            continue
        out.append(",".join([str(recv_ms), _f(ev.get("E", "")), _f(o.get("s", "")), _f(o.get("S", "")), _f(o.get("o", "")), _f(o.get("f", "")),
                             _f(o.get("q", "")), _f(o.get("p", "")), _f(o.get("ap", "")), _f(o.get("X", "")), _f(o.get("l", "")),
                             _f(o.get("z", "")), _f(o.get("T", ""))]) + "\n")
    return out


class DayFile:
    """The day's gzip stream; `flush` sync-flushes what was written since the last one; a new day (or a restart) opens a new member."""

    def __init__(self):
        self.day, self.g, self.dirty = None, None, False

    def write(self, recv_ms: int, lines_: list[str]) -> None:
        day = dt.datetime.fromtimestamp(recv_ms / 1000, dt.timezone.utc).strftime("%Y%m%d")
        if day != self.day:
            self.close()
            RAW.mkdir(parents=True, exist_ok=True)
            p = RAW / f"liq_{day}.csv.gz"
            new = not p.exists()
            self.g, self.day = gzip.open(p, "ab", compresslevel=6), day
            if new:
                self.g.write(HEADER.encode())
        self.g.write("".join(lines_).encode())
        self.dirty = True

    def flush(self) -> None:
        if self.g is not None and self.dirty:
            self.g.flush(zlib.Z_SYNC_FLUSH)
            self.dirty = False

    def close(self) -> None:
        if self.g is not None:
            self.g.close()
        self.g, self.dirty = None, False


class HourLog:
    def __init__(self):
        self.hour, self.rows, self.connects, self.errors, self.err = None, 0, 0, 0, ""

    def at(self, now_ms: int) -> None:
        """Move the clock: when the hour changes, the finished hour's row is written (also with zero rows)."""
        hour = dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H")
        if hour != self.hour:
            self.flush()
            self.hour = hour

    def flush(self) -> None:
        if self.hour is not None:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            if not LOG.exists():
                LOG.write_text(LOG_HEADER)
            with LOG.open("a") as f:
                f.write(f"{self.hour},{self.rows},{self.connects},{self.errors},{self.err}\n")
        self.rows, self.connects, self.errors, self.err = 0, 0, 0, ""

    def error(self, e) -> None:
        self.errors += 1
        self.err = repr(e)[:120].replace(",", ";").replace("\n", " ")


def take(now_ms: int, texts: list[str], day: DayFile, log: HourLog) -> int:
    """Write the messages read at `now_ms`; returns the rows written."""
    log.at(now_ms)
    n = 0
    for t in texts:
        r = rows(now_ms, t)
        if r:
            day.write(now_ms, r)
            n += len(r)
    log.rows += n
    return n


def session(day: DayFile, log: HourLog, until: float | None = None) -> None:
    """One socket's life: connect, read until an error, silence, age or `until` (a clock time, for the probe)."""
    s, rest = connect()
    try:
        log.at(int(time.time() * 1000)); log.connects += 1
        s.settimeout(TICK)
        rd = Reader(s.sendall)
        born = seen = time.time()
        take(int(born * 1000), rd.feed(rest), day, log)
        while True:
            now = time.time()
            if until is not None and now >= until:
                return
            if now - born > MAX_AGE:
                return
            if now - seen > SILENCE:
                raise Closed(f"no frame for {SILENCE:.0f} s")
            try:
                data = s.recv(65536)
            except (socket.timeout, TimeoutError):
                day.flush(); log.at(int(time.time() * 1000))
                continue
            if not data:
                raise Closed("socket closed")
            before = rd.frames
            texts = rd.feed(data)
            if rd.frames > before:
                seen = time.time()
            take(int(time.time() * 1000), texts, day, log)
            day.flush()
    finally:
        try:
            s.close()
        except OSError:
            pass


def main() -> int:
    day, log = DayFile(), HourLog()
    probe = float(os.environ.get("FT2_LIQ_PROBE", 0))            # seconds: run that long, then exit (the install probe)
    until = time.time() + probe if probe else None

    def stop(*_):
        log.flush(); day.close(); sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        try:
            session(day, log, until)
        except Exception as e:  # noqa: BLE001
            log.at(int(time.time() * 1000)); log.error(e)
            day.flush()
            if until is None:
                time.sleep(5)
        if until is not None and time.time() >= until - 1:
            stop()
        if until is not None:
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
