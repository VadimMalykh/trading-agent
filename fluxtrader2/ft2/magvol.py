"""P8 (R54) — magnitude against implied: does the candle-built realised-volatility forecast add to Deribit's implied volatility
index in forecasting BTC's and ETH's realised volatility over the next 1 and 7 days? (`ft2 magvol`)

target      y_h(d) = log RV_h(d), RV = √(365 / h × Σ r²) × 100 (annualised %), r the 5-minute log returns of the close over the h days
            from 00:00 UTC of day d; the bar closed at t belongs to the day of t − 5 min; a day with fewer than 95 % of its 288 bars
            is not a target day and poisons every window that holds it.
features    at 00:00 of day d, from bars strictly before d: C = { lrv1, lrv7, lrv30 (the HAR ladder, log RV over the last 1, 7, 30
            days), dvs = log(dollar volume of d − 1 / its 30-day mean) }; I = { ldvol = log DVOL_open(d) } — the index's OPEN of day
            d, the value known at 00:00 (dvol.py).
models      per name and horizon three OLS fits with an intercept — I, C, I + C — refitted every 30 days on every row from 2021-03-24
            whose target window ended at or before the block's first day; scored on the folds' whole days.
statistic   the per-day loss difference L_I − L_{I+C} (positive: the candles improve on the implied), its Newey–West mean over days
            (lags h + 1), t, and the same in R² units (÷ the scored days' mean total variance); the reverse L_C − L_{I+C} described.
family      BTC, ETH × 1, 7 days; t ≥ 2.24 (one-sided, four at 5 %). ALIVE: t ≥ 2.24 and ΔR² ≥ 0.02 and both folds positive; CLOSED:
            ΔR² + 1.96 se < 0.02; else NOT DETECTABLE with the MDE (2.8 se). SOL described if its DVOL covers the folds.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import ceiling, folds
from . import dvol as dvol_mod
from .ceiling import hac

OUT = Path("output/magvol")
NAMES = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}            # the family
DESCRIBED = {"SOLUSDT": "SOL"}                           # outside the family, if its index covers the folds
HOLDS = (1, 7)
TRAIN_START = pd.Timestamp("2021-03-24", tz="UTC")       # DVOL's first day
PANEL_START = pd.Timestamp("2021-01-01", tz="UTC")
REFIT_DAYS = 30
WHOLE = 0.95
MIN_ROWS = 60
T_BAR = 2.24
DR2_MIN = 0.02
DVOL_COVER = 0.99
DVOL_RANGE = (10.0, 300.0)
DROPPED_MAX = 0.02
ANN = 365.0
FEATURES_C = ["lrv1", "lrv7", "lrv30", "dvs"]
FEATURES_I = ["ldvol"]
MODELS = {"I": FEATURES_I, "C": FEATURES_C, "I+C": [*FEATURES_I, *FEATURES_C]}


# ---- the day table ---------------------------------------------------------------------------------------------------------------
def day_table(close: pd.Series, dv: pd.Series) -> pd.DataFrame:
    """Per day: ss = Σ r² of the bars closed inside the day, n = the bars with a return, dv = the day's dollar volume, whole."""
    r = np.log(close.astype(float)).diff()
    day = (close.index - bt.BAR).floor("D")
    g = pd.DataFrame({"ss": r.pow(2), "n": r.notna().astype(int), "dv": dv.astype(float)}, index=close.index).groupby(day)
    out = g.agg(ss=("ss", "sum"), n=("n", "sum"), dv=("dv", "sum"))
    out["whole"] = out["n"] >= WHOLE * 288
    return out


def rv(ss_sum, h: int):
    return np.sqrt(ANN / h * ss_sum) * 100


def table(close: pd.Series, dv: pd.Series, dvol_open: pd.Series | None, holds=HOLDS) -> pd.DataFrame:
    """One row per day d: the targets y<h> (NaN unless every day of [d, d + h) is whole), the features from the bars before d."""
    D = day_table(close, dv)
    ss = D["ss"].where(D["whole"])
    T = pd.DataFrame(index=D.index)
    for h in [*holds, 30]:
        T[f"y{h}"] = np.log(rv(ss[::-1].rolling(h, min_periods=h).sum()[::-1], h))        # the sum of d … d + h − 1
    past = ss.shift(1)
    T["lrv1"] = np.log(rv(past, 1))
    T["lrv7"] = np.log(rv(past.rolling(7, min_periods=7).sum(), 7))
    T["lrv30"] = np.log(rv(past.rolling(30, min_periods=30).sum(), 30))
    dvp = D["dv"].where(D["whole"]).shift(1)
    T["dvs"] = np.log(dvp / dvp.rolling(30, min_periods=30).mean())
    T["ldvol"] = np.log(dvol_open.reindex(T.index).astype(float)) if dvol_open is not None else np.nan
    T["whole"], T["nbars"] = D["whole"], D["n"]
    return T.replace([np.inf, -np.inf], np.nan)


# ---- the walk --------------------------------------------------------------------------------------------------------------------
def walk(T: pd.DataFrame, feats: list[str], y: str, h: int, scored: np.ndarray) -> tuple[pd.Series, list[dict]]:
    """ŷ on the scored days: OLS with an intercept, refitted every REFIT_DAYS days on the rows from TRAIN_START whose target window
    (d + h days) ended at or before the block's first day."""
    X = T[feats]
    ok = X.notna().all(axis=1) & T[y].notna()
    yhat = pd.Series(np.nan, index=T.index)
    days = T.index[scored]
    blocks = []
    if not len(days):
        return yhat, blocks
    for a in pd.date_range(days[0], days[-1], freq=f"{REFIT_DAYS}D"):
        b = a + pd.Timedelta(days=REFIT_DAYS)
        tr = (ok & (T.index >= TRAIN_START) & (T.index + pd.Timedelta(days=h) <= a)).to_numpy()
        if tr.sum() < MIN_ROWS:
            continue
        A = np.column_stack([np.ones(tr.sum()), X[tr].to_numpy()])
        beta = np.linalg.lstsq(A, T.loc[tr, y].to_numpy(), rcond=None)[0]
        sc = scored & np.asarray(T.index >= a) & np.asarray(T.index < b) & X.notna().all(axis=1).to_numpy()
        yhat[sc] = np.column_stack([np.ones(sc.sum()), X[sc].to_numpy()]) @ beta
        blocks.append({"block": str(a.date()), "train_rows": int(tr.sum()), "last_target_end": str((T.index[tr] + pd.Timedelta(days=h)).max()),
                       "scored_rows": int(sc.sum()), **{f"b_{k}": float(v) for k, v in zip(["const", *feats], beta)}})
    return yhat, blocks


# ---- the statistic ---------------------------------------------------------------------------------------------------------------
def compare(T: pd.DataFrame, yh: dict[str, pd.Series], y: str, h: int, scored: np.ndarray, fold: pd.Series, fold_names) -> tuple[dict, dict, pd.DataFrame]:
    sc = scored.copy()
    for m in yh:
        sc &= yh[m].notna().to_numpy()
    sc &= T[y].notna().to_numpy()
    yy = T.loc[sc, y]
    sst = ((yy - yy.mean()) ** 2).sum()
    mtv = sst / len(yy)
    L = {m: (yy - yh[m][sc]) ** 2 for m in yh}
    r2 = {m: {"all": 1 - L[m].sum() / sst, **{f: 1 - L[m][fold[sc] == f].sum() / ((yy[fold[sc] == f] - yy[fold[sc] == f].mean()) ** 2).sum() for f in fold_names}} for m in yh}
    rows = {}
    for label, (base, full) in (("candles beyond implied", ("I", "I+C")), ("implied beyond candles", ("C", "I+C"))):
        diff = L[base] - L[full]
        m, se, n = hac(diff.to_numpy(), h + 1)
        rows[label] = {"days": int(n), "dr2": m / mtv, "se_r2": se / mtv, "t": m / se if se else np.nan, "mde_r2": bt.MDE_K * se / mtv,
                       "upper_r2": (m + 1.96 * se) / mtv, **{f"dr2_{f}": float(diff[fold[sc] == f].mean() / mtv) for f in fold_names}}
    loss = pd.DataFrame({"day": yy.index, "y": yy.to_numpy(), **{f"yhat_{m}": yh[m][sc].to_numpy() for m in yh}, "fold": fold[sc].to_numpy()})
    return rows, r2, loss


def verdict(r: dict, fold_names) -> str:
    both = all(r.get(f"dr2_{f}", np.nan) > 0 for f in fold_names)
    if np.isfinite(r["t"]) and r["t"] >= T_BAR and r["dr2"] >= DR2_MIN and both:
        return "ALIVE"
    if np.isfinite(r["upper_r2"]) and r["upper_r2"] < DR2_MIN:
        return "CLOSED"
    return "NOT DETECTABLE"


# ---- the run ---------------------------------------------------------------------------------------------------------------------
def run(holds=HOLDS, names: list[str] | None = None, name: str = "f12", fold_names=("F1", "F2"), dvol_path: Path | str = dvol_mod.PARQUET,
        panel: dict | None = None) -> str:
    holds = tuple(int(h) for h in holds)
    names = list(names or NAMES)
    end = folds.bounds(fold_names[-1])[1]
    syms = [*names, *[s for s in DESCRIBED if s not in names]]
    P = panel or ceiling.panel(syms, end, PANEL_START)
    dv = dvol_mod.load(dvol_path)
    cur_of = {**NAMES, **DESCRIBED}
    days_all = pd.DatetimeIndex(P["close"].index - bt.BAR).floor("D").unique()
    fold_of = pd.Series("", index=days_all)
    for f in fold_names:
        fold_of[folds.mask(pd.Series(days_all, index=days_all), f).to_numpy()] = f
    infold = days_all[(fold_of != "").to_numpy()]
    midpoint = infold[len(infold) // 2]

    v = {"names": {}, "status": "PASS"}
    rows, r2rows, losses, blocks, coefs = [], [], [], [], []
    for sym in syms:
        if sym not in P["close"].columns:
            v["names"][sym] = {"note": "not in the panel"}
            continue
        cur = cur_of.get(sym)
        d = dv[dv["currency"] == cur].drop_duplicates("day").set_index("day")["open"].sort_index() if cur else pd.Series(dtype=float)
        close, dv_s = P["close"][sym], P["dv"][sym]
        T = table(close, dv_s, d if len(d) else None, holds)
        fold = fold_of.reindex(T.index).fillna("")
        in_fold = (fold != "").to_numpy()
        n_fold_days = int(in_fold.sum())
        dropped = int((in_fold & ~T["whole"].to_numpy()).sum())
        cover = float(T.loc[in_fold, "ldvol"].notna().mean()) if n_fold_days else np.nan
        rng = (float(np.exp(T.loc[in_fold, "ldvol"]).min()), float(np.exp(T.loc[in_fold, "ldvol"]).max())) if n_fold_days and T.loc[in_fold, "ldvol"].notna().any() else (np.nan, np.nan)
        # (3) causal: the features recomputed on the bars cut at the midpoint are identical for every day at or before it
        Tc = table(close[close.index <= midpoint], dv_s[dv_s.index <= midpoint], d if len(d) else None, holds)
        upto = T.index[T.index <= midpoint - pd.Timedelta(days=1)]
        feats = [*FEATURES_C, "ldvol"]
        causal_diff = float(np.nanmax(np.abs(T.loc[upto, feats].to_numpy() - Tc.reindex(upto)[feats].to_numpy()))) if len(upto) else 0.0
        member = sym in names
        nv = {"family": member, "currency": cur, "fold_days": n_fold_days, "days_dropped_not_whole": dropped, "dropped_share": dropped / n_fold_days if n_fold_days else np.nan,
              "dvol_cover": cover, "dvol_open_min": rng[0], "dvol_open_max": rng[1], "causal_max_diff": causal_diff}
        ok_dvol = np.isfinite(cover) and cover >= DVOL_COVER and rng[0] >= DVOL_RANGE[0] and rng[1] <= DVOL_RANGE[1]
        nv["(1) DVOL cover and range"] = "PASS" if ok_dvol else ("FAIL" if member else "not covered (described name skipped)")
        nv["(2) whole days"] = "PASS" if nv["dropped_share"] <= DROPPED_MAX else "FAIL"
        nv["(3) causal"] = "PASS" if causal_diff <= 1e-9 else "FAIL"
        if member and not (ok_dvol and nv["(2) whole days"] == "PASS" and nv["(3) causal"] == "PASS"):
            v["status"] = "FAIL"
        v["names"][sym] = nv
        if not ok_dvol:
            continue
        for h in holds:
            y = f"y{h}"
            scored = in_fold & T["whole"].to_numpy() & T[y].notna().to_numpy()
            yh, bl = {}, {}
            for m, fl in MODELS.items():
                yh[m], bl[m] = walk(T, fl, y, h, scored)
                blocks += [{"symbol": sym, "hold": h, "model": m, **b} for b in bl[m]]
                if bl[m]:
                    coefs.append({"symbol": sym, "hold": h, "model": m, **{k: x for k, x in bl[m][-1].items() if k.startswith("b_") or k == "block"}})
            # (4) every refit's rows ended before its block
            late = [b for b in blocks if b["symbol"] == sym and b["hold"] == h and pd.Timestamp(b["last_target_end"]) > pd.Timestamp(b["block"], tz="UTC")]
            nv[f"(4) refits causal h={h}"] = "PASS" if not late else "FAIL"
            if late and member:
                v["status"] = "FAIL"
            cmp_rows, r2, loss = compare(T, yh, y, h, scored, fold, fold_names)
            for label, r in cmp_rows.items():
                rows.append({"symbol": sym, "currency": cur, "hold_days": h, "contrast": label, "family": member and label == "candles beyond implied", **r,
                             "verdict": verdict(r, fold_names) if member and label == "candles beyond implied" else "described"})
            r2rows += [{"symbol": sym, "hold_days": h, "model": m, **{f"r2_{k}": x for k, x in r2[m].items()}} for m in r2]
            losses.append(loss.assign(symbol=sym, hold_days=h))
        # the variance risk premium, described: log DVOL_open(d) − log RV_30(d) over the scored days with a 30-day window
        sc30 = in_fold & T["whole"].to_numpy() & T["y30"].notna().to_numpy() & T["ldvol"].notna().to_numpy()
        prem = (T.loc[sc30, "ldvol"] - T.loc[sc30, "y30"])
        m, se, n = hac(prem.to_numpy(), 31)
        nv["vrp_log_mean"], nv["vrp_se"], nv["vrp_days"] = float(m), float(se), int(n)
        nv["dvol_vs_rv30_corr"] = float(np.corrcoef(T.loc[sc30, "ldvol"], T.loc[sc30, "y30"])[0, 1]) if sc30.sum() > 30 else np.nan

    rows_df, r2_df = pd.DataFrame(rows), pd.DataFrame(r2rows)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    rows_df.to_csv(out / "rows.csv", index=False)
    r2_df.to_csv(out / "r2.csv", index=False)
    (pd.concat(losses, ignore_index=True) if losses else pd.DataFrame()).to_csv(out / "loss.csv", index=False)
    pd.DataFrame(coefs).to_csv(out / "coef.csv", index=False)
    pd.DataFrame(blocks).to_csv(out / "blocks.csv", index=False)
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    fam = rows_df[rows_df["family"]] if len(rows_df) else rows_df
    md = [f"# Magnitude against implied — `{name}` (`ft2 magvol`, R54)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · names {names} · holds {list(holds)} days · "
          f"training rows from {TRAIN_START.date()}, refit every {REFIT_DAYS} days · DVOL {dvol_path}\n",
          "\nWords: the target is log realised volatility (annualised %) over the next h days from 00:00 UTC; *I* is the implied index's open that morning, *C* the "
          "HAR ladder of realised volatility and the dollar-volume surprise, *I+C* both; *ΔR²* is the per-day squared-error loss saved by the fuller model, in "
          f"units of the scored days' variance, with a Newey–West se over days; the bar is t ≥ {T_BAR} (one-sided, four rows) and ΔR² ≥ {DR2_MIN}.\n",
          "\n## Validity\n", f"\n**{v['status']}**\n", "```\n" + json.dumps(v, indent=1, default=str) + "\n```\n",
          "\n## The family — the candles beyond the implied (BTC, ETH × 1, 7 days)\n", fam.round(4).to_markdown(index=False) if len(fam) else "_none_", "\n",
          "\n## Every contrast, including the reverse and the described names\n", rows_df.round(4).to_markdown(index=False) if len(rows_df) else "_none_", "\n",
          "\n## Out-of-sample R² per model and fold\n", r2_df.round(4).to_markdown(index=False) if len(r2_df) else "_none_", "\n",
          "\n## The I + C coefficients at the last refit\n", pd.DataFrame(coefs).round(4).to_markdown(index=False) if coefs else "_none_", "\n"]
    txt = "\n".join(md)
    (out / "magvol.md").write_text(txt)
    return txt
