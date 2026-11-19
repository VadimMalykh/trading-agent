"""Decision CX1 (PLAN P8, 2026-11-19): the cost of the names outside the twelve, MEASURED, against `costwide`'s pooled proxy.

No label, no forecast, no fold: a name-day's cost is read from the archive's own book and tape and set beside the row the
harness charged. The method and the rule are PLAN's "CX1 — the method" block, committed before any number here was computed.

  sample    the frozen sample of name-days → ft2/cx1_sample.csv (deterministic from the two frozen F5 lists)
  fetch     the archive's bookDepth zip (kept) and aggTrades (reduced to the per-minute tape summary, the zip deleted) a cell
  validity  the impact estimator against the TRUTH on the twelve (the collector's ladder, 2026-08-05 → 09-13): the calibration
            factor k by fill fraction → output/cxcost/validity.csv
  measure   measured against modelled per cell, the tiers, the verdict → output/cxcost/cells.parquet, tiers.csv, cx1.md

The impact estimator (a market order of N USDT against one side whose book holds U02 within 0.2 % of the mid and U1 within 1 %,
the touch h bps from the mid), resting notional spread evenly between the touch and 20 bps, and between 20 and 100 bps:
  N ≤ U02:        N · (20 − h) / (2 · U02)
  U02 < N ≤ U1:   [U02 · (h + 20) / 2 + (N − U02) · (20 + (N − U02) · 80 / (2 · (U1 − U02)))] / N − h
  N > U1:         censored (NaN)
— bps beyond the half-spread, the ladder's own definition (slip − spread / 2)."""
from __future__ import annotations

import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data, ladder, tape

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "cx1_sample.csv"
LISTS = {"members": HERE / "screen_members_f5_coins.csv", "next60": HERE / "screen_next60_f5_coins.csv"}
OUT = Path("output/cxcost")
TAPE_PARTS = data.PROC / "cx1_tape"
BAND_FROM, LAST_DAY = pd.Timestamp("2026-01-15"), pd.Timestamp("2026-09-13")
ROW_STRIDE, DAY_OFFSETS = 3, (2, 8, 14, 20, 26)
NOTIONALS = [1_000, 2_500, 5_000, 10_000]
F_EDGES = [0.0, 0.02, 0.1, 0.3, 1.0, 3.0, np.inf]
F_LABELS = ["<0.02", "0.02-0.1", "0.1-0.3", "0.3-1", "1-3", ">3"]
TIER_EDGES = [0.0, 5e6, 15e6, 30e6, 60e6, np.inf]
TIER_LABELS = ["<5M", "5-15M", "15-30M", "30-60M", ">60M"]
RULE_TIERS = ["5-15M", "15-30M", "30-60M", ">60M"]            # the rule's four; "<5M" is described
BAND = 1.5                                                    # CERTIFIED inside 1/1.5 … 1.5
SHARE = 0.25
TAPE_CAL = 0.90      # the twelve's median tape / quoted ratio (cost_daily: spread_bps / spread_cal_bps, 0.76 … 1.01) — the bounce under-reads the quote
FILLS = {"R100 base": "output/next60/r100/fills_h1_d10_raw.parquet", "R90": "output/allbook/r90/fills.parquet"}


def est_impact(n, u02, u1, h):
    """The linear-book estimate (module docstring), bps beyond the half-spread; arrays broadcast; NaN where censored or no band."""
    n, u02, u1, h = (np.asarray(x, dtype="float64") for x in np.broadcast_arrays(n, u02, u1, h))
    h = np.clip(h, 0.0, 20.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        near = n * (20.0 - h) / (2.0 * u02)
        over = n - u02
        far = (u02 * (h + 20.0) / 2.0 + over * (20.0 + over * 80.0 / (2.0 * (u1 - u02)))) / n - h
    out = np.where(n <= u02, near, np.where(n <= u1, far, np.nan))
    return np.where((u02 > 0) & (u1 >= u02), out, np.nan)


# ---- the sample --------------------------------------------------------------------------------
def sample() -> pd.DataFrame:
    rows = []
    for name, p in LISTS.items():
        d = pd.read_csv(p).sort_values(["block", "symbol"], kind="mergesort").reset_index(drop=True)
        for _, r in d.iloc[::ROW_STRIDE].iterrows():
            for k in DAY_OFFSETS:
                day = pd.Timestamp(r["block"]) + pd.Timedelta(days=k)
                if BAND_FROM <= day <= LAST_DAY:
                    rows.append({"list": name, "block": r["block"], "symbol": r["symbol"], "day": f"{day:%Y-%m-%d}"})
    s = pd.DataFrame(rows).drop_duplicates(["symbol", "day"]).reset_index(drop=True)
    s.to_csv(SAMPLE, index=False)
    return s


# ---- the fetch ---------------------------------------------------------------------------------
def _cell(sym: str, day: str, keys: dict) -> str:
    d = date.fromisoformat(day)
    out = []
    nb = f"{sym}-bookDepth-{day}.zip"
    out.append("depth:" + (archive._fetch(keys["bookDepth"][nb], archive.ROOT / "bookDepth" / sym / nb) if nb in keys["bookDepth"] else "missing"))
    part = TAPE_PARTS / sym / f"{day}.parquet"
    na = f"{sym}-aggTrades-{day}.zip"
    if part.exists():
        out.append("tape:skip")
    elif na not in keys["aggTrades"]:
        out.append("tape:missing")
    else:
        zp = archive.ROOT / "aggTrades" / sym / na
        st = archive._fetch(keys["aggTrades"][na], zp)
        if st in ("ok", "skip"):
            try:
                df = tape.summarize_day(zp, sym)
                part.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(part, index=False)
                zp.unlink(missing_ok=True); zp.with_suffix(".zip.ok").unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                print(f"  err summarizing {na}: {e!r}", file=sys.stderr, flush=True)
                st = "err"
        out.append("tape:" + st)
    return " ".join(out)


def fetch() -> None:
    s = pd.read_csv(SAMPLE)
    counts: dict[str, int] = {}
    for sym, g in s.groupby("symbol"):
        keys = {k: {x.rsplit("/", 1)[1]: x for x in archive.list_keys(f"data/futures/um/daily/{k}/{sym}/") if x.endswith(".zip")}
                for k in ("bookDepth", "aggTrades")}
        with ThreadPoolExecutor(max_workers=5) as ex:
            for st in ex.map(lambda d: _cell(sym, d, keys), g["day"]):
                for x in st.split():
                    counts[x] = counts.get(x, 0) + 1
        print(f"fetch {sym:<16} {len(g)} days", flush=True)
    print("fetch counts:", dict(sorted(counts.items())), flush=True)


# ---- validity: the estimator against the ladder's truth on the twelve ---------------------------
def validity() -> pd.DataFrame:
    parts = []
    for p in sorted((data.PROC / "ladder").glob("*.parquet")):
        cols = ["symbol", "spread_bps", "usd_bid_02", "usd_ask_02", "usd_bid_1", "usd_ask_1"] + [ladder.slip_col(s, n) for s in ("buy", "sell") for n in ladder.NOTIONALS]
        d = pd.read_parquet(p, columns=cols).iloc[::5]
        h = d["spread_bps"].to_numpy() / 2
        for side, band in (("buy", "ask"), ("sell", "bid")):
            for n in ladder.NOTIONALS:
                u02, u1 = d[f"usd_{band}_02"].to_numpy(), d[f"usd_{band}_1"].to_numpy()
                parts.append(pd.DataFrame({"symbol": str(d["symbol"].iloc[0]), "n": n, "f": n / u02,
                                           "truth": d[ladder.slip_col(side, n)].to_numpy() - h, "est": est_impact(n, u02, u1, h)}))
    v = pd.concat(parts, ignore_index=True)
    v = v[np.isfinite(v["truth"]) & np.isfinite(v["est"]) & np.isfinite(v["f"])]
    v["f_bin"] = pd.cut(v["f"], F_EDGES, labels=F_LABELS, right=False)
    g = v.groupby("f_bin", observed=False)
    t = pd.DataFrame({"rows": g.size(), "pairs": g["symbol"].nunique(), "truth_p50": g["truth"].median(), "est_p50": g["est"].median(),
                      "truth_mean": g["truth"].mean(), "est_mean": g["est"].mean()})
    t["k"] = t["est_p50"] / t["truth_p50"]                     # the calibration factor: measured = est / k
    t["k_mean"] = t["est_mean"] / t["truth_mean"]
    bp = v.groupby(["f_bin", "symbol"], observed=True).agg(truth=("truth", "median"), est=("est", "median"))
    bp["k"] = bp["est"] / bp["truth"]
    t["k_pair_min"], t["k_pair_max"] = bp.groupby("f_bin", observed=False)["k"].min(), bp.groupby("f_bin", observed=False)["k"].max()
    OUT.mkdir(parents=True, exist_ok=True)
    t.to_csv(OUT / "validity.csv")
    bp.reset_index().to_csv(OUT / "validity_by_pair.csv", index=False)
    return t


# ---- the measurement ---------------------------------------------------------------------------
def _depth_day(sym: str, day: str) -> dict | None:
    zp = archive.ROOT / "bookDepth" / sym / f"{sym}-bookDepth-{day}.zip"
    if not (zp.exists() and zp.with_suffix(".zip.ok").exists()):
        return None
    with zipfile.ZipFile(zp) as z:
        d = pd.read_csv(z.open(z.namelist()[0]))
    w = d.pivot_table(index="timestamp", columns="percentage", values="notional", aggfunc="last")
    need = [-1.0, -0.2, 0.2, 1.0]
    if any(c not in w.columns for c in need):
        return None
    w = w[need].dropna()
    if len(w) < 100:
        return None
    return {"snaps": len(w), "bid_02": float(w[-0.2].median()), "ask_02": float(w[0.2].median()), "bid_1": float(w[-1.0].median()),
            "ask_1": float(w[1.0].median()), "_w": w}


def _tape_day(sym: str, day: str) -> dict | None:
    p = TAPE_PARTS / sym / f"{day}.parquet"
    if not p.exists():
        return None
    t = pd.read_parquet(p, columns=["eff_spread_bps", "n_flips", "notional"])
    e = t.loc[t["n_flips"] > 0, "eff_spread_bps"]
    if len(e) < 30:
        return None
    return {"tape_bps": float(e.median()), "tape_minutes": int(len(e)), "tape_notional": float(t["notional"].sum())}


def _k_of(f: np.ndarray, k: pd.Series) -> np.ndarray:
    idx = np.clip(np.searchsorted(F_EDGES, f, side="right") - 1, 0, len(F_LABELS) - 1)
    return k.reindex(F_LABELS).to_numpy()[idx]


def cells(k: pd.Series) -> pd.DataFrame:
    s = pd.read_csv(SAMPLE)
    cost = pd.read_parquet(data.PROC / "cost_daily_wide.parquet",
                           columns=["symbol", "day", "dollar_vol", "tick_bps", "spread_cal_bps"] + [f"imp_{n}" for n in NOTIONALS])
    cost["symbol"] = cost["symbol"].astype(str)
    cost["day"] = cost["day"].dt.strftime("%Y-%m-%d")
    rows = []
    for r in s.itertuples():
        dp, tp = _depth_day(r.symbol, r.day), _tape_day(r.symbol, r.day)
        row = {"list": r.list, "symbol": r.symbol, "day": r.day, "has_depth": dp is not None, "has_tape": tp is not None}
        if dp is not None and tp is not None:
            w = dp.pop("_w")
            spread = tp["tape_bps"] / TAPE_CAL
            h = spread / 2
            row.update(dp); row.update(tp); row["spread_meas"] = spread
            for n in NOTIONALS:
                raw, cal, snap, fs = [], [], [], []
                for u02, u1, c02, c1 in ((dp["bid_02"], dp["bid_1"], -0.2, -1.0), (dp["ask_02"], dp["ask_1"], 0.2, 1.0)):
                    e = float(est_impact(n, u02, u1, h))
                    f = n / u02 if u02 > 0 else np.inf
                    raw.append(e); cal.append(e / float(_k_of(np.array([f]), k)[0])); fs.append(f)
                    sn = est_impact(n, w[c02].to_numpy(), w[c1].to_numpy(), h)
                    snap.append(float(np.nanmedian(sn)) if np.isfinite(sn).any() else np.nan)
                row[f"imp_raw_{n}"], row[f"imp_meas_{n}"], row[f"imp_snap_{n}"], row[f"f_{n}"] = np.mean(raw), np.mean(cal), np.mean(snap), np.mean(fs)
        rows.append(row)
    c = pd.DataFrame(rows).merge(cost, on=["symbol", "day"], how="left")
    c["has_cost"] = c["spread_cal_bps"].notna()
    for n in NOTIONALS:
        c[f"leg_meas_{n}"] = c["spread_meas"] / 2 + c[f"imp_meas_{n}"]
        c[f"leg_raw_{n}"] = c["spread_meas"] / 2 + c[f"imp_raw_{n}"]
        c[f"leg_model_{n}"] = c["spread_cal_bps"] / 2 + c[f"imp_{n}"]
        c[f"ratio_{n}"] = c[f"leg_meas_{n}"] / c[f"leg_model_{n}"]
        c[f"ratio_raw_{n}"] = c[f"leg_raw_{n}"] / c[f"leg_model_{n}"]
    c["tier"] = pd.cut(c["dollar_vol"], TIER_EDGES, labels=TIER_LABELS, right=False)
    return c


def _boot(x: pd.DataFrame, col: str, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """A 95 % interval of the median of `col`, names resampled whole."""
    names = x["symbol"].unique()
    by = {s: g[col].to_numpy() for s, g in x.groupby("symbol")}
    rng = np.random.default_rng(seed)
    meds = [np.median(np.concatenate([by[s] for s in rng.choice(names, len(names))])) for _ in range(n_boot)]
    return float(np.quantile(meds, 0.025)), float(np.quantile(meds, 0.975))


def tiers(c: pd.DataFrame) -> pd.DataFrame:
    ok = c[c["has_depth"] & c["has_tape"] & c["has_cost"] & np.isfinite(c["ratio_10000"])]
    rows = []
    for t in TIER_LABELS:
        x = ok[ok["tier"] == t]
        if x.empty:
            rows.append({"tier": t, "cells": 0}); continue
        lo, hi = _boot(x, "ratio_10000") if x["symbol"].nunique() >= 5 else (np.nan, np.nan)
        row = {"tier": t, "cells": len(x), "names": x["symbol"].nunique(), "ratio_10000": x["ratio_10000"].median(), "ratio_lo": lo, "ratio_hi": hi,
               "ratio_raw_10000": x["ratio_raw_10000"].median(),
               "spread_meas": x["spread_meas"].median(), "spread_model": x["spread_cal_bps"].median(), "tick_bps": x["tick_bps"].median(),
               "u02_usd": ((x["bid_02"] + x["ask_02"]) / 2).median(), "f_10000": x["f_10000"].median()}
        for n in NOTIONALS:
            row[f"leg_meas_{n}"], row[f"leg_model_{n}"] = x[f"leg_meas_{n}"].median(), x[f"leg_model_{n}"].median()
            row[f"imp_meas_{n}"], row[f"imp_model_{n}"] = x[f"imp_meas_{n}"].median(), x[f"imp_{n}"].median()
            if n != 10_000:
                row[f"ratio_{n}"] = x[f"ratio_{n}"].median()
        r = row["ratio_10000"]
        row["verdict"] = "CERTIFIED" if 1 / BAND <= r <= BAND else ("OVERSTATED" if r < 1 / BAND else "UNDERSTATED")
        rows.append(row)
    return pd.DataFrame(rows).set_index("tier")


def shares() -> pd.DataFrame:
    """The share of each read's positions by the entry day's turnover tier (the name and the day only — no result column is read)."""
    cost = pd.read_parquet(data.PROC / "cost_daily_wide.parquet", columns=["symbol", "day", "dollar_vol"])
    cost["symbol"] = cost["symbol"].astype(str)
    out = {}
    for name, p in FILLS.items():
        if not Path(p).exists():
            continue
        f = pd.read_parquet(p, columns=["id", "symbol", "entry_t"]).drop_duplicates("id")
        f["symbol"] = f["symbol"].astype(str)
        f["day"] = pd.to_datetime(f["entry_t"], utc=True).dt.floor("D")
        m = f.merge(cost, on=["symbol", "day"], how="left")
        t = pd.cut(m["dollar_vol"], TIER_EDGES, labels=TIER_LABELS, right=False)
        out[name] = t.value_counts(normalize=True, dropna=False).rename(index=lambda x: "no cost row" if pd.isna(x) else x)
    return pd.DataFrame(out).fillna(0.0)


def verdict(t: pd.DataFrame, sh: pd.DataFrame) -> tuple[str, list[str]]:
    bad = [x for x in RULE_TIERS if x in t.index and t.loc[x].get("verdict") in ("OVERSTATED", "UNDERSTATED")]
    hit = [x for x in bad if x in sh.index and (sh.loc[x] >= SHARE).any()]
    return ("DEFECTIVE" if hit else "CERTIFIED"), hit


def measure() -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    v = validity()
    c = cells(v["k"])
    c.to_parquet(OUT / "cells.parquet", index=False)
    t, sh = tiers(c), shares()
    t.to_csv(OUT / "tiers.csv"); sh.to_csv(OUT / "shares.csv")
    word, hit = verdict(t, sh)
    ok = c[c["has_depth"] & c["has_tape"] & c["has_cost"] & np.isfinite(c["ratio_10000"])]
    fb = pd.cut(ok["f_10000"], F_EDGES, labels=F_LABELS, right=False).value_counts(normalize=True).reindex(F_LABELS)
    by_list = ok.groupby(["list", "tier"], observed=True)["ratio_10000"].agg(["size", "median"])
    cens = c[c["has_depth"] & c["has_tape"] & c["has_cost"] & ~np.isfinite(c["ratio_10000"])]
    text = "\n".join([
        "# CX1 — the wide names' cost, measured against `costwide`'s pooled proxy (PLAN P8 decision CX1)\n",
        f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
        f"\nSample: {len(c):,} name-days ({c['symbol'].nunique()} names); with the depth file {int(c['has_depth'].sum()):,}, the tape {int(c['has_tape'].sum()):,}, "
        f"a cost row {int(c['has_cost'].sum()):,}; measured at 10,000 {len(ok):,}; censored at 10,000 (N above the ±1 % band) {len(cens)}.\n",
        f"\n## VERDICT: {word}" + (f" — outside 1/{BAND} … {BAND} in {', '.join(hit)} (≥ {SHARE:.0%} of a read's positions)" if hit else "") + "\n",
        "\n## The tiers (medians over name-days; leg = half-spread + impact, bps beyond the fee; ratio = measured / modelled at 10,000)\n",
        t.round(3).T.to_markdown(), "\n",
        "\n## The share of each read's positions by the entry day's tier\n", sh.round(3).to_markdown(), "\n",
        "\n## Validity: the estimator against the ladder's truth on the twelve (k = est / truth at the medians; measured = est / k)\n", v.round(4).to_markdown(), "\n",
        "\n## The sample's fill fraction at 10,000 (N / U02), share of measured cells\n", fb.round(3).to_markdown(), "\n",
        "\n## By list\n", by_list.round(3).to_markdown(), "\n"])
    (OUT / "cx1.md").write_text(text)
    return text


def main(action: str) -> None:
    if action == "sample":
        s = sample()
        print(f"{len(s)} name-days, {s['symbol'].nunique()} names → {SAMPLE}")
        print(s.groupby("list").agg(cells=("day", "size"), names=("symbol", "nunique")).to_string())
    elif action == "fetch":
        fetch()
    elif action == "validity":
        print(validity().round(4).to_string())
    elif action == "measure":
        print(measure())
    else:
        raise SystemExit(f"unknown action {action}")
