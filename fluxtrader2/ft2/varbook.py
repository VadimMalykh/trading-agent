"""R55 (PLAN §8; decision AM1) — varbook: the one-day variance position on BTC and ETH, signed by R54's forecast against the straddle's
own implied, delta-hedged hourly, settled at expiry, at Deribit's prices and the project's hedge costs — does it pay? `ft2 varbook`.

inputs     data/straddle_1d.parquet, data/straddle_hedge.parquet, data/straddle_touch.parquet (`ft2 straddle`, DATA.md `straddle_1d`);
           output/magvol/f12/loss.csv — R54's per-day forecasts, column `yhat_I+C` at hold 1 (sha256 recorded; no refit);
           data/cost_daily.parquet — the calibrated spread per name and day (the hedge's half-spread beside the taker fee).
entry      at 00:00 of d: each leg at its last traded price before 00:00 (ingest), m = C + P in units of spot; the crossing = half the
           straddle's touch spread (ONE constant a name: the median over the free days, bps of spot); fees 0.03 % of spot a leg at
           entry and 0.015 % a leg at delivery, each capped at 12.5 % of the leg's premium.
sign       σ_q = m / (0.8 √(32 / 8760)) — the straddle's break-even volatility; RV̂ = exp(ŷ_{I+C}) / 100; LONG if log RV̂ > log σ_q.
hedge      the Black–Scholes delta of the straddle at σ_q and the hours left, at each hourly close 00:00 … 07:00 of d + 1 (32 hedges),
           the hedge trades (the changes in delta, the unwind at settlement) at the taker cost TAKER_BPS + half the day's calibrated spread.
pnl        bps of spot a straddle: sign × [ |S_T − K| / S − m + hedge PnL ] − crossing − fees − hedge crossings.
read       per name: the net and the gross (mean, Newey–West se with 2 lags, t, per fold); the costs; the hit rate; always-short /
           always-long, unhedged, and R54's I-alone / C-alone signs described; the family = the two hedged I + C rows, t ≥ 1.96.
out        output/varbook/<name>/varbook.md, rows.csv, days.csv, costs.csv, validity.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import folds, straddle

OUT = Path("output/varbook")
MAGVOL_LOSS = Path("output/magvol/f12/loss.csv")
COST_DAILY = Path("data/cost_daily.parquet")
TAKER_BPS = 5.0                  # makercost.TAKER_BPS — Binance's taker fee, the project's number
FEE_ENTRY = 0.0003               # Deribit: 0.03 % of the underlying a contract, a leg
FEE_DELIVERY = 0.00015           # 0.015 % a leg (the third-party figure, taken as written)
FEE_CAP = 0.125                  # of the leg's premium
BS_FACTOR = 0.8                  # the at-the-money straddle ≈ 0.8 σ √T S
T_BAR = 1.96                     # one-sided, a family of two at 5 %
NW_LAGS = 2
COVER_VOID, COVER_FULL = 0.5, 0.8
FORECASTS = {"I+C": "yhat_I+C", "I": "yhat_I", "C": "yhat_C"}


def tenor_years(hours: float) -> float:
    return hours / 8760.0


def breakeven_vol(m: float) -> float:
    return m / (BS_FACTOR * np.sqrt(tenor_years(straddle.TENOR_H)))


def straddle_delta(s: np.ndarray, k: float, sigma: float, hours_left: np.ndarray) -> np.ndarray:
    """Black–Scholes (r = 0) delta of a long straddle: 2 N(d1) − 1; zero time left → the sign of S − K."""
    s, h = np.asarray(s, dtype=float), np.asarray(hours_left, dtype=float)
    out = np.sign(s - k).astype(float)
    pos = h > 0
    tau = tenor_years(h[pos])
    d1 = (np.log(s[pos] / k) + 0.5 * sigma ** 2 * tau) / (sigma * np.sqrt(tau))
    out[pos] = 2 * norm.cdf(d1) - 1
    return out


def hedge_leg(path: np.ndarray, k: float, sigma: float, cost_frac: float) -> tuple[float, float, float]:
    """A LONG straddle hedged with −Δ units of the underlying, Δ recomputed at the 32 hourly closes (path[0..31]) and unwound at the
    settlement (path[32]); returns (hedge PnL, hedge crossing cost, units traded), all in units of spot (path[0])."""
    s0 = path[0]
    hours_left = straddle.TENOR_H - np.arange(straddle.TENOR_H)
    delta = straddle_delta(path[:straddle.TENOR_H], k, sigma, hours_left)
    pos = -delta
    pnl = float(np.sum(pos * np.diff(path)) / s0)
    trades = np.abs(np.diff(np.concatenate([[0.0], pos, [0.0]])))               # the entry, the 31 changes, the unwind
    px = np.concatenate([path[:straddle.TENOR_H], path[-1:]])
    cost = float(np.sum(trades * px / s0) * cost_frac)
    return pnl, cost, float(trades.sum())


def nw(x: np.ndarray, lags: int = NW_LAGS) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 3:
        return float(np.mean(x)) if n else np.nan, np.nan, np.nan
    e = x - x.mean()
    v = float(e @ e) / n
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        v += 2 * w * float(e[L:] @ e[:-L]) / n
    se = np.sqrt(max(v, 0) / n)
    return float(x.mean()), float(se), float(x.mean() / se) if se > 0 else np.nan


def verdict(mean: float, se: float, t: float, f1: float, f2: float, gross_t: float) -> str:
    if mean > 0 and t >= T_BAR and f1 > 0 and f2 > 0:
        return "FUNDED"
    if gross_t >= T_BAR:
        return "REAL, NOT FUNDED"
    if mean + 1.96 * se < 0:
        return "CLOSED"
    return "NOT DETECTABLE"


def load_forecasts(path: Path = MAGVOL_LOSS) -> tuple[pd.DataFrame, str]:
    raw = path.read_bytes()
    f = pd.read_csv(io_bytes(raw))
    f = f[f["hold_days"] == 1].copy()
    f["day"] = pd.to_datetime(f["day"], utc=True)
    return f, hashlib.sha256(raw).hexdigest()


def io_bytes(b: bytes):
    import io
    return io.BytesIO(b)


def costs_table(path: Path = COST_DAILY) -> pd.DataFrame | None:
    if not path.exists():
        return None
    c = pd.read_parquet(path)[["symbol", "day", "spread_cal_bps"]]
    c["day"] = pd.to_datetime(c["day"], utc=True)
    return c


def price_days(d: pd.DataFrame, hedge: pd.DataFrame, fc: pd.DataFrame, touch_bps: dict, costs: pd.DataFrame | None) -> pd.DataFrame:
    """Every covered day with a forecast: the entry, the sign under each forecast, the hedged and unhedged PnL and the costs (bps of spot)."""
    H = {(r.currency, r.day): None for r in d.itertuples()}
    hp = hedge.sort_values(["currency", "day", "i"]).groupby(["currency", "day"])["price"].apply(np.asarray)
    rows = []
    for r in d[d["covered"]].itertuples():
        sym = straddle.NAMES[r.currency]
        f = fc[(fc["symbol"] == sym) & (fc["day"] == r.day)]
        if not len(f) or (r.currency, r.day) not in hp.index:
            continue
        f = f.iloc[0]
        path = hp.loc[(r.currency, r.day)]
        if len(path) != straddle.TENOR_H + 1 or np.isnan(path).any():
            continue
        s0, k = r.spot_00, r.strike
        m = r.c_last + r.p_last
        sig_q = breakeven_vol(m)
        half_spread = TAKER_BPS
        if costs is not None:
            cc = costs[(costs["symbol"] == sym) & (costs["day"] == r.day)]
            sp = float(cc["spread_cal_bps"].iloc[0]) if len(cc) else float(costs.loc[costs["symbol"] == sym, "spread_cal_bps"].median())
            half_spread = TAKER_BPS + sp / 2
        hedge_pnl, hedge_cost, units = hedge_leg(path, k, sig_q, half_spread / 1e4)
        payoff = abs(path[-1] - k) / s0
        fee_entry = sum(min(FEE_ENTRY, FEE_CAP * px) for px in (r.c_last, r.p_last))
        fee_deliv = sum(min(FEE_DELIVERY, FEE_CAP * px) for px in (r.c_last, r.p_last))
        crossing = touch_bps[r.currency] / 2 / 1e4
        out = {"currency": r.currency, "symbol": sym, "day": r.day, "fold": next((n for n in ("F1", "F2", "F3", "F4", "F5") if folds.bounds(n)[0] <= r.day < folds.bounds(n)[1]), None),
               "spot": s0, "strike": k, "m": m, "m_pct": 100 * m, "sigma_q": sig_q, "rv_real": np.exp(f["y"]) / 100, "settle": path[-1], "payoff": payoff,
               "hedge_pnl_long": hedge_pnl, "hedge_cost": hedge_cost, "hedge_units": units, "crossing": crossing, "fee_entry": fee_entry, "fee_delivery": fee_deliv,
               "hit_I+C": np.nan}
        for key, col in FORECASTS.items():
            rv_hat = np.exp(f[col]) / 100
            sign = 1.0 if np.log(rv_hat) > np.log(sig_q) else -1.0
            out[f"sign_{key}"] = sign
            out[f"rvhat_{key}"] = rv_hat
            gross_h = sign * (payoff - m + hedge_pnl)
            gross_u = sign * (payoff - m)
            out[f"gross_hedged_{key}"] = 1e4 * gross_h
            out[f"net_hedged_{key}"] = 1e4 * (gross_h - crossing - fee_entry - fee_deliv - hedge_cost)
            out[f"gross_unhedged_{key}"] = 1e4 * gross_u
            out[f"net_unhedged_{key}"] = 1e4 * (gross_u - crossing - fee_entry - fee_deliv)
            out[f"hit_{key}"] = float(sign * (np.log(out["rv_real"]) - np.log(sig_q)) > 0)
        for key, sign in (("short", -1.0), ("long", 1.0)):
            gross_h = sign * (payoff - m + hedge_pnl)
            out[f"gross_hedged_{key}"] = 1e4 * gross_h
            out[f"net_hedged_{key}"] = 1e4 * (gross_h - crossing - fee_entry - fee_deliv - hedge_cost)
            out[f"gross_unhedged_{key}"] = 1e4 * sign * (payoff - m)
            out[f"net_unhedged_{key}"] = 1e4 * (sign * (payoff - m) - crossing - fee_entry - fee_deliv)
        rows.append(out)
    return pd.DataFrame(rows)


def read_rows(days: pd.DataFrame, fold_names=("F1", "F2")) -> pd.DataFrame:
    rows = []
    for cur, g in days.groupby("currency"):
        g = g.sort_values("day")
        for key in ["I+C", "I", "C", "short", "long"]:
            for acct in ("hedged", "unhedged"):
                net, gross = g[f"net_{acct}_{key}"].to_numpy(), g[f"gross_{acct}_{key}"].to_numpy()
                mn, se, t = nw(net)
                gm, gse, gt = nw(gross)
                per = {f: float(g.loc[g["fold"] == f, f"net_{acct}_{key}"].mean()) if (g["fold"] == f).any() else np.nan for f in fold_names}
                fam = key == "I+C" and acct == "hedged"
                rows.append({"currency": cur, "sign": key, "accounting": acct, "family": fam, "days": len(g), "net": mn, "se": se, "t": t, "mde": 2.8 * se, "upper": mn + 1.96 * se,
                             **{f"net_{f}": v for f, v in per.items()}, "gross": gm, "gross_se": gse, "gross_t": gt,
                             "hit": float(g[f"hit_{key}"].mean()) if f"hit_{key}" in g else np.nan,
                             "share_long": float((g[f"sign_{key}"] > 0).mean()) if f"sign_{key}" in g else (1.0 if key == "long" else 0.0),
                             "verdict": verdict(mn, se, t, per.get("F1", np.nan), per.get("F2", np.nan), gt) if fam else "described"})
    return pd.DataFrame(rows)


def run(name: str = "f12", fold_names=("F1", "F2")) -> str:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    d = pd.read_parquet(straddle.PARQUET)
    d["day"] = pd.to_datetime(d["day"], utc=True)
    hedge = pd.read_parquet(straddle.HEDGE)
    hedge["day"] = pd.to_datetime(hedge["day"], utc=True)
    tch = pd.read_parquet(straddle.TOUCH)
    tch["day"] = pd.to_datetime(tch["day"], utc=True)
    fc, sha = load_forecasts()
    costs = costs_table()
    sp = straddle.touch_spread(tch)
    touch_bps = {cur: v["median_bps"] for cur, v in sp.items()}
    # validity, read first
    v = {"status": "PASS", "r54_loss_sha256": sha, "r54_forecast_column": "yhat_I+C", "touch_bps": sp}
    a, b = straddle.window(fold_names)
    inwin = d[(d["day"] >= a) & (d["day"] < b)]
    cover = {cur: float(g["covered"].mean()) for cur, g in inwin.groupby("currency")}
    v["coverage"] = cover
    v["skips"] = {cur: {str(k): int(n) for k, n in g["skip"].value_counts().items()} for cur, g in inwin.groupby("currency")}
    v["(1) causal entry: every entry bar ends at or before 00:00"] = "PASS" if bool(((pd.to_datetime(d.loc[d["covered"], "c_last_ts"], utc=True) <= d.loc[d["covered"], "day"]) & (pd.to_datetime(d.loc[d["covered"], "p_last_ts"], utc=True) <= d.loc[d["covered"], "day"])).all()) else "FAIL"
    v["(2) coverage ≥ 50 % (void below), ≥ 80 % (full)"] = "VOID" if any(c < COVER_VOID for c in cover.values()) else ("PASS" if all(c >= COVER_FULL for c in cover.values()) else "PASS (read on the covered days, the share in every row)")
    v["(3) R54's file"] = {"sha256": sha, "rows_hold1": int(len(fc))}
    v["(4) settlement bars ≥ 25 on every covered day"] = "PASS" if bool((d.loc[d["covered"], "settle_bars"] >= straddle.SETTLE_MIN).all()) else "FAIL"
    names_ok = True
    for r in tch.itertuples():
        row = d[(d["currency"] == r.currency) & (d["day"] == r.day)]
        if not len(row) or r.name not in (row["call"].iloc[0], row["put"].iloc[0]):
            names_ok = False
    v["(5) the Tardis legs are the chart legs; the median spread in (0, 100) bps"] = "PASS" if names_ok and all(0 < x < 100 for x in touch_bps.values()) and set(touch_bps) >= set(d["currency"]) else "FAIL"
    if any(x.startswith("FAIL") or x == "VOID" for x in v.values() if isinstance(x, str)) or set(touch_bps) < set(d["currency"]):
        v["status"] = "VOID" if v["(2) coverage ≥ 50 % (void below), ≥ 80 % (full)"] == "VOID" else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    if v["status"] != "PASS":
        txt = f"# varbook {name} — VALIDITY {v['status']}\n\n```\n{json.dumps(v, indent=1, default=str)}\n```\n"
        (out / "varbook.md").write_text(txt)
        return txt
    days = price_days(inwin, hedge, fc, touch_bps, costs)
    days.to_csv(out / "days.csv", index=False)
    rows = read_rows(days, fold_names)
    rows.to_csv(out / "rows.csv", index=False)
    costs_df = days.groupby("currency")[["crossing", "fee_entry", "fee_delivery", "hedge_cost", "hedge_units", "m", "sigma_q", "rv_real", "payoff"]].mean()
    for c in ("crossing", "fee_entry", "fee_delivery", "hedge_cost", "m", "payoff"):
        costs_df[c] *= 1e4
    costs_df.to_csv(out / "costs.csv")
    txt = _md(name, rows, days, costs_df, v)
    (out / "varbook.md").write_text(txt)
    return txt


def _md(name: str, rows: pd.DataFrame, days: pd.DataFrame, costs: pd.DataFrame, v: dict) -> str:
    L = [f"# varbook {name} — R55: the one-day variance position signed by R54's forecast (F1+F2)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
         "\n**VALIDITY " + v["status"] + "** — coverage " + ", ".join(f"{c} {x:.0%}" for c, x in v["coverage"].items()) + "; the touch " + ", ".join(f"{c} {x['median_bps']:.0f} bps over {x['days']} days" for c, x in v["touch_bps"].items()) + "; R54's file sha256 " + v["r54_loss_sha256"][:12] + "…\n",
         "\n## The family — hedged, signed by R54's I + C forecast against the straddle's break-even volatility (bps of spot a straddle a day)\n",
         "| name | days | net | se | t | F1 | F2 | upper | MDE | gross | gross t | hit | long share | verdict |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    fam = rows[rows["family"]]
    for r in fam.itertuples():
        L.append(f"| {r.currency} | {r.days} | {r.net:+.1f} | {r.se:.1f} | {r.t:+.2f} | {r.net_F1:+.1f} | {r.net_F2:+.1f} | {r.upper:+.1f} | {r.mde:.1f} | {r.gross:+.1f} | {r.gross_t:+.2f} | {r.hit:.0%} | {r.share_long:.0%} | **{r.verdict}** |")
    L.append("\n## Described — every sign and accounting (no verdict)\n")
    L.append("| name | sign | accounting | days | net | se | t | F1 | F2 | gross | gross t | hit | long share |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows.itertuples():
        L.append(f"| {r.currency} | {r.sign} | {r.accounting} | {r.days} | {r.net:+.1f} | {r.se:.1f} | {r.t:+.2f} | {r.net_F1:+.1f} | {r.net_F2:+.1f} | {r.gross:+.1f} | {r.gross_t:+.2f} | {r.hit if np.isnan(r.hit) else f'{r.hit:.0%}'} | {r.share_long:.0%} |")
    L.append("\n## Costs and levels (means over the covered days; bps of spot unless stated)\n")
    L.append("| name | crossing | entry fees | delivery fees | hedge crossings | hedge units traded | straddle m | σ_q (ann.) | realised RV (ann.) | payoff |\n|---|---|---|---|---|---|---|---|---|---|")
    for cur, r in costs.iterrows():
        L.append(f"| {cur} | {r['crossing']:.1f} | {r['fee_entry']:.1f} | {r['fee_delivery']:.1f} | {r['hedge_cost']:.1f} | {r['hedge_units']:.2f} | {r['m']:.0f} | {r['sigma_q']:.3f} | {r['rv_real']:.3f} | {r['payoff']:.0f} |")
    L.append("\n## Validity\n\n```\n" + json.dumps(v, indent=1, default=str) + "\n```\n")
    return "\n".join(L) + "\n"


def main(name: str = "f12") -> None:
    print(run(name))
    print(f"wrote {OUT / name}/")
