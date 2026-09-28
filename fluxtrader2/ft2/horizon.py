"""P8 — the longer hold (PLAN §4 P8, registration R22 in §8). `ft2 horizon <run>` → output/horizon/<run>/horizon.md

Everything measured on names outside the twelve was measured at a one-day hold. A round trip costs the same whether a
position is held a day or a week: held 3 or 7 days, do the names a signal puts at the top earn more than the names it
puts at the bottom — in the mean, in bps, by more than the round trip? A ceiling audit: no model, no book, no fold spent.

cells      `audit.frame`'s: the scored cells of a `transferbook` run, hourly decision bars, the block's members.
label      what a long position earns before trading costs: the move from the close one bar after t to the close `hold`
           bars later, minus the funding a long pays over those bars (`backtest.load_costs`' cumulative funding), bps.
signals    `SIGNALS`: R20's five unresolved features by `audit.features`' own code, and the run's own forecast ẑ.
statistic  `_tenths`: per bar the mean label of the tenth highest by the signal minus that of the tenth lowest, halved —
           bps per leg of a top-against-bottom book; averaged per day; M = the mean over days.
null       `shifts`: the labels move by a whole number of days, the same for every name and bar (a circular shift of the
           scored days), EVERY admissible shift. Neighbouring days' labels share most of their window at these holds; a
           shift keeps that overlap, where trading days' places (`ceiling._shuffle_days`) would break it. A name keeps
           its own labels, so a lasting link between a name's level of a signal and its drift earns no credit.
           Per signal × hold: centre and se = the mean and the standard deviation of M over the shifts; M_c = M − centre,
           u = M_c / se; per shift the largest |u| of the family → the family-wise p.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import audit, folds
from . import backtest as bt
from .ceiling import MDE_K, Z_CLIP, Z_TOP, _ic_xs, day_lags, hac

OUT = Path("output/horizon")
HOLDS = (864, 2016)                # 3 days, 7 days
FEATURES = ["oi_turn", "oi_chg_1w", "oi_chg_1d", "global_ls", "top_vs_global"]      # R20's five NOT DETECTABLE
FORECAST, SCORE = "forecast", "oi_score"
SIGNALS = [*FEATURES, FORECAST]    # the family, × HOLDS; SCORE (R21's) and the run's own hold are reference rows
COST = 17.6                        # bps per leg: R21's fees + spread and impact on its taker trades
MIN_CELLS, TENTH = 20, 0.10
PER_DAY = 24                       # the grid's bars in a day
U_BAR, P_BAR, IC_TOL = 2.0, 0.05, 1e-9


def labels(M: bt.Market, fundcum: np.ndarray, hold: int, latency: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(the move, what a long earns): `backtest.labels`, and the same minus the funding a long pays between the entry bar
    and the exit bar — `backtest.price`'s gross and gross + funding of a long."""
    fc = pd.DataFrame(fundcum, index=M.index, columns=M.columns)
    y = bt.labels(M, hold, latency)
    return y, y - (fc.shift(-(latency + hold)) - fc.shift(-latency))


def gap_days(holds) -> int:
    """A day never receives the labels of a day nearer than this, in either direction: the longest feature window + the longest hold + 1."""
    return audit.W1 // audit.D1 + int(np.ceil(max(holds) / audit.D1)) + 1


def shifts(nd: int, gap: int) -> np.ndarray:
    """Every admissible circular shift of `nd` scored days, in days."""
    return np.arange(gap, nd - gap + 1)


def shifted(n_rows: int, k: int) -> np.ndarray:
    """Row indexer of the shift by k days: the label at row i is taken from row src[i]; time of day kept, whole rows move."""
    return (np.arange(n_rows) + k * PER_DAY) % n_rows


def _ranks(S: np.ndarray, ok: np.ndarray) -> np.ndarray:
    """Per row the rank 1 … n of S among the cells `ok` (the others rank above n)."""
    o = np.argsort(np.where(ok, S, np.inf), axis=1, kind="stable")
    r = np.empty_like(o)
    np.put_along_axis(r, o, np.broadcast_to(np.arange(1, S.shape[1] + 1), S.shape), axis=1)
    return r


def _tenths(S: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Per bar with ≥ MIN_CELLS cells that have the signal and the label: the mean label of the k highest by the signal
    minus that of the k lowest, halved; k = the tenth of them, rounded. Averaged per day (PER_DAY rows a day)."""
    ok = ~(np.isnan(S) | np.isnan(Y))
    n = ok.sum(1)
    k = np.rint(n * TENTH).astype(int)
    r = _ranks(S, ok)
    y = np.where(ok, Y, 0.0)
    lo, hi = r <= k[:, None], (r > (n - k)[:, None]) & (r <= n[:, None])
    with np.errstate(invalid="ignore", divide="ignore"):
        m = ((y * hi).sum(1) - (y * lo).sum(1)) / k / 2.0
    m[n < MIN_CELLS] = np.nan
    m = m.reshape(-1, PER_DAY)
    have = ~np.isnan(m)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(have.any(1), np.nansum(m, 1) / have.sum(1), np.nan)


def _by_tenth(S: np.ndarray, Y: np.ndarray) -> pd.DataFrame:
    """The label against the bar's peers, by the signal's tenth inside the bar (1 = lowest): cells, mean, median."""
    ok = ~(np.isnan(S) | np.isnan(Y))
    n = ok.sum(1)
    ok &= (n >= MIN_CELLS)[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = Y - (np.where(ok, Y, 0.0).sum(1) / n)[:, None]
        dec = np.ceil(_ranks(S, ok) / n[:, None] * 10).clip(1, 10)
    L = pd.DataFrame({"tenth": dec[ok].astype(int), "rel": rel[ok]})
    return L.groupby("tenth")["rel"].agg(cells="size", mean="mean", median="median")


def _null(name: str, S: np.ndarray, Y: dict[int, np.ndarray], ks: np.ndarray) -> pd.DataFrame:
    """One signal at every hold: M on the real labels (shift 0) and on every admissible shift."""
    rows = []
    for h, y in Y.items():
        for k in [0, *ks]:
            rows.append({"signal": name, "hold": h, "shift": int(k), "m": float(np.nanmean(_tenths(S, y[shifted(len(y), k)] if k else y)))})
    return pd.DataFrame(rows)


def verdict(r: dict, cost: float = COST) -> str:
    if abs(r["m_c"]) > cost and abs(r["u"]) >= U_BAR and r["p_family"] <= P_BAR and r["folds_same_sign"] and r["after_same_sign"]:
        return "CLEARS"
    return "CLOSED" if abs(r["m_c"]) + 1.96 * r["se"] < cost else "NOT DETECTABLE"


def run(run: str, holds=HOLDS, members: str | None = None, cost: float = COST, jobs: int = 4) -> str:
    from joblib import Parallel, delayed
    A = audit.frame(run, members)
    fold_names, ref, latency, end, M, o, names, idx, sig, z, grid, cell, v = (A[k] for k in (
        "fold_names", "hold", "latency", "end", "M", "o", "names", "idx", "sig", "z", "grid", "cell", "validity"))
    holds = [int(h) for h in holds]
    every = [ref, *holds]
    n_rows, nd = len(grid), len(grid) // PER_DAY
    whole = bool(n_rows == nd * PER_DAY and (np.bincount(audit._day(grid))[np.bincount(audit._day(grid)) > 0] == PER_DAY).all())
    ks = shifts(nd, gap_days(holds))
    cm = cell.to_numpy()

    # the labels: the price move (gross), and what a long earns (the move minus the funding it pays)
    fundcum = bt.load_costs(M.index, M.columns, end).fundcum
    G, Y = ({h: labels(M, fundcum, h, latency)[i].loc[grid, names].to_numpy() for h in every} for i in (0, 1))
    Zh = {h: (bt.labels(M, h, latency).loc[idx, names] / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).loc[grid] for h in every}

    # the signals, on the run's cells
    F, notes = audit.features(idx, names, M.dv.loc[idx, names], end, only=sorted({*FEATURES, *audit.OI}))
    F = {k: x.loc[grid].where(cell) for k, x in F.items()}
    S = {k: F[k] for k in FEATURES}
    S[FORECAST] = o.pivot(index="t", columns="symbol", values="zhat").reindex(index=grid, columns=names).where(cell)
    has = np.logical_and.reduce([F[k].notna().to_numpy() for k in audit.OI])
    r = {k: F[k].where(has).rank(axis=1, pct=True) for k in audit.OI}
    S[SCORE] = r["oi_turn"] - 0.5 * (r["oi_chg_1d"] + r["oi_chg_1w"])

    # validity: R20's numbers by this code, whole days, the shifts
    day, ic_rows = audit._day(grid), []
    for k, x in S.items():
        for h in every:
            m_, se_, n_ = hac(_ic_xs(x, Zh[h], day), day_lags(h))
            ic_rows.append({"signal": k, "hold": h, "ic": m_, "ic_se": se_, "ic_t": m_ / se_ if se_ else np.nan})
    ic = pd.DataFrame(ic_rows).set_index(["signal", "hold"])
    r20 = audit.OUT / run / "features.csv"
    d_ic = float((pd.read_csv(r20).set_index("feature").loc[FEATURES, "ic"] - ic.xs(ref, level="hold").loc[FEATURES, "ic"]).abs().max()) if r20.exists() else np.nan
    v = {**v, "whole_days": whole, "days": nd, "shifts": len(ks), "max_abs_d_ic_r20": d_ic}
    v["status"] = "PASS" if v["status"] == "PASS" and whole and len(ks) == nd - 2 * gap_days(holds) + 1 and d_ic <= IC_TOL else "FAIL"

    n_cells = int(cm.sum())
    print(f"horizon: {len(S)} signals × holds {every} × {len(ks)} shifts on {n_cells:,} cells, {nd} days…", flush=True)
    d = pd.concat(Parallel(n_jobs=jobs, verbose=5)(delayed(_null)(k, x.to_numpy(), Y, ks) for k, x in S.items()), ignore_index=True)
    real, null = d[d["shift"] == 0].set_index(["signal", "hold"])["m"], d[d["shift"] > 0]
    st = null.groupby(["signal", "hold"])["m"].agg(centre="mean", se="std")
    centre, se = st["centre"], st["se"]
    null = null.join(st, on=["signal", "hold"])
    null["u"] = (null["m"] - null["centre"]) / null["se"]
    fam = null[null["signal"].isin(SIGNALS) & null["hold"].isin(holds)]
    mx = fam.assign(a=fam["u"].abs()).groupby("shift")["a"].max()

    fold_of = np.full(nd, "", dtype=object)
    days = pd.DatetimeIndex(grid[::PER_DAY]).floor("D")
    for f in fold_names:
        fold_of[folds.mask(pd.Series(days, index=days), f, embargoed=False).to_numpy()] = f
    rows, tenth = [], []
    for k, x in S.items():
        s = x.to_numpy()
        for h in every:
            m_day = _tenths(s, Y[h])
            m, c, e = float(real[(k, h)]), float(centre[(k, h)]), float(se[(k, h)])
            own = null[(null["signal"] == k) & (null["hold"] == h)]
            per_fold = {f: float(np.nanmean(m_day[fold_of == f])) for f in fold_names}
            after = float(np.nanmean(_tenths(s, Y[h] - Y[ref]))) if h != ref else np.nan
            _, se_hac, n_days = hac(m_day, day_lags(h))
            yc = np.where(np.isnan(s), np.nan, Y[h])
            with np.errstate(invalid="ignore", divide="ignore"):
                move = float(np.nanmean(np.abs(yc - np.nansum(yc, axis=1, keepdims=True) / (~np.isnan(yc)).sum(1, keepdims=True))))
            row = {"signal": k, "hold": h, "family": k in SIGNALS and h in holds, "cells": int((~np.isnan(s) & ~np.isnan(Y[h])).sum()), "days": n_days, "m": m, "centre": c,
                   "m_c": m - c, "se": e, "u": (m - c) / e, "se_hac": se_hac, "lo": m - c - 1.96 * e, "hi": m - c + 1.96 * e, "mde": MDE_K * e,
                   "p_single": (1 + int((own["u"].abs() >= abs((m - c) / e)).sum())) / (len(own) + 1), "p_family": (1 + int((mx >= abs((m - c) / e)).sum())) / (len(mx) + 1),
                   **{f"m_{f}": per_fold[f] for f in fold_names}, "folds_same_sign": bool(all(np.sign(per_fold[f]) == np.sign(m - c) for f in fold_names)),
                   "m_after_first": after, "after_same_sign": bool(np.sign(after) == np.sign(m - c)), "funding_part": m - float(np.nanmean(_tenths(s, G[h]))),
                   "ic": ic.loc[(k, h), "ic"], "ic_t": ic.loc[(k, h), "ic_t"], "move": move, "ic_needed": cost / (Z_TOP * 1.2533 * move)}
            rows.append({**row, "verdict": verdict(row, cost) if row["family"] else "reference"})
            tenth.append(_by_tenth(s, Y[h]).reset_index().assign(signal=k, hold=h))
    tab, tenth = pd.DataFrame(rows), pd.concat(tenth, ignore_index=True)
    fam_tab, ref_tab = tab[tab["family"]], tab[~tab["family"]]
    clears = fam_tab[fam_tab["verdict"] == "CLEARS"]
    wide = lambda c: tenth.pivot(index=["signal", "hold"], columns="tenth", values=c).reindex(pd.MultiIndex.from_frame(tab[["signal", "hold"]])).reset_index()      # noqa: E731

    show = lambda df, k=2: df.round(k).to_markdown(index=False)                         # noqa: E731
    main = ["signal", "hold", "cells", "m", "centre", "m_c", "se", "u", "lo", "hi", "mde", "p_single", "p_family", "verdict"]
    more = ["signal", "hold", *(f"m_{f}" for f in fold_names), "folds_same_sign", "m_after_first", "after_same_sign", "funding_part", "se_hac", "ic", "ic_t", "move", "ic_needed"]
    md = [f"# The longer hold (R22) — the cells of `{run}` (`ft2 horizon`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {len(names)} names, {n_cells:,} cells, {nd} days · holds {holds} bars "
          f"(reference {ref}) · {len(ks)} shifts · cost {cost:g} bps a leg\n",
          "\nWords: a *signal* is one number known about a name before the decision. *hold*: how long the position is kept, in 5-minute bars (288 = a day, 864 = 3 days, "
          "2016 = 7 days). *m*: what one leg of a book earns before trading costs that buys the tenth of names the signal ranks highest and sells the tenth it ranks lowest, "
          "in bps (0.01 %) of the position, funding paid; negative = the signal sorts the wrong way round. *centre*: what the same book earns when the moves are taken from "
          "other weeks — the part that belongs to the names, not to the timing. *m_c* = m − centre. *se*: how much m_c varies over those other weeks; *u* = m_c / se, 2 or "
          "more is the bar. *p (family)*: the share of shifts in which the BEST of the twelve did at least as well. *MDE*: the smallest m_c this sample could have shown.\n",
          "\n## Validity\n",
          f"\n**{v['status']}**: {v['cells']:,} cells of {v['names']} names, largest |Δ label| against the run's {v['max_abs_dz']:.3g} (bar {audit.Z_TOL:g}); "
          f"{v['cells_off_grid']} cells off the hourly grid, {v['cells_without_label']} without a label; the five features' IC at {ref} bars against R20's: largest "
          f"|Δ| {v['max_abs_d_ic_r20']:.3g} (bar {IC_TOL:g}); whole days: {v['whole_days']}; {v['shifts']} shifts on {v['days']} days.\n", *(f"\n- {n}" for n in notes),
          "\n## The family — six signals × two holds\n",
          f"\n**{len(clears)} of {len(fam_tab)} clear the gate** (|m_c| > {cost:g}, |u| ≥ {U_BAR:g}, family-wise p ≤ {P_BAR:g}, m of m_c's sign in every fold and after the first day)"
          f"{': ' + ', '.join(f'{a} at {b}' for a, b in zip(clears['signal'], clears['hold'])) if len(clears) else ''}. Over the shifts the best of the family reaches "
          f"|u| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty.\n", show(fam_tab[main]), "\n",
          "\n### Described (decides nothing)\n", show(fam_tab[more], 4), "\n",
          "\n## Reference rows — the one-day hold and R21's score (outside the family, no verdict)\n", show(ref_tab[main]), "\n", show(ref_tab[more], 4), "\n",
          "\n## The label against the bar's peers, by the signal's tenth (1 = lowest, 10 = highest), bps\n", "\n### mean\n", show(wide("mean"), 1), "\n",
          "\n### median\n", show(wide("median"), 1), "\n"]
    out = OUT / run
    out.mkdir(parents=True, exist_ok=True)
    (out / "horizon.md").write_text("\n".join(md))
    tab.to_csv(out / "signals.csv", index=False)
    tenth.to_csv(out / "tenths.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95)), "cost_bps": cost}, indent=1))
    return "\n".join(md)
