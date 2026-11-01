"""R73's table (P8 decision BR1, 2026-11-01, docs/PLAN.md §8 R73 Data line) — the PERPETUAL's hourly participant mix per member:
`data/perp_mix_1h.parquet`: `(symbol, ts, ts_known) → close, volume, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, bars`,
summed from the archive's monthly 5m kline zips already on the work VM (`data/raw/external/binance/klines/<SYM>/<SYM>-5m-YYYY-MM.zip`,
§9 #2's fetch for R23 / R25 — the F1+F2 members through 2024-08, the F3+F4 members through 2025-12; nothing is fetched here). `count` is
the archive's column 9 (the bar's number of trades) and `quote_volume` its column 8 — neither was ingested into `candles_5m_archive`
(OHLCV only). `ts` = the hour's start, `ts_known` = `ts` + 1 h (the hour's last 5m bar closes at the hour; the spot table's rule), `bars`
= the number of 5m bars summed (12 when the hour is whole). One symbol at a time (R23: the slices as strings did not fit 16 GB).

`ft2 mix ingest` builds the table; `ft2 mix audit` writes `output/perp_mix_audit.md` / `.json`: the FINGERPRINT (rows, symbols, first /
last, Σ count, Σ quote_volume — R73's validity (1) compares the run's table against DATA.md), per symbol the hours and the share with fewer
than 12 bars, the aggregation check (the hour's `quote_volume` against Σ volume × close of the same hour from `candles_5m_archive` — the
same zips, so the ratio sits near 1; an hour off by one would not), the members' cover per block, the overlap with the spot table on
R68's kept names and the spot share of the count. Nothing is priced; no count is joined to a label.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import coinbase as cb, data, folds, spot

RAW_KL = data.EXT / "klines"
PARQUET = data.PROC / "perp_mix_1h.parquet"
OUT = Path("output/perp_mix_audit.md")
INTERVAL = "5m"
HOUR = pd.Timedelta("1h")
BAR = pd.Timedelta("5min")
COLS = ["symbol", "ts", "ts_known", "close", "volume", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "bars"]
SLICES = ("candles_5m_archive", "candles_5m")
R68_CSV = Path(__file__).with_name("spot_members_r68.csv")
AGG_TOL = 0.05               # the aggregation check: the share of hours whose quote_volume / Σ volume × close is more than this off 1
KLINE_COLS = data.KLINE_COLS


def symbols(raw: Path | None = None) -> list[str]:
    """Every symbol of the two member files that has 5m zips under `raw`, sorted."""
    raw = RAW_KL if raw is None else raw
    out = []
    for s in sorted(set(cb.member_symbols()["symbol"])):
        if any((raw / s).glob(f"{s}-{INTERVAL}-*.zip")):
            out.append(s)
    return out


def read_symbol(sym: str, raw: Path | None = None) -> pd.DataFrame:
    """One symbol's 5m zips (with `.zip.ok` beside) → its hourly rows."""
    raw = RAW_KL if raw is None else raw
    files = [f for f in sorted((raw / sym).glob(f"{sym}-{INTERVAL}-*.zip")) if f.with_suffix(".zip.ok").exists()]
    parts = []
    for f in files:
        with zipfile.ZipFile(f) as z:
            for n in z.namelist():
                parts.append(pd.read_csv(z.open(n), header=None, names=KLINE_COLS, dtype=str))
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts, ignore_index=True)
    df = df[df["open_time"].str.isdigit()]
    ot = spot._stamp(df["open_time"])
    b = pd.DataFrame({"open_time": ot})
    for c in ("close", "volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"):
        b[c] = df[c].astype(float).to_numpy()
    b["count"] = df["count"].astype("int64").to_numpy()
    b = b.sort_values("open_time", kind="mergesort").drop_duplicates("open_time", keep="last")
    b["hour_end"] = (b["open_time"] + BAR).dt.ceil("h")
    g = b.groupby("hour_end")
    out = pd.DataFrame({"close": g["close"].last(), "volume": g["volume"].sum(), "quote_volume": g["quote_volume"].sum(), "count": g["count"].sum(),
                        "taker_buy_volume": g["taker_buy_volume"].sum(), "taker_buy_quote_volume": g["taker_buy_quote_volume"].sum(), "bars": g["count"].size()})
    out.index.name = "ts_known"
    out = out.reset_index()
    out.insert(0, "ts", out["ts_known"] - HOUR)
    out.insert(0, "symbol", sym)
    out["count"] = out["count"].astype("int64")
    out["bars"] = out["bars"].astype("int64")
    return out[COLS].reset_index(drop=True)


def ingest(only: list[str] | None = None, path: Path | None = None, raw: Path | None = None, verbose: bool = True) -> dict:
    path, raw = (PARQUET if path is None else Path(path)), (RAW_KL if raw is None else raw)
    syms = [s for s in symbols(raw) if not only or s in only]
    parts = []
    for i, s in enumerate(syms):
        r = read_symbol(s, raw)
        if len(r):
            parts.append(r)
        if verbose:
            print(f"{i + 1:>4}/{len(syms)} {s:<16} {len(r):>7} hours", flush=True)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=COLS)
    df["symbol"] = df["symbol"].astype("category")
    df = df.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return {"symbols_asked": len(syms), "file": str(path)} | fingerprint(df)


def fingerprint(d: pd.DataFrame) -> dict:
    """R73's validity (1): rows, symbols, first / last hour, Σ count, Σ quote_volume (as integers / rounded floats)."""
    return {"rows": int(len(d)), "symbols": int(d["symbol"].nunique()) if len(d) else 0, "first": str(d["ts"].min()) if len(d) else None,
            "last": str(d["ts"].max()) if len(d) else None, "count_sum": int(d["count"].sum()) if len(d) else 0,
            "quote_volume_sum": float(round(float(d["quote_volume"].sum()), 2)) if len(d) else 0.0}


def load(path: Path | str | None = None) -> pd.DataFrame:
    d = pd.read_parquet(PARQUET if path is None else path)
    d["symbol"] = d["symbol"].astype(str)
    return d


def agg_check(d: pd.DataFrame, names: list[str], slices: tuple[str, ...] = SLICES) -> pd.DataFrame:
    """Per name: the hour's quote_volume over Σ volume × close of the same hour from the candle slices (the later slice winning) — the median
    ratio and the share of hours more than AGG_TOL off 1. The same zips feed both, so a ratio near 1 says the hours line up."""
    parts = []
    for sl in slices:
        if (data.PROC / f"{sl}.parquet").exists() or (data.PROC / sl).is_dir():
            try:
                parts.append(data.load(sl, columns=["symbol", "open_time", "close", "volume"], symbols=names))
            except (ValueError, FileNotFoundError):
                pass
    if not parts:
        return pd.DataFrame(columns=["symbol", "hours_compared", "ratio_median", f"share_off_{AGG_TOL:g}"])
    c = pd.concat(parts, ignore_index=True)
    c["symbol"] = c["symbol"].astype(str)
    c = c.drop_duplicates(["symbol", "open_time"], keep="last")
    ot = pd.DatetimeIndex(c["open_time"])
    c["ts_known"] = (ot.tz_localize("UTC") if ot.tz is None else ot.tz_convert("UTC")) + BAR
    c["ts_known"] = c["ts_known"].dt.ceil("h")
    c["dv"] = c["volume"] * c["close"]
    pv = c.groupby(["symbol", "ts_known"])["dv"].sum(min_count=1).rename("dv").reset_index()
    m = d[d["symbol"].isin(names)][["symbol", "ts_known", "quote_volume"]].merge(pv, on=["symbol", "ts_known"], how="inner")
    m = m[(m["dv"] > 0) & (m["quote_volume"] > 0)]
    m["ratio"] = m["quote_volume"] / m["dv"]
    rows = []
    for s, g in m.groupby("symbol"):
        rows.append({"symbol": s, "hours_compared": int(len(g)), "ratio_median": float(g["ratio"].median()), f"share_off_{AGG_TOL:g}": float(((g["ratio"] - 1).abs() > AGG_TOL).mean())})
    return pd.DataFrame(rows)


def audit(path: Path | None = None, out: Path | None = None, slices: tuple[str, ...] = SLICES, spot_path: Path | str | None = None, r68_csv: Path | None = None,
          today: pd.Timestamp | None = None) -> str:
    path, out, r68_csv = (PARQUET if path is None else Path(path)), (OUT if out is None else Path(out)), (R68_CSV if r68_csv is None else Path(r68_csv))
    today = today or pd.Timestamp.now("UTC")
    d = load(path)
    fp = fingerprint(d)
    per = []
    for s, g in d.groupby("symbol"):
        per.append({"symbol": s, "hours": int(len(g)), "first": str(g["ts"].min()), "last": str(g["ts"].max()), "share_bars_lt_12": float((g["bars"] < 12).mean()),
                    "count_per_hour_median": float(g["count"].median()), "size_usdt_median": float((g["quote_volume"] / g["count"].where(g["count"] > 0)).median()),
                    "share_zero_count": float((g["count"] == 0).mean())})
    per = pd.DataFrame(per)
    mcov, blocks = cb.member_cover(d.assign(product=d["symbol"]))
    kept = []
    if Path(r68_csv).exists():
        L = pd.read_csv(r68_csv)
        kept = sorted(L.loc[L["r68"].astype(bool), "symbol"].astype(str))
    names_chk = [s for s in kept if s in set(d["symbol"])] or sorted(set(d["symbol"]))
    agg = agg_check(d, names_chk, slices)
    # the overlap with the spot table on the kept names: hours with both bars, and the spot share of the count
    overlap = pd.DataFrame(columns=["symbol", "perp_hours", "both_hours", "spot_share_of_count_median"])
    sp_path = Path(spot_path) if spot_path else spot.PARQUET
    if sp_path.exists() and kept:
        sdf = pd.read_parquet(sp_path, columns=["symbol", "ts_known", "count"])
        sdf["symbol"] = sdf["symbol"].astype(str)
        sdf = sdf[sdf["symbol"].isin(kept)].rename(columns={"count": "spot_count"})
        j = d[d["symbol"].isin(kept)][["symbol", "ts_known", "count"]].merge(sdf, on=["symbol", "ts_known"], how="left")
        rows = []
        for s, g in j.groupby("symbol"):
            both = g["spot_count"].notna()
            tot = (g["count"] + g["spot_count"])[both]
            rows.append({"symbol": s, "perp_hours": int(len(g)), "both_hours": int(both.sum()),
                         "spot_share_of_count_median": float((g.loc[both, "spot_count"] / tot.where(tot > 0)).median()) if both.any() else np.nan})
        overlap = pd.DataFrame(rows)
    L_ = [f"# The perpetual's hourly participant mix per member — the table's audit (R73's Data line; `ft2 mix audit`)\n",
          f"generated {today:%Y-%m-%d %H:%M} UTC · {path} · summed from the archive's monthly 5m kline zips under {RAW_KL} (`count` = the bar's trades, `quote_volume` in USDT)\n",
          "\nWords: an hour's row holds the sums of the 5m bars whose END lies in (H, H + 1 h]; `ts` = H, `ts_known` = H + 1 h; `bars` = the number summed (12 when whole). "
          "Nothing is priced here; no count is joined to a label; no fold is read.\n",
          "\n## Fingerprint — R73's validity (1) compares the run's table against these numbers\n", "```\n", json.dumps(fp, indent=1), "\n```\n",
          "\n## Per symbol\n", per.round(4).to_markdown(index=False), "\n",
          f"\n- {len(per)} symbols; hours with fewer than 12 bars: median share {per['share_bars_lt_12'].median():.4f}, max {per['share_bars_lt_12'].max():.4f}; "
          f"zero-count hours: median share {per['share_zero_count'].median():.4f}, max {per['share_zero_count'].max():.4f}.\n",
          f"\n## The aggregation check — the hour's `quote_volume` over Σ volume × close of the same hour from `{slices[0]}` ({len(names_chk)} names)\n",
          agg.round(4).to_markdown(index=False) if len(agg) else "(no overlap)", "\n",
          (f"\n- Pooled: the median ratio across names {agg['ratio_median'].median():.4f} (min {agg['ratio_median'].min():.4f}, max {agg['ratio_median'].max():.4f}); the share of hours more than "
           f"{AGG_TOL:g} off 1: median {agg[f'share_off_{AGG_TOL:g}'].median():.4f}, max {agg[f'share_off_{AGG_TOL:g}'].max():.4f}. The same zips feed both tables: a ratio near 1 says the hours line up "
           "(within-bar price drift is the only difference).\n") if len(agg) else "",
          "\n## The members' cover of their own hours, per block\n", blocks.to_markdown(index=False) if len(blocks) else "(no member bars)", "\n",
          f"\n## The overlap with the spot table on R68's kept names ({len(kept)} kept) — hours with both bars, the spot share of the hour's count\n",
          overlap.round(4).to_markdown(index=False) if len(overlap) else "(no spot table or no kept names)", "\n",
          (f"\n- Pooled: both bars on a median {(overlap['both_hours'] / overlap['perp_hours']).median():.4f} of the kept names' perp hours; the spot share of the count median across names "
           f"{overlap['spot_share_of_count_median'].median():.3f} (p10 {overlap['spot_share_of_count_median'].quantile(0.1):.3f}, p90 {overlap['spot_share_of_count_median'].quantile(0.9):.3f}).\n") if len(overlap) else ""]
    row = (f"| **perp_mix_1h** (the perpetual's hourly trade count, quote volume and taker-buy quote volume per member, summed from the archive's 5m zips in hand; R73's Data line, 2026-11-01) | "
           f"`ft2 mix ingest` on the work VM; raw `data/raw/external/binance/klines/<SYM>/` (§9 #2) | {fp['symbols']} symbols, {fp['first'][:10]} → {fp['last'][:10]} | {fp['rows']:,} rows; "
           f"Σ count {fp['count_sum']:,}; Σ quote_volume {fp['quote_volume_sum']:,.2f} | the fingerprint above; per block "
           + "; ".join(f"{b['block']} {b[f'cover_ge_{cb.COVER_OK:g}']} of {b['members']}" for _, b in blocks.iterrows())
           + f" | `{path}`; a bar is read at `ts_known` = its start + 1 h |")
    L_ += ["\n## DATA.md row\n", "\n" + row + "\n"]
    txt = "".join(x if x.endswith("\n") else x + "\n" for x in L_)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt)
    (out.parent / "perp_mix_audit.json").write_text(json.dumps({"fingerprint": fp, "per_symbol": per.to_dict("records"), "agg_check": agg.to_dict("records"),
                                                               "blocks": blocks.to_dict("records"), "member_cover": mcov.to_dict("records") if len(mcov) else [],
                                                               "overlap": overlap.to_dict("records"), "kept_r68": len(kept)}, indent=1, default=str))
    return txt


def main(action: str, only: list[str] | None = None) -> None:
    if action == "ingest":
        print(json.dumps(ingest(only), indent=1))
    elif action == "audit":
        print(audit())
    elif action == "fingerprint":
        print(json.dumps(fingerprint(load()), indent=1))
    else:
        sys.exit(f"mix: unknown action {action}")
