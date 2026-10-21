"""M1 — the maker path priced on the policy's own entries, with an uncensored tape.

Registered in docs/BOOK_WAVE2_PLAN.md §M1 (2026-10-19) before any code. Every policy trade is
scored two ways at its entry AND its exit — TAKER (cross at the bar close) and MAKER→TAKER
(rest at the touch for W seconds, cross if unfilled) — and the per-trade net returns are
differenced on identical trade sets. The 4-hour price path sits inside each arm's return, so
adverse selection and the chase are lines in the ledger, not a side panel.

Subcommands (scripts/m3.sh -m m3 makerpath …):
  entries    stratum A (the served dump at cov 0.05) and B (the forward ledger), the candle
             match, the moment list, the pair-days to fetch and the BOOK_FILTER for the export
  fetch      archive aggTrades, streamed: each daily zip is downloaded, sha256-verified, cut to
             the moment windows and discarded
  calibrate  the prerequisite — the tape-implied touch against the collector's book
  read       the arms, S1, the tables, the verdict

Mechanical choices fixed HERE, before any fill number existed (each with its bias direction):
  (a) The QUOTED leg is a moment with an `orderbook_levels` row ≤ 30 s before it — the table
      §M1's data section names. That table begins 2026-08-05 (migration 20260805000001), not
      2026-07-17 as the registration's prose says: 07-17 → 08-05 has only scalar snapshots,
      no touch prices. Those moments go to the TAPE leg. Direction: none (a leg assignment).
  (b) The retained tape is [T − 120 s, T + 360 s] — the registration said T + 1,800 s, but no
      registered quantity reads past T + W_max + 60 s (= 360 s) and the 1,800 s tail would
      multiply the kept rows by four. Direction: none (nothing registered reads it).
  (c) The TAPE leg's T + W touch is read like the T touch — the last trade of each aggressor
      kind in [T + W − 60 s, T + W]; a moment missing either touch at T or at T + W is dropped
      from BOTH arms (M3-4 §2.7's consequence), counted. Direction: none.
  (d) Fees are INSIDE each arm's return (taker 5.0 / maker 2.0 per side, parameters) — the arms'
      fees differ, so nothing cancels in the contrast; an unfilled maker leg pays taker.
  (e) The primary weighting is EQUAL notional per trade ($1,000 each, the fill-model size);
      the policy's own size ladder (⅓ … 5⁄3) is a reported sensitivity.
  (f) The tick, per pair, is the smallest positive difference between distinct archive prices
      on that pair's retained tape (printed).
  (g) A trade's LEG is `quoted` iff both its moments are quoted, else `tape`; a moment is
      scored on its own leg either way. "Quoted leg alone" means the `quoted`-tagged trades.
  (h) Harness check 2 is read as M3_4_RESULTS §1's `C_taker` column — the ROUND-TRIP taker
      cost at the 4.0-bps fee of that table, on the 5-minute grid over M3-4's own exported
      book (output/m3_4) — reproduced per pair within ±1.0 bps by THIS module's walk.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import dumps, execcost, regime, backtest, sidetable
from . import walkforward as wf
from .archiveoi import DL, _get as _get_once


def _get(url: str, tries: int = 8) -> bytes | None:
    """archiveoi._get retries HTTP-level failures only; a daily aggTrades zip is 10–25 MB and the
    CDN drops a read now and then (IncompleteRead) — retry ANY exception with backoff, 404 stays None."""
    delay = 2.0
    for k in range(tries):
        try:
            return _get_once(url)
        except Exception as e:  # noqa: BLE001 — the point is to survive the CDN's transient faults
            if k == tries - 1:
                raise
            print(f"  retry {k + 1}/{tries - 1} {url.rsplit('/', 1)[-1]}: {type(e).__name__}", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    return None

# --------------------------------------------------------------------------------------
# Constants, fixed by the registration
# --------------------------------------------------------------------------------------
OUT_DIR = "output/makerpath"
BOOK_DIR = "output/makerpath_book"          # the ladder + candle export for the moment windows
TAPE_DIR = os.path.join(OUT_DIR, "tape_windows")
M34_BOOK = "output/m3_4"                    # M3-4's own book, for harness check 2
WF_SIDE = "output/wf_side"                  # 5m candles 2024-10 → 2026-09-11 (stratum A)
FORWARD_DIR = "output/forward"

P1_RUN = "20261003T191545Z"                 # the served checkpoint's dump (X8″ s3)
A_COVERAGE = 0.05
NS = 1_000_000_000
BAR_NS = 300 * NS
DECISION_OFFSET_NS = 5 * 60 * NS            # dump `ts` is the bar OPEN; T is its close
HOLD_NS = 240 * 60 * NS
TAPE_PRE_S, TAPE_POST_S = 120, 360          # choice (b)
TOUCH_LOOKBACK_S = 60
W_PRIMARY, W_SENS = 60, (30, 300)
SIZE_PRIMARY, SIZE_LADDER = 1_000.0, (100.0, 10_000.0)
TAKER_FEE, MAKER_FEE = 5.0, 2.0             # REAL_MONEY_TRACK §7 row 1 — parameters, not execcost's constants
STALE_S = execcost.STALENESS_CAP_S          # 30 s
LEVELS = 20
BPS = 1e4
CAL_TOUCH_SHARE, CAL_FILL_SHARE, CAL_MIN_MOMENTS = 0.80, 0.90, 1_000
B_ARMS = ("policy", "explore_cov05")
PILOT_ARM, PILOT_SIZE = "live", 100.0

# M3_4_RESULTS §1 — C_taker (round trip, L1, $10,000, fee 4.0) per pair; harness check 2
M34_C_TAKER = {"BTCUSDT": 8.017, "ETHUSDT": 8.057, "HYPEUSDT": 9.125, "SOLUSDT": 9.242,
               "ZECUSDT": 9.448, "DOGEUSDT": 9.538, "1000PEPEUSDT": 11.263, "WLDUSDT": 14.060}
M34_FEE = 4.0


def _p(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------------------
# entries — the two strata, the candle match, the moments, the pair-days, the BOOK_FILTER
# --------------------------------------------------------------------------------------

def stratum_a() -> pd.DataFrame:
    """The served policy's own trade list: WINNER_SPEC at coverage 0.05 over the dump's window,
    serial per pair, 240-minute hold — the backtester's list, not a re-derivation."""
    from .cli import WINNER_SPEC
    d = dumps.load(P1_RUN, seed="s3")
    reg = regime.build(d.df)
    spec = backtest.PolicySpec(label="m1_A", **{**WINNER_SPEC, "coverage": A_COVERAGE})
    t = backtest.run([d], spec, {d.seed: reg}).trades.copy()
    t["stratum"], t["arm"] = "A", "dump_cov05"
    t["side"] = t["side"].astype(int)
    return t[["stratum", "arm", "pair", "side", "size", "entry_ts", "exit_ts", "fwd_ret", "signed_ret",
              "conf", "regime"]].reset_index(drop=True)


def _newest(dirname: str, prefix: str) -> str:
    fs = sorted(f for f in os.listdir(dirname) if f.startswith(prefix) and f.endswith(".csv"))
    if not fs:
        raise SystemExit(f"no {prefix}*.csv in {dirname}")
    return os.path.join(dirname, fs[-1])



def _ledger_shift_ns(ledger_bar_ts):
    """Nanoseconds from a ledger row's `bar_ts` back to its signal bar's open: two bars before
    the clock fix's deploy, zero from it (forward.BAR_KEY_CHANGE_UTC; None = not deployed)."""
    from . import forward as _fwd
    ts = np.asarray(ledger_bar_ts, dtype="int64")
    if _fwd.BAR_KEY_CHANGE_UTC is None:
        return np.full(ts.shape, 2 * BAR_NS, dtype="int64")
    return np.where(ts >= int(pd.Timestamp(_fwd.BAR_KEY_CHANGE_UTC).value), 0, 2 * BAR_NS).astype("int64")

def stratum_b(path: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The forward ledger's closed `policy` and `explore_cov05` entries, plus the `live` pilot
    fills (returned apart). `entry_ts` is the bar OPEN (= policy_bars.bar_ts)."""
    path = path or _newest(FORWARD_DIR, "paper_trades_")
    df = pd.read_csv(path)
    for c in ("entry_ts", "exit_ts", "exit_after_ts"):
        df[c] = pd.to_datetime(df[c], utc=True)
    closed = df[df["status"] == "closed"].copy()
    b = closed[closed["arm"].isin(B_ARMS)].copy()
    b["stratum"] = "B"
    b["ledger_bar_ts"] = b["entry_ts"].astype("int64")
    # The served row's `bar_ts` was stamped 10 minutes AFTER the open of the bar whose close it books
    # (policy_bars.price == the candle close at bar_ts − 10 min on 99.7 % of 57,515 rows, 2026-10-21;
    # the entry pin below holds only there). The SIGNAL bar's open is therefore bar_ts − 10 min and
    # T, its close, bar_ts − 5 min — the registered T, read off the pin's own evidence. From the
    # clock fix's deploy (forward.BAR_KEY_CHANGE_UTC, M3_5 §4.5) `bar_ts` IS the signal bar's open.
    b["entry_ts"] = b["ledger_bar_ts"] - _ledger_shift_ns(b["ledger_bar_ts"])
    b["exit_ts_actual"] = b["exit_ts"].astype("int64")
    b["exit_ts"] = b["entry_ts"] + HOLD_NS                 # the bar whose close is T + 240 min
    b["inserted_at"] = pd.to_datetime(b["inserted_at"], utc=True).astype("int64")
    b["side"] = np.where(b["side"].astype(str).str.lower().isin(["long", "buy", "1", "1.0"]), 1, -1)
    b["fwd_ret"] = np.nan
    b["signed_ret"] = b["net_bps"] / BPS
    b["conf"], b["regime"] = b["confidence"], b["regime"]
    b = b.rename(columns={"entry_price": "ledger_entry_price", "exit_price": "ledger_exit_price"})
    live = closed[closed["arm"] == PILOT_ARM].copy()
    live["ledger_bar_ts"] = live["entry_ts"].astype("int64")
    live["entry_ts"] = live["ledger_bar_ts"] - _ledger_shift_ns(live["ledger_bar_ts"])
    live["inserted_at"] = pd.to_datetime(live["inserted_at"], utc=True).astype("int64")
    live["side"] = np.where(live["side"].astype(str).str.lower().isin(["long", "buy", "1", "1.0"]), 1, -1)
    _p(f"stratum B: {path} — {len(b)} closed rows ({b['arm'].value_counts().to_dict()}), "
       f"{len(live)} pilot fills; entries {pd.Timestamp(b['entry_ts'].min()).strftime('%Y-%m-%d %H:%M')} → "
       f"{pd.Timestamp(b['entry_ts'].max()).strftime('%Y-%m-%d %H:%M')} UTC")
    cols = ["stratum", "arm", "pair", "side", "size", "entry_ts", "exit_ts", "exit_ts_actual", "fwd_ret",
            "signed_ret", "conf", "regime", "ledger_entry_price", "ledger_exit_price", "id", "ledger_bar_ts", "inserted_at"]
    return b[cols].reset_index(drop=True), live[["pair", "side", "entry_ts", "entry_price", "size", "id", "ledger_bar_ts", "inserted_at"]]


def candle_match(trades: pd.DataFrame, candles: pd.DataFrame, label: str) -> pd.DataFrame:
    """Entry close = the close of the candle opening at `entry_ts` (the price at T); exit close =
    the candle opening at `exit_ts`. Pins: on A the dump's fwd_ret equals exit/entry − 1 (the
    backtester's own return) on ≥ 99 % of trades; on B the ledger's entry_price equals the
    entry close on ≥ 99 %. A miss beyond that is a harness defect, not a data point."""
    c = candles[["pair", "ts", "close"]].rename(columns={"ts": "entry_ts", "close": "entry_close"})
    t = trades.merge(c, on=["pair", "entry_ts"], how="left")
    c2 = c.rename(columns={"entry_ts": "exit_ts", "entry_close": "exit_close"})
    t = t.merge(c2, on=["pair", "exit_ts"], how="left")
    ok = t["entry_close"].notna() & t["exit_close"].notna()
    _p(f"{label}: {len(t)} trades, {int(ok.sum())} with both candles")
    if label == "A":
        r = t["exit_close"] / t["entry_close"] - 1
        agree = (np.abs(r - t["fwd_ret"]) <= 1e-9 + 1e-6 * np.abs(t["fwd_ret"])) & ok
        share = agree.sum() / max(ok.sum(), 1)
        _p(f"  pin: candle return == dump fwd_ret on {agree.sum()}/{int(ok.sum())} ({share:.4f})")
        if share < 0.99:
            raise SystemExit("candle match FAILED on A — harness defect, fix before fetching")
    else:
        agree = (np.abs(t["ledger_entry_price"] - t["entry_close"]) <= 1e-9 * t["entry_close"]) & ok
        share = agree.sum() / max(ok.sum(), 1)
        _p(f"  pin: ledger entry_price == candle close at T on {agree.sum()}/{int(ok.sum())} ({share:.4f})")
        if ok.sum() and share < 0.99:
            raise SystemExit("candle match FAILED on B — harness defect, fix before fetching")
        same_exit = (t["exit_ts_actual"] - (t["ledger_bar_ts"] + HOLD_NS)).abs() <= 2 * 60 * NS
        _p(f"  the ledger closed within 2 min of bar_ts + 240 min on {int(same_exit.sum())}/{len(t)} rows (the rest off the timer)")
    t["entry_T"] = t["entry_ts"] + DECISION_OFFSET_NS
    t["exit_T"] = t["exit_ts"] + DECISION_OFFSET_NS
    t["tid"] = [f"{s}:{a}:{p}:{e}" for s, a, p, e in zip(t["stratum"], t["arm"], t["pair"], t["entry_ts"])]
    return t


def moments_of(trades: pd.DataFrame) -> pd.DataFrame:
    """One row per (pair, T, role): the entry moment with the trade's side, the exit moment with
    the opposite side (the resting/crossing side at that moment)."""
    e = pd.DataFrame({"pair": trades["pair"], "T": trades["entry_T"], "role": "entry",
                      "side": trades["side"], "tid": trades["tid"]})
    x = pd.DataFrame({"pair": trades["pair"], "T": trades["exit_T"], "role": "exit",
                      "side": -trades["side"], "tid": trades["tid"]})
    return pd.concat([e, x], ignore_index=True).sort_values(["pair", "T"], kind="mergesort").reset_index(drop=True)


def pair_days(moments: pd.DataFrame) -> pd.DataFrame:
    """Every (pair, UTC day) a retained window [T − 120 s, T + 360 s] touches."""
    lo = moments["T"] - TAPE_PRE_S * NS
    hi = moments["T"] + TAPE_POST_S * NS
    rows = []
    for p, a, b in zip(moments["pair"], lo, hi):
        d0, d1 = a // (86_400 * NS), b // (86_400 * NS)
        for d in range(int(d0), int(d1) + 1):
            rows.append((p, pd.Timestamp(d * 86_400, unit="s", tz="UTC").strftime("%Y-%m-%d")))
    return pd.DataFrame(rows, columns=["pair", "day"]).drop_duplicates().sort_values(["pair", "day"]).reset_index(drop=True)


def book_filter_sql(moments: pd.DataFrame, quoted_from: str) -> str:
    """The export's BOOK_FILTER: per symbol, the union of [T − 60 s, T + 300 s] ranges (adjacent
    ranges merged, minute precision — T sits on the 5-minute grid), restricted to moments at or
    after the ladder table's first day. Pasted after `WHERE ts >= FROM AND ts < TO`. Kept compact:
    the script ships the query base64-encoded inside ONE remote-shell argument (128 KB on Linux)."""
    q0 = pd.Timestamp(quoted_from, tz="UTC").value
    m = moments[moments["T"] >= q0]
    groups = []
    for sym, g in m.groupby("pair", sort=True):
        lo, hi = merge_intervals(g["T"].to_numpy(np.int64) - 60 * NS, g["T"].to_numpy(np.int64) + 300 * NS)
        rngs = [f"(ts>='{pd.Timestamp(a).strftime('%Y-%m-%d %H:%M')}' AND ts<'{pd.Timestamp(b).strftime('%Y-%m-%d %H:%M')}')"
                for a, b in zip(lo, hi)]
        groups.append(f"(symbol='{sym}' AND ({' OR '.join(rngs)}))")
    return "AND (" + " OR ".join(groups) + ")" if groups else "AND false"


QUOTED_FROM = "2026-08-05"   # choice (a): orderbook_levels' first day


def run_entries(ledger_path: str | None = None) -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    a = stratum_a()
    _p(f"stratum A: {len(a)} trades at cov {A_COVERAGE} on {P1_RUN} s3, "
       f"{pd.Timestamp(a['entry_ts'].min()).strftime('%Y-%m-%d %H:%M')} → "
       f"{pd.Timestamp(a['entry_ts'].max()).strftime('%Y-%m-%d %H:%M')} UTC, "
       f"sides {a['side'].value_counts().to_dict()}, per pair {a['pair'].value_counts().sort_index().to_dict()}")
    ca = sidetable.load_candles("5m", export_dir=WF_SIDE)
    a = candle_match(a, ca, "A")
    b, live = stratum_b(ledger_path)
    cb_path = os.path.join(BOOK_DIR, "candles_5m.csv.gz")
    if os.path.exists(cb_path):
        b = candle_match(b, sidetable.load_candles("5m", export_dir=BOOK_DIR), "B")
    else:
        _p("B: no candle export yet (BOOK_DIR/candles_5m.csv.gz) — the ledger's own prices stand in; "
           "the candle pin runs at `read` once the export exists")
        b["entry_close"], b["exit_close"] = b["ledger_entry_price"], np.nan
        b["entry_T"], b["exit_T"] = b["entry_ts"] + DECISION_OFFSET_NS, b["exit_ts"] + DECISION_OFFSET_NS
        b["tid"] = [f"{s}:{ar}:{p}:{e}" for s, ar, p, e in zip(b["stratum"], b["arm"], b["pair"], b["entry_ts"])]
    trades = pd.concat([a, b], ignore_index=True)
    trades.to_parquet(os.path.join(OUT_DIR, "entries.parquet"), index=False)
    live.to_parquet(os.path.join(OUT_DIR, "pilot_fills.parquet"), index=False)
    m = moments_of(trades)
    m.to_parquet(os.path.join(OUT_DIR, "moments.parquet"), index=False)
    pdays = pair_days(m)
    pdays.to_parquet(os.path.join(OUT_DIR, "pair_days.parquet"), index=False)
    sql = book_filter_sql(m, QUOTED_FROM)
    with open(os.path.join(OUT_DIR, "book_filter.sql"), "w") as f:
        f.write(sql + "\n")
    nq = int((m["T"] >= pd.Timestamp(QUOTED_FROM, tz="UTC").value).sum())
    _p(f"moments: {len(m)} ({nq} on or after {QUOTED_FROM} → the quoted leg's export, {len(m) - nq} tape-only); "
       f"pair-days to fetch: {len(pdays)}; BOOK_FILTER {len(sql) // 1024} KB with {nq} ranges → {OUT_DIR}/book_filter.sql")
    _p(f"next: FROM={QUOTED_FROM} TO=<tomorrow> OUT=$PWD/ml/train/{BOOK_DIR} ONLY=book_raw,candles_5m "
       f"BOOK_FILTER=\"$(cat ml/train/{OUT_DIR}/book_filter.sql)\" ./scripts/gcp_m3_export.sh")
    return 0


# --------------------------------------------------------------------------------------
# fetch — archive aggTrades, streamed and cut to the windows
# --------------------------------------------------------------------------------------

def _agg_key(sym: str, day: str) -> str:
    return f"data/futures/um/daily/aggTrades/{sym}/{sym}-aggTrades-{day}.zip"


def parse_aggtrades(raw_zip: bytes) -> pd.DataFrame:
    """The daily aggTrades CSV: (ts_ns, price, qty, buyer_maker). `transact_time` is ms (µs if
    > 1e14 — the same guard archiveprem uses). `is_buyer_maker` true ⇒ the aggressor SOLD, so the
    print sits at the bid."""
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zz:
        with zz.open(zz.namelist()[0]) as fh:
            head = fh.read(64)
        with zz.open(zz.namelist()[0]) as fh:
            df = pd.read_csv(fh, header=0 if head.lstrip().lower().startswith(b"agg_trade_id") else None,
                             usecols=[1, 2, 5, 6], names=None if head.lstrip().lower().startswith(b"agg_trade_id")
                             else ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
                                   "transact_time", "is_buyer_maker"],
                             dtype={"price": np.float64, "quantity": np.float64, "transact_time": np.int64})
    t = df["transact_time"].to_numpy(np.int64)
    ts = t * 1_000 if t.size and t.max() > 10**14 else t * 1_000_000
    bm = df["is_buyer_maker"]
    if bm.dtype != bool:
        bm = bm.astype(str).str.lower().isin(["true", "1"])
    return pd.DataFrame({"ts": ts, "price": df["price"].to_numpy(np.float64),
                         "qty": df["quantity"].to_numpy(np.float64), "buyer_maker": bm.to_numpy(bool)})


def merge_intervals(lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    o = np.argsort(lo, kind="mergesort")
    lo, hi = lo[o], hi[o]
    mlo, mhi = [lo[0]], [hi[0]]
    for a, b in zip(lo[1:], hi[1:]):
        if a <= mhi[-1]:
            mhi[-1] = max(mhi[-1], b)
        else:
            mlo.append(a); mhi.append(b)
    return np.asarray(mlo), np.asarray(mhi)


def cut_windows(tape: pd.DataFrame, moments_T: np.ndarray) -> pd.DataFrame:
    """Keep exactly the rows with ts in some [T − TAPE_PRE_S, T + TAPE_POST_S] (closed)."""
    if tape.empty or moments_T.size == 0:
        return tape.iloc[:0]
    lo, hi = merge_intervals(moments_T - TAPE_PRE_S * NS, moments_T + TAPE_POST_S * NS)
    ts = tape["ts"].to_numpy(np.int64)
    i = np.searchsorted(lo, ts, side="right") - 1
    keep = (i >= 0) & (ts <= hi[np.clip(i, 0, None)])
    return tape[keep].reset_index(drop=True)


def fetch_pair_day(sym: str, day: str, moments_T: np.ndarray) -> tuple[str, str, str, int]:
    out = os.path.join(TAPE_DIR, sym, f"{day}.parquet")
    if os.path.exists(out + ".ok"):
        return sym, day, "cached", -1
    if os.path.exists(out + ".missing"):
        return sym, day, "missing", 0
    os.makedirs(os.path.dirname(out), exist_ok=True)
    key = _agg_key(sym, day)
    blob = _get(DL + key)
    if blob is None:
        open(out + ".missing", "w").close()
        return sym, day, "missing", 0
    chk = _get(DL + key + ".CHECKSUM")
    if chk is None:
        raise RuntimeError(f"{key}: zip present, CHECKSUM absent")
    want = chk.decode().split()[0].lower()
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise RuntimeError(f"{key}: sha256 {got} != {want}")
    tape = parse_aggtrades(blob)
    del blob
    n_all = len(tape)
    cut = cut_windows(tape, moments_T)
    cut["pair"] = sym
    cut.to_parquet(out, index=False)
    with open(out + ".ok", "w") as f:
        f.write(f"{n_all} rows in the day, {len(cut)} kept\n")
    return sym, day, "ok", len(cut)


def run_fetch(threads: int = 4) -> int:
    m = pd.read_parquet(os.path.join(OUT_DIR, "moments.parquet"))
    pdays = pd.read_parquet(os.path.join(OUT_DIR, "pair_days.parquet"))
    by_pair = {p: g["T"].to_numpy(np.int64) for p, g in m.groupby("pair")}
    jobs = [(p, d, by_pair[p]) for p, d in zip(pdays["pair"], pdays["day"])]
    _p(f"fetch: {len(jobs)} pair-days, {threads} threads, windows [T−{TAPE_PRE_S}s, T+{TAPE_POST_S}s]")
    t0, n_ok, n_cached, n_missing, kept = time.time(), 0, 0, 0, 0
    with ThreadPoolExecutor(threads) as ex:
        for i, (sym, day, st, n) in enumerate(ex.map(lambda j: fetch_pair_day(*j), jobs), 1):
            if st == "ok":
                n_ok += 1; kept += n
            elif st == "cached":
                n_cached += 1
            else:
                n_missing += 1
                _p(f"  missing: {sym} {day}")
            if i % 100 == 0 or i == len(jobs):
                _p(f"  {i}/{len(jobs)} — fetched {n_ok}, cached {n_cached}, missing {n_missing}, "
                   f"rows kept this run {kept:,}, {time.time() - t0:.0f}s")
    frames = []
    for sym in sorted(pdays["pair"].unique()):
        d = os.path.join(TAPE_DIR, sym)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".parquet") and os.path.exists(os.path.join(d, f + ".ok")):
                frames.append(pd.read_parquet(os.path.join(d, f)))
    tape = pd.concat(frames, ignore_index=True).sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    out = os.path.join(OUT_DIR, "tape_windows.parquet")
    tape.to_parquet(out, index=False)
    sz = os.path.getsize(out) / 1e6
    _p(f"tape_windows.parquet: {len(tape):,} rows, {sz:.0f} MB, per pair "
       f"{tape.groupby('pair').size().to_dict()}; missing pair-days {n_missing}")
    return 0


# --------------------------------------------------------------------------------------
# The two quote sources
# --------------------------------------------------------------------------------------

@dataclass
class Tape:
    ts: dict[str, np.ndarray]
    price: dict[str, np.ndarray]
    qty: dict[str, np.ndarray]
    bm: dict[str, np.ndarray]
    tick: dict[str, float]

    @classmethod
    def load(cls, path: str | None = None) -> "Tape":
        df = pd.read_parquet(path or os.path.join(OUT_DIR, "tape_windows.parquet"))
        ts, pr, q, bm, tick = {}, {}, {}, {}, {}
        for p, g in df.groupby("pair"):
            g = g.sort_values("ts", kind="mergesort")
            ts[p] = g["ts"].to_numpy(np.int64); pr[p] = g["price"].to_numpy(np.float64)
            q[p] = g["qty"].to_numpy(np.float64); bm[p] = g["buyer_maker"].to_numpy(bool)
            u = np.unique(pr[p])
            d = np.diff(u)
            tick[p] = float(d[d > 0].min()) if (d > 0).any() else np.nan
        return cls(ts, pr, q, bm, tick)

    def touch(self, pair: str, T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Tape-implied (P_bid, P_ask) at each T: the last buyer-maker print (aggressor sold → at
        the bid) and the last non-buyer-maker print (at the ask) in [T − 60 s, T]; NaN if none."""
        ts, pr, bm = self.ts[pair], self.price[pair], self.bm[pair]
        bid, ask = np.full(len(T), np.nan), np.full(len(T), np.nan)
        idx_b = np.flatnonzero(bm); idx_a = np.flatnonzero(~bm)
        for arr, out in ((idx_b, bid), (idx_a, ask)):
            if arr.size == 0:
                continue
            sub_ts = ts[arr]
            j = np.searchsorted(sub_ts, T, side="right") - 1
            ok = (j >= 0) & (sub_ts[np.clip(j, 0, None)] >= T - TOUCH_LOOKBACK_S * NS)
            out[ok] = pr[arr[j[ok]]]
        return bid, ask

    def window_agg(self, pair: str, T: np.ndarray, w_s: int) -> dict[str, np.ndarray]:
        """§2.3's aggregates over the prints in (T, T + W]: high, low, buy_volume (aggressor
        bought), sell_volume (aggressor sold), n_rows — uncensored, per print."""
        ts, pr, q, bm = self.ts[pair], self.price[pair], self.qty[pair], self.bm[pair]
        a = np.searchsorted(ts, T, side="right")
        b = np.searchsorted(ts, T + w_s * NS, side="right")
        n = len(T)
        hi, lo = np.full(n, np.nan), np.full(n, np.nan)
        bv, sv, nr = np.zeros(n), np.zeros(n), (b - a).astype(np.int64)
        for k in range(n):
            if b[k] > a[k]:
                s = slice(a[k], b[k])
                hi[k], lo[k] = pr[s].max(), pr[s].min()
                m = bm[s]
                sv[k] = q[s][m].sum(); bv[k] = q[s][~m].sum()
        return {"high": hi, "low": lo, "buy_volume": bv, "sell_volume": sv, "n_rows": nr}

    def through(self, pair: str, T: np.ndarray, w_s: int, side: np.ndarray, rest: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Branch 1 on the tape: a print strictly THROUGH the resting price within W (filled), and
        the optimistic touch rule (a print AT or better) — information only."""
        agg = self.window_agg(pair, T, w_s)
        buy = side > 0
        through = np.where(buy, agg["low"] < rest, agg["high"] > rest)
        at = np.where(buy, agg["low"] <= rest, agg["high"] >= rest)
        quiet = np.isnan(agg["low"])
        return through & ~quiet, at & ~quiet


@dataclass
class Book:
    ts: dict[str, np.ndarray]
    arr: dict[str, dict[str, np.ndarray]]      # bid_p, bid_q, ask_p, ask_q per pair

    @classmethod
    def load(cls, export_dir: str = BOOK_DIR) -> "Book | None":
        pq = os.path.join(export_dir, "ladder_wide20.parquet")
        raw = os.path.join(export_dir, "book_raw.csv.gz")
        if not os.path.exists(pq):
            if not os.path.exists(raw):
                return None
            from .ladderspan import _parse_side
            frames = []
            for chunk in pd.read_csv(raw, chunksize=5_000):
                cols = {"symbol": chunk["symbol"].to_numpy(),
                        "ts": pd.to_datetime(chunk["ts"], utc=True, format="ISO8601").to_numpy("datetime64[ns]").astype(np.int64)}
                cols.update(_parse_side(chunk["bids"], "b", LEVELS))
                cols.update(_parse_side(chunk["asks"], "a", LEVELS))
                frames.append(pd.DataFrame(cols))
            wide = pd.concat(frames, ignore_index=True).sort_values(["symbol", "ts"], kind="mergesort")
            wide.to_parquet(pq, index=False)
        wide = pd.read_parquet(pq)
        ts, arr = {}, {}
        for p, g in wide.groupby("symbol"):
            g = g.sort_values("ts", kind="mergesort")
            ts[p] = g["ts"].to_numpy(np.int64)
            arr[p] = execcost.ladder_arrays(g, LEVELS)
        return cls(ts, arr)

    def anchor(self, pair: str, T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if pair not in self.ts:
            return np.full(len(T), -1), np.full(len(T), np.inf)
        return execcost.anchor(self.ts[pair], T)

    def at(self, pair: str, idx: np.ndarray) -> dict[str, np.ndarray]:
        a = self.arr[pair]
        i = np.clip(idx, 0, None)
        return {k: a[k][i] for k in a}


# --------------------------------------------------------------------------------------
# Pricing one moment on each leg
# --------------------------------------------------------------------------------------

def _fill_price_taker_book(side: np.ndarray, bk: dict, size_usd: float, mid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    need = size_usd / mid
    vb, xb = execcost.walk(bk["ask_p"], bk["ask_q"], need)      # a buy walks the asks
    vs, xs = execcost.walk(bk["bid_p"], bk["bid_q"], need)
    return np.where(side > 0, vb, vs), np.where(side > 0, xb, xs)


def price_moments_quoted(book: Book, tape: Tape, pair: str, T: np.ndarray, side: np.ndarray,
                         w_s: int, size_usd: float) -> pd.DataFrame:
    """Both arms' fill prices at each moment on the QUOTED leg. Kept iff the T and T+W anchors are
    both ≤ 30 s old (§2.7's identical-set rule). Fill test: M3-4 §2.3's three branches on the
    uncensored tape, Q₀ = displayed size at the touch."""
    i0, age0 = book.anchor(pair, T)
    i1, age1 = book.anchor(pair, T + w_s * NS)
    fresh = (age0 <= STALE_S) & (age1 <= STALE_S)
    n = len(T)
    out = pd.DataFrame({"T": T, "side": side, "fresh": fresh})
    b0, b1 = book.at(pair, i0), book.at(pair, i1)
    bid0, ask0 = b0["bid_p"][:, 0], b0["ask_p"][:, 0]
    mid = 0.5 * (bid0 + ask0)
    rest = np.where(side > 0, bid0, ask0)
    q0 = np.where(side > 0, b0["bid_q"][:, 0], b0["ask_q"][:, 0])
    size_base = size_usd / mid
    agg = tape.window_agg(pair, T, w_s) if pair in tape.ts else \
        {"high": np.full(n, np.nan), "low": np.full(n, np.nan), "buy_volume": np.zeros(n), "sell_volume": np.zeros(n), "n_rows": np.zeros(n, int)}
    fb = execcost.fill_branch(+1, rest, q0, size_base, agg)
    fs = execcost.fill_branch(-1, rest, q0, size_base, agg)
    filled = np.where(side > 0, fb["filled"], fs["filled"])
    certain = np.where(side > 0, fb["certain"], fs["certain"])
    queued = np.where(side > 0, fb["queued"], fs["queued"])
    taker_px, taker_x = _fill_price_taker_book(side, b0, size_usd, mid)
    late_px, late_x = _fill_price_taker_book(side, b1, size_usd, mid)
    out["mid"], out["rest"], out["q0"], out["tape_rows"] = mid, rest, q0, agg["n_rows"]
    out["spread_bps"] = BPS * (ask0 - bid0) / mid
    out["taker_px"], out["taker_exhausted"] = taker_px, taker_x
    out["filled"], out["certain"], out["queued"] = filled, certain, queued
    out["touched"] = np.where(side > 0, fb["touched_at"], fs["touched_at"])
    out["maker_px"] = np.where(filled, rest, late_px)
    out["maker_fee"] = np.where(filled, MAKER_FEE, TAKER_FEE)
    out["maker_exhausted"] = np.where(filled, False, late_x)
    out["leg"] = "quoted"
    out.loc[~fresh, ["taker_px", "maker_px"]] = np.nan
    out["book_age_s"], out["book_age_w_s"] = age0, age1
    return out


def price_moments_tape(tape: Tape, pair: str, T: np.ndarray, side: np.ndarray, w_s: int, size_usd: float) -> pd.DataFrame:
    """Both arms on the TAPE leg: the touch read off the prints; branch 1 only (no Q₀ exists, so
    queue-conditional fills count as unfilled — the conservative side); taker fills AT the touch
    (no walk; sizes over $1,000 are not scored here); an unfilled rest crosses the T+W touch."""
    n = len(T)
    bid0, ask0 = tape.touch(pair, T)
    bid1, ask1 = tape.touch(pair, T + w_s * NS)
    mid = 0.5 * (bid0 + ask0)
    rest = np.where(side > 0, bid0, ask0)
    through, at = tape.through(pair, T, w_s, side, rest)
    fresh = ~np.isnan(bid0) & ~np.isnan(ask0) & ~np.isnan(bid1) & ~np.isnan(ask1)
    taker_px = np.where(side > 0, ask0, bid0)
    late_px = np.where(side > 0, ask1, bid1)
    out = pd.DataFrame({"T": T, "side": side, "fresh": fresh, "mid": mid, "rest": rest,
                        "q0": np.nan, "tape_rows": tape.window_agg(pair, T, w_s)["n_rows"],
                        "spread_bps": BPS * (ask0 - bid0) / mid,
                        "taker_px": taker_px, "taker_exhausted": size_usd > SIZE_PRIMARY,
                        "filled": through, "certain": through, "queued": False, "touched": at,
                        "maker_px": np.where(through, rest, late_px),
                        "maker_fee": np.where(through, MAKER_FEE, TAKER_FEE),
                        "maker_exhausted": False, "leg": "tape",
                        "book_age_s": np.nan, "book_age_w_s": np.nan})
    out.loc[~fresh, ["taker_px", "maker_px"]] = np.nan
    return out


def price_all_moments(moments: pd.DataFrame, book: Book | None, tape: Tape, w_s: int, size_usd: float,
                      force_leg: str | None = None) -> pd.DataFrame:
    """Every moment on its own leg: quoted where a fresh ladder exists (choice (a)), tape else."""
    parts = []
    for pair, g in moments.groupby("pair", sort=True):
        T, side = g["T"].to_numpy(np.int64), g["side"].to_numpy(int)
        if pair not in tape.ts:
            continue
        tp = price_moments_tape(tape, pair, T, side, w_s, size_usd)
        if book is not None and force_leg != "tape" and pair in book.ts:
            qt = price_moments_quoted(book, tape, pair, T, side, w_s, size_usd)
            use_q = qt["fresh"].to_numpy(bool)
            pr = tp.copy()
            cols = [c for c in qt.columns if c in pr.columns]
            pr.loc[use_q, cols] = qt.loc[use_q, cols].to_numpy()
            pr["leg"] = np.where(use_q, "quoted", "tape")
            pr["book_seen"] = True
        else:
            pr = tp
            pr["book_seen"] = False
        pr["pair"], pr["role"], pr["tid"] = pair, g["role"].to_numpy(), g["tid"].to_numpy()
        parts.append(pr)
    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------------------------------------------
# From priced moments to per-trade arm returns
# --------------------------------------------------------------------------------------

def trade_returns(trades: pd.DataFrame, priced: pd.DataFrame) -> pd.DataFrame:
    """Per trade: entry and exit fills under each arm → net return in bps of notional, fees
    inside (choice (d)). A trade is kept iff both moments priced (fresh on some leg)."""
    e = priced[priced["role"] == "entry"].set_index("tid")
    x = priced[priced["role"] == "exit"].set_index("tid")
    t = trades.set_index("tid")
    common = t.index.intersection(e.index).intersection(x.index)
    t, e, x = t.loc[common], e.loc[common], x.loc[common]
    side = t["side"].to_numpy(int)
    keep = e["fresh"].to_numpy(bool) & x["fresh"].to_numpy(bool)
    out = pd.DataFrame(index=common)
    out["pair"], out["side"], out["size"], out["stratum"], out["arm"] = t["pair"], side, t["size"], t["stratum"], t["arm"]
    out["entry_T"], out["exit_T"] = t["entry_T"], t["exit_T"]
    out["exit_day"] = wf._utc_day(t["exit_T"].to_numpy(np.int64))
    out["kept"] = keep
    out["leg"] = np.where((e["leg"] == "quoted") & (x["leg"] == "quoted"), "quoted", "tape")
    out["entry_leg"], out["exit_leg"] = e["leg"].to_numpy(), x["leg"].to_numpy()
    te, tx = e["taker_px"].to_numpy(), x["taker_px"].to_numpy()
    me, mx = e["maker_px"].to_numpy(), x["maker_px"].to_numpy()
    out["taker_ret_bps"] = side * (tx / te - 1) * BPS - 2 * TAKER_FEE
    out["maker_ret_bps"] = side * (mx / me - 1) * BPS - e["maker_fee"].to_numpy() - x["maker_fee"].to_numpy()
    out["s1_bps"] = out["maker_ret_bps"] - out["taker_ret_bps"]
    out["entry_filled"], out["exit_filled"] = e["filled"].to_numpy(bool), x["filled"].to_numpy(bool)
    out["entry_certain"], out["exit_certain"] = e["certain"].to_numpy(bool), x["certain"].to_numpy(bool)
    out["entry_queued"], out["exit_queued"] = e["queued"].to_numpy(bool), x["queued"].to_numpy(bool)
    out["exhausted"] = (e["taker_exhausted"].to_numpy(bool) | x["taker_exhausted"].to_numpy(bool)
                        | e["maker_exhausted"].to_numpy(bool) | x["maker_exhausted"].to_numpy(bool))
    # the entry-side and exit-side cost contributions, in bps of the moment mid (positive = cost),
    # so the contrast can be split into "where the maker path earned or lost"
    out["entry_taker_cost"] = side * (te / e["mid"].to_numpy() - 1) * BPS + TAKER_FEE
    out["entry_maker_cost"] = side * (me / e["mid"].to_numpy() - 1) * BPS + e["maker_fee"].to_numpy()
    out["exit_taker_cost"] = -side * (tx / x["mid"].to_numpy() - 1) * BPS + TAKER_FEE
    out["exit_maker_cost"] = -side * (mx / x["mid"].to_numpy() - 1) * BPS + x["maker_fee"].to_numpy()
    out["candle_ret_bps"] = side * (t["exit_close"] / t["entry_close"] - 1) * BPS
    return out.reset_index()


def ledger(tr: pd.DataFrame, col: str, weight: str) -> pd.DataFrame:
    notional = np.full(len(tr), SIZE_PRIMARY) if weight == "equal" else tr["size"].to_numpy(np.float64) * SIZE_PRIMARY
    gross = notional * tr[col].to_numpy(np.float64) / BPS
    return wf._ledger(tr["exit_day"].to_numpy(), gross, notional, "trade")


def s1(tr: pd.DataFrame, weight: str = "equal") -> dict:
    c = wf.paired_notional_diff_bps(ledger(tr, "maker_ret_bps", weight), ledger(tr, "taker_ret_bps", weight))
    c["n"] = int(len(tr))
    return c


def _ci(c: dict) -> str:
    return (f"{c['diff_bps']:+.2f} bps  [{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}]  "
            f"(n={c['n']}, exit-day clusters {c['clusters']})")


# --------------------------------------------------------------------------------------
# calibrate — the prerequisite
# --------------------------------------------------------------------------------------

def run_calibrate() -> int:
    moments = pd.read_parquet(os.path.join(OUT_DIR, "moments.parquet"))
    tape = Tape.load()
    book = Book.load()
    if book is None:
        raise SystemExit(f"no ladder export in {BOOK_DIR} — run the gcp_m3_export step first")
    rows, per = [], {}
    for pair, g in moments.groupby("pair", sort=True):
        if pair not in tape.ts or pair not in book.ts:
            continue
        T, side = g["T"].to_numpy(np.int64), g["side"].to_numpy(int)
        i0, age0 = book.anchor(pair, T)
        fresh = age0 <= STALE_S
        if not fresh.any():
            continue
        b = book.at(pair, i0)
        bid_b, ask_b = b["bid_p"][:, 0], b["ask_p"][:, 0]
        bid_t, ask_t = tape.touch(pair, T)
        tick = tape.tick[pair]
        have = fresh & ~np.isnan(bid_t) & ~np.isnan(ask_t)
        # branch-1 verdict from each touch, for the moment's resting side, W = 60
        rest_b = np.where(side > 0, bid_b, ask_b)
        rest_t = np.where(side > 0, bid_t, ask_t)
        thr_b, _ = tape.through(pair, T, W_PRIMARY, side, rest_b)
        thr_t, _ = tape.through(pair, T, W_PRIMARY, side, rest_t)
        for s_name, pb, pt in (("bid", bid_b, bid_t), ("ask", ask_b, ask_t)):
            ok = have
            within = np.abs(pt[ok] - pb[ok]) <= tick * 1.0001
            per[(pair, s_name)] = {"n": int(ok.sum()), "within_tick": float(within.mean()) if ok.any() else np.nan,
                                   "tick": tick, "median_abs_ticks": float(np.median(np.abs(pt[ok] - pb[ok]) / tick)) if ok.any() else np.nan}
        agree = (thr_b == thr_t)[have]
        per[(pair, "fill")] = {"n": int(have.sum()), "agree": float(agree.mean()) if have.any() else np.nan,
                               "fill_book": float(thr_b[have].mean()) if have.any() else np.nan,
                               "fill_tape": float(thr_t[have].mean()) if have.any() else np.nan}
        rows.append(pd.DataFrame({"pair": pair, "T": T[have], "side": side[have], "bid_book": bid_b[have], "bid_tape": bid_t[have],
                                  "ask_book": ask_b[have], "ask_tape": ask_t[have], "thr_book": thr_b[have], "thr_tape": thr_t[have]}))
    cal = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    cal.to_parquet(os.path.join(OUT_DIR, "calibration_moments.parquet"), index=False)
    n_total = len(cal)
    _p("=" * 96)
    _p(f"M1 PREREQUISITE — the tape-implied touch against the collector's book, {n_total} quoted-leg moments "
       f"(registered expectation ≥ {CAL_MIN_MOMENTS}); PASS iff every pair-side ≥ {CAL_TOUCH_SHARE:.0%} within one tick "
       f"AND the branch-1 verdict agrees on ≥ {CAL_FILL_SHARE:.0%} per pair")
    _p(f"{'pair':<13}{'n':>6}{'tick':>12}{'bid≤1tick':>11}{'ask≤1tick':>11}{'med|Δ|bid':>11}{'med|Δ|ask':>11}{'fill agree':>12}{'fill book':>11}{'fill tape':>11}  verdict")
    passes, fails = [], []
    for pair in sorted({k[0] for k in per}):
        b, a, f = per[(pair, "bid")], per[(pair, "ask")], per[(pair, "fill")]
        ok = b["within_tick"] >= CAL_TOUCH_SHARE and a["within_tick"] >= CAL_TOUCH_SHARE and f["agree"] >= CAL_FILL_SHARE
        (passes if ok else fails).append(pair)
        _p(f"{pair:<13}{f['n']:>6}{b['tick']:>12.6g}{b['within_tick']:>11.3f}{a['within_tick']:>11.3f}{b['median_abs_ticks']:>11.2f}"
           f"{a['median_abs_ticks']:>11.2f}{f['agree']:>12.3f}{f['fill_book']:>11.3f}{f['fill_tape']:>11.3f}  {'PASS' if ok else 'FAIL'}")
    verdict = "PASS" if (not fails and n_total >= CAL_MIN_MOMENTS and passes) else "FAIL"
    if n_total < CAL_MIN_MOMENTS:
        _p(f"  fewer than {CAL_MIN_MOMENTS} quoted moments ({n_total}) — the bar cannot be read as registered; FAIL by count")
    _p(f"PREREQUISITE {verdict}" + ("" if verdict == "PASS" else
       f" — the tape leg is reported descriptively only; the decision is read on the quoted leg alone (pairs failing: {fails})"))
    with open(os.path.join(OUT_DIR, "calibration.json"), "w") as fh:
        json.dump({"verdict": verdict, "n_moments": n_total, "fails": fails, "passes": passes,
                   "per": {f"{k[0]}:{k[1]}": v for k, v in per.items()}}, fh, indent=1, default=float)
    return 0 if verdict == "PASS" else 3


# --------------------------------------------------------------------------------------
# Harness checks
# --------------------------------------------------------------------------------------

def check_m34_ctaker() -> list[str]:
    """Choice (h): this module's walk on M3-4's exported book reproduces §1's C_taker per pair
    (round trip at $10,000, fee 4.0, the 5-minute grid, both anchors fresh) within ±1.0 bps."""
    lines = []
    pq = os.path.join(M34_BOOK, "book_top20.parquet")
    if not os.path.exists(pq):
        return [f"check 2 SKIPPED: {pq} absent"]
    bk = pd.read_parquet(pq)
    bk["ts_ns"] = pd.to_datetime(bk["ts"], utc=True).to_numpy("datetime64[ns]").astype(np.int64)
    ok_all = True
    for pair, ref in M34_C_TAKER.items():
        g = bk[bk["symbol"] == pair].sort_values("ts_ns")
        if g.empty:
            lines.append(f"  {pair:<13} no book rows"); ok_all = False; continue
        ts = g["ts_ns"].to_numpy(np.int64)
        lo = (ts.min() // BAR_NS + 1) * BAR_NS
        grid = np.arange(lo, ts.max(), BAR_NS)
        i0, a0 = execcost.anchor(ts, grid)
        i1, a1 = execcost.anchor(ts, grid + W_PRIMARY * NS)
        fresh = (a0 <= STALE_S) & (a1 <= STALE_S)
        arr = execcost.ladder_arrays(g, LEVELS)
        i = i0[fresh]
        bid, ask = arr["bid_p"][i, 0], arr["ask_p"][i, 0]
        mid = 0.5 * (bid + ask)
        need = SIZE_LADDER[1] / mid
        vb, xb = execcost.walk(arr["ask_p"][i], arr["ask_q"][i], need)
        vs, xs = execcost.walk(arr["bid_p"][i], arr["bid_q"][i], need)
        keep = ~(xb | xs)
        rt = BPS * (vb - mid) / mid + M34_FEE + BPS * (mid - vs) / mid + M34_FEE
        c = float(np.mean(rt[keep]))
        ok = abs(c - ref) <= 1.0
        ok_all &= ok
        lines.append(f"  {pair:<13} n={int(keep.sum()):>5}  C_taker here {c:7.3f}  M3-4 §1 {ref:7.3f}  Δ {c - ref:+.3f}  {'ok' if ok else 'OFF'}")
    lines.insert(0, f"check 2 — M3-4 §1's C_taker reproduced within ±1.0 bps on the m3_4 book: {'PASS' if ok_all else 'FAIL'}")
    return lines


def check_tape_counts(tape: Tape, moments: pd.DataFrame) -> list[str]:
    """The uncensored tape against the collector's capped polls, on the 5-minute bar [T, T + 300 s)
    that every retained window holds whole: the archive's VOLUME per bar must be ≥ the collector's
    `volume` summed over the polls stamped inside the bar (the polls are capped at 200 aggTrades and
    need not tile the bar, so ≤ is the only direction a sound archive can show); the print counts
    are printed beside in both units."""
    path = "output/book_era2/trades.parquet"
    if not os.path.exists(path):
        return ["check 3 SKIPPED: no collector tape at output/book_era2/trades.parquet"]
    col = pd.read_parquet(path)
    col["ws"] = pd.to_datetime(col["window_start"], utc=True).to_numpy("datetime64[ns]").astype(np.int64)
    n_bars, n_bad, worst, ratios = 0, 0, 0.0, []
    for pair, g in col.groupby("symbol"):
        if pair not in tape.ts:
            continue
        T = np.unique(moments.loc[moments["pair"] == pair, "T"].to_numpy(np.int64))
        ws = g["ws"].to_numpy(np.int64)
        o = np.argsort(ws); ws, vol, cnt = ws[o], g["volume"].to_numpy(np.float64)[o], g["trade_count"].to_numpy(np.float64)[o]
        cv, cc = np.cumsum(np.r_[0.0, vol]), np.cumsum(np.r_[0.0, cnt])
        a, b = np.searchsorted(ws, T, "left"), np.searchsorted(ws, T + BAR_NS, "left")
        col_vol, col_cnt = cv[b] - cv[a], cc[b] - cc[a]
        ts, q = tape.ts[pair], tape.qty[pair]
        cq = np.cumsum(np.r_[0.0, q])
        a2, b2 = np.searchsorted(ts, T, "left"), np.searchsorted(ts, T + BAR_NS, "left")
        arch_vol, arch_cnt = cq[b2] - cq[a2], (b2 - a2).astype(float)
        sel = (b > a) & (arch_cnt > 0)
        n_bars += int(sel.sum())
        bad = arch_vol[sel] < col_vol[sel] * (1 - 1e-6)
        n_bad += int(bad.sum())
        if sel.any():
            worst = max(worst, float((col_vol[sel] / np.maximum(arch_vol[sel], 1e-12)).max()))
            ratios.append(float(np.median(col_cnt[sel] / arch_cnt[sel])))
    return [f"check 3 — archive volume per 5m bar ≥ the collector's polled volume: {n_bars - n_bad}/{n_bars} bars "
            f"({'PASS' if n_bad == 0 else 'FAIL'}; max collector/archive volume ratio {worst:.3f}; "
            f"the collector's trade_count per bar is {np.median(ratios):.2f}× the archive's aggTrades count at the median — "
            f"different units if > 1 (raw fills vs aggregated prints), a cap if < 1)"]


# --------------------------------------------------------------------------------------
# read
# --------------------------------------------------------------------------------------

def _fill_table(tr: pd.DataFrame, label: str) -> list[str]:
    out = [f"  {label}: n={len(tr)}"]
    for role in ("entry", "exit"):
        f, c, q = tr[f"{role}_filled"].mean(), tr[f"{role}_certain"].mean(), tr[f"{role}_queued"].mean()
        out.append(f"    {role:<5} fill {f:.3f} (certain {c:.3f}, queue-conditional {q:.3f})")
    return out


def _cost_split(tr: pd.DataFrame) -> list[str]:
    def m(c):
        return float(np.nanmean(tr[c]))
    return [f"    entry: taker cost {m('entry_taker_cost'):+.2f}  maker path {m('entry_maker_cost'):+.2f}  (saving {m('entry_taker_cost') - m('entry_maker_cost'):+.2f})",
            f"    exit : taker cost {m('exit_taker_cost'):+.2f}  maker path {m('exit_maker_cost'):+.2f}  (saving {m('exit_taker_cost') - m('exit_maker_cost'):+.2f})",
            f"    taker arm net {m('taker_ret_bps'):+.2f}  maker arm net {m('maker_ret_bps'):+.2f}  candle return {m('candle_ret_bps'):+.2f} (fees out)"]


def run_read() -> int:
    trades = pd.read_parquet(os.path.join(OUT_DIR, "entries.parquet"))
    moments = pd.read_parquet(os.path.join(OUT_DIR, "moments.parquet"))
    cal_path = os.path.join(OUT_DIR, "calibration.json")
    if not os.path.exists(cal_path):
        raise SystemExit("calibrate first — the prerequisite decides which leg the verdict reads")
    cal = json.load(open(cal_path))
    tape = Tape.load()
    book = Book.load()
    if book is None:
        raise SystemExit(f"no ladder export in {BOOK_DIR}")
    # B's candle pin, if entries ran before the export existed
    cb = os.path.join(BOOK_DIR, "candles_5m.csv.gz")
    if os.path.exists(cb) and trades.loc[trades["stratum"] == "B", "exit_close"].isna().all():
        b = trades[trades["stratum"] == "B"].drop(columns=["entry_close", "exit_close", "entry_T", "exit_T", "tid"])
        b = candle_match(b, sidetable.load_candles("5m", export_dir=BOOK_DIR), "B")
        trades = pd.concat([trades[trades["stratum"] == "A"], b], ignore_index=True)
    L = []
    L.append("=" * 96)
    L.append(f"M1 READ — the maker path on the policy's own entries; prerequisite {cal['verdict']} "
             f"({cal['n_moments']} quoted moments{'' if not cal['fails'] else ', failing ' + str(cal['fails'])})")
    L.append("harness checks:")
    L.extend(check_m34_ctaker())
    L.extend(check_tape_counts(tape, moments))
    results = {}
    priced_primary = None
    for w_s in (W_PRIMARY,) + W_SENS:
        for size in (SIZE_PRIMARY,) + SIZE_LADDER:
            pr = price_all_moments(moments, book, tape, w_s, size)
            tr = trade_returns(trades, pr)
            if size > SIZE_PRIMARY:
                tr = tr[tr["leg"] == "quoted"]          # the tape leg has no walk
            tr = tr[tr["kept"]]
            results[(w_s, size)] = tr
            if w_s == W_PRIMARY and size == SIZE_PRIMARY:
                priced_primary = pr
    tr0 = results[(W_PRIMARY, SIZE_PRIMARY)]
    assert set(tr0["tid"]) <= set(trades["tid"]), "arms on a trade outside the population"
    # check 1: identical trade sets under both arms — by construction one row carries both; say so
    L.append(f"check 1 — both arms priced on the identical trade set: {len(tr0)} trades, one row each (by construction)")
    n_a, n_b = int((trades['stratum'] == 'A').sum()), int((trades['stratum'] == 'B').sum())
    kept_a, kept_b = int((tr0['stratum'] == 'A').sum()), int((tr0['stratum'] == 'B').sum())
    L.append(f"population: A {n_a} trades ({kept_a} priced; legs {tr0[tr0['stratum']=='A']['leg'].value_counts().to_dict()}), "
             f"B {n_b} ({kept_b} priced; {tr0[tr0['stratum']=='B']['leg'].value_counts().to_dict()}); "
             f"dropped: {n_a + n_b - len(tr0)} (no touch at T or T+W on either leg, or a missing archive day)")
    L.append(f"exhausted ladders at $1,000 on the quoted leg: {int(tr0[tr0['leg']=='quoted']['exhausted'].sum())}")
    A = tr0[tr0["stratum"] == "A"]
    Bt = tr0[tr0["stratum"] == "B"]
    Bp = Bt[Bt["arm"] == "policy"]                      # the sign check is the policy arm's own entries
    deciding_A = A if cal["verdict"] == "PASS" else A[A["leg"] == "quoted"]
    deciding_B = Bp if cal["verdict"] == "PASS" else Bp[Bp["leg"] == "quoted"]
    cA, cB = s1(deciding_A), s1(deciding_B)
    L.append("")
    L.append(f"S1 = MAKER→TAKER − TAKER, net bps per unit notional, W = {W_PRIMARY} s, ${SIZE_PRIMARY:.0f}, equal notional, "
             f"exit-day clusters — on {'both legs' if cal['verdict'] == 'PASS' else 'the QUOTED leg alone'}:")
    L.append(f"  A (decides): {_ci(cA)}")
    L.append(f"  B (sign, the ledger's policy arm): {_ci(cB)}")
    worth = (cA["lo95_bps"] > 0) and (np.sign(cB["diff_bps"]) == np.sign(cA["diff_bps"])) and cA["n"] > 0
    verdict = "WORTH BUILDING" if worth else "NOT WORTH BUILDING"
    L.append(f"VERDICT: {verdict}  (rule: A's 95 % lower bound > 0 AND B's point estimate the same sign)")
    L.append("")
    L.append("sensitivities (never promote):")
    L.append(f"  A, size-weighted (the policy's own ladder): {_ci(s1(deciding_A, 'size'))}")
    for leg in ("quoted", "tape"):
        sub = A[A["leg"] == leg]
        if len(sub):
            L.append(f"  A, {leg} leg only: {_ci(s1(sub))}")
    for w_s in W_SENS:
        sub = results[(w_s, SIZE_PRIMARY)]; sub = sub[sub["stratum"] == "A"]
        sub = sub if cal["verdict"] == "PASS" else sub[sub["leg"] == "quoted"]
        L.append(f"  A, W = {w_s:>3} s: {_ci(s1(sub))}")
    for size in SIZE_LADDER:
        sub = results[(W_PRIMARY, size)]; sub = sub[sub["stratum"] == "A"]
        if size > SIZE_PRIMARY:
            sub = sub[~sub["exhausted"]]
        L.append(f"  A, ${size:,.0f}{' (quoted leg, unexhausted)' if size > SIZE_PRIMARY else ''}: {_ci(s1(sub))}")
    both = deciding_A[deciding_A["entry_filled"] & deciding_A["exit_filled"]]
    L.append(f"  A, filled-at-both-ends subset (DIAGNOSTIC, conditions on the fill, never decides): {_ci(s1(both))}")
    L.append("  B per ledger arm (explore_cov05 is the second line, not the sign check):")
    for arm, sub in (Bt if cal["verdict"] == "PASS" else Bt[Bt["leg"] == "quoted"]).groupby("arm"):
        L.append(f"    B {arm:<14} {_ci(s1(sub))}")
    L.append("  A per pair:")
    for pair, sub in deciding_A.groupby("pair"):
        L.append(f"    {pair:<13} {_ci(s1(sub))}   fill entry {sub['entry_filled'].mean():.2f} exit {sub['exit_filled'].mean():.2f}")
    L.append("  A per side:")
    for sd, sub in deciding_A.groupby("side"):
        L.append(f"    {'long ' if sd > 0 else 'short'} {_ci(s1(sub))}")
    L.append("")
    L.append("fill rates (W = 60 s, $1,000) — the registered expectation was BELOW M3-4's 70–92 %:")
    for leg in ("quoted", "tape"):
        sub = A[A["leg"] == leg]
        if len(sub):
            L.extend(_fill_table(sub, f"A {leg} leg"))
    if len(Bt):
        L.extend(_fill_table(Bt, "B"))
    L.append("where the contrast comes from (mean bps of the moment mid, positive = cost; A deciding set):")
    L.extend(_cost_split(deciding_A))
    # the pilot's measured taker entries against the model
    pil_path = os.path.join(OUT_DIR, "pilot_fills.parquet")
    if os.path.exists(pil_path) and priced_primary is not None:
        pil = pd.read_parquet(pil_path)
        pol = trades[(trades["stratum"] == "B") & (trades["arm"] == "policy")][["pair", "entry_ts", "ledger_entry_price", "tid"]]
        j = pil.merge(pol, on=["pair", "entry_ts"], how="inner", suffixes=("_live", ""))
        pe = priced_primary[priced_primary["role"] == "entry"].set_index("tid")
        pr100 = price_all_moments(moments[moments["tid"].isin(j["tid"])], book, tape, W_PRIMARY, PILOT_SIZE)
        pe100 = pr100[pr100["role"] == "entry"].set_index("tid")
        j = j[j["tid"].isin(pe100.index)]
        if len(j):
            measured = j["side"].to_numpy() * (j["entry_price"].to_numpy() / j["ledger_entry_price"].to_numpy() - 1) * BPS
            model = j["side"].to_numpy() * (pe100.loc[j["tid"], "taker_px"].to_numpy() / pe100.loc[j["tid"], "mid"].to_numpy() - 1) * BPS
            close_vs_mid = j["side"].to_numpy() * (j["ledger_entry_price"].to_numpy() / pe100.loc[j["tid"], "mid"].to_numpy() - 1) * BPS
            d = measured - (model - close_vs_mid)
            L.append("")
            L.append(f"the pilot's {len(j)} measured taker entries (shared with the policy arm), bps vs the paper close, positive = cost:")
            L.append(f"  measured (live fill vs paper close): mean {np.nanmean(measured):+.2f}, median {np.nanmedian(measured):+.2f}, "
                     f"p90 {np.nanpercentile(measured, 90):+.2f}")
            L.append(f"  modelled taker at ${PILOT_SIZE:.0f} (walk vs mid, no fee) at the same moments: mean {np.nanmean(model):+.2f}; "
                     f"the paper close sits {np.nanmean(close_vs_mid):+.2f} from the mid")
            L.append(f"  measured − modelled (on the same reference): mean {np.nanmean(d):+.2f}, |mean| {'within' if abs(np.nanmean(d)) <= 2 else 'OUTSIDE'} the ±2 bps expectation "
                     f"(legs: {pe100.loc[j['tid'], 'leg'].value_counts().to_dict()})")
            # the ledger's paper close is the close of the bar that closed 5 min BEFORE bar_ts and the live
            # order went out at inserted_at (≈ bar_ts + 100 s), so the line above spans ~7 minutes of drift.
            # The execution-cost reading proper: the live fill against the archive print nearest the order.
            exe, lag = [], []
            for r in j.itertuples():
                ts_p = tape.ts[r.pair]; i = np.searchsorted(ts_p, r.inserted_at, "right") - 1
                if i >= 0:
                    exe.append(r.side * (r.entry_price / tape.price[r.pair][i] - 1) * BPS)
                    lag.append((r.inserted_at - r.ledger_bar_ts) / NS)
            exe = np.asarray(exe)
            L.append(f"  live fill vs the archive print at the order's inserted_at (the taker execution cost proper, {len(exe)} fills): "
                     f"mean {exe.mean():+.2f}, median {np.median(exe):+.2f}, p90 {np.percentile(exe, 90):+.2f} bps; "
                     f"the order goes out {np.median(lag):.0f} s (median) after bar_ts, i.e. ≈ {np.median(lag) / 60 + 5:.0f} min after the booked close")
    L.append("")
    L.append("what this licenses: " + ("WRITING a pilot-only served-change registration for a maker entry/exit path (nothing built or deployed on this read)."
                                       if worth else "nothing served changes; the executor stays taker; the maker line closes for the 4h policy (no re-cut by pair, side, size or window)."))
    text = "\n".join(L)
    print(text)
    tr0.to_parquet(os.path.join(OUT_DIR, "trade_arms_w60_1000.parquet"), index=False)
    with open(os.path.join(OUT_DIR, "read.md"), "w") as fh:
        fh.write(text + "\n")
    with open(os.path.join(OUT_DIR, "read.json"), "w") as fh:
        json.dump({"verdict": verdict, "S1_A": cA, "S1_B": cB, "prerequisite": cal["verdict"],
                   "n_A": n_a, "n_A_priced": kept_a, "n_B": n_b, "n_B_priced": kept_b}, fh, indent=1, default=float)
    return 0


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def add_parser(sub) -> None:
    ap = sub.add_parser("makerpath", help="M1 — the maker path priced on the policy's own entries (BOOK_WAVE2_PLAN §M1)")
    s2 = ap.add_subparsers(dest="job", required=True)
    e = s2.add_parser("entries", help="strata A and B, the candle match, moments, pair-days, BOOK_FILTER")
    e.add_argument("--ledger", default=None, help="paper_trades CSV (default: newest in output/forward)")
    f = s2.add_parser("fetch", help="archive aggTrades, streamed and cut to the moment windows")
    f.add_argument("--threads", type=int, default=4)
    s2.add_parser("calibrate", help="the prerequisite: tape-implied touch vs the collector's book")
    s2.add_parser("read", help="the arms, S1, the verdict")
    ap.set_defaults(fn=_main)


def _main(args) -> int:
    if args.job == "entries":
        return run_entries(args.ledger)
    if args.job == "fetch":
        return run_fetch(args.threads)
    if args.job == "calibrate":
        return run_calibrate()
    if args.job == "read":
        return run_read()
    return 2
