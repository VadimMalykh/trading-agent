"""P8 (decision AL1, after R54) — the option-price source audit: `ft2 optsrc audit`.

What a variance product on R54's one-day edge needs and the project does not hold: the price of a one-day BTC / ETH straddle at the
open of each day (the entry), the spread at the touch (the cost of crossing), the fees, and a daily series over F1+F2 to read the
forecast's sign against the implied. This module MEASURES what each free source serves — extent, shape, cadence — and records the
one paid source's price list; it builds no series and reads no fold (the cost read is its own registration, written against the
section this audit puts in DATA.md).

deribit    public, keyless JSON-RPC (www.deribit.com/api/v2/public/…):
           - get_instruments?expired=true — which expired instruments the exchange still lists (measured: today's expiries only);
           - get_last_trades_by_instrument_and_time with include_old — whether old option trades are served (measured: none);
           - get_tradingview_chart_data on an EXPIRED option by its deterministic name (BTC-2JUN23-27250-C): hourly OHLCV
             (trade-based: `volume` in contracts, `cost` in the base currency; a bar without a trade carries the last price) —
             probed one daily-expiry at-the-money call and put per half-year from 2019-07 and at each fold's first day;
           - the DVOL futures (BTCDVOL_USDC-<expiry>): the listing, the daily bars, the live book;
           - a dated snapshot of the live book summary: today's one-day at-the-money straddle at the touch, and an option
             instrument's fee fields.
tardis     api.tardis.dev/v1/exchanges/deribit (coverage, keyless) and datasets.tardis.dev (the CSV files): the FIRST DAY OF EACH
           MONTH is served without a key for every data type — measured by the HTTP status and size of `options_chain`, `quotes`,
           `trades`, `book_snapshot_5` for OPTIONS on each first-of-month day of F1–F5, and the 401 text on any other day; the
           per-instrument quote file's shape (columns, updates in the first hour). The price list is a dated hand-copy (PRICES).
binance    data.binance.vision `option/daily/EOHSummary/<SYMBOL>/` (end-of-hour best bid / ask / qty, mark, IV and greeks per option,
           per hour) and `option/daily/BVOLIndex/` (the exchange's implied volatility index, one row a second): the extent per
           symbol from the S3 listing; one file of each kind downloaded for its columns; eapi.binance.com's live ticker for today's
           one-day straddle on Binance's own options market (USDT-quoted).
raw        data/raw/external/deribit/audit/*.json, data/raw/external/tardis/*.json|csv.gz, data/raw/external/binance_options/*
out        output/optsrc_audit.md, output/optsrc_audit.json (every number in the md)
"""
from __future__ import annotations

import gzip
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds

RAW_DERIBIT = data.RAW / "external" / "deribit" / "audit"
RAW_TARDIS = data.RAW / "external" / "tardis"
RAW_BINANCE = data.RAW / "external" / "binance_options"
OUT = Path("output/optsrc_audit.md")
OUT_JSON = Path("output/optsrc_audit.json")
UA = {"User-Agent": "fluxtrader2-research/1.0"}
DERIBIT = "https://www.deribit.com/api/v2/public/"
TARDIS_API = "https://api.tardis.dev/v1/exchanges/deribit"
TARDIS_CSV = "https://datasets.tardis.dev/v1/deribit"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix="
S3NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
VISION = "https://data.binance.vision/"
EAPI = "https://eapi.binance.com/eapi/v1/"
PAUSE = 0.3
CURRENCIES = ("BTC", "ETH")
STRIKE_STEPS = {"BTC": (250, 500, 1000, 2000), "ETH": (25, 50, 100, 200)}
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
# Tardis's price list as the page showed it on 2026-10-18 (tardis.dev/#pricing, docs.tardis.dev/faq/billing-and-subscriptions) —
# a hand copy, dated; USD a month. Deribit's options are in the Options, Derivatives and All-Exchanges plans; no single exchange, no
# single date range, no one-off purchase, no discount, no refund. Monthly billing serves 4 MONTHS of history; yearly billing 4 years
# (5 on invoicing); Academic (a university e-mail) is quarterly or yearly and CSV files only. Free: the first day of each month,
# every exchange and data type, no key; a free trial of one month on 10 days of data (20 GB).
PRICES = {"as_of": "2026-10-18", "plan": "Options", "monthly_usd": {"Academic": 350, "Solo": 700, "Professional": 1000, "Business": 3000},
          "history_monthly_billing": "4 months", "history_yearly_billing": "4 years (5 on invoicing)", "minimum_order_usd": 300,
          "single_exchange": False, "one_off": False, "discounts": False, "refunds": False,
          "free": "first day of each month, every data type, no key; trial: 1 month on 10 days of data, 20 GB"}


# ----------------------------------------------------------------------------- http
def _get(u: str, raw: bool = False, timeout: int = 120, retries: int = 5, head_only: bool = False):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout) as r:
                if head_only:
                    return {"status": r.status, "length": int(r.headers.get("Content-Length") or 0)}
                b = r.read()
            if raw:
                return b
            j = json.loads(b)
            if "result" in j:
                return j["result"]
            if "error" in j:
                last = j["error"]
                if isinstance(last, dict) and last.get("code") in (10020, 11050, -32602):      # unknown instrument: not a throttle
                    return {"error": last}
            else:
                return j
        except urllib.error.HTTPError as e:                                                     # noqa: PERF203
            body = e.read()[:300]
            if e.code in (401, 403, 404, 400, 429):
                return {"status": e.code, "body": body.decode(errors="ignore")}
            last = f"HTTP {e.code} {body!r}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last = e
        time.sleep(PAUSE * 2 ** i)
    raise RuntimeError(f"optsrc: {u} failed after {retries} tries: {last}")


def _save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, (bytes, bytearray)):
        path.write_bytes(obj)
    else:
        path.write_text(json.dumps(obj, indent=1, default=str))


# ----------------------------------------------------------------------------- pure helpers (tested)
def expiry_code(day: pd.Timestamp) -> str:
    """Deribit's expiry code: day without a leading zero, month in capitals, two-digit year — 2023-06-02 → 2JUN23."""
    return f"{day.day}{day.strftime('%b').upper()}{day.strftime('%y')}"


def daily_name(cur: str, expiry: pd.Timestamp, strike: int, cp: str) -> str:
    return f"{cur}-{expiry_code(expiry)}-{int(strike)}-{cp}"


def atm_candidates(cur: str, spot: float, n: int = 6) -> list[int]:
    """Strikes on the currency's grids nearest the spot, nearest first, without repeats."""
    ks = set()
    for step in STRIKE_STEPS[cur]:
        base = round(spot / step) * step
        for k in range(-2, 3):
            ks.add(int(base + k * step))
    return sorted(ks, key=lambda k: (abs(k - spot), k))[:n]


def first_of_months(a: pd.Timestamp, b: pd.Timestamp) -> list[pd.Timestamp]:
    """The first day of each month in [a, b)."""
    out, d = [], pd.Timestamp(a.year, a.month, 1, tz="UTC")
    if d < a:
        d = d + pd.offsets.MonthBegin(1)
    while d < b:
        out.append(d)
        d = d + pd.offsets.MonthBegin(1)
    return out


def chart_summary(res: dict, day_ms: int) -> dict:
    """What an hourly chart answer on an option says: bars, the bars with a trade, the 00:00 bar's open and its traded VWAP."""
    if not res or res.get("status") != "ok" or not res.get("ticks"):
        return {"served": False, "status": (res or {}).get("status") or (res or {}).get("error")}
    t = np.asarray(res["ticks"], dtype="int64")
    vol = np.asarray(res["volume"], dtype=float)
    cost = np.asarray(res["cost"], dtype=float)
    i0 = int(np.argmin(np.abs(t - day_ms)))
    h0 = slice(i0, min(i0 + 24, len(t)))
    traded = vol[h0] > 0
    return {"served": True, "bars": int(len(t)), "bars_with_a_trade": int((vol > 0).sum()), "day_bars_with_a_trade": int(traded.sum()),
            "open_00": float(res["open"][i0]), "traded_00": bool(vol[i0] > 0), "vwap_00": float(cost[i0] / vol[i0]) if vol[i0] > 0 else None,
            "day_volume": float(vol[h0].sum()), "first_bar": str(pd.Timestamp(int(t[0]), unit="ms", tz="UTC"))}


def summary_straddle(rows: list[dict], expiry_min: pd.Timestamp | None = None) -> dict | None:
    """Binance's end-of-hour rows at one hour → the at-the-money straddle of the nearest expiry at or after `expiry_min`:
    the strike whose call delta is nearest 0.5."""
    exps = {}
    for r in rows:
        code = r["symbol"].split("-")[1]
        exp = pd.Timestamp(f"20{code[:2]}-{code[2:4]}-{code[4:6]}", tz="UTC")
        if expiry_min is None or exp >= expiry_min:
            exps.setdefault(exp, []).append(r)
    if not exps:
        return None
    exp = min(exps)
    rr = exps[exp]
    calls = [r for r in rr if r["type"] == "C" and r.get("delta") not in (None, "")]
    if not calls:
        return None
    atm = min(calls, key=lambda r: abs(float(r["delta"]) - 0.5))
    puts = [r for r in rr if r["type"] == "P" and r["strike"] == atm["strike"]]
    if not puts:
        return None
    put = puts[0]
    f = lambda r, k: float(r[k]) if r.get(k) not in (None, "") else np.nan     # noqa: E731
    bid = f(atm, "best_bid_price") + f(put, "best_bid_price")
    ask = f(atm, "best_ask_price") + f(put, "best_ask_price")
    return {"expiry": str(exp.date()), "strike": float(atm["strike"].split("-")[-1]) if "-" in atm["strike"] else float(atm["strike"]),
            "call": atm["symbol"], "put": put["symbol"], "bid": bid, "ask": ask, "mid": (bid + ask) / 2, "spread": ask - bid,
            "spread_over_mid": (ask - bid) / ((bid + ask) / 2) if bid + ask > 0 else np.nan,
            "call_mark_iv": f(atm, "mark_iv"), "put_mark_iv": f(put, "mark_iv"),
            "bid_qty": min(f(atm, "best_bid_qty"), f(put, "best_bid_qty")), "ask_qty": min(f(atm, "best_ask_qty"), f(put, "best_ask_qty"))}


def book_straddle(bs: list[dict], cur: str, expiry_min: pd.Timestamp) -> dict | None:
    """Deribit's live book summary → the at-the-money straddle of the nearest expiry at or after `expiry_min` (prices in the base
    currency, as the exchange quotes them)."""
    rows = []
    for b in bs:
        m = re.match(rf"{cur}-(\d{{1,2}}[A-Z]{{3}}\d{{2}})-(\d+)-([CP])$", b["instrument_name"])
        if not m:
            continue
        exp = pd.Timestamp(pd.to_datetime(m.group(1), format="%d%b%y"), tz="UTC") + pd.Timedelta(hours=8)
        if exp >= expiry_min and b.get("underlying_price"):
            rows.append((exp, int(m.group(2)), m.group(3), b))
    if not rows:
        return None
    exp = min(r[0] for r in rows)
    rr = [r for r in rows if r[0] == exp]
    u = float(rr[0][3]["underlying_price"])
    k = min({r[1] for r in rr}, key=lambda k: abs(k - u))
    c = next((r[3] for r in rr if r[1] == k and r[2] == "C"), None)
    p = next((r[3] for r in rr if r[1] == k and r[2] == "P"), None)
    if c is None or p is None:
        return None
    g = lambda b, key: float(b[key]) if b.get(key) is not None else np.nan      # noqa: E731
    bid, ask = g(c, "bid_price") + g(p, "bid_price"), g(c, "ask_price") + g(p, "ask_price")
    return {"expiry": str(exp), "strike": k, "underlying": u, "call": c["instrument_name"], "put": p["instrument_name"], "bid": bid, "ask": ask,
            "mid": (bid + ask) / 2, "spread": ask - bid, "spread_over_mid": (ask - bid) / ((bid + ask) / 2), "mid_over_spot_pct": 100 * (bid + ask) / 2,
            "spread_over_spot_bps": 1e4 * (ask - bid), "mark_iv": g(c, "mark_iv"), "open_interest": g(c, "open_interest") + g(p, "open_interest"),
            "volume_24h": g(c, "volume") + g(p, "volume")}


# ----------------------------------------------------------------------------- deribit
def _perp_open(cur: str, day: pd.Timestamp) -> float | None:
    ms = int(day.timestamp() * 1000)
    r = _get(f"{DERIBIT}get_tradingview_chart_data?instrument_name={cur}-PERPETUAL&start_timestamp={ms}&end_timestamp={ms + 2 * 60_000}&resolution=1")
    time.sleep(PAUSE)
    return float(r["open"][0]) if isinstance(r, dict) and r.get("status") == "ok" and r.get("open") else None


def _probe_day(cur: str, day: pd.Timestamp) -> dict:
    """The daily-expiry at-the-money call and put expiring the day after `day`, as Deribit's chart endpoint serves them."""
    spot = _perp_open(cur, day)
    out = {"day": str(day.date()), "spot_00": spot}
    if spot is None:
        out["served"] = False
        return out
    expiry = day + pd.Timedelta(days=1)
    ms = int(day.timestamp() * 1000)
    for k in atm_candidates(cur, spot):
        legs = {}
        for cp in ("C", "P"):
            name = daily_name(cur, expiry, k, cp)
            r = _get(f"{DERIBIT}get_tradingview_chart_data?instrument_name={name}&start_timestamp={ms}&end_timestamp={ms + 2 * DAY_MS}&resolution=60")
            time.sleep(PAUSE)
            legs[cp] = {"name": name, **chart_summary(r if isinstance(r, dict) else {}, ms)}
        if legs["C"]["served"] and legs["P"]["served"]:
            out.update({"served": True, "strike": k, "call": legs["C"], "put": legs["P"],
                        "straddle_open_00": legs["C"]["open_00"] + legs["P"]["open_00"],
                        "straddle_open_00_over_spot_pct": 100 * (legs["C"]["open_00"] + legs["P"]["open_00"])})
            return out
        out.setdefault("tried", []).append({k: {cp: legs[cp].get("status") for cp in legs}})
    out["served"] = False
    return out


def audit_deribit(currencies=CURRENCIES, probe_days: list[pd.Timestamp] | None = None, today: pd.Timestamp | None = None) -> dict:
    today = today or pd.Timestamp.now("UTC").floor("D")
    rep = {"endpoint": DERIBIT, "as_of": str(today.date())}
    # (a) what `expired=true` lists
    for cur in currencies:
        r = _get(f"{DERIBIT}get_instruments?currency={cur}&kind=option&expired=true")
        time.sleep(PAUSE)
        exps = sorted({i["expiration_timestamp"] for i in r}) if isinstance(r, list) else []
        rep[f"expired_listed_{cur}"] = {"instruments": len(r) if isinstance(r, list) else 0,
                                        "earliest_expiry": str(pd.Timestamp(exps[0], unit="ms", tz="UTC").date()) if exps else None,
                                        "latest_expiry": str(pd.Timestamp(exps[-1], unit="ms", tz="UTC").date()) if exps else None}
        _save(RAW_DERIBIT / f"expired_{cur}_{today:%Y%m%d}.json", r)
    # (b) old trades
    s = int(pd.Timestamp("2023-06-01", tz="UTC").timestamp() * 1000)
    r = _get(f"{DERIBIT}get_last_trades_by_currency_and_time?currency=BTC&kind=option&start_timestamp={s}&end_timestamp={s + DAY_MS}&count=1000&include_old=true")
    time.sleep(PAUSE)
    rep["old_trades_2023_06_01_BTC_options"] = len(r.get("trades", [])) if isinstance(r, dict) else None
    # (c) chart history on expired daily options
    if probe_days is None:
        probe_days = [pd.Timestamp(f"{y}-{m:02d}-01", tz="UTC") for y in range(2019, today.year + 1) for m in (1, 7)]
        probe_days += [pd.Timestamp(folds.FOLDS[f][0], tz="UTC") for f in ("F0", "F1", "F2", "F3", "F4", "F5")]
        probe_days += [pd.Timestamp("2020-05-01", tz="UTC")]
        probe_days = sorted({d for d in probe_days if pd.Timestamp("2019-07-01", tz="UTC") <= d < today - pd.Timedelta(days=3)})
    probes = {cur: [_probe_day(cur, d) for d in probe_days] for cur in currencies}
    rep["chart_probes"] = probes
    _save(RAW_DERIBIT / f"chart_probes_{today:%Y%m%d}.json", probes)
    for cur in currencies:
        ok = [p for p in probes[cur] if p.get("served")]
        rep[f"chart_served_{cur}"] = {"probed": len(probes[cur]), "served": len(ok), "earliest_served": ok[0]["day"] if ok else None,
                                      "not_served": [p["day"] for p in probes[cur] if not p.get("served")],
                                      "share_of_day_bars_with_a_trade": float(np.mean([(p["call"]["day_bars_with_a_trade"] + p["put"]["day_bars_with_a_trade"]) / 48 for p in ok])) if ok else None,
                                      "straddle_00_traded_both_legs": int(sum(p["call"]["traded_00"] and p["put"]["traded_00"] for p in ok)),
                                      "straddle_open_00_over_spot_pct_median": float(np.median([p["straddle_open_00_over_spot_pct"] for p in ok])) if ok else None}
    # (d) DVOL futures
    dv = {}
    for exp in ("true", "false"):
        r = _get(f"{DERIBIT}get_instruments?currency=USDC&kind=future&expired={exp}")
        time.sleep(PAUSE)
        for i in (r if isinstance(r, list) else []):
            if "DVOL" in i["instrument_name"]:
                dv[i["instrument_name"]] = {"created": str(pd.Timestamp(i["creation_timestamp"], unit="ms", tz="UTC").date()),
                                            "expiry": str(pd.Timestamp(i["expiration_timestamp"], unit="ms", tz="UTC").date()), "live": exp == "false",
                                            "maker": i.get("maker_commission"), "taker": i.get("taker_commission"), "tick": i.get("tick_size")}
    for name, d in dv.items():
        a = int(pd.Timestamp(d["created"], tz="UTC").timestamp() * 1000)
        r = _get(f"{DERIBIT}get_tradingview_chart_data?instrument_name={name}&start_timestamp={a - DAY_MS}&end_timestamp={int(time.time() * 1000)}&resolution=1D")
        time.sleep(PAUSE)
        d["daily_bars"] = len(r.get("ticks", [])) if isinstance(r, dict) else 0
        d["volume_total"] = float(sum(r.get("volume", []))) if isinstance(r, dict) else None
        if d["live"]:
            b = _get(f"{DERIBIT}get_order_book?instrument_name={name}&depth=1")
            time.sleep(PAUSE)
            d["book"] = {k: b.get(k) for k in ("best_bid_price", "best_ask_price", "mark_price", "index_price", "open_interest")} if isinstance(b, dict) else None
    rep["dvol_futures"] = dv
    _save(RAW_DERIBIT / f"dvol_futures_{today:%Y%m%d}.json", dv)
    # (e) today's touch and the fee fields
    live = {}
    for cur in currencies:
        bs = _get(f"{DERIBIT}get_book_summary_by_currency?currency={cur}&kind=option")
        time.sleep(PAUSE)
        _save(RAW_DERIBIT / f"book_summary_{cur}_{today:%Y%m%d}.json", bs)
        st = book_straddle(bs if isinstance(bs, list) else [], cur, today + pd.Timedelta(days=1, hours=8))
        if st:
            ins = _get(f"{DERIBIT}get_instrument?instrument_name={st['call']}")
            time.sleep(PAUSE)
            st["fees"] = {k: ins.get(k) for k in ("maker_commission", "taker_commission", "block_trade_commission", "tick_size", "min_trade_amount", "settlement_period")} if isinstance(ins, dict) else None
        live[cur] = {"instruments": len(bs) if isinstance(bs, list) else 0, "straddle_next_day": st}
    rep["live"] = live
    return rep


# ----------------------------------------------------------------------------- tardis
# Sizes of the whole-market files on free days, measured 2026-10-18 from a workstation by a GET closed after the headers (the request
# itself counts against the free tier's DAILY TRANSFER LIMIT — the VM's run of 2026-10-18 learned that the hard way after ≈ 75 such
# requests whose files sum to ≈ 50 GB: HTTP 429 "This account has reached its data transfer limit", retryAfterSeconds 86287). The audit
# does not repeat them; it records them here, dated, and probes the rule with one small per-instrument file.
SIZES_MB = {"as_of": "2026-10-18", "options_chain OPTIONS 2023-05-01": 1311.3, "options_chain OPTIONS 2023-06-01": 1209.5, "options_chain OPTIONS 2024-08-01": 4503.1,
            "quotes OPTIONS 2023-06-01": 65.3, "trades OPTIONS 2023-06-01": 0.24, "book_snapshot_5 OPTIONS 2023-06-01": 175.8,
            "quotes BTC-2JUN23-27250-C 2023-06-01": 0.26, "options_chain BTC-2JUN23-27250-C 2023-06-01": 0.87, "book_snapshot_5 BTC-2JUN23-27250-C 2023-06-01": 0.46}


def audit_tardis(today: pd.Timestamp | None = None) -> dict:
    today = today or pd.Timestamp.now("UTC").floor("D")
    j = _get(TARDIS_API)
    _save(RAW_TARDIS / f"exchanges_deribit_{today:%Y%m%d}.json", j)
    sy = j.get("availableSymbols", [])
    rep = {"api": TARDIS_API, "available_since": j.get("availableSince"), "symbols": len(sy),
           "option_data_types": next((g["dataTypes"] for g in j.get("datasets", {}).get("symbols", []) if g["id"] == "OPTIONS"), None)}
    for cur in CURRENCIES:
        opt = [s for s in sy if s.get("type") == "option" and s["id"].startswith(cur + "-")]
        yrs = pd.Series([s["availableSince"][:4] for s in opt]).value_counts().sort_index()
        rep[f"option_symbols_{cur}"] = {"total": len(opt), "by_year": {str(k): int(v) for k, v in yrs.items()}}
    rep["dvol_future_symbols"] = sorted((s["id"], s["availableSince"][:10]) for s in sy if "DVOL" in s["id"])
    a, b = pd.Timestamp(folds.FOLDS["F1"][0], tz="UTC"), min(pd.Timestamp(folds.FOLDS["F5"][1], tz="UTC"), today)
    rep["free_days_F1_F5"] = [str(d.date()) for d in first_of_months(a, b)]
    nf = _get(f"{TARDIS_CSV}/options_chain/2023/06/02/OPTIONS.csv.gz", head_only=True)
    rep["not_first_of_month"] = {"status": nf.get("status"), "body": nf.get("body")}
    # one instrument's quote file on a free day: columns and cadence (≈ 0.3 MB; a 429 here is the daily limit, recorded)
    u = f"{TARDIS_CSV}/quotes/2023/06/01/BTC-2JUN23-27250-C.csv.gz"
    b = _get(u, raw=True)
    if isinstance(b, (bytes, bytearray)):
        _save(RAW_TARDIS / "quotes_2023-06-01_BTC-2JUN23-27250-C.csv.gz", b)
        q = pd.read_csv(io.BytesIO(b))
        q["ts"] = pd.to_datetime(q["timestamp"], unit="us", utc=True)
        h0 = q[q["ts"] < pd.Timestamp("2023-06-01 01:00", tz="UTC")]
        rep["quote_file_sample"] = {"instrument": "BTC-2JUN23-27250-C", "columns": list(q.columns.drop("ts")), "rows": int(len(q)), "gz_kb": round(len(b) / 1e3),
                                    "updates_in_hour_0": int(len(h0)), "first_update": str(q["ts"].iloc[0]),
                                    "first_bid_ask": [float(q["bid_price"].iloc[0]), float(q["ask_price"].iloc[0])],
                                    "spread_median_hour_0_over_mid": float(((h0["ask_price"] - h0["bid_price"]) / ((h0["ask_price"] + h0["bid_price"]) / 2)).median()) if len(h0) else None}
    else:
        rep["quote_file_sample"] = {"instrument": "BTC-2JUN23-27250-C", "status": b.get("status"), "body": b.get("body")}
    rep["sizes_mb"] = SIZES_MB
    rep["prices"] = PRICES
    return rep


# ----------------------------------------------------------------------------- binance
def _s3_list(prefix: str) -> tuple[list[str], list[tuple[str, int]]]:
    prefixes, keys, marker = [], [], None
    while True:
        x = _get(S3 + prefix + (f"&marker={marker}" if marker else ""), raw=True)
        root = ET.fromstring(x)
        prefixes += [c.find("s:Prefix", S3NS).text for c in root.findall("s:CommonPrefixes", S3NS)]
        page = [(k.find("s:Key", S3NS).text, int(k.find("s:Size", S3NS).text)) for k in root.findall("s:Contents", S3NS)]
        keys += page
        if root.find("s:IsTruncated", S3NS).text != "true" or not page:
            return prefixes, keys
        marker = page[-1][0]


def audit_binance(today: pd.Timestamp | None = None) -> dict:
    today = today or pd.Timestamp.now("UTC").floor("D")
    rep = {"archive": VISION + "data/option/daily/", "kinds": [p.split("/")[-2] for p in _s3_list("data/option/daily/")[0]]}
    for kind in ("EOHSummary", "BVOLIndex"):
        syms = [p.split("/")[-2] for p in _s3_list(f"data/option/daily/{kind}/")[0]]
        ext = {}
        for s in syms:
            _, keys = _s3_list(f"data/option/daily/{kind}/{s}/")
            zs = [k for k in keys if k[0].endswith(".zip")]
            days = sorted(re.search(r"(\d{4}-\d{2}-\d{2})", k[0]).group(1) for k in zs)
            full = pd.date_range(days[0], days[-1], freq="D") if days else []
            ext[s] = {"files": len(zs), "first": days[0] if days else None, "last": days[-1] if days else None,
                      "days_missing_inside": int(len(full) - len(days)) if days else None, "mb": round(sum(k[1] for k in zs) / 1e6, 1)}
        rep[kind] = ext
    # one file of each: columns, hours, the 1-day at-the-money straddle at hour 00
    f = "data/option/daily/EOHSummary/BTCUSDT/BTCUSDT-EOHSummary-2023-07-17.zip"
    b = _get(VISION + f, raw=True)
    _save(RAW_BINANCE / Path(f).name, b)
    z = zipfile.ZipFile(io.BytesIO(b))
    e = pd.read_csv(z.open(z.namelist()[0]), dtype=str)
    rows = e[e["hour"] == "00"].to_dict("records")
    st = summary_straddle(rows, pd.Timestamp("2023-07-18", tz="UTC"))
    rep["EOHSummary_sample"] = {"file": Path(f).name, "columns": list(e.columns), "rows": int(len(e)), "hours": int(e["hour"].nunique()), "instruments": int(e["symbol"].nunique()),
                                "expiries_at_00": sorted({s.split("-")[1] for s in e.loc[e["hour"] == "00", "symbol"]})[:6], "straddle_next_day_at_00_usdt": st}
    f = "data/option/daily/BVOLIndex/BTCBVOLUSDT/BTCBVOLUSDT-BVOLIndex-2024-06-03.zip"
    b = _get(VISION + f, raw=True)
    _save(RAW_BINANCE / Path(f).name, b)
    z = zipfile.ZipFile(io.BytesIO(b))
    v = pd.read_csv(z.open(z.namelist()[0]))
    rep["BVOLIndex_sample"] = {"file": Path(f).name, "columns": list(v.columns), "rows": int(len(v)), "cadence_s": float(pd.Series(v["calc_time"]).diff().median() / 1000),
                               "value_first": float(v["index_value"].iloc[0]), "value_min_max": [float(v["index_value"].min()), float(v["index_value"].max())]}
    # the live market today
    try:
        ei = _get(EAPI + "exchangeInfo")
        syms = ei.get("optionSymbols", [])
        tk = _get(EAPI + "ticker")
        _save(RAW_BINANCE / f"eapi_ticker_{today:%Y%m%d}.json", tk)
        live = {"option_symbols": len(syms), "underlyings": sorted({s["underlying"] for s in syms})}
        for cur in CURRENCIES:
            idx = _get(EAPI + f"index?underlying={cur}USDT").get("indexPrice")
            rows = []
            for t in tk:
                m = re.match(rf"{cur}-(\d{{6}})-(\d+)-([CP])$", t["symbol"])
                if m:
                    rows.append({"symbol": t["symbol"], "type": m.group(3), "strike": m.group(2), "best_bid_price": t["bidPrice"], "best_ask_price": t["askPrice"],
                                 "delta": None, "mark_iv": "", "best_bid_qty": "", "best_ask_qty": ""})
            exp_min = today + pd.Timedelta(days=1)
            nxt = {r["symbol"].split("-")[1] for r in rows if pd.Timestamp(f"20{r['symbol'].split('-')[1][:2]}-{r['symbol'].split('-')[1][2:4]}-{r['symbol'].split('-')[1][4:6]}", tz='UTC') >= exp_min}
            code = min(nxt) if nxt else None
            rr = [r for r in rows if code and r["symbol"].split("-")[1] == code]
            k = min({int(r["strike"]) for r in rr}, key=lambda k: abs(k - float(idx))) if rr and idx else None
            c = next((r for r in rr if int(r["strike"]) == k and r["type"] == "C"), None)
            p = next((r for r in rr if int(r["strike"]) == k and r["type"] == "P"), None)
            if c and p and idx:
                bid = float(c["best_bid_price"]) + float(p["best_bid_price"])
                ask = float(c["best_ask_price"]) + float(p["best_ask_price"])
                live[cur] = {"index": float(idx), "expiry": code, "strike": k, "bid": bid, "ask": ask, "spread_over_mid": (ask - bid) / ((ask + bid) / 2),
                             "mid_over_spot_pct": 100 * (ask + bid) / 2 / float(idx), "spread_over_spot_bps": 1e4 * (ask - bid) / float(idx)}
        rep["live"] = live
    except Exception as e:      # noqa: BLE001 — the live market is a snapshot, not a measurement the audit depends on
        rep["live"] = {"error": str(e)}
    return rep


# ----------------------------------------------------------------------------- report
def _md(rep: dict) -> str:
    L = ["# Option-price sources — the audit (decision AL1, after R54)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · every number also in `{OUT_JSON}`\n",
         "\nWhat a one-day variance product needs: the one-day straddle's price at the open of each day, the spread at the touch, the fees, a daily series over F1+F2.",
         "No series is built here; no fold is read. The cost read is its own registration, written against DATA.md's sections from this audit.\n"]
    d = rep.get("deribit")
    if d:
        L += ["\n## Deribit — the public, keyless API\n"]
        curs = [c for c in CURRENCIES if f"expired_listed_{c}" in d]
        for cur in curs:
            e = d[f"expired_listed_{cur}"]
            L.append(f"- `get_instruments expired=true` {cur} options: {e['instruments']} instruments, expiries {e['earliest_expiry']} → {e['latest_expiry']} — the exchange lists only what expired today.")
        L.append(f"- `get_last_trades_by_currency_and_time` with `include_old`, BTC options on 2023-06-01: {d['old_trades_2023_06_01_BTC_options']} trades — old option trades are not served.")
        for cur in curs:
            c = d[f"chart_served_{cur}"]
            L.append(f"- `get_tradingview_chart_data` on EXPIRED daily options by their name, {cur}: served on {c['served']} of {c['probed']} probe days (earliest {c['earliest_served']}; not served: {c['not_served'] or 'none'}); "
                     f"hourly bars, trade-based — on the probe days {c['share_of_day_bars_with_a_trade']:.0%} of a leg's 24 bars hold a trade, the 00:00 bar holds a trade on both legs on {c['straddle_00_traded_both_legs']} of {c['served']} days (a bar without a trade carries the last price); "
                     f"the straddle's 00:00 price, median {c['straddle_open_00_over_spot_pct_median']:.2f} % of spot.")
        L.append("\n| probe day | spot 00:00 | strike | call 00:00 | put 00:00 | straddle % spot | day bars with a trade (C+P of 48) |\n|---|---|---|---|---|---|---|")
        for cur in curs:
            for p in d["chart_probes"][cur]:
                if p.get("served"):
                    L.append(f"| {cur} {p['day']} | {p['spot_00']:.0f} | {p['strike']} | {p['call']['open_00']} | {p['put']['open_00']} | {p['straddle_open_00_over_spot_pct']:.2f} | {p['call']['day_bars_with_a_trade'] + p['put']['day_bars_with_a_trade']} |")
                else:
                    L.append(f"| {cur} {p['day']} | {p.get('spot_00') or '—'} | — | not served | | | |")
        dv = d["dvol_futures"]
        L.append(f"\n- DVOL futures (USDC-settled, `BTCDVOL_USDC-<expiry>`): {len(dv)} listed by the API ({sum(v['live'] for v in dv.values())} live); "
                 + "; ".join(f"{k} created {v['created']} exp {v['expiry']} daily bars {v['daily_bars']} volume {v['volume_total']}" + (f" book {v['book']}" if v.get('book') else "") for k, v in dv.items()))
        for cur in curs:
            s = d["live"][cur]["straddle_next_day"]
            if s:
                L.append(f"- live {d['as_of']} {cur}: {d['live'][cur]['instruments']} options quoted; the next-day at-the-money straddle {s['call']} + {s['put']}: bid {s['bid']:.4f} / ask {s['ask']:.4f} {cur} "
                         f"(mid {s['mid_over_spot_pct']:.2f} % of spot, spread {s['spread_over_spot_bps']:.0f} bps of spot = {s['spread_over_mid']:.0%} of the mid), mark IV {s['mark_iv']}, OI {s['open_interest']}, 24h volume {s['volume_24h']}; "
                         f"fee fields {s.get('fees')}")
    t = rep.get("tardis")
    if t:
        L += ["\n## Tardis — Deribit's full history, paid; the first day of each month free\n",
              f"- coverage API: Deribit since {t['available_since']}, {t['symbols']:,} symbols; option data types {t['option_data_types']}.",
              "- option symbols by the year they start: " + "; ".join(f"{cur} {t[f'option_symbols_{cur}']['total']:,} ({', '.join(f'{k} {v:,}' for k, v in t[f'option_symbols_{cur}']['by_year'].items())})" for cur in CURRENCIES) + ".",
              f"- DVOL futures symbols: {len(t['dvol_future_symbols'])}, first {t['dvol_future_symbols'][0] if t['dvol_future_symbols'] else None}.",
              f"- any day but the first of a month: HTTP {t['not_first_of_month']['status']} — `{(t['not_first_of_month'].get('body') or '')[:160]}`",
              f"- the free days inside F1–F5: {len(t['free_days_F1_F5'])} ({t['free_days_F1_F5'][0]} … {t['free_days_F1_F5'][-1]}); the files on them, sizes measured {t['sizes_mb']['as_of']} (MB): "
              + "; ".join(f"{k} {v}" for k, v in t['sizes_mb'].items() if k != 'as_of') + ". The free tier has a DAILY transfer limit (HTTP 429, retry after a day); the whole-market files count against it on request."]
        q = t.get("quote_file_sample")
        if q and "status" in q:
            L.append(f"- one instrument's `quotes` file on a free day ({q['instrument']}): HTTP {q['status']} — `{(q.get('body') or '')[:160]}` (the day's limit was spent by the first run's size probes).")
        elif q:
            L.append(f"\n- one instrument's `quotes` file on a free day ({q['instrument']}, 2023-06-01): columns {q['columns']}, {q['rows']:,} rows ({q['gz_kb']} KB gz), {q['updates_in_hour_0']:,} updates in hour 0, "
                     f"first update {q['first_update']} bid/ask {q['first_bid_ask']}, the median spread over the mid in hour 0 {q['spread_median_hour_0_over_mid']:.1%}.")
        p = t["prices"]
        L.append(f"- price list ({p['as_of']}, hand copy): the {p['plan']} plan {p['monthly_usd']} USD a month; monthly billing serves {p['history_monthly_billing']} of history, yearly {p['history_yearly_billing']}; "
                 f"minimum order {p['minimum_order_usd']}; single exchange {p['single_exchange']}, one-off {p['one_off']}, discounts {p['discounts']}, refunds {p['refunds']}; free: {p['free']}.")
    b = rep.get("binance")
    if b:
        L += ["\n## Binance — the options market's archive and live quotes\n", f"- `{b['archive']}` holds {b['kinds']} and nothing else."]
        for kind in ("EOHSummary", "BVOLIndex"):
            L.append(f"- {kind}: " + "; ".join(f"{s} {v['first']} → {v['last']} ({v['files']} files, {v['days_missing_inside']} missing inside, {v['mb']} MB)" for s, v in b[kind].items()))
        e = b["EOHSummary_sample"]
        L.append(f"- EOHSummary file ({e['file']}): {e['rows']:,} rows, {e['hours']} hours, {e['instruments']} instruments, columns {e['columns']}; at hour 00 the next-day at-the-money straddle (USDT): {e['straddle_next_day_at_00_usdt']}")
        v = b["BVOLIndex_sample"]
        L.append(f"- BVOLIndex file ({v['file']}): {v['rows']:,} rows, one every {v['cadence_s']} s, columns {v['columns']}, value {v['value_first']} (day range {v['value_min_max']}).")
        L.append(f"- live eapi.binance.com: {b.get('live')}")
    return "\n".join(L) + "\n"


def audit(sources=("deribit", "tardis", "binance"), today: pd.Timestamp | None = None) -> str:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rep = json.loads(OUT_JSON.read_text()) if OUT_JSON.exists() else {}
    fn = {"deribit": lambda: audit_deribit(today=today), "tardis": lambda: audit_tardis(today=today), "binance": lambda: audit_binance(today=today)}
    for src in sources:
        rep[src] = fn[src]()
        OUT_JSON.write_text(json.dumps(rep, indent=1, default=str))
        print(f"optsrc: {src} done", flush=True)
    txt = _md(rep)
    OUT.write_text(txt)
    return txt


def main(action: str, sources=None) -> None:
    if action == "audit":
        print(audit(tuple(sources) if sources else ("deribit", "tardis", "binance")))
    else:
        sys.exit(f"optsrc: unknown action {action}")
