"""Decision CW1's count (2026-11-17): the coins the screener did NOT pick, as a second universe — "the next sixty". Per block of the
pre-history, F1+F2, F3+F4 and F5, the screener's unchanged rule (`universe.characteristics`: the USDT perpetuals with a daily bar on
each of the 30 days before the block, the twelve left out, by median daily quote volume) taken to rank 120; ranks 1–60 must BE the
frozen member lists (the validity of the count), ranks 61–120 are the next sixty. Counted: rows and names a segment, the tier's
liquidity against the members', how many of the names were ever a member, and which of them already have 5m candles, positioning
(`metrics`), funding and cost rows on this VM — what a Data line would have to fetch.

Daily bars before each block start only (the screener's own inputs). No 5m bar, no label, no forecast, no price after a block start.

    cd ~/fluxtrader2 && source ~/ft2-venv/bin/activate && PYTHONPATH=. python scripts/cw_count.py
→ output/cw_count/count.md, next60_<segment>.csv (candidates; nothing is frozen by this script)
"""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from ft2 import archive, folds, universe
from ft2.__main__ import PAIRS
from ft2.backtest import REFIT_DAYS, blocks

OUT = Path("output/cw_count")
K = universe.SCREEN_K
SEGMENTS = {"PRE": (None, universe.PRE_MEMBERS_CSV), "F1+F2": (("F1", "F2"), universe.MEMBERS_CSV), "F3+F4": (("F3", "F4"), universe.F34_MEMBERS_CSV),
            "F5": (("F5",), universe.F5_MEMBERS_CSV)}


def starts_of(fold_names):
    if fold_names is None:
        return universe.pre_starts()
    return [a for f in fold_names for a, _ in blocks(f, pd.Timestamp(folds.FOLDS[f][1], tz="UTC"), REFIT_DAYS)]


def symbols_in(slice_: str) -> set[str]:
    p = Path("data") / f"{slice_}.parquet"
    if not p.exists():
        return set()
    f = pq.ParquetFile(p)
    out = set()
    for i in range(f.num_row_groups):
        out |= set(map(str, f.read_row_group(i, columns=["symbol"]).column("symbol").unique().to_pylist()))
    return out


def contract_types() -> dict[str, str]:
    try:
        with urllib.request.urlopen("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=30) as r:
            return {s["symbol"]: s["contractType"] for s in json.loads(r.read())["symbols"]}
    except Exception as e:  # noqa: BLE001
        print(f"exchangeInfo: {e!r}", flush=True)
        return {}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    all_starts = {seg: starts_of(fn) for seg, (fn, _) in SEGMENTS.items()}
    last = max(max(v) for v in all_starts.values())
    months = archive.months_between(universe.SCREEN_FROM, (last - pd.Timedelta(days=1)).date())
    syms = universe.candidates()
    print(f"{len(syms)} USDT perpetuals listed by the archive; 1d klines {months[0]} .. {months[-1]}", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        d = pd.concat(list(ex.map(lambda s: universe._daily_1d(s, months), syms)), ignore_index=True)
    have = {k: symbols_in(k) for k in ("candles_5m_archive", "candles_5m", "metrics", "funding_archive", "cost_daily_wide")}
    have["candles"] = have.pop("candles_5m_archive") | have.pop("candles_5m")
    ever_member = set().union(*(set(pd.read_csv(p)["symbol"]) for _, p in SEGMENTS.values()))
    types = contract_types()
    f5_types = pd.read_csv(universe.F5_TYPES_CSV).set_index("symbol")["contract_type"].to_dict()

    lines = ["# Decision CW1's count — the next sixty (ranks 61–120 by the screener's unchanged rule)\n",
             f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(syms)} candidates · daily bars before each block start only; no 5m bar, no label\n"]
    rows, need = [], {}
    for seg, (fn, csv) in SEGMENTS.items():
        m = universe.characteristics(d, all_starts[seg], set(PAIRS), 2 * K)
        m["rank"] = m.groupby("block")["liq_musd"].rank(ascending=False, method="first").astype(int)
        frozen = pd.read_csv(csv)
        frozen["block"] = pd.to_datetime(frozen["block"], utc=True)
        top = m[m["rank"] <= K]
        same = set(map(tuple, top[["block", "symbol"]].to_numpy())) == set(map(tuple, frozen[["block", "symbol"]].to_numpy()))
        nxt = m[m["rank"] > K].copy()
        nxt["type"] = nxt["symbol"].map(lambda s: f5_types.get(s) or types.get(s) or "UNKNOWN (not listed today)")
        nxt.assign(block=nxt["block"].dt.strftime("%Y-%m-%d")).to_csv(OUT / f"next60_{seg.replace('+', '')}.csv", index=False, float_format="%.6g")
        per = nxt.groupby("block").agg(n=("symbol", "size"), liq_top=("liq_musd", "max"), liq_p50=("liq_musd", "median"), liq_min=("liq_musd", "min"),
                                       vol_p50=("vol_pct", "median"), age_p50=("age_days", "median"))
        mem = top.groupby("block").agg(m_liq_p50=("liq_musd", "median"), m_liq_min=("liq_musd", "min"), m_vol_p50=("vol_pct", "median"), m_age_p50=("age_days", "median"))
        names = sorted(set(nxt["symbol"]))
        coin = nxt[nxt["type"] == "PERPETUAL"] if seg == "F5" else nxt
        need[seg] = {k: sorted(set(names) - v) for k, v in have.items()}
        rows.append({"segment": seg, "blocks": nxt["block"].nunique(), "rows": len(nxt), "full blocks (60)": int((per["n"] == K).sum()), "min rows a block": int(per["n"].min()),
                     "names": len(names), "never a member": len(set(names) - ever_member), "rows of never-members": int((~nxt["symbol"].isin(ever_member)).sum()),
                     "top 60 = the frozen list": "yes" if same else "NO", "liq p50 (M USDT)": round(per["liq_p50"].median(), 1), "members' liq p50": round(mem["m_liq_p50"].median(), 1),
                     "members' liq min": round(mem["m_liq_min"].median(), 1), "liq of rank 120": round(per["liq_min"].median(), 1), "vol p50 %": round(per["vol_p50"].median(), 2),
                     "members' vol p50 %": round(mem["m_vol_p50"].median(), 2), "age p50 d": int(per["age_p50"].median()), "members' age p50 d": int(mem["m_age_p50"].median()),
                     "no candles": len(need[seg]["candles"]), "no metrics": len(need[seg]["metrics"]), "no funding": len(need[seg]["funding_archive"]),
                     "no cost row": len(need[seg]["cost_daily_wide"]), "upper bound of hourly cells": len(nxt) * REFIT_DAYS * 24,
                     **({"coin rows (PERPETUAL)": len(coin), "TRADIFI rows": int((nxt["type"] == "TRADIFI_PERPETUAL").sum()), "type unknown rows": int(nxt["type"].str.startswith("UNKNOWN").sum())}
                        if seg == "F5" else {})})
        lines += [f"\n## {seg} — per block\n", per.join(mem).round(2).reset_index().assign(block=lambda x: x["block"].dt.date).to_markdown(index=False), "\n"]
    T = pd.DataFrame(rows).set_index("segment").T
    lines[2:2] = ["\n## The segments\n", T.to_markdown(), "\n"]
    alln = sorted(set().union(*(set(pd.read_csv(OUT / f"next60_{s.replace('+', '')}.csv")["symbol"]) for s in SEGMENTS)))
    lines += ["\n## What a Data line would fetch\n", f"{len(alln)} distinct names over the four segments; without 5m candles on this VM: "
              f"{len(set(alln) - have['candles'])}; without metrics: {len(set(alln) - have['metrics'])}; without funding rows: {len(set(alln) - have['funding_archive'])}; "
              f"without a cost row: {len(set(alln) - have['cost_daily_wide'])}.\n"]
    (OUT / "count.md").write_text("\n".join(lines))
    (OUT / "need.json").write_text(json.dumps(need, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
