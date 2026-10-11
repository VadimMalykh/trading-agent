"""BOOK_WAVE2_PLAN §L1 — what the 100-level ladder reaches, and the archive band identity.

Nothing on the Python side had read `orderbook_levels` before this module. It answers two
questions the M2 freeze's reopening condition turns on, with the registration's numbers fixed
before any row was read:

  1. How far from the mid does the collector's level 100 sit, per pair (bps, p5/p50/p95), and
     on what share of rows does the ladder reach the archive's ±0.2 % and ±1 % bands?
  2. Where it reaches, is the quantity summed from the ladder inside a band THE SAME NUMBER the
     public archive publishes for that band (data.binance.vision bookDepth, 30 s)? If it is,
     the band can be served live from the ladder and filled from the archive back to 2024-05.

The sample is six UTC days at one ladder row per 30-second slot, exported by
scripts/gcp_m3_export.sh with LEVELS=100 and BOOK_FILTER (§L1's command). The archive rows
are matched to the nearest ladder row within TOL_S seconds on the receipt clock `ts`, and
again on the exchange clock `event_time` where present. Two band references are scored — the
mid, and the side's own best price — and the one that matches is reported as the data's choice,
the way X8 reported its +5 min shift.

A pair-band is UNREACHABLE when fewer than REACH_MIN of its matched rows have level 100 beyond
the band edge; that is a measurement, not a failure. On reachable rows the bar is
median relative difference < MED_MAX and p99 < P99_MAX with at least MIN_MATCHED rows.
"""
from __future__ import annotations

import hashlib
import io
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from . import archiveoi
from .bookprep import _csv

DAYS = ["2026-08-06", "2026-08-20", "2026-09-03", "2026-09-17", "2026-10-01", "2026-10-10"]
PAIRS = list(archiveoi.DEFAULT_PAIRS)
EXPORT_DIR = os.environ.get("M3_LADDER_DIR", "/workspace/train/output/ladder_span")
SLICE = "book_top100"
LEVELS = 100
SCALAR_LEVELS = 20                 # the served scalars' basis (book_features.ex)
BANDS = (0.002, 0.01)              # the archive's ±0.2 % and ±1 %
TOL_S = 15.0
REACH_MIN = 0.50
MIN_MATCHED = 1000
MED_MAX, P99_MAX = 0.02, 0.10
ARCHIVE_KIND = "bookDepth"
ARCHIVE_CACHE = "output/archive/bookdepth_zips"
ARCHIVE_OUT = "output/archive/bookdepth_l1.parquet"
BPS = 1e4


# --------------------------------------------------------------------------------------
# the archive
# --------------------------------------------------------------------------------------

def _key(sym: str, d: date) -> str:
    return f"data/futures/um/daily/{ARCHIVE_KIND}/{sym}/{sym}-{ARCHIVE_KIND}-{d.isoformat()}.zip"


def _fetch_day(sym: str, d: date, cache: str) -> tuple[str, date, str]:
    """archiveoi._fetch_day for the bookDepth product: sha256-verified, .ok/.missing markers."""
    key = _key(sym, d)
    path = os.path.join(cache, os.path.basename(key))
    if os.path.exists(path + ".ok"):
        return sym, d, "cached"
    if os.path.exists(path + ".missing"):
        return sym, d, "missing"
    blob = archiveoi._get(archiveoi.DL + key)
    if blob is None:
        open(path + ".missing", "w").close()
        return sym, d, "missing"
    chk = archiveoi._get(archiveoi.DL + key + ".CHECKSUM")
    if chk is None:
        raise RuntimeError(f"{key}: zip exists but its .CHECKSUM does not")
    want = chk.decode().split()[0].lower()
    got = hashlib.sha256(blob).hexdigest()
    if want != got:
        raise RuntimeError(f"{key}: sha256 mismatch (published {want[:12]}…, got {got[:12]}…)")
    with open(path, "wb") as f:
        f.write(blob)
    open(path + ".ok", "w").close()
    return sym, d, "ok"


def _parse_zip(path: str, sym: str) -> pd.DataFrame:
    """Long (timestamp, percentage, depth, notional) -> wide: one row per timestamp, a `depth`
    column per band and side, e.g. d_bid_0.2 / d_ask_1.0 (quantity in the base asset)."""
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as f:
            df = pd.read_csv(io.BytesIO(f.read()))
    need = ["timestamp", "percentage", "depth", "notional"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise RuntimeError(f"{os.path.basename(path)}: columns {missing} missing (have {list(df.columns)})")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)
    df["pct"] = df["percentage"].astype(float)
    df["side"] = np.where(df["pct"] < 0, "bid", "ask")
    df["band"] = df["pct"].abs().map(lambda v: f"{v:g}")
    df["col"] = "d_" + df["side"] + "_" + df["band"]
    wide = df.pivot_table(index="ts", columns="col", values="depth", aggfunc="last")
    wide = wide.reset_index()
    wide.insert(0, "symbol", sym)
    return wide


def fetch(pairs: list[str], days: list[str], cache: str = ARCHIVE_CACHE, out: str = ARCHIVE_OUT,
          threads: int = 12) -> str:
    os.makedirs(cache, exist_ok=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    ds = [date.fromisoformat(d) for d in days]
    jobs = [(s, d) for s in pairs for d in ds]
    print(f"fetch: {len(pairs)} pairs x {len(ds)} days = {len(jobs)} daily bookDepth files, cache {cache}")
    counts = {"ok": 0, "cached": 0, "missing": 0}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        for s, d, st in ex.map(lambda j: _fetch_day(j[0], j[1], cache), jobs):
            counts[st] += 1
            if st == "missing":
                print(f"  missing: {s} {d}")
    print(f"  done: {counts} in {time.time() - t0:.0f}s")
    frames = [_parse_zip(os.path.join(cache, os.path.basename(_key(s, d))), s)
              for s in pairs for d in ds
              if os.path.exists(os.path.join(cache, os.path.basename(_key(s, d))) + ".ok")]
    if not frames:
        raise SystemExit("fetch: nothing downloaded")
    df = pd.concat(frames, ignore_index=True).sort_values(["symbol", "ts"]).reset_index(drop=True)
    print(f"rows {len(df):,}; columns {[c for c in df.columns if c.startswith('d_')]}")
    for s in pairs:
        g = df[df["symbol"] == s]
        gaps = g["ts"].diff().dt.total_seconds().dropna()
        print(f"  {s:<14}{len(g):>8} rows  {str(g['ts'].min())[:19]} .. {str(g['ts'].max())[:19]}  "
              f"cadence p50 {gaps.median() if len(gaps) else float('nan'):.0f}s")
    df.to_parquet(out, index=False)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
    return out


# --------------------------------------------------------------------------------------
# the ladder
# --------------------------------------------------------------------------------------

def ladder_cols(levels: int = LEVELS) -> list[str]:
    return [f"{s}{i}{k}" for s in ("b", "a") for i in range(levels) for k in ("p", "q")]


def load_ladder(export_dir: str | None = None) -> pd.DataFrame:
    return _csv(SLICE, ["ts", "event_time", "transaction_time"], export_dir=export_dir or EXPORT_DIR,
                float_cols=ladder_cols())


def arrays(book: pd.DataFrame, levels: int = LEVELS) -> dict[str, np.ndarray]:
    """(n, levels) best-first price/qty matrices per side; absent levels: price NaN, qty 0."""
    out = {}
    for side, letter in (("bid", "b"), ("ask", "a")):
        p = np.column_stack([book[f"{letter}{i}p"].to_numpy(np.float64) for i in range(levels)])
        q = np.column_stack([book[f"{letter}{i}q"].to_numpy(np.float64) for i in range(levels)])
        out[f"{side}_p"] = p
        out[f"{side}_q"] = np.nan_to_num(q, nan=0.0)
    out["mid"] = (out["bid_p"][:, 0] + out["ask_p"][:, 0]) / 2.0
    return out


def deepest(a: dict[str, np.ndarray], levels: int) -> tuple[np.ndarray, np.ndarray]:
    """The deepest present price on each side within the first `levels` levels."""
    bp = a["bid_p"][:, :levels]
    ap = a["ask_p"][:, :levels]
    with np.errstate(all="ignore"):
        return np.nanmin(bp, axis=1), np.nanmax(ap, axis=1)


def span_bps(a: dict[str, np.ndarray], levels: int) -> tuple[np.ndarray, np.ndarray]:
    """Distance of the deepest level from the mid, bid and ask, in bps."""
    lo, hi = deepest(a, levels)
    mid = a["mid"]
    return (mid - lo) / mid * BPS, (hi - mid) / mid * BPS


def band_edge(a: dict[str, np.ndarray], x: float, side: str, ref: str) -> np.ndarray:
    """The band's price edge: ref 'mid' -> mid·(1∓x); ref 'best' -> best price on that side·(1∓x)."""
    base = a["mid"] if ref == "mid" else (a["bid_p"][:, 0] if side == "bid" else a["ask_p"][:, 0])
    return base * (1.0 - x) if side == "bid" else base * (1.0 + x)


def band_sum(a: dict[str, np.ndarray], x: float, side: str, ref: str) -> tuple[np.ndarray, np.ndarray]:
    """(quantity inside the band, reaches) — `reaches` is True where the ladder's deepest level
    lies beyond the band edge, i.e. the sum covers the whole band."""
    edge = band_edge(a, x, side, ref)
    p, q = a[f"{side}_p"], a[f"{side}_q"]
    inside = (p >= edge[:, None]) if side == "bid" else (p <= edge[:, None])
    inside &= np.isfinite(p)
    total = (q * inside).sum(axis=1)
    lo, hi = deepest(a, p.shape[1])
    reaches = (lo <= edge) if side == "bid" else (hi >= edge)
    return total, reaches


# --------------------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------------------

def _pct(v: float) -> str:
    return f"{v:.1%}" if np.isfinite(v) else "—"


def span_table(book: pd.DataFrame, a: dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    sym = book["symbol"].astype(str).to_numpy()
    for s in sorted(set(sym)):
        m = sym == s
        sub = {k: v[m] for k, v in a.items()}
        rec = {"pair": s, "rows": int(m.sum()),
               "n_bid_p50": float(np.median(np.isfinite(sub["bid_p"]).sum(axis=1))),
               "n_ask_p50": float(np.median(np.isfinite(sub["ask_p"]).sum(axis=1)))}
        for levels, tag in ((SCALAR_LEVELS, "L20"), (LEVELS, "L100")):
            b, k = span_bps(sub, levels)
            rec[f"{tag} bid p5/p50/p95"] = f"{np.nanpercentile(b, 5):.1f}/{np.nanmedian(b):.1f}/{np.nanpercentile(b, 95):.1f}"
            rec[f"{tag} ask p5/p50/p95"] = f"{np.nanpercentile(k, 5):.1f}/{np.nanmedian(k):.1f}/{np.nanpercentile(k, 95):.1f}"
            for x in BANDS:
                both = (b >= x * BPS) & (k >= x * BPS)
                rec[f"{tag} reach ±{x:.1%} both"] = _pct(float(np.nanmean(both)))
        b100, k100 = span_bps(sub, LEVELS)
        per_level = float(np.nanmedian((b100 + k100) / 2.0)) / LEVELS
        rec["bps/level (est.)"] = per_level
        rec["levels to 20 bps (est.)"] = int(np.ceil(20.0 / per_level)) if per_level > 0 else -1
        rec["levels to 100 bps (est.)"] = int(np.ceil(100.0 / per_level)) if per_level > 0 else -1
        rows.append(rec)
    return pd.DataFrame(rows)


def _tag(x: float) -> str:
    """0.002 -> '0.2', 0.01 -> '1' — the archive's own band label (percent)."""
    return f"{x * 100:g}"


def identity(book: pd.DataFrame, a: dict[str, np.ndarray], arch: pd.DataFrame,
             clock: str = "ts") -> pd.DataFrame:
    """Per pair x band x side x reference: the archive's depth against the ladder's band sum on
    rows matched within TOL_S on `clock`, scored only where the ladder reaches."""
    rows = []
    sums = {}
    for x in BANDS:
        for side in ("bid", "ask"):
            for ref in ("mid", "best"):
                sums[(x, side, ref)] = band_sum(a, x, side, ref)
    lad = pd.DataFrame({"symbol": book["symbol"].astype(str).to_numpy(),
                        "t": pd.to_datetime(book[clock], utc=True)})
    for key, (tot, reach) in sums.items():
        lad[f"sum_{_tag(key[0])}_{key[1]}_{key[2]}"] = tot
        lad[f"reach_{_tag(key[0])}_{key[1]}"] = reach
    lad = lad.dropna(subset=["t"]).sort_values("t")
    tol = pd.Timedelta(seconds=TOL_S)
    for s in sorted(arch["symbol"].unique()):
        ga = arch[arch["symbol"] == s].sort_values("ts").rename(columns={"ts": "t"})
        gl = lad[lad["symbol"] == s]
        if gl.empty:
            continue
        m = pd.merge_asof(ga, gl.drop(columns=["symbol"]), on="t", direction="nearest", tolerance=tol)
        n_arch = len(ga)
        matched = m.dropna(subset=[f"sum_{_tag(BANDS[0])}_bid_mid"])
        for x in BANDS:
            for side in ("bid", "ask"):
                acol = f"d_{side}_{_tag(x)}"
                if acol not in matched.columns:
                    rows.append({"pair": s, "band": f"±{x:.1%}", "side": side, "ref": "—", "archive": n_arch,
                                 "matched": len(matched), "reach": float("nan"), "n": 0, "median": float("nan"),
                                 "p99": float("nan"), "max": float("nan"), "verdict": "NO ARCHIVE BAND"})
                    continue
                reach = matched[f"reach_{_tag(x)}_{side}"].astype(bool)
                share = float(reach.mean()) if len(matched) else float("nan")
                for ref in ("mid", "best"):
                    sub = matched[reach & (matched[acol] > 0)]
                    rel = (sub[f"sum_{_tag(x)}_{side}_{ref}"] - sub[acol]).abs() / sub[acol]
                    rec = {"pair": s, "band": f"±{x:.1%}", "side": side, "ref": ref, "archive": n_arch,
                           "matched": len(matched), "reach": share, "n": len(sub),
                           "median": float(rel.median()) if len(sub) else float("nan"),
                           "p99": float(rel.quantile(0.99)) if len(sub) else float("nan"),
                           "max": float(rel.max()) if len(sub) else float("nan")}
                    if not np.isfinite(share) or share < REACH_MIN:
                        rec["verdict"] = "UNREACHABLE"
                    elif len(sub) < MIN_MATCHED:
                        rec["verdict"] = "TOO FEW"
                    else:
                        rec["verdict"] = "IDENTICAL" if (rec["median"] < MED_MAX and rec["p99"] < P99_MAX) else "DIFFERENT"
                    rows.append(rec)
    return pd.DataFrame(rows)


def report(export_dir: str | None = None, archive: str = ARCHIVE_OUT) -> int:
    print("=" * 100)
    print("BOOK_WAVE2_PLAN §L1 — THE LADDER'S REACH, AND THE ARCHIVE BAND IDENTITY")
    print("=" * 100)
    book = load_ladder(export_dir)
    book = book[book["symbol"].astype(str).isin(PAIRS)].reset_index(drop=True)
    t = pd.to_datetime(book["ts"], utc=True)
    days = sorted(set(t.dt.strftime("%Y-%m-%d")))
    print(f"ladder sample: {len(book):,} rows x {book['symbol'].nunique()} pairs, days {days}")
    unexpected = [d for d in days if d not in DAYS]
    if unexpected:
        print(f"🔴 rows outside the registered days: {unexpected} — the export filter did not apply")
        return 3
    gaps = t.sort_values().groupby(book.loc[t.sort_values().index, "symbol"].astype(str).to_numpy()).diff()
    print(f"row spacing p50 {gaps.dt.total_seconds().median():.0f}s (registered: one row per 30 s slot)")
    a = arrays(book)
    bad_mid = ~np.isfinite(a["mid"]) | (a["bid_p"][:, 0] >= a["ask_p"][:, 0])
    print(f"rows with a crossed or missing touch: {int(bad_mid.sum())} (dropped)")
    if bad_mid.any():
        book = book[~bad_mid].reset_index(drop=True)
        a = arrays(book)

    print("\n" + "=" * 100)
    print("1. WHAT THE LADDER REACHES — distance of the deepest level from the mid, bps (p5/p50/p95),")
    print("   and the share of rows where BOTH sides reach the band. L20 = the served scalars' basis.")
    print("   'bps/level' and the 'levels to …' columns are ESTIMATES (a deeper book is not linear).")
    print("=" * 100)
    st = span_table(book, a)
    print(st.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    if not os.path.exists(archive):
        print(f"\n🔴 {archive} missing — run `m3 ladderspan fetch` first; identity not scored")
        return 2
    arch = pd.read_parquet(archive)
    arch["ts"] = pd.to_datetime(arch["ts"], utc=True)
    arch = arch[arch["symbol"].isin(PAIRS)]
    print("\n" + "=" * 100)
    print(f"2. IDENTITY — archive bookDepth vs the ladder's band sum, nearest row within {TOL_S:.0f}s.")
    print(f"   Scored where the ladder reaches the band; UNREACHABLE below {REACH_MIN:.0%} reach;")
    print(f"   bar: median < {MED_MAX:.0%}, p99 < {P99_MAX:.0%}, n ≥ {MIN_MATCHED:,}. ref = band edge from the mid or the side's best.")
    print("=" * 100)
    fmt = {"reach": _pct, "median": lambda v: f"{v:.3%}" if np.isfinite(v) else "—",
           "p99": lambda v: f"{v:.2%}" if np.isfinite(v) else "—",
           "max": lambda v: f"{v:.1%}" if np.isfinite(v) else "—"}
    verdicts = {}
    for clock in ("ts", "event_time"):
        if clock == "event_time" and book["event_time"].isna().all():
            continue
        tab = identity(book, a, arch, clock=clock)
        print(f"\n--- clock: {clock} ---")
        print(tab.to_string(index=False, formatters=fmt))
        if clock == "ts":
            verdicts = tab
    print("\n" + "=" * 100)
    print("3. THE READING, per pair and band (receipt clock; the better of the two references)")
    print("=" * 100)
    summary = []
    for (p, b), g in verdicts.groupby(["pair", "band"], sort=True):
        scored = g[g["verdict"].isin(["IDENTICAL", "DIFFERENT"])]
        if scored.empty:
            v = "UNREACHABLE" if (g["verdict"] == "UNREACHABLE").any() else g["verdict"].iloc[0]
            summary.append({"pair": p, "band": b, "verdict": v, "reach": g["reach"].max(), "ref": "—", "median": float("nan")})
            continue
        best = scored.sort_values("median").iloc[0]
        both_sides = scored.groupby("side")["verdict"].apply(lambda s: (s == "IDENTICAL").any())
        v = "IDENTICAL" if both_sides.all() else "DIFFERENT"
        summary.append({"pair": p, "band": b, "verdict": v, "reach": g["reach"].max(), "ref": best["ref"], "median": best["median"]})
    sm = pd.DataFrame(summary)
    print(sm.to_string(index=False, formatters={"reach": _pct, "median": fmt["median"]}))
    n_id = int((sm["verdict"] == "IDENTICAL").sum())
    n_un = int((sm["verdict"] == "UNREACHABLE").sum())
    n_df = int((sm["verdict"] == "DIFFERENT").sum())
    print(f"\n==> pair-bands IDENTICAL {n_id}, UNREACHABLE {n_un}, DIFFERENT {n_df} of {len(sm)}. "
          f"Read §L1's outcome paragraph; transcribe this table into BOOK_WAVE2_PLAN §L1.")
    return 0


def add_parser(sub) -> None:
    ap = sub.add_parser("ladderspan", help="BOOK_WAVE2_PLAN §L1: what the 100-level ladder reaches per "
                        "pair, and whether the archive's ±0.2 % / ±1 % depth bands equal the band "
                        "summed from the ladder (six sampled days)")
    s2 = ap.add_subparsers(dest="job", required=True)
    f = s2.add_parser("fetch")
    f.add_argument("--pairs", default=",".join(PAIRS))
    f.add_argument("--days", default=",".join(DAYS))
    f.add_argument("--cache", default=ARCHIVE_CACHE)
    f.add_argument("--out", default=ARCHIVE_OUT)
    r = s2.add_parser("report")
    r.add_argument("--export-dir", default=None, help=f"default {EXPORT_DIR} (M3_LADDER_DIR)")
    r.add_argument("--archive", default=ARCHIVE_OUT)
    ap.set_defaults(fn=_main)


def _main(args) -> int:
    if args.job == "fetch":
        fetch(args.pairs.split(","), args.days.split(","), cache=args.cache, out=args.out)
        return 0
    return report(export_dir=args.export_dir, archive=args.archive)
