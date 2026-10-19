"""Decision AQ2 (PLAN P8 decision AQ, DECIDED 2026-10-19; a DESCRIBED row in AA5's form — no registration, no gate, no verdict): the
variance premium at a MONTHLY tenor on BTC and ETH — the at-the-money straddle sold in the first hour after the previous monthly
expiry, delta-hedged daily (the primary row) and hourly (beside) at the project's hedge costs, settled at expiry, at Deribit's trade
prices; per month gross and net in bps of spot, by year and by fold. `ft2 varmonth fetch|run`.

fetch   for each monthly expiry E (Deribit's last Friday of the month, 08:00 UTC) with a previous expiry E₋₁: ONE call for the
        perpetual's hourly bars over [E₋₁ 08:00, E) (the close of the bar ending at H is the price at H: the spot at the entry
        09:00 UTC of E₋₁'s Friday, the hedge's hourly closes), one for the perpetual's 1-minute bars over E's 07:30 → 08:00 (the
        settlement TWAP, R55's stand-in for the delivery price), then the call and put `<CUR>-<E>-<K>-C/P` at the strike nearest the
        spot on the currency's grid (nearest first until both legs are served) as hourly bars over [E₋₁ − 24 h, E). One JSON a
        month a name under data/raw/external/deribit/varmonth/<CUR>/<E>.json; resumable; two names in parallel, paced.
run     the rows: the entry at 09:00 of E₋₁'s Friday — each leg at the close of its last hourly bar with a trade ending at or
        before 09:00 (R55's rule), screened by put–call parity within PARITY_TOL of spot and the legs traded within the 24 h before;
        m = C + P in units of spot; σ_q = m / (0.8 √T) the straddle's own break-even vol; the Black–Scholes delta at σ_q hedged at
        every 24th hourly close (daily, 08:00 UTC) and at every close (hourly), the hedge trades at TAKER_BPS + half the name's
        calibrated spread (the month's median of `cost_daily`, the name's median where the month is absent), unwound at the
        settlement; the crossing = half the touch of the front monthly at-the-money straddle in today's live book (one constant a
        name, measured at the run and recorded; a 2 × touch sensitivity beside; R55's constants if the book cannot be read); the
        fees 0.03 % of spot a leg at entry and 0.015 % at delivery, each capped at 12.5 % of the leg's premium. Per month: the
        short's gross = m − |S_T − K| / S − the long hedge's PnL, the net = the gross less the costs; σ_q against the month's
        realised vol; the tables by year 2020 → 2026 and by fold, the mean with a Newey–West se (1 lag) over months and its t, the
        worst month, the share of losing months, the drawdown of the summed series; the unhedged short beside.
out     output/varmonth/<name>/varmonth.md, months.csv, tables.csv, validity.json
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds, optsrc, straddle, varbook

RAW = data.RAW / "external" / "deribit" / "varmonth"
OUT = Path("output/varmonth")
NAMES = straddle.NAMES
FIRST = {"BTC": pd.Timestamp("2020-05-01", tz="UTC"), "ETH": pd.Timestamp("2020-07-01", tz="UTC")}   # the audit: served from here
EXPIRY_H = 8                       # the last Friday's 08:00 UTC
ENTRY_H = 1                        # the entry one hour after the previous expiry: 09:00 UTC
PARITY_TOL = 0.01                  # |C − P − (S − K) / S| in units of spot (a monthly straddle is ≈ 10 % of spot)
SETTLE_MIN = 25
TOUCH_FALLBACK_BPS = {"BTC": 13.0, "ETH": 20.0}      # R55's live-book touch of the daily straddle, used only if the book cannot be read
REBALANCE = {"daily": 24, "hourly": 1}
HOUR_MS, MIN_MS = 3_600_000, 60_000
BS_FACTOR, TAKER_BPS = varbook.BS_FACTOR, varbook.TAKER_BPS
FEE_ENTRY, FEE_DELIVERY, FEE_CAP = varbook.FEE_ENTRY, varbook.FEE_DELIVERY, varbook.FEE_CAP


# ---- the calendar --------------------------------------------------------------------------------------------------------
def last_friday(year: int, month: int) -> pd.Timestamp:
    d = pd.Timestamp(year, month, 1, tz="UTC") + pd.offsets.MonthEnd(0)
    d = d - pd.Timedelta(days=(d.dayofweek - 4) % 7)
    return d.normalize() + pd.Timedelta(hours=EXPIRY_H)


def monthly_expiries(a: pd.Timestamp, b: pd.Timestamp) -> list[pd.Timestamp]:
    """The monthly expiries (the last Friday of each month, 08:00 UTC) in [a, b]."""
    out, y, m = [], a.year, a.month
    while True:
        e = last_friday(y, m)
        if e > b:
            break
        if e >= a:
            out.append(e)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_pairs(cur: str, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(E₋₁, E) for every expiry E whose previous expiry is at or after the name's first served month and E ≤ end."""
    ex = monthly_expiries(FIRST[cur], end)
    return list(zip(ex[:-1], ex[1:]))


# ---- fetch ---------------------------------------------------------------------------------------------------------------
def fetch_month(cur: str, e_prev: pd.Timestamp, e: pd.Timestamp) -> dict:
    t0 = e_prev + pd.Timedelta(hours=ENTRY_H)
    ms0, mse = int(e_prev.timestamp() * 1000), int(e.timestamp() * 1000)
    perp = straddle._chart(f"{cur}-PERPETUAL", ms0 - HOUR_MS, mse, "60")
    out = {"currency": cur, "expiry": str(e), "prev_expiry": str(e_prev), "entry": str(t0), "perp_1h": perp if straddle._served(perp) else None,
           "settle_1m": None, "legs": None, "tried": []}
    if not straddle._served(perp):
        return out
    settle = straddle._chart(f"{cur}-PERPETUAL", mse - 30 * MIN_MS, mse - MIN_MS, "1")
    out["settle_1m"] = settle if straddle._served(settle) else None
    t = np.asarray(perp["ticks"], dtype="int64")
    i0 = np.flatnonzero(t == int(t0.timestamp() * 1000) - HOUR_MS)       # the bar ending at the entry hour
    spot = float(perp["close"][int(i0[0])]) if len(i0) else None
    out["spot"] = spot
    if spot is None:
        return out
    for k in optsrc.atm_candidates(cur, spot):
        legs = {}
        for cp in ("C", "P"):
            name = optsrc.daily_name(cur, e.normalize(), k, cp)
            legs[cp] = {"name": name, "chart": straddle._chart(name, ms0 - 24 * HOUR_MS, mse, "60")}
        if straddle._served(legs["C"]["chart"]) and straddle._served(legs["P"]["chart"]):
            out["strike"], out["legs"] = k, legs
            return out
        out["tried"].append({str(k): {cp: legs[cp]["chart"].get("status") or legs[cp]["chart"].get("error") for cp in legs}})
    return out


def fetch(currencies=tuple(NAMES), end: str | None = None) -> dict:
    now = pd.Timestamp.now(tz="UTC")
    b = pd.Timestamp(end, tz="UTC") if end else now - pd.Timedelta(days=1)

    def one(cur):
        n_new = 0
        for e_prev, e in month_pairs(cur, b):
            dest = RAW / cur / f"{e:%Y-%m-%d}.json"
            if dest.exists():
                continue
            optsrc._save(dest, fetch_month(cur, e_prev, e))
            n_new += 1
            if n_new % 10 == 0:
                print(f"varmonth fetch {cur}: {e:%Y-%m-%d} ({n_new} new)", flush=True)
        return n_new

    with ThreadPoolExecutor(max_workers=len(currencies)) as ex:
        res = dict(zip(currencies, ex.map(one, currencies)))
    print(f"varmonth fetch: {res} new month files", flush=True)
    return res


def live_touch(currencies=tuple(NAMES), today: pd.Timestamp | None = None) -> dict:
    """The front monthly at-the-money straddle's touch in today's live book, bps of spot, per name; the fallback where unread."""
    today = pd.Timestamp.now(tz="UTC") if today is None else today
    out = {}
    for cur in currencies:
        try:
            bs = optsrc._get(f"{optsrc.DERIBIT}get_book_summary_by_currency?currency={cur}&kind=option")
            time.sleep(optsrc.PAUSE)
            nxt = monthly_expiries(today + pd.Timedelta(days=7), today + pd.Timedelta(days=45))
            st = optsrc.book_straddle(bs if isinstance(bs, list) else [], cur, nxt[0]) if nxt else None
        except Exception as exc:            # noqa: BLE001 — a network failure is recorded, not fatal
            st = {"error": str(exc)}
        ok = bool(st) and np.isfinite(st.get("spread_over_spot_bps", np.nan))
        out[cur] = {"touch_bps": float(st["spread_over_spot_bps"]) if ok else TOUCH_FALLBACK_BPS[cur], "measured": ok, "book": st}
    return out


# ---- the pricing ---------------------------------------------------------------------------------------------------------
def month_row(j: dict) -> tuple[dict, np.ndarray | None]:
    cur = j["currency"]
    e, t0 = pd.Timestamp(j["expiry"]), pd.Timestamp(j["entry"])
    row = {"currency": cur, "symbol": NAMES[cur], "expiry": e, "entry": t0, "spot": j.get("spot"), "strike": j.get("strike"), "covered": False, "skip": None}
    if not j.get("perp_1h"):
        row["skip"] = "no perpetual bars"
        return row, None
    n = int((e - t0) / pd.Timedelta(hours=1))
    t = np.asarray(j["perp_1h"]["ticks"], dtype="int64")
    c = np.asarray(j["perp_1h"]["close"], dtype=float)
    pos = {int(x): i for i, x in enumerate(t)}
    ms0 = int(t0.timestamp() * 1000)
    path = np.full(n + 1, np.nan)
    for i in range(n):
        k = ms0 + i * HOUR_MS - HOUR_MS
        if k in pos:
            path[i] = c[pos[k]]
    row["path_missing"] = int(np.isnan(path[:n]).sum())
    if j.get("settle_1m"):
        sc = np.asarray(j["settle_1m"]["close"], dtype=float)
        row["settle_bars"] = int(len(sc))
        path[n] = float(sc.mean()) if len(sc) >= SETTLE_MIN else np.nan
    else:
        row["settle_bars"] = 0
    row["hours"] = n
    if not j.get("legs"):
        row["skip"] = "no served pair"
        return row, None
    for cp, key in (("C", "c"), ("P", "p")):
        px, ts, n24 = straddle.last_trade_before(j["legs"][cp]["chart"], ms0)
        row[{"C": "call", "P": "put"}[cp]] = j["legs"][cp]["name"]
        row.update({f"{key}_last": px, f"{key}_last_ts": pd.Timestamp(ts, unit="ms", tz="UTC") if ts else pd.NaT, f"{key}_trades_24h": n24})
    s, k = row["spot"], row["strike"]
    if row["c_last"] is None or row["p_last"] is None or row["c_trades_24h"] == 0 or row["p_trades_24h"] == 0:
        row["skip"] = "a leg without a trade in the 24 h before"
    else:
        row["parity"] = row["c_last"] - row["p_last"] - (s - k) / s
        if abs(row["parity"]) > PARITY_TOL:
            row["skip"] = "parity"
        elif row["path_missing"] > 0:
            row["skip"] = "perpetual path incomplete"
        elif not np.isfinite(path[n]):
            row["skip"] = "settlement window short"
        else:
            row["covered"] = True
    return row, (path if row["covered"] else None)


def hedge_short(path: np.ndarray, k: float, sigma: float, cost_frac: float, every: int) -> tuple[float, float, float]:
    """A SHORT straddle hedged with +Δ units of the underlying at every `every`-th hourly close (path[0 … n−1]) and unwound at the
    settlement (path[n]); returns (the hedge's PnL, its crossing cost, the units traded), in units of spot (path[0])."""
    n = len(path) - 1
    s0 = path[0]
    hours_left = n - np.arange(n)
    delta = varbook.straddle_delta(path[:n], k, sigma, hours_left)
    pos = np.full(n, np.nan)
    for i in range(0, n, every):
        pos[i: i + every] = delta[i]
    pnl = float(np.sum(pos * np.diff(path)) / s0)
    trades = np.abs(np.diff(np.concatenate([[0.0], pos[::every], [0.0]])))
    px = np.concatenate([path[:n:every], path[-1:]])
    cost = float(np.sum(trades * px / s0) * cost_frac)
    return pnl, cost, float(trades.sum())


def price_month(path: np.ndarray, k: float, c_px: float, p_px: float, half_spread_bps: float, touch_bps: float) -> dict:
    """One month, the short straddle: the gross, the costs and the net in bps of spot for the daily and the hourly hedge and unhedged."""
    s0, n = path[0], len(path) - 1
    m = c_px + p_px
    T = varbook.tenor_years(n)
    sig_q = m / (BS_FACTOR * np.sqrt(T))
    payoff = abs(path[-1] - k) / s0
    lr = np.diff(np.log(path[:n]))
    rv = float(np.std(lr) * np.sqrt(8760.0)) if n > 2 else np.nan
    fee_entry = sum(min(FEE_ENTRY, FEE_CAP * px) for px in (c_px, p_px))
    fee_deliv = sum(min(FEE_DELIVERY, FEE_CAP * px) for px in (c_px, p_px))
    crossing = touch_bps / 2 / 1e4
    out = {"m": m, "m_pct": 100 * m, "sigma_q": sig_q, "rv_month": rv, "payoff": payoff, "hours": n, "fee_entry_bps": 1e4 * fee_entry,
           "fee_delivery_bps": 1e4 * fee_deliv, "crossing_bps": 1e4 * crossing, "gross_unhedged": 1e4 * (m - payoff)}
    out["net_unhedged"] = out["gross_unhedged"] - 1e4 * (crossing + fee_entry + fee_deliv)
    for lab, every in REBALANCE.items():
        pnl, cost, units = hedge_short(path, k, sig_q, half_spread_bps / 1e4, every)
        gross = m - payoff + pnl
        out[f"hedge_pnl_{lab}"], out[f"hedge_cost_{lab}"], out[f"hedge_units_{lab}"] = 1e4 * pnl, 1e4 * cost, units
        out[f"gross_{lab}"] = 1e4 * gross
        out[f"net_{lab}"] = 1e4 * (gross - cost - crossing - fee_entry - fee_deliv)
        out[f"net_{lab}_2x"] = out[f"net_{lab}"] - 1e4 * crossing
    return out


def _fold(t: pd.Timestamp) -> str:
    for n, (a, b) in folds.FOLDS.items():
        if pd.Timestamp(a, tz="UTC") <= t < pd.Timestamp(b, tz="UTC"):
            return n
    return "pre" if t < pd.Timestamp(folds.FOLDS["FP"][0], tz="UTC") else "post"


def _table(g: pd.DataFrame, col: str) -> dict:
    x = g[col].to_numpy(dtype=float)
    mean, se, t = varbook.nw(x, lags=1)
    cum = np.cumsum(x)
    dd = float((cum - np.maximum.accumulate(cum)).min()) if len(x) else np.nan
    return {"months": int(len(x)), "mean": mean, "se": se, "t": t, "worst": float(x.min()) if len(x) else np.nan,
            "losing": float((x < 0).mean()) if len(x) else np.nan, "sum": float(x.sum()), "drawdown": dd}


def run(name: str = "all", currencies=tuple(NAMES), touch: dict | None = None) -> str:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    touch = live_touch(currencies) if touch is None else touch
    costs = varbook.costs_table()
    rows, skips = [], {}
    for cur in currencies:
        files = sorted((RAW / cur).glob("*.json")) if (RAW / cur).exists() else []
        for f in files:
            j = json.loads(f.read_text())
            row, path = month_row(j)
            if not row["covered"]:
                skips.setdefault(cur, {}).setdefault(row["skip"], 0)
                skips[cur][row["skip"]] += 1
                rows.append(row)
                continue
            sym = NAMES[cur]
            hs = TAKER_BPS
            if costs is not None:
                cc = costs[(costs["symbol"] == sym) & (costs["day"] >= row["entry"].floor("D")) & (costs["day"] < row["expiry"])]
                sp = float(cc["spread_cal_bps"].median()) if len(cc) else float(costs.loc[costs["symbol"] == sym, "spread_cal_bps"].median())
                hs = TAKER_BPS + sp / 2
            row.update({"half_spread_bps": hs, "touch_bps": touch[cur]["touch_bps"]})
            row.update(price_month(path, row["strike"], row["c_last"], row["p_last"], hs, touch[cur]["touch_bps"]))
            row["year"], row["fold"] = row["entry"].year, _fold(row["entry"])
            rows.append(row)
    months = pd.DataFrame(rows)
    months.to_csv(out / "months.csv", index=False)
    cov = months[months["covered"]] if len(months) else months
    tabs = []
    cols = ["net_daily", "gross_daily", "net_hourly", "gross_hourly", "net_unhedged", "gross_unhedged", "net_daily_2x"]
    for cur, g in cov.groupby("currency"):
        for scope, gg in [("all", g)] + [(f"year {y}", h) for y, h in g.groupby("year")] + [(f"fold {f}", h) for f, h in g.groupby("fold")]:
            for col in cols:
                tabs.append({"currency": cur, "scope": scope, "row": col, **_table(gg, col)})
    tables = pd.DataFrame(tabs)
    tables.to_csv(out / "tables.csv", index=False)
    validity = {"months_asked": {cur: int((months["currency"] == cur).sum()) for cur in currencies} if len(months) else {},
                "covered": {cur: int(((months["currency"] == cur) & months["covered"]).sum()) for cur in currencies} if len(months) else {},
                "skips": skips, "touch": {cur: {k: v for k, v in touch[cur].items() if k != "book"} for cur in touch},
                "parity_abs_median": {cur: float(g["parity"].abs().median()) for cur, g in cov.groupby("currency")} if len(cov) else {},
                "path_missing_max": int(months["path_missing"].max()) if "path_missing" in months and len(months) else None,
                "costs_table": costs is not None}
    (out / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    md = _md(name, cov, tables, validity)
    (out / "varmonth.md").write_text(md)
    return md


def _md(name: str, cov: pd.DataFrame, tables: pd.DataFrame, v: dict) -> str:
    L = [f"# varmonth — the variance premium at a monthly tenor, a described row (`{name}`)", "",
         "The at-the-money straddle SOLD at 09:00 UTC of the previous monthly expiry's Friday, held to the last Friday's 08:00 settlement, the Black–Scholes "
         "delta at its own break-even vol hedged daily (primary) and hourly at the project's taker cost, the touch from today's live book, Deribit's fees. "
         "bps of spot a month. No gate, no verdict.", "",
         f"Months asked {v['months_asked']}, covered {v['covered']}, skipped {v['skips']}; the touch {v['touch']}; |parity| median {v['parity_abs_median']}.", ""]
    for cur, g in cov.groupby("currency"):
        L += [f"## {cur}", "", "| scope | row | months | mean | se (NW 1) | t | worst | losing | sum | drawdown |", "|---|---|---|---|---|---|---|---|---|---|"]
        tt = tables[tables["currency"] == cur]
        for _, r in tt.iterrows():
            L.append(f"| {r['scope']} | {r['row']} | {r['months']} | {r['mean']:+.1f} | {r['se']:.1f} | {r['t']:.2f} | {r['worst']:+.0f} | {r['losing']:.2f} | {r['sum']:+.0f} | {r['drawdown']:+.0f} |")
        L += ["", "| expiry | fold | spot | K | m % | σ_q | rv | gross daily | hedge cost | crossing | fees | net daily | net hourly | net unhedged |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in g.sort_values("expiry").iterrows():
            L.append(f"| {r['expiry']:%Y-%m-%d} | {r['fold']} | {r['spot']:.0f} | {r['strike']:.0f} | {r['m_pct']:.2f} | {r['sigma_q']:.3f} | {r['rv_month']:.3f} | "
                     f"{r['gross_daily']:+.0f} | {r['hedge_cost_daily']:.1f} | {r['crossing_bps']:.1f} | {r['fee_entry_bps'] + r['fee_delivery_bps']:.1f} | "
                     f"{r['net_daily']:+.0f} | {r['net_hourly']:+.0f} | {r['net_unhedged']:+.0f} |")
        L.append("")
    return "\n".join(L) + "\n"


def main(action: str, currencies=None, end=None, name: str = "all") -> None:
    cur = tuple(currencies) if currencies else tuple(NAMES)
    if action == "fetch":
        fetch(cur, end=end)
    elif action == "run":
        print(run(name, cur))
    else:
        sys.exit(f"varmonth: unknown action {action}")
