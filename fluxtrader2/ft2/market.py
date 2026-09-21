"""P5 — the ceiling audit for the MARKET FACTOR (PLAN §4 P5, registration R6 in §8).
`ft2 ceiling --target basket` → output/market.md, output/market/*.parquet.

P2 asked how predictable a PAIR's move is. R3/R4 showed that the one rule that made money was a bet on
the whole market (it bounced after violent falls — in a rising market only). This audit asks the same
question of the market itself: the equal-weight basket of the pairs present (≥ MIN_PAIRS), one series,
over every exploration year there is (FP+F0+F1+F2 = 2020-05 → 2024-08), and it reports every number
PER CALENDAR YEAR, because R4's lesson is that a pooled number hides a sign that follows the regime.

Conventions are P2's (`ceiling.py`): the 5m grid indexed by decision time t; a feature at t uses bars
closed at t; a label is the basket's log move from t to t + h in bps, divided by the basket's trailing
1-week volatility and clipped at ±5; t-statistics are HAC over days. Confirmation folds are refused.

What differs, and why:
  the IC        the uncentred correlation over the WHOLE sample (or year), Σ f·y / √(Σf² Σy²), with the HAC t of
                the daily sums Σ_day f·y. NOT P2's mean of per-day correlations: on one series a day's
                normaliser √(Σf² Σy²) is largest on the days that trend, which shrinks exactly the positive
                products — on pure random walks that statistic reads −0.06 … −0.12 for a trailing return
                (t −2 … −5; measured 2026-09-21 while testing this module, see `tests/test_p5_market.py`).
  the null      CIRCULAR SHIFTS of the label series by a random number of whole days (≥ SHIFT_MIN from
                either end), not day shuffles. One series with slow features (a 30-day trend keeps its
                sign for weeks, and so does the market's drift) has a daily IC that is autocorrelated far
                beyond the HAC lags; a day shuffle destroys exactly that and would call every slow feature
                significant. A shift keeps both autocorrelations whole and breaks only the link.
  encodings     signed features (returns, interactions) enter as themselves, clipped at ±5 — they have a
                natural zero; level features (volatility, breadth, funding) as their rank over the sample − ½.
  the forecast  a walk-forward ridge WITHOUT an intercept on standardised features, refitted every 30 days
                on the last 120 / 365 / all days (training bars thinned to every THIN-th: 4h labels overlap
                48 bars). No intercept: for this target an intercept is "the market goes up on average",
                i.e. being long — P2 #4 measured that as a quarter of the directional forecast's IC.
  the money view  the basket's mean next-4h move in bps after a 2σ fall / rise / broad fall, split by the
                sign of the 30-day trend and by year — R4's half-year table, stated before the read.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import folds
from .ceiling import ALPHAS, BAR, HORIZONS, MDE_K, MIN_PAIRS, TOP, W, Z_CLIP, Z_TOP, basket, day_lags, hac, panel

OUT_MD = Path("output/market.md")
OUT_DIR = Path("output/market")
FOLDS = (*folds.PREHISTORY, *folds.EXPLORATION)
HZ = ("1h", "4h", "1d")
PRIMARY = "4h"
LOOKBACKS = {"1h": W["1h"], "4h": W["4h"], "1d": W["1d"], "1w": W["1w"], "30d": 30 * 288}
PER_DAY = 288
FALL = 2.0               # the money view: a basket move of this many of its own 4h sigmas
BROAD = 2 / 3            # … or this share of the pairs down ≥ 1 of their own sigmas over 4 hours
SHIFT_MIN = 60           # days; the null's shifts stay this far from 0 and from a full turn (> the 30-day lookback + 1d)
DRAWS = 200
WINDOWS = (120, 365, None)   # the ridge's training windows in days (None = everything before the block)
GATE_WINDOW = 120            # R6's gate reads this one (P2 #5: short refits); the others are reported
REFIT_DAYS = 30
MIN_TRAIN_DAYS = 60
THIN = 6


# ---- the series -------------------------------------------------------------------------------------
def derive(P: dict[str, pd.DataFrame]) -> dict:
    lr = np.log(P["close"])
    b1 = basket(lr.diff() * 1e4)                                   # the basket's 5m move, bps
    blr = b1.fillna(0.0).cumsum().where(b1.notna())
    sig = {w: b1.rolling(k, min_periods=int(k * 0.8)).std() for w, k in LOOKBACKS.items() if k >= W["4h"]}
    fwd = {h: blr.shift(-HORIZONS[h]) - blr for h in HZ}
    z = {h: (fwd[h] / (sig["1w"] * np.sqrt(HORIZONS[h]))).clip(-Z_CLIP, Z_CLIP) for h in HZ}
    return {"lr": lr, "b1": b1, "blr": blr, "sig": sig, "fwd": fwd, "z": z}


def features(P: dict[str, pd.DataFrame], D: dict, fund: pd.DataFrame | None = None) -> tuple[dict[str, pd.Series], set[str]]:
    """(features, the signed ones). `fund`: funding events, ts × pair, bps — usable from the bar after the event."""
    lr, blr, sig = D["lr"], D["blr"], D["sig"]
    F = {f"mret_{w}": (blr - blr.shift(k)) / (sig["1w"] * np.sqrt(k)) for w, k in LOOKBACKS.items()}
    k = W["4h"]
    pz = (lr - lr.shift(k)) * 1e4 / ((lr.diff() * 1e4).rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std() * np.sqrt(k))
    n = pz.notna().sum(axis=1)
    n = n.where(n >= MIN_PAIRS)
    F["breadth_dn_4h"], F["breadth_up_4h"], F["disp_4h"] = (pz <= -1).sum(axis=1) / n, (pz >= 1).sum(axis=1) / n, pz.std(axis=1).where(n.notna())
    F["volratio_4h"], F["volratio_1d"], F["volratio_1w"] = np.log(sig["4h"] / sig["1w"]), np.log(sig["1d"] / sig["1w"]), np.log(sig["1w"] / sig["30d"])
    dv = P["dv"].sum(axis=1, min_count=MIN_PAIRS)
    F["dvol_1h"] = np.log(dv.rolling(W["1h"]).sum() / (dv.rolling(W["1w"], min_periods=1000).sum() / 168))
    if fund is not None and len(fund):
        idx = blr.index
        F["fund_mean"] = fund.reindex(idx.union(fund.index)).ffill().reindex(idx).shift(1).mean(axis=1)
    trend30, trend1w = np.sign(F["mret_30d"]), np.sign(F["mret_1w"])
    F["rev4h_x_trend30d"], F["rev4h_x_trend1w"] = -F["mret_4h"] * trend30, -F["mret_4h"] * trend1w
    F["fall_4h"] = F["mret_4h"].clip(upper=0.0).where(F["mret_4h"].notna())
    F["fall_x_trend30d"] = -F["fall_4h"] * trend30
    signed = {k_ for k_ in F if k_.startswith(("mret_", "rev4h_", "fall_"))}
    return {k_: v.replace([np.inf, -np.inf], np.nan) for k_, v in F.items()}, signed


def encode(F: dict[str, pd.Series], signed: set[str], s: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """On the scored bars: (for the direction target, for the |move| target)."""
    rank = lambda x: (x.rank(pct=True) - 0.5).to_numpy()                                           # noqa: E731
    fd = {k: (v[s].clip(-Z_CLIP, Z_CLIP).to_numpy() if k in signed else rank(v[s])) for k, v in F.items()}
    fa = {k: rank(v[s].abs() if k in signed else v[s]) for k, v in F.items()}
    return fd, fa


def scored_mask(idx: pd.DatetimeIndex, fold_names) -> np.ndarray:
    t = pd.Series(idx, index=idx)
    s = np.zeros(len(idx), dtype=bool)
    for f in fold_names:
        s |= folds.mask(t, f).to_numpy()
    return s


def shifts(n_days: int, draws: int, seed: int) -> np.ndarray:
    """Whole-day circular shifts for the null; draw 0 is the real data."""
    assert n_days > 3 * SHIFT_MIN, "too short for the shift null"
    return np.concatenate([[0], np.random.default_rng(seed).integers(SHIFT_MIN, n_days - SHIFT_MIN + 1, draws)])


# ---- #7 what a signal must clear ----------------------------------------------------------------------
def basket_cost(idx: pd.DatetimeIndex, cols: pd.Index, end: pd.Timestamp, taker_bps: float, maker_bps: float) -> pd.DataFrame:
    """Round trip of buying every pair, per bar: the mean over the pairs priced that day (maker: tape days only)."""
    from .backtest import load_costs
    C = load_costs(idx, cols, end)
    leg, adv = pd.DataFrame(C.taker_leg, index=C.days).mean(axis=1), pd.DataFrame(C.maker_adv, index=C.days).mean(axis=1)      # NaN-skipping
    d = pd.DataFrame({"taker": 2 * (taker_bps + leg), "maker": 2 * maker_bps - 2 * adv})
    return d.reindex(idx.floor("D")).set_index(idx)


def move_vs_cost(D: dict, cost: pd.DataFrame, s: np.ndarray, volatile: np.ndarray) -> pd.DataFrame:
    rows = []
    for h in HZ:
        a = D["fwd"][h].abs()
        for scope, m in (("all bars", s), (f"most volatile {TOP:.0%} (volratio_4h)", s & volatile)):
            for ex in ("taker", "maker"):
                ok = m & a.notna().to_numpy() & cost[ex].notna().to_numpy()
                if ok.sum() < 1000:
                    continue
                mv, c = a[ok].mean(), cost[ex][ok].mean()
                rows.append({"horizon": h, "bars": scope, "exec": ex, "cells": int(ok.sum()), "from": a.index[ok][0].date(), "abs_move_mean": mv, "round_trip": c,
                             "hit_needed": 0.5 + c / (2 * mv), "ic_needed": c / (Z_TOP * 1.2533 * mv)})
    return pd.DataFrame(rows)


# ---- #3 + #4 the screen and its null --------------------------------------------------------------------
def ic_stats(f: np.ndarray, y: np.ndarray, day: np.ndarray, lags: int, groups: dict[str, np.ndarray] | None = None) -> dict:
    """Whole-sample uncentred correlation, the HAC t and standard error (in IC units) from the daily sums of
    f·y, and the same correlation within each group of days (`groups`: name → a label per day)."""
    ok = ~(np.isnan(f) | np.isnan(y))
    nd = int(day.max()) + 1
    d, ff, yy = day[ok], f[ok], y[ok]
    num, sf, sy = np.bincount(d, ff * yy, nd), np.bincount(d, ff * ff, nd), np.bincount(d, yy * yy, nd)
    have = np.bincount(d, minlength=nd) > 0
    norm = np.sqrt(sf.sum() * sy.sum())
    mean, se, n = hac(np.where(have, num, np.nan), lags)
    out = {"ic": num.sum() / norm if norm else np.nan, "t": mean / se if se else np.nan, "days": n, "ic_se": se * n / norm if norm and se else np.nan}
    for gname, g in (groups or {}).items():
        x = pd.DataFrame({"g": g, "num": num, "sf": sf, "sy": sy})[have].groupby("g").sum()
        out[gname] = (x["num"] / np.sqrt(x["sf"] * x["sy"])).to_dict()
    return out


def screen(D: dict, F: dict[str, pd.Series], signed: set[str], s: np.ndarray, draws: int = DRAWS, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(the real screen with per-year ICs and both p-values, every draw's t). Bets: directional and vol."""
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    dates = pd.date_range(sidx[0].floor("D"), periods=int(day.max()) + 1, freq="D")
    year, month = dates.year.to_numpy(), np.asarray(dates.tz_localize(None).to_period("M").astype(str))
    fd, fa = encode(F, signed, s)
    sh = shifts(len(idx) // PER_DAY, draws, seed)
    real, null = [], []
    for draw, n_days in enumerate(sh):
        for h in HZ:
            zf = np.roll(D["z"][h].to_numpy(), int(n_days) * PER_DAY)[s]
            targets = {"directional": zf, "vol": (pd.Series(np.abs(zf)).rank(pct=True) - 0.5).to_numpy()}
            for bet, y in targets.items():
                for name in F:
                    r = ic_stats((fd if bet == "directional" else fa)[name], y, day, day_lags(HORIZONS[h]), None if draw else {"year": year, "month": month})
                    null.append({"bet": bet, "horizon": h, "feature": name, "draw": draw, "ic": r["ic"], "t": r["t"]})
                    if draw == 0:
                        mm, ym = np.array(list(r["month"].values())), r["year"]
                        real.append({"bet": bet, "horizon": h, "feature": name, "ic": r["ic"], "t": r["t"], "days": r["days"], "ic_mde": MDE_K * r["ic_se"],
                                     "months_same_sign": float((np.sign(mm) == np.sign(r["ic"])).mean()) if len(mm) else np.nan,
                                     "years_same_sign": int(sum(np.sign(v) == np.sign(r["ic"]) for v in ym.values())),
                                     **{str(k): v for k, v in ym.items()}})
    real, null = pd.DataFrame(real), pd.DataFrame(null)
    nz = null[null["draw"] > 0].dropna(subset=["t"])
    mx = nz.assign(a=nz["t"].abs()).groupby(["bet", "horizon", "draw"])["a"].max()
    ps, pf, sd = [], [], []
    for _, r in real.iterrows():
        own = nz[(nz["bet"] == r["bet"]) & (nz["horizon"] == r["horizon"]) & (nz["feature"] == r["feature"])]["t"]
        fam = mx.loc[r["bet"], r["horizon"]]
        ps.append((1 + int((own.abs() >= abs(r["t"])).sum())) / (len(own) + 1))
        pf.append((1 + int((fam >= abs(r["t"])).sum())) / (len(fam) + 1))
        sd.append(own.std())
    return real.assign(p_single=ps, p_fw=pf, null_t_sd=sd), null


# ---- #1 the forecast ------------------------------------------------------------------------------------
def design(D: dict, F: dict[str, pd.Series], signed: set[str]) -> np.ndarray:
    idx = D["blr"].index
    hour = idx.hour.to_numpy() * (2 * np.pi / 24)
    cols = [(v.clip(-Z_CLIP, Z_CLIP) if k in signed else v).to_numpy() for k, v in F.items()]
    return np.column_stack([*cols, np.sin(hour), np.cos(hour)])


def walk_ridge(X: np.ndarray, y: np.ndarray, t: np.ndarray, s: np.ndarray, k: int, window: int | None) -> np.ndarray:
    """Out-of-sample forecast on the scored bars: per REFIT_DAYS block, a ridge with no intercept fitted on
    standardised features over the `window` days whose labels ended before the block."""
    from sklearn.linear_model import RidgeCV
    yhat = np.full(len(y), np.nan)
    valid = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    thin = (np.arange(len(y)) % THIN) == 0
    step, bar = np.timedelta64(REFIT_DAYS, "D"), np.timedelta64(int(BAR.total_seconds()), "s")
    a = t[s][0]
    while a <= t[s][-1]:
        tr_end = a - k * bar
        tr = valid & thin & (t < tr_end) & ((t >= tr_end - np.timedelta64(window, "D")) if window else True)
        te = valid & s & (t >= a) & (t < a + step)
        if tr.sum() >= MIN_TRAIN_DAYS * PER_DAY // THIN and te.any():
            mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-12
            yhat[te] = RidgeCV(alphas=ALPHAS, fit_intercept=False).fit((X[tr] - mu) / sd, y[tr]).predict((X[te] - mu) / sd)
        a = a + step
    return yhat


def _ridge_task(X, z, t, s, h, window, draw_shifts, day, year):
    out = []
    for draw, n_days in draw_shifts:
        y = np.roll(z, int(n_days) * PER_DAY)
        yhat = walk_ridge(X, y, t, s, HORIZONS[h], window)
        r = ic_stats(yhat[s], y[s], day, day_lags(HORIZONS[h]), None if draw else {"year": year})
        row = {"horizon": h, "window": str(window or "all"), "draw": draw, "ic": r["ic"], "t": r["t"], "days": r["days"]}
        if draw == 0:
            row |= {str(k): v for k, v in r["year"].items()}
        out.append(row)
    return out


def forecast(D: dict, F: dict[str, pd.Series], signed: set[str], s: np.ndarray, draws: int = DRAWS, seed: int = 1, jobs: int = 1,
             horizons: tuple[str, ...] = (PRIMARY, "1d")) -> pd.DataFrame:
    from joblib import Parallel, delayed
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    year = pd.date_range(sidx[0].floor("D"), periods=int(day.max()) + 1, freq="D").year.to_numpy()
    X, t = design(D, F, signed), idx.tz_localize(None).to_numpy()
    sh = list(enumerate(shifts(len(idx) // PER_DAY, draws, seed)))
    chunks = [sh[i::max(1, min(jobs, 8))] for i in range(max(1, min(jobs, 8)))]
    tasks = [(h, w, c) for h in horizons for w in WINDOWS for c in chunks if c]
    res = Parallel(n_jobs=jobs, verbose=5)(delayed(_ridge_task)(X, D["z"][h].to_numpy(), t, s, h, w, c, day, year) for h, w, c in tasks)
    x = pd.DataFrame([r for part in res for r in part])
    rows = []
    for (h, w), g in x.groupby(["horizon", "window"], sort=False):
        real, null = g[g["draw"] == 0].iloc[0], g[g["draw"] > 0]
        yrs = {c: real[c] for c in g.columns if c.isdigit()}
        rows.append({"horizon": h, "window": w, "ic": real["ic"], "t": real["t"], "days": real["days"], "null_ic_sd": null["ic"].std(), "null_t_sd": null["t"].std(),
                     "p_one_sided": (1 + int((null["t"] >= real["t"]).sum())) / (len(null) + 1), "years_positive": int(sum(v > 0 for v in yrs.values())), **yrs})
    return pd.DataFrame(rows)


# ---- the money view ---------------------------------------------------------------------------------------
def cond_mean(y: np.ndarray, on: np.ndarray, day: np.ndarray, lags: int) -> dict:
    """Mean of y over the bars `on`, with a day-clustered (HAC) standard error of that ratio."""
    ok = on & ~np.isnan(y)
    nd = int(day.max()) + 1
    cnt, tot = np.bincount(day[ok], minlength=nd).astype(float), np.bincount(day[ok], y[ok], nd)
    if cnt.sum() < 50 or (cnt > 0).sum() < 5:
        return {"bars": int(cnt.sum()), "days": int((cnt > 0).sum()), "mean": np.nan, "se": np.nan}
    m = tot.sum() / cnt.sum()
    _, se, n = hac(tot - m * cnt, lags)
    return {"bars": int(cnt.sum()), "days": int((cnt > 0).sum()), "mean": float(m), "se": float(se * n / cnt.sum())}


def money_view(D: dict, F: dict[str, pd.Series], s: np.ndarray) -> pd.DataFrame:
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    yr = sidx.year.to_numpy()
    y, m4, tr = D["fwd"][PRIMARY].to_numpy()[s], F["mret_4h"].to_numpy()[s], F["mret_30d"].to_numpy()[s]
    states = {f"fall ≥ {FALL:g}σ in 4h": m4 <= -FALL, f"rise ≥ {FALL:g}σ in 4h": m4 >= FALL,
              f"broad fall (≥ {BROAD:.0%} of pairs down ≥ 1σ)": F["breadth_dn_4h"].to_numpy()[s] >= BROAD - 1e-12, "every bar": np.ones(len(y), dtype=bool)}
    rows = []
    for sname, on in states.items():
        for tname, tm in (("any", np.ones(len(y), dtype=bool)), ("30d trend up", tr > 0), ("30d trend down", tr < 0)):
            for period, pm in [("all", np.ones(len(y), dtype=bool)), *[(str(v), yr == v) for v in np.unique(yr)]]:
                rows.append({"state": sname, "trend": tname, "period": period, **cond_mean(y, on & tm & pm, day, day_lags(HORIZONS[PRIMARY]))})
    return pd.DataFrame(rows)


# ---- assemble -----------------------------------------------------------------------------------------------
def gate(sc: pd.DataFrame, fc: pd.DataFrame, mv: pd.DataFrame) -> list[str]:
    """R6's gate, evaluated mechanically from the tables (PLAN §8)."""
    need = mv[(mv["horizon"] == PRIMARY) & (((mv["exec"] == "maker") & (mv["bars"] == "all bars")) | ((mv["exec"] == "taker") & (mv["bars"] != "all bars")))]
    bar = float(need["ic_needed"].min())
    f = fc[(fc["horizon"] == PRIMARY) & (fc["window"] == str(GATE_WINDOW))].iloc[0]
    yrs = [c for c in fc.columns if c.isdigit()]
    fund = f["p_one_sided"] <= 0.05 and f["years_positive"] == len(yrs) and f["ic"] >= bar
    out = [f"- **Forecast (ridge, {GATE_WINDOW}-day window, {PRIMARY}):** IC {f['ic']:.4f} against a bar of {bar:.4f}; p {f['p_one_sided']:.3f}; positive in "
           f"{int(f['years_positive'])} of {len(yrs)} years → **{'FUND the basket forecast' if fund else 'NOT FUNDED'}**."]
    d = sc[(sc["bet"] == "directional") & (sc["horizon"] == PRIMARY)]
    stable = d[(d["p_fw"] <= 0.05) & (d["years_same_sign"] == len(yrs))]
    out.append("- **Single features, family-wise p ≤ 0.05 AND one sign in every year:** " +
               (", ".join(f"`{r['feature']}` (IC {r['ic']:+.4f}{', above the bar' if abs(r['ic']) >= bar else ''})" for _, r in stable.iterrows()) or "none") + ".")
    return out


def run(taker_bps: float, maker_bps: float, fee_source: str, symbols: list[str], fold_names=FOLDS, draws: int = DRAWS) -> str:
    from . import data
    from .backtest import PRE_START
    fold_names = folds.order(fold_names or FOLDS)
    if bad := [f for f in fold_names if f not in FOLDS]:
        raise SystemExit(f"ceiling reads exploration data only; refused: {bad}")
    end = folds.bounds(fold_names[-1])[1]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("panel…", flush=True)
    P = panel(symbols, end, PRE_START if set(fold_names) & set(folds.PREHISTORY) else pd.Timestamp(folds.FOLDS["F0"][0], tz="UTC"))
    idx, cols = P["close"].index, P["close"].columns
    D = derive(P)
    fu = data.load("funding_archive", columns=["symbol", "ts", "rate"], symbols=list(cols))
    fu = fu[fu["ts"] < end].assign(symbol=lambda x: x["symbol"].astype(str))
    F, signed = features(P, D, fu.pivot(index="ts", columns="symbol", values="rate") * 1e4)
    s = scored_mask(idx, fold_names)
    sidx = idx[s]
    jobs = int(os.environ.get("FT2_JOBS", os.cpu_count() or 1))
    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                           # noqa: E731
    print("#7 move vs cost…", flush=True)
    vr = F["volratio_4h"]
    mv = move_vs_cost(D, basket_cost(idx, cols, end, taker_bps, maker_bps), s, (vr >= vr[s].quantile(1 - TOP)).to_numpy())
    print(f"#3/#4 screen: {len(F)} features × {len(HZ)} horizons × 2 bets × {draws} shifts…", flush=True)
    sc, null = screen(D, F, signed, s, draws)
    print("#1 forecast…", flush=True)
    fc = forecast(D, F, signed, s, draws, jobs=jobs)
    print("money view…", flush=True)
    mo = money_view(D, F, s)
    for name, df in (("move_vs_cost", mv.assign(**{"from": mv["from"].astype(str)})), ("screen", sc), ("screen_null", null), ("forecast", fc), ("money_view", mo)):
        df.to_parquet(OUT_DIR / f"{name}.parquet", index=False)
    yrs = [c for c in sc.columns if c.isdigit()]
    md = ["# Ceiling audit for the market factor — measured (`ft2 ceiling --target basket`, registration R6)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
          f"\n**Folds read:** {'+'.join(fold_names)}; every source cut at {end:%Y-%m-%d}. Scored bars {sidx[0]:%Y-%m-%d} → {sidx[-1]:%Y-%m-%d} ({len(sidx):,}); "
          f"pairs in the basket {int(P['close'][s].notna().sum(axis=1).min())}–{int(P['close'][s].notna().sum(axis=1).max())}. Target: the equal-weight basket's forward log move.\n",
          f"\n**Fees (input):** taker {taker_bps} bps, maker {maker_bps} bps per side — {fee_source}. Spread and impact before 2023 are the candle proxy (`ft2 costpre`); "
          "maker adverse selection exists on tape days only (2023 →).\n",
          "\n## Verdict by R6's gate\n", *[g + "\n" for g in gate(sc, fc, mv)],
          "\n## #7 What a signal on the basket must clear\n", show(mv), "\n",
          f"\n## #3 + #4 The screen at {PRIMARY}, per year — directional\n",
          f"`t` = HAC t over days; `null_t_sd` = the spread of that t on {draws} circular shifts of the labels (1 = calibrated; slow features are not); `p_single` / `p_fw` = share "
          "of shifts whose |t| (of this feature / of the best feature of the screen) is at least the real one; the year columns are the same correlation within that year.\n"]
    top = lambda bet, h: sc[(sc["bet"] == bet) & (sc["horizon"] == h)].assign(a=lambda x: x["t"].abs()).sort_values("a", ascending=False).drop(columns=["a", "bet", "horizon"])  # noqa: E731
    md += [show(top("directional", PRIMARY)), "\n"]
    for h in [x for x in HZ if x != PRIMARY]:
        md += [f"\n### directional, {h} — top 8 by |t|\n", show(top("directional", h).head(8)), "\n"]
    md += ["\n### |move| (vol) — top 5 by |t| per horizon\n", *[f"\n{h}\n\n" + show(top("vol", h).head(5)[["feature", "ic", "t", "p_fw", "years_same_sign", *yrs]]) + "\n" for h in HZ],
           "\n## #1 The forecast — walk-forward ridge, no intercept, refitted every 30 days\n",
           "`p_one_sided` = share of shifts whose t is at least the real one (a negative IC is not usable, so one side).\n", show(fc), "\n",
           f"\n## The money view — the basket's mean next-{PRIMARY} move, bps before costs\n",
           "mean (t) [days with such bars]; blank = fewer than 50 bars or 5 days. Costs: the table of #7.\n"]
    cell = lambda r: "" if np.isnan(r["mean"]) else f"{r['mean']:+.1f} ({r['mean'] / r['se']:+.1f}) [{r['days']}]"   # noqa: E731
    md += [mo.assign(cell=mo.apply(cell, axis=1)).pivot(index=["state", "trend"], columns="period", values="cell")[["all", *yrs]].reset_index().to_markdown(index=False), "\n"]
    text = "\n".join(md)
    OUT_MD.write_text(text)
    return text
