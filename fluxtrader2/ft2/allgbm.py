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
    F, _ = audit.features(M.index, list(M.columns), M.dv, ceiling.END)
    return {k: F[k].reindex(index=grid, columns=names) for k in audit.FEATURES}


def src_book(M, grid, names):
    from . import book_ext
    F = book_ext.features_depth(M.index, list(M.columns), ceiling.END)
    return {k: F[k].reindex(index=grid, columns=names) for k in (book_ext.RAW, book_ext.DM)}


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
    G, _ = sx.grids_spot(kept, spot.PARQUET, cx.MEMBERS_SLICES, cx.MEMBERS_START, ceiling.END)
    return {k: cx.to_panel(G[sx.GRID_OF[k]], grid, names) for k in (sx.TB24, sx.SR24)}


def src_mix(M, grid, names):
    from . import cb_ext as cx, mix, mix_ext as mx, spot, spot_ext as sx
    kept = [s for s in sx.r68_list()["kept"] if s in names]
    G, _ = mx.grids_mix(kept, mix.PARQUET, spot.PARQUET, cx.MEMBERS_START, ceiling.END)
    return {k: cx.to_panel(G[k], grid, names) for k in (mx.CNT, mx.SIZE)}


def src_hl(M, grid, names):
    from . import cb_ext as cx, hl, hl_ext as hx
    kept = [s for s in hx.r69_list()["kept"] if s in names]
    G, _, _ = hx.grids_hl(kept, hl.PARQUET, hl.BN_PARQUET, cx.MEMBERS_START, ceiling.END)
    F = cx.to_panel(G[hx.GRID_OF[hx.GAP]], grid, names)
    return {hx.GAP: F.where(np.broadcast_to(np.asarray(grid >= hx.SCORED_FROM)[:, None], F.shape))}        # nothing before the audit's cover (2023-08)


def src_wiki(M, grid, names):
    from . import wiki, wiki_ext as wx
    kept = [s for s in wx.names_r72()["names"] if s in names]
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
def run(name: str = NAME, members: str | None = None, jobs: int = 4, sources: dict | None = None, fold_names=None) -> str:
    sources = SOURCES if sources is None else sources
    fold_names = list(fold_names or folds.EXPLORATION)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    mem = universe.members(members)
    names = universe.screen_symbols(members)
    print("market…", flush=True)
    M = bt.market(names, ceiling.END)
    names = [c for c in names if c in M.columns]
    idx = M.index
    t5 = pd.Series(idx, index=idx)
    scored = np.zeros(len(idx), dtype=bool)
    for f_ in fold_names:
        scored |= folds.mask(t5, f_).to_numpy()
    grid = idx[scored & (idx.minute == 0) & (idx.second == 0)]
    day = (grid.floor("D") - grid[0].floor("D")).days.to_numpy()
    cell = audit.member_mask(mem, np.asarray(names), grid)
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    block = np.searchsorted(starts.asi8, grid.asi8, side="right") - 1
    t_end = grid + pd.Timedelta(minutes=5 * (bt.LATENCY + HOLD))
    grp = np.array([i % GROUPS for i in range(len(names))])                       # R53's: the sorted member names, every fourth

    print("the label…", flush=True)
    from . import forecast
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
    cov = pd.DataFrame(cover)
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
