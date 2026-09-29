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

`oibook` (a strategy, registration R21; `ft2 backtest oibook --universe screen`) trades the three open-interest features
the audit left nearest its bar, as one rank score, through the harness. `ft2 audit <run> --book` is its validity check.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import data, folds, screen, universe
from .ceiling import BAR, MDE_K, MIN_PAIRS, Z_CLIP, Z_TOP, _ic_xs, _shuffle_days, day_lags, hac
from .forecast import _derive

OUT = Path("output/audit")
FEATURES = ["funding_last", "funding_7d", "premium_1h", "premium_1d", "oi_chg_1d", "oi_chg_1w", "oi_turn", "global_ls", "global_ls_chg_1d", "top_ls",
            "top_vs_global", "taker_1d"]
OI = ["oi_chg_1d", "oi_chg_1w", "oi_turn"]      # what `oibook` trades (R21): the three R20 left nearest the bar
DRAWS = 200
Z_TOL = 1e-6                       # the audit's labels against the run's
GRID = pd.Timedelta("1h")          # the run's decision bars (grid 12)
H1, D1, W1 = 12, 288, 2016         # feature windows, in 5m bars
WARMUP = pd.Timedelta(days=9)      # bars loaded before the first cell: the longest window (1w) and its minimum
T_BAR, P_BAR, IC_CLOSED = 2.0, 0.05, 0.02


def features(idx: pd.DatetimeIndex, cols: list[str], dv: pd.DataFrame, end: pd.Timestamp, only: list[str] | None = None) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """`FEATURES` on the 5m decision times `idx` × `cols`; `dv` is the bars' dollar volume on the same index. An absent
    source leaves its features NaN and a note. `only`: build these and no others (the same code, the same numbers — a
    rule that trades three of them does not load the sources of the other nine)."""
    keys = [k for k in FEATURES if only is None or k in only]
    want = lambda *ks: any(k in keys for k in ks)                                       # noqa: E731
    empty = lambda: pd.DataFrame(np.nan, index=idx, columns=cols)                       # noqa: E731
    F, notes = {k: empty() for k in keys}, []

    def put(**kv):
        F.update({k: v for k, v in kv.items() if k in F})
    pos = lambda x: np.log(x.where(x > 0))                                              # noqa: E731
    a = idx[0] - pd.Timedelta(days=1)
    try:                                                     # funding: per 8 h, bps; usable from the bar after the funding time
        if want("funding_last", "funding_7d"):
            fu = data.load("funding_archive", symbols=cols)
            fu = fu[(fu["ts"] < end) & (fu["ts"] >= a - pd.Timedelta(days=8))]
            fw = (fu.assign(symbol=fu["symbol"].astype(str), r=fu["rate"] * 8.0 / fu["interval_h"] * 1e4).pivot(index="ts", columns="symbol", values="r").reindex(columns=cols))
            on = lambda x: x.reindex(idx.union(x.index)).ffill().reindex(idx).shift(1)      # noqa: E731
            put(funding_last=on(fw), funding_7d=on(fw.rolling("7D", min_periods=1).mean()))
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("funding_archive absent: funding_* skipped")
    try:                                                     # premium index: the bar that closed at t
        if want("premium_1h", "premium_1d"):
            pr = data.load("premium", symbols=cols)
            pr = pr[(pr["open_time"] + BAR <= end) & (pr["open_time"] >= a)]
            pw = pr.assign(symbol=pr["symbol"].astype(str), t=pr["open_time"] + BAR, p=pr["premium"] * 1e4).pivot(index="t", columns="symbol", values="p").reindex(index=idx, columns=cols)
            put(premium_1h=pw.rolling(H1, min_periods=int(H1 * 0.8)).mean(), premium_1d=pw.rolling(D1, min_periods=int(D1 * 0.8)).mean())
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("premium absent: premium_* skipped")
    try:                                                     # metrics, 5m: the row stamped ts is used from ts + 5 min
        if want(*FEATURES[4:]):
            m = data.load("metrics", columns=["symbol", "ts", "oi", "oi_value", "top_ls_sum", "global_ls", "taker_ratio"], symbols=cols)
            m = m[(m["ts"] < end) & (m["ts"] >= a)]
            m["symbol"] = m["symbol"].astype(str)
            wide = lambda c: m.pivot(index="ts", columns="symbol", values=c).shift(freq=BAR).reindex(index=idx, columns=cols).ffill(limit=3)      # noqa: E731
            if want("oi_chg_1d", "oi_chg_1w"):
                oi = pos(wide("oi"))
                put(oi_chg_1d=oi.diff(D1), oi_chg_1w=oi.diff(W1))
            if want("oi_turn"):
                put(oi_turn=pos(wide("oi_value")) - pos(dv.rolling(D1, min_periods=int(D1 * 0.8)).sum()))
            if want("global_ls", "global_ls_chg_1d", "top_ls", "top_vs_global"):
                g, tp = pos(wide("global_ls")), pos(wide("top_ls_sum"))
                put(global_ls=g, global_ls_chg_1d=g.diff(D1), top_ls=tp, top_vs_global=tp - g)
            if want("taker_1d"):
                put(taker_1d=pos(wide("taker_ratio")).rolling(D1, min_periods=int(D1 * 0.8)).mean())
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("metrics absent: oi_*, *_ls*, top_vs_global, taker_1d skipped")
    return {k: F[k].replace([np.inf, -np.inf], np.nan) for k in keys}, notes


def _day(ts: pd.DatetimeIndex) -> np.ndarray:
    return (ts.floor("D") - ts[0].floor("D")).days.to_numpy()


# ---- R21: the open-interest features as a book ------------------------------------------------------------------------------
def member_mask(mem: pd.DataFrame, cols: np.ndarray, ts: pd.DatetimeIndex) -> np.ndarray:
    """bar × pair: is the pair a member of the block the bar falls in (the latest block start at or before it)?"""
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    table = np.zeros((len(starts) + 1, len(cols)), dtype=bool)                   # the last row: before the first block, nobody
    b, j = starts.get_indexer(mem["block"]), pd.Index(cols).get_indexer(mem["symbol"])
    table[b[j >= 0], j[j >= 0]] = True
    return table[starts.searchsorted(ts, side="right") - 1]


class OIBook(bt.Strategy):
    """`oibook` (registration R21): R20's three open-interest features as one rank score, traded dollar-neutral.
    At an hourly decision bar, among the block's members with a close and all three features (≥ max(MIN_PAIRS, 2k)):
        s = r(oi_turn) − ½·[r(oi_chg_1d) + r(oi_chg_1w)],   r = the rank among them, as a share
    long the k highest, short the k lowest, one unit each; the i-th highest and the i-th lowest are one unit of the book
    (both legs or neither). No fit, no label. The features are `features`' own, attached by the harness (`needs`)."""
    name = "oibook"
    needs = ("oi",)

    def __init__(self, hold: int = 288, k: int = 6, grid: int = 12, members: str = ""):
        self.hold, self.k, self.grid = int(hold), int(k), int(grid)
        self.members = str(members)                              # "" = universe.MEMBERS_CSV
        self._mem: pd.DataFrame | None = None

    def score(self, M: bt.Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        if self._mem is None:
            self._mem = universe.members(self.members or None)
        X, idx = M.extra["oi"], M.index
        grid = (idx.minute == 0) & (idx.second == 0) if self.grid == 12 else (np.arange(len(idx)) % self.grid == 0)
        ts = idx[grid & (idx >= a) & (idx < b)]
        cols = list(M.columns)
        f = {k: X[k].reindex(index=ts, columns=cols) for k in OI}
        ok = M.close.loc[ts].notna() & member_mask(self._mem, np.asarray(cols, dtype=str), ts)
        for x in f.values():
            ok &= x.notna()
        r = {k: x.where(ok).rank(axis=1, pct=True) for k, x in f.items()}
        s = r["oi_turn"] - 0.5 * (r["oi_chg_1d"] + r["oi_chg_1w"])
        return s.where(ok.sum(axis=1) >= max(MIN_PAIRS, 2 * self.k), axis=0)

    def decide(self, M: bt.Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        s = self.score(M, a, b)
        rl, rh = s.rank(axis=1, method="first"), s.rank(axis=1, method="first", ascending=False)
        lo, hi = rl <= self.k, rh <= self.k
        d = bt.decisions_from(hi.astype(float) - lo.astype(float), a, b, signal=s,
                              why=f"open interest: rank of oi_turn − ½(oi_chg_1d + oi_chg_1w) among the block's members, {self.k} a side")
        slot = rh.where(hi, rl).to_numpy()[s.index.get_indexer(d["t"]), s.columns.get_indexer(d["symbol"])]      # 1 … k on both sides
        return d.assign(group=M.index.get_indexer(d["t"]) * self.k + slot.astype(int) - 1)


STRATEGIES = {OIBook.name: OIBook}


def book_check(run: str, members: str | None = None) -> dict:
    """R21's validity, read before any money: the decisions of a run sit on the hourly grid and on members of their
    block, and the accepted book is made of whole units — one long and one short leg each."""
    run_dir = bt.OUT / run
    meta = json.loads((run_dir / "meta.json").read_text())
    d = pd.read_parquet(run_dir / "decisions.parquet")
    mem = universe.members(members or meta["params"].get("members") or None)
    t, cols = pd.DatetimeIndex(d["t"]), np.asarray(sorted(set(d["symbol"]) | set(mem["symbol"])), dtype=str)
    is_mem = member_mask(mem, cols, t)[np.arange(len(d)), pd.Index(cols).get_indexer(d["symbol"])] if len(d) else np.zeros(0, dtype=bool)
    acc = d[d["accepted"]]
    u = acc.groupby("group")["side"].agg(["size", "sum"])
    v = {"decisions": len(d), "accepted": len(acc), "off_grid": int(((t.minute != 0) | (t.second != 0)).sum()), "not_a_member": int((~is_mem).sum()),
         "units": len(u), "broken_units": int(((u["size"] != 2) | (u["sum"] != 0)).sum()), "accepted_long": int((acc["side"] > 0).sum()),
         "accepted_short": int((acc["side"] < 0).sum()), "names_traded": int(acc["symbol"].nunique())}
    v["status"] = "PASS" if len(acc) and not (v["off_grid"] or v["not_a_member"] or v["broken_units"]) and v["accepted_long"] == v["accepted_short"] else "FAIL"
    (run_dir / "book_check.json").write_text(json.dumps(v, indent=1))
    return v


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


def frame(run: str, members: str | None = None) -> dict:
    """The scored cells of a `transferbook` run on their hourly grid, the labels rebuilt here from the candles, and the
    validity of that: the labels are the run's on every cell. R20's set-up; R22 (`horizon.py`) reads the same cells."""
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
    sig = _derive(M.close.loc[idx, names])["sig"]["1w"]
    sig_h = sig * np.sqrt(hold)
    z = (bt.labels(M, hold, latency).loc[idx, names] / sig_h.where(sig_h > 0)).clip(-Z_CLIP, Z_CLIP)
    t5 = pd.Series(idx, index=idx)
    scored = np.zeros(len(idx), dtype=bool)
    for f in fold_names:
        scored |= folds.mask(t5, f).to_numpy()
    grid = idx[scored & (idx.minute == 0) & (idx.second == 0)]

    # validity: the labels rebuilt here are the run's, on the run's cells
    zi = z.to_numpy()[idx.get_indexer(o["t"]), pd.Index(names).get_indexer(o["symbol"])]
    dz = np.abs(zi - o["z"].to_numpy())
    on_grid = bool(pd.DatetimeIndex(o["t"]).isin(grid).all())
    v = {"status": "PASS" if on_grid and np.isfinite(dz).all() and dz.max() <= Z_TOL else "FAIL", "cells": len(o), "names": len(names),
         "cells_off_grid": int((~pd.DatetimeIndex(o["t"]).isin(grid)).sum()), "cells_without_label": int((~np.isfinite(dz)).sum()), "max_abs_dz": float(np.nanmax(dz))}
    cell = o.assign(one=1.0).pivot(index="t", columns="symbol", values="one").reindex(index=grid, columns=names).notna()
    return {"run_dir": run_dir, "meta": meta, "fold_names": fold_names, "hold": hold, "latency": latency, "end": end, "M": M, "o": o, "names": names, "idx": idx,
            "sig": sig, "z": z, "grid": grid, "cell": cell, "validity": v}


def run(run: str, draws: int = DRAWS, members: str | None = None, seed: int = 0, jobs: int = 4) -> str:
    from joblib import Parallel, delayed
    A = frame(run, members)
    run_dir, fold_names, hold, latency, end, M, o, names, idx, z, grid, cell, v = (A[k] for k in (
        "run_dir", "fold_names", "hold", "latency", "end", "M", "o", "names", "idx", "z", "grid", "cell", "validity"))
    lags, day = day_lags(hold), _day(grid)
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


# ---- R24: several `oibook` runs read as one book ------------------------------------------------------------------------------
POOL_SKIP = ("2022-05", "2022-11")      # described: the pooled net without the trades decided in these calendar months
POOL_SPLIT = {"FP": pd.Timestamp("2022-08-17", tz="UTC")}     # described: a run that reads the pre-history is shown in R23's two halves
POOL_TOP, REPRICE_TOL = 5, 1e-9


def pool_verdict(r: dict) -> str:
    """R24's gate, on the taker book as priced, the samples pooled."""
    if r["net"] > 0 and r["hedged_net"] > 0 and r["flip_p"] <= P_BAR and r["gross_positive_in_each"]:
        return "CANDIDATE"
    return "CLOSED" if r["net_hi"] < 0 and r["maker_net"] <= 0 else "NOT FUNDED"


def confirm_verdict(r: dict) -> str:
    """R25's gate, on the taker book as priced: the per-sample sign is not in it (registered)."""
    if r["net"] > 0 and r["hedged_net"] > 0 and r["flip_p"] <= P_BAR:
        return "CONFIRMED"
    return "CLOSED" if r["net_hi"] < 0 and r["maker_net"] <= 0 else "NOT CONFIRMED"


BESIDE = ("r24_oibook_7d_pre", "r24_oibook_7d_f12")     # R25, described: the exploration runs whose saved fills are pooled beside the confirmation's


def _pooled_p(nulls: list[pd.DataFrame], exec_: str, kind: str, real: float) -> dict:
    """The null pooled draw by draw: each run's draw weighted by its trades."""
    x = pd.concat([n[(n["exec"] == exec_) & (n["kind"] == kind)] for n in nulls], ignore_index=True).dropna(subset=["net"])
    g = x.assign(w=x["net"] * x["trades"]).groupby("draw").agg(w=("w", "sum"), n=("trades", "sum"), runs=("net", "size"))
    d = (g["w"] / g["n"])[g["runs"] == len(nulls)]
    return {"draws": len(d), "mean": float(d.mean()), "sd": float(d.std()), "p95": float(d.quantile(0.95)), "p": (1 + int((d >= real).sum())) / (len(d) + 1)}


def pool(runs: list[str], name: str = "r24_pool", confirm: bool = False) -> str:
    """The fills of several `oibook` runs as ONE book (registration R24): the harness's statistics on the pooled fills,
    the flip null pooled draw by draw, costs doubled by re-pricing each run's own decisions. Validity first."""
    from . import ceiling
    out = bt.OUT / name
    out.mkdir(parents=True, exist_ok=True)
    F, nulls, days, val, holds = {"taker": [], "maker": [], "taker_x2": []}, [], [], [], set()
    for run in runs:
        rd = bt.OUT / run
        meta = json.loads((rd / "meta.json").read_text())
        chk = json.loads((rd / "book_check.json").read_text()) if (rd / "book_check.json").exists() else {"status": "NOT RUN"}
        fold_names, p = meta["folds"], meta["params"]
        end = folds.bounds(fold_names[-1])[1]
        M = bt.market(meta["pairs"], end, bt.PRE_START if "FP" in fold_names else ceiling.START)
        dec = pd.read_parquet(rd / "decisions.parquet")
        mem = universe.members(p.get("members") or None)
        first = pd.Timestamp(mem["block"].min())
        same = lambda a, b: float(np.nanmax(np.abs(a.to_numpy() - b.to_numpy()))) if len(a) == len(b) and (a.isna() == b.isna().to_numpy()).all() else np.inf      # noqa: E731
        f1 = pd.read_parquet(rd / "fills_taker.parquet")
        re1 = bt.price(dec, M, bt.load_costs(M.index, M.columns, end, 1.0), "taker", meta["taker_bps"], meta["maker_bps"], meta["latency_bars"])
        f2 = bt.price(dec, M, bt.load_costs(M.index, M.columns, end, 2.0), "taker", meta["taker_bps"], meta["maker_bps"], meta["latency_bars"])
        priced = f1.dropna(subset=["net_bps"])
        v = {"run": run, "folds": "+".join(fold_names), "hold": int(p["hold"]), "k": int(p["k"]), "book_check": chk["status"], "decisions": len(dec), "accepted": int(dec["accepted"].sum()),
             "first_decision": str(dec["t"].min()), "decisions_before_the_first_block": int((dec["t"] < first).sum()), "priced": len(priced),
             "unpriced": int(len(f1) - len(priced)), "last_exit": str(priced["exit_t"].max()), "exits_at_or_after_end": int((priced["exit_t"] >= end).sum()),
             "reprice_max_abs_diff": same(f1["net_bps"], re1["net_bps"]), "cost_mult": float(meta["cost_mult"])}
        v["status"] = "PASS" if chk["status"] == "PASS" and not (v["decisions_before_the_first_block"] or v["exits_at_or_after_end"]) and v["priced"] > 0 \
            and v["reprice_max_abs_diff"] <= REPRICE_TOL and v["cost_mult"] == 1.0 else "FAIL"
        val.append(v)
        holds.add(int(p["hold"]))
        lab = lambda f: f.assign(run=run, part=np.where(pd.DatetimeIndex(f["t"]) < POOL_SPLIT["FP"], run + " H1", run + " H2") if "FP" in fold_names else      # noqa: E731
                                 (run + " " + f["fold"].astype(str)) if confirm else run)
        F["taker"].append(lab(f1)), F["maker"].append(lab(pd.read_parquet(rd / "fills_maker.parquet"))), F["taker_x2"].append(lab(f2))
        nulls.append(pd.read_parquet(rd / "null.parquet"))
        days.append(bt.scored_days(fold_names, M.index[-1]))
        del M
    ok = all(v["status"] == "PASS" for v in val) and len(holds) == 1 and len({(v["hold"], v["k"]) for v in val}) == 1
    (out / "validity.json").write_text(json.dumps({"status": "PASS" if ok else "FAIL", "runs": val}, indent=1))
    if not ok:
        raise SystemExit(f"validity FAIL, no money number was read: {val}")
    hold = holds.pop()
    days = days[0].append(days[1:]).unique().sort_values() if len(days) > 1 else days[0]
    F = {k: pd.concat(v, ignore_index=True) for k, v in F.items()}
    t = F["taker"]
    month = pd.DatetimeIndex(t["t"]).tz_localize(None).to_period("M").astype(str)
    rows = [{"exec": "taker", "scope": "pooled", **bt.summarize(t, days, hold)}, {"exec": "maker", "scope": "pooled", **bt.summarize(F["maker"], days, hold)},
            {"exec": "taker, costs doubled", "scope": "pooled", **bt.summarize(F["taker_x2"], days, hold)},
            {"exec": "taker", "scope": f"pooled without {', '.join(POOL_SKIP)}", **bt.summarize(t[~np.isin(month, list(POOL_SKIP))], days, hold)}]
    rows += [{"exec": "taker", "scope": r, **bt.summarize(t[t["run"] == r], days, hold)} for r in runs]
    rows += [{"exec": "taker", "scope": r, **bt.summarize(t[t["part"] == r], days, hold)} for r in sorted(set(t["part"]) - set(runs))]
    rows += [{"exec": "taker", "scope": k, **bt.summarize(t[t["side"] == s], days, hold)} for k, s in bt.SIDES.items()]
    if confirm:                                               # described: the exploration runs' saved fills beside this one's
        ex, ex_days = [t], [days]
        for r in BESIDE:
            if (bt.OUT / r / "fills_taker.parquet").exists() and r not in runs:
                ex.append(pd.read_parquet(bt.OUT / r / "fills_taker.parquet"))
                ex_days.append(bt.scored_days(m_ := json.loads((bt.OUT / r / "meta.json").read_text())["folds"], folds.bounds(m_[-1])[1] - bt.BAR))
        if len(ex) > 1:
            rows.append({"exec": "taker", "scope": f"with {', '.join(BESIDE)} (exploration)", **bt.summarize(pd.concat(ex, ignore_index=True), ex_days[0].append(ex_days[1:]).unique().sort_values(), hold)})
    rows += [{"exec": "taker, costs doubled", "scope": r, **bt.summarize(F["taker_x2"][F["taker_x2"]["run"] == r], days, hold)} for r in runs]
    rows += [{"exec": "maker", "scope": r, **bt.summarize(F["maker"][F["maker"]["run"] == r], days, hold)} for r in runs]
    tab = pd.DataFrame(rows)
    a = tab.iloc[0]
    flip, shuf = (_pooled_p(nulls, "taker", k, float(a["net"])) for k in ("flip", "shuffle"))
    flip_m = _pooled_p(nulls, "maker", "flip", float(tab.iloc[1]["net"]))
    gross_each = {r: float(tab[(tab["exec"] == "taker") & (tab["scope"] == r)]["gross"].iloc[0]) for r in runs}
    g = {"net": float(a["net"]), "net_lo": float(a["net_lo"]), "net_hi": float(a["net_hi"]), "net_mde": float(a["net_mde"]), "hedged_net": float(a["hedged_net"]),
         "gross": float(a["gross"]), "flip_p": flip["p"], "gross_positive_in_each": bool(all(x > 0 for x in gross_each.values())), "maker_net": float(tab.iloc[1]["net"])}
    g["verdict"] = confirm_verdict(g) if confirm else pool_verdict(g)
    pr = t.dropna(subset=["net_bps"])
    by = pr.groupby("symbol")["net_bps"].sum().sort_values()
    op = pd.DataFrame([{"run": v["run"], "trades": v["priced"], "unpriced": v["unpriced"], **dict(zip(("max_open", "avg_open"), (json.loads((bt.OUT / v["run"] / "meta.json").read_text())[k]
                                                                                                                         for k in ("max_open", "avg_open"))))} for v in val])
    show = lambda df, k=2: df.round(k).to_markdown(index=False)                         # noqa: E731
    cols = ["exec", "scope", "trades", "unpriced", "trades_per_day", "hit", "gross", "hedged", "fee", "other_cost", "funding", "net", "net_lo", "net_hi", "net_mde", "hedged_net",
            "hedged_net_lo", "hedged_net_hi"]
    md = [f"# The open-interest score as a priced book at a {hold}-bar hold ({'R25, the confirmation read' if confirm else 'R24'}) — {', '.join(f'`{r}`' for r in runs)} pooled (`ft2 audit --pool`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(pr):,} priced trades on {pr['symbol'].nunique()} names, {len(days)} days in the folds read\n",
          "\nWords: a *trade* is one position in one name, opened an hour after the ranking was read and closed 7 days later; the book always opens a bought and a sold name "
          "together. *gross*: what a trade earned before costs, in bps (0.01 %) of the position — 1 bps is 1 USDT on 10,000. *hedged*: the same against the move of the other "
          "names. *fee*: the exchange's fee for getting in and out. *other cost*: spread and price impact, estimated from the candles (these names have no recorded tape). "
          "*funding*: what the position paid (−) or received (+) while open. *net* = gross − fee − other cost + funding, with its interval; *MDE*: the smallest net this "
          "sample could have shown. *flip p*: the share of books that kept every trade but chose the direction of each day by a coin and did at least as well — 0.05 or "
          "less is the bar. *maker*: the same trades entered with resting orders instead of crossing the spread.\n",
          "\n## Validity\n", f"\n**{'PASS' if ok else 'FAIL'}**\n", show(pd.DataFrame(val), 12), "\n",
          "\n## The gate — the taker book as priced, the samples pooled\n",
          f"\n**{g['verdict']}**: net {g['net']:+.2f} [{g['net_lo']:+.2f}, {g['net_hi']:+.2f}] (MDE {g['net_mde']:.1f}), hedged net {g['hedged_net']:+.2f}, gross {g['gross']:+.2f}; "
          f"flip null {flip['mean']:+.2f} ± {flip['sd']:.2f}, one in twenty {flip['p95']:+.2f}, **flip p {flip['p']:.3f}** ({flip['draws']} draws); gross per sample: "
          f"{', '.join(f'{k} {x:+.2f}' for k, x in gross_each.items())}; maker net {g['maker_net']:+.2f} (flip p {flip_m['p']:.3f}). Shuffle null (reported, does not decide): "
          f"{shuf['mean']:+.2f} ± {shuf['sd']:.2f}, p {shuf['p']:.3f}.\n",
          "\nGate: CONFIRMED if net > 0, hedged net > 0 and flip p ≤ 0.05; CLOSED if the net interval's upper end < 0 and the maker net ≤ 0; else NOT CONFIRMED.\n" if confirm else
          "\nGate: CANDIDATE if net > 0, hedged net > 0, flip p ≤ 0.05 and gross > 0 in each sample; CLOSED if the net interval's upper end < 0 and the maker net ≤ 0; else NOT FUNDED.\n",
          "\n## The rows\n", show(tab[cols]), "\n",
          "\n## Positions\n", show(op), "\n",
          "\n## Names\n", f"\nThe net summed over trades is {by.sum():+,.0f} bps on {len(by)} names, {int((by > 0).sum())} of them positive; the {POOL_TOP} best "
          f"{by.tail(POOL_TOP).sum():+,.0f} ({', '.join(x.replace('USDT', '') for x in by.tail(POOL_TOP).index[::-1])}), the {POOL_TOP} worst {by.head(POOL_TOP).sum():+,.0f} "
          f"({', '.join(x.replace('USDT', '') for x in by.head(POOL_TOP).index)}).\n"]
    (out / "pool.md").write_text("\n".join(md))
    tab.to_csv(out / "pool.csv", index=False)
    (out / "gate.json").write_text(json.dumps({**g, "flip": flip, "flip_maker": flip_m, "shuffle": shuf, "gross_each": gross_each}, indent=1))
    return "\n".join(md)
