"""R55 (PLAN §8; decision AM1) — the one-day at-the-money straddle's history on BTC and ETH from Deribit's public chart endpoint, and
its touch on Tardis's free days: `ft2 straddle fetch|quotes|ingest|inventory`.

fetch      for each day d of the window (F1+F2 by default) and name: ONE call for the perpetual's 1-minute bars over [d 00:00, d+1 08:00)
           (1,920 bars: the spot = the 00:00 bar's open, the hedge's prices = the close of the bar ending at each hour, the settlement =
           the mean close of the 07:30 → 07:59 bars — Deribit delivers daily options at 08:00 UTC on a 30-minute TWAP of the index; the
           perpetual's TWAP stands in), then the daily-expiry call and put `<CUR>-<d+1>-<K>-C/P` at the strike nearest the spot on the
           exchange's grid (nearest first until both legs are served) as hourly bars over [d−1 00:00, d+1 08:00). One JSON a day a name
           under data/raw/external/deribit/straddle/<CUR>/<day>.json; resumable; two names in parallel, paced.
quotes     Tardis's free first-of-month days inside the window: the `quotes` CSV of the SAME two legs the chart used that day
           (≈ 0.3 MB a file; per-instrument files only — the whole-market files burn the free tier's daily limit, DATA.md `tardis`),
           under data/raw/external/tardis/quotes/<day>/<name>.csv.gz; a 429 stops the run (the limit resets daily); resumable.
ingest     data/straddle_1d.parquet   (currency, day) → spot_00, strike, call, put, c_last / p_last (the LAST TRADED price before 00:00:
                                      the close of the last hourly bar with volume > 0 ending at or before 00:00), c_last_ts / p_last_ts,
                                      c_trades_24h / p_trades_24h, c_open_00 / p_open_00, settle (the TWAP), settle_bars, parity
                                      (c_last − p_last − (spot − K) / spot), covered + skip reason
           data/straddle_hedge.parquet (currency, day, i) → ts, price: i = 0 … 31 the perpetual's close at 00:00 + i h (i = 0 the spot),
                                      i = 32 the settlement
           data/straddle_touch.parquet (currency, day, leg) → name, first_ts, bid, ask, spread_med_h0, spot: the quote at the first
                                      update at or after 00:00 and the median spread of hour 0
inventory  output/straddle_inventory.md: per name and fold the days, the served, the traded-within-24h, the parity-consistent (covered),
           the skip causes; the touch's 16 days and their median; a DATA.md table.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds, optsrc

RAW = data.RAW / "external" / "deribit" / "straddle"
RAW_Q = data.RAW / "external" / "tardis" / "quotes"
PARQUET = data.PROC / "straddle_1d.parquet"
HEDGE = data.PROC / "straddle_hedge.parquet"
TOUCH = data.PROC / "straddle_touch.parquet"
OUT = Path("output/straddle_inventory.md")
NAMES = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
EXPIRY_H = 8                     # daily options settle at 08:00 UTC
TENOR_H = 24 + EXPIRY_H          # 00:00 of d → 08:00 of d + 1
PARITY_TOL = 0.005               # |C − P − (S − K) / S| in units of spot
SETTLE_MIN = 25                  # of the 30 one-minute bars 07:30 → 07:59
PAUSE = 0.2
HOUR_MS, MIN_MS = 3_600_000, 60_000


def window(fold_names=("F1", "F2")) -> tuple[pd.Timestamp, pd.Timestamp]:
    a = min(pd.Timestamp(folds.FOLDS[f][0], tz="UTC") for f in fold_names)
    b = max(pd.Timestamp(folds.FOLDS[f][1], tz="UTC") for f in fold_names)
    return a, b


def _chart(name: str, start_ms: int, end_ms: int, res: str) -> dict:
    r = optsrc._get(f"{optsrc.DERIBIT}get_tradingview_chart_data?instrument_name={name}&start_timestamp={start_ms}&end_timestamp={end_ms}&resolution={res}")
    time.sleep(PAUSE)
    return r if isinstance(r, dict) else {}


def _served(r: dict) -> bool:
    return r.get("status") == "ok" and bool(r.get("ticks"))


def fetch_day(cur: str, day: pd.Timestamp) -> dict:
    d0 = int(day.timestamp() * 1000)
    perp = _chart(f"{cur}-PERPETUAL", d0, d0 + TENOR_H * HOUR_MS - MIN_MS, "1")
    out = {"currency": cur, "day": str(day.date()), "perp_1m": perp if _served(perp) else None, "legs": None, "tried": []}
    if not _served(perp):
        return out
    i0 = int(np.argmin(np.abs(np.asarray(perp["ticks"]) - d0)))
    spot = float(perp["open"][i0]) if abs(perp["ticks"][i0] - d0) < MIN_MS else None
    out["spot_00"] = spot
    if spot is None:
        return out
    expiry = day + pd.Timedelta(days=1)
    for k in optsrc.atm_candidates(cur, spot):
        legs = {}
        for cp in ("C", "P"):
            name = optsrc.daily_name(cur, expiry, k, cp)
            legs[cp] = {"name": name, "chart": _chart(name, d0 - 24 * HOUR_MS, d0 + TENOR_H * HOUR_MS, "60")}
        if _served(legs["C"]["chart"]) and _served(legs["P"]["chart"]):
            out["strike"], out["legs"] = k, legs
            return out
        out["tried"].append({str(k): {cp: legs[cp]["chart"].get("status") or legs[cp]["chart"].get("error") for cp in legs}})
    return out


def fetch(currencies=tuple(NAMES), fold_names=("F1", "F2"), start: str | None = None, end: str | None = None) -> dict:
    a, b = window(fold_names)
    a = pd.Timestamp(start, tz="UTC") if start else a
    b = pd.Timestamp(end, tz="UTC") if end else b
    days = pd.date_range(a, b - pd.Timedelta(days=1), freq="D")

    def one(cur):
        n_new = 0
        for d in days:
            dest = RAW / cur / f"{d:%Y-%m-%d}.json"
            if dest.exists():
                continue
            optsrc._save(dest, fetch_day(cur, d))
            n_new += 1
            if n_new % 20 == 0:
                print(f"straddle fetch {cur}: {d:%Y-%m-%d} ({n_new} new)", flush=True)
        return n_new

    with ThreadPoolExecutor(max_workers=len(currencies)) as ex:
        res = dict(zip(currencies, ex.map(one, currencies)))
    print(f"straddle fetch: {res} new day files, {len(days)} days a name asked", flush=True)
    return res


def _day_files(cur: str) -> list[Path]:
    return sorted((RAW / cur).glob("*.json")) if (RAW / cur).exists() else []


def quotes(currencies=tuple(NAMES), fold_names=("F1", "F2")) -> dict:
    a, b = window(fold_names)
    rep = {}
    for cur in currencies:
        for d in optsrc.first_of_months(a, b):
            f = RAW / cur / f"{d:%Y-%m-%d}.json"
            if not f.exists():
                rep[f"{cur} {d:%Y-%m-%d}"] = "no day file"
                continue
            j = json.loads(f.read_text())
            if not j.get("legs"):
                rep[f"{cur} {d:%Y-%m-%d}"] = "no legs"
                continue
            for cp in ("C", "P"):
                name = j["legs"][cp]["name"]
                dest = RAW_Q / f"{d:%Y-%m-%d}" / f"{name}.csv.gz"
                if dest.exists():
                    continue
                r = optsrc._get(f"{optsrc.TARDIS_CSV}/quotes/{d:%Y/%m/%d}/{name}.csv.gz", raw=True)
                if isinstance(r, (bytes, bytearray)):
                    optsrc._save(dest, r)
                    rep[f"{cur} {d:%Y-%m-%d} {cp}"] = len(r)
                else:
                    rep[f"{cur} {d:%Y-%m-%d} {cp}"] = f"HTTP {r.get('status')} {str(r.get('body'))[:80]}"
                    if r.get("status") == 429:
                        print(json.dumps(rep, indent=1))
                        sys.exit("straddle quotes: Tardis's daily limit reached — run again tomorrow (resumable)")
                time.sleep(0.5)
    print(json.dumps(rep, indent=1))
    return rep


# ----------------------------------------------------------------------------- ingest (pure on the saved JSON; tested)
def last_trade_before(chart: dict, t_ms: int) -> tuple[float | None, int | None, int]:
    """The close of the last hourly bar with a trade that ENDS at or before t_ms; its end time; the bars with a trade in the 24 h before."""
    t = np.asarray(chart["ticks"], dtype="int64")
    v = np.asarray(chart["volume"], dtype=float)
    c = np.asarray(chart["close"], dtype=float)
    ok = (t + HOUR_MS <= t_ms) & (v > 0)
    n24 = int((ok & (t >= t_ms - 24 * HOUR_MS)).sum())
    if not ok.any():
        return None, None, n24
    i = int(np.flatnonzero(ok)[-1])
    return float(c[i]), int(t[i] + HOUR_MS), n24


def perp_path(perp: dict, d0: int) -> tuple[np.ndarray, float | None, int]:
    """From the perpetual's 1-minute bars: the price at 00:00 + i h for i = 0 … 31 (i = 0 the 00:00 bar's OPEN, then the close of the
    bar ending at the hour), the settlement TWAP (mean close of the bars 07:30 → 07:59 of d + 1) and its bar count."""
    t = np.asarray(perp["ticks"], dtype="int64")
    o = np.asarray(perp["open"], dtype=float)
    c = np.asarray(perp["close"], dtype=float)
    pos = {int(x): i for i, x in enumerate(t)}
    path = np.full(TENOR_H, np.nan)
    if d0 in pos:
        path[0] = o[pos[d0]]
    for i in range(1, TENOR_H):
        k = d0 + i * HOUR_MS - MIN_MS
        if k in pos:
            path[i] = c[pos[k]]
    s0 = d0 + (24 + EXPIRY_H) * HOUR_MS - 30 * MIN_MS
    m = (t >= s0) & (t < s0 + 30 * MIN_MS)
    return path, (float(c[m].mean()) if m.any() else None), int(m.sum())


def day_row(j: dict) -> tuple[dict, list[dict]]:
    cur, day = j["currency"], pd.Timestamp(j["day"], tz="UTC")
    d0 = int(day.timestamp() * 1000)
    row = {"currency": cur, "day": day, "spot_00": j.get("spot_00"), "strike": j.get("strike"), "call": None, "put": None, "covered": False, "skip": None}
    hedge = []
    if not j.get("perp_1m"):
        row["skip"] = "no perpetual bars"
        return row, hedge
    path, settle, nbars = perp_path(j["perp_1m"], d0)
    row.update({"settle": settle, "settle_bars": nbars, "path_missing": int(np.isnan(path).sum())})
    if not j.get("legs"):
        row["skip"] = "no served pair"
        return row, hedge
    for cp, key in (("C", "c"), ("P", "p")):
        ch = j["legs"][cp]["chart"]
        px, ts, n24 = last_trade_before(ch, d0)
        t = np.asarray(ch["ticks"], dtype="int64")
        i0 = int(np.argmin(np.abs(t - d0)))
        row[{"C": "call", "P": "put"}[cp]] = j["legs"][cp]["name"]
        row.update({f"{key}_last": px, f"{key}_last_ts": pd.Timestamp(ts, unit="ms", tz="UTC") if ts else pd.NaT, f"{key}_trades_24h": n24,
                    f"{key}_open_00": float(ch["open"][i0]) if abs(t[i0] - d0) < HOUR_MS else np.nan,
                    f"{key}_traded_00": bool(ch["volume"][i0] > 0) if abs(t[i0] - d0) < HOUR_MS else False})
    s, k = row["spot_00"], row["strike"]
    if row["c_last"] is None or row["p_last"] is None or row["c_trades_24h"] == 0 or row["p_trades_24h"] == 0:
        row["skip"] = "a leg without a trade in the 24 h before"
    else:
        row["parity"] = row["c_last"] - row["p_last"] - (s - k) / s
        if abs(row["parity"]) > PARITY_TOL:
            row["skip"] = "parity"
        elif settle is None or nbars < SETTLE_MIN:
            row["skip"] = "settlement window short"
        elif np.isnan(path).any():
            row["skip"] = "perpetual path incomplete"
        else:
            row["covered"] = True
    if row["covered"]:
        hedge = [{"currency": cur, "day": day, "i": i, "ts": day + pd.Timedelta(hours=i), "price": float(path[i])} for i in range(TENOR_H)]
        hedge.append({"currency": cur, "day": day, "i": TENOR_H, "ts": day + pd.Timedelta(hours=TENOR_H), "price": float(settle)})
    return row, hedge


def touch_rows(cur: str, day: pd.Timestamp, name: str, leg: str, raw: bytes, spot: float) -> dict:
    q = pd.read_csv(io.BytesIO(raw), compression="gzip")
    q["ts"] = pd.to_datetime(q["timestamp"], unit="us", utc=True)
    q = q.dropna(subset=["bid_price", "ask_price"])
    after = q[q["ts"] >= day]
    h0 = q[(q["ts"] >= day) & (q["ts"] < day + pd.Timedelta(hours=1))]
    first = after.iloc[0] if len(after) else None
    return {"currency": cur, "day": day, "leg": leg, "name": name, "spot": spot,
            "first_ts": first["ts"] if first is not None else pd.NaT, "bid": float(first["bid_price"]) if first is not None else np.nan,
            "ask": float(first["ask_price"]) if first is not None else np.nan,
            "spread_med_h0": float((h0["ask_price"] - h0["bid_price"]).median()) if len(h0) else np.nan, "updates_h0": int(len(h0))}


def ingest(currencies=tuple(NAMES)) -> dict:
    rows, hedge, touch, rep = [], [], [], {}
    for cur in currencies:
        files = _day_files(cur)
        for f in files:
            r, h = day_row(json.loads(f.read_text()))
            rows.append(r)
            hedge += h
        rep[cur] = {"day_files": len(files), "covered": int(sum(r["covered"] for r in rows if r["currency"] == cur))}
    if RAW_Q.exists():
        by = {(r["currency"], r["day"]): r for r in rows}
        for dd in sorted(RAW_Q.iterdir()):
            day = pd.Timestamp(dd.name, tz="UTC")
            for f in sorted(dd.glob("*.csv.gz")):
                name = f.name[:-7]
                cur = name.split("-")[0]
                r = by.get((cur, day))
                if r is None or r.get("spot_00") is None:
                    continue
                touch.append(touch_rows(cur, day, name, name[-1], f.read_bytes(), r["spot_00"]))
    PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(PARQUET, index=False)
    pd.DataFrame(hedge).to_parquet(HEDGE, index=False)
    pd.DataFrame(touch).to_parquet(TOUCH, index=False)
    rep["touch_rows"] = len(touch)
    print(json.dumps(rep, indent=1, default=str))
    return rep


def inventory(fold_names=("F1", "F2")) -> str:
    d = pd.read_parquet(PARQUET)
    d["day"] = pd.DatetimeIndex(d["day"]).tz_convert("UTC") if pd.DatetimeIndex(d["day"]).tz else pd.DatetimeIndex(d["day"]).tz_localize("UTC")
    tch = pd.read_parquet(TOUCH) if TOUCH.exists() else pd.DataFrame()
    L = ["# The one-day straddle's history — inventory (R55, `ft2 straddle`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
         "\nA day is COVERED when both legs are served, each traded in the 24 hours before 00:00, the pair is parity-consistent (|C − P − (S − K) / S| ≤ 0.5 % of spot), the settlement window holds ≥ 25 of its 30 bars and the hedge path is whole.\n",
         "\n| name | fold | days | served pair | both legs traded 24h | parity-consistent | covered | 00:00 bar traded both legs | skipped: no pair / untraded / parity / settle / path |\n|---|---|---|---|---|---|---|---|---|"]
    tab = []
    for cur, g in d.groupby("currency"):
        for f in [*fold_names, "all"]:
            if f == "all":
                gg = g
            else:
                a, b = folds.bounds(f)
                gg = g[(g["day"] >= a) & (g["day"] < b)]
            served = gg["call"].notna()
            traded = served & (gg["c_trades_24h"].fillna(0) > 0) & (gg["p_trades_24h"].fillna(0) > 0)
            par = traded & (gg["parity"].abs() <= PARITY_TOL)
            sk = gg["skip"].value_counts()
            r = {"name": cur, "fold": f, "days": len(gg), "served": int(served.sum()), "traded": int(traded.sum()), "parity_ok": int(par.sum()), "covered": int(gg["covered"].sum()),
                 "both_00": int((gg["c_traded_00"].fillna(False) & gg["p_traded_00"].fillna(False)).sum()),
                 "skips": f"{sk.get('no served pair', 0)} / {sk.get('a leg without a trade in the 24 h before', 0)} / {sk.get('parity', 0)} / {sk.get('settlement window short', 0)} / {sk.get('perpetual path incomplete', 0)}"}
            tab.append(r)
            L.append(f"| {cur} | {f} | {r['days']} | {r['served']} | {r['traded']} | {r['parity_ok']} | {r['covered']} ({r['covered'] / max(r['days'], 1):.0%}) | {r['both_00']} | {r['skips']} |")
    cov = d[d["covered"]]
    if len(cov):
        L.append("\n| name | straddle at the last trades, % of spot: median (p10 – p90) | c_last age at 00:00, median h | p_last age, median h | settle − spot, median % |\n|---|---|---|---|---|")
        for cur, g in cov.groupby("currency"):
            m = 100 * (g["c_last"] + g["p_last"])
            ca = (g["day"] - pd.DatetimeIndex(g["c_last_ts"])).dt.total_seconds() / 3600
            pa = (g["day"] - pd.DatetimeIndex(g["p_last_ts"])).dt.total_seconds() / 3600
            L.append(f"| {cur} | {m.median():.2f} ({m.quantile(.1):.2f} – {m.quantile(.9):.2f}) | {ca.median():.1f} | {pa.median():.1f} | {(100 * (g['settle'] / g['spot_00'] - 1)).median():+.2f} |")
    if len(tch):
        L.append("\n## The touch on Tardis's free days (the at-the-money straddle at the first quote at or after 00:00; bps of spot)\n")
        L.append("| name | day | call | put | straddle bid | ask | spread bps of spot | spread / mid | median spread hour 0, bps |\n|---|---|---|---|---|---|---|---|---|")
        tch["day"] = pd.DatetimeIndex(tch["day"]).tz_convert("UTC") if pd.DatetimeIndex(tch["day"]).tz else pd.DatetimeIndex(tch["day"]).tz_localize("UTC")
        for (cur, day), g in tch.groupby(["currency", "day"]):
            c = g[g["leg"] == "C"].iloc[0] if (g["leg"] == "C").any() else None
            p = g[g["leg"] == "P"].iloc[0] if (g["leg"] == "P").any() else None
            if c is None or p is None:
                L.append(f"| {cur} | {day:%Y-%m-%d} | {'' if c is None else c['name']} | {'' if p is None else p['name']} | one leg missing | | | | |")
                continue
            bid, ask = c["bid"] + p["bid"], c["ask"] + p["ask"]
            L.append(f"| {cur} | {day:%Y-%m-%d} | {c['name']} | {p['name']} | {bid:.4f} | {ask:.4f} | {1e4 * (ask - bid):.0f} | {(ask - bid) / ((ask + bid) / 2):.0%} | {1e4 * (c['spread_med_h0'] + p['spread_med_h0']):.0f} |")
        sp = touch_spread(tch)
        L.append("\n" + "; ".join(f"{cur}: median spread {v['median_bps']:.0f} bps of spot over {v['days']} days (range {v['min_bps']:.0f} – {v['max_bps']:.0f})" for cur, v in sp.items()))
    rows = pd.DataFrame(tab)
    allr = rows[rows["fold"] == "all"].set_index("name")
    L.append("\n## DATA.md row\n")
    L.append("| **straddle_1d** (the one-day at-the-money straddle on BTC and ETH, F1+F2; R55) | Deribit's public chart endpoint, `ft2 straddle fetch`, raw `data/raw/external/deribit/straddle/` | "
             + "; ".join(f"{cur} {int(r['days'])} days, {int(r['covered'])} covered ({r['covered'] / r['days']:.0%})" for cur, r in allr.iterrows())
             + " | `data/straddle_1d.parquet`, `data/straddle_hedge.parquet`, `data/straddle_touch.parquet` |")
    txt = "\n".join(L) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(txt)
    return txt


def touch_spread(tch: pd.DataFrame) -> dict:
    """Per name: the straddle's spread at the touch (bid-ask of the call + of the put) at the first quote at or after 00:00 on each free
    day, in bps of spot; the median is R55's one crossing constant."""
    out = {}
    for cur, g in tch.groupby("currency"):
        days = []
        for day, gg in g.groupby("day"):
            if set(gg["leg"]) >= {"C", "P"} and gg["bid"].notna().all():
                days.append(1e4 * float((gg["ask"] - gg["bid"]).sum()))
        if days:
            out[cur] = {"median_bps": float(np.median(days)), "days": len(days), "min_bps": float(min(days)), "max_bps": float(max(days))}
    return out


def main(action: str, currencies=None, start=None, end=None) -> None:
    cur = tuple(currencies) if currencies else tuple(NAMES)
    if action == "fetch":
        fetch(cur, start=start, end=end)
    elif action == "quotes":
        quotes(cur)
    elif action == "ingest":
        ingest(cur)
    elif action == "inventory":
        print(inventory())
    else:
        sys.exit(f"straddle: unknown action {action}")
