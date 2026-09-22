"""P5's forecast layer, pair-held-out (PLAN §4 P5 step 7, registration R12 in §8).

`ridgebook`: a ridge forecast of a pair's move RELATIVE to the other pairs, fitted on pairs the scored
pair is not one of, turned into trades by a closed-form rule. No learned policy.

    universe   the pairs the harness hands over, in their given order (the wide universe's volume rank);
               group g = every `groups`-th name starting at g. A pair in group g is scored ONLY by the
               model fitted without group g (four rotations: every pair is scored by a model that never
               saw its bars).
    features   the 11 candle features of the P2 screen, ONE definition (`ceiling.dir_features`: the
               vol-scaled trailing returns over 15m/1h/4h/1d/1w, the three relative ones, two vol ratios)
               plus hour of day as sin and cos — 12 columns, standardised with the training mean and sd.
    grid       decisions and training rows on the bars where t is on the hour (`grid` = 12 bars): 24 a
               day per pair. Adjacent 5m bars share their labels almost entirely, so the grid loses
               little and keeps the ledger small.
    label      the harness's y (the gross bps from execution to exit at `hold`), divided by the pair's
               σ_1w·√hold and clipped at ±5 (P2's z), MINUS the mean over the training pairs present at
               that bar (≥ `min_pairs`): the pair's move against its peers, so that the forecast carries
               no market direction (R8 and R11: a long bias looks like skill in a rising fold).
    model      RidgeCV over ceiling.ALPHAS, no intercept (an intercept is a standing market bet), refitted
               by the harness every block on ALL rows whose labels ended before the block (R7: more
               history helps; short refits were the biased statistic).
    forecast   f = ẑ · σ_1w · √hold, in bps: the expected move against the peers over the hold.
    decision   trade when |f| ≥ `min_bps` (a taker round trip of ~12.5 plus a margin), side = sign(f),
               held `hold` bars, one position per pair (the harness). Size = (|f| / min_bps) · (σ_ref/σ_h)²
               — expected value over variance, σ_ref the median σ_h of the training rows — floored at
               0.25 and capped at `cap` units. The harness weights every mean by size; bps are per unit.

Registered before the read: groups 4, grid 12, min_bps, cap 2, min_pairs 5, hold ∈ {288 (primary), 48}.
The strategy also keeps every out-of-sample forecast of the FIRST walk (the real one; the noise floor's
re-walks are not recorded) so that `forecast_report` can say whether the IC survives the pair hold-out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import Market, Strategy, decisions_from, labels
from .ceiling import ALPHAS, BAR, W, Z_CLIP, _ic_pooled, day_lags, dir_features, hac

LOOKBACK = W["1w"] + 1                  # bars a feature looks back: computing on a tail this long reproduces the full-panel value
MIN_ROWS = 500                           # training rows a rotation needs before it forecasts
N_FEAT = 12


def _derive(close: pd.DataFrame) -> dict:
    """The part of `ceiling.derive` the candle features need (lr, sig), on the frame given."""
    lr = np.log(close)
    r1 = lr.diff() * 1e4
    sig = {w: r1.rolling(k, min_periods=int(k * 0.8)).std() for w, k in W.items() if k >= 12}
    return {"lr": lr, "r1": r1, "sig": sig}


def _cells(F: dict[str, pd.DataFrame], sig1w: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(bar × pair × feature) cells of the 12 features, and (bar × pair) σ_1w in bps per bar."""
    idx = next(iter(F.values())).index
    hour = idx.hour.to_numpy() * (2 * np.pi / 24)
    n_pairs = sig1w.shape[1]
    hs, hc = (np.repeat(f(hour)[:, None], n_pairs, 1) for f in (np.sin, np.cos))
    X = np.stack([*(v.to_numpy() for v in F.values()), hs, hc], axis=-1)
    return X, sig1w.to_numpy()


class RidgeBook(Strategy):
    name = "ridgebook"
    uses_labels = True

    def __init__(self, hold: int = 288, min_bps: float = 15.0, cap: float = 2.0, groups: int = 4, grid: int = 12, min_pairs: int = 5):
        self.hold, self.min_bps, self.cap, self.groups, self.grid, self.min_pairs = int(hold), float(min_bps), float(cap), int(groups), int(grid), int(min_pairs)
        self._ts: list[pd.Timestamp] = []                  # cached grid bars, in time order
        self._X: list[np.ndarray] = []                     # per cached bar: (pair × feature)
        self._S: list[np.ndarray] = []                     # per cached bar: σ_1w per pair (bps per 5m bar)
        self._pos: dict[pd.Timestamp, int] = {}
        self._models: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray] | None] = {}
        self._sigma_ref = np.nan
        self._last_now: pd.Timestamp | None = None
        self._walks = 0
        self._oos: list[pd.DataFrame] = []

    # ---- features, cached per grid bar (they look back only, so a prefix of the market gives the same values) ----
    def _grid(self, idx: pd.DatetimeIndex) -> np.ndarray:
        return (idx.minute == 0) & (idx.second == 0) if self.grid == 12 else (np.arange(len(idx)) % self.grid == 0)

    def _ensure(self, M: Market) -> None:
        idx = M.index
        g = np.flatnonzero(self._grid(idx))
        missing = [p for p in g if idx[p] not in self._pos]
        if not missing:
            return
        start = max(int(missing[0]) - LOOKBACK, 0)
        D = _derive(M.close.iloc[start:])
        X, S = _cells(dir_features(D), D["sig"]["1w"])
        for p in missing:
            self._pos[idx[p]] = len(self._ts)
            self._ts.append(idx[p])
            self._X.append(X[p - start])
            self._S.append(S[p - start])

    def _rows(self, ts: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
        pos = np.array([self._pos[t] for t in ts], dtype=int)
        return np.stack([self._X[p] for p in pos]), np.stack([self._S[p] for p in pos])

    def _group(self, n_pairs: int) -> np.ndarray:
        return np.arange(n_pairs) % self.groups

    # ---- fit: one ridge per rotation, on the other groups' rows ------------------------------------------------------
    def fit(self, M: Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        from sklearn.linear_model import RidgeCV
        if self._last_now is not None and now <= self._last_now:
            self._walks += 1                                # the harness started another walk (a noise-floor draw)
        self._last_now = now
        self._ensure(M)
        ts = y.index[self._grid(y.index)]
        ts = ts[np.array([t in self._pos for t in ts], dtype=bool)]
        self._models = {g: None for g in range(self.groups)}
        if not len(ts):
            return
        X, S = self._rows(ts)                                # (rows × pair × feat), (rows × pair)
        sig_h = S * np.sqrt(self.hold)
        z = np.clip(y.loc[ts].to_numpy() / sig_h, -Z_CLIP, Z_CLIP)
        grp = self._group(X.shape[1])
        self._sigma_ref = float(np.nanmedian(sig_h))
        for g in range(self.groups):
            tr = grp != g
            zt = z[:, tr]
            have = ~np.isnan(zt)
            n = have.sum(1, keepdims=True)
            mean = np.where(n >= self.min_pairs, np.nansum(zt, 1, keepdims=True) / np.maximum(n, 1), np.nan)
            zr = (zt - mean).ravel()
            Xt = X[:, tr, :].reshape(-1, N_FEAT)
            ok = ~np.isnan(zr) & ~np.isnan(Xt).any(1)
            if ok.sum() < MIN_ROWS:
                continue
            mu, sd = Xt[ok].mean(0), Xt[ok].std(0) + 1e-12
            m = RidgeCV(alphas=ALPHAS, fit_intercept=False).fit((Xt[ok] - mu) / sd, zr[ok])
            self._models[g] = (mu, sd, m.coef_)

    # ---- decide: each pair scored by the model that never saw it ---------------------------------------------------------
    def _forecast(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
        """Grid bars in [a, b): the forecast in bps (NaN = none) and σ_h per pair."""
        self._ensure(M)
        idx = M.index
        ts = idx[self._grid(idx) & (idx >= a) & (idx < b)]
        if not len(ts):
            return ts, np.zeros((0, len(M.columns))), np.zeros((0, len(M.columns)))
        X, S = self._rows(ts)
        sig_h = S * np.sqrt(self.hold)
        zhat = np.full(S.shape, np.nan)
        grp = self._group(X.shape[1])
        for g, m in self._models.items():
            if m is None:
                continue
            mu, sd, coef = m
            cols = grp == g
            zhat[:, cols] = ((X[:, cols, :] - mu) / sd) @ coef
        f = zhat * sig_h
        f[np.isnan(M.close.loc[ts].to_numpy())] = np.nan
        return ts, f, sig_h

    def decide(self, M: Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        ts, f, sig_h = self._forecast(M, a, b)
        with np.errstate(invalid="ignore", divide="ignore"):
            on = np.abs(f) >= self.min_bps
            size = np.clip((np.abs(f) / self.min_bps) * (self._sigma_ref / sig_h) ** 2, 0.25, self.cap)
        side = pd.DataFrame(np.where(on, np.sign(f) * size, 0.0), index=ts, columns=M.columns)
        sig = pd.DataFrame(f, index=ts, columns=M.columns)
        if self._walks == 0 and len(ts):
            self._oos.append(pd.DataFrame({"t": np.repeat(ts, f.shape[1]), "symbol": np.tile(np.asarray(M.columns, dtype=str), len(ts)),
                                           "group": np.tile(self._group(f.shape[1]), len(ts)), "f_bps": f.ravel(), "sigma_h": sig_h.ravel()}))
        return decisions_from(side, a, b, signal=sig, why=f"ridge forecast vs peers ≥ {self.min_bps:g} bps, pair held out")

    # ---- the forecast read: does the IC survive the pair hold-out? ----------------------------------------------------
    def oos(self) -> pd.DataFrame:
        if not self._oos:
            return pd.DataFrame(columns=["t", "symbol", "group", "f_bps", "sigma_h"])
        return pd.concat(self._oos, ignore_index=True).drop_duplicates(["t", "symbol"], keep="first").sort_values(["t", "symbol"]).reset_index(drop=True)


def forecast_report(strategy: RidgeBook, M: Market, fold_names, latency: int) -> str:
    """IC of the held-out forecast against the realised z on the decision grid, pooled (`ceiling._ic_pooled`,
    day-clustered t), per fold and per held-out group; the share of grid cells clearing min_bps; and the realised
    gross by forecast decile (is the forecast calibrated?)."""
    from . import folds
    o = strategy.oos()
    if o.empty:
        return "# Forecast — no out-of-sample forecasts were recorded\n"
    y = labels(M, strategy.hold, latency)
    i, j = M.index.get_indexer(o["t"]), M.columns.get_indexer(o["symbol"])
    o["y_bps"] = y.to_numpy()[i, j]
    o["z"] = np.clip(o["y_bps"] / o["sigma_h"], -Z_CLIP, Z_CLIP)
    o["zhat"] = o["f_bps"] / o["sigma_h"]
    t = pd.DatetimeIndex(o["t"])
    o["fold"] = ""
    for f in fold_names:
        o.loc[folds.mask(pd.Series(t, index=o.index), f).to_numpy(), "fold"] = f
    ok = o["f_bps"].notna() & o["z"].notna() & (o["fold"] != "")
    o = o[ok].copy()
    # residual of the realised z against the other pairs present at the bar: the forecast is of the move against peers
    zm = o.groupby("t")["z"].transform("mean")
    o["zres"] = o["z"] - zm
    lags = day_lags(strategy.hold)

    def ic(d: pd.DataFrame) -> dict:
        if len(d) < 200:
            return {"n": len(d), "ic": np.nan, "t": np.nan, "days": 0}
        day = (pd.DatetimeIndex(d["t"]).floor("D") - t.min().floor("D")).days.to_numpy()
        daily = _ic_pooled(d["zhat"].to_numpy(), d["zres"].to_numpy(), day, min_cells=1)
        m, se, n = hac(daily[~np.isnan(daily)], lags)
        return {"n": len(d), "ic": float(m), "t": float(m / se) if se else np.nan, "days": int(n)}

    rows = [{"scope": "all", "group": "all", **ic(o)}]
    rows += [{"scope": f, "group": "all", **ic(o[o["fold"] == f])} for f in fold_names]
    rows += [{"scope": "all", "group": int(g), **ic(o[o["group"] == g])} for g in sorted(o["group"].unique())]
    rows += [{"scope": f, "group": int(g), **ic(o[(o["fold"] == f) & (o["group"] == g)])} for f in fold_names for g in sorted(o["group"].unique())]
    per_pair = [{"symbol": s, "group": int(d["group"].iloc[0]), **ic(d), "share_on": float((d["f_bps"].abs() >= strategy.min_bps).mean())}
                for s, d in o.groupby("symbol")]
    o["decile"] = pd.qcut(o["f_bps"].rank(method="first"), 10, labels=False) + 1
    cal = o.groupby("decile").agg(n=("f_bps", "size"), f_bps=("f_bps", "mean"), realised_bps=("y_bps", "mean"),
                                  realised_vs_peers_bps=("zres", lambda z: float(np.mean(z * o.loc[z.index, "sigma_h"])))).reset_index()
    on = float((o["f_bps"].abs() >= strategy.min_bps).mean())
    md = [f"# Forecast — `{strategy.name}` held-out IC on the decision grid\n",
          f"\n{len(o):,} grid cells over {'+'.join(fold_names)}; {on:.1%} clear |f| ≥ {strategy.min_bps:g} bps; hold {strategy.hold} bars; "
          f"IC = pooled correlation of ẑ with the realised z minus the bar's cross-pair mean (`_ic_pooled`), t clustered by day (lags {lags}). "
          "Group g's cells are scored by the model fitted without group g.\n",
          "\n## IC per fold and held-out group\n", pd.DataFrame(rows).round(4).to_markdown(index=False), "\n",
          "\n## Per pair\n", pd.DataFrame(per_pair).round(4).to_markdown(index=False), "\n",
          "\n## Calibration: realised move by forecast decile (bps, gross, before costs; latency as the harness)\n", cal.round(2).to_markdown(index=False), "\n"]
    return "\n".join(md)


STRATEGIES = {RidgeBook.name: RidgeBook}
