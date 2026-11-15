"""Decision CU1 (2026-11-15): the Data line for the screener's members BEFORE F1 — `ft2 predata klines|spot|coinbase|korea`.

Nothing here reads a label, a forecast or an IC: files are fetched, tables re-ingested, and every row a table held before is checked
to be back unchanged (a changed old row voids the step, exit 2). The names are the frozen `ft2/screen_members_pre.csv` (R23's list);
the hourly sources are fetched only for the names their own FROZEN lists keep (no list is extended — R91's rule).

klines    the monthly 5m klines of KL_MONTHS (2021-09, 2021-10: the 12-week momentum's lookback before 2021-12-10 — the slice held
          these names from 2021-11) for every pre name; the archive slice re-ingested whole; R28's extent fingerprint, R78's row check.
spot      Binance spot 1h klines of SRC_MONTHS for R68's kept names among the pre names; `spot.ingest`; the old rows identical.
coinbase  Coinbase's hourly candles of SRC_MONTHS for R62's kept names among the pre names and the control USDT-USD; month files that
          exist are never rewritten (the fetchers' own loop would rewrite the boundary month); `coinbase.ingest`; the old rows identical.
korea     Bithumb's hourly candles of SRC_MONTHS for R64's kept names among the pre names and KRW-BTC; the same rule.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data, krlist, universe

OUT = Path("output/predata")
KL_MONTHS = archive.months_between(date(2021, 9, 1), date(2021, 10, 31))
SRC_START, SRC_END = "2021-11-01", "2023-03-31"                          # the hourly sources: a month before the first scored day's trailing month … the month before their tables begin
SRC_MONTHS = archive.months_between(date(2021, 11, 1), date(2023, 3, 31))


def names() -> list[str]:
    return universe.screen_symbols(universe.PRE_MEMBERS_CSV)


def _write(name: str, rep: dict) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


def old_rows(d: pd.DataFrame, key: str, cols: tuple[str, ...]) -> dict:
    """A table's fingerprint: rows, names, first / last stamp, the sums of `cols` (rounded) — compared before and after on the old extent."""
    return {"rows": int(len(d)), "names": int(d[key].astype(str).nunique()) if len(d) else 0, "first": str(d["ts"].min()) if len(d) else None,
            "last": str(d["ts"].max()) if len(d) else None, **{f"sum_{c}": float(np.round(float(d[c].sum()), 6)) if len(d) else 0.0 for c in cols}}


def same_old(before: dict, after: pd.DataFrame, key: str, cols: tuple[str, ...]) -> tuple[bool, dict]:
    """`after` cut at the old table's first stamp must carry the old fingerprint (sums to 1e-9 relative)."""
    if before["rows"] == 0:
        return True, old_rows(after.iloc[:0], key, cols)
    a = old_rows(after[after["ts"] >= pd.Timestamp(before["first"])], key, cols)
    ok = all(a[k] == before[k] for k in ("rows", "names", "first", "last")) and all(np.isclose(a[f"sum_{c}"], before[f"sum_{c}"], rtol=1e-9, atol=1e-6) for c in cols)
    return bool(ok), a


def _zips(sym: str) -> set[str]:
    return {f.name for f in (data.EXT / "klines" / sym).glob(f"{sym}-5m-*.zip")}


def klines() -> dict:
    N = names()
    OUT.mkdir(parents=True, exist_ok=True)
    fp = krlist.fingerprint()
    fp.to_csv(OUT / "fingerprint_before.csv", index=False)
    before = {s: _zips(s) for s in N}
    rep = {"names": len(N), "months": [KL_MONTHS[0], KL_MONTHS[-1]], "names_fingerprinted": int(len(fp))}
    rep["fetch"] = {s: archive.fetch_monthly("klines", s, sub="5m", months=list(KL_MONTHS)) for s in N}
    rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
    new_files = {s: sorted(_zips(s) - before[s]) for s in N}
    rep["new_files"] = int(sum(len(v) for v in new_files.values()))
    _write("klines", rep)
    rep["ingest"] = {k: str(v) for k, v in data.ingest_klines(krlist.ingest_symbols(N)).items()}
    chk = krlist.fingerprint_check(fp, after_fn=krlist.fingerprint)
    rep["fingerprint"] = {"pass": chk["pass"], "changed": [c["symbol"] for c in chk["changed"]], "names_before": chk["names_before"], "names_after": chk["names_after"]}
    rows = [krlist.rowcheck(c["symbol"], set(new_files.get(c["symbol"], []))) for c in chk["changed"] if c["why"] == "changed"]
    rep["rowcheck"] = rows
    rep["pass"] = bool(chk["pass"] or (all(c["why"] == "changed" for c in chk["changed"]) and all(r["pass"] for r in rows)))
    have = data.load(krlist.SLICE, columns=["symbol", "open_time"], symbols=N)
    have["open_time"] = pd.to_datetime(have["open_time"], utc=True)
    g = have.groupby(have["symbol"].astype(str))["open_time"].agg(["min", "max", "size"])
    rep["names_with_bars"] = int(len(g))
    rep["names_starting_by_2021_09_02"] = int((g["min"] < pd.Timestamp("2021-09-02", tz="UTC")).sum())
    g.to_csv(OUT / "klines_extent.csv")
    _write("klines", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    if not rep["pass"]:
        raise SystemExit(2)
    return rep


def spot() -> dict:
    from . import spot as sp, spot_ext as sx
    N = set(names())
    kept = [s for s in sx.r68_list()["kept"] if s in N]
    cols = ("close", "quote_volume", "count")
    old = sp.load()
    b = old_rows(old, "symbol", cols)
    del old
    rep = {"pre_names_kept_by_r68": len(kept), "months": [SRC_MONTHS[0], SRC_MONTHS[-1]], "before": b}
    rep["fetch"] = sp.fetch(SRC_START, SRC_END, listed_only=True, only=kept)
    _write("spot", rep)
    rep["ingest"] = sp.ingest(listed_only=True)
    new = sp.load()
    rep["pass"], rep["after_on_the_old_extent"] = same_old(b, new, "symbol", cols)
    rep["after"] = old_rows(new, "symbol", cols)
    early = new[new["ts"] < pd.Timestamp(b["first"])]
    rep["pre_names_with_early_rows"] = int(early["symbol"].nunique())
    _write("spot", rep)
    print(json.dumps(rep, indent=1, default=str), flush=True)
    if not rep["pass"]:
        raise SystemExit(2)
    return rep


def _months_once(raw: Path, ids: list[str], candles, head: dict) -> dict:
    """Per id, per month of SRC_MONTHS: fetch the month's hourly candles and write `<raw>/<id>/<YYYY-MM>.json` — ONLY when the file does
    not exist (a held month is never touched). `candles(id, a, b)` returns the rows with start in [a, b)."""
    today = pd.Timestamp.now("UTC")
    rep = {}
    for i in ids:
        d = raw / i
        d.mkdir(parents=True, exist_ok=True)
        n_new = n_rows = n_kept = 0
        for m in SRC_MONTHS:
            f = d / f"{m}.json"
            if f.exists():
                n_kept += 1
                continue
            m0 = pd.Timestamp(f"{m}-01", tz="UTC")
            m1 = m0 + pd.offsets.MonthBegin(1)
            rows = candles(i, m0, m1)
            f.write_text(json.dumps({**head, "month": m, "fetched": f"{today:%Y-%m-%d %H:%M} UTC", "start": str(m0), "end": str(m1), "rows": rows} | {head["idkey"]: i}))
            n_new += 1
            n_rows += len(rows)
        rep[i] = {"months_fetched": n_new, "months_kept": n_kept, "rows": n_rows}
        print(f"predata {head['idkey']} {i}: {n_new} month files, {n_rows} hourly bars ({n_kept} held)", flush=True)
    return rep


def coinbase() -> dict:
    from . import cb_ext as cx, coinbase as cb
    N = set(names())
    kept = [s for s in cx.r62_list()["kept"] if s in N]
    U = cb.universe("members")
    pid_of = {sym: pid for pid, sym in U["products"].items() if sym}
    pids = [cb.CONTROL] + sorted(pid_of[s] for s in kept if s in pid_of)
    cols = ("close", "volume")
    b = old_rows(cb.load(U["parquet"]), "product", cols)
    rep = {"pre_names_kept_by_r62": len(kept), "products": len(pids), "months": [SRC_MONTHS[0], SRC_MONTHS[-1]], "before": b}
    rep["fetch"] = _months_once(cb.RAW, pids, lambda pid, a, e: cb._candles(pid, a, e, 3600), {"idkey": "product"})
    _write("coinbase", rep)
    cb.ingest(U=U)
    new = cb.load(U["parquet"])
    rep["pass"], rep["after_on_the_old_extent"] = same_old(b, new, "product", cols)
    rep["after"] = old_rows(new, "product", cols)
    rep["products_with_early_rows"] = int(new.loc[new["ts"] < pd.Timestamp(b["first"]), "product"].nunique())
    _write("coinbase", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    if not rep["pass"]:
        raise SystemExit(2)
    return rep


def korea(venue: str = "bithumb") -> dict:
    from . import cb_ext as cx, krw
    N = set(names())
    kept = [s for s in cx.r64_list()["kept"] if s in N]
    U = krw.universe(venue)
    mk_of = {sym: mk for mk, sym in U["markets"].items() if sym}
    mkts = sorted({mk_of[s] for s in [krw.BTC, *kept] if s in mk_of})
    cols = ("close", "volume")
    b = old_rows(krw.load(U["parquet"]), "market", cols)
    rep = {"pre_names_kept_by_r64": len(kept), "markets": len(mkts), "months": [SRC_MONTHS[0], SRC_MONTHS[-1]], "before": b}
    rep["fetch"] = _months_once(U["raw"], mkts, lambda mk, a, e: krw._candles(U, mk, a, e), {"idkey": "market", "venue": venue})
    _write("korea", rep)
    krw.ingest(U)
    new = krw.load(U["parquet"])
    rep["pass"], rep["after_on_the_old_extent"] = same_old(b, new, "market", cols)
    rep["after"] = old_rows(new, "market", cols)
    rep["markets_with_early_rows"] = int(new.loc[new["ts"] < pd.Timestamp(b["first"]), "market"].nunique())
    _write("korea", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    if not rep["pass"]:
        raise SystemExit(2)
    return rep


def main(action: str) -> None:
    {"klines": klines, "spot": spot, "coinbase": coinbase, "korea": korea}[action]()
