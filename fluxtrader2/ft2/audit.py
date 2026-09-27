"""P8 — the ceiling audit on the point-in-time universe (PLAN §4 P8, registration R20 in §8).
`ft2 audit <run>` → output/audit/<run>/audit.md

Five registrations looked for the candle ridge's signal on names outside the twelve and found none. This asks the question
that comes before any model (Principle 2): does the information the model does NOT use — funding, the perpetual's premium
over spot, open interest, the long/short ratios, the taker flow — say which way a name moves over the next day against the
other members of the universe?

cells      the scored cells of a `transferbook` run (`screen.cells`): hourly decision bars, the block's members. The labels
           are rebuilt here from the candles and must equal the run's on every cell (`validity`), or the read is void.
features   `FEATURES`, each on the 5m bar index from data known strictly before the bar's decision time t: a metrics row
           stamped ts is used from ts + 5 min, a premium bar from its close, a funding rate from the bar after its funding
           time. Every source is cut at the end of the last fold read.
statistic  `ceiling._ic_xs`: per bar the Spearman correlation, across the members present, of the feature with the label;
           averaged per day; the mean over days with its HAC t.
null       `ceiling._shuffle_days` on the hourly grid: the labels' whole days trade places, whole rows move. A name keeps
           its own labels, so a link between a name's lasting level of a feature and its drift survives in the null and
           earns no credit. Per draw the largest |t| of the family → the family-wise p.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import data, folds, screen, universe
from .ceiling import BAR, MDE_K, Z_CLIP, Z_TOP, _ic_xs, _shuffle_days, day_lags, hac
from .forecast import _derive

OUT = Path("output/audit")
FEATURES = ["funding_last", "funding_7d", "premium_1h", "premium_1d", "oi_chg_1d", "oi_chg_1w", "oi_turn", "global_ls", "global_ls_chg_1d", "top_ls",
            "top_vs_global", "taker_1d"]
DRAWS = 200
Z_TOL = 1e-6                       # the audit's labels against the run's
GRID = pd.Timedelta("1h")          # the run's decision bars (grid 12)
H1, D1, W1 = 12, 288, 2016         # feature windows, in 5m bars
WARMUP = pd.Timedelta(days=9)      # bars loaded before the first cell: the longest window (1w) and its minimum
T_BAR, P_BAR, IC_CLOSED = 2.0, 0.05, 0.02


def features(idx: pd.DatetimeIndex, cols: list[str], dv: pd.DataFrame, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """`FEATURES` on the 5m decision times `idx` × `cols`; `dv` is the bars' dollar volume on the same index. An absent
    source leaves its features NaN and a note."""
    empty = lambda: pd.DataFrame(np.nan, index=idx, columns=cols)                       # noqa: E731
    F, notes = {k: empty() for k in FEATURES}, []
    pos = lambda x: np.log(x.where(x > 0))                                              # noqa: E731
    a = idx[0] - pd.Timedelta(days=1)
    try:                                                     # funding: per 8 h, bps; usable from the bar after the funding time
        fu = data.load("funding_archive", symbols=cols)
        fu = fu[(fu["ts"] < end) & (fu["ts"] >= a - pd.Timedelta(days=8))]
        fw = (fu.assign(symbol=fu["symbol"].astype(str), r=fu["rate"] * 8.0 / fu["interval_h"] * 1e4).pivot(index="ts", columns="symbol", values="r").reindex(columns=cols))
        on = lambda x: x.reindex(idx.union(x.index)).ffill().reindex(idx).shift(1)      # noqa: E731
        F["funding_last"], F["funding_7d"] = on(fw), on(fw.rolling("7D", min_periods=1).mean())
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("funding_archive absent: funding_* skipped")
    try:                                                     # premium index: the bar that closed at t
        pr = data.load("premium", symbols=cols)
        pr = pr[(pr["open_time"] + BAR <= end) & (pr["open_time"] >= a)]
        pw = pr.assign(symbol=pr["symbol"].astype(str), t=pr["open_time"] + BAR, p=pr["premium"] * 1e4).pivot(index="t", columns="symbol", values="p").reindex(index=idx, columns=cols)
        F["premium_1h"], F["premium_1d"] = pw.rolling(H1, min_periods=int(H1 * 0.8)).mean(), pw.rolling(D1, min_periods=int(D1 * 0.8)).mean()
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("premium absent: premium_* skipped")
    try:                                                     # metrics, 5m: the row stamped ts is used from ts + 5 min
        m = data.load("metrics", columns=["symbol", "ts", "oi", "oi_value", "top_ls_sum", "global_ls", "taker_ratio"], symbols=cols)
        m = m[(m["ts"] < end) & (m["ts"] >= a)]
        m["symbol"] = m["symbol"].astype(str)
        wide = lambda c: m.pivot(index="ts", columns="symbol", values=c).shift(freq=BAR).reindex(index=idx, columns=cols).ffill(limit=3)      # noqa: E731
        oi = pos(wide("oi"))
        F["oi_chg_1d"], F["oi_chg_1w"] = oi.diff(D1), oi.diff(W1)
        F["oi_turn"] = pos(wide("oi_value")) - pos(dv.rolling(D1, min_periods=int(D1 * 0.8)).sum())
        g, tp = pos(wide("global_ls")), pos(wide("top_ls_sum"))
        F["global_ls"], F["global_ls_chg_1d"], F["top_ls"], F["top_vs_global"] = g, g.diff(D1), tp, tp - g
        F["taker_1d"] = pos(wide("taker_ratio")).rolling(D1, min_periods=int(D1 * 0.8)).mean()
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("metrics absent: oi_*, *_ls*, top_vs_global, taker_1d skipped")
    return {k: F[k].replace([np.inf, -np.inf], np.nan) for k in FEATURES}, notes


def _day(ts: pd.DatetimeIndex) -> np.ndarray:
    return (ts.floor("D") - ts[0].floor("D")).days.to_numpy()


def _draws(name: str, f: pd.DataFrame, Z: np.ndarray, lags: int, draws: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    """One feature on the real labels (draw 0) and on `draws` shuffles; shuffle number `draw` is the same for every feature."""
    ts, day, rows, real = f.index, _day(f.index), [], None
    for draw in range(draws + 1):
        src = _shuffle_days(ts, np.ones(len(ts)), np.random.default_rng([seed, draw]), GRID) if draw else np.arange(len(ts))
        ic = _ic_xs(f, pd.DataFrame(Z[src], index=ts, columns=f.columns), day)
        mean, se, n = hac(ic, lags)
        rows.append({"feature": name, "draw": draw, "ic": mean, "se": se, "t": mean / se if se else np.nan, "days": n})
        real = ic if draw == 0 else real
    return pd.DataFrame(rows), real


def verdict(r: dict) -> str:
    if abs(r["t"]) >= T_BAR and r["p_family"] <= P_BAR and r["ic_F_same_sign"]:
        return "CLEARS"
    return "CLOSED" if abs(r["ic"]) + 1.96 * r["se"] < IC_CLOSED else "NOT DETECTABLE"


def run(run: str, draws: int = DRAWS, members: str | None = None, seed: int = 0, jobs: int = 4) -> str:
    from joblib import Parallel, delayed
    run_dir = bt.OUT / run
    meta = json.loads((run_dir / "meta.json").read_text())
    p, fold_names = meta["params"], meta["folds"]
    hold, latency = int(p["hold"]), int(meta["latency_bars"])
    if int(p["grid"]) != 12:
        raise SystemExit("the audit reads hourly decision bars (grid 12)")
    mem = universe.members(members or p.get("members") or None)
    end = folds.bounds(fold_names[-1])[1]
    M = bt.market(meta["pairs"], end)
    o = screen.cells(run_dir, M, hold, latency, fold_names, mem)
    names = sorted(o["symbol"].unique())
    idx = M.index[M.index >= pd.DatetimeIndex(o["t"]).min() - WARMUP]
    sig_h = _derive(M.close.loc[idx, names])["sig"]["1w"] * np.sqrt(hold)
    z = (bt.labels(M, hold, latency).loc[idx, names] / sig_h.where(sig_h > 0)).clip(-Z_CLIP, Z_CLIP)
    t5 = pd.Series(idx, index=idx)
    scored = np.zeros(len(idx), dtype=bool)
    for f in fold_names:
        scored |= folds.mask(t5, f).to_numpy()
    grid = idx[scored & (idx.minute == 0) & (idx.second == 0)]
    lags, day = day_lags(hold), _day(grid)

    # validity: the labels rebuilt here are the run's, on the run's cells
    zi = z.to_numpy()[idx.get_indexer(o["t"]), pd.Index(names).get_indexer(o["symbol"])]
    dz = np.abs(zi - o["z"].to_numpy())
    on_grid = bool(pd.DatetimeIndex(o["t"]).isin(grid).all())
    v = {"status": "PASS" if on_grid and np.isfinite(dz).all() and dz.max() <= Z_TOL else "FAIL", "cells": len(o), "names": len(names),
         "cells_off_grid": int((~pd.DatetimeIndex(o["t"]).isin(grid)).sum()), "cells_without_label": int((~np.isfinite(dz)).sum()), "max_abs_dz": float(np.nanmax(dz))}
    cell = o.assign(one=1.0).pivot(index="t", columns="symbol", values="one").reindex(index=grid, columns=names).notna()
    Z = z.loc[grid].to_numpy()

    F, notes = features(idx, names, M.dv.loc[idx, names], end)
    F = {k: x.loc[grid].where(cell) for k, x in F.items()}
    n_cells = int(cell.to_numpy().sum())
    print(f"audit: {len(F)} features × {draws} draws on {n_cells:,} cells…", flush=True)
    res = Parallel(n_jobs=jobs, verbose=5)(delayed(_draws)(k, x, Z, lags, draws, seed) for k, x in F.items())
    d = pd.concat([r for r, _ in res], ignore_index=True)
    real, null = d[d["draw"] == 0].set_index("feature"), d[(d["draw"] > 0) & d["t"].notna()]
    mx = null.assign(a=null["t"].abs()).groupby("draw")["a"].max()
    dates = pd.date_range(grid[0].floor("D"), periods=int(day.max()) + 1, freq="D")
    month = dates.tz_localize(None).to_period("M")
    fold_of = pd.Series("", index=dates)
    for f in fold_names:
        fold_of[folds.mask(pd.Series(dates, index=dates), f, embargoed=False).to_numpy()] = f
    rows = []
    for (k, x), (_, ic) in zip(F.items(), res):
        r, own = real.loc[k], null[null["feature"] == k]
        if not np.isfinite(r["t"]):
            rows.append({"feature": k, "coverage": float(x.notna().to_numpy().sum() / n_cells), "verdict": "NO DATA"})
            continue
        per_fold = {f: float(np.nanmean(ic[(fold_of == f).to_numpy()])) for f in fold_names}
        mm = pd.Series(ic).groupby(np.asarray(month)).mean().dropna()
        row = {"feature": k, "coverage": float(x.notna().to_numpy().sum() / n_cells), "ic": r["ic"], "se": r["se"], "t": r["t"], "days": int(r["days"]),
               **{f"ic_{f}": per_fold[f] for f in fold_names}, "ic_F_same_sign": bool(len({np.sign(per_fold[f]) for f in fold_names}) == 1),
               "months_same_sign": float((np.sign(mm) == np.sign(r["ic"])).mean()), "mde": MDE_K * r["se"], "upper": abs(r["ic"]) + 1.96 * r["se"],
               "p_single": (1 + int((own["t"].abs() >= abs(r["t"])).sum())) / (len(own) + 1), "p_family": (1 + int((mx >= abs(r["t"])).sum())) / (len(mx) + 1)}
        rows.append({**row, "verdict": verdict(row)})
    tab = pd.DataFrame(rows)

    # described: the run's own forecast by the same statistic, and what a signal needs to pay for the trade on these names
    zh = o.pivot(index="t", columns="symbol", values="zhat").reindex(index=grid, columns=names)
    m_ref, se_ref, _ = hac(_ic_xs(zh, pd.DataFrame(Z, index=grid, columns=names), day), lags)
    yb = bt.labels(M, hold, latency).loc[grid, names].where(cell)
    move = float(yb.sub(yb.mean(axis=1), axis=0).abs().stack().mean())
    fills = pd.read_parquet(run_dir / "fills_taker.parquet") if (run_dir / "fills_taker.parquet").exists() else None
    cost = float((fills["fee_bps"] + fills["other_cost_bps"]).mean()) if fills is not None and len(fills) else np.nan
    need = cost / (Z_TOP * 1.2533 * move)

    clears = tab[tab["verdict"] == "CLEARS"]["feature"].tolist()
    show = lambda df, k=4: df.round(k).to_markdown(index=False)                         # noqa: E731
    md = [f"# The ceiling audit on the point-in-time universe (R20) — the cells of `{run}` (`ft2 audit`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {len(names)} names, {n_cells:,} cells, {int(day.max()) + 1} days · "
          f"label: the move over {hold} bars against the other members · {draws} draws\n",
          "\nWords: a *feature* is one number known about a name before the decision (its funding rate, its open interest …). *IC* is the correlation, across the names "
          "present at one moment, between the feature and the move that followed: 0 = the feature says nothing, ±0.02–0.03 is where a weak signal starts to be usable. "
          "*t* is the IC over its day-to-day standard error; 2 or more is the bar. *p (family)* is the share of label shuffles in which the BEST of the twelve features did "
          "at least as well — the honest bar when twelve things are tried at once. *MDE*: the smallest IC this sample could have shown. A basis point (bps) is 0.01 %.\n",
          "\n## Validity — are the labels the run's?\n",
          f"\n**{v['status']}**: {v['cells']:,} cells of {v['names']} names, largest |Δ label| {v['max_abs_dz']:.3g} (bar {Z_TOL:g}); {v['cells_off_grid']} cells off the hourly grid, "
          f"{v['cells_without_label']} without a label here.\n", *(f"\n- {n}" for n in notes),
          "\n## The features\n",
          f"\n**{len(clears)} of {len(tab)} clear the gate** (|t| ≥ {T_BAR:g}, family-wise p ≤ {P_BAR:g}, one sign in every fold){': ' + ', '.join(clears) if clears else ''}. "
          f"On shuffled labels the best of the family reaches |t| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty ({len(mx)} draws).\n",
          show(tab), "\n",
          "\n## For reference (described, decides nothing)\n",
          f"\n- The run's own forecast (the candle ridge fitted on the twelve), by the same statistic on the same cells: IC {m_ref:+.4f}, t {m_ref / se_ref:.2f}.\n"
          f"- A taker round trip on these names costs {cost:.1f} bps on the run's trades; the mean move against the other members is {move:.0f} bps; trading the top tenth of a "
          f"signal breaks even at an IC of about {need:.3f} (P2 #7's formula).\n"]
    out = OUT / run
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.md").write_text("\n".join(md))
    tab.to_csv(out / "features.csv", index=False)
    d.to_parquet(out / "draws.parquet", index=False)
    pd.DataFrame({k: ic for (k, _), (_, ic) in zip(F.items(), res)}, index=dates).to_csv(out / "ic_daily.csv")
    (out / "validity.json").write_text(json.dumps({**v, "reference_ic": m_ref, "reference_t": m_ref / se_ref, "cost_bps": cost, "move_bps": move, "ic_needed": need,
                                                   "null_max_t_p95": float(mx.quantile(0.95))}, indent=1))
    return "\n".join(md)
