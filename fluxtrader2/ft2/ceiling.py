"""P2 — the ceiling audit (PLAN §4 P2). `ft2 ceiling` → output/ceiling.md, output/ceiling/*.parquet.

How much signal is there, per bet type × horizon, before any model is built. Reads the
EXPLORATION folds only (F1+F2, embargoed) with F0 as training history: every source is cut at
END (the end of F2) when it is loaded, so nothing from a confirmation fold can enter a number
here, and a forward label never reaches past END (the last k bars of the panel have none).

The grid is the 5m candle, indexed by its DECISION TIME t = open_time + 5 min (the bar is
closed at t). A feature at t uses only data stamped strictly before t; a label at t is the
log return from the close at t to the close at t + h, in bps.

Bets:    directional  the pair's own forward return
         relative     the pair's forward return minus the equal-weight basket of the pairs
                      present at t (≥ MIN_PAIRS); a leg of a dollar-neutral book earns exactly this
         vol          the forward absolute move — a multiplier on the other two, not a bet
Horizons: 15m, 1h, 4h, 1d.

Items (PLAN P2's numbering):
  #7 move_vs_cost      share of bars whose |move| exceeds the P1 round trip (taker at NOTIONAL,
                       maker at 15 min) from data/cost_daily.parquet; the perfect-foresight net;
                       the hit rate and the rank IC a signal needs to break even
  #1 mag_vs_dir        walk-forward ridge (fit strictly before the fold, labels ending before it):
                       out-of-sample R² of |move| vs of the signed move; what trading only the top
                       decile of predicted magnitude does to the break-even
  #2 linear_structure  variance ratios (Lo–MacKinlay, heteroskedasticity-robust z), lag-1
                       autocorrelation of non-overlapping returns, raw and basket-residual;
                       the first principal component's share of cross-pair variance
  #3 ic_screen         rank IC of each candidate feature with each target, per day (no within-day demeaning),
                       HAC t-statistic over days, share of months agreeing in sign, and its MDE
  #6 power             bars, non-overlapping labels, days; the smallest per-trade mean (bps) a
                       strategy trading 10 % of bars could be told from zero (80 % power, 5 %)
  #4 noise_floor       #3's screen and #1's walk-forward direction ridge re-run on shuffled labels
                       (`_shuffle_days`: whole days trade places, whole rows move, so the market factor
                       the pairs share stays intact), DRAWS times, at 1h/4h/1d: what the best of 24 features, and the ridge,
                       reach on noise — the family-wise bar a measured IC has to clear
  #5 learning_curves   ridge vs a depth-2 boosted tree on the most recent 30 … all days before each
                       fold, 4h and 1d, both bets: in-sample vs out-of-sample IC (variance?), the
                       slope in days (data-limited?), tree minus ridge per day (interactions?)

A run of every item writes output/ceiling.md; a partial `--items` run writes
output/ceiling_items_<…>.md and never overwrites the full report.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds
from .cost import DAILY

OUT_MD = Path("output/ceiling.md")
OUT_DIR = Path("output/ceiling")

BAR = pd.Timedelta("5min")
HORIZONS = {"15m": 3, "1h": 12, "4h": 48, "1d": 288}          # in 5m bars
W = {"15m": 3, "1h": 12, "4h": 48, "1d": 288, "1w": 2016}     # lookbacks, in 5m bars
START = pd.Timestamp(folds.FOLDS["F0"][0], tz="UTC")
END = folds.bounds(folds.EXPLORATION[-1])[1]                  # nothing at or after this instant is read
MIN_PAIRS = 5            # a basket (and a cross-sectional rank) needs at least this many pairs at t
NOTIONAL = 10_000        # the taker round trip is priced at this size (cost_daily's imp_<N>)
MAKER_H = 15
TOP = 0.10               # "trade the top decile of signals"
Z_TOP = 1.755            # E[z | z > 90th percentile] for a standard normal
MDE_K = 2.80             # (z_0.975 + z_0.80): detectable effect = MDE_K × standard error
ALPHAS = [1.0, 1e2, 1e4, 1e6]
Z_CLIP = 5.0
DRAWS = 200                                  # #4: label shuffles
NULL_GAP = 8                                 # #4: days; ≥ the longest return lookback (1w) + the longest horizon (1d)
NULL_HORIZONS = ("1h", "4h", "1d")           # #4: the candidate / edge rows of #3 (15m is excluded on cost by #7)
LC_HORIZONS = ("4h", "1d")                   # #5
LC_DAYS = (30, 60, 120, 250)                 # #5: training windows in days, most recent first; then everything before the fold
LC_TREES = (50, 150, 300)                    # #5: the boosted tree is read at these sizes


# ---- the panel ---------------------------------------------------------------------------------
def panel(symbols: list[str], end: pd.Timestamp = END, start: pd.Timestamp = START) -> dict[str, pd.DataFrame]:
    """Wide frames (decision time × pair) of close/high/low/dollar volume, cut at `end` (the audit's END
    unless the harness, reading a registered fold, says otherwise). A `start` before the collector's
    history (the pre-history fold FP) puts the archive's klines under the collector's bars: wherever
    both have a bar, the collector's is the one used."""
    cols_ = ["symbol", "open_time", "high", "low", "close", "volume"]
    c = data.load("candles_5m", columns=cols_, symbols=symbols)
    if start < START:
        c = pd.concat([data.load("candles_5m_archive", columns=cols_, symbols=symbols), c], ignore_index=True)
        c["symbol"] = c["symbol"].astype(str)
        c = c.drop_duplicates(["symbol", "open_time"], keep="last")
    c["t"] = c["open_time"] + BAR
    c = c[(c["t"] >= start) & (c["t"] <= end)]
    c["symbol"] = c["symbol"].astype(str)
    c["dv"] = c["volume"] * c["close"]
    idx = pd.date_range(c["t"].min(), c["t"].max(), freq="5min", name="t")
    cols = [s for s in symbols if s in set(c["symbol"])]
    return {k: c.pivot(index="t", columns="symbol", values=k).reindex(index=idx, columns=cols) for k in ("close", "high", "low", "dv")}


def basket(x: pd.DataFrame) -> pd.Series:
    return x.mean(axis=1).where(x.notna().sum(axis=1) >= MIN_PAIRS)


def derive(P: dict[str, pd.DataFrame]) -> dict:
    lr = np.log(P["close"])
    r1 = lr.diff() * 1e4
    sig = {w: r1.rolling(k, min_periods=int(k * 0.8)).std() for w, k in W.items() if k >= 12}     # bps per 5m bar
    fwd = {h: (lr.shift(-k) - lr) * 1e4 for h, k in HORIZONS.items()}
    res = {h: f.sub(basket(f), axis=0) for h, f in fwd.items()}
    z = {h: (fwd[h] / (sig["1w"] * np.sqrt(k))) for h, k in HORIZONS.items()}                     # vol-standardised
    zres = {h: v.sub(basket(v), axis=0) for h, v in z.items()}
    t = pd.Series(lr.index, index=lr.index)
    scored = np.zeros(len(t), dtype=bool)
    for f in folds.EXPLORATION:
        scored |= folds.mask(t, f).to_numpy()
    return {"lr": lr, "r1": r1, "sig": sig, "fwd": fwd, "res": res, "z": z, "zres": zres, "scored": scored}


def bar_cost(index: pd.DatetimeIndex, cols: list[str], taker_bps: float, maker_bps: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Round trip per bar in bps from P1's pair × day series (the day of the decision time)."""
    d = pd.read_parquet(DAILY)
    d = d[d["day"] < END]
    d["symbol"] = d["symbol"].astype(str)
    d["taker"] = 2 * taker_bps + d["spread_cal_bps"] + 2 * d[f"imp_{NOTIONAL}"]
    d["maker"] = 2 * maker_bps - 2 * d[f"maker_adv_{MAKER_H}"]
    out = []
    for k in ("taker", "maker"):
        w = d.pivot(index="day", columns="symbol", values=k).reindex(columns=cols)
        out.append(pd.DataFrame(w.reindex(index.floor("D")).to_numpy(), index=index, columns=cols))
    return out[0], out[1]


# ---- statistics over days ----------------------------------------------------------------------
def hac(x: np.ndarray, lags: int) -> tuple[float, float, int]:
    """Mean, Newey–West (Bartlett) standard error of the mean, n — over a daily series."""
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 20:
        return np.nan, np.nan, n
    d = x - x.mean()
    v = d @ d / n
    for l in range(1, min(lags, n - 1) + 1):
        v += 2 * (1 - l / (lags + 1)) * (d[l:] @ d[:-l]) / n
    return float(x.mean()), float(np.sqrt(max(v, 0) / n)), n


def day_lags(k: int) -> int:
    return int(np.ceil(k / 288)) + 1          # labels of adjacent days overlap once the horizon crosses midnight


# ---- #7 move vs cost ----------------------------------------------------------------------------
def move_vs_cost(D: dict, ct: pd.DataFrame, cm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = D["scored"]
    t, m_ = ct[s].to_numpy(), cm[s].to_numpy()
    rows, per_pair = [], {}
    for bet, src in (("directional", D["fwd"]), ("relative", D["res"])):
        for h in HORIZONS:
            a = src[h][s].abs().to_numpy()
            ok = ~np.isnan(a) & ~np.isnan(t) & ~np.isnan(m_)
            mv, tk, mk = a[ok], t[ok], m_[ok]
            sd = mv.mean() * 1.2533                      # Gaussian-equivalent sd from the mean absolute move (tail-robust)
            rows.append({"bet": bet, "horizon": h, "cells": int(ok.sum()), "no_cost_share": float((~np.isnan(a) & ~ok).sum() / max((~np.isnan(a)).sum(), 1)),
                         "abs_move_p50": np.median(mv), "abs_move_mean": mv.mean(), "taker_rt": tk.mean(), "maker_rt": mk.mean(),
                         "share_gt_taker": (mv > tk).mean(), "share_gt_maker": (mv > mk).mean(),
                         "oracle_net_taker": np.maximum(mv - tk, 0).mean(), "oracle_net_maker": np.maximum(mv - mk, 0).mean(),
                         "hit_needed_taker": 0.5 + tk.mean() / (2 * mv.mean()), "hit_needed_maker": 0.5 + mk.mean() / (2 * mv.mean()),
                         "ic_needed_taker": tk.mean() / (Z_TOP * sd), "ic_needed_maker": mk.mean() / (Z_TOP * sd), "sd_equiv": sd})
            if bet == "directional":
                aa, tt = src[h][s].abs(), ct[s]
                per_pair[h] = ((aa > tt) & tt.notna()).sum() / (aa.notna() & tt.notna()).sum()
    return pd.DataFrame(rows), pd.DataFrame(per_pair)


# ---- #1 magnitude vs direction ------------------------------------------------------------------
def _cells(frames: list[pd.DataFrame]) -> np.ndarray:
    return np.column_stack([f.to_numpy().ravel() for f in frames])


def _walk_forward(X: np.ndarray, y: np.ndarray, t: np.ndarray, k: int, clip_q: float | None = None) -> np.ndarray:
    """Ridge fitted on cells whose label ends before the fold starts, scored on the (embargoed) fold."""
    from sklearn.linear_model import RidgeCV
    yhat = np.full(len(y), np.nan)
    valid = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    for f in folds.EXPLORATION:
        a, b = (np.datetime64(x.tz_localize(None)) for x in folds.bounds(f))
        tr_end = np.datetime64((folds.training_end(f) - k * BAR).tz_localize(None))
        tr, te = valid & (t < tr_end), valid & (t >= a) & (t < b)
        if tr.sum() < 1000 or te.sum() == 0:
            continue
        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-12
        ytr = y[tr] if clip_q is None else np.minimum(y[tr], np.quantile(y[tr], clip_q))
        model = RidgeCV(alphas=ALPHAS).fit((X[tr] - mu) / sd, ytr)
        yhat[te] = model.predict((X[te] - mu) / sd)
    return yhat


def dir_features(D: dict) -> dict[str, pd.DataFrame]:
    lr, sig = D["lr"], D["sig"]
    F = {f"ret_{w}": (lr - lr.shift(k)) * 1e4 / (sig["1w"] * np.sqrt(k)) for w, k in W.items()}
    for w in ("1h", "4h", "1d"):
        F[f"relret_{w}"] = F[f"ret_{w}"].sub(basket(F[f"ret_{w}"]), axis=0)
    F["volratio_1h"] = np.log(sig["1h"] / sig["1w"])
    F["volratio_1d"] = np.log(sig["1d"] / sig["1w"])
    return F


def _design(D: dict, F: dict[str, pd.DataFrame] | None = None) -> dict:
    """The (bar × pair) cells of the direction forecasts, shared by #1, #4 and #5: Xd for a pair's own
    move (the features and hour of day), Xr for the move against the basket (the features' deviations
    from their cross-sectional mean). F defaults to the candle features of `dir_features`."""
    idx, cols = D["lr"].index, D["lr"].columns
    hour = pd.DataFrame(np.repeat(idx.hour.to_numpy()[:, None], len(cols), 1) * (2 * np.pi / 24), index=idx, columns=cols)
    F = F or dir_features(D)
    own = [k for k in F if not k.startswith("relret")]
    return {"t": np.repeat(idx.tz_localize(None).to_numpy(), len(cols)), "pair": np.tile(np.arange(len(cols)), len(idx)),
            "day": np.repeat((idx.floor("D") - idx[0].floor("D")).days.to_numpy(), len(cols)), "scored": np.repeat(D["scored"], len(cols)),
            "Xd": _cells([*F.values(), np.sin(hour), np.cos(hour)]), "Xr": _cells([F[k].sub(basket(F[k]), axis=0) for k in own])}


def mag_vs_dir(D: dict, ct: pd.DataFrame, cm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx, cols = D["lr"].index, D["lr"].columns
    G = _design(D)
    t, pair, day, scored, Xd, Xr = (G[k] for k in ("t", "pair", "day", "scored", "Xd", "Xr"))
    tk, mk = ct.to_numpy().ravel(), cm.to_numpy().ravel()
    rows, mult = [], []
    for h, k in HORIZONS.items():
        # magnitude: |move| in bps from trailing volatilities scaled to the horizon (homogeneous, pooled over pairs)
        past_abs = ((D["lr"] - D["lr"].shift(k)) * 1e4).abs().rolling(W["1w"], min_periods=1000).mean()
        Xm = _cells([*(D["sig"][w] * np.sqrt(k) for w in D["sig"]), past_abs])
        y = D["fwd"][h].abs().to_numpy().ravel()
        yhat = _walk_forward(Xm, y, t, k, clip_q=0.999)
        ok = scored & ~np.isnan(yhat) & ~np.isnan(y)
        r2p = []
        for p in range(len(cols)):
            o = ok & (pair == p)
            if o.sum() > 1000:
                r2p.append(1 - ((y[o] - yhat[o]) ** 2).sum() / ((y[o] - y[o].mean()) ** 2).sum())
        wide = lambda v: pd.DataFrame(np.where(ok, v, np.nan).reshape(len(idx), len(cols)))      # noqa: E731
        ic, se, n = hac(_ic_pooled(_pair_rank(wide(yhat)).to_numpy().ravel(), _pair_rank(wide(y)).to_numpy().ravel(), day), day_lags(k))
        rows.append({"target": "magnitude |move|", "horizon": h, "cells": int(ok.sum()), "r2_oos": float(np.median(r2p)),
                     "r2_min_pair": float(np.min(r2p)), "r2_max_pair": float(np.max(r2p)), "rank_ic": ic, "ic_t": ic / se})
        # what the top decile of predicted magnitude (within pair) does to the break-even
        top = np.zeros(len(y), dtype=bool)
        for p in range(len(cols)):
            o = ok & (pair == p)
            if o.any():
                top |= o & (yhat >= np.quantile(yhat[o], 1 - TOP))
        for bet, src in (("directional", D["fwd"]), ("relative", D["res"])):
            a = np.abs(src[h].to_numpy().ravel())
            o_all, o_top = ok & ~np.isnan(a) & ~np.isnan(tk) & ~np.isnan(mk), top & ~np.isnan(a) & ~np.isnan(tk) & ~np.isnan(mk)
            mult.append({"bet": bet, "horizon": h, "abs_move_all": a[o_all].mean(), "abs_move_top": a[o_top].mean(),
                         "multiplier": a[o_top].mean() / a[o_all].mean(), "taker_rt_top": tk[o_top].mean(),
                         "hit_needed_taker_top": 0.5 + tk[o_top].mean() / (2 * a[o_top].mean()),
                         "hit_needed_maker_top": 0.5 + mk[o_top].mean() / (2 * a[o_top].mean()),
                         "ic_needed_taker_top": tk[o_top].mean() / (Z_TOP * 1.2533 * a[o_top].mean()),
                         "ic_needed_maker_top": mk[o_top].mean() / (Z_TOP * 1.2533 * a[o_top].mean())})
        # direction, own and relative: the vol-standardised move, clipped, against a zero forecast
        for name, X, tgt in (("direction (own)", Xd, D["z"][h]), ("direction (relative)", Xr, D["zres"][h])):
            y = np.clip(tgt.to_numpy().ravel(), -Z_CLIP, Z_CLIP)
            yhat = _walk_forward(X, y, t, k)
            ok = scored & ~np.isnan(yhat) & ~np.isnan(y)
            r2f = [1 - ((y[o] - yhat[o]) ** 2).sum() / (y[o] ** 2).sum()
                   for f in folds.EXPLORATION for o in [ok & (t >= np.datetime64(folds.bounds(f)[0].tz_localize(None)))
                                                        & (t < np.datetime64(folds.bounds(f)[1].tz_localize(None)))] if o.sum() > 1000]
            ic, se, n = hac(_ic_pooled(yhat[ok], y[ok], day[ok]), day_lags(k))
            rows.append({"target": name, "horizon": h, "cells": int(ok.sum()), "r2_oos": float(np.mean(r2f)), "r2_min_pair": float(np.min(r2f)),
                         "r2_max_pair": float(np.max(r2f)), "rank_ic": ic, "ic_t": ic / se})
    return pd.DataFrame(rows), pd.DataFrame(mult)


# ---- #2 raw linear structure --------------------------------------------------------------------
def variance_ratio(r: np.ndarray, q: int) -> tuple[float, float]:
    """Lo–MacKinlay VR(q) from the autocorrelations, with the heteroskedasticity-robust z."""
    r = r[~np.isnan(r)]
    d = r - r.mean()
    a, s2 = d * d, d @ d
    vr, var = 1.0, 0.0
    for j in range(1, q):
        w = 2 * (1 - j / q)
        vr += w * (d[j:] @ d[:-j]) / s2
        var += w * w * (a[j:] @ a[:-j]) / (s2 * s2)
    return float(vr), float((vr - 1) / np.sqrt(var))


def linear_structure(D: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = D["scored"]
    r1 = D["r1"][s]
    series = {"raw": r1, "residual": r1.sub(basket(r1), axis=0)}
    rows = []
    for kind, x in series.items():
        for sym in x.columns:
            v = x[sym].to_numpy()
            v = v[~np.isnan(v)]
            if len(v) < 5_000:
                continue
            for h, k in HORIZONS.items():
                vr, zz = variance_ratio(v, k)
                nb = v[: len(v) // k * k].reshape(-1, k).sum(1)                 # non-overlapping h-returns
                ac = float(np.corrcoef(nb[1:], nb[:-1])[0, 1])
                rows.append({"series": kind, "symbol": sym, "horizon": h, "vr": vr, "vr_z": zz, "ac1": ac, "ac1_z": ac * np.sqrt(len(nb) - 1)})
    pcs = []
    t = pd.Series(D["r1"].index, index=D["r1"].index)
    for f in folds.EXPLORATION:
        x = D["r1"][folds.mask(t, f).to_numpy()]
        x = x.loc[:, x.notna().mean() > 0.99].fillna(0.0)                       # pairs present for the whole fold
        if len(x) < 5_000 or x.shape[1] < 3:
            continue
        for h, k in HORIZONS.items():
            nb = x.to_numpy()[: len(x) // k * k].reshape(-1, k, x.shape[1]).sum(1)
            c = np.corrcoef(nb.T)
            ev = np.linalg.eigvalsh(c)
            pcs.append({"fold": f, "horizon": h, "pairs": x.shape[1], "obs": len(nb), "pc1_share": float(ev[-1] / ev.sum()),
                        "mean_pair_corr": float((c.sum() - len(c)) / (len(c) * (len(c) - 1)))})
    return pd.DataFrame(rows), pd.DataFrame(pcs)


# ---- #3 rank IC screen --------------------------------------------------------------------------
def _pair_rank(x: pd.DataFrame) -> pd.DataFrame:
    """Each pair's column → its rank over the sample, in (−0.5, 0.5]: a fixed monotone map, robust to tails."""
    return x.rank(pct=True) - 0.5


def _ic_pooled(f: np.ndarray, y: np.ndarray, day: np.ndarray) -> np.ndarray:
    """Each day's share of the WHOLE-SAMPLE uncentred correlation Σ f·y / √(Σf² Σy²) over every (bar, pair)
    cell: the day's Σ f·y × (number of days) / the sample's √(Σf² Σy²). The mean over days IS that
    correlation, and its HAC t is the day-clustered t of the sums.

    Nothing is ranked, demeaned or NORMALISED inside the day — two defects, both found on random walks:
    (1) a within-day Spearman: feature and label share the price at t (f = p_t − p_{t−k}, y = p_{t+h} − p_t),
    and removing the day's mean of y — which holds future prices — makes them negatively correlated (the
    first run of this audit, 2026-09-20, read −0.2 at 1d from exactly that; voided). (2) a per-day
    normaliser √(Σ_day f² Σ_day y²): it is largest on the days that trend, i.e. on the days whose products
    are positive, so the mean of per-day correlations of a trailing return reads −0.02 … −0.03 on
    correlated random walks (found 2026-09-21; every P2 number read before that date carries it).
    Inputs must come with a natural zero: `_pair_rank` for features, the vol-standardised move itself."""
    ok = ~(np.isnan(f) | np.isnan(y))
    nd = int(day.max()) + 1 if len(day) else 0
    d, ff, yy = day[ok], f[ok], y[ok]
    use = np.bincount(d, minlength=nd) >= 100
    num, sf, sy = np.bincount(d, ff * yy, nd), np.bincount(d, ff * ff, nd), np.bincount(d, yy * yy, nd)
    norm = np.sqrt(sf[use].sum() * sy[use].sum())
    with np.errstate(invalid="ignore", divide="ignore"):
        ic = num * use.sum() / norm
    ic[~use] = np.nan
    return ic


def _ic_xs(F: pd.DataFrame, Y: pd.DataFrame, day: np.ndarray) -> np.ndarray:
    """Spearman per bar across the pairs present (≥ MIN_PAIRS), averaged per day."""
    ok = F.notna() & Y.notna()
    rf, ry = F.where(ok).rank(axis=1).to_numpy(), Y.where(ok).rank(axis=1).to_numpy()
    n = ok.sum(axis=1).to_numpy().astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mf, my = np.nansum(rf, 1) / n, np.nansum(ry, 1) / n
        cov = np.nansum(rf * ry, 1) / n - mf * my
        vf, vy = np.nansum(rf * rf, 1) / n - mf ** 2, np.nansum(ry * ry, 1) / n - my ** 2
        ic = cov / np.sqrt(vf * vy)
    ic[(n < MIN_PAIRS) | ~np.isfinite(ic)] = np.nan
    return pd.Series(ic).groupby(day).mean().reindex(range(int(day.max()) + 1)).to_numpy()


def features(P: dict, D: dict, symbols: list[str]) -> tuple[dict[str, pd.DataFrame], set[str], list[str]]:
    """Candidate features, all scale-free and known strictly before the decision time.
    Returns (features, the unsigned ones — used as they are for the vol target; the signed ones
    enter it as absolute values —, notes about sources that were absent)."""
    idx, cols, sig = D["lr"].index, list(D["lr"].columns), D["sig"]
    F = dir_features(D)
    unsigned = {"volratio_1h", "volratio_1d"}
    hi, lo = P["high"].rolling(288, min_periods=200).max(), P["low"].rolling(288, min_periods=200).min()
    F["rangepos_1d"] = (P["close"] - lo) / (hi - lo) - 0.5
    F["dvol_1h"] = np.log(P["dv"].rolling(12).sum() / (P["dv"].rolling(2016, min_periods=1000).sum() / 168))
    unsigned.add("dvol_1h")
    notes = []
    empty = lambda: pd.DataFrame(np.nan, index=idx, columns=cols)                       # noqa: E731
    # tape: minute rows [ts, ts+1min) → 5m bins labelled by their right edge (complete at t)
    flow, spr = {w: empty() for w in ("1h", "1d")}, empty()
    try:
        for sym in cols:
            tp = data.load("tape", columns=["ts", "buy_vol", "sell_vol", "volume", "eff_spread_bps"], symbols=[sym])
            tp = tp[tp["ts"] < END].set_index("ts")
            b = tp.resample("5min", label="right", closed="left").agg({"buy_vol": "sum", "sell_vol": "sum", "volume": "sum",
                                                                        "eff_spread_bps": "mean"}).reindex(idx)
            for w in flow:
                flow[w][sym] = ((b["buy_vol"] - b["sell_vol"]).rolling(W[w]).sum() / b["volume"].rolling(W[w]).sum().replace(0, np.nan))
            spr[sym] = np.log(b["eff_spread_bps"].rolling(12, min_periods=6).mean() / b["eff_spread_bps"].rolling(2016, min_periods=1000).mean())
        F["flow_1h"], F["flow_1d"], F["spread_1h"] = flow["1h"], flow["1d"], spr
        unsigned.add("spread_1h")
    except (FileNotFoundError, ValueError):
        notes.append("tape absent: flow_*, spread_1h skipped")
    # archive metrics, 5m: the row stamped ts is used from ts + 5 min (strictly before the decision)
    try:
        m = data.load("metrics", symbols=cols)
        m = m[m["ts"] < END]
        m["symbol"] = m["symbol"].astype(str)
        wide = lambda c: (m.pivot(index="ts", columns="symbol", values=c).shift(freq=BAR).reindex(index=idx, columns=cols).ffill(limit=3))  # noqa: E731
        oi = np.log(wide("oi").where(lambda x: x > 0))
        F["oi_chg_1h"], F["oi_chg_1d"] = oi.diff(12), oi.diff(288)
        for name, c in (("global_ls_z", "global_ls"), ("top_ls_z", "top_ls_sum")):
            x = np.log(wide(c).where(lambda v: v > 0))
            F[name] = (x - x.rolling(2016, min_periods=1000).mean()) / x.rolling(2016, min_periods=1000).std()
        F["taker_ratio_1h"] = np.log(wide("taker_ratio").where(lambda v: v > 0)).rolling(12, min_periods=6).mean()
    except (FileNotFoundError, ValueError):
        notes.append("metrics absent: oi_chg_*, *_ls_z, taker_ratio_1h skipped")
    # archive depth, ~30 s: the last sample strictly before t
    try:
        imb1, imb5, lvl = empty(), empty(), empty()
        for sym in cols:
            dp = data.load("depth", columns=["ts", "usd_m1", "usd_p1", "usd_m5", "usd_p5"], symbols=[sym])
            dp = dp[dp["ts"] < END].set_index("ts").resample("5min", label="right", closed="left").last().reindex(idx)
            imb1[sym] = (dp["usd_m1"] - dp["usd_p1"]) / (dp["usd_m1"] + dp["usd_p1"])
            imb5[sym] = (dp["usd_m5"] - dp["usd_p5"]) / (dp["usd_m5"] + dp["usd_p5"])
            d1 = dp["usd_m1"] + dp["usd_p1"]
            lvl[sym] = np.log(d1 / d1.rolling(2016, min_periods=1000).mean())
        F["depth_imb_1"], F["depth_imb_5"], F["depth_lvl_1"] = imb1, imb5, lvl
        unsigned.add("depth_lvl_1")
    except (FileNotFoundError, ValueError):
        notes.append("depth absent: depth_* skipped")
    # funding: the last settled rate, usable from the bar after the funding time
    try:
        fu = data.load("funding_archive", symbols=cols)
        fu = fu[fu["ts"] < END]
        fu["symbol"] = fu["symbol"].astype(str)
        fw = fu.pivot(index="ts", columns="symbol", values="rate").reindex(columns=cols) * 1e4
        F["funding_last"] = fw.reindex(idx.union(fw.index)).ffill().reindex(idx).shift(1)
    except (FileNotFoundError, ValueError):
        notes.append("funding_archive absent: funding_last skipped")
    F = {k: v.replace([np.inf, -np.inf], np.nan) for k, v in F.items()}
    return F, unsigned, notes


def ic_screen(D: dict, F: dict[str, pd.DataFrame], unsigned: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    s, idx = D["scored"], D["lr"].index
    sidx = idx[s]
    day1 = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    dates = pd.date_range(sidx[0].floor("D"), periods=int(day1.max()) + 1, freq="D")
    month = dates.to_period("M") if dates.tz is None else dates.tz_localize(None).to_period("M")
    ncol = D["lr"].shape[1]
    dayc = np.repeat(day1, ncol)
    rows, daily = [], []
    for name, f in F.items():
        fs = f[s]
        fv, fa = _pair_rank(fs).to_numpy().ravel(), _pair_rank(fs if name in unsigned else fs.abs()).to_numpy().ravel()
        for h, k in HORIZONS.items():
            zs, zr = D["z"][h][s], D["zres"][h][s]
            series = {"directional": _ic_pooled(fv, zs.clip(-Z_CLIP, Z_CLIP).to_numpy().ravel(), dayc),
                      "vol": _ic_pooled(fa, _pair_rank(zs.abs()).to_numpy().ravel(), dayc)}
            if not name.startswith("relret_"):                  # a cross-sectional rank is unchanged by removing the basket
                series["relative"] = _ic_xs(fs, zr, day1)
            for bet, ic in series.items():
                mean, se, n = hac(ic, day_lags(k))
                mm = pd.Series(ic).groupby(np.asarray(month)).mean().dropna()
                rows.append({"bet": bet, "horizon": h, "feature": name, "ic": mean, "t": mean / se if se else np.nan, "days": n,
                             "months_same_sign": float((np.sign(mm) == np.sign(mean)).mean()) if len(mm) else np.nan,
                             "ic_mde": MDE_K * se})
                daily.append(pd.DataFrame({"bet": bet, "horizon": h, "feature": name, "day": dates, "ic": ic}))
    return pd.DataFrame(rows), pd.concat(daily, ignore_index=True)


# ---- #6 effective sample size and detectable effect ---------------------------------------------
def power(D: dict) -> pd.DataFrame:
    s, idx = D["scored"], D["lr"].index
    sidx = idx[s]
    day = np.repeat((sidx.floor("D") - sidx[0].floor("D")).days.to_numpy(), D["lr"].shape[1])
    rng = np.random.default_rng(0)
    rows = []
    for bet, src in (("directional", D["fwd"]), ("relative", D["res"])):
        for h, k in HORIZONS.items():
            m = src[h][s].to_numpy().ravel()
            ok = ~np.isnan(m)
            # a strategy with no skill trading TOP of the cells: random cells, random side; its daily P&L is the null
            se = []
            for _ in range(20):
                pick = ok & (rng.random(len(m)) < TOP)
                pnl = np.bincount(day[pick], m[pick] * rng.choice([-1.0, 1.0], pick.sum()), int(day.max()) + 1)
                _, se_d, nd = hac(pnl, day_lags(k))
                se.append(se_d * nd / pick.sum())
            rows.append({"bet": bet, "horizon": h, "cells": int(ok.sum()), "non_overlapping": int(ok.sum() / k), "days": int(len(np.unique(day[ok]))),
                         "trades_at_top_decile": int(ok.sum() * TOP), "mde_bps_per_trade": MDE_K * float(np.mean(se))})
    return pd.DataFrame(rows)


# ---- #4 noise floor -------------------------------------------------------------------------------
def _shuffle_days(idx: pd.DatetimeIndex, group: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Row indexer for a label null: the label at row i is taken from row src[i]. Whole days trade
    places, time of day kept, only with days of the same `group` (scored / not scored), and whole rows
    move — the market factor every pair shares at one instant, and a label's overlap with its
    neighbours inside the day, stay intact; every link to the features is broken.

    A day never receives the labels of one of the NULL_GAP days before it: such a label's window lies
    inside the trailing-return features' lookback, and the feature would then contain the label.
    (That is why the plan's first idea, shuffling rows WITHIN a day, is not used: a label moved to a
    later bar of its own day always overlaps the features — a 4-draw trial on 2026-09-20 read an IC
    of +0.09 … +0.18 for the ridge from that leak alone.)"""
    day = (idx.floor("D") - idx[0].floor("D")).days.to_numpy()
    per_day = int(pd.Timedelta("1D") / BAR)
    slot = ((idx - idx.floor("D")) // BAR).to_numpy()
    nd = int(day.max()) + 1
    row_of = np.full((nd, per_day), -1)
    row_of[day, slot] = np.arange(len(idx))
    n_rows, n_in = np.bincount(day, minlength=nd), np.bincount(day, weights=group, minlength=nd)
    src_day = np.arange(nd)
    for members in (n_in == per_day, (n_in == 0) & (n_rows == per_day)):           # partial days stay where they are
        ids = np.flatnonzero(members)
        src_day[ids] = rng.permutation(ids)
        while len(bad := ids[(ids - src_day[ids] > 0) & (ids - src_day[ids] <= NULL_GAP)]):
            for d in bad:
                o = rng.choice(ids)
                src_day[d], src_day[o] = src_day[o], src_day[d]
    return row_of[src_day[day], slot]


def _null_feature(name: str, fs: pd.DataFrame, Zs: dict, Zr: dict, draws: int, seed: int) -> pd.DataFrame:
    """One feature of #3's screen — the same statistics — on the real labels (draw 0) and on `draws`
    shuffles. Shuffle number `draw` is the same for every feature, so the best of the screen can be
    taken per draw."""
    sidx = fs.index
    day1 = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    dayc = np.repeat(day1, fs.shape[1])
    fv = _pair_rank(fs).to_numpy().ravel()
    rows = []
    for draw in range(draws + 1):
        src = _shuffle_days(sidx, np.ones(len(sidx)), np.random.default_rng([seed, draw])) if draw else np.arange(len(sidx))
        for h in Zs:
            series = {"directional": _ic_pooled(fv, Zs[h][src].ravel(), dayc)}
            if not name.startswith("relret_"):
                series["relative"] = _ic_xs(fs, pd.DataFrame(Zr[h][src], index=sidx, columns=fs.columns), day1)
            for bet, ic in series.items():
                mean, se, _ = hac(ic, day_lags(HORIZONS[h]))
                rows.append({"bet": bet, "horizon": h, "feature": name, "draw": draw, "ic": mean, "t": mean / se if se else np.nan})
    return pd.DataFrame(rows)


def _null_ridge(X: np.ndarray, yw: np.ndarray, G: dict, idx: pd.DatetimeIndex, group: np.ndarray, k: int, draws: list[int], seed: int) -> list[tuple]:
    """#1's walk-forward direction ridge, refitted on shuffled labels (training history included)."""
    out = []
    for draw in draws:
        src = _shuffle_days(idx, group, np.random.default_rng([seed, draw])) if draw else np.arange(len(idx))
        y = yw[src].ravel()
        yhat = _walk_forward(X, y, G["t"], k)
        ok = G["scored"] & ~np.isnan(yhat) & ~np.isnan(y)
        ic, se, _ = hac(_ic_pooled(yhat[ok], y[ok], G["day"][ok]), day_lags(k))
        out.append((draw, ic, ic / se if se else np.nan))
    return out


def noise_floor(D: dict, F: dict[str, pd.DataFrame], draws: int = DRAWS, jobs: int = 1, seed: int = 0,
                horizons: tuple[str, ...] = NULL_HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    from joblib import Parallel, delayed
    s, idx = D["scored"], D["lr"].index
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in horizons}
    Zr = {h: D["zres"][h][s].to_numpy() for h in horizons}
    print(f"#4 noise floor: screen, {len(F)} features × {len(horizons)} horizons × {draws} draws…", flush=True)
    nic = pd.concat(Parallel(n_jobs=jobs, verbose=5)(delayed(_null_feature)(name, f[s], Zs, Zr, draws, seed) for name, f in F.items()), ignore_index=True)
    G = _design(D)
    X, G = {"directional": G["Xd"], "relative": G["Xr"]}, {k: G[k] for k in ("t", "day", "scored")}
    chunks = [list(c) for c in np.array_split(np.arange(1, draws + 1), max(1, draws // 10))]
    chunks[0] = [0, *chunks[0]]
    tasks = [(bet, h, c) for bet in ("directional", "relative") for h in horizons for c in chunks]
    yw = {("directional", h): np.clip(D["z"][h].to_numpy(), -Z_CLIP, Z_CLIP) for h in horizons}
    yw |= {("relative", h): np.clip(D["zres"][h].to_numpy(), -Z_CLIP, Z_CLIP) for h in horizons}
    print(f"#4 noise floor: walk-forward ridge, {len(tasks)} tasks of ≤ {len(chunks[0])} draws…", flush=True)
    res = Parallel(n_jobs=jobs, verbose=5)(delayed(_null_ridge)(X[bet], yw[bet, h], G, idx, s.astype(float), HORIZONS[h], c, seed) for bet, h, c in tasks)
    nr = pd.DataFrame([{"bet": bet, "horizon": h, "draw": d, "ic": ic, "t": t_} for (bet, h, _), part in zip(tasks, res) for d, ic, t_ in part])
    return nic, nr


def floor_tables(nic: pd.DataFrame, nr: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(the screen per bet × horizon, every feature with its single and family-wise p, the ridge)."""
    screen, feats, ridge = [], [], []
    for (bet, h), x in nic.dropna(subset=["t"]).groupby(["bet", "horizon"], sort=False):
        real, null = x[x["draw"] == 0], x[x["draw"] > 0]
        mx = null.assign(a=null["t"].abs(), b=null["ic"].abs()).groupby("draw")[["a", "b"]].max()
        best = real.loc[real["t"].abs().idxmax()]
        p_fw = lambda t_: (1 + int((mx["a"] >= abs(t_)).sum())) / (len(mx) + 1)               # noqa: E731
        screen.append({"bet": bet, "horizon": h, "features": len(real), "draws": len(mx), "best_feature": best["feature"], "ic": best["ic"], "t": best["t"],
                       "null_t_sd": null["t"].std(), "bar_t_p95": mx["a"].quantile(0.95), "floor_ic_p95": mx["b"].quantile(0.95),
                       "p_fw": p_fw(best["t"]), "n_clear": int((real["t"].abs() > mx["a"].quantile(0.95)).sum())})
        for _, r in real.iterrows():
            own = null.loc[null["feature"] == r["feature"]]
            feats.append({"bet": bet, "horizon": h, "feature": r["feature"], "ic": r["ic"], "t": r["t"], "null_ic_sd": own["ic"].std(),
                          "p_single": (1 + int((own["t"].abs() >= abs(r["t"])).sum())) / (len(own) + 1), "p_fw": p_fw(r["t"])})
    for (bet, h), x in nr.groupby(["bet", "horizon"], sort=False):
        real, null = x[x["draw"] == 0].iloc[0], x[x["draw"] > 0]
        ridge.append({"bet": bet, "horizon": h, "draws": len(null), "ic": real["ic"], "t": real["t"], "null_ic_mean": null["ic"].mean(),
                      "null_ic_sd": null["ic"].std(), "null_t_sd": null["t"].std(), "floor_ic_p95": null["ic"].abs().quantile(0.95),
                      "p": (1 + int((null["t"].abs() >= abs(real["t"])).sum())) / (len(null) + 1)})
    return pd.DataFrame(screen), pd.DataFrame(feats), pd.DataFrame(ridge)


# ---- #5 learning curves ---------------------------------------------------------------------------
def learning_curves(D: dict, F: dict[str, pd.DataFrame], horizons: tuple[str, ...] = LC_HORIZONS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Ridge (as #1) and a depth-2 boosted tree, fitted on the most recent L days before each fold
    and scored on the fold, on the candle features of #1 and on every feature of #3 (rows with a
    missing feature dropped for both models). Returns (per fold, pooled over folds)."""
    import lightgbm as lgb
    from sklearn.linear_model import RidgeCV
    rows, daily = [], {}
    for sname, G in (("candle", _design(D)), ("all", _design(D, F))):
        t, day = G["t"], G["day"]
        for bet, X, tgt in (("directional", G["Xd"], D["z"]), ("relative", G["Xr"], D["zres"])):
            finite = ~np.isnan(X).any(axis=1)
            for h in horizons:
                k = HORIZONS[h]
                y = np.clip(tgt[h].to_numpy().ravel(), -Z_CLIP, Z_CLIP)
                valid = finite & ~np.isnan(y)
                for f in folds.EXPLORATION:
                    a, b = (np.datetime64(x.tz_localize(None)) for x in folds.bounds(f))
                    tr_end = np.datetime64((folds.training_end(f) - k * BAR).tz_localize(None))
                    te = valid & (t >= a) & (t < b)
                    avail = (tr_end - t[valid].min()) / np.timedelta64(1, "D")           # days of usable history before the fold
                    for L in [*[d for d in LC_DAYS if d <= 0.9 * avail], None]:
                        tr = valid & (t < tr_end) & ((t >= tr_end - np.timedelta64(L, "D")) if L else True)
                        if tr.sum() < 1000 or not te.any():
                            continue
                        print(f"#5 {sname} {bet} {h} {f} window={L or 'all'} train cells={tr.sum():,}", flush=True)
                        mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-12
                        ridge = RidgeCV(alphas=ALPHAS).fit((X[tr] - mu) / sd, y[tr])
                        tree = lgb.LGBMRegressor(n_estimators=max(LC_TREES), learning_rate=0.05, max_depth=2, num_leaves=4, min_child_samples=1000,
                                                 reg_lambda=10.0, deterministic=True, force_row_wise=True, random_state=0, verbose=-1).fit(X[tr], y[tr])
                        either = tr | te
                        preds = {"ridge": ridge.predict((X[either] - mu) / sd)} | {f"tree{n}": tree.predict(X[either], num_iteration=n) for n in LC_TREES}
                        for model, p in preds.items():
                            yhat = np.full(len(y), np.nan)
                            yhat[either] = p
                            ic_in, ic_out = _ic_pooled(np.where(tr, yhat, np.nan), y, day), _ic_pooled(np.where(te, yhat, np.nan), y, day)
                            key = (sname, bet, h, model, str(L or "all"))
                            for side, ic in (("in", ic_in), ("out", ic_out)):
                                prev = daily.get((*key, side))
                                daily[(*key, side)] = ic if prev is None else np.where(np.isnan(prev), ic, prev)
                            m_out, se_out, _ = hac(ic_out, day_lags(k))
                            rows.append({"features": sname, "bet": bet, "horizon": h, "model": model, "window": str(L or "all"), "fold": f,
                                         "train_days": float(min(L or avail, avail)), "train_cells": int(tr.sum()), "ic_in": float(np.nanmean(ic_in)),
                                         "ic_out": m_out, "t_out": m_out / se_out if se_out else np.nan,
                                         "r2_out": float(1 - ((y[te] - yhat[te]) ** 2).sum() / (y[te] ** 2).sum())})
    per_fold = pd.DataFrame(rows)
    pooled = []
    for (sname, bet, h, window), x in per_fold.groupby(["features", "bet", "horizon", "window"], sort=False):
        lags = day_lags(HORIZONS[h])
        r = {"features": sname, "bet": bet, "horizon": h, "window": window, "folds": "+".join(x["fold"].unique())}
        for model in ("ridge", f"tree{max(LC_TREES)}"):
            m, se, _ = hac(daily[(sname, bet, h, model, window, "out")], lags)
            r |= {f"{model}_in": float(np.nanmean(daily[(sname, bet, h, model, window, "in")])), f"{model}_out": m, f"{model}_t": m / se if se else np.nan}
        for n in LC_TREES[:-1]:
            r[f"tree{n}_out"] = float(np.nanmean(daily[(sname, bet, h, f"tree{n}", window, "out")]))
        m, se, _ = hac(daily[(sname, bet, h, f"tree{max(LC_TREES)}", window, "out")] - daily[(sname, bet, h, "ridge", window, "out")], lags)
        r |= {"tree_minus_ridge": m, "tree_minus_ridge_t": m / se if se else np.nan}
        pooled.append(r)
    return per_fold, pd.DataFrame(pooled)


# ---- assemble -------------------------------------------------------------------------------------
ITEMS = ["7", "1", "2", "3", "6", "4", "5"]


def run(taker_bps: float, maker_bps: float, fee_source: str, symbols: list[str], items: list[str] | None = None, draws: int = DRAWS) -> str:
    items = items or ITEMS
    out_md = OUT_MD if set(items) >= set(ITEMS) else OUT_MD.with_name(f"ceiling_items_{'_'.join(items)}.md")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("panel…", flush=True)
    P = panel(symbols)
    D = derive(P)
    idx, cols = D["lr"].index, list(D["lr"].columns)
    ct, cm = bar_cost(idx, cols, taker_bps, maker_bps)
    sidx = idx[D["scored"]]
    show = lambda df, digits=3: df.round(digits).to_markdown(index=False)                  # noqa: E731
    md = ["# Ceiling audit — measured (`ft2 ceiling`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
          f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed), F0 as training history only; every source cut at {END:%Y-%m-%d}. "
          f"Scored bars {sidx[0]:%Y-%m-%d} → {sidx[-1]:%Y-%m-%d} ({len(sidx):,} × {len(cols)} pairs).\n",
          f"\n**Fees (input):** taker {taker_bps} bps, maker {maker_bps} bps per side — {fee_source}. Taker round trip priced at "
          f"{NOTIONAL:,} USDT, maker at a {MAKER_H}-minute rest (P1, `data/cost_daily.parquet`, the decision day's row).\n"]
    summary = None
    if "7" in items:
        print("#7 move vs cost…", flush=True)
        mv, mv_pair = move_vs_cost(D, ct, cm)
        mv.to_parquet(OUT_DIR / "move_vs_cost.parquet", index=False)
        summary = mv[["bet", "horizon", "taker_rt", "maker_rt", "abs_move_mean", "hit_needed_taker", "hit_needed_maker",
                      "ic_needed_taker", "ic_needed_maker"]]
        md += ["\n## #7 Move vs cost\n",
               "All bps. `share_gt_*` = share of bars whose absolute move over the horizon exceeds the round trip; `oracle_net_*` = mean per bar of "
               "max(|move| − cost, 0), what perfect foresight would net; `hit_needed_*` = the share of correct sides a trade-every-bar sign bet "
               "needs to break even, 0.5 + cost / (2·mean|move|); `ic_needed_*` = the correlation between a signal and the move at which trading "
               f"the top {TOP:.0%} of signals breaks even, cost / ({Z_TOP}·sd) with sd = 1.2533·mean|move| (Gaussian approximation). "
               "`no_cost_share` = cells with a move but no priced cost (censored impact), left out.\n", show(mv), "\n",
               "\n### Directional, per pair: share of bars whose |move| exceeds the taker round trip\n", mv_pair.round(3).to_markdown(), "\n"]
    if "1" in items:
        print("#1 magnitude vs direction…", flush=True)
        r2, mult = mag_vs_dir(D, ct, cm)
        r2.to_parquet(OUT_DIR / "mag_vs_dir.parquet", index=False)
        mult.to_parquet(OUT_DIR / "vol_timing.parquet", index=False)
        md += ["\n## #1 Magnitude vs direction — walk-forward ridge, out of sample\n",
               "Magnitude: |move| in bps from four trailing volatilities and the trailing mean |move|; R² per pair against that pair's own fold "
               "mean (median / min / max over pairs). Direction: the move divided by trailing 1-week volatility, clipped at ±5, from trailing "
               "returns, volatility ratios and hour of day (own) or their cross-sectional deviations (relative); R² against a zero forecast "
               "(mean / min / max over the two folds). `rank_ic` = daily Spearman of forecast and outcome, HAC t over days.\n", show(r2, 4), "\n",
               f"\n### What trading only the top {TOP:.0%} of predicted magnitude (within pair) does to the break-even\n", show(mult), "\n"]
    if "2" in items:
        print("#2 linear structure…", flush=True)
        ls, pcs = linear_structure(D)
        ls.to_parquet(OUT_DIR / "linear_structure.parquet", index=False)
        agg = ls.groupby(["series", "horizon"], sort=False).agg(pairs=("vr", "size"), vr_median=("vr", "median"), vr_min=("vr", "min"), vr_max=("vr", "max"),
                                                                 vr_z_gt2=("vr_z", lambda z: int((z > 2).sum())), vr_z_lt_m2=("vr_z", lambda z: int((z < -2).sum())),
                                                                 ac1_median=("ac1", "median"), ac1_z_abs_gt2=("ac1_z", lambda z: int((z.abs() > 2).sum()))).reset_index()
        md += ["\n## #2 Raw linear structure\n",
               "Variance ratio of h-returns to 5m returns (1 = random walk, < 1 = mean reversion, > 1 = momentum), robust z; lag-1 autocorrelation "
               "of non-overlapping h-returns. `raw` = the pair's own return, `residual` = minus the basket.\n", show(agg), "\n",
               "\n### Per pair: VR (robust z)\n",
               show(ls.assign(cell=ls["vr"].round(3).astype(str) + " (" + ls["vr_z"].round(1).astype(str) + ")")
                    .pivot(index=["series", "symbol"], columns="horizon", values="cell")[list(HORIZONS)].reset_index()), "\n",
               "\n### How much is 'the market': first principal component of the pairs' h-returns\n", show(pcs), "\n"]
    if {"3", "4", "5"} & set(items):
        print("features…", flush=True)
        F, unsigned, notes = features(P, D, symbols)
    if "3" in items:
        print(f"#3 IC screen: {len(F)} features × {len(HORIZONS)} horizons × 3 bets…", flush=True)
        ic, ic_daily = ic_screen(D, F, unsigned)
        ic.to_parquet(OUT_DIR / "ic.parquet", index=False)
        ic_daily.to_parquet(OUT_DIR / "ic_daily.parquet", index=False)
        n_tests = int(ic["t"].notna().sum())
        from scipy.stats import norm
        bonf = float(norm.isf(0.025 / max(n_tests, 1)))
        md += ["\n## #3 Rank IC screen\n",
               "Daily correlation between the feature at t and the vol-standardised forward move. Directional: the feature as its per-pair rank "
               "over the sample, the move clipped at ±5, uncentred correlation over the day's bars and pairs — nothing is demeaned inside the day "
               "(see `_ic_pooled`). Relative: Spearman across pairs per bar, averaged per day, both sides relative to the basket. Vol: |feature| "
               "for signed features against |move|, both as per-pair ranks. `t` = HAC t over days; `months_same_sign` = share of calendar months whose mean IC has the overall sign; "
               f"`ic_mde` = smallest |IC| detectable at this sample. **{n_tests} tests: |t| > {bonf:.2f} is the Bonferroni bar; |t| ≈ 2 is "
               f"expected {0.05 * n_tests:.0f} times by chance.**\n", *[f"- note: {n}\n" for n in notes]]
        for bet in ("directional", "relative", "vol"):
            for h in HORIZONS:
                x = ic[(ic["bet"] == bet) & (ic["horizon"] == h)].dropna(subset=["t"])
                x = x.reindex(x["t"].abs().sort_values(ascending=False).index).head(6)
                md += [f"\n### {bet}, {h} — top 6 by |t|\n", show(x[["feature", "ic", "t", "months_same_sign", "ic_mde", "days"]], 4), "\n"]
        if summary is not None:
            best = (ic[ic["bet"] != "vol"].dropna(subset=["t"]).assign(abs_t=lambda x: x["t"].abs()).sort_values("abs_t", ascending=False)
                    .groupby(["bet", "horizon"], sort=False).head(1)[["bet", "horizon", "feature", "ic", "t", "months_same_sign", "ic_mde"]]
                    .rename(columns={"feature": "best_feature", "ic": "best_ic", "t": "best_t"}))
            summary = summary.merge(best, on=["bet", "horizon"], how="left")
    if "6" in items:
        print("#6 power…", flush=True)
        pw = power(D)
        pw.to_parquet(OUT_DIR / "power.parquet", index=False)
        md += ["\n## #6 Sample size and detectable effect\n",
               f"`mde_bps_per_trade` = the smallest mean per trade a strategy trading {TOP:.0%} of the cells could be told from zero (80 % power, "
               "5 % two-sided), from the day-clustered (HAC) spread of a no-skill strategy's daily P&L on the same cells.\n", show(pw), "\n"]
        if summary is not None:
            summary = summary.merge(pw[["bet", "horizon", "mde_bps_per_trade"]], on=["bet", "horizon"], how="left")
    if "4" in items:
        nic, nr = noise_floor(D, F, draws, int(os.environ.get("FT2_JOBS", os.cpu_count() or 1)))
        nic.to_parquet(OUT_DIR / "noise_ic.parquet", index=False)
        nr.to_parquet(OUT_DIR / "noise_ridge.parquet", index=False)
        screen, feats, ridge = floor_tables(nic, nr)
        screen.to_parquet(OUT_DIR / "noise_floor.parquet", index=False)
        feats.to_parquet(OUT_DIR / "noise_features.parquet", index=False)
        md += [f"\n## #4 Noise floor — the same pipeline on shuffled labels, {draws} draws\n",
               "Whole days of labels trade places (time of day kept, all pairs of one instant together, never from the 8 days before — see "
               "`_shuffle_days`), which breaks every link between features and labels and keeps everything else. Draw 0 is the real data.\n",
               "\n### The screen of #3: the best feature against the best of the same screen on noise\n",
               "`null_t_sd` = spread of a single feature's t on noise (1 = the HAC t is calibrated); `bar_t_p95` / `floor_ic_p95` = the |t| and |IC| "
               "the best of the screen reaches in 95 % of noise draws; `p_fw` = share of draws whose best |t| is at least the real best "
               "(family-wise, so the choice among the features is paid for); `n_clear` = real features above `bar_t_p95`.\n", show(screen, 4), "\n",
               "\n### Features with family-wise p ≤ 0.10\n", show(feats[feats["p_fw"] <= 0.10], 4), "\n",
               "\n### The walk-forward direction ridge of #1, refitted on shuffled labels\n",
               "`p` = share of draws whose |t| is at least the real one; `floor_ic_p95` = the |IC| the ridge reaches in 95 % of noise draws. "
               "`null_ic_mean` need not be 0: the ridge's intercept forecasts the average move of the training history, and a shuffle keeps "
               "that average — it is the part of the ridge's IC that is drift, not signal.\n", show(ridge, 4), "\n"]
        if summary is not None:
            fl = screen[["bet", "horizon", "floor_ic_p95", "bar_t_p95", "p_fw"]]
            rd = ridge[["bet", "horizon", "ic", "p"]].rename(columns={"ic": "ridge_ic", "p": "ridge_p"})
            summary = summary.merge(fl, on=["bet", "horizon"], how="left").merge(rd, on=["bet", "horizon"], how="left")
    if "5" in items:
        lc, lcp = learning_curves(D, F)
        lc.to_parquet(OUT_DIR / "learning_curves_folds.parquet", index=False)
        lcp.to_parquet(OUT_DIR / "learning_curves.parquet", index=False)
        md += ["\n## #5 Learning curves — ridge vs a depth-2 boosted tree, growing training windows\n",
               f"Each model is fitted on the most recent `window` days before a fold (`all` = everything before it, about 250 days for F1 and 490 for F2 — `train_days` below) and "
               f"scored on the fold; pooled over the folds that have the window. `*_in` / `*_out` = mean daily IC on the training window / on the fold; "
               f"`tree*` = {max(LC_TREES)} trees of depth 2, learning rate 0.05 (`tree50_out`, `tree150_out`: the same model read earlier); "
               "`tree_minus_ridge_t` = HAC t of the daily IC difference. `candle` = the features of #1, `all` = every feature of #3. "
               "Read: in ≫ out = fitting noise; out rising with the window = data-limited; tree above ridge with t > 2 = interactions.\n",
               show(lcp, 4), "\n", "\n### Per fold\n", show(lc, 4), "\n"]
    if summary is not None:
        summary.to_parquet(OUT_DIR / "summary.parquet", index=False)
        md.insert(4, "\n## Summary — what a signal must clear, and the best single feature found\n\n" + show(summary, 4) + "\n")
    text = "\n".join(md)
    out_md.write_text(text)
    return text
