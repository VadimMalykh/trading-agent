"""Decision CW1 (2026-11-17), step (i): the Data line for the NEXT SIXTY (ranks 61–120 of the screener's unchanged rule; the four frozen
lists `ft2/screen_next60_{pre,f12,f34,f5}.csv`, F5's PERPETUAL rows only) — `ft2 next60data plan|klines|funding|metrics|mix|cover`.

Nothing here reads a label, a forecast or an IC: files are fetched, tables re-written, and every row a table held before is checked to be
back unchanged (a missing or changed old row voids the step, exit 2).

What a row of a list needs (block [a, b), b = a + 30 days cut at the segment's end):
klines    the monthly 5m files of a − 91 days (the 12-week momentum's lookback and a week) … b + 2 days (the one-day label), cut at the
          segment's end. Only these months are asked for: a re-used ticker (ANTUSDT, NUUSDT, MDTUSDT) gets nothing of its later contract.
funding   the monthly files of a − 10 days … b.
metrics   the daily files of a − 10 days … b (the positioning features look back ≤ 9 days).
mix       no fetch: the hourly perpetual trade table rebuilt from the 5m zips on disk for the names it already holds (`mix.symbols()`).
The hourly sources of the frozen lists (spot, Coinbase, Korea, Hyperliquid, Wikipedia, the book) stay as they stand — no list is extended.

How the tables are written: the VM holds a member's months, so most fetched months fill HOLES inside a name's old extent — the extent
fingerprint (R28's) reads those names as changed. The check here is the row itself: every old (symbol, stamp) row is in the new table
with identical values (`old_rows_in`, against a before-copy). The slice and the metrics table are written a name at a time
(`stream_klines`, `stream_metrics`): the same rows in the same order as `data.ingest_klines` / `ingest_metrics`, without the whole-table
concat (≈ 140M candle rows / ≈ 105M metrics rows do not fit 32 GB three times over).

cover     `allgbm.cover` with a next-sixty list as the members — scorable cells a block and each input's cover; features only.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data, folds, universe

OUT = Path("output/next60data")
HERE = Path(__file__).parent
LISTS = {"pre": HERE / "screen_next60_pre.csv", "f12": HERE / "screen_next60_f12.csv", "f34": HERE / "screen_next60_f34.csv", "f5": HERE / "screen_next60_f5.csv"}
F5_COINS_CSV = HERE / "screen_next60_f5_coins.csv"          # the F5 list's PERPETUAL rows (478) — a filter of the frozen list, nothing chosen
ENDS = {"pre": universe.PRE_END, "f12": folds.bounds("F2")[1], "f34": folds.bounds("F4")[1], "f5": folds.bounds("F5")[1]}
BLOCK = pd.Timedelta(days=30)
LOOKBACK = pd.Timedelta(days=91)
AFTER = pd.Timedelta(days=2)
BACK_DAYS = pd.Timedelta(days=10)
SLICE = "candles_5m_archive"
TAG = "cw1"                                                  # the before-copies: data/<table>_before_cw1.parquet
MIN_COVER = 0.95


def rows() -> pd.DataFrame:
    """Every (segment, block, symbol) row of the four lists (F5: the PERPETUAL rows), with the block [a, b)."""
    parts = []
    for seg, p in LISTS.items():
        m = pd.read_csv(p)
        if seg == "f5":
            m = m[m["type"] == "PERPETUAL"]
        a = pd.to_datetime(m["block"], utc=True)
        parts.append(pd.DataFrame({"seg": seg, "symbol": m["symbol"].astype(str).to_numpy(), "a": a.to_numpy(), "b": np.minimum(a + BLOCK, ENDS[seg]).to_numpy()}))
    R = pd.concat(parts, ignore_index=True)
    R["a"], R["b"] = pd.to_datetime(R["a"], utc=True), pd.to_datetime(R["b"], utc=True)
    return R


def names() -> list[str]:
    return sorted(set(rows()["symbol"]))


def _merge(iv: list[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for s, e in sorted(iv):
        if out and (s - out[-1][1]).days <= 1:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def need(R: pd.DataFrame | None = None) -> dict:
    """{"klines": {name: [months]}, "funding": {name: [months]}, "metrics": {name: [(first day, last day), …]}} from the lists alone."""
    R = rows() if R is None else R
    kl: dict[str, set] = {}
    fu: dict[str, set] = {}
    me: dict[str, list] = {}
    sec = pd.Timedelta(seconds=1)
    for r in R.itertuples(index=False):
        end = ENDS[r.seg]
        kl.setdefault(r.symbol, set()).update(archive.months_between((r.a - LOOKBACK).date(), (min(r.b + AFTER, end) - sec).date()))
        fu.setdefault(r.symbol, set()).update(archive.months_between((r.a - BACK_DAYS).date(), (r.b - sec).date()))
        me.setdefault(r.symbol, []).append(((r.a - BACK_DAYS).date(), (r.b - sec).date()))
    return {"klines": {s: sorted(v) for s, v in sorted(kl.items())}, "funding": {s: sorted(v) for s, v in sorted(fu.items())},
            "metrics": {s: _merge(v) for s, v in sorted(me.items())}}


def _write(name: str, rep: dict) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


def _ok(kind: str, sym: str, name: str) -> bool:
    f = data.EXT / kind / sym / name
    return f.exists() and f.with_suffix(".zip.ok").exists()


def _zips(sym: str) -> set[str]:
    return {f.name for f in (data.EXT / "klines" / sym).glob(f"{sym}-5m-*.zip")}


def held(table: str) -> list[str]:
    """The names a table holds, read a row group at a time (no string copy of the column)."""
    import pyarrow.parquet as pq
    p = data.PROC / f"{table}.parquet"
    if not p.exists():
        return []
    f = pq.ParquetFile(p)
    out: set[str] = set()
    for i in range(f.num_row_groups):
        out |= set(map(str, f.read_row_group(i, columns=["symbol"]).column("symbol").unique().to_pylist()))
    return sorted(out)


def before_copy(table: str) -> Path:
    src, dst = data.PROC / f"{table}.parquet", data.PROC / f"{table}_before_{TAG}.parquet"
    if not dst.exists():
        shutil.copy2(src, dst.with_suffix(".tmp"))
        os.replace(dst.with_suffix(".tmp"), dst)
    return dst


# ---- the row check -------------------------------------------------------------------------------------------------------------------
def _read(path: Path, tcol: str, cols: tuple[str, ...]) -> pd.DataFrame:
    d = pd.read_parquet(path, columns=["symbol", tcol, *cols])
    if not isinstance(d["symbol"].dtype, pd.CategoricalDtype):
        d["symbol"] = d["symbol"].astype("category")
    d[tcol] = pd.to_datetime(d[tcol], utc=True)
    return d


def old_rows_in(old: pd.DataFrame, new: pd.DataFrame, tcol: str, cols: tuple[str, ...]) -> dict:
    """Every (symbol, stamp) row of `old` is in `new` with identical `cols` (NaN equal to NaN). Both sorted by (symbol, stamp) or not —
    each name's stamps are sorted here. Returns the counts; `pass` is no missing and no changed row."""
    def per_name(d):
        codes = d["symbol"].cat.codes.to_numpy()
        cats = [str(c) for c in d["symbol"].cat.categories]
        t = pd.DatetimeIndex(d[tcol]).asi8
        order = np.lexsort((t, codes))
        codes, t = codes[order], t[order]
        cut = np.searchsorted(codes, np.arange(len(cats) + 1))
        return cats, t, order, cut
    oc, ot, oo, ocut = per_name(old)
    nc, nt, no, ncut = per_name(new)
    npos = {c: i for i, c in enumerate(nc)}
    ovals = {c: old[c].to_numpy()[oo] for c in cols}
    nvals = {c: new[c].to_numpy()[no] for c in cols}
    missing = changed = n_names = 0
    bad: dict[str, dict] = {}
    for i, c in enumerate(oc):
        a, b = ocut[i], ocut[i + 1]
        if a == b:
            continue
        n_names += 1
        if c not in npos:
            missing += b - a
            bad[c] = {"missing": int(b - a), "changed": 0}
            continue
        x, y = ncut[npos[c]], ncut[npos[c] + 1]
        pos = np.searchsorted(nt[x:y], ot[a:b])
        hit = (pos < y - x) & (nt[x:y][np.minimum(pos, max(y - x - 1, 0))] == ot[a:b]) if y > x else np.zeros(b - a, dtype=bool)
        m = int((~hit).sum())
        diff = np.zeros(int(hit.sum()), dtype=bool)
        for k in cols:
            u, v = ovals[k][a:b][hit], nvals[k][x:y][pos[hit]]
            both_nan = pd.isna(u) & pd.isna(v)
            diff |= ~((u == v) | both_nan)
        ch = int(diff.sum())
        if m or ch:
            bad[c] = {"missing": m, "changed": ch}
        missing += m
        changed += ch
    return {"names_checked": n_names, "rows_checked": int(len(old)), "rows_new": int(len(new)), "old_rows_missing": int(missing), "old_rows_changed": int(changed),
            "bad_names": dict(list(bad.items())[:50]), "pass": missing == 0 and changed == 0}


def check_table(table: str, tcol: str, passes: tuple[tuple[str, ...], ...]) -> dict:
    """`old_rows_in` of data/<table>_before_cw1.parquet against data/<table>.parquet, a few columns a pass (memory)."""
    rep = {"pass": True, "passes": []}
    for cols in passes:
        old = _read(data.PROC / f"{table}_before_{TAG}.parquet", tcol, cols)
        new = _read(data.PROC / f"{table}.parquet", tcol, cols)
        r = old_rows_in(old, new, tcol, cols)
        del old, new
        rep["passes"].append({"cols": list(cols), **r})
        rep["pass"] = rep["pass"] and r["pass"]
    return rep


# ---- the tables, a name at a time ----------------------------------------------------------------------------------------------------
def _stream(dst: Path, parts) -> dict:
    """Write the (table part, rows read) pairs of `parts` to `dst` through a temporary file; a killed run leaves the old table whole."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    tmp = dst.with_suffix(".parquet.tmp")
    writer, n_in, n_out, first, last, n_names = None, 0, 0, None, None, 0
    try:
        for part, n, tcol in parts:
            if not len(part):
                continue
            t = pa.Table.from_pandas(part, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(tmp, t.schema)
            elif t.schema.remove_metadata() != writer.schema.remove_metadata():
                raise SystemExit(f"stream: the part of {part['symbol'].iloc[0]} has another schema:\n{t.schema}\n— the first part's:\n{writer.schema}")
            writer.write_table(t)
            n_in, n_out, n_names = n_in + n, n_out + len(part), n_names + 1
            first = part[tcol].iloc[0] if first is None else min(first, part[tcol].iloc[0])
            last = part[tcol].iloc[-1] if last is None else max(last, part[tcol].iloc[-1])
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        raise SystemExit("stream: no rows")
    os.replace(tmp, dst)
    return {"slice": dst.stem, "names": n_names, "rows_in": n_in, "dups_dropped": n_in - n_out, "rows_out": n_out, "first": str(first), "last": str(last), "file": str(dst)}


def stream_klines(symbols: list[str], interval: str = "5m") -> dict:
    """`data.ingest_klines`' rows in its order — per name sorted by open_time, a bar kept once (the last file's) — written a name at a time."""
    def parts():
        for sym in sorted(set(symbols)):
            out, n = data.kline_part(sym, [sym], interval)
            if n:
                yield out.reset_index(drop=True), n, "open_time"
    return _stream(data.PROC / f"candles_{interval}_archive.parquet", parts())


def metrics_dtypes() -> dict:
    """The value columns' types in the table as it stands (float64 where there is no table): a name's part is cast to them, so the
    table keeps the types the whole-table concat gave it."""
    import pyarrow.parquet as pq
    p = data.PROC / "metrics.parquet"
    vals = [c for c in data.METRICS_COLS.values() if c != "ts"]
    if not p.exists():
        return dict.fromkeys(vals, "float64")
    e = pq.read_schema(p).empty_table().to_pandas()
    return {c: str(e[c].dtype) for c in vals}


def metrics_part(sym: str, dtypes: dict | None = None) -> tuple[pd.DataFrame, int]:
    dtypes = metrics_dtypes() if dtypes is None else dtypes
    df = data._read_zips("metrics", sym)
    if df.empty:
        return pd.DataFrame(), 0
    vals = [c for c in data.METRICS_COLS.values() if c != "ts"]
    df = df.rename(columns=data.METRICS_COLS)[["symbol", "ts", *vals]]
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if set(df["symbol"].astype(str)) != {sym}:
        raise ValueError(f"metrics of {sym}: the files' symbol column holds {set(df['symbol'].astype(str))}")
    df["symbol"] = pd.Categorical(df["symbol"].astype(str), categories=[sym])
    for c in vals:
        df[c] = df[c].astype(dtypes[c])
    n = len(df)
    return df.sort_values("ts", kind="mergesort").drop_duplicates("ts", keep="last").reset_index(drop=True), n


def stream_metrics(symbols: list[str]) -> dict:
    """`data.ingest_metrics`' rows in its order, written a name at a time."""
    dtypes = metrics_dtypes()

    def parts():
        for sym in sorted(set(symbols)):
            out, n = metrics_part(sym, dtypes)
            if n:
                yield out, n, "ts"
    return _stream(data.PROC / "metrics.parquet", parts())


# ---- the steps -----------------------------------------------------------------------------------------------------------------------
def plan() -> dict:
    """What the lists need against what is on disk — no network."""
    R, N = rows(), need()
    rep = {"rows": {s: int(n) for s, n in R.groupby("seg").size().items()}, "names": {s: int(g["symbol"].nunique()) for s, g in R.groupby("seg")}, "names_all": len(names())}
    for kind, sub, src in (("klines", "5m", "klines"), ("funding", "fundingRate", "fundingRate")):
        want = [(s, f"{s}-{sub}-{m}.zip") for s, ms in N[kind].items() for m in ms]
        have = sum(_ok(src, s, f) for s, f in want)
        rep[kind] = {"month_files_needed": len(want), "on_disk": int(have), "to_fetch_at_most": len(want) - int(have)}
    want = [(s, f"{s}-metrics-{d:%Y-%m-%d}.zip") for s, iv in N["metrics"].items() for a, b in iv for d in pd.date_range(a, b)]
    have = sum(_ok("metrics", s, f) for s, f in want)
    rep["metrics"] = {"day_files_needed": len(want), "on_disk": int(have), "to_fetch_at_most": len(want) - int(have)}
    _write("plan", rep)
    print(json.dumps(rep, indent=1, default=str), flush=True)
    return rep


def _fail(rep: dict) -> None:
    if not rep["pass"]:
        raise SystemExit(2)


def klines_cover(R: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per list row: the share of the block's 5m bars the slice (and the collector's table) holds, and of the lookback's."""
    R = rows() if R is None else R
    N = sorted(set(R["symbol"]))
    d = pd.concat([data.load(s, columns=["symbol", "open_time"], symbols=N) for s in (SLICE, "candles_5m")], ignore_index=True)
    d["open_time"] = pd.to_datetime(d["open_time"], utc=True)
    d["symbol"] = d["symbol"].astype(str)
    d = d.drop_duplicates(["symbol", "open_time"])
    ts = {s: np.sort(pd.DatetimeIndex(g).asi8) for s, g in d.groupby("symbol")["open_time"]}
    bar = pd.Timedelta("5min").value
    out = []
    for r in R.itertuples(index=False):
        t = ts.get(r.symbol, np.array([], dtype="int64"))
        cnt = lambda x, y: int(np.searchsorted(t, y.value) - np.searchsorted(t, x.value))          # noqa: E731
        out.append({"seg": r.seg, "block": r.a.date(), "symbol": r.symbol, "block_cover": cnt(r.a, r.b) / max((r.b - r.a).value // bar, 1),
                    "lookback_cover": cnt(r.a - LOOKBACK, r.a) / (LOOKBACK.value // bar)})
    return pd.DataFrame(out)


def klines() -> dict:
    N = need()["klines"]
    OUT.mkdir(parents=True, exist_ok=True)
    before_copy(SLICE)
    before = {s: _zips(s) for s in N}
    rep = {"names": len(N), "month_files_needed": int(sum(len(v) for v in N.values()))}
    rep["fetch"] = {s: archive.fetch_monthly("klines", s, sub="5m", months=ms) for s, ms in N.items()}
    rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
    rep["new_files"] = int(sum(len(_zips(s) - before[s]) for s in N))
    _write("klines", rep)                                                  # before the ingest: a killed ingest leaves the fetch's record
    rep["ingest"] = stream_klines(list(dict.fromkeys([*held(SLICE), *N])))
    return klines_check(rep)


def klines_check(rep: dict | None = None) -> dict:
    """The check alone (also a resumed run's): the old rows, then the lists' cover."""
    rep = json.loads((OUT / "klines.json").read_text()) if rep is None else rep
    rep["old_rows"] = check_table(SLICE, "open_time", (("open", "high", "low"), ("close", "volume", "quote_volume")))
    rep["pass"] = rep["old_rows"]["pass"]
    _write("klines", rep)
    C = klines_cover()
    C.to_csv(OUT / "klines_cover.csv", index=False, float_format="%.4f")
    rep["cover"] = {seg: {"rows": int(len(g)), f"block_cover_at_least_{MIN_COVER}": int((g["block_cover"] >= MIN_COVER).sum()), "rows_without_a_bar": int((g["block_cover"] == 0).sum()),
                          f"lookback_cover_at_least_{MIN_COVER}": int((g["lookback_cover"] >= MIN_COVER).sum())} for seg, g in C.groupby("seg")}
    _write("klines", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    _fail(rep)
    return rep


def funding() -> dict:
    """The names' needed monthly funding files fetched; every row of theirs the table does not hold comes in (a hole inside a name's old
    extent too — `fundevent.funding_update` appends only after a name's last stamp); every old row kept to the digit."""
    N = need()["funding"]
    path = before_copy("funding_archive")
    old = pd.read_parquet(path)
    old["symbol"] = old["symbol"].astype(str)
    old["ts"] = pd.to_datetime(old["ts"], utc=True)
    rep = {"names": len(N), "rows_before": int(len(old)), "names_before": int(old["symbol"].nunique())}
    rep["fetch"] = {s: archive.fetch_monthly("fundingRate", s, months=ms) for s, ms in N.items()}
    rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
    have = {s: set(pd.DatetimeIndex(g).asi8) for s, g in old[old["symbol"].isin(N)].groupby("symbol")["ts"]}
    parts, added = [], {}
    for sym in N:
        df = data._read_zips("fundingRate", sym)
        if df.empty:
            added[sym] = 0
            continue
        new = pd.DataFrame({"symbol": sym, "ts": pd.to_datetime(df["calc_time"], unit="ms", utc=True).dt.round("s"), "rate": df["last_funding_rate"].astype(float),
                            "interval_h": df["funding_interval_hours"].astype("int16")})
        new = new.sort_values("ts", kind="mergesort").drop_duplicates(["symbol", "ts"], keep="last")
        new = new[~np.isin(pd.DatetimeIndex(new["ts"]).asi8, np.fromiter(have.get(sym, ()), dtype="int64"))]
        added[sym] = int(len(new))
        if len(new):
            parts.append(new)
    out = pd.concat([old, *parts], ignore_index=True).sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    assert not out.duplicated(["symbol", "ts"]).any()
    chk = old.merge(out, on=["symbol", "ts"], how="left", suffixes=("_o", "_n"))
    same = bool(len(chk) == len(old) and chk["rate_n"].notna().all() and np.allclose(chk["rate_o"], chk["rate_n"], atol=0, rtol=0) and (chk["interval_h_o"].to_numpy() == chk["interval_h_n"].to_numpy()).all())
    rep.update({"rows_added": int(sum(added.values())), "names_gaining_rows": int(sum(v > 0 for v in added.values())), "rows_after": int(len(out)), "names_after": int(out["symbol"].nunique()),
                "old_rows_identical": same, "pass": same})
    if same:
        R = rows()
        ts = {s: np.sort(pd.DatetimeIndex(g).asi8) for s, g in out[out["symbol"].isin(N)].groupby("symbol")["ts"]}
        n_in = [int(np.searchsorted(ts.get(r.symbol, np.array([], dtype="int64")), r.b.value) - np.searchsorted(ts.get(r.symbol, np.array([], dtype="int64")), (r.a - pd.Timedelta(days=7)).value))
                for r in R.itertuples(index=False)]
        R["stamps"] = n_in
        rep["cover"] = {seg: {"rows": int(len(g)), "rows_with_a_stamp": int((g["stamps"] > 0).sum()), "names_without": sorted(set(g.loc[g["stamps"] == 0, "symbol"]))[:40]} for seg, g in R.groupby("seg")}
        out["symbol"] = out["symbol"].astype("category")
        out.to_parquet(data.PROC / "funding_archive.parquet", index=False)
    _write("funding", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    _fail(rep)
    return rep


def metrics() -> dict:
    N = need()["metrics"]
    before_copy("metrics")
    rep = {"names": len(N), "day_files_needed": int(sum((b - a).days + 1 for iv in N.values() for a, b in iv))}
    fetch = {}
    for s, iv in N.items():
        tot = {"ok": 0, "skip": 0, "bad": 0, "err": 0, "missing": 0}
        for a, b in iv:
            for k, v in archive.fetch_daily("metrics", s, a, b).items():
                tot[k] += v
        fetch[s] = tot
    rep["fetch"] = fetch
    rep["fetch_totals"] = {k: int(sum(v[k] for v in fetch.values())) for k in ("ok", "skip", "bad", "err", "missing")}
    _write("metrics", rep)
    rep["ingest"] = stream_metrics(list(dict.fromkeys([*held("metrics"), *N])))
    return metrics_check(rep)


def metrics_check(rep: dict | None = None) -> dict:
    rep = json.loads((OUT / "metrics.json").read_text()) if rep is None else rep
    rep["old_rows"] = check_table("metrics", "ts", (("oi", "oi_value", "top_ls_count"), ("top_ls_sum", "global_ls", "taker_ratio")))
    rep["pass"] = rep["old_rows"]["pass"]
    _write("metrics", rep)
    R = rows()
    N = sorted(set(R["symbol"]))
    d = _read(data.PROC / "metrics.parquet", "ts", ())
    d = d[d["symbol"].isin(N)]
    ts = {str(s): np.sort(pd.DatetimeIndex(g).asi8) for s, g in d.groupby("symbol", observed=True)["ts"]}
    del d
    bar = pd.Timedelta("5min").value
    e = np.array([], dtype="int64")
    R["cover"] = [(np.searchsorted(ts.get(r.symbol, e), r.b.value) - np.searchsorted(ts.get(r.symbol, e), r.a.value)) / max((r.b - r.a).value // bar, 1) for r in R.itertuples(index=False)]
    R.assign(block=R["a"].dt.date)[["seg", "block", "symbol", "cover"]].to_csv(OUT / "metrics_cover.csv", index=False, float_format="%.4f")
    rep["cover"] = {seg: {"rows": int(len(g)), f"block_cover_at_least_{MIN_COVER}": int((g["cover"] >= MIN_COVER).sum()), "rows_without_a_row": int((g["cover"] == 0).sum())} for seg, g in R.groupby("seg")}
    _write("metrics", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    _fail(rep)
    return rep


def mix() -> dict:
    from . import mix as mx
    before_copy("perp_mix_1h")
    cols = ("count", "quote_volume", "close", "taker_buy_quote_volume")
    rep = {"before": mx.fingerprint(mx.load(data.PROC / f"perp_mix_1h_before_{TAG}.parquet")), "ingest": mx.ingest(verbose=False)}
    old, new = _read(data.PROC / f"perp_mix_1h_before_{TAG}.parquet", "ts", cols), _read(mx.PARQUET, "ts", cols)
    rep["old_rows"] = old_rows_in(old, new, "ts", cols)
    rep["pass"] = rep["old_rows"]["pass"]
    N = set(names())
    rep["next_sixty_names_in_the_table"] = int(new.loc[new["symbol"].isin(N), "symbol"].astype(str).nunique())
    _write("mix", rep)
    print(json.dumps(rep, indent=1, default=str), flush=True)
    _fail(rep)
    return rep


def cover(seg: str) -> None:
    """The features-only cover of one segment's next sixty (`allgbm.cover`, the list as the members) → output/allgbm/cover_next60_<seg>/."""
    from . import allgbm
    name = f"cover_next60_{seg}"
    if seg == "pre":
        allgbm.cover(name, LISTS["pre"], (), universe.PRE_END, allgbm.PRE_START, allgbm.PRE_GRIDS, span=allgbm.PRE_SPAN)
    elif seg == "f12":
        allgbm.cover(name, LISTS["f12"], ("F1", "F2"), None, None, None)
    elif seg == "f34":
        allgbm.cover(name, LISTS["f34"], allgbm.CONF_FOLDS, folds.bounds("F4")[1], allgbm.CONF_START, allgbm.CONF_GRIDS)
    elif seg == "f5":
        allgbm.cover(name, F5_COINS_CSV, ("F5",), folds.bounds("F5")[1], allgbm.F5_START, allgbm.F5_GRIDS)
    else:
        raise SystemExit("next60data cover: --seg pre | f12 | f34 | f5")
    print(f"wrote {allgbm.OUT / name}/")


def main(action: str, seg: str | None = None) -> None:
    if action == "cover":
        return cover(seg or "")
    {"plan": plan, "klines": klines, "klinescheck": klines_check, "funding": funding, "metrics": metrics, "metricscheck": metrics_check, "mix": mix}[action]()
