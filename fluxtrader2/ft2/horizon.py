"""P8 — the longer hold (PLAN §4 P8, registration R22 in §8). `ft2 horizon <run>` → output/horizon/<run>/horizon.md

Everything measured on names outside the twelve was measured at a one-day hold. A round trip costs the same whether a
position is held a day or a week: held 3 or 7 days, do the names a signal puts at the top earn more than the names it
puts at the bottom — in the mean, in bps, by more than the round trip? A ceiling audit: no model, no book, no fold spent.

cells      `audit.frame`'s: the scored cells of a `transferbook` run, hourly decision bars, the block's members.
label      what a long position earns before trading costs: the move from the close one bar after t to the close `hold`
           bars later — exit / entry − 1, the harness's unit; a log until 2026-09-30 (PLAN §3) — minus the funding a
           long pays over those bars (`backtest.load_costs`' cumulative funding), bps. The rank IC beside it keeps
           R20's vol-standardised log label: a rank, not money.
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
    """(the move, what a long earns): exit / entry − 1 between the entry bar and the exit bar — what a long of fixed
    size earns, never the log (PLAN §3) — and the same minus the funding it pays: `backtest.price`'s gross and
    gross + funding of a long."""
    fc = pd.DataFrame(fundcum, index=M.index, columns=M.columns)
    y = (M.close.shift(-(latency + hold)) / M.close.shift(-latency) - 1.0) * 1e4
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


def run(run: str, holds=HOLDS, members: str | None = None, cost: float = COST, jobs: int = 4, name: str | None = None) -> str:
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
    out = OUT / (name or run)
    out.mkdir(parents=True, exist_ok=True)
    (out / "horizon.md").write_text("\n".join(md))
    tab.to_csv(out / "signals.csv", index=False)
    tenth.to_csv(out / "tenths.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95)), "cost_bps": cost, "unit": bt.UNIT}, indent=1))
    return "\n".join(md)


# ---- R23: the one open-interest score on the months before F1 ---------------------------------------------------------------
# No run exists on those months (no model is fitted there), so the cells are built from the frozen members and the candles.
# ONE number is in the family — SCORE at PRE_HOLDS — and its direction is fixed: positive. `run` above is R22's and is
# not touched: R23's validity re-runs it after the ingest and asks for the same numbers.
PRE = "pre"
PRE_SIGNALS = [SCORE]
PRE_HOLDS = (2016,)
PRE_REFS = (288, 864)               # reference holds; the first is "the first day"
PRE_SKIP = ("2022-05", "2022-11")   # described: M with these calendar months left out (the two collapses of 2022)
PRE_FOLDS = ("FP", "F0")            # what the read is logged against (`backtest.READS`)
COVER_BAR = 0.90                    # validity: the score is there on at least this share of the cells
R22_CHECK = OUT / "r22_check.json"  # written by scripts/r23_check_r22.py: R22 came back after the ingest


def frame_pre(members=None, days=None, end=None, holds=(*PRE_REFS, *PRE_HOLDS)) -> dict:
    """The cells of R23: the hourly bars of the scored days × the block's members with a close at t, and their validity."""
    from . import universe
    from .__main__ import PAIRS
    mem = universe.members(members or universe.PRE_MEMBERS_CSV)
    a, b = (pd.Timestamp(d, tz="UTC") for d in (days or universe.PRE_DAYS))
    end = universe.PRE_END if end is None else pd.Timestamp(end) if pd.Timestamp(end).tzinfo else pd.Timestamp(end, tz="UTC")
    M = bt.market(sorted(mem["symbol"].unique()), end, start=a - audit.WARMUP)
    names = list(M.columns)
    idx = M.index[M.index >= a - audit.WARMUP]
    grid = pd.date_range(a, b + pd.Timedelta(hours=PER_DAY - 1), freq=audit.GRID)
    in_market = bool(grid.isin(idx).all())
    cell = pd.DataFrame(audit.member_mask(mem, np.asarray(names, dtype=str), grid), index=grid, columns=names) & M.close.reindex(grid).notna()

    # validity: membership looked up a second way, the twelve, the grid, whole days
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    pairs = set(zip(mem["block"], mem["symbol"]))
    i, j = np.nonzero(cell.to_numpy())
    blk = starts[np.clip(starts.searchsorted(grid[i], side="right") - 1, 0, None)]
    not_member = sum((x, names[k]) not in pairs for x, k in zip(blk, j))
    nd = len(grid) // PER_DAY
    ks = shifts(nd, gap_days(holds))
    v = {"cells": int(len(i)), "names": int(cell.any().sum()), "members_without_a_bar": sorted(set(mem["symbol"]) - set(names)), "days": nd,
         "first_bar": str(grid[0]), "last_bar": str(grid[-1]), "end": str(end), "grid_in_market": in_market, "cells_not_a_member": int(not_member),
         "cells_of_the_twelve": int(cell[[s for s in names if s in PAIRS]].to_numpy().sum()), "cells_at_or_after_end": int((grid[i] >= end).sum()),
         "whole_days": bool(len(grid) == nd * PER_DAY and grid[0].hour == 0), "shifts": len(ks)}
    return {"mem": mem, "M": M, "names": names, "idx": idx, "grid": grid, "cell": cell, "end": end, "ks": ks, "validity": v}


def _null_kept(name: str, S: np.ndarray, Y: dict[int, np.ndarray], ks: np.ndarray) -> pd.DataFrame:
    """`_null`, with the cells that have the signal and a label under each shift."""
    rows, has = [], ~np.isnan(S)
    for h, y in Y.items():
        for k in [0, *ks]:
            ys = y[shifted(len(y), k)] if k else y
            rows.append({"signal": name, "hold": h, "shift": int(k), "m": float(np.nanmean(_tenths(S, ys))), "cells": int((has & ~np.isnan(ys)).sum())})
    return pd.DataFrame(rows)


def verdict_pre(r: dict, cost: float = COST) -> str:
    """Stage 1 of R23, one-sided: the direction is fixed (positive)."""
    if r["m_c"] > cost and r["u"] >= U_BAR and r["p_one"] <= P_BAR and r["halves_positive"] and r["m_after_first"] > 0:
        return "CLEARS"
    if r["m_c"] + 1.96 * r["se"] < cost:
        return "CLOSED"
    return "GO ON" if r["m_c"] > cost else "PARKED"


def pooled(s1: dict, s2: dict, cost: float = COST) -> dict:
    """R23's pooled rule, fixed at registration: the two stages (m_c, se, days, m_after_first) weighted by their scored days."""
    w1 = s1["days"] / (s1["days"] + s2["days"])
    w2 = 1.0 - w1
    m_c, se = w1 * s1["m_c"] + w2 * s2["m_c"], float(np.sqrt((w1 * s1["se"]) ** 2 + (w2 * s2["se"]) ** 2))
    r = {"m_c": m_c, "se": se, "u": m_c / se, "mde": MDE_K * se}
    if m_c > cost and r["u"] >= U_BAR and s2["m_c"] > 0 and s2["m_after_first"] > 0:
        return {**r, "verdict": "CLEARS"}
    return {**r, "verdict": "CLOSED" if m_c + 1.96 * se < cost else "NOT DETECTABLE"}


def run_pre(holds=PRE_HOLDS, refs=PRE_REFS, members=None, days=None, end=None, cost: float = COST, skip=PRE_SKIP, registration: str | None = "R23",
            jobs: int = 4, name: str = PRE, reexecute: str | None = None) -> str:
    from joblib import Parallel, delayed
    from .forecast import _derive
    holds, refs = [int(h) for h in holds], [int(h) for h in refs]
    every, first, latency = [*refs, *holds], refs[0], bt.LATENCY
    if registration:                                          # the pre-history is read once per registered question, and only once R22 came back
        conf = bt._guard(PRE_FOLDS, registration, reexecute)
        registration = bt.read_tag(registration, reexecute)
        if not (R22_CHECK.exists() and json.loads(R22_CHECK.read_text()).get("status") == "PASS"):
            raise SystemExit(f"{R22_CHECK} does not say PASS: re-run R22 after the ingest and compare it first (scripts/r23_check_r22.py)")
    A = frame_pre(members, days, end, every)
    M, names, idx, grid, cell, end, ks, v = (A[k] for k in ("M", "names", "idx", "grid", "cell", "end", "ks", "validity"))
    nd, cm = v["days"], cell.to_numpy()
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)

    # the signals, on the cells
    F, notes = audit.features(idx, names, M.dv.loc[idx, names], end, only=audit.OI)
    F = {k: x.reindex(grid).where(cell) for k, x in F.items()}
    has = np.logical_and.reduce([F[k].notna().to_numpy() for k in audit.OI])
    r = {k: F[k].where(has).rank(axis=1, pct=True) for k in audit.OI}
    S = {SCORE: r["oi_turn"] - 0.5 * (r["oi_chg_1d"] + r["oi_chg_1w"]), **{k: F[k] for k in audit.OI}}
    n_cells = int(cm.sum())
    v["score_coverage"] = float(S[SCORE].notna().to_numpy().sum() / max(n_cells, 1))
    ok = (v["grid_in_market"] and v["whole_days"] and n_cells > 0 and not (v["cells_not_a_member"] or v["cells_of_the_twelve"] or v["cells_at_or_after_end"])
          and v["shifts"] == nd - 2 * gap_days(every) + 1 and v["score_coverage"] >= COVER_BAR)
    v["status"] = "PASS" if ok else "FAIL"
    (out / "validity.json").write_text(json.dumps({**v, "cost_bps": cost, "notes": notes, "unit": bt.UNIT}, indent=1))
    if not ok:                                                # void: no number is computed on cells that are not the registered ones
        raise SystemExit(f"validity FAIL, nothing was read: {v}")

    # the labels: the price move (gross), and what a long earns (the move minus the funding it pays)
    fundcum = bt.load_costs(M.index, M.columns, end).fundcum
    G, Y = ({h: labels(M, fundcum, h, latency)[i].reindex(grid)[names].to_numpy() for h in every} for i in (0, 1))
    sig = _derive(M.close.loc[idx, names])["sig"]["1w"]
    Zh = {h: (bt.labels(M, h, latency).loc[idx, names] / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).reindex(grid) for h in every}

    print(f"horizon --pre: {len(S)} signals × holds {every} × {len(ks)} shifts on {n_cells:,} cells, {nd} days…", flush=True)
    d = pd.concat(Parallel(n_jobs=jobs, verbose=5)(delayed(_null_kept)(k, x.to_numpy(), Y, ks) for k, x in S.items()), ignore_index=True)
    real, null = d[d["shift"] == 0].set_index(["signal", "hold"]), d[d["shift"] > 0]
    st = null.groupby(["signal", "hold"]).agg(centre=("m", "mean"), se=("m", "std"), kept=("cells", "mean"))
    null = null.join(st[["centre", "se"]], on=["signal", "hold"])
    null["u"] = (null["m"] - null["centre"]) / null["se"]

    day = audit._day(grid)
    dates = pd.DatetimeIndex(grid[::PER_DAY]).floor("D")
    half = np.where(np.arange(nd) < nd // 2, "H1", "H2")
    kept_days = ~np.isin(dates.tz_localize(None).to_period("M").astype(str), list(skip))
    rows, tenth = [], []
    for k, x in S.items():
        s = x.to_numpy()
        for h in every:
            m_day = _tenths(s, Y[h])
            m, c, e = float(real.loc[(k, h), "m"]), float(st.loc[(k, h), "centre"]), float(st.loc[(k, h), "se"])
            u = (m - c) / e
            own = null[(null["signal"] == k) & (null["hold"] == h)]
            per_half = {f: float(np.nanmean(m_day[half == f])) for f in ("H1", "H2")}
            after = float(np.nanmean(_tenths(s, Y[h] - Y[first]))) if h != first else np.nan
            _, se_hac, n_days = hac(m_day, day_lags(h))
            ic, ic_se, _ = hac(_ic_xs(x, Zh[h], day), day_lags(h))
            yc = np.where(np.isnan(s), np.nan, Y[h])
            with np.errstate(invalid="ignore", divide="ignore"):
                move = float(np.nanmean(np.abs(yc - np.nansum(yc, axis=1, keepdims=True) / (~np.isnan(yc)).sum(1, keepdims=True))))
            row = {"signal": k, "hold": h, "family": k in PRE_SIGNALS and h in holds, "cells": int(real.loc[(k, h), "cells"]), "days": n_days, "m": m, "centre": c,
                   "m_c": m - c, "se": e, "u": u, "se_hac": se_hac, "lo": m - c - 1.96 * e, "hi": m - c + 1.96 * e, "mde": MDE_K * e,
                   "p_one": (1 + int((own["u"] >= u).sum())) / (len(own) + 1), "m_H1": per_half["H1"], "m_H2": per_half["H2"],
                   "halves_positive": bool(per_half["H1"] > 0 and per_half["H2"] > 0), "m_after_first": after, "funding_part": m - float(np.nanmean(_tenths(s, G[h]))),
                   "m_skip": float(np.nanmean(m_day[kept_days])), "kept_by_a_shift": float(st.loc[(k, h), "kept"] / max(real.loc[(k, h), "cells"], 1)),
                   "ic": ic, "ic_t": ic / ic_se if ic_se else np.nan, "move": move, "ic_needed": cost / (Z_TOP * 1.2533 * move)}
            rows.append({**row, "verdict": verdict_pre(row, cost) if row["family"] else "reference"})
            tenth.append(_by_tenth(s, Y[h]).reset_index().assign(signal=k, hold=h))
    tab, tenth = pd.DataFrame(rows), pd.concat(tenth, ignore_index=True)
    fam_tab, ref_tab = tab[tab["family"]], tab[~tab["family"]]
    wide = lambda c: tenth.pivot(index=["signal", "hold"], columns="tenth", values=c).reindex(pd.MultiIndex.from_frame(tab[["signal", "hold"]])).reset_index()      # noqa: E731
    starts = pd.DatetimeIndex(sorted(A["mem"]["block"].unique()))
    per_block = pd.DataFrame({"block": starts[np.clip(starts.searchsorted(grid, side="right") - 1, 0, None)].date, "cells": cm.sum(1), "with_score": S[SCORE].notna().to_numpy().sum(1)}
                             ).groupby("block").agg(bars=("cells", "size"), cells_per_bar=("cells", "mean"), with_score_per_bar=("with_score", "mean")).reset_index()

    show = lambda df, k=2: df.round(k).to_markdown(index=False)                         # noqa: E731
    main = ["signal", "hold", "cells", "m", "centre", "m_c", "se", "u", "lo", "hi", "mde", "p_one", "verdict"]
    more = ["signal", "hold", "m_H1", "m_H2", "halves_positive", "m_after_first", "funding_part", "m_skip", "kept_by_a_shift", "se_hac", "ic", "ic_t", "move", "ic_needed"]
    md = [f"# The open-interest score on the months before F1 (R23, stage 1) — `ft2 horizon --pre`\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · scored days {dates[0].date()} → {dates[-1].date()} · {v['names']} names, {n_cells:,} cells, {nd} days · "
          f"family: {', '.join(PRE_SIGNALS)} at {holds} bars, direction positive · reference holds {refs} · {len(ks)} shifts · cost {cost:g} bps a leg\n",
          "\nWords: the *score* ranks the names at one moment by their open interest (the total size of the positions open in a name): high = much open interest against "
          "the day's trading and open interest that has been falling; low = a name in a trading frenzy. *hold*: how long the position is kept, in 5-minute bars (288 = a "
          "day, 864 = 3 days, 2016 = 7 days). *m*: what one leg of a book earns before trading costs that buys the tenth of names the score ranks highest and sells the "
          "tenth it ranks lowest, in bps (0.01 %) of the position — 1 bps is 1 USDT on 10,000 — funding paid. *centre*: what the same book earns when the moves are taken "
          "from other weeks — the part that belongs to the names, not to the timing. *m_c* = m − centre. *se*: how much m_c varies over those other weeks; *u* = m_c / se, "
          "2 or more is the bar. *p*: the share of those other weeks' books that did at least as well. *MDE*: the smallest m_c this sample could have shown. *H1, H2*: "
          "the two halves of the scored days.\n",
          "\n## Validity\n",
          f"\n**{v['status']}**: {v['cells']:,} cells of {v['names']} names on {nd} whole days ({v['first_bar']} → {v['last_bar']}; the market ends at {v['end']}); cells of a name "
          f"that is not a member of its block: {v['cells_not_a_member']}; cells of the twelve: {v['cells_of_the_twelve']}; cells at or after the end: {v['cells_at_or_after_end']}; "
          f"{v['shifts']} shifts; the score is there on {v['score_coverage']:.1%} of the cells (bar {COVER_BAR:.0%}); members without a 5m bar: "
          f"{', '.join(v['members_without_a_bar']) or 'none'}.\n", *(f"\n- {n}" for n in notes),
          "\n## The family — one number\n",
          f"\nGate: CLEARS if m_c > {cost:g}, u ≥ {U_BAR:g}, p ≤ {P_BAR:g}, m > 0 in both halves and after the first day; CLOSED if m_c + 1.96 se < {cost:g}; GO ON if m_c > {cost:g} "
          f"without clearing; PARKED otherwise.\n", show(fam_tab[main]), "\n",
          "\n### Described (decides nothing)\n", show(fam_tab[more], 4), "\n",
          "\n## Reference rows — the three features alone and the shorter holds (outside the family, no verdict)\n", show(ref_tab[main]), "\n", show(ref_tab[more], 4), "\n",
          "\n## The label against the bar's peers, by the signal's tenth (1 = lowest, 10 = highest), bps\n", "\n### mean\n", show(wide("mean"), 1), "\n",
          "\n### median\n", show(wide("median"), 1), "\n",
          "\n## Members with a bar, per block\n", show(per_block, 1), "\n"]
    (out / "horizon.md").write_text("\n".join(md))
    tab.to_csv(out / "signals.csv", index=False)
    tenth.to_csv(out / "tenths.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    per_block.to_csv(out / "blocks.csv", index=False)
    if registration:                                          # only once the number exists
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "horizon --pre",
                      "params": json.dumps({"holds": holds, "refs": refs, "signals": PRE_SIGNALS})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    return "\n".join(md)
