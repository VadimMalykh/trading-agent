"""P8 (B3) — the US stock index as per-name information (PLAN §4 P8, §9 #7, registration R26 in §8).
`ft2 audit <run> --family index --twelve` → output/audit/<run>_index/audit.md (and output/audit/twelve_index/audit.md)

One number for the whole market has no cross-section, so the index reaches pair-vs-peers only through each name: does a
name's trailing SENSITIVITY to the Nasdaq 100, times what the index just did, say which way the name moves over the next
day against the other names?

index      US100 (`data/index_1m.parquet`, DATA.md `index_1m`). A minute bar stamped ts is known from ts + 1 min; the index's
           value at an instant s is the close of the last traded minute ≤ s − 1 min. The index is OPEN at s if that minute is
           within OPEN_WITHIN of s, CLOSED otherwise (the weekend, the daily break, holidays — and an hour missing inside a
           session, which 2023-05 → 07 has many of). Nothing is interpolated.
cells      (a) the scored cells of a `transferbook` run (`audit.frame`: R18's); (b) the twelve on the same hourly grid of
           F1+F2 (`cells_twelve`), the same label (`audit.frame`'s code).
features   `FEATURES`, per name, known strictly before t: beta (the 30-day slope of the name's hourly return on the index's,
           open hours), beta × the index's move over 1 h and 4 h (open at both ends), over 24 h (open at t; the start taken
           whatever its age), and on closed hours beta × the index's move over its last 240 traded minutes before the close.
statistic  R20's (`ceiling._ic_xs`): per bar the Spearman across the names present, averaged per day, the mean over days.
null       R22's (`horizon.shifts`): the labels move by a whole number of days, every admissible shift (gap = beta's window
           + the hold + 1 days), the SAME shift on both universes; each number against the centre and sd of its own shifts
           (R20 (D1)); per shift the largest |u| of the family of ten → the family-wise p.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import audit, folds, horizon, index
from . import backtest as bt
from .ceiling import MDE_K, MIN_PAIRS, Z_CLIP, Z_TOP, _ic_xs, day_lags, hac
from .forecast import _derive

OUT = audit.OUT
INDEX, REF_INDEX = "US100", "US500"
FEATURES = ["beta", "bx_1h", "bx_4h", "bx_24h", "bx_gap"]
BETA_DAYS, BETA_MIN_HOURS = 30, 200    # the sensitivity: hours ending ≤ t over the last 30 days with the index open at both ends; ≥ 200 of them
REF_BETA_DAYS = 90                      # a reference row
GAP_MINUTES = 240                       # bx_gap: the index's move over its last 240 traded minutes before the close in force
OPEN_WITHIN = pd.Timedelta("15min")     # the index is open at s if its last traded minute is within this of s
KNOWN_AFTER = pd.Timedelta("1min")      # a minute bar stamped ts is known from ts + 1 min
HOUR = pd.Timedelta("1h")
HOLD, PER_DAY = 288, horizon.PER_DAY
U_BAR, P_BAR, IC_CLOSED = 2.0, 0.05, audit.IC_CLOSED
TWELVE_RUN = "r14_ridgebook_1d_ho12"    # validity (b): the twelve's labels against this run's z (or its decisions' cells)


def gap_days(beta_days: int | None = None, hold: int = HOLD) -> int:
    """A day never receives the labels of a day nearer than this: beta's window + the hold + 1."""
    return (beta_days or BETA_DAYS) + int(np.ceil(hold / audit.D1)) + 1


# ---- the index at an instant ---------------------------------------------------------------------------------------------------
class Minutes:
    """One index's traded minutes, in row order; `at(s)` is what is known at the instants s."""

    def __init__(self, m: pd.DataFrame):
        m = m.sort_values("ts").reset_index(drop=True)
        self.ts = pd.DatetimeIndex(m["ts"])
        self.known = self.ts + KNOWN_AFTER
        self.lc = np.log(m["close"].to_numpy(dtype=float))
        g = np.full(len(m), np.nan)
        if len(m) > GAP_MINUTES:
            g[GAP_MINUTES:] = self.lc[GAP_MINUTES:] - self.lc[:-GAP_MINUTES]
        self.gap = g                                      # the move over the GAP_MINUTES traded minutes ending at this row

    def at(self, s: pd.DatetimeIndex) -> dict[str, np.ndarray]:
        """For each instant: the row of the minute in force (−1 if none), its log close, its age (s − stamp), open?"""
        i = self.known.searchsorted(s, side="right") - 1
        ok = i >= 0
        age = np.full(len(s), np.nan)
        age[ok] = np.asarray((s[ok] - self.ts[i[ok]]) / pd.Timedelta("1min"), dtype=float)
        lc = np.where(ok, self.lc[np.clip(i, 0, None)], np.nan)
        is_open = ok & (age <= OPEN_WITHIN / pd.Timedelta("1min"))
        return {"row": i, "lc": lc, "age_min": age, "open": is_open, "gap": np.where(ok, self.gap[np.clip(i, 0, None)], np.nan)}


def load_minutes(symbol: str, end: pd.Timestamp) -> Minutes:
    m = index.load()
    m = m[(m["symbol"].astype(str) == symbol) & (m["ts"] + KNOWN_AFTER <= end)]
    if not len(m):
        raise FileNotFoundError(f"index_1m: no {symbol} minute before {end}")
    return Minutes(m[["ts", "close"]])


def _beta(rc: np.ndarray, ri: np.ndarray, window: int, min_n: int) -> np.ndarray:
    """Rolling least-squares slope of each column of `rc` (hours × names) on `ri` (hours), over the last `window` rows,
    on rows where both are finite; NaN under `min_n` such rows."""
    ok = np.isfinite(rc) & np.isfinite(ri)[:, None]
    x = np.where(ok, ri[:, None], 0.0)
    y = np.where(ok, rc, 0.0)
    csum = lambda a: np.cumsum(np.vstack([np.zeros((1, a.shape[1])), a]), axis=0)      # noqa: E731
    roll = lambda a: (lambda c: c[window:] - c[:-window] if len(c) > window else c[:0])(csum(a))      # noqa: E731
    n, sx, sy, sxx, sxy = (roll(a) for a in (ok.astype(float), x, y, x * x, x * y))
    out = np.full(rc.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        b = (sxy - sx * sy / n) / (sxx - sx * sx / n)
    b[n < min_n] = np.nan
    out[window - 1:] = b
    return out


def features_index(hidx: pd.DatetimeIndex, cols: list[str], close_h: pd.DataFrame, end: pd.Timestamp, symbol: str = INDEX,
                   beta_days: int | None = None, minutes: Minutes | None = None) -> tuple[dict[str, pd.DataFrame], dict[str, np.ndarray]]:
    """`FEATURES` on the hourly grid `hidx` × `cols`; `close_h` the names' close on that grid (the bar closed at t, known at t).
    Returns the features and the index's own series on the grid (open?, age, m_1h, m_4h, m_24h, the move into the close)."""
    mi = minutes or load_minutes(symbol, end)
    now = mi.at(hidx)
    back = {h: mi.at(hidx - h * HOUR) for h in (1, 4, 24)}
    m = {h: (now["lc"] - back[h]["lc"]) * 1e4 for h in (1, 4, 24)}
    is_open = now["open"]
    m1 = np.where(is_open & back[1]["open"], m[1], np.nan)
    m4 = np.where(is_open & back[4]["open"], m[4], np.nan)
    m24 = np.where(is_open, m[24], np.nan)
    gap = np.where(~is_open & (now["row"] >= 0), now["gap"] * 1e4, np.nan)
    # the sensitivity: hourly log returns, the index's on hours open at both ends
    rc = (np.log(close_h) - np.log(close_h.shift(1))).to_numpy() * 1e4
    ri = np.where(is_open & back[1]["open"], m[1], np.nan)
    beta = _beta(rc, ri, (beta_days or BETA_DAYS) * 24, BETA_MIN_HOURS)
    F = {"beta": beta, "bx_1h": beta * m1[:, None], "bx_4h": beta * m4[:, None], "bx_24h": beta * m24[:, None], "bx_gap": beta * gap[:, None]}
    F = {k: pd.DataFrame(v, index=hidx, columns=cols).replace([np.inf, -np.inf], np.nan) for k, v in F.items()}
    own = {"open": is_open, "age_min": now["age_min"], "m_1h": m1, "m_4h": m4, "m_24h": m24, "m_24h_any": m[24], "gap": gap}
    return F, own


# ---- the twelve's cells ----------------------------------------------------------------------------------------------------------
def cells_twelve(pairs: list[str], fold_names=folds.EXPLORATION, hold: int = HOLD, latency: int = bt.LATENCY, run: str | None = "") -> dict:
    """The twelve on the hourly grid of the scored folds, the label as `audit.frame` builds it, and the validity of that
    against `run`'s saved forecast (its z on the cells it scored) or, if the run kept no forecast, its decisions' cells."""
    run = TWELVE_RUN if run == "" else run
    fold_names = folds.order(fold_names)
    end = folds.bounds(fold_names[-1])[1]
    M = bt.market(pairs, end)
    names = list(M.columns)
    t5 = pd.Series(M.index, index=M.index)
    scored = np.zeros(len(M.index), dtype=bool)
    for f in fold_names:
        scored |= folds.mask(t5, f).to_numpy()
    grid = M.index[scored & (M.index.minute == 0) & (M.index.second == 0)]
    idx = M.index[M.index >= grid[0] - audit.WARMUP]
    sig = _derive(M.close.loc[idx, names])["sig"]["1w"]
    sig_h = sig * np.sqrt(hold)
    z = (bt.labels(M, hold, latency).loc[idx, names] / sig_h.where(sig_h > 0)).clip(-Z_CLIP, Z_CLIP)
    zg = z.loc[grid]
    cell = zg.notna()
    cell = cell.where(cell.sum(axis=1) >= MIN_PAIRS, False)
    v = {"status": "PASS", "cells": int(cell.to_numpy().sum()), "names": len(names), "hours_under_min_pairs": int((zg.notna().sum(axis=1) < MIN_PAIRS).sum()), "run": run}
    run_dir = bt.OUT / run if run else None
    if run_dir is not None and (run_dir / "forecast.parquet").exists():
        o = pd.read_parquet(run_dir / "forecast.parquet")
        o = o[(o["group"] == 0) & o["symbol"].isin(names)]
        y = bt.labels(M, hold, latency)
        zr = np.clip(y.to_numpy()[M.index.get_indexer(o["t"]), M.columns.get_indexer(o["symbol"])] / o["sigma_h"].to_numpy(), -Z_CLIP, Z_CLIP)
        zi = z.to_numpy()[idx.get_indexer(o["t"]), pd.Index(names).get_indexer(o["symbol"])]
        has = np.isfinite(zr)                                                   # the run's last hours have no label either (`screen.cells` drops them)
        dz = np.abs(zi - zr)[has]
        ok = np.isfinite(dz)
        v.update({"checked": "forecast", "run_cells": int(has.sum()), "max_abs_dz": float(np.nanmax(dz)) if ok.any() else np.nan, "run_cells_without_label": int((~ok).sum()),
                  "run_cells_off_grid": int((~pd.DatetimeIndex(o["t"]).isin(grid)).sum())})
        v["status"] = "PASS" if ok.all() and v["max_abs_dz"] <= audit.Z_TOL and v["run_cells_off_grid"] == 0 else "FAIL"
    elif run_dir is not None and (run_dir / "decisions.parquet").exists():
        d = pd.read_parquet(run_dir / "decisions.parquet", columns=["t", "symbol"])
        ti, si = grid.get_indexer(d["t"]), pd.Index(names).get_indexer(d["symbol"])
        inside = (ti >= 0) & (si >= 0)
        has = np.zeros(len(d), dtype=bool)
        has[inside] = cell.to_numpy()[ti[inside], si[inside]]
        reach = M.index[-1] - audit.BAR * (hold + latency)                # the last t whose label fits before the market's cut (`screen.cells` drops the rest too)
        beyond = np.asarray(pd.DatetimeIndex(d["t"]) > reach)
        v.update({"checked": "decisions", "run_cells": int(len(d)), "run_cells_off_grid": int((ti < 0).sum()), "run_cells_beyond_label": int(beyond.sum()),
                  "run_cells_without_label": int((~has & ~beyond).sum()),
                  "note": "the run kept no forecast.parquet: its decisions' cells are checked to be cells here with a label, except those decided after the last "
                          "bar a label can reach before the fold's end (counted as beyond_label)"})
        v["status"] = "PASS" if (has | beyond).all() else "FAIL"
    else:
        v.update({"checked": "none", "note": f"no run `{run}` to check against"})
        v["status"] = "FAIL" if run else "PASS"
    return {"M": M, "names": names, "idx": idx, "sig": sig, "z": z, "grid": grid, "cell": cell, "validity": v, "end": end, "fold_names": fold_names, "hold": hold,
            "latency": latency, "run_dir": run_dir}


# ---- the read ------------------------------------------------------------------------------------------------------------------------
def _ic_shifts(name: str, F: pd.DataFrame, Z: np.ndarray, ks: np.ndarray, day: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    """One feature on the real labels (shift 0) and on every shift; the daily IC series of shift 0."""
    rows, real = [], None
    for k in (0, *ks):
        src = horizon.shifted(len(Z), int(k)) if k else np.arange(len(Z))
        ic = _ic_xs(F, pd.DataFrame(Z[src], index=F.index, columns=F.columns), day)
        rows.append({"feature": name, "shift": int(k), "ic": float(np.nanmean(ic)), "days": int(np.isfinite(ic).sum())})
        real = ic if k == 0 else real
    return pd.DataFrame(rows), real


def _ic_on(F: pd.DataFrame, Z: np.ndarray, day: np.ndarray, mask: np.ndarray | None = None, hold: int = HOLD) -> tuple[float, float]:
    """IC and HAC t of a feature on the cells where `mask` (per bar) holds."""
    x = F if mask is None else F.where(pd.Series(mask, index=F.index), axis=0)
    m, se, _ = hac(_ic_xs(x, pd.DataFrame(Z, index=F.index, columns=F.columns), day), day_lags(hold))
    return m, (m / se if se else np.nan)


def verdict(r: dict) -> str:
    if abs(r["u"]) >= U_BAR and r["p_family"] <= P_BAR and r["ic_F_same_sign"]:
        return "CLEARS"
    return "CLOSED" if abs(r["ic_c"]) + 1.96 * r["se"] < IC_CLOSED else "NOT DETECTABLE"


def _universe(tag: str, A: dict, mi: Minutes, ref_mi: Minutes | None) -> dict:
    """Everything one universe contributes: its features on its grid, its labels, the index's own series, the reference features."""
    M, names, grid, cell, end = A["M"], A["names"], A["grid"], A["cell"], A["end"]
    hidx = pd.date_range(grid[0] - pd.Timedelta(days=BETA_DAYS + 1), grid[-1], freq="1h")
    close_h = M.close.reindex(hidx)[names]
    F, own = features_index(hidx, names, close_h, end, minutes=mi)
    R = {}
    if ref_mi is not None:
        Fr, _ = features_index(hidx, names, close_h, end, symbol=REF_INDEX, minutes=ref_mi)
        R.update({f"{k}_{REF_INDEX}": v for k, v in Fr.items()})
    Fb, _ = features_index(hidx, names, close_h, end, beta_days=REF_BETA_DAYS, minutes=mi)
    R[f"beta_{REF_BETA_DAYS}d"] = Fb["beta"]
    at = hidx.get_indexer(grid)
    cut = lambda d: {k: v.iloc[at].where(cell) for k, v in d.items()}     # noqa: E731
    return {"tag": tag, "F": cut(F), "R": cut(R), "own": {k: np.asarray(v)[at] for k, v in own.items()}, "Z": A["z"].loc[grid].to_numpy(), "grid": grid, "cell": cell,
            "names": names, "A": A}


def run(run: str, pairs: list[str] | None = None, twelve: bool = True, members: str | None = None, jobs: int = 4, name: str | None = None) -> str:
    from joblib import Parallel, delayed
    A = audit.frame(run, members)
    fold_names, end, grid, hold = A["fold_names"], A["end"], A["grid"], A["hold"]
    gap = gap_days(hold=hold)
    mi, ref_mi = load_minutes(INDEX, end), None
    try:
        ref_mi = load_minutes(REF_INDEX, end)
    except FileNotFoundError:
        pass
    U = [_universe("outside", A, mi, ref_mi)]
    if twelve:
        B = cells_twelve(pairs or [], fold_names, A["hold"], A["latency"])
        if not B["grid"].equals(grid):
            raise SystemExit("the twelve's grid is not the run's: the shifts could not be the same")
        U.append(_universe("twelve", B, mi, ref_mi))
    nd = len(grid) // PER_DAY
    day = audit._day(grid)
    whole = bool(len(grid) == nd * PER_DAY and (np.bincount(day)[np.bincount(day) > 0] == PER_DAY).all())
    ks = horizon.shifts(nd, gap)
    v = {u["tag"]: u["A"]["validity"] for u in U}
    v["whole_days"], v["days"], v["shifts"] = whole, nd, len(ks)
    v["status"] = "PASS" if all(x["status"] == "PASS" for x in (v[u["tag"]] for u in U)) and whole and len(ks) == nd - 2 * gap + 1 else "FAIL"

    jobs_ = [(u["tag"], k, u["F"][k], u["Z"]) for u in U for k in FEATURES]
    print(f"audit --family index: {len(jobs_)} feature×universe × {len(ks)} shifts on {nd} days…", flush=True)
    res = Parallel(n_jobs=jobs, verbose=5)(delayed(_ic_shifts)(f"{t}:{k}", F, Z, ks, day) for t, k, F, Z in jobs_)
    d = pd.concat([r for r, _ in res], ignore_index=True)
    d[["universe", "feature"]] = d["feature"].str.split(":", expand=True)
    real = d[d["shift"] == 0].set_index(["universe", "feature"])["ic"]
    null = d[d["shift"] > 0]
    st = null.groupby(["universe", "feature"])["ic"].agg(centre="mean", se="std")
    null = null.join(st, on=["universe", "feature"])
    null["u"] = (null["ic"] - null["centre"]) / null["se"]
    mx = null.assign(a=null["u"].abs()).groupby("shift")["a"].max()

    dates = pd.date_range(grid[0].floor("D"), periods=int(day.max()) + 1, freq="D")      # the daily IC series' calendar (a gap between folds is a NaN day)
    month = dates.tz_localize(None).to_period("M")
    fold_of = pd.Series("", index=dates)
    for f in fold_names:
        fold_of[folds.mask(pd.Series(dates, index=dates), f, embargoed=False).to_numpy()] = f
    rows, cov_rows, refs = [], [], []
    for u, ((t, k, F, Z), (_, ic_daily)) in zip([u for u in U for _ in FEATURES], zip(jobs_, res)):
        n_cells = int(u["cell"].to_numpy().sum())
        c, e = float(st.loc[(t, k), "centre"]), float(st.loc[(t, k), "se"])
        ic = float(real[(t, k)])
        own = null[(null["universe"] == t) & (null["feature"] == k)]
        per_fold = {f: float(np.nanmean(ic_daily[(fold_of == f).to_numpy()])) for f in fold_names}
        mm = pd.Series(ic_daily).groupby(np.asarray(month)).mean().dropna()
        m_hac, t_hac = _ic_on(F, Z, day, hold=hold)
        has = F.notna().to_numpy()
        row = {"universe": t, "feature": k, "coverage": float(has.sum() / n_cells), "ic": ic, "centre": c, "ic_c": ic - c, "se": e, "u": (ic - c) / e, "t_hac": t_hac,
               "days": int(np.isfinite(ic_daily).sum()), **{f"ic_{f}": per_fold[f] for f in fold_names}, "ic_F_same_sign": bool(len({np.sign(per_fold[f]) for f in fold_names}) == 1),
               "months_same_sign": float((np.sign(mm) == np.sign(ic - c)).mean()), "mde": MDE_K * e, "upper": abs(ic - c) + 1.96 * e,
               "p_single": (1 + int((own["u"].abs() >= abs((ic - c) / e)).sum())) / (len(own) + 1), "p_family": (1 + int((mx >= abs((ic - c) / e)).sum())) / (len(mx) + 1)}
        rows.append({**row, "verdict": verdict(row)})
        cov = pd.Series(has.sum(axis=1), index=grid).groupby(np.asarray(pd.DatetimeIndex(grid).tz_localize(None).to_period("M"))).sum() / \
            pd.Series(u["cell"].to_numpy().sum(axis=1), index=grid).groupby(np.asarray(pd.DatetimeIndex(grid).tz_localize(None).to_period("M"))).sum()
        cov_rows.append(cov.rename(f"{t}:{k}"))
    tab = pd.DataFrame(rows)
    coverage = pd.concat(cov_rows, axis=1)

    # described: the splits, the reference indices and window, the runs' own forecasts, what a signal needs to pay for the trade
    for u in U:
        t, F, Z, own = u["tag"], u["F"], u["Z"], u["own"]
        is_open, m24 = own["open"], own["m_24h_any"]
        for k in ("beta", "bx_24h"):
            for lab, mask in (("open hours", is_open), ("closed hours", ~is_open)):
                m_, t_ = _ic_on(F[k], Z, day, mask, hold)
                refs.append({"universe": t, "row": f"{k} on {lab}", "ic": m_, "t_hac": t_, "cells": int(F[k].where(pd.Series(mask, index=F[k].index), axis=0).notna().to_numpy().sum())})
        for lab, mask in (("after an index rise (m_24h > 0)", m24 > 0), ("after an index fall (m_24h < 0)", m24 < 0)):
            m_, t_ = _ic_on(F["beta"], Z, day, mask, hold)
            refs.append({"universe": t, "row": f"beta {lab}", "ic": m_, "t_hac": t_, "cells": int(F["beta"].where(pd.Series(mask, index=grid), axis=0).notna().to_numpy().sum())})
        for k, x in u["R"].items():
            m_, t_ = _ic_on(x, Z, day, hold=hold)
            refs.append({"universe": t, "row": k, "ic": m_, "t_hac": t_, "cells": int(x.notna().to_numpy().sum())})
        A_ = u["A"]
        if t == "outside":
            zh = A_["o"].pivot(index="t", columns="symbol", values="zhat").reindex(index=grid, columns=u["names"])
            m_, t_ = _ic_on(zh, Z, day, hold=hold)
            refs.append({"universe": t, "row": "the run's forecast (R18's candle ridge)", "ic": m_, "t_hac": t_, "cells": int(zh.notna().to_numpy().sum())})
        elif A_["run_dir"] is not None and (A_["run_dir"] / "forecast.parquet").exists():
            o = pd.read_parquet(A_["run_dir"] / "forecast.parquet")
            o = o[o["group"] == 0]
            zh = o.assign(zhat=o["f_bps"] / o["sigma_h"]).pivot(index="t", columns="symbol", values="zhat").reindex(index=grid, columns=u["names"])
            m_, t_ = _ic_on(zh, Z, day, hold=hold)
            refs.append({"universe": t, "row": "R14's held-out forecast", "ic": m_, "t_hac": t_, "cells": int(zh.notna().to_numpy().sum())})
        M_, cell = A_["M"], u["cell"]
        yb = bt.labels(M_, hold, A_["latency"]).loc[grid, u["names"]].where(cell)
        move = float(yb.sub(yb.mean(axis=1), axis=0).abs().stack().mean())
        fp = A_["run_dir"] / "fills_taker.parquet" if A_["run_dir"] is not None else None
        fills = pd.read_parquet(fp) if fp is not None and fp.exists() else None
        cost = float((fills["fee_bps"] + fills["other_cost_bps"]).mean()) if fills is not None and len(fills) else np.nan
        v[t].update({"move_bps": move, "cost_bps": cost, "ic_needed": cost / (Z_TOP * 1.2533 * move)})
    ref_tab = pd.DataFrame(refs)
    hw = pd.DataFrame({"age_min": U[0]["own"]["age_min"], "open": U[0]["own"]["open"]}, index=grid)
    age = hw.groupby([grid.dayofweek, grid.hour]).agg(age_min=("age_min", "mean"), open=("open", "mean"))
    age.index.names = ["weekday", "hour"]

    clears = tab[tab["verdict"] == "CLEARS"]
    sizes = " · ".join(f"{u['tag']}: {len(u['names'])} names, {int(u['cell'].to_numpy().sum()):,} cells" for u in U)
    show = lambda df, k=4: df.round(k).to_markdown(index=False)                         # noqa: E731
    main = ["universe", "feature", "coverage", "ic", "centre", "ic_c", "se", "u", "t_hac", "p_single", "p_family", "mde", "upper", "verdict"]
    more = ["universe", "feature", "days", *(f"ic_{f}" for f in fold_names), "ic_F_same_sign", "months_same_sign"]
    md = [f"# The US stock index as per-name information (R26) — the cells of `{run}`{' and the twelve' if twelve else ''} (`ft2 audit --family index`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · index {INDEX}, {len(mi.ts):,} traded minutes before {end:%Y-%m-%d} · "
          f"{sizes} · {nd} days · {len(ks)} shifts (gap {gap} days)\n",
          "\nWords: *beta* is how much a name moves with the Nasdaq 100, hour by hour, over the last 30 days. *bx_1h / 4h / 24h*: that sensitivity times what the index did over "
          "the last 1, 4 or 24 hours (read when the index is open); *bx_gap*: times what it did going into its close (read when it is closed). *IC* is the correlation, "
          "across the names present at one moment, between the feature and the move that followed; *centre* is the IC the same feature has when the moves are taken from "
          "other weeks, *ic_c* = IC − centre, *se* the spread over those weeks, *u* = ic_c / se (2 or more is the bar). *p (family)*: the share of shifts in which the BEST of "
          "the ten did at least as well. *MDE*: the smallest ic_c this sample could have shown. *coverage*: the share of cells the feature is read on.\n",
          "\n## Validity\n",
          f"\n**{v['status']}**: outside — {v['outside']['status']}, {v['outside']['cells']:,} cells of {v['outside']['names']} names, largest |Δ label| against the run's "
          f"{v['outside']['max_abs_dz']:.3g} (bar {audit.Z_TOL:g}), {v['outside']['cells_off_grid']} off the grid, {v['outside']['cells_without_label']} without a label"
          + (f"; the twelve — {v['twelve']['status']}, {v['twelve']['cells']:,} cells of {v['twelve']['names']} names, checked against `{v['twelve']['run']}`'s "
             f"{v['twelve'].get('checked')} ({v['twelve'].get('run_cells', 0):,} cells: {v['twelve'].get('run_cells_off_grid', 0)} off the grid, "
             f"{v['twelve'].get('run_cells_without_label', 0)} without a label here" + (f", largest |Δ z| {v['twelve']['max_abs_dz']:.3g}" if "max_abs_dz" in v["twelve"] else "") + ")"
             if twelve else "") + f"; whole days: {whole}; {len(ks)} shifts on {nd} days.\n",
          "\n## The family — five features × " + ("two universes" if twelve else "one universe") + "\n",
          f"\n**{len(clears)} of {len(tab)} clear the gate** (|u| ≥ {U_BAR:g}, family-wise p ≤ {P_BAR:g}, one sign in every fold)"
          f"{': ' + ', '.join(f'{a} {b}' for a, b in zip(clears['universe'], clears['feature'])) if len(clears) else ''}. Over the shifts the best of the family reaches "
          f"|u| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty.\n", show(tab[main]), "\n",
          "\n### Described (decides nothing)\n", show(tab[more]), "\n",
          "\n### Coverage by month (the share of a month's cells the feature is read on)\n", coverage.round(3).to_markdown(), "\n",
          "\n## Reference rows (described, no null, no verdict)\n", show(ref_tab), "\n",
          *(f"\n- {u['tag']}: a taker round trip costs {v[u['tag']]['cost_bps']:.1f} bps on the run's trades; the mean move against the other names is "
            f"{v[u['tag']]['move_bps']:.0f} bps; trading the top tenth of a signal breaks even at an IC of about {v[u['tag']]['ic_needed']:.3f} (P2 #7's formula).\n" for u in U),
          "\n### The index minute in force, by hour of the week (mean age in minutes; share of hours open)\n",
          age.unstack("hour")["age_min"].round(0).to_markdown(), "\n", age.unstack("hour")["open"].round(2).to_markdown(), "\n"]
    out = OUT / (name or f"{run}_index")
    out.mkdir(parents=True, exist_ok=True)
    text = "\n".join(md)
    (out / "audit.md").write_text(text)
    tab.to_csv(out / "features.csv", index=False)
    ref_tab.to_csv(out / "reference.csv", index=False)
    coverage.to_csv(out / "coverage_month.csv")
    age.to_csv(out / "age_hourweek.csv")
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95)), "gap_days": gap, "index": INDEX}, indent=1, default=str))
    if twelve:
        o2 = OUT / "twelve_index"
        o2.mkdir(parents=True, exist_ok=True)
        tw = tab[tab["universe"] == "twelve"]
        (o2 / "audit.md").write_text(f"# The twelve's rows of R26 (the full read, the family and the null: `{out}/audit.md`)\n\n" + show(tw[main]) + "\n\n" + show(tw[more]) + "\n\n"
                                     + show(ref_tab[ref_tab["universe"] == "twelve"]) + "\n")
        tw.to_csv(o2 / "features.csv", index=False)
    return text
