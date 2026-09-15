"""P1 — price the trade (PLAN §4 P1). `ft2 cost` → output/cost.md, data/cost_daily.parquet,
data/cost_table.parquet.

Every number is measured from the data on the VM; the only input is the fee schedule, which
is recorded with its source in the report header. Components, each its own function and its
own section of the report:

  regimes         daily realised volatility per pair from 5m candles (std of 5m log returns ×
                  √288, in %), cut into per-pair terciles lo / mid / hi over the whole history.
  spread          the full bid–ask spread in bps per pair × day from the tape's bounce estimate
                  (`eff_spread_bps`, DATA.md "tape"), by hour-of-day and by regime; validated
                  against the collector's quoted spread on their 2026-07 → 09 overlap.
  impact          slippage beyond the half-spread of a market order of N USDT, from the ladder
                  (`data/ladder`, 2026-08-05 → 09-13): a measured per-pair curve over eight
                  notionals, carried back in time as impact(N · D_ref / D_day) with D the notional
                  within ±1 % of mid (the archive `depth` band, 2023-01 →), censored beyond the
                  measured range; the scaling is tested deep-vs-shallow hours inside the window.
  maker           a limit order resting at the touch (the tape's last bid / last ask of the
                  minute): the share filled within H minutes (price traded through it) and the
                  post-fill drift against the fill (adverse selection), per pair × regime.
  funding         the settled funding rate per event and per day, signed (a long pays a positive
                  rate) and absolute, with the interval, from `funding_archive`.
  candle_proxy    a per-pair regression of the daily tape spread on 5m-candle features (range,
                  dollar volume, price), time-split error reported, applied only where the tape
                  is absent (2022-08 → 2022-12).

Round-trip totals (bps) in the summary table:
  taker_rt_<N> = 2·taker_fee + spread + impact_buy(N) + impact_sell(N)
  maker_rt_<H> = 2·maker_fee − 2·drift_after_fill(H)    (drift vs the resting price, negative = adverse;
                 with the fill probability alongside — an unfilled order costs the taker path plus
                 the drift meanwhile, which the harness prices)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, ladder

OUT_MD = Path("output/cost.md")
DAILY = data.PROC / "cost_daily.parquet"
TABLE = data.PROC / "cost_table.parquet"

HOLDS = [5, 15, 30]            # minutes a maker order rests before we give up
TAPE_START = pd.Timestamp("2023-01-01", tz="UTC")
REGIMES = ["lo", "mid", "hi"]
CENSOR_MAX = 0.2               # a pair × regime × notional whose impact is censored on more days than this stays blank


def _day(ts: pd.Series) -> pd.Series:
    return ts.dt.floor("D")


# ---- 1. volatility regimes ---------------------------------------------------------------------
def regimes() -> pd.DataFrame:
    c = data.load("candles_5m", columns=["symbol", "open_time", "close", "high", "low", "volume"])
    c = c.sort_values(["symbol", "open_time"])
    c["r"] = np.log(c["close"]).groupby(c["symbol"], observed=True).diff()
    c["day"] = _day(c["open_time"])
    g = c.groupby(["symbol", "day"], observed=True)
    d = pd.DataFrame({
        "vol_pct": g["r"].std() * np.sqrt(288) * 100,
        "range_bps": g.apply(lambda x: ((x["high"] - x["low"]) / x["close"]).mean() * 1e4, include_groups=False),
        "dollar_vol": g.apply(lambda x: (x["volume"] * x["close"]).sum(), include_groups=False),
        "px": g["close"].mean(), "bars": g.size(),
    }).reset_index()
    d = d[d["bars"] >= 200]                     # a day with < 200 of 288 bars is not a day
    d["regime"] = (d.groupby("symbol", observed=True)["vol_pct"]
                    .transform(lambda v: pd.qcut(v, 3, labels=REGIMES)).astype(str))
    return d


# ---- 2. spread from the tape, validated against quotes -----------------------------------------
def spread(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Returns (daily, by_hour, validation)."""
    daily, hourly, val = [], [], []
    snaps = data.load("snapshots", columns=["symbol", "ts", "mid", "spread"]).dropna()
    snaps["minute"] = snaps["ts"].dt.floor("min")
    snaps["quoted_bps"] = snaps["spread"] / snaps["mid"] * 1e4
    q = snaps.groupby(["symbol", "minute"], observed=True)["quoted_bps"].mean().reset_index()
    for sym in symbols:
        t = data.load("tape", columns=["ts", "eff_spread_bps", "n_flips", "n_trades", "notional"], symbols=[sym])
        if t.empty:
            continue
        t["day"] = _day(t["ts"])
        t["hour"] = t["ts"].dt.hour
        g = t.groupby("day")
        daily.append(pd.DataFrame({"symbol": sym, "spread_bps": g["eff_spread_bps"].median(),
                                   "spread_mean_bps": g["eff_spread_bps"].mean(), "minutes": g.size(),
                                   "tape_notional": g["notional"].sum()}).reset_index())
        hourly.append(t.groupby("hour")["eff_spread_bps"].median().rename(sym))
        m = t.merge(q[q["symbol"] == sym], left_on="ts", right_on="minute", how="inner")
        if len(m):
            dm = m.groupby("day")[["eff_spread_bps", "quoted_bps"]].median()
            val.append({"symbol": sym, "overlap_minutes": len(m),
                        "tape_bps_p50": m["eff_spread_bps"].median(), "quoted_bps_p50": m["quoted_bps"].median(),
                        "ratio_p50": (m["eff_spread_bps"] / m["quoted_bps"]).median(),
                        "abs_err_bps_p50": (m["eff_spread_bps"] - m["quoted_bps"]).abs().median(),
                        "daily_corr": dm["eff_spread_bps"].corr(dm["quoted_bps"]), "overlap_days": len(dm)})
    return (pd.concat(daily, ignore_index=True), pd.concat(hourly, axis=1).T.round(3),
            pd.DataFrame(val).set_index("symbol").round(4))


# ---- 3. impact from the ladder, scaled back in time by depth -----------------------------------
IMPACT_TEST_N = [10_000, 100_000]
GAMMAS = [0.0, 0.25, 0.5, 0.75, 1.0]     # impact(N · (D_ref/D)^γ): γ = 1 is 'impact depends on N/D', γ = 0 no scaling


def _curve_eval(curve_n: np.ndarray, curve_imp: np.ndarray, n_eff) -> np.ndarray:
    """Impact at an effective notional from a measured (N, impact) curve: log-log interpolation
    between grid points, linear below the smallest N, NaN (censored) above the largest."""
    imp = np.maximum.accumulate(np.maximum(curve_imp, 1e-6))
    n_eff = np.asarray(n_eff, dtype=float)
    out = np.exp(np.interp(np.log(n_eff), np.log(curve_n), np.log(imp)))
    out = np.where(n_eff < curve_n[0], imp[0] * n_eff / curve_n[0], out)
    return np.where(n_eff > curve_n[-1], np.nan, out)


def impact(symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, float]:
    """Impact beyond the half-spread, per side, from the ladder window; carried back in time by depth.

    Model: impact depends on N · (D_ref / D)^γ — a notional N on a day whose ±1 % depth D is
    below the ladder window's D_ref behaves like a larger notional today. Per pair the window
    gives a measured curve impact(N) at the eight notionals (hourly means) and D_ref (window
    median); a historical day gets impact(N · (D_ref/D_day)^γ) from that curve, censored (NaN)
    when the effective notional exceeds the largest measured one — never extrapolated. γ is
    chosen inside the window: the curve is fitted on the hours above median depth, applied to
    the hours below it, and the γ in GAMMAS with the smallest mean relative error wins (γ = 1
    is 'impact ∝ N/D', γ = 0 'depth does not matter').
    Returns (window curve per pair×N, checks per pair, scaling test per pair, daily history, γ)."""
    hours, checks, tests, curves = [], [], [], {}
    N = np.array(ladder.NOTIONALS, dtype=float)
    for sym in symbols:
        try:
            lad = data.load("ladder", symbols=[sym])
        except (FileNotFoundError, ValueError):
            continue
        if lad.empty:
            continue
        dep = data.load("depth", columns=["ts", "usd_m1", "usd_p1"], symbols=[sym])
        dep["D"] = (dep["usd_m1"] + dep["usd_p1"]) / 2
        m = pd.merge_asof(lad.sort_values("ts"), dep[["ts", "D"]].sort_values("ts"), on="ts",
                          tolerance=pd.Timedelta("45s"), direction="nearest")
        own = (m["usd_bid_1"] + m["usd_ask_1"]) / 2
        checks.append({"symbol": sym, "snapshots": len(m), "matched_depth": int(m["D"].notna().sum()),
                       "ladder_1pct_usd_p50": own.median(), "archive_1pct_usd_p50": m["D"].median(),
                       "ratio_ladder_over_archive_p50": (own / m["D"]).median(),
                       "ask_extent_bps_p50": m["ask_extent_bps"].median(), "spread_bps_p50": m["spread_bps"].median(),
                       **{f"censored_{n}": (m[ladder.slip_col("buy", n)].isna() | m[ladder.slip_col("sell", n)].isna()).mean()
                          for n in ladder.NOTIONALS}})
        cols = {}
        for n in ladder.NOTIONALS:
            cols[f"imp_{n}"] = (m[ladder.slip_col("buy", n)] + m[ladder.slip_col("sell", n)]) / 2 - m["spread_bps"] / 2
        hh = pd.DataFrame({**cols, "D": m["D"]}).groupby(m["ts"].dt.floor("h")).mean().dropna(subset=["D"])
        curve = hh[[f"imp_{n}" for n in ladder.NOTIONALS]].mean().to_numpy()
        curves[sym] = (curve, float(hh["D"].median()))
        hh["symbol"] = sym
        hours.append(hh.reset_index())
        # scaling test: curve + D_ref from the deep half of the hours, predict the shallow half
        deep = hh["D"] >= hh["D"].median()
        c_deep = hh.loc[deep, [f"imp_{n}" for n in ladder.NOTIONALS]].mean().to_numpy()
        d_ref = float(hh.loc[deep, "D"].median())
        row = {"symbol": sym, "hours_deep": int(deep.sum()), "hours_shallow": int((~deep).sum()),
               "depth_ratio_deep_over_shallow": d_ref / float(hh.loc[~deep, "D"].median())}
        for n in IMPACT_TEST_N:
            act = hh.loc[~deep, f"imp_{n}"].to_numpy()
            row[f"actual_{n}_bps"] = float(np.mean(act))
            for g in GAMMAS:
                pred = _curve_eval(N, c_deep, n * (d_ref / hh.loc[~deep, "D"].to_numpy()) ** g)
                ok = ~np.isnan(pred)
                row[f"pred_{n}_g{g}"] = float(np.mean(pred[ok])) if ok.any() else np.nan
                row[f"relerr_{n}_g{g}"] = float(np.mean(np.abs(pred[ok] - act[ok])) / max(np.mean(act), 1e-6)) if ok.any() else np.nan
        tests.append(row)
    if not hours:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), np.nan
    h = pd.concat(hours, ignore_index=True)
    win = h.groupby("symbol")[[f"imp_{n}" for n in ladder.NOTIONALS]].mean()
    win.columns = [int(c.split("_")[1]) for c in win.columns]
    test = pd.DataFrame(tests).set_index("symbol")
    # the exponent: the one with the smallest mean relative error over pairs and both test notionals
    err = {g: float(np.nanmean(test[[f"relerr_{n}_g{g}" for n in IMPACT_TEST_N]].to_numpy())) for g in GAMMAS}
    gamma = min(err, key=err.get)
    test.attrs["gamma_error"] = err
    # daily history from the archive depth
    rows = []
    for sym, (curve, d_ref) in curves.items():
        dep = data.load("depth", columns=["ts", "usd_m1", "usd_p1"], symbols=[sym])
        dd = ((dep["usd_m1"] + dep["usd_p1"]) / 2).groupby(_day(dep["ts"])).median()
        dd = pd.DataFrame({"day": dd.index, "depth_usd_1pct": dd.to_numpy()})
        dd["symbol"] = sym
        dd["depth_ratio"] = d_ref / dd["depth_usd_1pct"]          # > 1: shallower than the ladder window
        for n in ladder.NOTIONALS:
            dd[f"imp_{n}"] = _curve_eval(N, curve, n * dd["depth_ratio"].to_numpy() ** gamma)
        rows.append(dd)
    return win, pd.DataFrame(checks).set_index("symbol"), test, pd.concat(rows, ignore_index=True), gamma


# ---- 4. maker: fill within H minutes and adverse selection --------------------------------------
def maker(symbols: list[str]) -> pd.DataFrame:
    """Per pair × day: for each H, the share of resting orders filled (price traded *through* the
    resting level) or merely touched, and the drift H minutes after placement versus the resting
    price, conditional on a fill, in bps (negative = adverse selection; a positive value means the
    half-spread earned exceeded the adverse drift), both sides pooled."""
    out = []
    for sym in symbols:
        t = data.load("tape", columns=["ts", "high", "low", "close", "ask_last", "bid_last"], symbols=[sym])
        if t.empty:
            continue
        t = t.set_index("ts").sort_index()
        t = t.reindex(pd.date_range(t.index.min(), t.index.max(), freq="min", tz="UTC"))
        close_ff = t["close"].ffill()
        res = pd.DataFrame(index=t.index)
        res["day"] = res.index.floor("D")
        for H in HOLDS:
            fut_low = t["low"][::-1].rolling(H, min_periods=1).min()[::-1].shift(-1)
            fut_high = t["high"][::-1].rolling(H, min_periods=1).max()[::-1].shift(-1)
            c_h = close_ff.shift(-H)
            buy_ok, sell_ok = t["bid_last"].notna(), t["ask_last"].notna()
            fb_strict, fs_strict = (fut_low < t["bid_last"]) & buy_ok, (fut_high > t["ask_last"]) & sell_ok
            fb, fs = (fut_low <= t["bid_last"]) & buy_ok, (fut_high >= t["ask_last"]) & sell_ok
            adv_b = ((c_h - t["bid_last"]) / t["bid_last"] * 1e4).where(fb_strict)
            adv_s = ((t["ask_last"] - c_h) / t["ask_last"] * 1e4).where(fs_strict)
            drift = ((c_h - close_ff) / close_ff * 1e4)
            res[f"placed_{H}"] = (buy_ok.astype(int) + sell_ok.astype(int))
            res[f"fill_{H}"] = fb_strict.astype(int) + fs_strict.astype(int)        # traded through: surely filled
            res[f"touch_{H}"] = fb.astype(int) + fs.astype(int)                     # touched: filled only with queue luck
            res[f"adv_sum_{H}"] = adv_b.fillna(0) + adv_s.fillna(0)
            res[f"drift_abs_{H}"] = drift.abs()
        g = res.groupby("day")
        d = g.sum(numeric_only=True)
        for H in HOLDS:
            d[f"maker_fill_{H}"] = d[f"fill_{H}"] / d[f"placed_{H}"]
            d[f"maker_touch_{H}"] = d[f"touch_{H}"] / d[f"placed_{H}"]
            d[f"maker_adv_{H}"] = d[f"adv_sum_{H}"] / d[f"fill_{H}"].replace(0, np.nan)
            d[f"drift_abs_{H}"] = g[f"drift_abs_{H}"].mean()
        d["symbol"] = sym
        out.append(d.reset_index()[["symbol", "day", *[c for c in d.columns if c.startswith(("maker_", "drift_abs_"))]]])
    return pd.concat(out, ignore_index=True)


# ---- 5. funding ---------------------------------------------------------------------------------
def funding() -> pd.DataFrame:
    f = data.load("funding_archive")
    f["day"] = _day(f["ts"])
    f["bps"] = f["rate"] * 1e4
    g = f.groupby(["symbol", "day"], observed=True)
    return pd.DataFrame({"fund_bps_day": g["bps"].sum(), "fund_abs_bps_day": g["bps"].apply(lambda s: s.abs().sum()),
                         "fund_events": g.size(), "fund_interval_h": g["interval_h"].median()}).reset_index()


# ---- 6. candle proxy for the spread where the tape is absent ---------------------------------
def candle_proxy(reg: pd.DataFrame, sp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per pair OLS: log(spread) ~ 1 + log(range) + log(dollar volume) + log(price), on tape days.
    Time split (fit < 2025-01-01, test ≥) for the error; refit on all tape days for the application.
    Returns (proxy per pair × day for days before TAPE_START, fit report)."""
    m = reg.merge(sp[["symbol", "day", "spread_bps"]], on=["symbol", "day"], how="left")
    m = m[(m["range_bps"] > 0) & (m["dollar_vol"] > 0)]
    X_all = np.column_stack([np.ones(len(m)), np.log(m["range_bps"]), np.log(m["dollar_vol"]), np.log(m["px"])])
    proxies, report = [], []
    for sym, idx in m.groupby("symbol", observed=True).indices.items():
        g, X = m.iloc[idx], X_all[idx]
        have = g["spread_bps"].notna() & (g["spread_bps"] > 0)
        y = np.log(g["spread_bps"].where(have))
        tr = have & (g["day"] < pd.Timestamp("2025-01-01", tz="UTC"))
        te = have & ~tr
        if tr.sum() < 60 or te.sum() < 30:
            continue
        b, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        pred = np.exp(X[te] @ b)
        mape = float(np.mean(np.abs(pred - g.loc[te, "spread_bps"]) / g.loc[te, "spread_bps"]))
        b_all, *_ = np.linalg.lstsq(X[have], y[have], rcond=None)
        r2 = float(1 - np.var(y[have] - X[have] @ b_all) / np.var(y[have]))
        report.append({"symbol": sym, "fit_days": int(tr.sum()), "test_days": int(te.sum()), "r2_all": r2, "test_mape": mape,
                       "b_range": b_all[1], "b_dollar_vol": b_all[2], "b_px": b_all[3]})
        pre = g["day"] < TAPE_START
        if pre.any():
            proxies.append(pd.DataFrame({"symbol": sym, "day": g.loc[pre, "day"].to_numpy(),
                                         "spread_proxy_bps": np.exp(X[pre.to_numpy()] @ b_all)}))
    rep = pd.DataFrame(report, columns=["symbol", "fit_days", "test_days", "r2_all", "test_mape", "b_range", "b_dollar_vol", "b_px"])
    return pd.concat(proxies, ignore_index=True) if proxies else pd.DataFrame(), rep.set_index("symbol").round(4)


# ---- assemble ---------------------------------------------------------------------------------
def run(taker_bps: float, maker_bps: float, fee_source: str, symbols: list[str]) -> str:
    md = ["# Cost of a trade — measured (`ft2 cost`)\n", f"generated {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC\n",
          f"\n**Fees (input):** taker {taker_bps} bps, maker {maker_bps} bps per side — source: {fee_source}\n"]
    print("regimes…", flush=True)
    reg = regimes()
    print("spread…", flush=True)
    sp, sp_hour, sp_val = spread(symbols)
    print("impact…", flush=True)
    imp_win, imp_check, imp_test, imp_hist, gamma = impact(symbols)
    print("maker…", flush=True)
    mk = maker(symbols)
    print("funding…", flush=True)
    fu = funding()
    print("candle proxy…", flush=True)
    proxy, proxy_rep = candle_proxy(reg, sp)

    # daily series
    d = reg.merge(sp, on=["symbol", "day"], how="left")
    d = d.merge(proxy, on=["symbol", "day"], how="left") if len(proxy) else d.assign(spread_proxy_bps=np.nan)
    d["spread_src"] = np.where(d["spread_bps"].notna(), "tape", np.where(d["spread_proxy_bps"].notna(), "proxy", "none"))
    d["spread_bps"] = d["spread_bps"].fillna(d["spread_proxy_bps"])
    # the bounce estimate under-reads the quoted spread where flips at the same price count as zero;
    # the overlap gives a per-pair factor (tape / quoted), applied to the whole history
    d["spread_cal_bps"] = d["spread_bps"] / d["symbol"].map(sp_val["ratio_p50"]).astype(float)
    if len(imp_hist):
        d = d.merge(imp_hist, on=["symbol", "day"], how="left")
    d = d.merge(mk, on=["symbol", "day"], how="left").merge(fu, on=["symbol", "day"], how="left")
    d = d.sort_values(["symbol", "day"]).reset_index(drop=True)
    d["symbol"] = d["symbol"].astype("category")
    d.to_parquet(DAILY, index=False)

    # summary per pair × regime (medians of the daily series over tape days)
    t = d[d["spread_src"] == "tape"]
    imp_cols = [c for c in d.columns if c.startswith("imp_")]
    for c in imp_cols:
        t = t.assign(**{f"cens_{c}": t[c].isna()})
    agg = {"spread_bps": "median", "spread_cal_bps": "median", "vol_pct": "median", **{c: "median" for c in imp_cols},
           **({"depth_ratio": "median"} if "depth_ratio" in t else {}), **{f"cens_{c}": "mean" for c in imp_cols},
           **{f"maker_fill_{H}": "mean" for H in HOLDS}, **{f"maker_touch_{H}": "mean" for H in HOLDS},
           **{f"maker_adv_{H}": "mean" for H in HOLDS}, "fund_abs_bps_day": "mean", "fund_bps_day": "mean",
           "fund_interval_h": "median", "day": "size"}
    tab = t.groupby(["symbol", "regime"], observed=True).agg(agg).rename(columns={"day": "days"}).reset_index()
    for n in ladder.NOTIONALS:
        if f"imp_{n}" in tab:
            tab[f"taker_rt_{n}"] = (2 * taker_bps + tab["spread_cal_bps"] + 2 * tab[f"imp_{n}"]).where(tab[f"cens_imp_{n}"] <= CENSOR_MAX)
    for H in HOLDS:
        tab[f"maker_rt_{H}"] = 2 * maker_bps - 2 * tab[f"maker_adv_{H}"]
    tab["fund_bps_per_8h"] = tab["fund_abs_bps_day"] / 3
    tab["regime"] = pd.Categorical(tab["regime"], REGIMES)
    tab = tab.sort_values(["symbol", "regime"]).reset_index(drop=True)
    tab.to_parquet(TABLE, index=False)

    # report
    def show(df, cols=None, digits=3):
        return (df[cols] if cols else df).round(digits).to_markdown(index=False)
    md += ["\n## Round trip, bps, per pair × volatility regime (tape days 2023-01 →)\n",
           "taker_rt_N = 2·taker fee + full spread (calibrated) + impact both sides at N USDT, blank where the day's depth "
           "makes N exceed the measured curve (censored); maker_rt_H = 2·maker fee − 2·(post-fill drift vs the resting price) "
           "for an order filled within H minutes (fill share alongside — the unfilled remainder pays the taker path). "
           "Funding is per 8 h held, unconditional on side (mean |rate|).\n",
           show(tab, ["symbol", "regime", "days", "vol_pct", "spread_bps", "spread_cal_bps",
                      *[f"taker_rt_{n}" for n in ladder.NOTIONALS if f"taker_rt_{n}" in tab],
                      *[f"maker_fill_{H}" for H in HOLDS], *[f"maker_rt_{H}" for H in HOLDS], "fund_bps_per_8h"], 2), "\n"]
    md += ["\n## Spread (full, bps) from the tape: validation against the collector's quoted spread (2026-07 → 09 overlap)\n",
           sp_val.to_markdown(), "\n", "\n### Spread by hour of day (UTC), median over all tape minutes\n", sp_hour.to_markdown(), "\n"]
    if len(imp_win):
        md += ["\n## Impact beyond the half-spread (bps per side) in the ladder window 2026-08-05 → 09-13, hourly means\n",
               imp_win.round(3).to_markdown(), "\n",
               "\n### Ladder vs archive depth (±1 % band) on the same timestamps; censored_N = share of snapshots whose ladder held less than N\n",
               imp_check.round(3).to_markdown(), "\n",
               "\n### Depth scaling test inside the window: curve fitted on the deeper half of the hours, applied at N·(D_ref/D)^γ to the shallower half\n",
               f"mean relative error by γ (over pairs, N = {IMPACT_TEST_N}): "
               + ", ".join(f"γ={g}: {e:.3f}" for g, e in imp_test.attrs["gamma_error"].items())
               + f" → **γ = {gamma} is used for the history**. Depth ratios inside the window are only 1.2–1.9; the history's "
               "ratios (`depth_ratio` in the daily series, its median per regime in the summary) go far beyond that, and the "
               "censoring rule, not the curve, is what protects the large notionals there.\n",
               imp_test[[c for c in imp_test.columns if not c.startswith("relerr_")]].round(3).to_markdown(), "\n",
               "\n### Share of tape days on which the impact at N is censored (effective notional beyond the measured curve)\n",
               show(tab, ["symbol", "regime", "depth_ratio", *[f"cens_imp_{n}" for n in ladder.NOTIONALS]], 2), "\n"]
    md += ["\n## Maker at the touch: fill share within H minutes and post-fill drift (bps vs the resting price; negative = adverse), tape days, per regime\n",
           show(tab, ["symbol", "regime", *[f"maker_fill_{H}" for H in HOLDS], *[f"maker_touch_{H}" for H in HOLDS],
                      *[f"maker_adv_{H}" for H in HOLDS]], 3), "\n"]
    md += ["\n## Funding per day (bps): signed (long pays) and absolute, and the interval\n",
           show(tab, ["symbol", "regime", "fund_bps_day", "fund_abs_bps_day", "fund_interval_h"], 3), "\n"]
    md += ["\n## Candle proxy for the spread (fit on tape days < 2025, tested ≥ 2025; applied to 2022-08 → 2022-12)\n",
           proxy_rep.to_markdown(), "\n",
           f"\nproxied pair-days: {len(proxy)}; daily series `{DAILY}` ({len(d):,} pair-days, columns: {', '.join(d.columns)})\n"]
    text = "\n".join(md)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(text)
    return text


def main(argv=None):
    p = argparse.ArgumentParser(prog="ft2 cost")
    p.add_argument("--taker-bps", type=float, default=5.0)
    p.add_argument("--maker-bps", type=float, default=2.0)
    p.add_argument("--fee-source", default="Binance USDⓈ-M published VIP 0 schedule (0.020 % maker / 0.050 % taker), "
                                           "no BNB discount — PENDING the account's tier from Vadim")
    p.add_argument("--symbols", nargs="*")
    a = p.parse_args(argv)
    from .__main__ import PAIRS
    print(run(a.taker_bps, a.maker_bps, a.fee_source, a.symbols or PAIRS))
