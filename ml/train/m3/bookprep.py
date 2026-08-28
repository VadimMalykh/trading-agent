"""M3-4a — turn the exported book/tape slice into parquet, and audit what it can support.

WHY THIS MODULE EXISTS. `m3 power` and `m3 fitprep` were written so that M3-1's and M3-3's
pre-registrations rested on counts a later session could re-derive rather than on prose.
This is the same thing for M3-4, and it is needed more here than in either of those, because
M3_PLAN §2 M3-4 described a data source that does not exist as described:

  * it said the ladder is sampled "every 5s" — the true median gap is 7.6s in the 8-pair era
    and 9.0s in the 12-pair era, and the p95 is 23s;
  * it said `market_trades` gives "per-window high/low" — the collector asks for at most 200
    aggTrades per poll, so on the majors a large minority of windows are RIGHT-CENSORED and
    their high/low describe only the tail of the interval;
  * it treated `window_start` as a contiguous 5s grid — it is `floor_to_5s` of the LAST
    trade in a ~10s poll, so a row aggregates about ten seconds of tape while carrying a
    five-second label. The volume coverage is complete (the batch is cut by `last_id`, not
    by time); it is the TIME ATTRIBUTION that is coarse, and that is what bounds how short
    a fill window can be.

Every one of those changes what a fill number means. This module measures them so the
protocol can state its sampling assumption instead of inheriting a wrong one.

WHAT IT DELIBERATELY DOES NOT COMPUTE. No fill probability, no queue drain, no adverse
selection, no effective cost. Those are the study, and docs/M3_4_PROTOCOL.md must be
committed before any of them is calculated — the same order M3-1/M3-2 and M3-3a/M3-3 used.
The spread IS reported, because the protocol needs it to set per-pair sample floors and to
define the resting price, and because a half-spread on its own answers none of the three
questions the study asks.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

# Where scripts/gcp_m3_export.sh drops its five slices, as a container path.
EXPORT_DIR = os.environ.get("M3_EXPORT_DIR", "/workspace/train/output/m3_4")

# The eight pairs the served universe trades (M3_PLAN §0.6 — the 8-vs-12 question is closed).
# Imported rather than re-listed: a second copy of the universe is exactly the thing that
# drifts out of sync with the one every published number was measured on.
from .dumps import BASE8  # noqa: E402
# The four added on 2026-08-14. They hold 13 days of ladder against the majors' 22, so the
# protocol reports them SEPARATELY and never pools two depths of evidence (M3_PLAN §2 M3-4).
EXTRA4 = ("ADAUSDT", "AVAXUSDT", "LINKUSDT", "XRPUSDT")

# The collector polls with `limit: 200`, so a window that reports exactly this many trades
# is one where an unknown number more were dropped. It is a censoring flag, not a count.
TRADE_LIMIT = 200

# The date the universe went from 8 pairs to 12. The book cadence is a function of how many
# pairs the serial poll loop walks, so it steps here and the two eras must be split.
ERA_SPLIT = pd.Timestamp("2026-08-14", tz="UTC")


def _csv(name: str, parse: list[str]) -> pd.DataFrame:
    """Read one exported slice, caching a parquet next to it.

    The CSVs are ~300 MB gzipped and re-parsing them on every invocation dominates the
    runtime of everything downstream, so the first read writes a parquet and later reads
    use it. Deleting the parquet is the way to force a re-parse after a fresh export — and
    it is REQUIRED after one, since the cache is keyed only on the filename.
    """
    pq = os.path.join(EXPORT_DIR, f"{name}.parquet")
    if os.path.exists(pq):
        return pd.read_parquet(pq)
    csv = os.path.join(EXPORT_DIR, f"{name}.csv.gz")
    if not os.path.exists(csv):
        raise FileNotFoundError(
            f"{csv} not found — run ./scripts/gcp_m3_export.sh first (it pulls from the VM)"
        )

    # Written in chunks rather than one read_csv. The 20-level ladder is ~1.8M rows x 86
    # columns; parsing it whole and then handing pandas' block manager a second full copy to
    # serialise is the kind of thing that dies inside a container with no useful traceback.
    import pyarrow as pa
    import pyarrow.parquet as pqt

    writer = None
    try:
        for chunk in pd.read_csv(csv, chunksize=250_000):
            for c in parse:
                # The VM stores naive UTC timestamps; make that explicit rather than leaving
                # tz-naive columns to be compared against tz-aware ones later.
                #
                # format="ISO8601" is required, not cosmetic: Postgres omits the fractional
                # part entirely when it is zero, so the column mixes "…04:04:51" and
                # "…04:04:51.243642", and one inferred format fails on whichever kind pandas
                # did not see first.
                chunk[c] = pd.to_datetime(chunk[c], utc=True, format="ISO8601")
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pqt.ParquetWriter(pq, table.schema)
            writer.write_table(table)
    except BaseException:
        # A half-written parquet is worse than none: the next run would read it as cached and
        # silently analyse a truncated export.
        if writer is not None:
            writer.close()
        if os.path.exists(pq):
            os.remove(pq)
        raise
    if writer is None:
        raise ValueError(f"{csv} has a header but no rows")
    writer.close()
    return pd.read_parquet(pq)


def load_book(levels: int | None = None) -> pd.DataFrame:
    """Load the exported ladder, discovering its depth if not told.

    The export is parameterised by `LEVELS` and the filename carries it, so the audit works
    against whatever depth is on disk: `bookprep` only reads the touch (b0/a0), while §2.5's
    slippage walk needs 20. Auto-discovery keeps one command working for both.
    """
    if levels is None:
        import glob
        found = sorted(glob.glob(os.path.join(EXPORT_DIR, "book_top*.csv.gz"))
                       + glob.glob(os.path.join(EXPORT_DIR, "book_top*.parquet")))
        if not found:
            raise FileNotFoundError(
                f"no book_top*.csv.gz in {EXPORT_DIR} — run ./scripts/gcp_m3_export.sh first"
            )
        # Deepest wins: a 20-level export supersedes a 5-level one left over from an audit.
        levels = max(int(os.path.basename(f).split("book_top")[1].split(".")[0])
                     for f in found)
    return _csv(f"book_top{levels}", ["ts", "event_time", "transaction_time"])


def load_trades() -> pd.DataFrame:
    return _csv("trades", ["window_start"])


def load_snapshots() -> pd.DataFrame:
    return _csv("snapshots", ["ts"])


def _gaps(df: pd.DataFrame, tcol: str) -> pd.Series:
    """Seconds between consecutive rows within a symbol."""
    return df.groupby("symbol")[tcol].diff().dt.total_seconds()


def cadence_table(book: pd.DataFrame) -> pd.DataFrame:
    """Per-pair, per-era sampling interval of the raw ladder.

    Split at ERA_SPLIT because the poll loop is serial over pairs — `collector.ex` schedules
    the next `:poll_book` 5s AFTER walking every pair — so the interval is 5s plus the time
    to fetch the whole universe, and it stepped when four pairs were added. That is the
    mechanism; the numbers here are the test of it.
    """
    b = book[["symbol", "ts"]].sort_values(["symbol", "ts"])
    b["dt"] = _gaps(b, "ts")
    b["era"] = np.where(b["ts"] < ERA_SPLIT, "8-pair", "12-pair")
    g = b.dropna(subset=["dt"]).groupby(["symbol", "era"])["dt"]
    out = pd.DataFrame({
        "n": g.size(),
        "median_s": g.median(),
        "mean_s": g.mean(),
        "p95_s": g.quantile(0.95),
        "p99_s": g.quantile(0.99),
        "max_s": g.max(),
    })
    return out.reset_index()


def staleness_table(book: pd.DataFrame) -> pd.DataFrame:
    """How old the ladder already was when we wrote it down.

    `ts` is the collector's wall clock at insert; `event_time` is Binance's clock on the
    depth message. The difference is one-way network + processing latency, and it bounds how
    precisely any fill can be timed: a book stamped 300 ms late cannot support a claim about
    what was resting at a 100 ms resolution.
    """
    b = book.dropna(subset=["event_time"]).copy()
    lag = (b["ts"] - b["event_time"]).dt.total_seconds()
    g = lag.groupby(b["symbol"])
    return pd.DataFrame({
        "n": g.size(),
        "median_s": g.median(),
        "p95_s": g.quantile(0.95),
        "p99_s": g.quantile(0.99),
    }).reset_index()


def truncation_table(trades: pd.DataFrame) -> pd.DataFrame:
    """How much of the tape the 200-aggTrade poll limit threw away.

    `agg_trades` returns the MOST RECENT trades, so a censored window has lost its OLDEST
    ones: `high`/`low` describe the tail of the interval, not the interval. The censoring is
    concentrated in busy windows, which are exactly the windows in which a resting order
    would have filled — so the bias in a naive fill rate is neither small nor random.
    """
    t = trades[trades["window_start"] >= ERA_SPLIT]
    g = t.groupby("symbol")
    return pd.DataFrame({
        "windows": g.size(),
        "mean_trades": g["trade_count"].mean(),
        "p95_trades": g["trade_count"].quantile(0.95),
        "pct_censored": 100.0 * g["trade_count"].apply(lambda s: (s >= TRADE_LIMIT).mean()),
    }).reset_index()


def tape_coverage_table(trades: pd.DataFrame) -> pd.DataFrame:
    """What fraction of wall-clock time the tape actually accounts for.

    `window_start` is `floor_to_5s` of the last trade in a poll, and polls are ~10s apart, so
    consecutive labels are typically two buckets apart. A study that reads a row as "the 5
    seconds beginning at window_start" silently discards half the tape; a study that reads it
    as "everything since the previous row" is right about the volume but wrong about the
    5s label. The protocol has to pick one, and this is the table that forces the choice.
    """
    t = trades[["symbol", "window_start"]].sort_values(["symbol", "window_start"])
    t["dt"] = _gaps(t, "window_start")
    g = t.dropna(subset=["dt"]).groupby("symbol")["dt"]
    return pd.DataFrame({
        "rows": t.groupby("symbol").size(),
        "median_gap_s": g.median(),
        "p95_gap_s": g.quantile(0.95),
        "pct_gap_5s": 100.0 * g.apply(lambda s: (s == 5).mean()),
        "pct_gap_ge20s": 100.0 * g.apply(lambda s: (s >= 20).mean()),
    }).reset_index()


def spread_table(book: pd.DataFrame) -> pd.DataFrame:
    """Touch spread in bps of mid, from the ladder itself rather than from the derived table.

    Computed here from b0p/a0p so it is the spread of the SAME rows the fill study will use.
    `orderbook_snapshots.spread` is the same quantity in price units on the same (symbol, ts),
    but taking it from the ladder removes any dependence on that join holding 1:1.
    """
    b = book.dropna(subset=["b0p", "a0p"]).copy()
    mid = 0.5 * (b["b0p"] + b["a0p"])
    b["spread_bps"] = 1e4 * (b["a0p"] - b["b0p"]) / mid
    g = b.groupby("symbol")["spread_bps"]
    out = pd.DataFrame({
        "n": g.size(),
        "median_bps": g.median(),
        "mean_bps": g.mean(),
        "p95_bps": g.quantile(0.95),
    })
    # A resting order earns at most the half-spread over the mid, before any fill or
    # adverse-selection haircut. Reported as a CEILING, and labelled as one — it is not a
    # maker cost estimate and the protocol must not be read as if it were.
    out["half_spread_bps"] = out["median_bps"] / 2.0
    return out.reset_index()


def touch_depth_table(book: pd.DataFrame) -> pd.DataFrame:
    """Notional resting at the touch — the queue a maker order would join the back of."""
    b = book.dropna(subset=["b0p", "b0q", "a0p", "a0q"]).copy()
    b["touch_usd"] = 0.5 * (b["b0p"] * b["b0q"] + b["a0p"] * b["a0q"])
    g = b.groupby("symbol")["touch_usd"]
    return pd.DataFrame({
        "median_usd": g.median(),
        "p05_usd": g.quantile(0.05),
        "p95_usd": g.quantile(0.95),
    }).reset_index()


def _order(df: pd.DataFrame) -> pd.DataFrame:
    """BASE8 first (that is what is served), then the four short-window pairs."""
    rank = {s: i for i, s in enumerate(list(BASE8) + list(EXTRA4))}
    return df.assign(_r=df["symbol"].map(rank)).sort_values(
        ["_r"] + ([c for c in ("era",) if c in df.columns])).drop(columns="_r")


def _show(title: str, why: str, df: pd.DataFrame, fmt: dict | None = None) -> None:
    print("\n" + "=" * 92)
    print(title)
    print("-" * 92)
    print(why)
    print("=" * 92)
    with pd.option_context("display.width", 200, "display.max_columns", 40):
        print(_order(df).to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


def audit() -> int:
    book = load_book()
    trades = load_trades()

    span = f"{book['ts'].min():%Y-%m-%d %H:%M} .. {book['ts'].max():%Y-%m-%d %H:%M} UTC"
    print("=" * 92)
    print("M3-4a — DATA-QUALITY FACTS FOR THE MAKER-FEE STUDY")
    print("=" * 92)
    print(f"ladder rows : {len(book):,} over {span}")
    print(f"tape rows   : {len(trades):,}")
    print(f"served (8)  : {', '.join(BASE8)}")
    print(f"short (4)   : {', '.join(EXTRA4)}  — 13d of ladder, reported separately")
    print("\nNO fill rate, queue drain, adverse selection or effective cost is computed here.")
    print("Those are the study; docs/M3_4_PROTOCOL.md is committed before any of them exists.")

    _show("A. LADDER SAMPLING INTERVAL — the plan assumed 5s; it is not 5s",
          "collector.ex schedules the next :poll_book 5s AFTER a serial walk of every pair, so\n"
          "the period is 5s + the whole universe's fetch time and it STEPPED when 4 pairs were\n"
          "added on 2026-08-14. If the 8-pair -> 12-pair medians differ by ~4 x (one pair's\n"
          "fetch), that mechanism is confirmed and nothing is being dropped.",
          cadence_table(book))

    _show("B. BOOK STALENESS — ts (our clock) minus event_time (Binance's)",
          "Bounds the time resolution any fill claim can honestly carry.",
          staleness_table(book))

    _show("C. TAPE CENSORING — the collector's `limit: 200` on agg_trades",
          "A window at the cap has lost its OLDEST trades, so its high/low cover only the tail\n"
          "of the interval. Censoring concentrates in busy windows, which are exactly the ones\n"
          "where a resting order fills — so this biases a naive fill rate DOWNWARD, and not at\n"
          "random. 12-pair era only, so the two eras are not pooled.",
          truncation_table(trades))

    _show("D. TAPE COVERAGE — window_start is floor_to_5s(last trade), not a 5s grid",
          "If the median gap is 10s while the label is a 5s bucket, the tape is a sparse series\n"
          "of ~10s aggregates and NOT a contiguous 5s tape. The protocol must say which of the\n"
          "two readings it uses (§2.2) rather than let the column name decide.",
          tape_coverage_table(trades))

    _show("E. TOUCH SPREAD — the ceiling on what resting can earn",
          "half_spread_bps is an UPPER BOUND on the maker edge per side before any fill\n"
          "probability or adverse-selection haircut. It is not a cost estimate and the study\n"
          "is not entitled to quote it as one.",
          spread_table(book))

    _show("F. TOUCH DEPTH — the queue a maker order joins the back of",
          "Sets the per-pair size at which the queue model is even arguable: an order large\n"
          "against p05 touch notional is not 'resting at the touch', it IS the touch.",
          touch_depth_table(book))
    return 0
