"""R87 (docs/PLAN.md §8): one non-linear model on EVERY per-name input in hand — `ft2 allgbm run`.

The registration is the specification; this docstring only maps it to the code.

cells      the 188 members on the hourly grid of F1+F2 while a member of the block the bar falls in (`audit.member_mask`); the market
           `backtest.market(screen_symbols(), ceiling.END)`.
label      `backtest.labels(M, 288, LATENCY)` ÷ (σ_1w · √288), clipped ±5, minus its mean over the member cells present at the bar (≥ 5).
features   37, from the `SOURCES` builders (each returns frames on the hourly grid × the market's names, known at t by its own module's
           rule); each entered as its percentile rank among the member cells that have it at the bar (≥ 5, else absent) — `rank_rows`.
model      LightGBM, `PARAMS`, fixed.
hold-out   `fits`: per (block b ≥ 1, name group g) the training cells are the other groups' cells whose label ENDED before the block's
           first bar; the scored cells are group g's inside block b. Counted per fit for validity (1).
statistic  R53's pooled IC (`ceiling._ic_pooled` per day, HAC by day) of the forecast with the label re-centred on the cells that have a
           forecast at the bar; `verdict` is the gate. The described rows (ridge, the candle-only and no-candle models, gain by source,
           the per-bar rank IC, by month, the tenths) decide nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import audit, ceiling, folds, universe
from . import backtest as bt
from .ceiling import MDE_K, _ic_pooled, _ic_xs, day_lags, hac

OUT = Path("output/allgbm")
REG, NAME = "R87", "r87"
HOLD = 288
Z_CLIP = 5.0
MIN_PEERS = 5
GROUPS = 4
SEED = 87
PARAMS = dict(objective="regression", n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=2000, colsample_bytree=0.7,
              subsample=0.7, subsample_freq=1, reg_lambda=10.0, random_state=SEED, deterministic=True, force_row_wise=True, n_jobs=1, verbose=-1)
BAR_TAKER, BAR_MAKER, T_BAR = 0.0214, 0.0059, 2.0          # R53's measured bars on these cells at one day; the family is one
CANDLE = ["ret_15m", "ret_1h", "ret_4h", "ret_1d", "ret_1w", "relret_1h", "relret_4h", "relret_1d", "volratio_1h", "volratio_1d",
          "mom_4w", "mom_12w", "vol_4w", "maxd_4w"]
EXPECTED_FEATURES = 37
PER_DAY = 24
CTX = {"end": ceiling.END, "start": None, "members": None}     # set by `build`: the market's end, the hourly grids' start, the members' csv (None = F1+F2's)


# ---- the sources: each builder returns {feature: frame on the hourly grid × names} -----------------------------------------------
def src_candles(M: bt.Market, grid: pd.DatetimeIndex, names: list[str], close: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    from . import forecast, horizon
    close = M.close if close is None else close
    g = grid[grid <= close.index[-1]]
    D = forecast._derive(close)
    F = {k: v.reindex(g) for k, v in ceiling.dir_features(D).items()}
    F |= {k: v.reindex(g) for k, v in horizon.mom_signals(close, {"mom_4w": 8064, "mom_12w": 24192}).items()}
    F |= {k: v.reindex(g) for k, v in horizon.vol_signals(close, {"vol_4w": 8064, "maxd_4w": 8064}).items()}
    assert list(F) == CANDLE, list(F)
    return {k: v.reindex(columns=names) for k, v in F.items()}


def src_positioning(M, grid, names):
    F, _ = audit.features(M.index, list(M.columns), M.dv, CTX["end"])
    return {k: F[k].reindex(index=grid, columns=names) for k in audit.FEATURES}


def src_book(M, grid, names):
    from . import book_ext
    cols = list(M.columns)
    try:
        F = book_ext.features_depth(M.index, cols, CTX["end"])
        return {k: F[k].reindex(index=grid, columns=names) for k in (book_ext.RAW, book_ext.DM)}
    except ValueError:                                         # a name without a depth file (F3+F4's members: the book was fetched for F1+F2's): name by name, absent stays absent
        out = {k: pd.DataFrame(np.nan, index=grid, columns=names) for k in (book_ext.RAW, book_ext.DM)}
        for c in cols:
            try:
                F = book_ext.features_depth(M.index, [c], CTX["end"])
            except ValueError:
                continue
            for k in out:
                out[k][c] = F[k][c].reindex(grid)
        return out


def src_coinbase(M, grid, names):
    from . import cb_ext as cx, coinbase as cb
    kept = [s for s in cx.r62_list()["kept"] if s in names]
    H = cx.features_hourly(cx.hourly(kept, cb.MEMBERS_PARQUET, cx.MEMBERS_SLICES, {s: cb.mult_of(s) for s in kept}))
    return {k: cx.to_panel(H[k], grid, names) for k in (cx.DEV, cx.CHG)}


def src_korea(M, grid, names):
    from . import cb_ext as cx
    kept = [s for s in cx.r64_list()["kept"] if s in names]
    H = cx.features_hourly(cx.hourly_krw(kept, cx.KR_PARQUET, cx.MEMBERS_SLICES))
    return {cx.KDEV: cx.to_panel(H[cx.DEV], grid, names)}


def src_spot(M, grid, names):
    from . import cb_ext as cx, spot, spot_ext as sx
    kept = [s for s in sx.r68_list()["kept"] if s in names]
    G, _ = sx.grids_spot(kept, spot.PARQUET, cx.MEMBERS_SLICES, CTX["start"] or cx.MEMBERS_START, CTX["end"])
    return {k: cx.to_panel(G[sx.GRID_OF[k]], grid, names) for k in (sx.TB24, sx.SR24)}


def src_mix(M, grid, names):
    from . import cb_ext as cx, mix, mix_ext as mx, spot, spot_ext as sx
    kept = [s for s in sx.r68_list()["kept"] if s in names]
    G, _ = mx.grids_mix(kept, mix.PARQUET, spot.PARQUET, CTX["start"] or cx.MEMBERS_START, CTX["end"])
    return {k: cx.to_panel(G[k], grid, names) for k in (mx.CNT, mx.SIZE)}


def src_hl(M, grid, names):
    from . import cb_ext as cx, hl, hl_ext as hx
    kept = [s for s in hx.r69_list()["kept"] if s in names]
    G, _, _ = hx.grids_hl(kept, hl.PARQUET, hl.BN_PARQUET, CTX["start"] or cx.MEMBERS_START, CTX["end"])
    F = cx.to_panel(G[hx.GRID_OF[hx.GAP]], grid, names)
    return {hx.GAP: F.where(np.broadcast_to(np.asarray(grid >= hx.SCORED_FROM)[:, None], F.shape))}        # nothing before the audit's cover (2023-08)


def src_wiki(M, grid, names):
    from . import wiki, wiki_ext as wx
    kept = [s for s in (wx.names_r72(CTX["members"])["names"] if CTX["members"] else wx.names_r72()["names"]) if s in names]
    Dd = wx.daily(wiki.load(), kept)
    return {wx.DEV: wx.to_panel(wx.to_hourly(Dd[wx.DEV], Dd["ts_known"]), grid, names)}


SOURCES = {"candles": src_candles, "positioning": src_positioning, "book": src_book, "coinbase": src_coinbase, "korea": src_korea,
           "spot": src_spot, "mix": src_mix, "hyperliquid": src_hl, "wikipedia": src_wiki}


# ---- the cells -----------------------------------------------------------------------------------------------------------------------
def rank_rows(X: np.ndarray, cell: np.ndarray, min_n: int = MIN_PEERS) -> np.ndarray:
    """Per bar: the percentile rank (rank − 0.5) / n of each member cell that has the value, among those cells; absent stays NaN; a bar
    with fewer than `min_n` of them has none."""
    x = np.where(cell, X, np.nan)
    ok = ~np.isnan(x)
    n = ok.sum(1)
    r = pd.DataFrame(x).rank(axis=1).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (r - 0.5) / n[:, None]
    out[(n < min_n)[:, None] & np.ones_like(ok)] = np.nan
    return out.astype(np.float32)


def centre(z: np.ndarray, ok: np.ndarray, min_n: int = MIN_PEERS) -> np.ndarray:
    """z minus its mean over the cells `ok` at the bar (≥ `min_n` of them, else NaN); NaN outside `ok`."""
    zz = np.where(ok, z, np.nan)
    n = (~np.isnan(zz)).sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.nansum(zz, 1) / n
    out = zz - m[:, None]
    out[n < min_n] = np.nan
    return out


def fits(block: np.ndarray, t_end: np.ndarray, block_start: np.ndarray, grp: np.ndarray, usable: np.ndarray, scorable: np.ndarray):
    """Yield (b, g, train mask, score mask) on the bar × name grid: block b ≥ 1, name group g; train = usable cells of the OTHER groups
    whose label ended strictly before the block's first bar; score = scorable cells of group g inside the block."""
    for b in range(1, int(block.max()) + 1):
        before = (t_end < block_start[b])[:, None]
        inside = (block == b)[:, None]
        for g in range(GROUPS):
            yield b, g, usable & before & (grp != g)[None, :], scorable & inside & (grp == g)[None, :]


def _fit_predict(kind: str, Xtr, ytr, Xte, cols):
    if kind == "ridge":
        from sklearn.linear_model import RidgeCV
        m = RidgeCV(alphas=ceiling.ALPHAS, fit_intercept=False).fit(np.nan_to_num(Xtr[:, cols], nan=0.5) - 0.5, ytr)
        return m.predict(np.nan_to_num(Xte[:, cols], nan=0.5) - 0.5), None
    import lightgbm as lgb
    m = lgb.LGBMRegressor(**PARAMS).fit(Xtr[:, cols], ytr)
    return m.predict(Xte[:, cols]), m.booster_.feature_importance(importance_type="gain")


def walk(X: np.ndarray, zres: np.ndarray, plan: list, kind: str = "gbm", cols: list[int] | None = None, jobs: int = 1):
    """The forecast on the bar × name grid (NaN where not scored) and the mean gain per feature (None for the ridge). X: bar × name ×
    feature; a fit needs ≥ 2 × the leaf floor of training cells, else its cells stay unscored and the fit is listed with 0 rows."""
    from joblib import Parallel, delayed
    cols = list(range(X.shape[2])) if cols is None else cols

    def one(b, g, tr, te):
        if tr.sum() < 2 * PARAMS["min_child_samples"] or not te.any():
            return b, g, te, None, None, int(tr.sum())
        p, imp = _fit_predict(kind, X[tr], zres[tr], X[te], cols)
        return b, g, te, p, imp, int(tr.sum())
    res = Parallel(n_jobs=jobs, backend="threading", verbose=5)(delayed(one)(*a) for a in plan)      # threads: the matrix is shared, the fits release the GIL
    f = np.full(zres.shape, np.nan)
    gains, rows = [], []
    for b, g, te, p, imp, n in res:
        rows.append({"block": b, "group": g, "train_cells": n, "scored_cells": int(te.sum()) if p is not None else 0})
        if p is not None:
            f[te] = p
            if imp is not None:
                gains.append(imp / max(imp.sum(), 1e-12))
    return f, (np.mean(gains, 0) if gains else None), pd.DataFrame(rows)


def ic_row(f: np.ndarray, z: np.ndarray, day: np.ndarray, keep: np.ndarray | None = None) -> dict:
    """R53's (A): the forecast against z re-centred on the cells that have a forecast at the bar; pooled, HAC by day."""
    have = ~np.isnan(f) & ~np.isnan(z)
    zr = centre(z, have)
    if keep is not None:
        zr = np.where(keep[:, None], zr, np.nan)
    d = np.repeat(day[:, None], f.shape[1], 1)
    ok = ~np.isnan(zr)
    if ok.sum() < 200:
        return {"cells": int(ok.sum()), "days": 0, "ic": np.nan, "se": np.nan, "t": np.nan}
    m, se, n = hac(_ic_pooled(f[ok], zr[ok], d[ok], min_cells=1), day_lags(HOLD))
    return {"cells": int(ok.sum()), "days": n, "ic": m, "se": se, "t": m / se if se else np.nan}


def verdict(ic: float, se: float, t: float, folds_pos: bool) -> str:
    if not np.isfinite(ic) or not np.isfinite(se):
        return "NOT DETECTABLE"
    if t >= T_BAR and folds_pos and ic >= BAR_TAKER:
        return "CLEARS"
    if t >= T_BAR and folds_pos and ic >= BAR_MAKER:
        return "REAL UNDER THE TAKER BAR"
    return "CLOSED" if ic + 1.96 * se < BAR_MAKER else "NOT DETECTABLE"


# ---- the run -------------------------------------------------------------------------------------------------------------------------
def build(members: str | None, fold_names, sources: dict, end: pd.Timestamp | None = None, start: pd.Timestamp | None = None, grids_start: pd.Timestamp | None = None,
          span: tuple[pd.Timestamp, pd.Timestamp] | None = None) -> dict:
    """The cells of `fold_names` for the members of `members`: the market, the hourly grid, the member mask, the blocks, the label (z, its
    re-centred form), the ranked feature matrix (bar × name × feature) and each feature's cover. `end` / `start`: the market's span
    (F1+F2's by default); `grids_start`: where the hourly sources' grids begin; `span` (R97): the scored bars are [span[0], span[1]) instead
    of the folds' own masks (the pre-history's days are the frozen list's, not a fold's). No outcome is read by the features."""
    from . import forecast
    end = ceiling.END if end is None else end
    CTX.update(end=end, start=grids_start, members=members)
    mem = universe.members(members)
    names = universe.screen_symbols(members)
    print("market…", flush=True)
    M = bt.market(names, end) if start is None else bt.market(names, end, start)
    names = [c for c in names if c in M.columns]
    idx = M.index
    t5 = pd.Series(idx, index=idx)
    scored = np.zeros(len(idx), dtype=bool)
    for f_ in fold_names:
        scored |= folds.mask(t5, f_).to_numpy()
    if span is not None:
        scored = np.asarray((idx >= span[0]) & (idx < span[1]))
    grid = idx[scored & (idx.minute == 0) & (idx.second == 0)]
    day = (grid.floor("D") - grid[0].floor("D")).days.to_numpy()
    cell = audit.member_mask(mem, np.asarray(names), grid)
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    block = np.searchsorted(starts.asi8, grid.asi8, side="right") - 1
    t_end = grid + pd.Timedelta(minutes=5 * (bt.LATENCY + HOLD))
    grp = np.array([i % GROUPS for i in range(len(names))])                       # R53's: the sorted member names, every fourth

    print("the label…", flush=True)
    sig = forecast._derive(M.close)["sig"]["1w"].reindex(index=grid, columns=names).to_numpy()
    y = bt.labels(M, HOLD, bt.LATENCY).reindex(index=grid, columns=names).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.clip(y / (np.where(sig > 0, sig, np.nan) * np.sqrt(HOLD)), -Z_CLIP, Z_CLIP)
    scorable = cell & np.isfinite(sig) & (sig > 0)
    zres = centre(z, cell)
    usable = scorable & ~np.isnan(zres)

    print("the features…", flush=True)
    feats, src_of, cover = [], [], []
    for sname, fn in sources.items():
        F = fn(M, grid, names)
        for k, v in F.items():
            a = v.reindex(index=grid, columns=names).to_numpy(dtype=float)
            a[~np.isfinite(a)] = np.nan
            feats.append(rank_rows(a, cell))
            src_of.append((sname, k))
            cover.append({"source": sname, "feature": k, "cells": int((~np.isnan(feats[-1]) & scorable).sum()), "cover": float((~np.isnan(feats[-1]) & scorable).sum() / max(scorable.sum(), 1)),
                          "names": int((~np.isnan(feats[-1]) & scorable).any(0).sum())})
        print(f"  {sname}: {len(F)} feature(s)", flush=True)
        del F
    X = np.stack(feats, axis=-1)
    del feats
    return {"M": M, "mem": mem, "names": names, "grid": grid, "day": day, "cell": cell, "starts": starts, "block": block, "t_end": t_end, "grp": grp, "y": y, "z": z, "zres": zres,
            "scorable": scorable, "usable": usable, "X": X, "src_of": src_of, "cover": pd.DataFrame(cover), "fold_names": list(fold_names)}


def cover(name: str, members: str | None, fold_names, end: pd.Timestamp, start: pd.Timestamp, grids_start: pd.Timestamp, sources: dict | None = None,
          span: tuple[pd.Timestamp, pd.Timestamp] | None = None) -> pd.DataFrame:
    """The features' cover on the members' cells of `fold_names` — no forecast, no IC, no label statistic: the check made BEFORE a
    registration on those folds is written."""
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    B = build(members, fold_names, SOURCES if sources is None else sources, end, start, grids_start, span)
    B["cover"].to_csv(out / "cover.csv", index=False)
    per_block = pd.DataFrame({"block": B["starts"][np.unique(B["block"])], "scorable_cells": [int(B["scorable"][B["block"] == b].sum()) for b in np.unique(B["block"])],
                              "names": [int(B["scorable"][B["block"] == b].any(0).sum()) for b in np.unique(B["block"])]})
    per_block.to_csv(out / "cover_blocks.csv", index=False)
    (out / "cover.json").write_text(json.dumps({"folds": list(fold_names), "names": len(B["names"]), "rows": int(len(B["grid"])), "scorable_cells": int(B["scorable"].sum()),
                                                "first": str(B["grid"][0]), "last": str(B["grid"][-1]), "blocks": int(B["block"].max()) + 1}, indent=1))
    print(B["cover"].round(4).to_string(index=False), flush=True)
    return B["cover"]


def run(name: str = NAME, members: str | None = None, jobs: int = 4, sources: dict | None = None, fold_names=None) -> str:
    sources = SOURCES if sources is None else sources
    fold_names = list(fold_names or folds.EXPLORATION)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    B = build(members, fold_names, sources)
    M, mem, names, grid, day, cell, starts, block, t_end, grp = (B[k] for k in ("M", "mem", "names", "grid", "day", "cell", "starts", "block", "t_end", "grp"))
    y, z, zres, scorable, usable, X, src_of, cov = (B[k] for k in ("y", "z", "zres", "scorable", "usable", "X", "src_of", "cover"))
    cov.to_csv(out / "cover.csv", index=False)
    fnames = [k for _, k in src_of]

    # validity (2): the candle features causal — recomputed on the market cut at the midpoint, identical at every cell at or before it
    d_causal = None
    if "candles" in sources:
        mid = grid[len(grid) // 2]
        again = sources["candles"](M, grid, names, M.close.loc[M.close.index <= mid])
        full = sources["candles"](M, grid, names)
        d_causal = 0.0
        for k in again:
            a, b = full[k].reindex(index=grid[grid <= mid], columns=names), again[k].reindex(index=grid[grid <= mid], columns=names)
            both = a.notna() & b.notna()
            d_causal = max(d_causal, float((a - b).abs().where(both).max().max() or 0.0), float((a.isna() != b.isna()).sum().sum()))
        del again, full
    plan = list(fits(block, t_end.asi8, starts.asi8, grp, usable, scorable))
    leak_group = sum(int((tr & (grp == g)[None, :]).sum()) for _, g, tr, _ in plan)
    leak_time = sum(int((tr & (t_end.asi8 >= starts.asi8[b])[:, None]).sum()) for b, _, tr, _ in plan)
    per_src = cov.groupby("source")["cells"].max()
    in_scope = mem[(mem["block"] >= grid[0].floor("D") - pd.Timedelta(days=30)) & (mem["block"] < grid[-1])]
    member_names = sorted(set(in_scope["symbol"]))
    gsize = np.bincount(grp, minlength=GROUPS).tolist()
    y_chk = bt.labels(M, HOLD, bt.LATENCY).reindex(index=grid, columns=names).to_numpy()
    v = {"registration": REG, "folds": fold_names, "hold": HOLD, "params": PARAMS, "features": len(fnames), "feature_names": fnames, "names": len(names), "members": len(member_names),
         "members_without_bars": [c for c in member_names if c not in names], "blocks": int(in_scope["block"].nunique()), "groups": gsize, "rows": int(len(grid)), "days": int(day.max()) + 1,
         "fits": len(plan), "train_cells_of_the_scored_group": leak_group, "train_cells_with_label_ending_in_or_after_the_block": leak_time, "max_abs_d_causal": d_causal,
         "sources_without_a_cell": [s for s, n in per_src.items() if n == 0], "max_abs_d_label": float(np.nanmax(np.abs(y - y_chk))) if np.isfinite(y).any() else None,
         "scorable_cells": int(scorable.sum()), "usable_cells": int(usable.sum()), "bars": {"taker": BAR_TAKER, "maker": BAR_MAKER, "t": T_BAR}}
    v["status"] = "PASS" if (leak_group == 0 and leak_time == 0 and (d_causal in (None, 0.0)) and not v["sources_without_a_cell"] and not v["members_without_bars"]
                             and len(plan) >= GROUPS and v["max_abs_d_label"] == 0.0) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {REG} — one boosted-tree model on every per-name input, the members' next day against their peers (`ft2 allgbm run`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {len(names)} names · {len(fnames)} features from {len(sources)} sources · "
            f"{len(plan)} fits (blocks × name groups) · bars: taker {BAR_TAKER}, maker {BAR_MAKER}, t ≥ {T_BAR:g}\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps({k: x for k, x in v.items() if k not in ("feature_names", "params")}, indent=1, default=str), "\n```\n",
            "\n### Cover of each feature on the scorable member cells\n", cov.round(4).to_markdown(index=False), "\n"]
    if v["status"] != "PASS":
        (out / "read.md").write_text("\n".join(head + ["\n**The read is VOID: no IC was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    ci = [i for i, (s, _) in enumerate(src_of) if s == "candles"]
    oi = [i for i in range(len(src_of)) if i not in ci]
    variants = {"gbm (the gate)": ("gbm", None), "ridge, the same matrix": ("ridge", None)}
    if ci and oi:
        variants |= {"gbm, candles only": ("gbm", ci), "gbm, without the candles": ("gbm", oi)}
    F, rows, gain, fit_tab = {}, [], None, None
    fold_of = np.full(len(grid), "", dtype=object)
    for f_ in fold_names:
        fold_of[folds.mask(pd.Series(grid, index=grid), f_, embargoed=False).to_numpy()] = f_
    for label, (kind, cols) in variants.items():
        print(f"{label}…", flush=True)
        f, g_, tab = walk(X, zres, plan, kind, cols, jobs)
        F[label] = f
        if label.startswith("gbm (the gate)"):
            gain, fit_tab = g_, tab
        r = ic_row(f, z, day)
        pf = {f_: ic_row(f, z, day, fold_of == f_)["ic"] for f_ in fold_names}
        zr = centre(z, ~np.isnan(f) & ~np.isnan(z))
        m_xs, se_xs, _ = hac(_ic_xs(pd.DataFrame(f), pd.DataFrame(zr), day), day_lags(HOLD))
        yb = np.where(~np.isnan(f), y, np.nan)
        from .horizon import _tenths
        whole = len(grid) % PER_DAY == 0
        tenths = float(np.nanmean(_tenths(f, yb))) if whole else np.nan
        folds_pos = bool(all(np.isfinite(x) and x > 0 for x in pf.values()))
        rows.append({"model": label, **r, "mde": MDE_K * r["se"] if np.isfinite(r["se"]) else np.nan, **{f"ic_{k}": x for k, x in pf.items()}, "folds_positive": folds_pos,
                     "ic_rank_per_bar": m_xs, "t_rank": m_xs / se_xs if se_xs else np.nan, "tenths_bps_a_leg": tenths,
                     "verdict": verdict(r["ic"], r["se"], r["t"], folds_pos) if label.startswith("gbm (the gate)") else "described"})
    tab = pd.DataFrame(rows)
    gate = tab.iloc[0]
    f = F["gbm (the gate)"]
    by_group = pd.DataFrame([{"group": g, **ic_row(np.where((grp == g)[None, :], f, np.nan), z, day)} for g in range(GROUPS)])
    month = pd.Series(grid.strftime("%Y-%m"))
    by_month = pd.DataFrame([{"month": mth, **ic_row(f, z, day, (month == mth).to_numpy())} for mth in sorted(month.unique())])
    imp = pd.DataFrame({"source": [s for s, _ in src_of], "feature": fnames, "gain_share": gain if gain is not None else np.nan}).sort_values("gain_share", ascending=False)
    by_src = imp.groupby("source")["gain_share"].sum().sort_values(ascending=False).reset_index()
    show = lambda d, k=4: d.round(k).to_markdown(index=False)                    # noqa: E731
    md = head + [
        "\nWords: *ic*: the correlation of the model's forecast with what the name then did against its peers over the next day (in its own sigmas), on cells whose name and "
        "days the model never saw; 0 = a coin flip. *se*, *t*: its noise and the ratio, clustered by day. *taker bar* 0.0214: the IC at which a taker round trip on these names "
        "is paid; *maker bar* 0.0059: the same for a resting order (an estimate). *tenths*: what the top tenth by the forecast earned over the bottom tenth, bps a leg a day, "
        "before costs.\n",
        f"\n## The gate — **{gate['verdict']}**: held-out IC {gate['ic']:+.4f} (se {gate['se']:.4f}, t {gate['t']:+.2f}, MDE {gate['mde']:.4f}) on {int(gate['cells']):,} cells, "
        f"{int(gate['days'])} days; per fold " + ", ".join(f"{k} {gate[f'ic_{k}']:+.4f}" for k in fold_names) + "\n", show(tab), "\n",
        "\n## Described (decides nothing)\n", "\n### By name group\n", show(by_group), "\n", "\n### By month\n", show(by_month), "\n",
        "\n### The gain share by source and by feature (the gate's model, the mean over its fits)\n", show(by_src), "\n", show(imp), "\n",
        "\n### The fits (training and scored cells)\n", show(fit_tab, 0), "\n"]
    (out / "read.md").write_text("\n".join(md))
    tab.to_csv(out / "models.csv", index=False)
    imp.to_csv(out / "importance.csv", index=False)
    fit_tab.to_csv(out / "fits.csv", index=False)
    o = pd.DataFrame({"t": np.repeat(grid.to_numpy(), len(names)), "symbol": np.tile(np.asarray(names), len(grid)), "f": f.ravel(), "z": z.ravel()})
    o[~np.isnan(o["f"])].to_parquet(out / "forecast.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "verdict": gate["verdict"], "ic": float(gate["ic"]), "se": float(gate["se"]), "t": float(gate["t"]),
                                                   "train_cells_min": int(fit_tab["train_cells"].min()), "train_cells_max": int(fit_tab["train_cells"].max())}, indent=1, default=str))
    print(f"{REG}: {gate['verdict']} — IC {gate['ic']:+.4f} (t {gate['t']:+.2f}); wrote {out}/", flush=True)
    return "\n".join(md)


# ---- R88: the confirmation read — one frozen ridge, fitted on F1+F2's members, scored once on F3+F4's -------------------------------
REG88, NAME88 = "R88", "r88"
DROP88 = ("premium_1h", "premium_1d", "depth_imb_1", "depth_imb_1_dm")           # no cell on F3+F4 by the cover check of 2026-11-11
T_ONE_SIDED = 1.645
CONF_FOLDS = ("F3", "F4")
CONF_START, CONF_GRIDS = pd.Timestamp("2024-03-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC")


# decision CU1 (2026-11-15): the screener's members BEFORE F1 (R23's frozen list). The market from 2021-09-01 (the 12-week momentum's lookback), the hourly
# grids from 2021-11-01 (a trailing month before the first scored day), the scored bars R23's own days — the first whole day after the archive's open interest
# has a week (2021-12-10) to the list's last day (2023-04-23, inclusive); the market ends at F1's first instant, so no bar of F1 is read.
PRE_START, PRE_GRIDS = pd.Timestamp("2021-09-01", tz="UTC"), pd.Timestamp("2021-11-01", tz="UTC")
PRE_SPAN = (pd.Timestamp(universe.PRE_DAYS[0], tz="UTC"), pd.Timestamp(universe.PRE_DAYS[1], tz="UTC") + pd.Timedelta(days=1))
PRE_FOLDS = ("FP", "F0")


F5_START, F5_GRIDS = pd.Timestamp("2025-07-01", tz="UTC"), pd.Timestamp("2025-10-01", tz="UTC")     # decision CO1: F5's market and hourly grids, six / three months before the fold as F3+F4's were


def verdict88(ic: float, se: float, t: float) -> str:
    if np.isfinite(ic) and np.isfinite(t) and t >= T_ONE_SIDED and ic >= BAR_MAKER:
        return "CONFIRMED AT THE TAKER BAR" if ic >= BAR_TAKER else "CONFIRMED"
    return "NOT CONFIRMED — CLOSED" if np.isfinite(ic) and np.isfinite(se) and ic + 1.96 * se < BAR_MAKER else "NOT CONFIRMED"


def frozen_fit(X: np.ndarray, zres: np.ndarray, train: np.ndarray, cols: list[int]) -> dict:
    """The gate's model on the training cells: RidgeCV over `ceiling.ALPHAS`, no intercept, on (rank − 0.5) with an absent value at 0;
    and R87's trees on the same cells and columns (described)."""
    import lightgbm as lgb
    from sklearn.linear_model import RidgeCV
    Xt, yt = X[train][:, cols], zres[train]
    r = RidgeCV(alphas=ceiling.ALPHAS, fit_intercept=False).fit(np.nan_to_num(Xt, nan=0.5) - 0.5, yt)
    g = lgb.LGBMRegressor(**{**PARAMS, "n_jobs": 8}).fit(Xt, yt)
    return {"coef": np.asarray(r.coef_, float), "alpha": float(r.alpha_), "gbm": g, "train_cells": int(train.sum())}


def frozen_score(X: np.ndarray, scorable: np.ndarray, cols: list[int], fit: dict) -> dict[str, np.ndarray]:
    """The two forecasts on the scorable cells of another build (NaN elsewhere)."""
    out = {}
    Xs = X[scorable][:, cols]
    for k, p in (("ridge (the gate)", (np.nan_to_num(Xs, nan=0.5) - 0.5) @ fit["coef"]), ("gbm, R87's parameters", fit["gbm"].predict(Xs))):
        f = np.full(scorable.shape, np.nan)
        f[scorable] = p
        out[k] = f
    return out


def _causal(B: dict, sources: dict) -> float | None:
    if "candles" not in sources:
        return None
    M, grid, names = B["M"], B["grid"], B["names"]
    mid = grid[len(grid) // 2]
    again, full = sources["candles"](M, grid, names, M.close.loc[M.close.index <= mid]), sources["candles"](M, grid, names)
    d = 0.0
    for k in again:
        a, b = full[k].reindex(index=grid[grid <= mid], columns=names), again[k].reindex(index=grid[grid <= mid], columns=names)
        both = a.notna() & b.notna()
        d = max(d, float((a - b).abs().where(both).max().max() or 0.0), float((a.isna() != b.isna()).sum().sum()))
    return d


def confirm(name: str = NAME88, sources: dict | None = None, members_fit: str | None = None, members_conf: str | None = None, registration: str = REG88) -> str:
    import hashlib
    from .horizon import _tenths
    from .universe import F34_MEMBERS_CSV
    sources = SOURCES if sources is None else sources
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    conf = bt._guard(list(CONF_FOLDS), registration)                       # F3+F4: only under the registration, once; logged when the number exists
    f3_start = folds.bounds(CONF_FOLDS[0])[0]

    print("F1+F2: the cells the model is fitted on…", flush=True)
    B1 = build(members_fit, folds.EXPLORATION, sources)
    names1 = [k for _, k in B1["src_of"]]
    cols = [i for i, k in enumerate(names1) if k not in DROP88]
    used = [names1[i] for i in cols]
    train = B1["usable"] & (B1["t_end"].asi8 < f3_start.value)[:, None]
    late = int((B1["usable"] & ~train).sum())
    fit = frozen_fit(B1["X"], B1["zres"], train, cols)
    coef = pd.DataFrame({"source": [B1["src_of"][i][0] for i in cols], "feature": used, "coef": fit["coef"]})
    coef.to_csv(out / "coef.csv", index=False)
    coef_md5 = hashlib.md5((out / "coef.csv").read_bytes()).hexdigest()
    print(f"frozen: {len(used)} features, {fit['train_cells']:,} cells, alpha {fit['alpha']:g}, coef.csv md5 {coef_md5}", flush=True)
    del B1["X"], B1["M"]

    print("F3+F4: the cells it is scored on…", flush=True)
    B2 = build(members_conf or F34_MEMBERS_CSV, CONF_FOLDS, sources, folds.bounds(CONF_FOLDS[-1])[1], CONF_START, CONF_GRIDS)
    names2 = [k for _, k in B2["src_of"]]
    cov = B2["cover"].set_index("feature")
    d_causal = _causal(B2, sources)
    v = {"registration": registration, "folds_fit": list(folds.EXPLORATION), "folds_scored": list(CONF_FOLDS), "features": len(used), "feature_names": used, "dropped": list(DROP88),
         "same_feature_names": names1 == names2, "dropped_in_use": [k for k in used if k in DROP88], "train_cells": fit["train_cells"], "train_cells_with_label_ending_in_or_after_F3": int((train & (B1["t_end"].asi8 >= f3_start.value)[:, None]).sum()),
         "usable_cells_left_out_by_the_embargo": late, "alpha": fit["alpha"], "coef_md5": coef_md5, "features_without_a_cell_on_the_scored_folds": [k for k in used if int(cov.loc[k, "cells"]) == 0],
         "max_abs_d_causal": d_causal, "names_scored": len(B2["names"]), "scorable_cells": int(B2["scorable"].sum()), "rows": int(len(B2["grid"])), "first": str(B2["grid"][0]), "last": str(B2["grid"][-1]),
         "bars": {"taker": BAR_TAKER, "maker": BAR_MAKER, "t_one_sided": T_ONE_SIDED}}
    v["status"] = "PASS" if (v["same_feature_names"] and not v["dropped_in_use"] and v["train_cells_with_label_ending_in_or_after_F3"] == 0 and not v["features_without_a_cell_on_the_scored_folds"]
                             and d_causal in (None, 0.0) and len(used) == len(names1) - sum(k in names1 for k in DROP88)) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    B2["cover"].to_csv(out / "cover.csv", index=False)
    head = [f"# {registration} — the frozen all-inputs model, fitted on F1+F2's members, scored once on F3+F4's (`ft2 allgbm confirm`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(used)} features · fitted on {fit['train_cells']:,} cells (alpha {fit['alpha']:g}) · scored on {len(B2['names'])} names · "
            f"bars: maker {BAR_MAKER}, taker {BAR_TAKER}, one-sided t ≥ {T_ONE_SIDED}\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps({k: x for k, x in v.items() if k != "feature_names"}, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "read.md").write_text("\n".join(head + ["\n**The read is VOID: no IC was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    grid, day, z, y = B2["grid"], B2["day"], B2["z"], B2["y"]
    F = frozen_score(B2["X"], B2["scorable"], cols, fit)
    fold_of = np.full(len(grid), "", dtype=object)
    for f_ in CONF_FOLDS:
        fold_of[folds.mask(pd.Series(grid, index=grid), f_, embargoed=False).to_numpy()] = f_
    rows = []
    for label, f in F.items():
        r = ic_row(f, z, day)
        zr = centre(z, ~np.isnan(f) & ~np.isnan(z))
        m_xs, se_xs, _ = hac(_ic_xs(pd.DataFrame(f), pd.DataFrame(zr), day), day_lags(HOLD))
        tenths = float(np.nanmean(_tenths(f, np.where(~np.isnan(f), y, np.nan)))) if len(grid) % PER_DAY == 0 else np.nan
        rows.append({"model": label, **r, "mde": MDE_K * r["se"] if np.isfinite(r["se"]) else np.nan, **{f"ic_{k}": ic_row(f, z, day, fold_of == k)["ic"] for k in CONF_FOLDS},
                     "ic_rank_per_bar": m_xs, "t_rank": m_xs / se_xs if se_xs else np.nan, "tenths_bps_a_leg": tenths,
                     "verdict": verdict88(r["ic"], r["se"], r["t"]) if label.startswith("ridge") else "described"})
    tab = pd.DataFrame(rows)
    gate = tab.iloc[0]
    f = F["ridge (the gate)"]
    month = pd.Series(grid.strftime("%Y-%m"))
    by_month = pd.DataFrame([{"month": mth, **ic_row(f, z, day, (month == mth).to_numpy())} for mth in sorted(month.unique())])
    show = lambda d, k=4: d.round(k).to_markdown(index=False)                    # noqa: E731
    md = head + [
        f"\n## The gate — **{gate['verdict']}**: the frozen ridge's IC on F3+F4 {gate['ic']:+.4f} (se {gate['se']:.4f}, t {gate['t']:+.2f}, MDE {gate['mde']:.4f}) on {int(gate['cells']):,} cells, "
        f"{int(gate['days'])} days; " + ", ".join(f"{k} {gate[f'ic_{k}']:+.4f}" for k in CONF_FOLDS) + "\n", show(tab), "\n",
        "\n## Described (decides nothing)\n", "\n### By month (the gate's model)\n", show(by_month), "\n", "\n### The frozen coefficients (on rank − 0.5)\n", show(coef.sort_values("coef", key=np.abs, ascending=False)), "\n",
        "\n### Cover of each feature on F3+F4's scorable member cells\n", B2["cover"].round(4).to_markdown(index=False), "\n"]
    (out / "read.md").write_text("\n".join(md))
    tab.to_csv(out / "models.csv", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "verdict": gate["verdict"], "ic": float(gate["ic"]), "se": float(gate["se"]), "t": float(gate["t"])}, indent=1, default=str))
    if conf:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "allgbm confirm",
                      "params": json.dumps({"features": len(used), "alpha": fit["alpha"], "coef_md5": coef_md5})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    print(f"{registration}: {gate['verdict']} — IC {gate['ic']:+.4f} (t {gate['t']:+.2f}); wrote {out}/", flush=True)
    return "\n".join(md)


# ---- R89: the frozen trees (R88's described fit) scored once on F5's coin members ------------------------------------------------------
REG89, NAME89 = "R89", "r89"
R88_TRAIN_CELLS = 695_140                                    # R88's fit: the same cells, or the model is not the one F3+F4 described
R89_SCORABLE = 298_291                                       # the cover check's count on F5's coin cells (output/allgbm/cover_f5_coins)
R89_MD5 = {"screen_members_f5.csv": "778ca0a5498cc1fc103d16361d456392", "screen_members_f5_coins.csv": "816f8ab9f53b54ca3070e1937fee14ef",
           "f5_contract_types.csv": "ba761b2090f4844a6f607ed0142c37d7"}
LATE_FROM = pd.Timestamp("2026-07-02", tz="UTC")              # the three last blocks (38 … 29 coins a bar), described apart


def ic_cells(f: np.ndarray, z: np.ndarray, day: np.ndarray, cells: np.ndarray | None = None) -> dict:
    """`ic_row` on a SUBSET of cells: the label is re-centred on every cell that has a forecast at the bar (the peers stay the whole
    set), then only `cells` (bar × name) enter the pooled IC."""
    have = ~np.isnan(f) & ~np.isnan(z)
    zr = centre(z, have)
    if cells is not None:
        zr = np.where(cells, zr, np.nan)
    d = np.repeat(day[:, None], f.shape[1], 1)
    ok = ~np.isnan(zr)
    if ok.sum() < 200:
        return {"cells": int(ok.sum()), "days": 0, "ic": np.nan, "se": np.nan, "t": np.nan}
    m, se, n = hac(_ic_pooled(f[ok], zr[ok], d[ok], min_cells=1), day_lags(HOLD))
    return {"cells": int(ok.sum()), "days": n, "ic": m, "se": se, "t": m / se if se else np.nan}


def trees_score(model, X: np.ndarray, scorable: np.ndarray, cols: list[int]) -> np.ndarray:
    """The frozen trees' forecast on the scorable cells of a build (NaN elsewhere); `model` is anything with `.predict`."""
    f = np.full(scorable.shape, np.nan)
    f[scorable] = model.predict(X[scorable][:, cols])
    return f


def confirm5(name: str = NAME89, sources: dict | None = None, members_fit: str | None = None, members_conf: str | None = None, members_all: str | None = None,
             registration: str = REG89, expect: bool = True) -> str:
    import hashlib
    import lightgbm as lgb
    from .horizon import _tenths
    from .universe import F5_COINS_CSV, F5_MEMBERS_CSV, F5_TYPES_CSV
    sources = SOURCES if sources is None else sources
    members_conf, members_all = members_conf or F5_COINS_CSV, members_all or F5_MEMBERS_CSV
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    conf = bt._guard(["F5"], registration)                                 # F5: only under the registration, once; logged when the number exists
    md5 = lambda p: hashlib.md5(Path(p).read_bytes()).hexdigest()         # noqa: E731
    lists = {Path(p).name: md5(p) for p in (F5_MEMBERS_CSV, F5_COINS_CSV, F5_TYPES_CSV)} if expect else {}
    f3_start = folds.bounds("F3")[0]

    print("F1+F2: the cells the model is fitted on…", flush=True)
    B1 = build(members_fit, folds.EXPLORATION, sources)
    names1 = [k for _, k in B1["src_of"]]
    cols = [i for i, k in enumerate(names1) if k not in DROP88]
    used = [names1[i] for i in cols]
    train = B1["usable"] & (B1["t_end"].asi8 < f3_start.value)[:, None]
    late_train = int((train & (B1["t_end"].asi8 >= f3_start.value)[:, None]).sum())
    r88_names = list(pd.read_csv(OUT / NAME88 / "coef.csv")["feature"]) if expect else used
    gbm = lgb.LGBMRegressor(**{**PARAMS, "n_jobs": 8}).fit(B1["X"][train][:, cols], B1["zres"][train])
    gbm.booster_.save_model(str(out / "model.txt"))
    model_md5 = md5(out / "model.txt")
    model = lgb.Booster(model_file=str(out / "model.txt"))                 # the FILE is the model from here on
    train_cells = int(train.sum())
    print(f"frozen: {len(used)} features, {train_cells:,} cells, model.txt md5 {model_md5}", flush=True)
    del B1

    print("F5: the coin cells it is scored on…", flush=True)
    end = folds.bounds("F5")[1]
    B2 = build(members_conf, ("F5",), sources, end, F5_START, F5_GRIDS)
    names2 = [k for _, k in B2["src_of"]]
    cov = B2["cover"].set_index("feature")
    d_causal = _causal(B2, sources)
    v = {"registration": registration, "folds_fit": list(folds.EXPLORATION), "folds_scored": ["F5"], "lists_md5": lists, "lists_as_registered": lists == R89_MD5 if expect else None,
         "features": len(used), "feature_names": used, "same_names_as_r88": used == r88_names, "dropped_in_use": [k for k in used if k in DROP88], "train_cells": train_cells,
         "train_cells_as_r88": train_cells == R88_TRAIN_CELLS if expect else None, "train_cells_with_label_ending_in_or_after_F3": late_train, "model_md5": model_md5,
         "same_feature_names": names1 == names2, "features_without_a_cell_on_F5": [k for k in used if int(cov.loc[k, "cells"]) == 0], "max_abs_d_causal": d_causal,
         "names_scored": len(B2["names"]), "blocks": int(B2["block"].max()) + 1, "scorable_cells": int(B2["scorable"].sum()), "scorable_as_the_cover_check": int(B2["scorable"].sum()) == R89_SCORABLE if expect else None,
         "rows": int(len(B2["grid"])), "first": str(B2["grid"][0]), "last": str(B2["grid"][-1]), "bars": {"taker": BAR_TAKER, "maker": BAR_MAKER, "t_one_sided": T_ONE_SIDED}}
    v["status"] = "PASS" if (v["same_names_as_r88"] and not v["dropped_in_use"] and late_train == 0 and v["same_feature_names"] and not v["features_without_a_cell_on_F5"]
                             and d_causal in (None, 0.0) and v["lists_as_registered"] in (None, True) and v["train_cells_as_r88"] in (None, True)
                             and v["scorable_as_the_cover_check"] in (None, True)) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    B2["cover"].to_csv(out / "cover.csv", index=False)
    head = [f"# {registration} — the frozen trees (R87's LightGBM as R88 fitted it on F1+F2's members), scored once on F5's coin members (`ft2 allgbm confirm5`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(used)} features · fitted on {train_cells:,} cells · scored on {len(B2['names'])} names · "
            f"bars: maker {BAR_MAKER}, taker {BAR_TAKER}, one-sided t ≥ {T_ONE_SIDED}\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps({k: x for k, x in v.items() if k != "feature_names"}, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "read.md").write_text("\n".join(head + ["\n**The read is VOID: no IC was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    grid, day, z, y, names = B2["grid"], B2["day"], B2["z"], B2["y"], B2["names"]
    f = trees_score(model, B2["X"], B2["scorable"], cols)
    r = ic_row(f, z, day)
    zr = centre(z, ~np.isnan(f) & ~np.isnan(z))
    m_xs, se_xs, _ = hac(_ic_xs(pd.DataFrame(f), pd.DataFrame(zr), day), day_lags(HOLD))
    tenths = float(np.nanmean(_tenths(f, np.where(~np.isnan(f), y, np.nan)))) if len(grid) % PER_DAY == 0 else np.nan
    gate = {"model": "the frozen trees on F5's coins (the gate)", **r, "mde": MDE_K * r["se"] if np.isfinite(r["se"]) else np.nan, "ic_rank_per_bar": m_xs, "t_rank": m_xs / se_xs if se_xs else np.nan,
            "tenths_bps_a_leg": tenths, "verdict": verdict88(r["ic"], r["se"], r["t"])}
    old = set(universe.screen_symbols()) | set(universe.screen_symbols(universe.F34_MEMBERS_CSV)) if expect else set(names[::2])
    is_old = np.array([c in old for c in names])
    late = np.asarray(grid >= LATE_FROM)
    rows = [gate,
            {"model": f"described: coins that were members in F1–F4 ({int(is_old.sum())})", **ic_cells(f, z, day, np.broadcast_to(is_old[None, :], f.shape)), "verdict": "described"},
            {"model": f"described: coins new in 2026 ({int((~is_old).sum())})", **ic_cells(f, z, day, np.broadcast_to(~is_old[None, :], f.shape)), "verdict": "described"},
            {"model": "described: the blocks before 2026-07-02", **ic_row(f, z, day, ~late), "verdict": "described"},
            {"model": "described: the blocks from 2026-07-02", **ic_row(f, z, day, late), "verdict": "described"}]
    month = pd.Series(grid.strftime("%Y-%m"))
    by_month = pd.DataFrame([{"month": mth, **ic_row(f, z, day, (month == mth).to_numpy())} for mth in sorted(month.unique())])
    o = pd.DataFrame({"t": np.repeat(grid.to_numpy(), len(names)), "symbol": np.tile(np.asarray(names), len(grid)), "f": f.ravel(), "z": z.ravel()})
    o[~np.isnan(o["f"])].to_parquet(out / "forecast.parquet", index=False)
    pd.DataFrame(rows).to_csv(out / "models.csv", index=False)                    # the gate's row is on disk before the described second build
    (out / "validity.json").write_text(json.dumps({**v, "verdict": gate["verdict"], "ic": float(gate["ic"]), "se": float(gate["se"]), "t": float(gate["t"])}, indent=1, default=str))
    if conf:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "allgbm confirm5",
                      "params": json.dumps({"features": len(used), "model_md5": model_md5})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    print(f"{registration}: {gate['verdict']} — IC {gate['ic']:+.4f} (t {gate['t']:+.2f})", flush=True)
    cover2 = B2["cover"]
    del B2

    print("F5: all the members (described)…", flush=True)
    B3 = build(members_all, ("F5",), sources, end, F5_START, F5_GRIDS)
    f3 = trees_score(model, B3["X"], B3["scorable"], cols)
    coin = np.array([c in set(names) for c in B3["names"]])
    for label, cells in ((f"described: ALL {len(B3['names'])} members (peers: all)", None), ("described: the coin cells among all members", np.broadcast_to(coin[None, :], f3.shape)),
                         (f"described: the {int((~coin).sum())} stock / ETF / commodity names' cells", np.broadcast_to(~coin[None, :], f3.shape))):
        rows.append({"model": label, **ic_cells(f3, B3["z"], B3["day"], cells), "verdict": "described"})
    tab = pd.DataFrame(rows)
    tab.to_csv(out / "models.csv", index=False)
    show = lambda d, k=4: d.round(k).to_markdown(index=False)                    # noqa: E731
    md = head + [
        f"\n## The gate — **{gate['verdict']}**: the frozen trees' IC on F5's coins {gate['ic']:+.4f} (se {gate['se']:.4f}, t {gate['t']:+.2f}, MDE {gate['mde']:.4f}) on {int(gate['cells']):,} cells, "
        f"{int(gate['days'])} days; per-bar rank IC {gate['ic_rank_per_bar']:+.4f} (t {gate['t_rank']:+.2f}); tenths {gate['tenths_bps_a_leg']:+.1f} bps a leg a day before costs\n", show(tab), "\n",
        "\n## Described (decides nothing)\n", "\n### By month (the gate's cells)\n", show(by_month), "\n",
        "\n### Cover of each feature on F5's scorable coin cells\n", cover2.round(4).to_markdown(index=False), "\n"]
    (out / "read.md").write_text("\n".join(md))
    print(f"wrote {out}/", flush=True)
    return "\n".join(md)


# ---- R97: the frozen trees' FILE scored once, backward, on the screener's members before F1 ---------------------------------------------
REG97, NAME97 = "R97", "r97"
MODEL_FILE = Path(__file__).with_name("r89_model.txt")
MODEL_MD5 = "816b994c136fda82eb36ceca88580d36"
PRE_MD5 = "901782ce7a03fa4970c1dd471f31fd6b"
R97_SCORABLE = 714_084                                       # the cover check's count (output/allgbm/cover_pre, 2026-11-15)
R97_ABSENT = ("hl_gap24_dev",)                               # the registration's Features line: the only input without a cell
R97_YOUNG_DAYS = 180
R89_FEATURES = ["ret_15m", "ret_1h", "ret_4h", "ret_1d", "ret_1w", "relret_1h", "relret_4h", "relret_1d", "volratio_1h", "volratio_1d", "mom_4w", "mom_12w", "vol_4w", "maxd_4w",
                "funding_last", "funding_7d", "oi_chg_1d", "oi_chg_1w", "oi_turn", "global_ls", "global_ls_chg_1d", "top_ls", "top_vs_global", "taker_1d", "cbprem_dev", "cbprem_chg_1d",
                "krprem_dev", "spot_tb24_dev", "spot_sr24_dev", "mix_cnt24_dev", "mix_size24_dev", "hl_gap24_dev", "wiki_dev"]


def verdict97(ic: float, se: float, t: float, first: float, last: float) -> str:
    """R97 (A): R89's one-sided words with BOTH parts required positive."""
    if all(np.isfinite(x) for x in (ic, t, first, last)) and t >= T_ONE_SIDED and ic >= BAR_MAKER and first > 0 and last > 0:
        return "CONFIRMED AT THE TAKER BAR" if ic >= BAR_TAKER else "CONFIRMED"
    return "NOT CONFIRMED — CLOSED" if np.isfinite(ic) and np.isfinite(se) and ic + 1.96 * se < BAR_MAKER else "NOT CONFIRMED"


def rows_mask(rows: pd.DataFrame, names: list[str], starts: pd.DatetimeIndex, block: np.ndarray) -> np.ndarray:
    """bar × name: True where the bar lies in a block for which `rows` (block, symbol) holds that name."""
    pos = {c: i for i, c in enumerate(names)}
    has = np.zeros((len(starts), len(names)), dtype=bool)
    for b, s in zip(starts.get_indexer(pd.DatetimeIndex(rows["block"])), rows["symbol"].astype(str)):
        if b >= 0 and s in pos:
            has[b, pos[s]] = True
    return has[np.clip(block, 0, len(starts) - 1)] & (block >= 0)[:, None]


def confirm_pre(name: str = NAME97, sources: dict | None = None, members: str | None = None, model_file: Path | str | None = None, registration: str = REG97, expect: bool = True,
                book: bool = True) -> str:
    import hashlib
    import lightgbm as lgb
    from . import allbook
    from .horizon import _tenths
    from .universe import PRE_END, PRE_MEMBERS_CSV
    sources = SOURCES if sources is None else sources
    members, model_file = members or PRE_MEMBERS_CSV, Path(model_file or MODEL_FILE)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    conf = bt._guard(list(PRE_FOLDS), registration)                        # the pre-history: only under the registration, once; logged when (A)'s number exists
    md5 = lambda p: hashlib.md5(Path(p).read_bytes()).hexdigest()         # noqa: E731
    list_md5, model_md5 = md5(members), md5(model_file)
    model = lgb.Booster(model_file=str(model_file))                        # the FILE is the model: nothing is fitted here
    f0 = folds.bounds("F0", embargoed=False)[0]

    B = build(members, (), sources, PRE_END, PRE_START, PRE_GRIDS, span=PRE_SPAN)
    names_ = [k for _, k in B["src_of"]]
    cols = [i for i, k in enumerate(names_) if k not in DROP88]
    used = [names_[i] for i in cols]
    cov = B["cover"].set_index("feature")
    absent = [k for k in used if int(cov.loc[k, "cells"]) == 0]
    d_causal = _causal(B, sources)
    grid, M = B["grid"], B["M"]
    v = {"registration": registration, "folds_scored": list(PRE_FOLDS), "list_md5": list_md5, "list_as_registered": list_md5 == PRE_MD5 if expect else None, "model_md5": model_md5,
         "model_as_registered": model_md5 == MODEL_MD5 if expect else None, "model_features": int(model.num_feature()), "features": len(used), "feature_names": used,
         "same_names_as_r89": used == R89_FEATURES if expect else None, "features_without_a_cell": absent, "absent_as_registered": tuple(absent) == R97_ABSENT if expect else None,
         "max_abs_d_causal": d_causal, "names_scored": len(B["names"]), "blocks": int(len(np.unique(B["block"]))), "scorable_cells": int(B["scorable"].sum()),
         "scorable_as_the_cover_check": int(B["scorable"].sum()) == R97_SCORABLE if expect else None, "rows": int(len(grid)), "first": str(grid[0]), "last": str(grid[-1]),
         "span_as_registered": bool(grid[0] == PRE_SPAN[0] and grid[-1] == PRE_SPAN[1] - pd.Timedelta(hours=1)) if expect else None, "market_last_bar": str(M.index[-1]),
         "market_ends_before_F1": bool(M.index[-1] <= PRE_END), "names_as_registered": len(B["names"]) == 141 and len(np.unique(B["block"])) == 17 if expect else None,
         "bars": {"taker": BAR_TAKER, "maker": BAR_MAKER, "t_one_sided": T_ONE_SIDED}, "parts_split_at": str(f0)}
    # market_ends_before_F1: the index is the bar's CLOSE — the bar stamped at F1's first instant is 2023-04-30's last five minutes (R97's Void 1)
    v["status"] = "PASS" if (v["model_features"] == len(used) and d_causal in (None, 0.0) and v["market_ends_before_F1"]
                             and all(v[k] in (None, True) for k in ("list_as_registered", "model_as_registered", "same_names_as_r89", "absent_as_registered", "scorable_as_the_cover_check",
                                                                    "span_as_registered", "names_as_registered"))) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    B["cover"].to_csv(out / "cover.csv", index=False)
    head = [f"# {registration} — the frozen trees' FILE (R89's), scored once, backward, on the screener's members before F1 (`ft2 allgbm confirmpre`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(used)} features · scored on {len(B['names'])} names, {len(grid):,} hourly bars · "
            f"bars: maker {BAR_MAKER}, taker {BAR_TAKER}, one-sided t ≥ {T_ONE_SIDED} · the parts split at {f0:%Y-%m-%d}\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps({k: x for k, x in v.items() if k != "feature_names"}, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "read.md").write_text("\n".join(head + ["\n**The read is VOID: no forecast and no IC was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    day, z, y, names = B["day"], B["z"], B["y"], B["names"]
    f = trees_score(model, B["X"], B["scorable"], cols)
    r = ic_row(f, z, day)
    in_fp = np.asarray(grid < f0)
    p1, p2 = ic_row(f, z, day, in_fp), ic_row(f, z, day, ~in_fp)
    zr = centre(z, ~np.isnan(f) & ~np.isnan(z))
    m_xs, se_xs, _ = hac(_ic_xs(pd.DataFrame(f), pd.DataFrame(zr), day), day_lags(HOLD))
    tenths = float(np.nanmean(_tenths(f, np.where(~np.isnan(f), y, np.nan)))) if len(grid) % PER_DAY == 0 else np.nan
    gate = {"model": "(A) the frozen trees on the members before F1 (the gate)", **r, "mde": MDE_K * r["se"] if np.isfinite(r["se"]) else np.nan, "ic_FP": p1["ic"], "ic_F0": p2["ic"],
            "ic_rank_per_bar": m_xs, "t_rank": m_xs / se_xs if se_xs else np.nan, "tenths_bps_a_leg": tenths, "verdict": verdict97(r["ic"], r["se"], r["t"], p1["ic"], p2["ic"])}
    fitted = set(universe.screen_symbols()) if expect else set(names[::2])
    was = np.array([c in fitted for c in names])
    mem = B["mem"]
    young = rows_mask(mem[mem["age_days"] < R97_YOUNG_DAYS], names, B["starts"], B["block"]) if "age_days" in mem else np.zeros(f.shape, dtype=bool)
    rows = [gate,
            {"model": "described: the days in FP (to 2022-08-17)", **p1, "verdict": "described"}, {"model": "described: the days in F0 (from 2022-08-18)", **p2, "verdict": "described"},
            {"model": f"described: names that were F1+F2 members later ({int(was.sum())})", **ic_cells(f, z, day, np.broadcast_to(was[None, :], f.shape)), "verdict": "described"},
            {"model": f"described: names never fitted ({int((~was).sum())})", **ic_cells(f, z, day, np.broadcast_to(~was[None, :], f.shape)), "verdict": "described"},
            {"model": f"described: member rows under {R97_YOUNG_DAYS} days old at the block", **ic_cells(f, z, day, young), "verdict": "described"},
            {"model": "described: the older member rows", **ic_cells(f, z, day, ~young & B["cell"]), "verdict": "described"}]
    tab = pd.DataFrame(rows)
    month = pd.Series(grid.strftime("%Y-%m"))
    by_month = pd.DataFrame([{"month": mth, **ic_row(f, z, day, (month == mth).to_numpy())} for mth in sorted(month.unique())])
    o = pd.DataFrame({"t": np.repeat(grid.to_numpy(), len(names)), "symbol": np.tile(np.asarray(names), len(grid)), "f": f.ravel(), "z": z.ravel()})
    o[~np.isnan(o["f"])].to_parquet(out / "forecast.parquet", index=False)
    tab.to_csv(out / "models.csv", index=False)
    by_month.to_csv(out / "by_month.csv", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "verdict": gate["verdict"], "ic": float(gate["ic"]), "se": float(gate["se"]), "t": float(gate["t"]), "ic_FP": float(p1["ic"]), "ic_F0": float(p2["ic"])},
                                                  indent=1, default=str))
    if conf:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "allgbm confirmpre",
                      "params": json.dumps({"features": len(used), "model_md5": model_md5})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    print(f"{registration} (A): {gate['verdict']} — IC {gate['ic']:+.4f} (t {gate['t']:+.2f}; FP {p1['ic']:+.4f}, F0 {p2['ic']:+.4f})", flush=True)
    show = lambda d, k=4: d.round(k).to_markdown(index=False)                    # noqa: E731
    md = head + [
        f"\n## (A) the forecast — **{gate['verdict']}**: IC {gate['ic']:+.4f} (se {gate['se']:.4f}, t {gate['t']:+.2f}, MDE {gate['mde']:.4f}) on {int(gate['cells']):,} cells, {int(gate['days'])} days; "
        f"FP {p1['ic']:+.4f}, F0 {p2['ic']:+.4f}; per-bar rank IC {m_xs:+.4f} (t {gate['t_rank']:+.2f}); tenths {tenths:+.1f} bps a leg a day before costs\n", show(tab), "\n",
        "\n### By month (described)\n", show(by_month), "\n", "\n### Cover of each feature on the scorable cells\n", B["cover"].round(4).to_markdown(index=False), "\n"]
    (out / "read.md").write_text("\n".join(md))
    del B
    if not book:
        return "\n".join(md)

    a, b, mid = allbook.pre_span()
    try:
        g = allbook.forward(out / "forecast.parquet", name=allbook.NAME97, registration=registration, guard=False, start=a, end=b, mid=mid)
    except SystemExit:
        md += ["\n## (B) the taker's money — **VOID** (the book's validity failed: `output/allbook/r97/validity_book.json`); (A) stands\n"]
        (out / "read.md").write_text("\n".join(md))
        raise
    fills = pd.read_parquet(allbook.OUT / allbook.NAME97 / "fills.parquet")
    parts, by_why, bm = allbook.book_rows(fills, pd.date_range(a, b - pd.Timedelta(1, "ns"), freq="D"), mid)
    vb = json.loads((allbook.OUT / allbook.NAME97 / "validity_book.json").read_text())
    md += [f"\n## (B) the taker's money — **{g['verdict']}**: hedged net − {allbook.HEDGE_BPS:g} = {g['mean']:+.1f} bps a trade (se {g['se']:.1f}, t {g['t']:+.2f}; FP {g['first_half']:+.1f} / F0 {g['last_half']:+.1f}) "
           f"on {g['trades']} positions\n", "```\n", json.dumps(vb, indent=1, default=str), "\n```\n", "\n### The money's parts (bps a trade, described)\n", parts.round(2).to_markdown(index=False), "\n",
           "\n### By exit clause\n", by_why.round(2).to_markdown(index=False), "\n", "\n### By month\n", bm.round(2).to_markdown(index=False), "\n"]
    (out / "read.md").write_text("\n".join(md))
    print(f"wrote {out}/", flush=True)
    return "\n".join(md)


# ---- R98: the refit challenger for F6 — the same trees fitted ONCE on every member cell of F1 … F5 ---------------------------------------
REG98, NAME98 = "R98", "r98"
R98_CUT = pd.Timestamp("2026-09-15", tz="UTC")               # no training label ends at or after it
R98_LISTS = {"screen_members.csv": "0e55255d37412d3b63a021d3c8a732ab", "screen_members_f34.csv": "9625d74d2cd79b080de0d1b158095248", "screen_members_f5_coins.csv": R89_MD5["screen_members_f5_coins.csv"]}


def refit_parts() -> list[dict]:
    """The three builds of R98's Fit line, as the earlier reads built them."""
    from .universe import F34_MEMBERS_CSV, F5_COINS_CSV, MEMBERS_CSV
    return [{"tag": "F1+F2", "members": MEMBERS_CSV, "folds": folds.EXPLORATION, "end": None, "start": None, "grids": None},
            {"tag": "F3+F4", "members": F34_MEMBERS_CSV, "folds": CONF_FOLDS, "end": folds.bounds(CONF_FOLDS[-1])[1], "start": CONF_START, "grids": CONF_GRIDS},
            {"tag": "F5", "members": F5_COINS_CSV, "folds": ("F5",), "end": folds.bounds("F5")[1], "start": F5_START, "grids": F5_GRIDS}]


def train_cells(usable: np.ndarray, t_end: pd.DatetimeIndex, cut: pd.Timestamp) -> np.ndarray:
    """The usable cells whose label ends strictly before `cut`."""
    return usable & (t_end.asi8 < cut.value)[:, None]


def refit(name: str = NAME98, sources: dict | None = None, parts: list[dict] | None = None, registration: str = REG98, expect: bool = True) -> dict:
    """R98's fit: no statistic of the fit is computed — the file, its md5 and the cell counts only."""
    import hashlib
    import lightgbm as lgb
    sources = SOURCES if sources is None else sources
    parts = refit_parts() if parts is None else parts
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    conf = bt._guard([f for p in parts for f in p["folds"]], registration)    # F3, F4, F5: the fit is their one use under R98; a second fit is refused
    md5 = lambda p: hashlib.md5(Path(p).read_bytes()).hexdigest()         # noqa: E731
    lists = {Path(p["members"]).name: md5(p["members"]) for p in parts}
    f3_start = folds.bounds("F3")[0]
    Xs, ys, rep, used = [], [], [], None
    for p in parts:
        print(f"{p['tag']}: the cells…", flush=True)
        B = build(p["members"], p["folds"], sources, p["end"], p["start"], p["grids"])
        names_ = [k for _, k in B["src_of"]]
        cols = [i for i, k in enumerate(names_) if k not in DROP88]
        train = train_cells(B["usable"], B["t_end"], R98_CUT)
        rep.append({"part": p["tag"], "names": len(B["names"]), "scorable_cells": int(B["scorable"].sum()), "usable_cells": int(B["usable"].sum()), "train_cells": int(train.sum()),
                    "train_cells_with_label_ending_before_F3": int((train & (B["t_end"].asi8 < f3_start.value)[:, None]).sum()),
                    "train_cells_with_label_ending_at_or_after_the_cut": int((train & (B["t_end"].asi8 >= R98_CUT.value)[:, None]).sum()),
                    "feature_names": [names_[i] for i in cols], "max_abs_d_causal": _causal(B, sources), "first": str(B["grid"][0]), "last": str(B["grid"][-1])})
        Xs.append(B["X"][train][:, cols].astype(np.float32))
        ys.append(B["zres"][train])
        used = rep[-1]["feature_names"] if used is None else used
        del B
    v = {"registration": registration, "lists_md5": lists, "lists_as_registered": lists == R98_LISTS if expect else None, "parts": [{k: x for k, x in r.items() if k != "feature_names"} for r in rep],
         "same_names_as_r89_in_every_part": all(r["feature_names"] == R89_FEATURES for r in rep) if expect else all(r["feature_names"] == used for r in rep),
         "f12_cells_before_F3_as_r88": rep[0]["train_cells_with_label_ending_before_F3"] == R88_TRAIN_CELLS if expect else None,
         "f5_scorable_as_r89": rep[-1]["scorable_cells"] == R89_SCORABLE if expect else None,
         "no_label_at_or_after_the_cut": all(r["train_cells_with_label_ending_at_or_after_the_cut"] == 0 for r in rep), "causal": all(r["max_abs_d_causal"] in (None, 0.0) for r in rep),
         "train_cells": int(sum(r["train_cells"] for r in rep)), "cut": str(R98_CUT), "params": {k: x for k, x in PARAMS.items()}}
    v["status"] = "PASS" if (v["same_names_as_r89_in_every_part"] and v["no_label_at_or_after_the_cut"] and v["causal"]
                             and all(v[k] in (None, True) for k in ("lists_as_registered", "f12_cells_before_F3_as_r88", "f5_scorable_as_r89"))) else "FAIL"
    (out / "fit.json").write_text(json.dumps(v, indent=1, default=str))
    if v["status"] != "PASS":
        print(f"validity FAIL — no model is fitted; wrote {out}/fit.json", flush=True)
        raise SystemExit(2)
    gbm = lgb.LGBMRegressor(**{**PARAMS, "n_jobs": 8}).fit(np.concatenate(Xs), np.concatenate(ys))
    gbm.booster_.save_model(str(out / "model.txt"))
    v["model_md5"] = md5(out / "model.txt")
    v["fitted_at"] = f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC"
    (out / "fit.json").write_text(json.dumps(v, indent=1, default=str))
    if conf:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": v["fitted_at"], "registration": registration, "fold": conf, "strategy": "allgbm refit (the fit only, no statistic)",
                      "params": json.dumps({"features": len(used), "train_cells": v["train_cells"], "model_md5": v["model_md5"]})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    print(f"{registration}: fitted on {v['train_cells']:,} cells ({', '.join(str(r['train_cells']) for r in rep)}), model.txt md5 {v['model_md5']}; wrote {out}/", flush=True)
    return v
