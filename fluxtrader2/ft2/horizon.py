"""P8 — the longer hold (PLAN §4 P8, registration R22 in §8). `ft2 horizon <run>` → output/horizon/<run>/horizon.md

Everything measured on names outside the twelve was measured at a one-day hold. A round trip costs the same whether a
position is held a day or a week: held 3 or 7 days, do the names a signal puts at the top earn more than the names it
puts at the bottom — in the mean, in bps, by more than the round trip? A ceiling audit: no model, no book, no fold spent.

cells      `audit.frame`'s: the scored cells of a `transferbook` run, hourly decision bars, the block's members.
label      what a long position earns before trading costs: the move from the close one bar after t to the close `hold`
           bars later — exit / entry − 1, the harness's unit; a log until 2026-09-30 (PLAN §3) — minus the funding a
           long pays over those bars, each payment on the position's value at that moment (`backtest.load_costs`'
           `fundval` ÷ the entry close; on its size at entry until 2026-10-01), bps. The rank IC beside it keeps
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


def labels(M: bt.Market, C: bt.Costs, hold: int, latency: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(the move, what a long earns): exit / entry − 1 between the entry bar and the exit bar — what a long of fixed
    size earns, never the log (PLAN §3) — and the same minus the funding it pays, each payment on the position's value
    at that moment (`C.fundval`, ÷ the entry close): `backtest.price`'s gross and gross + funding of a long."""
    assert C.fundval is not None, "horizon.labels: the costs were loaded without the market's close"
    fv = pd.DataFrame(C.fundval, index=M.index, columns=M.columns)
    pe = M.close.shift(-latency)
    y = (M.close.shift(-(latency + hold)) / pe - 1.0) * 1e4
    return y, y - (fv.shift(-(latency + hold)) - fv.shift(-latency)) / pe


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


def _tenths(S: np.ndarray, Y: np.ndarray, min_cells: int | None = None) -> np.ndarray:
    """Per bar with ≥ `min_cells` cells that have the signal and the label: the mean label of the k highest by the signal
    minus that of the k lowest, halved; k = the tenth of them, rounded (at least one). Averaged per day (PER_DAY rows a day).
    `min_cells` is MIN_CELLS for every registered statistic; R35's described rows on one universe at a time pass a smaller one."""
    min_cells = MIN_CELLS if min_cells is None else min_cells            # read at call time: the tests set the module's floor
    ok = ~(np.isnan(S) | np.isnan(Y))
    n = ok.sum(1)
    k = np.maximum(np.rint(n * TENTH).astype(int), 1)
    r = _ranks(S, ok)
    y = np.where(ok, Y, 0.0)
    lo, hi = r <= k[:, None], (r > (n - k)[:, None]) & (r <= n[:, None])
    with np.errstate(invalid="ignore", divide="ignore"):
        m = ((y * hi).sum(1) - (y * lo).sum(1)) / k / 2.0
    m[n < min_cells] = np.nan
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
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    G, Y = ({h: labels(M, C, h, latency)[i].loc[grid, names].to_numpy() for h in every} for i in (0, 1))
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
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95)), "cost_bps": cost, "unit": bt.UNIT, "charged": bt.CHARGED}, indent=1))
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
    (out / "validity.json").write_text(json.dumps({**v, "cost_bps": cost, "notes": notes, "unit": bt.UNIT, "charged": bt.CHARGED}, indent=1))
    if not ok:                                                # void: no number is computed on cells that are not the registered ones
        raise SystemExit(f"validity FAIL, nothing was read: {v}")

    # the labels: the price move (gross), and what a long earns (the move minus the funding it pays)
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    G, Y = ({h: labels(M, C, h, latency)[i].reindex(grid)[names].to_numpy() for h in every} for i in (0, 1))
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


# ---- R35: the slow book at a longer hold --------------------------------------------------------------------------------------
# The ±1 % imbalance's month-mean (`book_ext.LVL`), found twice at one day (R33, R34), and the raw imbalance, at 3 and 7 days in R22's
# frame on the 43 names whose book is in hand (the eleven + universe.NEW), hourly cells of F1+F2. `run` above is R22's and is not
# touched; this reuses its label, statistic, null, by-tenth table and verdict. Cost 15 bps a leg, fixed in the registration. The sign is
# registered NEGATIVE (a bid-heavy month precedes the worse week): a clear with M_c > 0 is recorded as "with the opposite sign".
BOOK_HOLDS = (864, 2016)
BOOK_REF = 288
BOOK_COST = 15.0                      # R35: the 43 names
BOOK_COST_BY_UNIVERSE = {"screen": 25.0}   # R36: the 188 screener members (their proxy round trip 23.2, rounded up) — fixed in the registration
BOOK_REG_BY_UNIVERSE = {"screen": "R36"}
BOOK_WINDOW_DAYS = 30                 # the slow level's window: the null's gap = this + the longest hold in days + 1
BOOK_MIN_CELLS_ONE = 8                # the described rows on one part of the universe at a time (the eleven: one name a side)
WINSOR = 1000.0                       # R36, described: M with every label clipped at ±WINSOR bps (the young-name tail's weight)
FUND_COVER = 0.95


def _book_signals() -> tuple[list[str], list[str]]:
    from .book_ext import DM, LVL, RAW
    return [LVL, RAW], [DM]


def book_verdict(r: dict, cost: float = BOOK_COST) -> str:
    v = verdict(r, cost)
    return ("CLEARS" if r["m_c"] < 0 else "CLEARS WITH THE OPPOSITE SIGN") if v == "CLEARS" else v


def run_book(symbols: list[str], holds=BOOK_HOLDS, ref: int = BOOK_REF, cost: float | None = None, universe: str = "both", jobs: int = 4,
             name: str | None = None, twelve: list[str] | None = None, md5_file: Path | None = None,
             split: tuple[str, list[str]] | None = None) -> str:
    import hashlib
    from joblib import Parallel, delayed
    from . import book_ext, ceiling, data
    from .ceiling import END, W
    fam, described = _book_signals()
    cost = BOOK_COST_BY_UNIVERSE.get(universe, BOOK_COST) if cost is None else cost      # the registered cost of the universe read
    reg = BOOK_REG_BY_UNIVERSE.get(universe, "R35")
    if md5_file is None:                                                  # the chain's md5s of the depth files in hand before the fetch: R34's for the 43, R36's for the members
        md5_file = Path("output/logs/r36_md5_after.txt" if universe == "screen" else "output/logs/r34_md5_after.txt")
    holds = [int(h) for h in holds]
    every = [ref, *holds]
    fold_names = list(folds.EXPLORATION)
    out = OUT / (name or f"book_{universe}")
    out.mkdir(parents=True, exist_ok=True)
    print("market…", flush=True)
    M = bt.market(symbols, END)
    idx, names = M.index, list(M.columns)
    t5 = pd.Series(idx, index=idx)
    scored = np.zeros(len(idx), dtype=bool)
    for f in fold_names:
        scored |= folds.mask(t5, f).to_numpy()
    grid = idx[scored & (idx.minute == 0) & (idx.second == 0)]
    n_rows, nd = len(grid), len(grid) // PER_DAY
    day = (grid.floor("D") - grid[0].floor("D")).days.to_numpy()
    whole = bool(n_rows == nd * PER_DAY and (np.bincount(day)[np.bincount(day) > 0] == PER_DAY).all())
    gap = BOOK_WINDOW_DAYS + int(np.ceil(max(holds) / 288)) + 1
    ks = shifts(nd, gap)

    print("labels (actual returns, funding on value) and the book's three frames…", flush=True)
    C = bt.load_costs(idx, M.columns, END, close=M.close)
    G, Y = ({h: labels(M, C, h, bt.LATENCY)[i].loc[grid, names].to_numpy() for h in every} for i in (0, 1))
    sig = (np.log(M.close).diff() * 1e4).rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std()
    Zh = {h: (bt.labels(M, h, bt.LATENCY) / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).loc[grid, names] for h in every}
    F5 = book_ext.features_depth(idx, names, END)
    F = {k: v.loc[grid] for k, v in F5.items()}
    S = {k: F[k] for k in [*fam, *described]}

    # validity, read first
    again = book_ext.features_depth(idx, names, END)
    d_frames = max(float((again[k].loc[grid] - F[k]).abs().max().max()) if F[k].notna().any().any() else 0.0 for k in F)
    actual_from_log = (np.exp(bt.labels(M, ref, bt.LATENCY).loc[grid, names].to_numpy() / 1e4) - 1.0) * 1e4
    both = ~np.isnan(G[ref]) & ~np.isnan(actual_from_log)
    d_label = float(np.abs(G[ref] - actual_from_log)[both].max()) if both.any() else np.nan
    fund_cover = {c: float(np.isfinite(Y[ref][:, j][~np.isnan(G[ref][:, j])]).mean()) if (~np.isnan(G[ref][:, j])).any() else 0.0 for j, c in enumerate(names)}
    md5s = {}
    if md5_file.exists():
        want = dict(reversed(line.split()) for line in md5_file.read_text().splitlines() if line.strip())
        for p, h in want.items():
            f = Path(p)
            md5s[f.stem] = "same" if f.exists() and hashlib.md5(f.read_bytes()).hexdigest() == h else "DIFFERENT"
    v = {"registration": reg, "universe": universe, "names": len(names), "pairs": names, "folds": fold_names, "days": nd, "rows": n_rows, "whole_days": whole,
         "gap_days": gap, "shifts": len(ks), "shifts_expected": nd - 2 * gap + 1, "max_abs_d_frames": d_frames, "max_abs_d_label_288": d_label,
         "funding_cover_by_name": {k: round(x, 4) for k, x in fund_cover.items()}, "names_under_funding_cover": [k for k, x in fund_cover.items() if x < FUND_COVER],
         "depth_md5_vs_r34": md5s, "cells": {str(h): int((~np.isnan(Y[h])).sum()) for h in every}, "cost_bps": cost, "unit": bt.UNIT, "charged": bt.CHARGED}
    v["status"] = "PASS" if (whole and len(ks) == v["shifts_expected"] and len(ks) >= 20 and d_frames == 0.0 and np.isfinite(d_label) and d_label <= 1e-9
                             and not v["names_under_funding_cover"] and "DIFFERENT" not in md5s.values()) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {reg} — the slow book at a longer hold: the cells of `{universe}` ({len(names)} names) (`ft2 horizon --book --universe {universe}`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {nd} days · holds {holds} bars (reference {ref}) · {len(ks)} shifts "
            f"(gap {gap} days) · cost {cost:g} bps a leg · the registered sign negative\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "horizon.md").write_text("\n".join(head + ["\n**The read is VOID: nothing of the family was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    n_cells = int((~np.isnan(Y[ref])).sum())
    print(f"horizon --book: {len(S)} signals × holds {every} × {len(ks)} shifts on {n_cells:,} cells, {nd} days…", flush=True)
    d = pd.concat(Parallel(n_jobs=jobs, verbose=5)(delayed(_null)(k, x.to_numpy(), Y, ks) for k, x in S.items()), ignore_index=True)
    real, null = d[d["shift"] == 0].set_index(["signal", "hold"])["m"], d[d["shift"] > 0]
    st = null.groupby(["signal", "hold"])["m"].agg(centre="mean", se="std")
    centre, se = st["centre"], st["se"]
    null = null.join(st, on=["signal", "hold"])
    null["u"] = (null["m"] - null["centre"]) / null["se"]
    famn = null[null["signal"].isin(fam) & null["hold"].isin(holds)]
    mx = famn.assign(a=famn["u"].abs()).groupby("shift")["a"].max()

    # the cells' actual taker round trip on the extreme tenths (the proxy for a name the tape never priced)
    ct = ceiling.bar_cost(idx, names, 5.0, 2.0)[0].loc[grid].to_numpy()
    if split is None:                                                     # the described split: the twelve vs the rest (R35); in R10's forty vs the rest (R36)
        from .universe import NEW
        split = ("twelve", list(twelve or [])) if universe != "screen" else ("r10", list(NEW))
    label_a, part_a = split[0], set(split[1])
    j11 = np.array([c in part_a for c in names])
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
            m_ic, se_ic, _ = hac(_ic_xs(x, Zh[h], day), day_lags(h))
            yc = np.where(np.isnan(s), np.nan, Y[h])
            with np.errstate(invalid="ignore", divide="ignore"):
                move = float(np.nanmean(np.abs(yc - np.nansum(yc, axis=1, keepdims=True) / (~np.isnan(yc)).sum(1, keepdims=True))))
            ok = ~(np.isnan(s) | np.isnan(Y[h]))
            n = ok.sum(1)
            kk = np.maximum(np.rint(n * TENTH).astype(int), 1)
            r = _ranks(s, ok)
            ext = ((r <= kk[:, None]) | ((r > (n - kk)[:, None]) & (r <= n[:, None]))) & ok & (n >= MIN_CELLS)[:, None]
            rt_ext = float(np.nanmean(np.where(ext, ct, np.nan))) if ext.any() else np.nan
            m11 = float(np.nanmean(_tenths(s[:, j11], Y[h][:, j11], BOOK_MIN_CELLS_ONE))) if j11.sum() >= BOOK_MIN_CELLS_ONE else np.nan
            m32 = float(np.nanmean(_tenths(s[:, ~j11], Y[h][:, ~j11], BOOK_MIN_CELLS_ONE))) if (~j11).sum() >= BOOK_MIN_CELLS_ONE else np.nan
            m_w = float(np.nanmean(_tenths(s, np.clip(Y[h], -WINSOR, WINSOR))))
            row = {"signal": k, "hold": h, "family": k in fam and h in holds, "cells": int(ok.sum()), "days": n_days, "m": m, "centre": c, "m_c": m - c, "se": e,
                   "u": (m - c) / e if e else np.nan, "se_hac": se_hac, "lo": m - c - 1.96 * e, "hi": m - c + 1.96 * e, "mde": MDE_K * e,
                   "p_single": (1 + int((own["u"].abs() >= abs((m - c) / e)).sum())) / (len(own) + 1), "p_family": (1 + int((mx >= abs((m - c) / e)).sum())) / (len(mx) + 1),
                   **{f"m_{f}": per_fold[f] for f in fold_names}, "folds_same_sign": bool(all(np.sign(per_fold[f]) == np.sign(m - c) for f in fold_names if np.isfinite(per_fold[f])) and any(np.isfinite(per_fold[f]) for f in fold_names)),
                   "m_after_first": after, "after_same_sign": bool(np.sign(after) == np.sign(m - c)), "funding_part": m - float(np.nanmean(_tenths(s, G[h]))),
                   f"m_{label_a}": m11, "m_rest": m32, "m_winsorised": m_w, "rt_extreme_tenths": rt_ext, "ic": m_ic, "ic_t": m_ic / se_ic if se_ic else np.nan, "move": move,
                   "ic_needed": cost / (Z_TOP * 1.2533 * move) if move else np.nan}
            rows.append({**row, "verdict": book_verdict(row, cost) if row["family"] else "reference"})
            tenth.append(_by_tenth(s, Y[h]).reset_index().assign(signal=k, hold=h))
    tab, tenth = pd.DataFrame(rows), pd.concat(tenth, ignore_index=True)
    fam_tab, ref_tab = tab[tab["family"]], tab[~tab["family"]]
    clears = fam_tab[fam_tab["verdict"].str.startswith("CLEARS")]
    wide = lambda c: tenth.pivot(index=["signal", "hold"], columns="tenth", values=c).reindex(pd.MultiIndex.from_frame(tab[["signal", "hold"]])).reset_index()      # noqa: E731
    show = lambda df, k=2: df.round(k).to_markdown(index=False)                         # noqa: E731
    main = ["signal", "hold", "cells", "m", "centre", "m_c", "se", "u", "lo", "hi", "mde", "p_single", "p_family", "verdict"]
    more = ["signal", "hold", *(f"m_{f}" for f in fold_names), "folds_same_sign", "m_after_first", "after_same_sign", "funding_part", f"m_{label_a}", "m_rest", "m_winsorised",
            "rt_extreme_tenths", "se_hac", "ic", "ic_t", "move", "ic_needed"]
    md = head + [
        "\nWords: *m*: what one leg of a book earns before trading costs that buys the tenth of names the signal ranks highest and sells the tenth it ranks lowest, in bps "
        "of the position, funding paid, against the bar's peers; NEGATIVE is the registered direction (a bid-heavy month → the worse week, so the book sells the top tenth). "
        "*centre*: the same book on moves taken from other weeks; *m_c* = m − centre; *se*: its spread over those weeks; *u* = m_c / se; *p (family)*: the share of shifts "
        "in which the best of the four did at least as well. *m_<part>*, *m_rest*: the universe's two parts apart (the twelve vs the rest, or the names in R10's forty vs the rest; described). *m_winsorised*: M with every label clipped at ±1,000 bps. *rt_extreme_tenths*: "
        "the cells' own taker round trip on the tenths traded (the proxy for the 32), against the fixed cost.\n",
        f"\n## The family — two signals × two holds: **{len(clears)} of {len(fam_tab)} clear** (|m_c| > {cost:g}, |u| ≥ {U_BAR:g}, family-wise p ≤ {P_BAR:g}, m of m_c's "
        f"sign in every fold and after the first day; the registered sign negative)"
        f"{': ' + ', '.join(f'{a} at {b} ({c})' for a, b, c in zip(clears['signal'], clears['hold'], clears['verdict'])) if len(clears) else ''}. Over the shifts the best "
        f"of the family reaches |u| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty.\n", show(fam_tab[main]), "\n",
        "\n### Described (decides nothing)\n", show(fam_tab[more], 4), "\n",
        "\n## Reference rows — the one-day hold and the within-month part at every hold (outside the family, no verdict)\n", show(ref_tab[main]), "\n", show(ref_tab[more], 4), "\n",
        "\n## The label against the bar's peers, by the signal's tenth (1 = lowest, 10 = highest), bps\n", "\n### mean\n", show(wide("mean"), 1), "\n",
        "\n### median\n", show(wide("median"), 1), "\n"]
    (out / "horizon.md").write_text("\n".join(md))
    tab.to_csv(out / "signals.csv", index=False)
    tenth.to_csv(out / "tenths.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95))}, indent=1, default=str))
    print(f"{reg}: {len(clears)} of {len(fam_tab)} clear; wrote {out}/", flush=True)
    return "\n".join(md)


# ---- R43: the slow cross-section — the members' trailing return, held 2 and 4 weeks (PLAN §8 R43) ---------------------------------
# Every per-name read stopped at a 7-day hold. Here the cells are the 188 screener members' own (the block's members on the
# hourly grid of F1+F2, `audit.member_mask`), the signals the name's trailing 4- and 12-week return (the ranking inside a bar
# is against the peers), the holds 14 and 28 days, R22's statistic and null with the gap grown to the signal's window.
# `run` and `run_book` above are R22's and R35's and are not touched.
MOM_HOLDS = (4032, 8064)                 # 14 and 28 days
MOM_REFS = (288, 2016)                   # one day (validity (2)) and the first week (the "after the first week" part)
MOM_FAMILY = {"mom_4w": 8064, "mom_12w": 24192}      # the family: the trailing return over this many bars
MOM_DESCRIBED = {"mom_1w": 2016}                     # outside the family: the week's move (the reversal's cousin)
MOM_COST = 17.6                          # bps a leg, FIXED in R43: R22's on these members
MOM_WINDOW_DAYS = 84                     # the longest signal window: the null's gap = this + the longest hold in days + 1 = 113
MOM_WINSOR = 3000.0                      # described: M with every label clipped at ±MOM_WINSOR bps
MOM_FUND_COVER = 0.95                    # a name's labelled cells with funding present, else the name is dropped and listed
MOM_MAX_DROPPED = 0.10                   # more than this share of the members dropped voids the run
MOM_NAME, MOM_REG = "mom_screen", "R43"


def mom_signals(close: pd.DataFrame, windows: dict[str, int]) -> dict[str, pd.DataFrame]:
    """The name's own trailing return over `w` bars: close[t] / close[t − w] − 1 — closes at or before t only."""
    return {k: close / close.shift(w) - 1.0 for k, w in windows.items()}


def mom_gap_days(holds) -> int:
    return MOM_WINDOW_DAYS + int(np.ceil(max(holds) / 288)) + 1


def mom_verdict(r: dict, cost: float = MOM_COST) -> str:
    """R43's gate: the registered sign POSITIVE (momentum). CLOSED is one-sided — the upper bound under the cost."""
    strong = abs(r["u"]) >= U_BAR and r["p_family"] <= P_BAR and r["folds_same_sign"] and r["after_same_sign"]
    if r["m_c"] > cost and strong:
        return "CLEARS"
    if r["m_c"] < -cost and strong:
        return "CLEARS WITH THE OPPOSITE SIGN"
    return "CLOSED" if r["m_c"] + 1.96 * r["se"] < cost else "NOT DETECTABLE"


def run_mom(symbols: list[str], holds=MOM_HOLDS, refs=MOM_REFS, cost: float = MOM_COST, jobs: int = 4, name: str | None = None,
            members: str | None = None, end: pd.Timestamp | None = None, fold_names=None) -> str:
    from joblib import Parallel, delayed
    from . import ceiling, universe
    from .ceiling import W
    holds, refs = [int(h) for h in holds], [int(h) for h in refs]
    every = [*refs, *holds]
    first_week = refs[-1]
    fold_names = list(fold_names or folds.EXPLORATION)
    end = ceiling.END if end is None else end
    out = OUT / (name or MOM_NAME)
    out.mkdir(parents=True, exist_ok=True)
    mem = universe.members(members)
    print("market…", flush=True)
    M = bt.market(symbols, end)
    idx, names = M.index, list(M.columns)
    t5 = pd.Series(idx, index=idx)
    scored = np.zeros(len(idx), dtype=bool)
    for f in fold_names:
        scored |= folds.mask(t5, f).to_numpy()
    grid = idx[scored & (idx.minute == 0) & (idx.second == 0)]
    n_rows, nd = len(grid), len(grid) // PER_DAY
    day = (grid.floor("D") - grid[0].floor("D")).days.to_numpy()
    whole = bool(n_rows == nd * PER_DAY and (np.bincount(day)[np.bincount(day) > 0] == PER_DAY).all())
    gap = mom_gap_days(holds)
    ks = shifts(nd, gap)
    cell = audit.member_mask(mem, np.asarray(names), grid)                      # the block's members, point in time

    print("labels (actual returns, funding on value) and the signals…", flush=True)
    C = bt.load_costs(idx, M.columns, end, close=M.close)
    G, Y = ({h: labels(M, C, h, bt.LATENCY)[i].loc[grid, names].to_numpy() for h in every} for i in (0, 1))
    G = {h: np.where(cell, g, np.nan) for h, g in G.items()}
    Y = {h: np.where(cell, y, np.nan) for h, y in Y.items()}
    sig = (np.log(M.close).diff() * 1e4).rolling(W["1w"], min_periods=int(W["1w"] * 0.8)).std()
    Zh = {h: (bt.labels(M, h, bt.LATENCY) / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).loc[grid, names] for h in every}
    windows = {**MOM_FAMILY, **MOM_DESCRIBED}
    S_full = mom_signals(M.close, windows)
    S = {k: x.loc[grid, names].where(pd.DataFrame(cell, index=grid, columns=names)) for k, x in S_full.items()}

    # validity (3): the signals are causal — recomputed on the market cut at the midpoint, every value at or before it identical
    mid = grid[n_rows // 2]
    again = mom_signals(M.close.loc[M.close.index <= mid], windows)
    d_causal = 0.0
    for k in windows:
        a, b = S_full[k].loc[grid[grid <= mid], names], again[k].loc[grid[grid <= mid], names]
        both = a.notna() & b.notna()
        d_causal = max(d_causal, float((a - b).abs().where(both).max().max() or 0.0), float((a.isna() != b.isna()).sum().sum()))
    # validity (2): the label at the one-day reference before funding is the harness's unit converted from the log
    actual_from_log = (np.exp(bt.labels(M, refs[0], bt.LATENCY).loc[grid, names].to_numpy() / 1e4) - 1.0) * 1e4
    both = ~np.isnan(G[refs[0]]) & ~np.isnan(actual_from_log)
    d_label = float(np.abs(G[refs[0]] - actual_from_log)[both].max()) if both.any() else np.nan
    # validity (4): funding present — events inside the first week's window (the cumulative rate moves) — on the labelled cells of a
    # name, else the name is dropped from the cells and listed (a name without events has a zero `fundval`, which is finite: the event count is the check)
    fcum = pd.DataFrame(C.fundcum, index=idx, columns=M.columns)
    events = ((fcum.shift(-(bt.LATENCY + first_week)) - fcum.shift(-bt.LATENCY)).loc[grid, names].to_numpy() != 0.0)
    labelled = ~np.isnan(G[first_week])
    fund_cover = {c: float(events[:, j][labelled[:, j]].mean()) if labelled[:, j].any() else 0.0 for j, c in enumerate(names)}
    dropped = [c for c, x in fund_cover.items() if x < MOM_FUND_COVER]
    if dropped:
        jd = np.array([c in dropped for c in names])
        cell = cell & ~jd[None, :]
        G = {h: np.where(cell, g, np.nan) for h, g in G.items()}
        Y = {h: np.where(cell, y, np.nan) for h, y in Y.items()}
        S = {k: x.where(pd.DataFrame(cell, index=grid, columns=names)) for k, x in S.items()}
    # validity (5): the blocks of the scored months
    in_scope = mem[(mem["block"] >= grid[0].floor("D") - pd.Timedelta(days=30)) & (mem["block"] < grid[-1])]
    per_block = in_scope.groupby("block").size()
    member_names = sorted(set(in_scope["symbol"]))
    without_bars = [c for c in member_names if c not in names]
    n_members = len(member_names)
    v = {"registration": MOM_REG, "names": len(names), "members": n_members, "members_without_bars": without_bars, "blocks": int(len(per_block)),
         "members_per_block": {str(k.date()): int(x) for k, x in per_block.items()}, "folds": fold_names, "days": nd, "rows": n_rows, "whole_days": whole,
         "gap_days": gap, "shifts": len(ks), "shifts_expected": nd - 2 * gap + 1, "max_abs_d_causal": d_causal, "max_abs_d_label_ref": d_label,
         "funding_cover_by_name": {k: round(x, 4) for k, x in fund_cover.items()}, "names_dropped_under_funding_cover": dropped,
         "dropped_share": len(dropped) / max(n_members, 1), "cells": {str(h): int((~np.isnan(Y[h]) & ~np.isnan(S["mom_4w"].to_numpy())).sum()) for h in every},
         "signal_windows_bars": windows, "holds": holds, "refs": refs, "cost_bps": cost, "unit": bt.UNIT, "charged": bt.CHARGED}
    v["status"] = "PASS" if (whole and len(ks) == v["shifts_expected"] and len(ks) >= 20 and d_causal == 0.0 and np.isfinite(d_label) and d_label <= 1e-9
                             and v["dropped_share"] <= MOM_MAX_DROPPED and not without_bars) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {MOM_REG} — the slow cross-section: the members' trailing return held {holds} bars (`ft2 horizon --mom`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {len(names)} names, {n_members} members · {nd} days · holds {holds} bars "
            f"(references {refs}) · {len(ks)} shifts (gap {gap} days) · cost {cost:g} bps a leg · the registered sign POSITIVE (momentum)\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "horizon.md").write_text("\n".join(head + ["\n**The read is VOID: nothing of the family was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    fam = list(MOM_FAMILY)
    n_cells = int((~np.isnan(Y[refs[0]])).sum())
    print(f"horizon --mom: {len(S)} signals × holds {every} × {len(ks)} shifts on {n_cells:,} cells, {nd} days…", flush=True)
    d = pd.concat(Parallel(n_jobs=jobs, verbose=5)(delayed(_null)(k, x.to_numpy(), Y, ks) for k, x in S.items()), ignore_index=True)
    real, null = d[d["shift"] == 0].set_index(["signal", "hold"])["m"], d[d["shift"] > 0]
    st = null.groupby(["signal", "hold"])["m"].agg(centre="mean", se="std")
    centre, se = st["centre"], st["se"]
    null = null.join(st, on=["signal", "hold"])
    null["u"] = (null["m"] - null["centre"]) / null["se"]
    famn = null[null["signal"].isin(fam) & null["hold"].isin(holds)]
    mx = famn.assign(a=famn["u"].abs()).groupby("shift")["a"].max()

    ct = ceiling.bar_cost(idx, names, 5.0, 2.0)[0].loc[grid].to_numpy()        # the cells' own taker round trip (the proxy for the members)
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
            per_fold = {f: float(np.nanmean(m_day[fold_of == f])) if (fold_of == f).any() else np.nan for f in fold_names}
            if h in holds:                                                     # the part earned after the first week
                after = float(np.nanmean(_tenths(s, Y[h] - Y[first_week])))
            elif h == first_week:
                after = float(np.nanmean(_tenths(s, Y[h] - Y[refs[0]])))       # the week after its first day (reference)
            else:
                after = np.nan
            _, se_hac, n_days = hac(m_day, day_lags(h))
            m_ic, se_ic, _ = hac(_ic_xs(x, Zh[h], day), day_lags(h))
            yc = np.where(np.isnan(s), np.nan, Y[h])
            with np.errstate(invalid="ignore", divide="ignore"):
                move = float(np.nanmean(np.abs(yc - np.nansum(yc, axis=1, keepdims=True) / (~np.isnan(yc)).sum(1, keepdims=True))))
            ok = ~(np.isnan(s) | np.isnan(Y[h]))
            n = ok.sum(1)
            kk = np.maximum(np.rint(n * TENTH).astype(int), 1)
            r = _ranks(s, ok)
            top, bottom = (r > (n - kk)[:, None]) & (r <= n[:, None]) & ok & (n >= MIN_CELLS)[:, None], (r <= kk[:, None]) & ok & (n >= MIN_CELLS)[:, None]
            ext = top | bottom
            rt_ext = float(np.nanmean(np.where(ext, ct, np.nan))) if ext.any() else np.nan
            with np.errstate(invalid="ignore", divide="ignore"):
                rel = yc - np.nansum(yc, axis=1, keepdims=True) / (~np.isnan(yc)).sum(1, keepdims=True)
            m_top, m_bottom = float(np.nanmean(np.where(top, rel, np.nan))), float(np.nanmean(np.where(bottom, rel, np.nan)))
            m_w = float(np.nanmean(_tenths(s, np.clip(Y[h], -MOM_WINSOR, MOM_WINSOR))))
            row = {"signal": k, "hold": h, "family": k in fam and h in holds, "cells": int(ok.sum()), "days": n_days, "m": m, "centre": c, "m_c": m - c, "se": e,
                   "u": (m - c) / e if e else np.nan, "se_hac": se_hac, "lo": m - c - 1.96 * e, "hi": m - c + 1.96 * e, "mde": MDE_K * e,
                   "p_single": (1 + int((own["u"].abs() >= abs((m - c) / e)).sum())) / (len(own) + 1), "p_family": (1 + int((mx >= abs((m - c) / e)).sum())) / (len(mx) + 1),
                   **{f"m_{f}": per_fold[f] for f in fold_names},
                   "folds_same_sign": bool(all(np.sign(per_fold[f]) == np.sign(m - c) for f in fold_names if np.isfinite(per_fold[f])) and any(np.isfinite(per_fold[f]) for f in fold_names)),
                   "m_after_first_week": after, "after_same_sign": bool(np.isfinite(after) and np.sign(after) == np.sign(m - c)), "funding_part": m - float(np.nanmean(_tenths(s, G[h]))),
                   "m_top_tenth": m_top, "m_bottom_tenth": m_bottom, "m_winsorised": m_w, "rt_extreme_tenths": rt_ext, "ic": m_ic, "ic_t": m_ic / se_ic if se_ic else np.nan,
                   "move": move, "ic_needed": cost / (Z_TOP * 1.2533 * move) if move else np.nan}
            rows.append({**row, "verdict": mom_verdict(row, cost) if row["family"] else "reference"})
            tenth.append(_by_tenth(s, Y[h]).reset_index().assign(signal=k, hold=h))
    tab, tenth = pd.DataFrame(rows), pd.concat(tenth, ignore_index=True)
    fam_tab, ref_tab = tab[tab["family"]], tab[~tab["family"]]
    clears = fam_tab[fam_tab["verdict"].str.startswith("CLEARS")]
    wide = lambda c: tenth.pivot(index=["signal", "hold"], columns="tenth", values=c).reindex(pd.MultiIndex.from_frame(tab[["signal", "hold"]])).reset_index()      # noqa: E731
    show = lambda df, k=2: df.round(k).to_markdown(index=False)                         # noqa: E731
    main = ["signal", "hold", "cells", "m", "centre", "m_c", "se", "u", "lo", "hi", "mde", "p_single", "p_family", "verdict"]
    more = ["signal", "hold", *(f"m_{f}" for f in fold_names), "folds_same_sign", "m_after_first_week", "after_same_sign", "funding_part", "m_top_tenth", "m_bottom_tenth",
            "m_winsorised", "rt_extreme_tenths", "se_hac", "ic", "ic_t", "move", "ic_needed"]
    md = head + [
        "\nWords: *m*: what one leg of a book earns before trading costs that buys the tenth of names with the highest trailing return and sells the tenth with the "
        "lowest, in bps of the position, funding paid; POSITIVE is the registered direction (momentum). *centre*: the same book on moves taken from other months; "
        "*m_c* = m − centre; *se*: its spread over those months; *u* = m_c / se; *p (family)*: the share of shifts in which the best of the four did at least as well. "
        "*m_after_first_week*: the part of m earned from the eighth day on. *m_top_tenth*, *m_bottom_tenth*: each side's label against the bar's peers (which side "
        "carries it). *m_winsorised*: M with every label clipped at ±3,000 bps. *rt_extreme_tenths*: the cells' own taker round trip on the tenths traded, against the fixed cost.\n",
        f"\n## The family — two signals × two holds: **{len(clears)} of {len(fam_tab)} clear** (m_c > {cost:g}, u ≥ {U_BAR:g}, family-wise p ≤ {P_BAR:g}, m of m_c's "
        f"sign in every fold and after the first week; the registered sign positive)"
        f"{': ' + ', '.join(f'{a} at {b} ({c})' for a, b, c in zip(clears['signal'], clears['hold'], clears['verdict'])) if len(clears) else ''}. Over the shifts the best "
        f"of the family reaches |u| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty.\n", show(fam_tab[main]), "\n",
        "\n### Described (decides nothing)\n", show(fam_tab[more], 4), "\n",
        "\n## Reference rows — the one-day and the one-week hold, and the week's move at every hold (outside the family, no verdict)\n", show(ref_tab[main]), "\n", show(ref_tab[more], 4), "\n",
        "\n## The label against the bar's peers, by the signal's tenth (1 = lowest, 10 = highest), bps\n", "\n### mean\n", show(wide("mean"), 1), "\n",
        "\n### median\n", show(wide("median"), 1), "\n"]
    (out / "horizon.md").write_text("\n".join(md))
    tab.to_csv(out / "signals.csv", index=False)
    tenth.to_csv(out / "tenths.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95))}, indent=1, default=str))
    print(f"{MOM_REG}: {len(clears)} of {len(fam_tab)} clear; wrote {out}/", flush=True)
    return "\n".join(md)
