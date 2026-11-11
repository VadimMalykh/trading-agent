"""Decision CO1 (2026-11-11): the Data line for F5's members — `ft2 f5data klines|funding|metrics|mix`.

Nothing here reads a label, a forecast or an IC: files are fetched, slices re-ingested, and every row a slice held before is checked
to be back unchanged (a changed old row voids the step, exit 2). The names are the frozen `ft2/screen_members_f5.csv`.

klines    the monthly 5m klines of MONTHS for every F5 name; the archive slice re-ingested whole (held ∪ F5, `krlist.ingest_symbols`);
          R28's extent fingerprint, and for a name it reads as changed (a hole filled inside its old extent) R78's row check.
funding   `fundevent.funding_update` — the names' newer monthly rows appended, every old row identical.
metrics   the daily metrics files METRICS_FROM → F5's end + 1 day; `data.ingest_metrics(held ∪ F5)`; per old name the rows and Σ oi on
          its old extent equal before and after.
mix       `mix.ingest()` — the hourly perpetual trade table rebuilt from the 5m zips now on disk (the 2026 months come in for the names
          `mix.symbols()` already holds); the table cut at its old last hour must carry its old fingerprint.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data, folds, krlist, universe

OUT = Path("output/f5data")
MONTHS = archive.months_between(date(2025, 7, 1), date(2026, 9, 30))       # the market's start (allgbm.F5_START) → the month F5 ends in
METRICS_FROM = date(2025, 12, 1)                                           # the positioning features look back ≤ 9 days before the grid


def names() -> list[str]:
    return universe.screen_symbols(universe.F5_MEMBERS_CSV)


def _write(name: str, rep: dict) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


def _zips(sym: str) -> set[str]:
    return {f.name for f in (data.EXT / "klines" / sym).glob(f"{sym}-5m-*.zip")}


def klines() -> dict:
    N = names()
    OUT.mkdir(parents=True, exist_ok=True)
    fp = krlist.fingerprint()
    fp.to_csv(OUT / "fingerprint_before.csv", index=False)
    before = {s: _zips(s) for s in N}
    rep = {"names": len(N), "months": [MONTHS[0], MONTHS[-1]], "names_fingerprinted": int(len(fp))}
    rep["fetch"] = {s: archive.fetch_monthly("klines", s, sub="5m", months=list(MONTHS)) for s in N}
    rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
    new_files = {s: sorted(_zips(s) - before[s]) for s in N}
    rep["new_files"] = int(sum(len(v) for v in new_files.values()))
    _write("klines", rep)                                                  # before the ingest: a killed ingest leaves the fetch's record
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
    rep["names_without_bars"] = sorted(set(N) - set(g.index))
    g.to_csv(OUT / "klines_extent.csv")
    _write("klines", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    if not rep["pass"]:
        raise SystemExit(2)
    return rep


def funding() -> dict:
    from . import fundevent
    rep = fundevent.funding_update(names(), MONTHS)
    rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
    _write("funding", rep)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("fetch", "appended", "last_per_name_after")}, indent=1, default=str), flush=True)
    return rep


def _metrics_fp(cut: pd.Series | None = None) -> pd.DataFrame:
    d = pd.read_parquet(data.PROC / "metrics.parquet", columns=["symbol", "ts", "oi"])
    d["symbol"] = d["symbol"].astype(str)
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    if cut is not None:
        d = d[d["ts"] <= d["symbol"].map(cut)]
    return d.groupby("symbol").agg(rows=("ts", "size"), first=("ts", "min"), last=("ts", "max"), sum_oi=("oi", "sum")).reset_index()


def metrics() -> dict:
    N = names()
    b = _metrics_fp()
    OUT.mkdir(parents=True, exist_ok=True)
    b.to_csv(OUT / "metrics_before.csv", index=False)
    end = folds.bounds("F5")[1].date()
    rep = {"names": len(N), "from": str(METRICS_FROM), "to": str(end), "names_before": int(len(b)), "rows_before": int(b["rows"].sum())}
    rep["fetch"] = {s: archive.fetch_daily("metrics", s, METRICS_FROM, end) for s in N}
    rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
    _write("metrics", rep)
    rep["ingest"] = {k: str(v) for k, v in data.ingest_metrics(list(dict.fromkeys([*b["symbol"], *N]))).items()}
    a = _metrics_fp(b.set_index("symbol")["last"]).set_index("symbol")
    bad = [r.symbol for r in b.itertuples(index=False)
           if r.symbol not in a.index or int(a.loc[r.symbol, "rows"]) != int(r.rows) or not np.isclose(a.loc[r.symbol, "sum_oi"], r.sum_oi, rtol=1e-12, atol=1e-6)]
    now = _metrics_fp()
    now.to_csv(OUT / "metrics_after.csv", index=False)
    m = now[now["symbol"].isin(N)]
    rep.update({"old_names_changed": bad, "pass": not bad, "names_after": int(len(now)), "rows_after": int(now["rows"].sum()), "f5_names_with_rows": int(len(m)),
                "f5_names_without_rows": sorted(set(N) - set(m["symbol"])), "f5_last_min": str(m["last"].min()), "f5_last_max": str(m["last"].max())})
    _write("metrics", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "fetch"}, indent=1, default=str), flush=True)
    if bad:
        raise SystemExit(2)
    return rep


def mix() -> dict:
    from . import mix as mx
    old = mx.load()
    fp_old = mx.fingerprint(old)
    last = old["ts"].max()
    del old
    rep = {"before": fp_old, "ingest": mx.ingest(verbose=False)}
    new = mx.load()
    rep["after_on_the_old_extent"] = mx.fingerprint(new[new["ts"] <= last])
    rep["after"] = mx.fingerprint(new)
    rep["pass"] = rep["after_on_the_old_extent"] == fp_old
    N = set(names())
    g = new[new["symbol"].astype(str).isin(N)].groupby(new["symbol"].astype(str))["ts"].max()
    rep["f5_names_in_the_table"] = int(len(g))
    rep["f5_names_reaching_f5_end"] = int((g >= folds.bounds("F5")[1] - pd.Timedelta(hours=1)).sum())
    _write("mix", rep)
    print(json.dumps(rep, indent=1, default=str), flush=True)
    if not rep["pass"]:
        raise SystemExit(2)
    return rep


def main(action: str) -> None:
    {"klines": klines, "funding": funding, "metrics": metrics, "mix": mix}[action]()
