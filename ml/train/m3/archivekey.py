"""BOOK_WAVE2_PLAN §K1 — X7's ladder key rebuilt from Binance's public archive, read on history.

X7 (bookladder.py, §R.4) found on the 43-day book era that sizing the incumbent's trades by how
QUIET the whole market is — `book_composite_lo`, the negated mean of four market-wide percentile
ranks (spread, trade count, traded volume, open-interest change) — beat the live key
`btc_absret_1d` by +13.46 bps per notional at cov 0.05, weakly, on bars B1/B2 had already read.
Its confirmation was parked to 2027-03-10 for want of untouched book history.

§K1 asks the same question on history the collector never saw. The archive carries, per
5-minute bar, three of X7's four ingredients: `count` and `volume` from the `klines` files and
`sum_open_interest` from the `metrics` files (X8's reduced parquet, reused as is). The spread is
NOT in the archive after 2024-03-30 (`bookTicker` stops), so the archive key is the composite of
THREE ingredients — `a_composite3_lo` — and the registration's prerequisite is that it IS X7's
key where both exist (the book era): the harness replays X7's numbers, the two keys rank the
same bars the same way (Spearman ≥ 0.80), and they put the incumbent's trades on the same ladder
rung (identical on ≥ 70 %, within one rung on ≥ 95 %). Any of the three failing → K1 VOID,
nothing further is read, and X7's confirmation stays exactly where §R.4 put it.

Four jobs, all CPU, all in `ml_analysis` (scripts/m3.sh), in this order:

  fetch   — the monthly USDⓈ-M `klines` 5m files (sha256-verified, cached, resumable) → ONE
            parquet (symbol, ts, count, volume), sha8 in the name.
  reduce  — the archive observables on a full 5-minute grid per pair:
            a_trade_count, a_trade_vol, has_a_trades (the kline exists), a_oi_chg, has_a_oi —
            the OI change aligned EXACTLY as sidetable.add_open_interest aligns the collector's
            polls (asof-backward, the 8 h cap, pct_change on the ALIGNED level), the archive's
            bucket-start stamps relabelled +5 min first (X8's convention: a bucket's closing
            value is stored under its start). → output/archive/archive_key_5m_<sha8>.parquet.
  check   — the prerequisite above, on X7's own population (M3_ERA=repaired, the eight book
            pairs, M3_EXPORT_DIR=book_era). Exit 2 = VOID. PASS writes the marker
            output/archive/archive_key_check.json carrying the key parquet's sha8.
  bookladder --stage archive-confirm --population P1|P2 — §K1's read, refused without the
            marker (and refused on a second look at the same population).

`bookregime.observables` runs UNCHANGED on the archive table: the a_* columns are presented to
it under the candidate names it knows (trade_count, trade_vol, oi_chg), it finds those three of
its four candidates, and its `book_composite_lo` IS the registered `a_composite3_lo` — the mean
of the three market-wide ranks, negated. Nothing is re-cut: §K1 forbids a second composite.

Everything here was fixed by §K1 (2026-10-19) before any archive file beyond the format
listing was fetched.
"""
from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from . import backtest, bookregime, dumps, metrics, regime, sidetable
from . import walkforward as wf
from .archiveoi import DEFAULT_PAIRS, DL, _get

# --------------------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------------------
KLINES_CACHE = "output/archive/klines_zips"
KLINES_OUT = "output/archive/klines_um_5m.parquet"          # sha8 inserted before .parquet
KEY_OUT = "output/archive/archive_key_5m.parquet"            # sha8 inserted before .parquet
METRICS_GLOB = "output/archive/metrics_um_5m_*.parquet"      # X8's reduced OI parquet
CHECK_MARKER = "output/archive/archive_key_check.json"
LOOK_MARKER = "output/archive/k1_look_{pop}.json"

FETCH_FROM, FETCH_TO = "2024-10-01", "2026-09-30"           # §K1 "Data, fixed now"

# X8's relabel: the archive stores a 5m bucket's closing OI under the bucket's START.
OI_SHIFT_MIN = 5.0
BAR_NS = 5 * 60 * dumps.NS

# --------------------------------------------------------------------------------------
# The key, the populations, the gates — §K1 verbatim
# --------------------------------------------------------------------------------------
KEY = "a_composite3_lo"
KEY_CAUSAL = "a_composite3_lo_causal"      # trailing-30-day ranks; secondary, information only
CAUSAL_BARS = 30 * 288
INCUMBENT = bookregime.INCUMBENT
# The three archive ingredients, presented to bookregime.observables under the names it knows.
INGREDIENTS = {"a_trade_count": "trade_count", "a_trade_vol": "trade_vol", "a_oi_chg": "oi_chg"}
X7_KEY = "book_composite_lo"

COVERAGE, COVERAGE_INFO = 0.05, 0.02
COST = metrics.TAKER_COST_BPS

# Prerequisite bars (§K1): X7's exploration numbers, from logs/bookladder_explore_20260915.log.
REPLAY_N = 670
REPLAY_CONTRAST = 13.46
REPLAY_TOL = 0.01
SPEARMAN_MIN = 0.80
RUNG_SAME_MIN = 0.70
RUNG_WITHIN1_MIN = 0.95

# P1 — decides: the served checkpoint's own dump (X8″ s3, serving since 2026-10-04), every bar
# before the book era's first bar. P2 — replication: the X8 fold era, F3+F2+F1, before P1.
P1_RUN = "20261003T191545Z"
P1_START = "2025-12-14 09:35"
P1_END = "2026-07-17 00:00"
P2_ERA = "walkforward_x8"
P2_FOLDS = ("F3", "F2", "F1")


# --------------------------------------------------------------------------------------
# fetch — the klines
# --------------------------------------------------------------------------------------

def _months(start: str, end: str) -> list[str]:
    a, b = pd.Period(start[:7], "M"), pd.Period(end[:7], "M")
    return [str(p) for p in pd.period_range(a, b, freq="M")]


def _kline_key(sym: str, month: str) -> str:
    return f"data/futures/um/monthly/klines/{sym}/5m/{sym}-5m-{month}.zip"


def _fetch_month(sym: str, month: str, cache: str) -> tuple[str, str, str]:
    key = _kline_key(sym, month)
    path = os.path.join(cache, os.path.basename(key))
    if os.path.exists(path + ".ok"):
        return sym, month, "cached"
    if os.path.exists(path + ".missing"):
        return sym, month, "missing"
    blob = _get(DL + key)
    if blob is None:
        open(path + ".missing", "w").close()
        return sym, month, "missing"
    chk = _get(DL + key + ".CHECKSUM")
    if chk is None:
        raise RuntimeError(f"{key}: zip exists but its .CHECKSUM does not")
    want = chk.decode().split()[0].lower()
    got = hashlib.sha256(blob).hexdigest()
    if want != got:
        raise RuntimeError(f"{key}: sha256 mismatch (published {want[:12]}…, got {got[:12]}…)")
    with open(path, "wb") as f:
        f.write(blob)
    open(path + ".ok", "w").close()
    return sym, month, "ok"


KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]


def parse_klines(raw: bytes, sym: str) -> pd.DataFrame:
    """One monthly klines CSV → (symbol, ts, count, volume). The futures files carry a header
    row; the stamps are epoch milliseconds (microseconds are detected by magnitude, so a
    later archive change cannot silently shift every bar by a factor of 1,000)."""
    head = raw[:64].decode(errors="replace")
    df = pd.read_csv(io.BytesIO(raw), header=0 if head.startswith("open_time") else None)
    if df.shape[1] != len(KLINE_COLS):
        raise RuntimeError(f"{sym}: expected {len(KLINE_COLS)} kline columns, got {df.shape[1]}")
    df.columns = KLINE_COLS
    t = df["open_time"].to_numpy(np.int64)
    unit = "us" if (t.size and t.max() > 10 ** 14) else "ms"
    out = pd.DataFrame({
        "symbol": sym,
        "ts": pd.to_datetime(t, unit=unit, utc=True),
        "count": df["count"].astype("int64"),
        "volume": df["volume"].astype("float64"),
    })
    return out


def _parse_zip(path: str, sym: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        with z.open(z.namelist()[0]) as f:
            return parse_klines(f.read(), sym)


def fetch(pairs: list[str], start: str, end: str, cache: str = KLINES_CACHE,
          out: str = KLINES_OUT, threads: int = 12) -> str:
    os.makedirs(cache, exist_ok=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    months = _months(start, end)
    jobs = [(s, m) for s in pairs for m in months]
    print(f"fetch klines 5m: {len(pairs)} pairs x {len(months)} months = {len(jobs)} files, "
          f"{months[0]} -> {months[-1]}, cache {cache}")
    counts = {"ok": 0, "cached": 0, "missing": 0}
    missing: dict[str, list[str]] = {s: [] for s in pairs}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=threads) as ex:
        for s, m, st in ex.map(lambda j: _fetch_month(j[0], j[1], cache), jobs):
            counts[st] += 1
            if st == "missing":
                missing[s].append(m)
    print(f"  done: {counts} in {time.time() - t0:.0f}s")
    frames = []
    for s in pairs:
        for m in months:
            p = os.path.join(cache, os.path.basename(_kline_key(s, m)))
            if os.path.exists(p + ".ok"):
                frames.append(_parse_zip(p, s))
    if not frames:
        raise SystemExit("fetch: nothing downloaded")
    df = pd.concat(frames, ignore_index=True)
    lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    df = df[(df["ts"] >= lo) & (df["ts"] < hi)]
    n0 = len(df)
    df = df.drop_duplicates(subset=["symbol", "ts"], keep="last").sort_values(["symbol", "ts"])
    df = df.reset_index(drop=True)
    print(f"\nrows {len(df):,} (dropped {n0 - len(df)} duplicate keys)")
    print(f"{'symbol':<14}{'rows':>9}  first                 last                  missing months")
    for s in pairs:
        g = df[df["symbol"] == s]
        first = g["ts"].min() if len(g) else pd.NaT
        holes = [m for m in missing[s] if first is not pd.NaT and pd.Period(m, "M").end_time.tz_localize("UTC") > first]
        print(f"{s:<14}{len(g):>9}  {str(first)[:19]:<21} {str(g['ts'].max())[:19] if len(g) else '—':<21} "
              f"{len(holes)}{(' (' + ', '.join(holes[:6]) + ('…' if len(holes) > 6 else '') + ')') if holes else ''}")
    tmp = out + ".tmp"
    df.to_parquet(tmp, index=False)
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()[:8]
    root, ext = os.path.splitext(out)
    final = f"{root}_{sha}{ext}"
    os.replace(tmp, final)
    print(f"\nwrote {final}  sha8={sha}  ({os.path.getsize(final) / 1e6:.1f} MB)")
    return final


# --------------------------------------------------------------------------------------
# reduce — the archive observables on the 5-minute grid
# --------------------------------------------------------------------------------------

def _newest(pattern: str) -> str:
    found = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not found:
        raise SystemExit(f"no file matches {pattern} — run the step that writes it first")
    return found[-1]


def oi_change(grid: pd.DataFrame, src: pd.DataFrame) -> pd.DataFrame:
    """`a_oi_chg` / `has_a_oi` on `grid` (pair, ts int64 ns) from `src` (pair, ts int64 ns,
    open_interest) — sidetable.add_open_interest's derivation with the source injected: asof
    backward within pair, stale past the 8 h cap, the change on the ALIGNED level (a bar that
    sees the same reading as the bar before reads 0.0), zeroed where stale."""
    out = grid.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    j = sidetable._asof(out, src.rename(columns={"ts": "src_ts"}), "src_ts")
    age_min = (j["ts"] - j["src_ts"]) / 6e10
    stale = (~np.isfinite(age_min) | (age_min > sidetable.FUNDING_OI_MAX_AGE)).to_numpy()
    level = j["open_interest"]
    prev = level.groupby(out["pair"].to_numpy()).shift(1)
    chg = (level / prev - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    out["a_oi_chg"] = np.where(stale, 0.0, chg.to_numpy())
    out["has_a_oi"] = (~stale).astype("int8")
    return out


def reduce(klines_parquet: str, metrics_parquet: str, out: str = KEY_OUT) -> str:
    k = pd.read_parquet(klines_parquet)
    k["ts"] = pd.DatetimeIndex(pd.to_datetime(k["ts"], utc=True)).asi8
    frames = []
    for sym, g in k.groupby("symbol", sort=True):
        g = g.sort_values("ts")
        ts = np.arange(g["ts"].min(), g["ts"].max() + BAR_NS, BAR_NS, dtype=np.int64)
        grid = pd.DataFrame({"pair": str(sym), "ts": ts})
        grid = grid.merge(g[["ts", "count", "volume"]], on="ts", how="left")
        grid["has_a_trades"] = grid["count"].notna().astype("int8")
        grid["a_trade_count"] = grid["count"].fillna(0.0).astype("float64")
        grid["a_trade_vol"] = grid["volume"].fillna(0.0).astype("float64")
        frames.append(grid.drop(columns=["count", "volume"]))
    grid = pd.concat(frames, ignore_index=True)

    m = pd.read_parquet(metrics_parquet)[["symbol", "ts", "open_interest"]]
    m["ts"] = pd.to_datetime(m["ts"], utc=True) + pd.Timedelta(minutes=OI_SHIFT_MIN)
    src = pd.DataFrame({"pair": m["symbol"].astype(str), "ts": pd.DatetimeIndex(m["ts"]).asi8,
                        "open_interest": m["open_interest"].astype("float64")})
    src = src.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)
    tab = oi_change(grid, src)
    tab = tab[["pair", "ts", "a_trade_count", "a_trade_vol", "has_a_trades", "a_oi_chg", "has_a_oi"]]

    print(f"archive key table: {len(tab):,} bars, {tab['pair'].nunique()} pairs; klines {os.path.basename(klines_parquet)}, "
          f"metrics {os.path.basename(metrics_parquet)} (+{OI_SHIFT_MIN:g} min relabel, {sidetable.FUNDING_OI_MAX_AGE:g} min cap)")
    print(f"{'pair':<14}{'bars':>9}  first             last              {'klines':>8}{'oi':>8}  {'both':>8}")
    for p, g in tab.groupby("pair", sort=True):
        t = pd.to_datetime(g["ts"], unit="ns", utc=True)
        both = ((g["has_a_trades"] == 1) & (g["has_a_oi"] == 1)).mean()
        print(f"{p:<14}{len(g):>9}  {t.min():%Y-%m-%d %H:%M}  {t.max():%Y-%m-%d %H:%M}  "
              f"{g['has_a_trades'].mean():>7.1%} {g['has_a_oi'].mean():>7.1%}  {both:>7.1%}")
    tmp = out + ".tmp"
    tab.to_parquet(tmp, index=False)
    sha = hashlib.sha256(open(tmp, "rb").read()).hexdigest()[:8]
    root, ext = os.path.splitext(out)
    final = f"{root}_{sha}{ext}"
    os.replace(tmp, final)
    print(f"\nwrote {final}  sha8={sha}  ({os.path.getsize(final) / 1e6:.1f} MB)")
    return final


def _sha8(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:8]


# --------------------------------------------------------------------------------------
# The key on a population's bars
# --------------------------------------------------------------------------------------

def load_table(path: str | None = None, pairs: list[str] | None = None,
               lo: str | None = None, hi: str | None = None) -> pd.DataFrame:
    """The archive table's usable bars — kline AND OI present, as load_book keeps only bars
    with book, tape and OI — in a window, with the ingredients under the candidate names."""
    path = path or _newest(KEY_OUT.replace(".parquet", "_*.parquet"))
    t = pd.read_parquet(path)
    keep = (t["has_a_trades"] == 1) & (t["has_a_oi"] == 1)
    if pairs is not None:
        keep &= t["pair"].isin(pairs)
    if lo is not None:
        keep &= t["ts"] >= pd.Timestamp(lo, tz="UTC").value
    if hi is not None:
        keep &= t["ts"] <= pd.Timestamp(hi, tz="UTC").value
    t = t[keep].rename(columns=INGREDIENTS)
    return t.sort_values(["pair", "ts"], kind="mergesort").reset_index(drop=True)


def observables(tab: pd.DataFrame) -> pd.DataFrame:
    """`bookregime.observables` unchanged on the archive table; its three-ingredient
    `book_composite_lo` is the registered `a_composite3_lo`. Ranks are within the bars given —
    the population window — as B2 and X7 took them."""
    present = [c for c in INGREDIENTS.values() if c in tab.columns]
    if len(present) != 3:
        raise SystemExit(f"archive table must carry the three ingredients, has {present}")
    if "spread_bps" in tab.columns:
        raise SystemExit("the archive table must not carry a spread — that would be a fourth ingredient")
    obs = bookregime.observables(tab[["pair", "ts", *present]])
    out = obs[["pair", "ts", bookregime.COMPOSITE + "_lo"]].rename(columns={bookregime.COMPOSITE + "_lo": KEY})
    for c in present:
        out[c + "_mkt"] = obs[c + "_mkt"].to_numpy()
    return out


def causal_observables(tab: pd.DataFrame, window: int = CAUSAL_BARS) -> pd.DataFrame:
    """The secondary: the same composite with each ingredient's percentile taken over the pair's
    trailing `window` bars (30 days) — a rank a live collector could compute. Information only."""
    out = tab[["pair", "ts"]].copy()
    tmp = []
    for c in INGREDIENTS.values():
        r = (tab.groupby("pair", observed=True)[c]
             .transform(lambda s: s.rolling(window, min_periods=window // 2).rank(pct=True)))
        out[c + "_ctmp"] = r.to_numpy()
        tmp.append(c + "_ctmp")
    mkt = out.groupby("ts", observed=True)[tmp].mean()
    mkt.columns = [c + "_cmkt" for c in INGREDIENTS.values()]
    out = out.merge(mkt.reset_index(), on="ts", how="left")
    out[KEY_CAUSAL] = -out[[c + "_cmkt" for c in INGREDIENTS.values()]].mean(axis=1)
    return out[["pair", "ts", KEY_CAUSAL]]


def population(ds: list[dumps.Dump], obs: pd.DataFrame, keys: list[str]) -> tuple[list, dict]:
    """Each dump restricted to `obs`'s bars and to rows where the incumbent key and every key
    in `keys` is present — bookladder.population with the key list given, so `regime_col`
    changes the size alone (the harness check verifies it)."""
    cols = [INCUMBENT] + keys
    out_ds, regimes = [], {}
    for d in ds:
        de = bookregime.restrict(d, obs[["pair", "ts"]])
        if de.df.empty:
            raise SystemExit(f"{d.seed}: no rows inside the population's bars")
        r = regime.build(de.df).merge(obs, on=["pair", "ts"], how="left")
        r = r[r[cols].notna().all(axis=1)].reset_index(drop=True)
        out_ds.append(bookregime.restrict(de, r[["pair", "ts"]]))
        regimes[d.seed] = r
    return out_ds, regimes


def arm(ds, regimes, sized_fields: dict, coverage: float, key: str | None) -> pd.DataFrame:
    f = {**sized_fields, "coverage": coverage, "regime_col": key or INCUMBENT,
         "size_by_regime": key is not None}
    return backtest.run(ds, backtest.PolicySpec(label=key or "flat", **f), regimes).trades


def ledger(t: pd.DataFrame) -> pd.DataFrame:
    return wf._ledger(wf._utc_day(t["exit_ts"]), t["signed_ret"].to_numpy(np.float64),
                      t["size"].to_numpy(np.float64), "trade")


def contrast(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    return wf.paired_notional_diff_bps(ledger(a), ledger(b))


def check_same_trades(a: pd.DataFrame, inc: pd.DataFrame) -> tuple[bool, str]:
    from .bookladder import check_same_trades as _c
    return _c(a, inc)


def _ci(c: dict) -> str:
    return f"{c['diff_bps']:+.2f} [{c['lo95_bps']:+.2f}, {c['hi95_bps']:+.2f}] se {c['se_bps']:.2f} on {c['clusters']} days"


def rung(size: pd.Series) -> np.ndarray:
    return np.rint(size.to_numpy(np.float64) * 3.0).astype(int)


# --------------------------------------------------------------------------------------
# check — the prerequisite
# --------------------------------------------------------------------------------------

def check(sized_fields: dict, table: str | None = None) -> int:
    print("=" * 96)
    print("BOOK_WAVE2_PLAN §K1 — PREREQUISITE: the archive key IS X7's key (exit 2 = VOID)")
    print("=" * 96)
    if dumps.ERA != "repaired":
        print(f"\n🔴 refusing: X7's population is M3_ERA=repaired, got {dumps.ERA!r}.")
        return 2
    table = table or _newest(KEY_OUT.replace(".parquet", "_*.parquet"))
    sha = _sha8(table)
    print(f"archive key table {table} (sha8 {sha})")

    # --- X7's population, reproduced from its own module -----------------------------
    from . import bookladder
    ds = dumps.load_baseline(pairs=dumps.BASE8)
    book = bookregime.load_book(dumps.BASE8)
    obs_book = bookregime.observables(book)
    ds_x7, reg_x7, keys_x7 = bookladder.population(ds, obs_book)
    for d in ds_x7:
        t = pd.to_datetime(d.df["ts"], unit="ns", utc=True)
        print(f"  {d.seed}: {d.df[['pair', 'ts']].drop_duplicates().shape[0]:,} bars x {d.df['pair'].nunique()} pairs, "
              f"{t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")

    # 1. harness replay
    print("\n1. HARNESS REPLAY — X7's incumbent trades and book_composite_lo contrast at cov 0.05")
    inc = arm(ds_x7, reg_x7, sized_fields, COVERAGE, INCUMBENT)
    flat = arm(ds_x7, reg_x7, sized_fields, COVERAGE, None)
    x7 = arm(ds_x7, reg_x7, sized_fields, COVERAGE, X7_KEY)
    ok_f, msg_f = check_same_trades(flat, inc)
    ok_x, msg_x = check_same_trades(x7, inc)
    c = contrast(x7, inc)
    e = contrast(inc, flat)
    print(f"  harness: flat {'PASS' if ok_f else 'FAIL'} ({msg_f}); {X7_KEY} {'PASS' if ok_x else 'FAIL'} ({msg_x})")
    print(f"  incumbent trades {len(inc):,} (registered {REPLAY_N}); {X7_KEY} − incumbent {_ci(c)} (registered {REPLAY_CONTRAST:+.2f}); "
          f"E {e['diff_bps']:+.2f}")
    replay_ok = ok_f and ok_x and len(inc) == REPLAY_N and abs(c["diff_bps"] - REPLAY_CONTRAST) <= REPLAY_TOL
    print(f"  -> {'PASS' if replay_ok else 'FAIL'}")

    # --- the archive key on the same bars --------------------------------------------
    bars = obs_book[["pair", "ts"]].drop_duplicates()
    lo = pd.to_datetime(bars["ts"].min(), unit="ns", utc=True)
    hi = pd.to_datetime(bars["ts"].max(), unit="ns", utc=True)
    tab = load_table(table, pairs=dumps.BASE8, lo=str(lo), hi=str(hi))
    tab = tab.merge(bars, on=["pair", "ts"], how="inner")
    obs_a = observables(tab)
    both = obs_book[["pair", "ts", X7_KEY, "trade_count_mkt", "trade_vol_mkt", "oi_chg_mkt"]].merge(
        obs_a, on=["pair", "ts"], how="inner", suffixes=("_b", "_a"))
    print(f"\n  archive key built on {both[['pair', 'ts']].drop_duplicates().shape[0]:,} of X7's "
          f"{len(bars):,} bars ({len(bars) - both[['pair', 'ts']].drop_duplicates().shape[0]:,} without an archive row)")

    # 2. rank agreement
    print(f"\n2. RANK AGREEMENT — Spearman({KEY}, {X7_KEY}) over the population's bars, bar ≥ {SPEARMAN_MIN:.2f}")
    obs_both = both[["pair", "ts", X7_KEY, KEY]]
    ds_pop, reg_pop = population(ds, obs_both, [X7_KEY, KEY])
    pop_bars = pd.concat([r[["pair", "ts", X7_KEY, KEY]] for r in reg_pop.values()]).drop_duplicates(["pair", "ts"])
    rho = float(pop_bars[[X7_KEY, KEY]].corr(method="spearman").iloc[0, 1])
    rho_ts = float(pop_bars.drop_duplicates("ts")[[X7_KEY, KEY]].corr(method="spearman").iloc[0, 1])
    print(f"  Spearman {rho:.4f} over {len(pop_bars):,} (pair, ts) bars ({rho_ts:.4f} over {pop_bars['ts'].nunique():,} distinct timestamps)")
    rank_ok = rho >= SPEARMAN_MIN
    print(f"  -> {'PASS' if rank_ok else 'FAIL'}")

    # 3. rung agreement
    print(f"\n3. RUNG AGREEMENT — the ladder rung per incumbent trade, identical ≥ {RUNG_SAME_MIN:.0%}, within one ≥ {RUNG_WITHIN1_MIN:.0%}")
    inc_p = arm(ds_pop, reg_pop, sized_fields, COVERAGE, INCUMBENT)
    x7_p = arm(ds_pop, reg_pop, sized_fields, COVERAGE, X7_KEY)
    a_p = arm(ds_pop, reg_pop, sized_fields, COVERAGE, KEY)
    ok1, m1 = check_same_trades(x7_p, inc_p)
    ok2, m2 = check_same_trades(a_p, inc_p)
    print(f"  harness on the joint population: {X7_KEY} {'PASS' if ok1 else 'FAIL'} ({m1}); {KEY} {'PASS' if ok2 else 'FAIL'} ({m2})")
    k = ["seed", "pair", "entry_ts"]
    j = x7_p[k + ["size"]].merge(a_p[k + ["size"]], on=k, suffixes=("_b", "_a"))
    d = np.abs(rung(j["size_b"]) - rung(j["size_a"]))
    same, within1 = float((d == 0).mean()), float((d <= 1).mean())
    print(f"  {len(j):,} trades (X7's {REPLAY_N} less those without an archive row): identical {same:.1%}, within one rung {within1:.1%}, "
          f"two+ apart {float((d >= 2).mean()):.1%}")
    ca = contrast(a_p, inc_p)
    cb = contrast(x7_p, inc_p)
    print(f"  on this population: {KEY} − incumbent {_ci(ca)}; {X7_KEY} − incumbent {_ci(cb)}  (information)")
    rung_ok = ok1 and ok2 and len(j) == len(inc_p) and same >= RUNG_SAME_MIN and within1 >= RUNG_WITHIN1_MIN
    print(f"  -> {'PASS' if rung_ok else 'FAIL'}")

    # 4. per-ingredient, reported
    print("\n4. PER-INGREDIENT (reported, not gated) — Spearman archive vs collector per pair on the population's bars")
    raw = book[["pair", "ts", "trade_count", "trade_vol", "oi_chg"]].merge(
        tab[["pair", "ts", "trade_count", "trade_vol", "oi_chg"]], on=["pair", "ts"], suffixes=("_b", "_a"))
    raw = raw.merge(pop_bars[["pair", "ts"]], on=["pair", "ts"])
    print(f"  {'pair':<14}{'n':>8}{'count':>9}{'volume':>9}{'oi_chg':>9}   market-wide rank: {'count':>7}{'volume':>8}{'oi_chg':>8}")
    for p, g in raw.groupby("pair", sort=True):
        rs = [float(g[[c + "_b", c + "_a"]].corr(method="spearman").iloc[0, 1]) for c in ("trade_count", "trade_vol", "oi_chg")]
        print(f"  {p:<14}{len(g):>8}{rs[0]:>9.3f}{rs[1]:>9.3f}{rs[2]:>9.3f}")
    mk = both.drop_duplicates("ts")
    rm = [float(mk[[c + "_mkt_b", c + "_mkt_a"]].corr(method="spearman").iloc[0, 1]) for c in ("trade_count", "trade_vol", "oi_chg")]
    print(f"  {'market-wide':<14}{len(mk):>8}{'':>27}   {rm[0]:>7.3f}{rm[1]:>8.3f}{rm[2]:>8.3f}")
    # Attribution, description only — never a key: X7's composite has a FOURTH ingredient (the
    # spread) the archive lacks, and its tape ingredients are the collector's last ~10 s poll at
    # the bar rather than the bar's 5-minute total (bookprep: window_start is the last trade of
    # a poll; sidetable: asof within 5 min). The collector's own three-ingredient composite
    # separates the two sources of a disagreement. Nothing here is read as a result.
    pb = pop_bars.merge(obs_book[["pair", "ts", "trade_count_mkt", "trade_vol_mkt", "oi_chg_mkt", "spread_bps_mkt"]],
                        on=["pair", "ts"]).drop_duplicates("ts")
    pb["collector3_lo"] = -pb[["trade_count_mkt", "trade_vol_mkt", "oi_chg_mkt"]].mean(axis=1)
    r_c3_a = float(pb[["collector3_lo", KEY]].corr(method="spearman").iloc[0, 1])
    r_c3_x7 = float(pb[["collector3_lo", X7_KEY]].corr(method="spearman").iloc[0, 1])
    r_sp_x7 = float((-pb["spread_bps_mkt"]).corr(pb[X7_KEY], method="spearman"))
    print(f"  attribution (description, not a gate): Spearman(collector's own three-ingredient composite, {KEY}) {r_c3_a:.3f}; "
          f"Spearman(that composite, {X7_KEY}) {r_c3_x7:.3f}; Spearman(−spread rank, {X7_KEY}) {r_sp_x7:.3f}")

    print("\n" + "=" * 96)
    passed = replay_ok and rank_ok and rung_ok
    if passed:
        marker = {"pass": True, "key_sha8": sha, "table": table, "date": str(pd.Timestamp.now(tz="UTC"))[:19],
                  "replay_n": int(len(inc)), "replay_contrast": c["diff_bps"], "spearman": rho,
                  "rung_same": same, "rung_within1": within1, "n_rung_trades": int(len(j))}
        with open(CHECK_MARKER, "w") as f:
            json.dump(marker, f, indent=1)
        print(f"PREREQUISITE PASS — the archive carries X7's key on the book era; marker {CHECK_MARKER} written.")
        print("next: bookladder --stage archive-confirm --population P1, then P2 (one look each).")
        return 0
    if os.path.exists(CHECK_MARKER):
        os.remove(CHECK_MARKER)
    print(f"PREREQUISITE FAIL (replay {replay_ok}, rank {rank_ok}, rung {rung_ok}) — K1 VOID. The archive cannot carry X7's key; "
          f"nothing further is read; X7's confirmation stays on 2027-03-10 as registered.")
    return 2


# --------------------------------------------------------------------------------------
# archive-confirm — §K1's read, one look per population
# --------------------------------------------------------------------------------------

def _load_population(pop: str) -> tuple[list[dumps.Dump], str, str, str]:
    if pop == "P1":
        d = dumps.load(P1_RUN, seed="s3")
        return [d], P1_START, P1_END, f"P1 — the served checkpoint's dump {P1_RUN} (X8″ s3), {P1_START} → {P1_END} UTC, all its pairs"
    if pop == "P2":
        if dumps.ERA != P2_ERA:
            raise SystemExit(f"P2 reads M3_ERA={P2_ERA}, got {dumps.ERA!r}")
        if dumps.missing_runs():
            raise SystemExit(f"P2 refuses a partial family: {dumps.missing_runs()}")
        ds = [d for d in dumps.load_baseline() if dumps.fold_of(d.seed) in P2_FOLDS]
        lo = min(dumps.FOLD_SPLITS[f][0] for f in P2_FOLDS)
        return ds, lo, P1_START, f"P2 — {P2_ERA} {'+'.join(P2_FOLDS)}, three seeds a fold, bars before {P1_START} UTC"
    raise SystemExit(f"population must be P1 or P2, got {pop!r}")


def _restrict_window(d: dumps.Dump, lo: str, hi: str, strict_hi: bool) -> dumps.Dump:
    t = d.df["ts"]
    a, b = pd.Timestamp(lo, tz="UTC").value, pd.Timestamp(hi, tz="UTC").value
    keep = (t >= a) & ((t < b) if strict_hi else (t <= b))
    return dumps.Dump(seed=d.seed, run_id=d.run_id, df=d.df[keep].reset_index(drop=True))


def _seed_rows(arms: dict, inc: pd.DataFrame, key: str) -> list[str]:
    lines = []
    for s in sorted(inc["seed"].unique()):
        c = contrast(arms[key][arms[key]["seed"] == s], inc[inc["seed"] == s])
        lines.append(f"    {s:<6} {key} − incumbent {_ci(c)}")
    return lines


def confirm_report(sized_fields: dict, pop: str, table: str | None = None) -> int:
    print("=" * 96)
    print(f"BOOK_WAVE2_PLAN §K1 — X7's LADDER KEY ON ARCHIVE HISTORY — population {pop}")
    print("=" * 96)
    if not os.path.exists(CHECK_MARKER):
        print(f"\n🔴 refusing: {CHECK_MARKER} missing — `archivekey check` has not PASSED.")
        return 2
    marker = json.load(open(CHECK_MARKER))
    table = table or marker["table"]
    if not marker.get("pass") or _sha8(table) != marker["key_sha8"]:
        print(f"\n🔴 refusing: the marker is not a PASS on {table} (sha8 {_sha8(table)} vs {marker['key_sha8']}).")
        return 2
    look = LOOK_MARKER.format(pop=pop)
    if os.path.exists(look):
        print(f"\n🔴 refusing: {look} exists — §K1 allows ONE look at {pop}, read on {json.load(open(look))['date']}.")
        return 2
    print(f"prerequisite PASS {marker['date']}: replay {marker['replay_n']} trades / {marker['replay_contrast']:+.2f}, "
          f"Spearman {marker['spearman']:.3f}, rungs identical {marker['rung_same']:.1%} / within one {marker['rung_within1']:.1%}")

    ds_raw, lo, hi, label = _load_population(pop)
    print(f"\n{label}")
    ds = [_restrict_window(d, lo, hi, strict_hi=(pop == "P2")) for d in ds_raw]
    pairs = sorted({p for d in ds for p in d.df["pair"].unique()})
    tab = load_table(table, pairs=pairs, lo=lo, hi=hi)
    obs = observables(tab)
    ds_pop, regimes = population(ds, obs, [KEY])
    n_bars = 0
    for d in ds_pop:
        t = pd.to_datetime(d.df["ts"], unit="ns", utc=True)
        nb = d.df[["pair", "ts"]].drop_duplicates().shape[0]
        n_bars += nb
        print(f"  {d.seed}: {nb:,} bars x {d.df['pair'].nunique()} pairs, {t.min():%Y-%m-%d %H:%M} .. {t.max():%Y-%m-%d %H:%M}")

    verdict_lines = []
    out = {"population": pop, "date": str(pd.Timestamp.now(tz="UTC"))[:19], "key_sha8": marker["key_sha8"]}
    for cov in (COVERAGE, COVERAGE_INFO):
        print("\n" + "=" * 96)
        print(f"COVERAGE {cov} — {'PRIMARY' if cov == COVERAGE else 'information only'}")
        print("=" * 96)
        arms = {"incumbent": arm(ds_pop, regimes, sized_fields, cov, INCUMBENT),
                "flat": arm(ds_pop, regimes, sized_fields, cov, None),
                KEY: arm(ds_pop, regimes, sized_fields, cov, KEY)}
        inc = arms["incumbent"]
        bad = False
        for name in ("flat", KEY):
            ok, msg = check_same_trades(arms[name], inc)
            print(f"  harness check {name}: {'PASS' if ok else 'FAIL'} — {msg}")
            bad |= not ok
        if bad:
            print("  🔴 harness check failed; nothing below may be read.")
            return 3
        e = contrast(inc, arms["flat"])
        kf = contrast(arms[KEY], arms["flat"])
        c = contrast(arms[KEY], inc)
        days = float((inc["exit_ts"].max() - inc["entry_ts"].min()) / 86_400e9) if len(inc) else 0.0
        print(f"  {len(inc):,} trades, span {days:.1f} days, {inc['seed'].nunique()} dump(s)")
        for name in ("incumbent", "flat", KEY):
            n = wf.notional_ratio_bps(ledger(arms[name]), COST)
            print(f"  {name:<18} net/notional @{COST:g}: {n['mean_bps']:+.2f} [{n['lo95_bps']:+.2f}, {n['hi95_bps']:+.2f}]")
        print(f"  E  (incumbent − flat)        {_ci(e)}")
        print(f"  {KEY} − flat    {_ci(kf)}")
        print(f"  {KEY} − incumbent  {_ci(c)}   <-- the contrast")
        if inc["seed"].nunique() > 1:
            print("\n".join(_seed_rows(arms, inc, KEY)))
            if pop == "P2":
                for f in P2_FOLDS:
                    cf = contrast(arms[KEY][arms[KEY]["seed"].str.startswith(f)],
                                  inc[inc["seed"].str.startswith(f)])
                    print(f"    {f:<6} pooled over its seeds: {KEY} − incumbent {_ci(cf)}")
        out[f"cov{cov}"] = {"n": int(len(inc)), "contrast": c, "E": e, "key_minus_flat": kf}
        if cov != COVERAGE:
            continue

        # the secondary: the causal rank, its own population (30-day warm-up), information only
        obs_c = causal_observables(tab)
        ds_c, reg_c = population(ds, obs_c, [KEY_CAUSAL])
        inc_c = arm(ds_c, reg_c, sized_fields, cov, INCUMBENT)
        a_c = arm(ds_c, reg_c, sized_fields, cov, KEY_CAUSAL)
        okc, msgc = check_same_trades(a_c, inc_c)
        cc = contrast(a_c, inc_c)
        print(f"\n  secondary, information only — trailing-30-day causal ranks on their own population "
              f"({len(inc_c):,} trades; harness {'PASS' if okc else 'FAIL'}): {KEY_CAUSAL} − incumbent {_ci(cc)}")
        out["causal"] = {"n": int(len(inc_c)), "contrast": cc}

        print("\n" + "=" * 96)
        print("THE VERDICT, under §K1 as written")
        print("=" * 96)
        lo95, hi95 = c["lo95_bps"], c["hi95_bps"]
        if pop == "P1":
            if lo95 > 0:
                v = "CONFIRMED — the 95 % lower bound of the contrast on P1 is above zero"
            elif not (lo95 <= e["diff_bps"] <= hi95):
                v = f"NOT CONFIRMED — the interval excludes zero's side and E ({e['diff_bps']:+.2f}); book-keyed sizing closes NOW, the 2027-03-10 look is cancelled"
            else:
                v = f"NOT DETECTABLE — the interval spans zero and E ({e['diff_bps']:+.2f}); X7 stays parked to 2027-03-10, unchanged"
            if lo95 > 0:
                v += "; licenses WRITING a served-change registration for the ladder key; the 2027-03-10 look becomes the second confirmation"
        else:
            v = (f"REPLICATION {'AGREES' if c['diff_bps'] > 0 else 'FAILED'} in sign (point {c['diff_bps']:+.2f}); "
                 f"reported beside P1, not deciding — if P1 is CONFIRMED and this point is negative, the result is "
                 f"CONFIRMED, REPLICATION FAILED")
        print(f"  {KEY} − incumbent on {pop}: {_ci(c)}")
        print(f"\n  ==> {v}")
        out["verdict"] = v
        verdict_lines.append(v)
    with open(look, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"\nlook recorded: {look}")
    return 0


# --------------------------------------------------------------------------------------

def add_parser(sub) -> None:
    ap = sub.add_parser("archivekey", help="BOOK_WAVE2_PLAN §K1: X7's ladder key from the archive — "
                        "fetch the 5m klines, reduce to the key table, run the prerequisite (exit 2 = VOID)")
    s2 = ap.add_subparsers(dest="job", required=True)
    f = s2.add_parser("fetch")
    f.add_argument("--pairs", default=",".join(DEFAULT_PAIRS))
    f.add_argument("--from", dest="start", default=FETCH_FROM)
    f.add_argument("--to", dest="end", default=FETCH_TO)
    f.add_argument("--cache", default=KLINES_CACHE)
    f.add_argument("--out", default=KLINES_OUT)
    f.add_argument("--threads", type=int, default=12)
    r = s2.add_parser("reduce")
    r.add_argument("--klines", default=None, help="default: the newest klines_um_5m_*.parquet")
    r.add_argument("--metrics", default=None, help="default: the newest metrics_um_5m_*.parquet (X8's)")
    r.add_argument("--out", default=KEY_OUT)
    c = s2.add_parser("check")
    c.add_argument("--table", default=None, help="default: the newest archive_key_5m_*.parquet")
    ap.set_defaults(fn=_main)


def _main(args) -> int:
    if args.job == "fetch":
        pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
        fetch(pairs, args.start, args.end, args.cache, args.out, args.threads)
        return 0
    if args.job == "reduce":
        reduce(args.klines or _newest(KLINES_OUT.replace(".parquet", "_*.parquet")),
               args.metrics or _newest(METRICS_GLOB), args.out)
        return 0
    from .cli import WINNER_SPEC
    return check(WINNER_SPEC, args.table)
