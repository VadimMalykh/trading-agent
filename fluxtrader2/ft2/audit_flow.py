"""R37 — the forced-flow signature (PLAN §8 R37): does an hour in which open interest LEFT while the price moved far and the takers
pushed with it predict a REVERSAL over the next 1 and 4 hours, per name, on R18's screener-member cells and on the twelve?

`ft2 audit r18_transferbook_1d --family flow --twelve` → output/audit/<run>_flow/

frame       R26's (`audit_index`): OUTSIDE = `audit.frame`'s cells (hourly bars of F1+F2, the block's members) as the membership mask;
            THE TWELVE = `audit_index.cells_twelve` on the same grid. Labels at HOLDS = 12 and 48 bars: z_h = the log move from the
            close one bar after t to the close h bars later over σ_1w·√h, clipped at ±5 (`horizon.run`'s Zh).
ingredients three numbers per name and bar, known strictly before t (a metrics row stamped ts is used from ts + 5 min and carried at
            most 3 bars — R20's rule; the candles are closed at t):
              move_1h   = the log return over the last 12 bars / (σ_1w·√12)            the hour's move in the name's own sigmas
              oi_chg_1h = log OI(t) − log OI(t − 12 bars)                              OI = `sum_open_interest` (contracts); < 0: positions left
              taker_1h  = mean over the last 12 rows of log(taker buy / taker sell)    > 0: the buyers took
family      rev_oi   = −move_1h × max(−oi_chg_1h, 0)                                   the move reversed, weighted by the OI that LEFT
            rev_flow = rev_oi × |taker_1h| × 1[sign(taker_1h) = sign(move_1h)]         … only when the takers pushed WITH the move
            × HOLDS × universes = 8 numbers. A POSITIVE IC is the hypothesis.
reference   rev_1h = −move_1h (the plain reversal, the known fact the family must beat), oi_chg_1h, taker_1h, rev_absoi = −move_1h ×
            |oi_chg_1h|, the run's forecast; and per family number the PAIRED Δ against rev_1h under the same shifts (u_Δ).
events      a FORCED HOUR: oi_chg_1h at or under the name's 5th percentile over its trailing 30 days (≥ 15 days of hours), |move_1h| ≥ 2,
            sign(taker_1h) = sign(move_1h). Their count and share, the mean |move_1h| on them, and the next-1h and next-4h ACTUAL
            return against the bar's peers (`horizon.labels`, funding on value) SIGNED by −sign(move_1h) — what fading them earns before
            trading costs — with the HAC se and the shift null's centre and u. Described; the thresholds are fixed, not searched.
statistic   R20's (`ceiling._ic_xs`), the HAC t beside. null: R26's — every admissible whole-day shift, gap = GAP days; centre, se, u =
            (IC − centre) / se; per shift the largest |u| of the eight → the family-wise p.
gate        CLEARS if |u| ≥ 2 AND p_family ≤ 0.05 AND one sign in F1 and F2 AND IC_c > 0 AND u_Δ ≥ 2 (ADDS to the plain reversal);
            "CLEARS AS THE PLAIN REVERSAL" without the last; "CLEARS WITH THE OPPOSITE SIGN" with IC_c < 0; CLOSED if |IC_c| + 1.96 se
            < 0.02; NOT DETECTABLE otherwise.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import audit, audit_index, data, folds, horizon
from . import backtest as bt
from .ceiling import BAR, MDE_K, Z_CLIP, Z_TOP, _ic_xs, day_lags, hac
from .forecast import _derive

OUT = audit.OUT
HOLDS = (12, 48)
H1 = 12
FAMILY = ["rev_oi", "rev_flow"]
PLAIN = "rev_1h"
REFS = [PLAIN, "oi_chg_1h", "taker_1h", "rev_absoi"]
GAP = 1 + 1 + 1                                   # days: the ingredients' window (an hour → a day) + the longest hold (4h → a day) + 1
EVENT_Q, EVENT_DAYS, EVENT_MOVE = 0.05, 30, 2.0   # a forced hour: the OI change at or under the trailing-30-day 5th percentile, |move| ≥ 2σ, the takers with the move
EVENT_MIN_HOURS = EVENT_DAYS * 24 // 2
U_BAR, P_BAR, IC_CLOSED = audit_index.U_BAR, audit_index.P_BAR, audit_index.IC_CLOSED
COVER_BAR = 0.95
COST = {"outside": 18.0, "twelve": 12.3}         # bps a taker round trip: R20 (D3) on the members' trades, P1 on the twelve
PER_DAY = horizon.PER_DAY
MIN_FADE = 1                                      # a bar's faded mean needs this many forced hours among its cells


# ---- the ingredients and the features ---------------------------------------------------------------------------------------------------
def ingredients(idx: pd.DatetimeIndex, names: list[str], close: pd.DataFrame, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """The three numbers on the 5m index `idx` (the bar closed at t), each known strictly before t."""
    notes = []
    lr = np.log(close)
    sig = _derive(close)["sig"]["1w"]
    move_1h = (lr.diff(H1) * 1e4) / (sig * np.sqrt(H1)).where(sig > 0)
    nan = lambda: pd.DataFrame(np.nan, index=idx, columns=names)       # noqa: E731
    oi_chg_1h, taker_1h = nan(), nan()
    try:
        m = data.load("metrics", columns=["symbol", "ts", "oi", "taker_ratio"], symbols=names)
        m = m[(m["ts"] < end) & (m["ts"] >= idx[0] - pd.Timedelta(days=1))]
        m["symbol"] = m["symbol"].astype(str)
        wide = lambda c: m.pivot(index="ts", columns="symbol", values=c).shift(freq=BAR).reindex(index=idx, columns=names).ffill(limit=3)      # noqa: E731
        pos = lambda x: np.log(x.where(x > 0))                             # noqa: E731
        oi_chg_1h = pos(wide("oi")).diff(H1)
        taker_1h = pos(wide("taker_ratio")).rolling(H1, min_periods=9).mean()
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("metrics absent: oi_chg_1h and taker_1h are NaN")
    I = {"move_1h": move_1h, "oi_chg_1h": oi_chg_1h, "taker_1h": taker_1h}
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in I.items()}, notes


def features_flow(I: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """(the family, the reference features) from the ingredients, on their index."""
    mv, oi, tk = I["move_1h"], I["oi_chg_1h"], I["taker_1h"]
    fall = (-oi).clip(lower=0.0)
    rev_oi = -mv * fall
    same = np.sign(tk) == np.sign(mv)
    rev_flow = rev_oi * tk.abs().where(same, 0.0)
    return {"rev_oi": rev_oi, "rev_flow": rev_flow}, {PLAIN: -mv, "oi_chg_1h": oi, "taker_1h": tk, "rev_absoi": -mv * oi.abs()}


def forced_hours(Ih: dict[str, pd.DataFrame], cell: pd.DataFrame) -> pd.DataFrame:
    """On the hourly grid: the forced-hour mask — the OI change at or under the name's trailing EVENT_DAYS 5th percentile (≥ EVENT_MIN_HOURS
    hours of it), |move_1h| ≥ EVENT_MOVE, the takers with the move — on the cells."""
    oi, mv, tk = Ih["oi_chg_1h"], Ih["move_1h"], Ih["taker_1h"]
    q = oi.rolling(EVENT_DAYS * PER_DAY, min_periods=EVENT_MIN_HOURS).quantile(EVENT_Q)
    return ((oi <= q) & (mv.abs() >= EVENT_MOVE) & (np.sign(tk) == np.sign(mv)) & cell).fillna(False)


# ---- the universes ----------------------------------------------------------------------------------------------------------------------
def _universe(tag: str, A: dict, holds=HOLDS) -> dict:
    """One universe's family, reference features, ingredients, labels at every hold (z and actual-against-peers) on its grid."""
    M, names, grid, cell, end, latency = A["M"], A["names"], A["grid"], A["cell"], A["end"], A["latency"]
    idx = M.index[M.index >= grid[0] - audit.WARMUP]
    close = M.close.loc[idx, names]
    I, notes = ingredients(idx, names, close, end)
    F, R = features_flow(I)
    at = idx.get_indexer(grid)
    cut = lambda d: {k: v.iloc[at].where(cell) for k, v in d.items()}      # noqa: E731
    sig = _derive(close)["sig"]["1w"]
    Z = {h: (bt.labels(M, h, latency).loc[idx, names] / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).iloc[at].where(cell).to_numpy() for h in holds}
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    Y = {}
    for h in holds:
        y = horizon.labels(M, C, h, latency)[1].loc[grid, names].where(cell)
        Y[h] = y.sub(y.mean(axis=1), axis=0).to_numpy()                   # against the bar's peers (the cells with a label)
    Ih = cut(I)
    cover = float(np.logical_and.reduce([v.notna().to_numpy() for v in Ih.values()]).sum() / max(int(cell.to_numpy().sum()), 1))
    return {"tag": tag, "F": cut(F), "R": cut(R), "I": Ih, "Z": Z, "Y": Y, "E": forced_hours(Ih, cell), "grid": grid, "cell": cell, "names": names, "A": A,
            "cover": cover, "notes": notes}


def _fade(E: np.ndarray, mv: np.ndarray, Y: np.ndarray, day: np.ndarray, ks: np.ndarray) -> dict:
    """The faded money on the forced hours: per bar the mean over its forced cells of −sign(move) × the actual return against the peers;
    per day; HAC over days; and the same under every shift of the labels (centre, se, u)."""
    s = np.where(E, -np.sign(mv), 0.0)
    n = E.sum(1).astype(float)
    def m_day(y):
        with np.errstate(invalid="ignore", divide="ignore"):
            bar = np.where(n >= MIN_FADE, np.nansum(np.where(E, s * y, 0.0), 1) / n, np.nan)
        return pd.Series(bar).groupby(day).mean().reindex(range(int(day.max()) + 1)).to_numpy()
    real = m_day(Y)
    m, se_h, nd = hac(real, 2)
    nulls = np.array([float(np.nanmean(m_day(Y[horizon.shifted(len(Y), int(k))]))) for k in ks])
    centre, se = float(np.nanmean(nulls)), float(np.nanstd(nulls, ddof=1))
    return {"m": float(np.nanmean(real)), "se_hac": se_h, "days": int(nd), "centre": centre, "se": se, "u": (float(np.nanmean(real)) - centre) / se if se else np.nan}


# ---- the verdict --------------------------------------------------------------------------------------------------------------------------
def verdict(r: dict) -> str:
    base = abs(r["u"]) >= U_BAR and r["p_family"] <= P_BAR and r["parts_same_sign"]
    if base and r["ic_c"] > 0:
        return "CLEARS" if r["u_delta"] >= U_BAR else "CLEARS AS THE PLAIN REVERSAL"
    if base and r["ic_c"] < 0:
        return "CLEARS WITH THE OPPOSITE SIGN"
    return "CLOSED" if abs(r["ic_c"]) + 1.96 * r["se"] < IC_CLOSED else "NOT DETECTABLE"


# ---- the read ------------------------------------------------------------------------------------------------------------------------------
def run(run: str, pairs: list[str] | None = None, twelve: bool = True, members: str | None = None, jobs: int = 4, name: str | None = None,
        holds=HOLDS) -> str:
    from joblib import Parallel, delayed
    holds = [int(h) for h in holds]
    A = audit.frame(run, members)
    fold_names, grid = A["fold_names"], A["grid"]
    U = [_universe("outside", A, holds)]
    if twelve:
        B = audit_index.cells_twelve(pairs or [], fold_names, A["hold"], A["latency"])
        if not B["grid"].equals(grid):
            raise SystemExit("the twelve's grid is not the run's: the shifts could not be the same")
        U.append(_universe("twelve", B, holds))
    nd = len(grid) // PER_DAY
    day = audit._day(grid)
    whole = bool(len(grid) == nd * PER_DAY and (np.bincount(day)[np.bincount(day) > 0] == PER_DAY).all())
    ks = horizon.shifts(nd, GAP)
    v = {u["tag"]: {**u["A"]["validity"], "ingredients_cover": u["cover"], "notes": u["notes"]} for u in U}
    v.update({"registration": "R37", "whole_days": whole, "days": nd, "shifts": len(ks), "shifts_expected": nd - 2 * GAP + 1, "gap_days": GAP, "holds": holds,
              "folds": list(fold_names), "run": run})
    v["status"] = "PASS" if (all(v[u["tag"]]["status"] == "PASS" and v[u["tag"]]["ingredients_cover"] >= COVER_BAR for u in U) and whole and len(ks) == nd - 2 * GAP + 1
                             and len(ks) >= 20) else "FAIL"
    out = OUT / (name or f"{run}_flow")
    out.mkdir(parents=True, exist_ok=True)
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    sizes = " · ".join(f"{u['tag']}: {len(u['names'])} names, {int(u['cell'].to_numpy().sum()):,} cells, the ingredients on {u['cover']:.1%}" for u in U)
    head = [f"# R37 — the forced-flow signature at 1h and 4h — the cells of `{run}`{' and the twelve' if twelve else ''} (`ft2 audit --family flow`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {sizes} · {nd} days · {len(ks)} shifts (gap {GAP} days)\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "audit.md").write_text("\n".join(head + ["\n**The read is VOID: nothing of the family was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    # the ICs under every shift: the family and the reference features, every hold, every universe
    jobs_ = [(u["tag"], k, h, X[k], u["Z"][h]) for u in U for X in (u["F"], u["R"]) for k in X for h in holds]
    print(f"audit --family flow: {len(jobs_)} feature×hold×universe × {len(ks)} shifts on {nd} days…", flush=True)
    res = Parallel(n_jobs=jobs, verbose=5)(delayed(audit_index._ic_shifts)(f"{t}:{k}:{h}", F, Z, ks, day) for t, k, h, F, Z in jobs_)
    d = pd.concat([r for r, _ in res], ignore_index=True)
    d[["universe", "feature", "hold"]] = d["feature"].str.split(":", expand=True)
    d["hold"] = d["hold"].astype(int)
    key = ["universe", "feature", "hold"]
    real = d[d["shift"] == 0].set_index(key)["ic"]
    null = d[d["shift"] > 0]
    st = null.groupby(key)["ic"].agg(centre="mean", se="std")
    null = null.join(st, on=key)
    null["u"] = (null["ic"] - null["centre"]) / null["se"]
    fam_null = null[null["feature"].isin(FAMILY)]
    mx = fam_null.assign(a=fam_null["u"].abs()).groupby("shift")["a"].max()
    # the paired difference against the plain reversal, per shift
    wide_ic = d.pivot_table(index="shift", columns=key, values="ic")
    dates = pd.date_range(grid[0].floor("D"), periods=int(day.max()) + 1, freq="D")
    month = dates.tz_localize(None).to_period("M")
    part = audit_index._parts(dates, fold_names, "index")
    parts = [p for p in dict.fromkeys(part) if p]
    rows = []
    for (t, k, h, F, Z), (_, ic_daily) in zip(jobs_, res):
        c, e = float(st.loc[(t, k, h), "centre"]), float(st.loc[(t, k, h), "se"])
        ic = float(real[(t, k, h)])
        own = null[(null["universe"] == t) & (null["feature"] == k) & (null["hold"] == h)]
        per_part = {p: float(np.nanmean(ic_daily[(part == p).to_numpy()])) for p in parts}
        mm = pd.Series(ic_daily).groupby(np.asarray(month)).mean().dropna()
        m_hac, se_hac, _ = hac(ic_daily, day_lags(h))
        dl = wide_ic[(t, k, h)] - wide_ic[(t, PLAIN, h)]
        d0, dn = float(dl.loc[0]), dl.loc[dl.index > 0]
        u_delta = (d0 - float(dn.mean())) / float(dn.std()) if k != PLAIN and dn.std() else np.nan
        has = F.notna().to_numpy()
        row = {"universe": t, "feature": k, "hold": h, "family": k in FAMILY, "coverage": float(has.sum() / max(int(U[[u["tag"] for u in U].index(t)]["cell"].to_numpy().sum()), 1)),
               "nonzero": float((F.fillna(0.0) != 0).to_numpy().sum() / max(has.sum(), 1)), "ic": ic, "centre": c, "ic_c": ic - c, "se": e, "u": (ic - c) / e if e else np.nan,
               "t_hac": m_hac / se_hac if se_hac else np.nan, "days": int(np.isfinite(ic_daily).sum()), **{f"ic_{p}": per_part[p] for p in parts},
               "parts_same_sign": bool(len({np.sign(per_part[p]) for p in parts}) == 1), "months_same_sign": float((np.sign(mm) == np.sign(ic - c)).mean()) if len(mm) else np.nan,
               "mde": MDE_K * e, "upper": abs(ic - c) + 1.96 * e, "p_single": (1 + int((own["u"].abs() >= abs((ic - c) / e)).sum())) / (len(own) + 1),
               "p_family": (1 + int((mx >= abs((ic - c) / e)).sum())) / (len(mx) + 1), "delta_vs_plain": d0 - float(dn.mean()) if k != PLAIN else np.nan, "u_delta": u_delta}
        rows.append({**row, "verdict": verdict(row) if row["family"] else "reference"})
    tab = pd.DataFrame(rows)
    fam_tab, ref_tab = tab[tab["family"]], tab[~tab["family"]]

    # the forced hours and their faded money, and the runs' forecasts as a reference
    ev_rows, ref_rows = [], []
    for u in U:
        t, E = u["tag"], u["E"].to_numpy()
        mv = u["I"]["move_1h"].to_numpy()
        n_ev, n_cells = int(E.sum()), int(u["cell"].to_numpy().sum())
        per_month = pd.Series(E.sum(1), index=grid).groupby(np.asarray(pd.DatetimeIndex(grid).tz_localize(None).to_period("M").astype(str))).sum()
        for h in holds:
            f = _fade(E, mv, u["Y"][h], day, ks)
            ev_rows.append({"universe": t, "hold": h, "forced_hours": n_ev, "share_of_cells": n_ev / max(n_cells, 1), "hours_with_one": int((E.sum(1) >= 1).sum()),
                            "mean_abs_move": float(np.nanmean(np.abs(mv[E]))) if n_ev else np.nan, "faded_bps": f["m"], "se_hac": f["se_hac"], "days": f["days"],
                            "centre": f["centre"], "se_shift": f["se"], "u": f["u"], "cost_round_trip": COST.get(t, np.nan), "per_month": json.dumps(per_month.to_dict())})
        A_ = u["A"]
        if t == "outside":
            zh = A_["o"].pivot(index="t", columns="symbol", values="zhat").reindex(index=grid, columns=u["names"])
            for h in holds:
                m_, t_ = audit_index._ic_on(zh, u["Z"][h], day, hold=h)
                ref_rows.append({"universe": t, "row": "the run's forecast (R18's candle ridge)", "hold": h, "ic": m_, "t_hac": t_})
    ev = pd.DataFrame(ev_rows)
    ref2 = pd.DataFrame(ref_rows)

    clears = fam_tab[fam_tab["verdict"] == "CLEARS"]
    show = lambda df, k=4: df.round(k).to_markdown(index=False)                         # noqa: E731
    main = ["universe", "feature", "hold", "coverage", "nonzero", "ic", "centre", "ic_c", "se", "u", "t_hac", "p_single", "p_family", "mde", "upper", "delta_vs_plain", "u_delta", "verdict"]
    more = ["universe", "feature", "hold", "days", *(f"ic_{p}" for p in parts), "parts_same_sign", "months_same_sign"]
    md = head + [
        "\nWords: *move_1h* is the hour's move in the name's own sigmas; *oi_chg_1h* the hour's change of open interest (log); *taker_1h* the hour's taker buy/sell balance (log). "
        "*rev_oi* reverses the hour's move weighted by the open interest that LEFT; *rev_flow* keeps only the hours in which the takers pushed with the move. *IC* is the "
        "correlation, across the names present at one moment, between the feature and the move that followed; *centre* the IC when the moves come from other days, *ic_c* = IC − "
        "centre, *se* its spread over those days, *u* = ic_c / se (2 or more is the bar); *p (family)*: the share of shifts in which the BEST of the eight did at least as well; "
        "*delta_vs_plain*, *u_delta*: the feature's ic_c minus the plain reversal's on the same cells and shifts, and that difference over its own spread — whether the footprint "
        "ADDS to a known, sub-cost fact. *nonzero*: the share of read cells on which the feature is not exactly zero (rev_oi is zero when open interest grew).\n",
        f"\n## The family — eight numbers: **{len(clears)} of {len(fam_tab)} clear the gate** (|u| ≥ {U_BAR:g}, family-wise p ≤ {P_BAR:g}, one sign in {', '.join(parts)}, "
        f"ic_c > 0, u_Δ ≥ {U_BAR:g} against the plain reversal){': ' + ', '.join(f'{a} {b} at {c}' for a, b, c in zip(clears['universe'], clears['feature'], clears['hold'])) if len(clears) else ''}. "
        f"Over the shifts the best of the eight reaches |u| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty.\n", show(fam_tab[main]), "\n",
        "\n### Described (decides nothing)\n", show(fam_tab[more]), "\n",
        "\n## Reference rows — the plain reversal and the parts alone (no verdict)\n", show(ref_tab[main[:-3] + ["delta_vs_plain", "u_delta"]]), "\n", show(ref_tab[more]), "\n",
        show(ref2) if len(ref2) else "", "\n",
        "\n## The forced hours and their faded money (described, actual returns against the peers, funding inside, before trading costs)\n",
        f"\nA forced hour: the OI change at or under the name's trailing-{EVENT_DAYS}-day {EVENT_Q:.0%} quantile, |move| ≥ {EVENT_MOVE:g}σ, the takers with the move. "
        "*faded_bps*: the mean over such hours of −sign(move) × the next move against the peers; *centre*, *se_shift*, *u*: the same under the shifts of the labels.\n",
        show(ev.drop(columns=["per_month"])), "\n", *(f"\n- {r['universe']} forced hours by month: {r['per_month']}\n" for _, r in ev.drop_duplicates("universe").iterrows()),
        *(f"\n- {u['tag']}: a taker round trip costs about {COST.get(u['tag'], float('nan')):.1f} bps on these names (R20 / P1); the family's IC bar for money is far above the "
          f"0.02 bar (P2 #7), so a clear here is a hypothesis about the mechanism.\n" for u in U)]
    text = "\n".join(md)
    (out / "audit.md").write_text(text)
    tab.to_csv(out / "features.csv", index=False)
    ev.to_csv(out / "events.csv", index=False)
    ref2.to_csv(out / "reference.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95))}, indent=1, default=str))
    print(f"R37: {len(clears)} of {len(fam_tab)} clear; wrote {out}/", flush=True)
    return text
