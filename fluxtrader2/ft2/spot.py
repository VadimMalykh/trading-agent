"""P8 (decision BH1, 2026-10-22) — Binance's own SPOT market per member as a data source: `ft2 spot symbols|fetch|ingest|audit`.

source     the public archive (`data.binance.vision`, free, keyless): `data/spot/monthly/klines/<SYMBOL>/1h/<SYMBOL>-1h-YYYY-MM.zip`, one
           file a month, no header row, the twelve kline columns (open_time, open, high, low, close, volume, close_time, quote_volume,
           count, taker_buy_volume, taker_buy_quote_volume, ignore). The stamps are MILLISECONDS through 2024 and MICROSECONDS from
           2025-01 (16 digits; read by magnitude). A monthly file holds closed bars only. CHECKSUM verified by `ft2/archive.py`.
symbols    `<BASE>USDT` for every base of the twelve and of the screener's members (`ft2/screen_members.csv`, `screen_members_f34.csv`;
           a 1000× / 1M× contract's base with the prefix stripped, as `coinbase.base`), else the contract's own symbol where the spot
           market lists it as such (1000SATSUSDT); the listing is the archive's prefixes under `data/spot/monthly/klines/`, saved once.
raw        data/raw/external/binance_spot/klines/<SYMBOL>/<SYMBOL>-1h-YYYY-MM.zip (+ .ok), data/raw/external/binance_spot/symbols_<YYYYMMDD>.json.
parquet    data/spot_1h.parquet: (spot_symbol, symbol, ts, ts_known, open, high, low, close, volume, quote_volume, count, taker_buy_volume,
           taker_buy_quote_volume) — `ts` the bar's start, `ts_known` = ts + 1 h the only stamp a feature may read the bar at.
audit      output/spot_audit.md (+ .json, spot_ratios.parquet, a DATA.md row): per symbol the first bar, the extent, completeness, gaps,
           F1–F5 cover, the member-hours cover and the per-block breadth (R62's frame); the stamp check (the spot close against the
           perpetual's 5m close ending at the same stamp — a basis of a few bps when the stamps agree, not one of an hour's move); the two
           FLOW ratios per name — the taker-buy share of the spot quote volume (unlevered buying against selling) and the log of the spot
           quote volume over the perpetual's in the same hour (unlevered against levered participation) — each its level, within-name sd,
           persistence, hour-of-day shape, and its deviation from the trailing month in sd units (cb_ext's DEV form) with that deviation's
           correlation with `cbprem_dev` on the same hours (the question BG3 asked: does either vary within a name, and is it the Coinbase
           deviation again?); the cross-name correlation of each deviation. Nothing priced, no fold read, nothing registered.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive
from . import coinbase as cb
from . import data, folds

RAW = data.RAW / "external" / "binance_spot"
PARQUET = data.PROC / "spot_1h.parquet"
OUT = Path("output/spot_audit.md")
PREFIX = "data/spot/monthly/klines/"
INTERVAL = "1h"
HOUR = pd.Timedelta("1h")
START = "2023-04-01"         # a month before F1
AUDIT_START = "2023-05-01"   # F1's first day: completeness is counted from here
MONTH = 30 * 24              # cb_ext's trailing month, in hourly bars
MIN_MONTH = MONTH // 2
COVER_OK = cb.COVER_OK
SLICES = ("candles_5m_archive", "candles_5m")
PREMIUM = Path("output/coinbase_members_premium.parquet")       # AX1's audit: prem_adj_bps per (symbol, ts_known) on the members
KEPT = Path(__file__).with_name("cb_members_r62.csv")            # R62's kept names (r62 True)
BASIS_BIG = 50.0             # bps: the share of hours whose |spot − perp| exceeds this (a stamp off by an hour would put most hours here)
MIN_CORR_HOURS = 100
CORR_SAME = 0.5              # BG3: a ratio is "cbprem_dev again" when |corr| ≥ this
TWELVE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "1000PEPEUSDT", "WLDUSDT", "ZECUSDT", "HYPEUSDT"]
KLINE_COLS = data.KLINE_COLS
COLS = ["spot_symbol", "symbol", "ts", "ts_known", "open", "high", "low", "close", "volume", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume"]


def perp_symbols() -> list[str]:
    """The twelve first, then every member symbol of the two member files, each once."""
    out = list(TWELVE)
    for s in sorted(set(cb.member_symbols()["symbol"])):
        if s not in out:
            out.append(s)
    return out


def candidates(sym: str) -> list[str]:
    """The spot symbols a perpetual may trade under, in order: the base's USDT pair, then the contract's own symbol."""
    c = [f"{cb.base(sym)}USDT"]
    return c if sym in c else c + [sym]


def listing() -> list[str]:
    return archive.list_prefixes(PREFIX)


def symbols_file() -> pd.DataFrame | None:
    files = sorted(RAW.glob("symbols_*.json"))
    return pd.DataFrame(json.load(open(files[-1]))["rows"]) if files else None


def symbols(today: pd.Timestamp | None = None, listed: list[str] | None = None) -> pd.DataFrame:
    """One row a perpetual: its spot symbol (the first candidate the archive lists, else None) — saved under RAW."""
    today = today or pd.Timestamp.now("UTC")
    have = set(listing() if listed is None else listed)
    rows = []
    for sym in perp_symbols():
        hit = next((c for c in candidates(sym) if c in have), None)
        rows.append({"symbol": sym, "spot_symbol": hit, "listed": hit is not None, "mult": cb.mult_of(sym)})
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"symbols_{today:%Y%m%d}.json").write_text(json.dumps({"archive_symbols": len(have), "rows": rows}, indent=1))
    return pd.DataFrame(rows)


def universe(listed_only: bool = False, only: list[str] | None = None) -> dict[str, str]:
    """spot symbol → perpetual symbol; from the saved listing when `listed_only`, else every first candidate."""
    sf = symbols_file()
    if listed_only:
        if sf is None:
            raise SystemExit("spot: no saved listing — run `ft2 spot symbols` first")
        mp: dict[str, str] = {}
        for _, r in sf.iterrows():
            if r["listed"]:
                mp.setdefault(r["spot_symbol"], r["symbol"])         # two contracts on one base: the first (the twelve's) keeps the spot symbol
    else:
        mp = {}
        for s in perp_symbols():
            mp.setdefault(candidates(s)[0], s)
    if only:
        mp = {k: v for k, v in mp.items() if v in only or k in only}
    return mp


def fetch(start: str = START, end: str | None = None, listed_only: bool = False, only: list[str] | None = None) -> dict:
    """Every month file of [start, end] for every spot symbol of the universe (end: F5's last month when None); resumable."""
    s = pd.Timestamp(start).date()
    e = pd.Timestamp(end).date() if end else folds.bounds("F5")[1].date()
    months = archive.months_between(s, e)
    mp = universe(listed_only, only)
    tot = {"symbols": len(mp), "ok": 0, "skip": 0, "bad": 0, "err": 0, "missing": 0}
    for i, (sp, sym) in enumerate(mp.items()):
        c = archive.fetch_monthly("klines", sp, sub=INTERVAL, months=months, market="spot", root=RAW)
        for k in ("ok", "skip", "bad", "err", "missing"):
            tot[k] += c.get(k, 0)
        print(f"{i + 1:>4}/{len(mp)} {sp:<14} {sym:<14} {c}", flush=True)
    if tot["err"] or tot["bad"]:
        print(f"spot fetch done with {tot['err'] + tot['bad']} errors — re-run the same command to pick them up", file=sys.stderr)
    return tot


def _stamp(x: pd.Series) -> pd.DatetimeIndex:
    """ms through 2024, µs from 2025-01 (the archive's change): read by magnitude, per row."""
    v = x.astype("int64").to_numpy()
    us = v >= 10**14
    out = np.where(us, v, v * 1000).astype("datetime64[us]")
    return pd.DatetimeIndex(out).tz_localize("UTC")


def read_symbol(sp: str, sym: str, raw: Path = RAW) -> pd.DataFrame:
    files = [f for f in sorted((raw / "klines" / sp).glob(f"{sp}-{INTERVAL}-*.zip")) if f.with_suffix(".zip.ok").exists()]
    parts = []
    for f in files:
        with zipfile.ZipFile(f) as z:
            for n in z.namelist():
                parts.append(pd.read_csv(z.open(n), header=None, names=KLINE_COLS, dtype=str))
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts, ignore_index=True)
    df = df[df["open_time"].str.isdigit()]
    ts = _stamp(df["open_time"])
    out = pd.DataFrame({"spot_symbol": sp, "symbol": sym, "ts": ts, "ts_known": ts + HOUR})
    for c in ("open", "high", "low", "close", "volume", "quote_volume", "taker_buy_volume", "taker_buy_quote_volume"):
        out[c] = df[c].astype(float).to_numpy()
    out["count"] = df["count"].astype("int64").to_numpy()
    return out[COLS].sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)


def ingest(listed_only: bool = True, only: list[str] | None = None, path: Path = PARQUET) -> dict:
    mp = universe(listed_only, only)
    parts = [read_symbol(sp, sym) for sp, sym in mp.items()]
    df = pd.concat([p for p in parts if len(p)], ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame(columns=COLS)
    for c in ("spot_symbol", "symbol"):
        df[c] = df[c].astype("category")
    df = df.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return {"symbols_asked": len(mp), "symbols_with_bars": int(df["spot_symbol"].nunique()), "rows": len(df),
            "first": str(df["ts"].min()) if len(df) else None, "last": str(df["ts"].max()) if len(df) else None, "file": str(path)}


def load(path: Path | str = PARQUET) -> pd.DataFrame:
    d = pd.read_parquet(path)
    for c in ("spot_symbol", "symbol"):
        d[c] = d[c].astype(str)
    return d


# ---- the ratios --------------------------------------------------------------------------------------------------------------------
def dev(X: pd.DataFrame) -> pd.DataFrame:
    """cb_ext's DEV form on an hourly grid: the deviation from the trailing month over the trailing sd, ≥ MIN_MONTH bars present."""
    m = X.rolling(MONTH, min_periods=MIN_MONTH).mean()
    sd = X.rolling(MONTH, min_periods=MIN_MONTH).std()
    return (X - m) / sd


def _acf(x: pd.Series, lag: int) -> float:
    return cb._acf(x, lag)


def grids(d: pd.DataFrame, a0: pd.Timestamp, end: pd.Timestamp, slices: tuple[str, ...] = SLICES, mult: dict[str, float] | None = None) -> dict[str, pd.DataFrame]:
    """On the hourly grid (ts_known × perp symbol), inside (a0, end]: the taker-buy share `tb`, the log spot/perp quote-volume ratio `sr`,
    the spot close over the perpetual's 5m close ending at the stamp minus one in bps `basis`, their deviations `tb_dev` / `sr_dev`."""
    d = d[(d["ts_known"] > a0) & (d["ts_known"] <= end)]
    grid = pd.date_range(a0.ceil("h") + HOUR, end.floor("h"), freq="h")
    W = lambda col: d.pivot_table(index="ts_known", columns="symbol", values=col, aggfunc="last").reindex(grid)
    qv, tbq, close = W("quote_volume"), W("taker_buy_quote_volume"), W("close")
    syms = list(qv.columns)
    tb = (tbq / qv.where(qv > 0))
    pv = cb.binance_dvol_hour(syms, grid, slices).reindex(columns=syms)
    sr = np.log((qv / pv.where(pv > 0)).where(lambda x: x > 0))
    bn = cb.binance_close_at(syms, grid, slices).reindex(columns=syms)
    mult = mult or {s: cb.mult_of(s) for s in syms}
    basis = (close / (bn / pd.Series(mult).reindex(syms)) - 1.0) * 1e4
    return {"tb": tb, "sr": sr, "basis": basis, "tb_dev": dev(tb), "sr_dev": dev(sr), "qv": qv, "pv": pv}


def cb_dev(path: Path = PREMIUM, grid: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """`cbprem_dev` on the hourly grid from AX1's premium parquet (prem_adj_bps per symbol × ts_known), cb_ext's DEV form; empty when absent."""
    if not Path(path).exists():
        return pd.DataFrame(index=grid)
    P = pd.read_parquet(path, columns=["symbol", "ts_known", "prem_adj_bps"])
    G = P.pivot_table(index="ts_known", columns="symbol", values="prem_adj_bps", aggfunc="last")
    full = pd.date_range(G.index.min().floor("h"), G.index.max().floor("h"), freq="h")
    D = dev(G.reindex(full))
    return D.reindex(grid) if grid is not None else D


def kept_names(path: Path = KEPT) -> set[str]:
    if not Path(path).exists():
        return set()
    k = pd.read_csv(path)
    return set(k.loc[k["r62"].astype(bool), "symbol"].astype(str))


def stats(G: dict[str, pd.DataFrame], CB: pd.DataFrame, kept: set[str]) -> pd.DataFrame:
    """Per name and ratio: the level's hours / mean / median / sd / p10 / p90 / acf at 1 h and 24 h; the deviation's sd and acf; the
    deviation's correlation with cbprem_dev on the hours both exist (≥ MIN_CORR_HOURS), and the two deviations' correlation."""
    rows = []
    for tag, lvl, dv in (("taker_buy_share", G["tb"], G["tb_dev"]), ("spot_over_perp_log", G["sr"], G["sr_dev"])):
        other = G["sr_dev"] if tag == "taker_buy_share" else G["tb_dev"]
        for sym in lvl.columns:
            x, z = lvl[sym], dv[sym]
            if not x.notna().any():
                continue
            c = CB[sym] if sym in CB.columns else pd.Series(np.nan, index=z.index)
            ok = z.notna() & c.notna()
            ok2 = z.notna() & other[sym].notna()
            rows.append({"symbol": sym, "ratio": tag, "kept_r62": sym in kept, "hours": int(x.notna().sum()), "mean": x.mean(), "median": x.median(), "sd": x.std(),
                         "p10": x.quantile(0.1), "p90": x.quantile(0.9), "acf_1h": _acf(x, 1), "acf_24h": _acf(x, 24),
                         "dev_hours": int(z.notna().sum()), "dev_sd": z.std(), "dev_acf_1h": _acf(z, 1), "dev_acf_24h": _acf(z, 24),
                         "corr_dev_cbdev": float(z[ok].corr(c[ok])) if ok.sum() >= MIN_CORR_HOURS else np.nan, "hours_with_cbdev": int(ok.sum()),
                         "corr_dev_other": float(z[ok2].corr(other[sym][ok2])) if ok2.sum() >= MIN_CORR_HOURS else np.nan})
    return pd.DataFrame(rows)


def basis_check(B: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym in B.columns:
        x = B[sym].dropna()
        if len(x) == 0:
            continue
        rows.append({"symbol": sym, "hours": int(len(x)), "basis_median_bps": x.median(), "basis_p10": x.quantile(0.1), "basis_p90": x.quantile(0.9),
                     "abs_median_bps": x.abs().median(), f"share_abs_gt_{BASIS_BIG:g}": float((x.abs() > BASIS_BIG).mean())})
    return pd.DataFrame(rows)


def _off_diag(W: pd.DataFrame) -> pd.Series:
    C = W.corr(min_periods=MIN_CORR_HOURS)
    return C.where(~np.eye(len(C), dtype=bool)).stack() if len(C) else pd.Series(dtype=float)


def audit(today: pd.Timestamp | None = None, path: Path = PARQUET, out: Path = OUT, slices: tuple[str, ...] = SLICES, premium: Path = PREMIUM,
          kept_csv: Path = KEPT, symbols_df: pd.DataFrame | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    d = load(path)
    a0 = pd.Timestamp(AUDIT_START, tz="UTC")
    end = min(d["ts_known"].max(), folds.bounds("F5")[1]) if len(d) else today
    expected = pd.date_range(a0, end, freq="h", inclusive="left")
    sf = symbols_df if symbols_df is not None else symbols_file()
    sf = sf if sf is not None else pd.DataFrame(columns=["symbol", "spot_symbol", "listed"])
    rows = []
    for _, r0 in sf.iterrows():
        sym, sp = r0["symbol"], r0["spot_symbol"]
        g = d[d["symbol"] == sym]
        r = {"symbol": sym, "spot_symbol": sp, "listed": bool(r0["listed"]), "hourly_first": str(g["ts"].min()) if len(g) else None,
             "hourly_last": str(g["ts"].max()) if len(g) else None, "hours": int(len(g))}
        if len(g):
            have = pd.DatetimeIndex(g["ts"])
            inside = have[(have >= a0) & (have < end)]
            r["completeness"] = float(len(inside) / max(len(expected), 1))
            dd = pd.Series(have.sort_values()).diff().dropna().dt.total_seconds().to_numpy() / 3600.0      # the parquet's unit is µs, not ns
            r["gaps_over_1h"] = int((dd > 1.0001).sum())
            r["largest_gap_h"] = float(dd.max()) if len(dd) else 0.0
            r["share_zero_volume"] = float((g["quote_volume"] <= 0).mean())
            for f in ("F1", "F2", "F3", "F4", "F5"):
                fa, fb = folds.bounds(f)
                sh = pd.date_range(fa.ceil("h"), min(fb, end), freq="h", inclusive="left")
                r[f"cover_{f}"] = float(sh.isin(have).mean()) if len(sh) else np.nan
        rows.append(r)
    cov = pd.DataFrame(rows)
    mcov, blocks = cb.member_cover(d.rename(columns={"spot_symbol": "product"}))
    if len(mcov):
        cov = cov.merge(mcov, on="symbol", how="left")
    G = grids(d, a0, end, slices)
    CB = cb_dev(premium, G["tb"].index)
    kept = kept_names(kept_csv)
    st = stats(G, CB, kept)
    bc = basis_check(G["basis"])
    off = {k: _off_diag(G[k]) for k in ("tb_dev", "sr_dev")}
    hod = {k: G[k].groupby(G[k].index.hour).mean().mean(axis=1) for k in ("tb", "sr")}
    # the pooled shares: the taker-buy share's hour mean across names, the spot volume's share of spot + perp per name (median)
    pooled_tb = G["tb"].mean(axis=1)
    spot_share = (G["qv"] / (G["qv"] + G["pv"])).median()
    kept_st = st[st["kept_r62"]]
    summary = {}
    for tag, g in kept_st.groupby("ratio"):
        c = g["corr_dev_cbdev"].dropna()
        summary[tag] = {"names": int(len(g)), "with_corr": int(len(c)), "corr_median": float(c.median()) if len(c) else None,
                        "corr_p10": float(c.quantile(0.1)) if len(c) else None, "corr_p90": float(c.quantile(0.9)) if len(c) else None,
                        f"share_abs_corr_ge_{CORR_SAME:g}": float((c.abs() >= CORR_SAME).mean()) if len(c) else None,
                        "dev_sd_median": float(g["dev_sd"].median()), "level_sd_median": float(g["sd"].median()), "acf_1h_median": float(g["acf_1h"].median()),
                        "acf_24h_median": float(g["acf_24h"].median()), "dev_acf_24h_median": float(g["dev_acf_24h"].median()),
                        "corr_other_median": float(g["corr_dev_other"].median()) if g["corr_dev_other"].notna().any() else None}
    listed = cov[cov["listed"] == True]  # noqa: E712
    with_bars = cov[cov["hours"] > 0]
    L = [f"# Binance's own spot market per member — source audit (decision BH1; `ft2 spot audit`)\n",
         f"generated {today:%Y-%m-%d %H:%M} UTC · {path} · counted over {a0.date()} → {end.date()} at each hour's END (the bar's start + 1 h)\n",
         "\nWords: a spot bar starting at H is read at `ts_known` = H + 1 h and nothing earlier. The *taker-buy share* is the bar's taker-buy quote volume over its "
         "quote volume (the share of the hour's spot turnover that was aggressive buying; 0.5 is balance). The *spot/perp ratio* is the log of the spot quote "
         "volume over the perpetual's quote volume of the same hour (Σ volume × close over the twelve 5m bars ending in the hour; the contract multiple cancels). "
         "Each *deviation* is cb_ext's DEV form — the ratio minus its trailing 30-day mean, over the trailing 30-day sd, ≥ 360 bars present. `cbprem_dev` is "
         f"the same form on AX1's adjusted Coinbase premium (`{premium}`); the kept names are R62's (`{kept_csv.name}`). Nothing is priced here; no fold is read.\n",
         "\n## Symbols, extent, completeness, cover (hours)\n", cov.round(4).to_markdown(index=False), "\n",
         f"\n- {len(listed)} of {len(sf)} perpetuals have a spot symbol in the archive, {len(with_bars)} with hourly bars in the window.\n",
         "\n## The stamp check — the spot close against the perpetual's 5m close ending at the same stamp (bps)\n", bc.round(2).to_markdown(index=False) if len(bc) else "(no overlap)", "\n",
         f"\n- Rule: when the stamps agree the basis is a few bps and |basis| > {BASIS_BIG:g} bps is rare; a stamp off by an hour would put most hours past it. Pooled: median |basis| "
         f"{bc['abs_median_bps'].median():.1f} bps across names, the share past {BASIS_BIG:g} bps median {bc[f'share_abs_gt_{BASIS_BIG:g}'].median():.4f}.\n" if len(bc) else "",
         "\n## The members' cover of their own hours, per block — the breadth R62's frame would have\n", blocks.to_markdown(index=False) if len(blocks) else "(no member bars)", "\n",
         f"\nA member counts in `cover_ge_{COVER_OK:g}` when ≥ {COVER_OK:.0%} of the hours of the block it is a member of have a spot bar.\n",
         "\n## The two ratios per name\n", st.round(4).to_markdown(index=False) if len(st) else "(no ratios)", "\n",
         "\n## Summary on R62's kept names\n", "```\n" + json.dumps(summary, indent=1) + "\n```\n",
         f"\n- BG3's two questions: does the ratio VARY within a name (`dev_sd`, the deviation's persistence `dev_acf_24h`), and is it `cbprem_dev` again (|corr| ≥ {CORR_SAME:g} on the kept names)?\n",
         "\n## Across names\n"]
    for k, tag in (("tb_dev", "taker-buy share deviation"), ("sr_dev", "spot/perp ratio deviation")):
        o = off[k]
        L.append(f"- {tag}: mean off-diagonal correlation {o.mean():.3f} (min {o.min():.3f}, max {o.max():.3f}) on the hours both names have\n" if len(o) else f"- {tag}: fewer than two names\n")
    for k, tag in (("tb", "taker-buy share"), ("sr", "spot/perp log ratio")):
        h = hod[k]
        L.append(f"- {tag} by hour of day (UTC), averaged over names: " + ", ".join(f"{hh:02d}h {val:+.3f}" for hh, val in h.items()) + "\n" if len(h) else "")
    L += [f"\n## Pooled\n- the taker-buy share's cross-name mean per hour: median {pooled_tb.median():.4f}, p10 {pooled_tb.quantile(0.1):.4f}, p90 {pooled_tb.quantile(0.9):.4f}, sd {pooled_tb.std():.4f}, acf 24 h {_acf(pooled_tb, 24):.3f}\n",
          f"- the spot share of spot + perp quote volume per name (median over hours): median across names {spot_share.median():.3f}, p10 {spot_share.quantile(0.1):.3f}, p90 {spot_share.quantile(0.9):.3f}\n"]
    row = (f"| **spot_1h** (Binance spot, hourly, the twelve's and the screener's members' `<BASE>USDT` markets; decision BH1) | `ft2 spot fetch --listed-only`, raw `data/raw/external/binance_spot/` | "
           + f"{len(listed)} of {len(sf)} perpetuals with a spot symbol, {len(with_bars)} with hourly bars; per block "
           + "; ".join(f"{b['block']} {b[f'cover_ge_{COVER_OK:g}']} of {b['members']}" for _, b in blocks.iterrows())
           + f" | `{path}`; a bar is read at `ts_known` = its start + 1 h |")
    L += ["\n## DATA.md row\n", "\n" + row + "\n"]
    txt = "".join(x if x.endswith("\n") else x + "\n" for x in L)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt)
    (out.parent / "spot_audit.json").write_text(json.dumps({"cover": cov.to_dict("records"), "stats": st.to_dict("records"), "basis": bc.to_dict("records"), "blocks": blocks.to_dict("records"),
                                                           "summary": summary, "corr_mean": {k: (float(v.mean()) if len(v) else None) for k, v in off.items()},
                                                           "hod": {k: {int(h): float(val) for h, val in v.items()} for k, v in hod.items()},
                                                           "pooled_tb": {"median": float(pooled_tb.median()), "sd": float(pooled_tb.std())},
                                                           "spot_share_median": float(spot_share.median()) if len(spot_share.dropna()) else None,
                                                           "window": [str(a0), str(end)]}, indent=1, default=str))
    long = pd.concat([G[k].stack(future_stack=True).rename(k) for k in ("tb", "sr", "basis", "tb_dev", "sr_dev")] + [CB.reindex(columns=G["tb"].columns).stack(future_stack=True).rename("cb_dev")], axis=1)
    long = long.dropna(how="all").reset_index().rename(columns={"level_0": "ts_known", "level_1": "symbol"})
    long.to_parquet(out.parent / "spot_ratios.parquet", index=False)
    return txt


def main(action: str, start: str = START, end: str | None = None, only: list[str] | None = None, listed_only: bool = False) -> None:
    if action == "symbols":
        print(symbols().to_string())
    elif action == "fetch":
        print(json.dumps(fetch(start, end, listed_only=listed_only, only=only), indent=1))
    elif action == "ingest":
        print(json.dumps(ingest(listed_only=True, only=only), indent=1))
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"spot: unknown action {action}")
