"""P8 (R56) — R54's forecast against the ONE-DAY implied: does the candle-and-index forecast add to the straddle's own break-even
volatility in forecasting BTC's and ETH's realised volatility over the next day? (`ft2 magvolq`)

data        data/straddle_1d.parquet (R55): on each covered day d, Q(d) = log σ_q, σ_q = (c_last + p_last) / (0.8 √(32 / 8760)) — the
            legs' last trades before 00:00 of d, in units of spot (the constant shifts Q, it cannot move a contrast);
            output/magvol/f12/loss.csv (R54, hold 1, its sha256 checked): y = log RV_1(d) and the written out-of-sample forecasts
            ŷ_{I+C}, ŷ_I, ŷ_C. No fetch.
models      per name OLS with an intercept — Q, Q+F (F = ŷ_{I+C}), F; Q+I, Q+C described — walked forward inside F1+F2 on the covered
            days (magvol.walk: refit every 30 days on the rows whose target window ended by the block's first day, ≥ 60 rows).
statistic   the per-day loss difference L_Q − L_{Q+F}, Newey–West (2 lags), in R² units (÷ the scored days' mean total variance); per
            fold; MDE 2.8 se; upper = mean + 1.96 se.
family      BTC, ETH at 1 day, t ≥ 1.96 (one-sided, two). ALIVE: t ≥ 1.96 and ΔR² ≥ 0.02 and both folds positive; CLOSED: upper < 0.02;
            else NOT DETECTABLE. Described: the reverse (F beyond Q), Q+I, Q+C, R54's own I-vs-I+C on the same days from the file, the
            plain correlation corr(ŷ − Q, y − Q), the R² per fold, the last refit's coefficients.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import magvol, straddle, varbook
from .ceiling import hac

OUT = Path("output/magvolq")
T_BAR = 1.96
DR2_MIN = 0.02
NW_LAGS = 2
COVER_VOID, COVER_FULL = 0.5, 0.8
SCORED_MIN, F1_MIN = 250, 60
R55_FILE = {"sha256": "5cd4491265f56739807897baf27c84539436991ce0ec5e6a503f3ca5ad6116ff", "rows_hold1": 970}
FORECASTS = {"I+C": "yhat_I+C", "I": "yhat_I", "C": "yhat_C"}
MODELS = {"Q": ["Q"], "Q+F": ["Q", "F_I+C"], "F": ["F_I+C"], "Q+I": ["Q", "F_I"], "Q+C": ["Q", "F_C"]}
CONTRASTS = {"forecast beyond one-day implied": ("Q", "Q+F"), "one-day implied beyond forecast": ("F", "Q+F"),
             "30-day index beyond one-day implied": ("Q", "Q+I"), "candles beyond one-day implied": ("Q", "Q+C")}
FAMILY = "forecast beyond one-day implied"


# ---- the inputs ------------------------------------------------------------------------------------------------------------------
def implied(d: pd.DataFrame) -> pd.DataFrame:
    """The covered days' one-day implied Q = log σ_q, with the two entry bars' END times kept for validity (3): a bar ending at 00:00 holds the 23:00 hour's trades."""
    c = d[d["covered"]].copy()
    c["day"] = pd.to_datetime(c["day"], utc=True)
    c["m"] = c["c_last"].astype(float) + c["p_last"].astype(float)
    c["Q"] = np.log(varbook.breakeven_vol(c["m"].to_numpy()))
    for k in ("c_last_ts", "p_last_ts"):
        c[k] = pd.to_datetime(c[k], utc=True)
    return c[["currency", "day", "Q", "m", "c_last_ts", "p_last_ts"]]


def load_r54(path: Path = varbook.MAGVOL_LOSS) -> tuple[pd.DataFrame, str]:
    f, sha = varbook.load_forecasts(path)
    return f, sha


def table(cur: str, imp: pd.DataFrame, fc: pd.DataFrame) -> pd.DataFrame:
    """One row per R54 scored day of the name: y, the three written forecasts, the fold, Q (NaN on the uncovered days)."""
    f = fc[fc["symbol"] == straddle.NAMES[cur]].drop_duplicates("day").set_index("day").sort_index()
    T = pd.DataFrame({"y1": f["y"].astype(float), **{f"F_{k}": f[v].astype(float) for k, v in FORECASTS.items()}, "fold": f["fold"]})
    q = imp[imp["currency"] == cur].drop_duplicates("day").set_index("day")["Q"]
    T["Q"] = q.reindex(T.index)
    return T


# ---- the statistic ---------------------------------------------------------------------------------------------------------------
def contrast(diff: pd.Series, mtv: float, fold: pd.Series, fold_names) -> dict:
    m, se, n = hac(diff.to_numpy(), NW_LAGS)
    return {"days": int(n), "dr2": m / mtv, "se_r2": se / mtv, "t": m / se if se else np.nan, "mde_r2": bt.MDE_K * se / mtv,
            "upper_r2": (m + 1.96 * se) / mtv, **{f"dr2_{f}": float(diff[fold == f].mean() / mtv) if (fold == f).any() else np.nan for f in fold_names}}


def verdict(r: dict, fold_names) -> str:
    both = all(r.get(f"dr2_{f}", np.nan) > 0 for f in fold_names)
    if np.isfinite(r["t"]) and r["t"] >= T_BAR and r["dr2"] >= DR2_MIN and both:
        return "ALIVE"
    if np.isfinite(r["upper_r2"]) and r["upper_r2"] < DR2_MIN:
        return "CLOSED"
    return "NOT DETECTABLE"


def read_name(cur: str, T: pd.DataFrame, fold_names) -> dict:
    scored = T["Q"].notna().to_numpy() & T["y1"].notna().to_numpy() & T[[f"F_{k}" for k in FORECASTS]].notna().all(axis=1).to_numpy()
    yh, blocks, coefs = {}, [], []
    for m, feats in MODELS.items():
        yh[m], bl = magvol.walk(T, feats, "y1", 1, scored)
        blocks += [{"currency": cur, "model": m, **b} for b in bl]
        if bl:
            coefs.append({"currency": cur, "model": m, **{k: x for k, x in bl[-1].items() if k.startswith("b_") or k == "block"}})
    sc = scored.copy()
    for m in yh:
        sc &= yh[m].notna().to_numpy()
    yy = T.loc[sc, "y1"]
    fold = T.loc[sc, "fold"]
    sst = ((yy - yy.mean()) ** 2).sum()
    mtv = sst / len(yy) if len(yy) else np.nan
    L = {m: (yy - yh[m][sc]) ** 2 for m in yh}
    rows = []
    for label, (base, full) in CONTRASTS.items():
        r = contrast(L[base] - L[full], mtv, fold, fold_names) if len(yy) else {"days": 0, "dr2": np.nan, "se_r2": np.nan, "t": np.nan, "mde_r2": np.nan, "upper_r2": np.nan}
        rows.append({"currency": cur, "contrast": label, "base": base, "full": full, "family": label == FAMILY, **r,
                     "verdict": verdict(r, fold_names) if label == FAMILY and len(yy) else "described"})
    # R54's own contrast on the same days, from the file (no refit)
    if len(yy):
        d54 = (yy - T.loc[sc, "F_I"]) ** 2 - (yy - T.loc[sc, "F_I+C"]) ** 2
        rows.append({"currency": cur, "contrast": "R54: candles beyond 30-day index, same days (file)", "base": "I (file)", "full": "I+C (file)", "family": False,
                     **contrast(d54, mtv, fold, fold_names), "verdict": "described"})
    r2 = [{"currency": cur, "model": m, "r2_all": 1 - L[m].sum() / sst if sst else np.nan,
           **{f"r2_{f}": 1 - L[m][fold == f].sum() / ((yy[fold == f] - yy[fold == f].mean()) ** 2).sum() if (fold == f).sum() > 2 else np.nan for f in fold_names}} for m in yh]
    ex_f, ex_y = T.loc[sc, "F_I+C"] - T.loc[sc, "Q"], yy - T.loc[sc, "Q"]
    desc = {"scored_days": int(sc.sum()), **{f"scored_{f}": int((fold == f).sum()) for f in fold_names},
            "corr_excess": float(np.corrcoef(ex_f, ex_y)[0, 1]) if sc.sum() > 10 else np.nan,
            "mean_Q": float(T.loc[sc, "Q"].mean()) if sc.sum() else np.nan, "mean_y": float(yy.mean()) if len(yy) else np.nan,
            "mean_F": float(T.loc[sc, "F_I+C"].mean()) if sc.sum() else np.nan}
    loss = pd.DataFrame({"currency": cur, "day": yy.index, "y": yy.to_numpy(), **{f"yhat_{m}": yh[m][sc].to_numpy() for m in yh}, "Q": T.loc[sc, "Q"].to_numpy(),
                         "F_I+C": T.loc[sc, "F_I+C"].to_numpy(), "fold": fold.to_numpy()})
    return {"rows": rows, "r2": r2, "blocks": blocks, "coefs": coefs, "desc": desc, "loss": loss}


# ---- the run ---------------------------------------------------------------------------------------------------------------------
def run(name: str = "f12", fold_names=("F1", "F2"), straddle_path: Path | str = straddle.PARQUET, loss_path: Path | str = varbook.MAGVOL_LOSS,
        expect: dict | None = None) -> str:
    expect = R55_FILE if expect is None else expect
    fc, sha = load_r54(Path(loss_path))
    imp = implied(pd.read_parquet(straddle_path))
    v = {"status": "PASS", "names": {}}
    cols_ok = all(c in fc.columns for c in ["y", *FORECASTS.values()])
    v["(1) R54's file unchanged"] = {"sha256": sha, "expected": expect["sha256"], "rows_hold1": int(len(fc)), "expected_rows": expect["rows_hold1"], "columns": cols_ok,
                                     "status": "PASS" if sha == expect["sha256"] and len(fc) == expect["rows_hold1"] and cols_ok else "FAIL"}
    if v["(1) R54's file unchanged"]["status"] == "FAIL":
        v["status"] = "FAIL"
    res = {}
    for cur in straddle.NAMES:
        T = table(cur, imp, fc)
        nv = {"fold_days_with_forecast": int(len(T)), "covered_with_forecast": int(T["Q"].notna().sum())}
        nv["coverage"] = nv["covered_with_forecast"] / nv["fold_days_with_forecast"] if len(T) else np.nan
        nv["(2) coverage"] = "VOID" if not (nv["coverage"] >= COVER_VOID) else ("PASS (full)" if nv["coverage"] >= COVER_FULL else "PASS (partial — the share in every row)")
        ic = imp[imp["currency"] == cur]
        ic = ic[ic["day"].isin(T.index)]
        late = ic[(ic["c_last_ts"] > ic["day"]) | (ic["p_last_ts"] > ic["day"])]          # the timestamp is the entry BAR's end (straddle.last_trade_before)
        nv["(3) Q known at 00:00"] = {"entry_bars_ending_after_midnight": int(len(late)), "entry_bars_ending_at_midnight": int(((ic["c_last_ts"] == ic["day"]) | (ic["p_last_ts"] == ic["day"])).sum()),
                                     "status": "PASS" if not len(late) else "FAIL"}
        if nv["(2) coverage"] == "VOID" or len(late):
            v["status"] = "FAIL"
            v["names"][cur] = nv
            continue
        r = read_name(cur, T, fold_names)
        bad = [b for b in r["blocks"] if pd.Timestamp(b["last_target_end"]) > pd.Timestamp(b["block"], tz="UTC")]
        nv["(4) refits causal"] = "PASS" if not bad else "FAIL"
        if bad:
            v["status"] = "FAIL"
        d = r["desc"]
        floor_ok = d["scored_days"] >= SCORED_MIN and d.get("scored_F1", 0) >= F1_MIN
        nv["(5) scored-day floor"] = "PASS" if floor_ok else "FAIL (the family row NOT DETECTABLE by construction)"
        if not floor_ok:
            for row in r["rows"]:
                if row["family"]:
                    row["verdict"] = "NOT DETECTABLE (scored-day floor)"
        nv.update(d)
        v["names"][cur] = nv
        res[cur] = r
    rows = pd.DataFrame([x for r in res.values() for x in r["rows"]])
    r2 = pd.DataFrame([x for r in res.values() for x in r["r2"]])
    coefs = pd.DataFrame([x for r in res.values() for x in r["coefs"]])
    blocks = pd.DataFrame([x for r in res.values() for x in r["blocks"]])
    loss = pd.concat([r["loss"] for r in res.values()], ignore_index=True) if res else pd.DataFrame()
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out / "rows.csv", index=False)
    r2.to_csv(out / "r2.csv", index=False)
    coefs.to_csv(out / "coef.csv", index=False)
    blocks.to_csv(out / "blocks.csv", index=False)
    loss.to_csv(out / "loss.csv", index=False)
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    txt = _md(name, fold_names, v, rows, r2, coefs, straddle_path, loss_path)
    (out / "magvolq.md").write_text(txt)
    return txt


def _md(name, fold_names, v, rows, r2, coefs, straddle_path, loss_path) -> str:
    fam = rows[rows["family"]] if len(rows) else rows
    n_alive = int((fam["verdict"] == "ALIVE").sum()) if len(fam) else 0
    md = [f"# R54's forecast against the one-day implied — `{name}` (`ft2 magvolq`, R56)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · the implied {straddle_path} (Q = log σ_q from the legs' last trades before "
          f"00:00) · the forecasts and the target {loss_path} (R54, hold 1) · refit every {magvol.REFIT_DAYS} days on ≥ {magvol.MIN_ROWS} covered rows\n",
          "\nWords: *Q* is the one-day at-the-money straddle's break-even volatility (log), *F* R54's written I + C forecast of log realised volatility over the next day; "
          "each model is an OLS fit walked forward inside the folds; *ΔR²* is the per-day squared-error loss the fuller model saves, in units of the scored days' "
          f"variance, Newey–West se ({NW_LAGS} lags); the family is the two 'forecast beyond one-day implied' rows at t ≥ {T_BAR} and ΔR² ≥ {DR2_MIN}, both folds positive.\n",
          "\n## Validity\n", f"\n**{v['status']}**\n", "```\n" + json.dumps(v, indent=1, default=str) + "\n```\n",
          f"\n## The family — R54's forecast beyond the one-day implied (BTC, ETH at 1 day): **{n_alive} of {len(fam)} ALIVE**\n",
          fam.round(4).to_markdown(index=False) if len(fam) else "_none_", "\n",
          "\n## Every contrast, including the reverse, the parts and R54's own on the same days\n", rows.round(4).to_markdown(index=False) if len(rows) else "_none_", "\n",
          "\n## Described: the correlation R55 reported and the levels\n"]
    for cur, nv in v["names"].items():
        if "corr_excess" in nv:
            md.append(f"- {cur}: corr(F − Q, y − Q) = {nv['corr_excess']:+.3f} on {nv['scored_days']} scored days (F1 {nv.get('scored_F1', 0)}, F2 {nv.get('scored_F2', 0)}); "
                      f"mean Q {nv['mean_Q']:.3f}, mean F {nv['mean_F']:.3f}, mean y {nv['mean_y']:.3f} (log annualised %).")
    md += ["\n\n## Out-of-sample R² per model and fold\n", r2.round(4).to_markdown(index=False) if len(r2) else "_none_", "\n",
           "\n## The coefficients at the last refit\n", coefs.round(4).to_markdown(index=False) if len(coefs) else "_none_", "\n"]
    return "\n".join(md)


def main(name: str = "f12"):
    print(run(name))
    print(f"wrote {OUT / name}/")
