"""P8 — the screener (PLAN §4 P8, registration R18 in §8).

PLAN §0's goal has two halves: a model that trades names it was not trained on, and a screener that says which names to
hand it. R14 and R16 measured the first half among the twelve; this module measures both on names the model never saw.

`transferbook` (a strategy, through the harness like any other)
    ONE ridge, `forecast.RidgeBook`'s in every respect (features, label, grid, RidgeCV, decision rule, sizing), fitted on
    the TRAINING names only — the twelve — and scoring every other name that is a MEMBER of the block's universe
    (`universe.members`: the block's top names by trailing volume, the training names left out). Two things differ from
    `RidgeBook`, both because the panel now holds names that are not peers of the fit:
      relative features   a name's return minus the mean return of the TRAINING names present (≥ MIN_PAIRS) — the market
                          as the model knows it, and the one a live host always has. For a training name this is
                          `RidgeBook`'s feature on the twelve, so the model IS R13 B's in-pair model, to the bit.
      what is traded      members only. A training name is forecast (in pair) and recorded with group 1 so that the read
                          can check the model against R13 B's forecasts; it is never traded here.
    `RidgeBook` itself is not touched: it is the class the serve host runs.

`read` (`ft2 screen <run>`) → output/screen/<run>/screen.md
    validity   the training names' forecasts against a reference run's forecast.parquet (R13 B): equal, or the read is void.
    transfer   the IC of the forecast on the members' cells — `ceiling._ic_pooled` of ẑ with the realised z minus the mean
               over the members present at the bar (≥ MIN_PAIRS), t clustered by day — pooled and per fold.
    screens    per characteristic (`universe.CHARACTERISTICS`), the same IC inside the block's top, middle and bottom third
               of members, and the SPREAD top − bottom (each day's share differenced, t clustered by day). Null: random
               STATIC thirds — every name draws one score for the whole sample and the block's members are cut by it; four
               such screens a draw, the largest spread t kept. Static, because a name's characteristic persists, and a third
               that keeps its names has the widest spread a meaningless screen can have. The family-wise p is the share of
               draws whose largest t is at least the real screens' largest.
    money      the book re-run on the top third's name-blocks only (`backtest.accept` on the run's own decisions, so one
               position per pair holds inside the screened book), priced as the harness prices, with the flip null; and
               once more with spread and impact doubled (most members are priced by the candle proxy).

`read(..., hindsight=<csv>)` (`ft2 screen <run> --hindsight`, registration R19) → output/screen/<run>_hindsight/screen.md
    The same cells, cut by ONE screen that uses hindsight on purpose (`universe.HINDSIGHT`: how much the name is traded in
    2026). It can never be traded; it asks whether the forecast looks skilled where the names are chosen knowing the
    future. The random static screens are drawn five at a time — the family counts R18's four. Added to the read: the
    bottom third's book, the part of each third's IC that is the product of the two means (a forecast that leans one
    way on names that drift that way), and the top third's cells split by R18's `young`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import folds, universe
from .ceiling import MIN_PAIRS, Z_CLIP, _ic_pooled, basket, day_lags, dir_features, hac
from .forecast import LOOKBACK, RidgeBook, _cells, _derive

OUT = Path("output/screen")
REFERENCE = Path("output/backtest/r13_ridgebook_1d_inpair12")
F_TOL = 1e-6                 # bps: the training names' forecasts against the reference run's
DRAWS = 200
SCORED, TRAIN = 0, 1         # `group` in forecast.parquet
HINDSIGHT_SUFFIX = "_hindsight"


class TransferBook(RidgeBook):
    name = "transferbook"

    def __init__(self, hold: int = 288, min_bps: float = 15.0, cap: float = 2.0, grid: int = 12, min_pairs: int = 5, train: str = "", members: str = ""):
        super().__init__(hold=hold, min_bps=min_bps, cap=cap, groups=1, grid=grid, min_pairs=min_pairs, holdout=False, features="candle")
        from .__main__ import PAIRS
        self.train = str(train)                              # "" = the twelve; else names joined by commas (the tests)
        self.members = str(members)                          # "" = universe.MEMBERS_CSV
        self._train = self.train.split(",") if self.train else list(PAIRS)
        self._mem: pd.DataFrame | None = None

    # ---- features: RidgeBook._ensure, the relative ones against the training names' mean ------------------------------
    def _ensure(self, M: bt.Market) -> None:
        idx = M.index
        g = np.flatnonzero(self._grid(idx))
        missing = [p for p in g if idx[p] not in self._pos]
        if not missing:
            return
        start = max(int(missing[0]) - LOOKBACK, 0)
        D = _derive(M.close.iloc[start:])
        F = dir_features(D)
        tr = [c for c in M.columns if c in self._train]
        for k in [k for k in F if k.startswith("relret_")]:
            own = F["ret_" + k.split("_", 1)[1]]
            F[k] = own.sub(basket(own[tr]), axis=0)
        X, S = _cells(F, D["sig"]["1w"])
        X[~np.isfinite(X)] = np.nan
        for p in missing:
            self._pos[idx[p]] = len(self._ts)
            self._ts.append(idx[p])
            self._X.append(X[p - start])
            self._S.append(S[p - start])

    # ---- fit: one ridge, on the training names' rows ---------------------------------------------------------------------
    def fit(self, M: bt.Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        if self._last_now is not None and now <= self._last_now:
            self._walks += 1
        self._last_now = now
        self._ensure(M)
        ts = y.index[self._grid(y.index)]
        ts = ts[np.array([t in self._pos for t in ts], dtype=bool)]
        self._models = {0: None}
        if not len(ts):
            return
        tr = np.isin(np.asarray(M.columns, dtype=str), self._train)
        X, S = self._rows(ts)
        X, S = X[:, tr, :], S[:, tr]
        sig_h = np.where(S > 0, S, np.nan) * np.sqrt(self.hold)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.clip(y.loc[ts].to_numpy()[:, tr] / sig_h, -Z_CLIP, Z_CLIP)
        self._sigma_ref = float(np.nanmedian(sig_h))
        n = (~np.isnan(z)).sum(1, keepdims=True)
        mean = np.where(n >= self.min_pairs, np.nansum(z, 1, keepdims=True) / np.maximum(n, 1), np.nan)
        self._models[0] = self._ridge(X.reshape(-1, self.n_feat), (z - mean).ravel())

    # ---- decide: members only ---------------------------------------------------------------------------------------------
    def _member_mask(self, cols: np.ndarray, ts: pd.DatetimeIndex) -> np.ndarray:
        """bar × pair: is the pair a member of the block the bar falls in (the latest block start at or before it)?"""
        if self._mem is None:
            self._mem = universe.members(self.members or None)
        starts = pd.DatetimeIndex(sorted(self._mem["block"].unique()))
        table = np.zeros((len(starts) + 1, len(cols)), dtype=bool)               # the last row: before the first block, nobody
        b, j = starts.get_indexer(self._mem["block"]), pd.Index(cols).get_indexer(self._mem["symbol"])
        table[b[j >= 0], j[j >= 0]] = True
        table[:, np.isin(cols, self._train)] = False
        return table[starts.searchsorted(ts, side="right") - 1]

    def decide(self, M: bt.Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        ts, f_all, sig_h, _ = self._forecast(M, a, b)                            # groups = 1: the one model scores every column
        cols = np.asarray(M.columns, dtype=str)
        mem = self._member_mask(cols, ts) if len(ts) else np.zeros(f_all.shape, dtype=bool)
        f = np.where(mem, f_all, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            on = np.abs(f) >= self.min_bps
            size = np.clip((np.abs(f) / self.min_bps) * (self._sigma_ref / sig_h) ** 2, 0.25, self.cap)
        side = pd.DataFrame(np.where(on, np.sign(f) * size, 0.0), index=ts, columns=M.columns)
        if self._walks == 0 and len(ts):
            tr = np.repeat(np.isin(cols, self._train)[None, :], len(ts), 0)
            keep = (mem | tr).ravel()
            self._oos.append(pd.DataFrame({"t": np.repeat(ts, len(cols)), "symbol": np.tile(cols, len(ts)), "group": np.where(tr, TRAIN, SCORED).ravel(),
                                           "f_bps": f_all.ravel(), "sigma_h": sig_h.ravel(), "f_ref_bps": np.nan})[keep])
        return bt.decisions_from(side, a, b, signal=pd.DataFrame(f, index=ts, columns=M.columns),
                                 why=f"ridge fitted on the training names, forecast vs peers ≥ {self.min_bps:g} bps, member of the block's universe")


STRATEGIES = {TransferBook.name: TransferBook}


# ---- the read ---------------------------------------------------------------------------------------------------------------
def _daily(A: tuple[np.ndarray, np.ndarray, np.ndarray], use: np.ndarray, nd: int) -> np.ndarray:
    """Each day's share of the pooled IC of the cells `use` picks from A = (ẑ, z residual, day), over `nd` days."""
    if not use.any():
        return np.full(nd, np.nan)
    x = _ic_pooled(A[0][use], A[1][use], A[2][use], min_cells=1)
    return np.concatenate([x, np.full(nd - len(x), np.nan)])


def _arrays(o: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return o["zhat"].to_numpy(), o["zres"].to_numpy(), o["day"].to_numpy()


def _ic(A, use: np.ndarray, nd: int, lags: int) -> dict:
    m, se, n = hac(_daily(A, use, nd), lags)
    return {"cells": int(use.sum()), "days": n, "ic": m, "se": se, "t": m / se if se else np.nan}


def _spread(A, top: np.ndarray, bottom: np.ndarray, nd: int, lags: int) -> dict:
    m, se, n = hac(_daily(A, top, nd) - _daily(A, bottom, nd), lags)
    return {"days": n, "spread": m, "se": se, "t": m / se if se else np.nan, "mde": bt.MDE_K * se if se else np.nan}


def _means(A, use: np.ndarray) -> dict:
    """The part of the pooled IC of the cells `use` picks that is the two means' product: Σ f·y = Σ (f − f̄)(y − ȳ) + n f̄ ȳ."""
    f, y = A[0][use], A[1][use]
    if not len(f):
        return {"zhat_mean": np.nan, "zres_mean": np.nan, "ic_of_means": np.nan}
    return {"zhat_mean": float(f.mean()), "zres_mean": float(y.mean()), "ic_of_means": float(len(f) * f.mean() * y.mean() / np.sqrt((f * f).sum() * (y * y).sum()))}


def ic(d: pd.DataFrame, nd: int, lags: int) -> dict:
    return _ic(_arrays(d), np.ones(len(d), dtype=bool), nd, lags)


def cells(run: Path, M: bt.Market, hold: int, latency: int, fold_names, mem: pd.DataFrame) -> pd.DataFrame:
    """The run's scored cells with the realised move, the residual against the members present, the fold, the block and the
    member's thirds."""
    o = pd.read_parquet(run / "forecast.parquet")
    o = o[o["group"] == SCORED].copy()
    y = bt.labels(M, hold, latency)
    o["y_bps"] = y.to_numpy()[M.index.get_indexer(o["t"]), M.columns.get_indexer(o["symbol"])]
    o["z"] = np.clip(o["y_bps"] / o["sigma_h"], -Z_CLIP, Z_CLIP)
    o["zhat"] = o["f_bps"] / o["sigma_h"]
    t = pd.Series(pd.DatetimeIndex(o["t"]), index=o.index)
    o["fold"] = ""
    for f in fold_names:
        o.loc[folds.mask(t, f).to_numpy(), "fold"] = f
    o = o[o["zhat"].notna() & o["z"].notna() & (o["fold"] != "")].copy()
    g = o.groupby("t")["z"]
    o["zres"] = (o["z"] - g.transform("mean")).where(g.transform("size") >= MIN_PAIRS)
    o = o.dropna(subset=["zres"])
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    o["block"] = starts[starts.searchsorted(pd.DatetimeIndex(o["t"]), side="right") - 1]
    o["day"] = (pd.DatetimeIndex(o["t"]).floor("D") - pd.DatetimeIndex(o["t"]).min().floor("D")).days
    return o.merge(mem[["block", "symbol", *(c for c in (*universe.CHARACTERISTICS, *universe.HINDSIGHT) if c in mem.columns)]], on=["block", "symbol"], how="left")


def validity(run: Path, reference: Path) -> dict:
    """The training names' forecasts against the reference run's, on the cells both hold."""
    if not (reference / "forecast.parquet").exists():
        return {"status": "NO REFERENCE", "cells": 0, "max_abs_df_bps": np.nan}
    a = pd.read_parquet(run / "forecast.parquet").query(f"group == {TRAIN}")[["t", "symbol", "f_bps", "sigma_h"]]
    b = pd.read_parquet(reference / "forecast.parquet")[["t", "symbol", "f_bps", "sigma_h"]]
    m = a.merge(b, on=["t", "symbol"], suffixes=("", "_ref"))
    both, one = m["f_bps"].notna() & m["f_bps_ref"].notna(), m["f_bps"].notna() != m["f_bps_ref"].notna()
    df = float((m["f_bps"] - m["f_bps_ref"]).abs()[both].max()) if both.any() else np.nan
    ok = bool(both.sum() > 0 and one.sum() == 0 and df <= F_TOL and len(m) == len(b))
    return {"status": "PASS" if ok else "FAIL", "cells": int(both.sum()), "cells_in_one_only": int(one.sum()), "reference_cells": len(b), "max_abs_df_bps": df}


def random_thirds(o: pd.DataFrame, nd: int, lags: int, draws: int, n_screens: int, seed: int = 0) -> np.ndarray:
    """Per draw: the largest spread t over `n_screens` random static screens (one score per name, the block's members cut by it)."""
    mb = o[["block", "symbol"]].drop_duplicates().sort_values(["block", "symbol"]).reset_index(drop=True)      # the name-blocks that hold cells
    row = pd.MultiIndex.from_frame(mb).get_indexer(pd.MultiIndex.from_frame(o[["block", "symbol"]]))
    names = np.array(sorted(mb["symbol"].unique()))
    j, n = pd.Index(names).get_indexer(mb["symbol"]), mb.groupby("block")["symbol"].transform("size").to_numpy()
    A, out = _arrays(o), np.full(draws, np.nan)
    for d in range(draws):
        rng = np.random.default_rng([seed, d])
        best = -np.inf
        for _ in range(n_screens):
            rk = pd.Series(rng.random(len(names))[j]).groupby(mb["block"]).rank(method="first").to_numpy()
            third = np.minimum((rk - 1) * 3 // n, 2)[row]
            t = _spread(A, third == 2, third == 0, nd, lags)["t"]
            best = max(best, t) if np.isfinite(t) else best
        out[d] = best
    return out


def book(dec: pd.DataFrame, keep: pd.DataFrame | None, M: bt.Market, C: bt.Costs, C2: bt.Costs, days: pd.DatetimeIndex, hold: int, execs, taker_bps: float, maker_bps: float,
         latency: int, draws: int, seed: int = 0) -> list[dict]:
    """The run's decisions on the (block, symbol) rows of `keep` (None = all), re-accepted, priced, with the flip null."""
    d = dec.drop(columns=["accepted", "skip"])
    if keep is not None:
        d = d.merge(keep[["block", "symbol"]].drop_duplicates(), on=["block", "symbol"], how="inner").sort_values(["t", "symbol"], kind="mergesort").reset_index(drop=True)
    if d.empty:
        return []
    d = bt.accept(d, M.index)
    rows = []
    for e in execs:
        f = bt.price(d, M, C, e, taker_bps, maker_bps, latency)
        s = bt.summarize(f, days, hold)
        nul = np.array([])
        if e == "taker":                                     # a taker's prices and costs do not depend on the side: the flip is a sign on gross and funding
            x = f.dropna(subset=["net_bps"])
            day = np.unique(pd.DatetimeIndex(x["t"]).floor("D"), return_inverse=True)[1]
            g, c, w = (x["gross_bps"] + x["funding_bps"]).to_numpy(), (x["fee_bps"] + x["other_cost_bps"]).to_numpy(), x["size"].to_numpy()
            nul = np.array([np.average(np.random.default_rng([seed, k, 1]).choice([-1, 1], day.max() + 1)[day] * g - c, weights=w) for k in range(1, draws + 1)]) if len(x) else nul
        f2 = bt.summarize(bt.price(d, M, C2, e, taker_bps, maker_bps, latency), days, hold)
        per_fold = {fo: bt.summarize(f[f["fold"] == fo], bt.scored_days([fo], M.index[-1]), hold)["net"] for fo in sorted(f["fold"].unique())}
        rows.append({"exec": e, "trades": s["trades"], "per_day": s["trades_per_day"], "names": int(f["symbol"].nunique()), "gross": s["gross"], "hedged": s["hedged"], "net": s["net"],
                     "net_lo": s["net_lo"], "net_hi": s["net_hi"], "mde": s["net_mde"], "hedged_net": s["hedged_net"], "hedged_net_lo": s["hedged_net_lo"],
                     "hedged_net_hi": s["hedged_net_hi"], "flip_p": (1 + int((nul >= s["net"]).sum())) / (len(nul) + 1) if len(nul) else np.nan,
                     "flip_null_sd": float(nul.std()) if len(nul) else np.nan, "net_cost_x2": f2["net"], "hedged_net_cost_x2": f2["hedged_net"],
                     "long_net": bt.summarize(f[f["side"] > 0], days, hold)["net"], "short_net": bt.summarize(f[f["side"] < 0], days, hold)["net"],
                     **{f"net_{fo}": v for fo, v in per_fold.items()}, "unpriced": s["unpriced"]})
    return rows


def read(run: str, reference: str | None = None, draws: int = DRAWS, members: str | None = None, seed: int = 0, hindsight: Path | str | None = None) -> str:
    run_dir = bt.OUT / run
    meta = json.loads((run_dir / "meta.json").read_text())
    p, fold_names = meta["params"], meta["folds"]
    hold, latency = int(p["hold"]), int(meta["latency_bars"])
    mem = universe.members(members or p.get("members") or None, hindsight)
    chars = universe.HINDSIGHT if hindsight else universe.CHARACTERISTICS
    family = len(universe.CHARACTERISTICS) + (len(universe.HINDSIGHT) if hindsight else 0)      # every screen tried on these cells so far
    end = folds.bounds(fold_names[-1])[1]
    M = bt.market(meta["pairs"], end)
    lags = day_lags(hold)
    v = validity(run_dir, Path(reference) if reference else REFERENCE)
    o = cells(run_dir, M, hold, latency, fold_names, mem)
    nd = int(o["day"].max()) + 1

    rows = [{"scope": "all members", **ic(o, nd, lags)}] + [{"scope": f, **ic(o[o["fold"] == f], nd, lags)} for f in fold_names]
    transfer = pd.DataFrame(rows)
    scr, per_fold, A = [], [], _arrays(o)
    for c in chars:
        third, on = o[c].to_numpy(), (o["f_bps"].abs() >= p["min_bps"]).to_numpy()
        top, mid, bot = (third == k for k in (2, 1, 0))
        s = _spread(A, top, bot, nd, lags)
        scr.append({"screen": c, "names_top": int(o.loc[top, "symbol"].nunique()),
                    **{f"{k}_{n}": x[k] for n, x in (("top", _ic(A, top, nd, lags)), ("mid", _ic(A, mid, nd, lags)), ("bottom", _ic(A, bot, nd, lags))) for k in ("ic", "t")},
                    "spread": s["spread"], "spread_t": s["t"], "spread_mde": s["mde"], "share_on_top": float(on[top].mean()) if top.any() else np.nan,
                    **({f"{k}_{n}": x for n, u in (("top", top), ("bottom", bot)) for k, x in _means(A, u).items()} if hindsight else {})})
        for f in fold_names:
            in_f = (o["fold"] == f).to_numpy()
            per_fold.append({"screen": c, "fold": f, "ic_top": _ic(A, top & in_f, nd, lags)["ic"], "ic_bottom": _ic(A, bot & in_f, nd, lags)["ic"],
                             "spread_t": _spread(A, top & in_f, bot & in_f, nd, lags)["t"]})
    scr = pd.DataFrame(scr)
    null = random_thirds(o, nd, lags, draws, family, seed)
    null = null[np.isfinite(null)]
    scr["p_family"] = [(1 + int((null >= t).sum())) / (len(null) + 1) for t in scr["spread_t"]]
    best = scr.sort_values("spread_t", ascending=False).iloc[0]

    dec = pd.read_parquet(run_dir / "decisions.parquet")
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    dec["block"] = starts[starts.searchsorted(pd.DatetimeIndex(dec["t"]), side="right") - 1]
    C, C2 = bt.load_costs(M.index, M.columns, end, meta["cost_mult"]), bt.load_costs(M.index, M.columns, end, 2 * meta["cost_mult"])
    days = bt.scored_days(fold_names, M.index[-1])
    execs = [e for e in ("taker", "maker") if (run_dir / f"fills_{e}.parquet").exists()]
    money = [{"book": "all members", **r} for r in book(dec, None, M, C, C2, days, hold, execs, meta["taker_bps"], meta["maker_bps"], latency, draws, seed)]
    for c in chars:
        for k, third in ((2, "top"), (0, "bottom"))[:2 if hindsight else 1]:
            money += [{"book": f"{c}: {third} third", **r} for r in book(dec, mem[mem[c] == k], M, C, C2, days, hold, execs, meta["taker_bps"], meta["maker_bps"], latency, draws, seed)]
    money = pd.DataFrame(money)
    cross = pd.DataFrame([{"cells": n, **_ic(A, u, nd, lags)} for n, u in (
        ("hindsight top ∩ young top", ((o["hindsight"] == 2) & (o["young"] == 2)).to_numpy()), ("hindsight top, not young top", ((o["hindsight"] == 2) & (o["young"] != 2)).to_numpy()),
        ("young top, not hindsight top", ((o["hindsight"] != 2) & (o["young"] == 2)).to_numpy()))]).rename(columns={"cells": "n"}) if hindsight else None

    per_name = pd.DataFrame([{"symbol": s, "blocks": int(d["block"].nunique()), **{k: x for k, x in ic(d, nd, lags).items() if k in ("cells", "ic", "t")},
                              "share_on": float((d["f_bps"].abs() >= p["min_bps"]).mean()), **{f"top_{c}": int(d.loc[d[c] == 2, "block"].nunique()) for c in chars}}
                             for s, d in o.groupby("symbol")]).sort_values("ic", ascending=False)
    a = transfer.iloc[0]
    md = [f"# The screener read — `{run}` (`ft2 screen`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · run generated {meta['generated']} · folds {'+'.join(fold_names)} · "
          f"{o['symbol'].nunique()} scored names, {len(o):,} cells, {nd} days · params {p}\n",
          "\nWords: *IC* is the correlation between the forecast and the move that followed, against the other members at the same bar; 0 = no information, 0.03–0.05 is what a "
          "tradable weak signal looks like here. *t* is the IC over its day-to-day standard error; 2 or more is the bar. A *screen* ranks the block's members by something known "
          "before the block and keeps the top third; its *spread* is the top third's IC minus the bottom third's. *p (family)* is the share of random static screens, " + str(family) + " at a "
          "time, whose best spread did at least as well. A basis point (bps) is 0.01 %; net is after fees, spread, impact and funding; hedged net is net against the market.\n",
          "\n## Validity — is the model R13 B's?\n",
          f"\n**{v['status']}**: {v['cells']:,} training-name cells compared with `{reference or REFERENCE}`, largest |Δ forecast| {v['max_abs_df_bps']:.3g} bps (bar {F_TOL:g}); "
          f"{v.get('cells_in_one_only', 0)} cells forecast in one run only; the reference holds {v.get('reference_cells', 0):,}.\n",
          "\n## Transfer — the forecast on names the model never saw, no screen\n",
          f"\n**IC {a['ic']:+.4f}, t {a['t']:.2f}** on {int(a['cells']):,} cells.\n", transfer.round(4).to_markdown(index=False), "\n",
          "\n## Screens — the IC inside each third of the block's members\n",
          f"\nBest spread: **{best['screen']}**, top third IC {best['ic_top']:+.4f} (t {best['t_top']:.2f}), spread {best['spread']:+.4f} (t {best['spread_t']:.2f}, "
          f"family-wise p {best['p_family']:.3f}; the smallest spread this sample could have shown: {best['spread_mde']:.4f}). Random static screens, best of {family}: "
          f"mean t {null.mean():.2f}, 95th percentile {np.quantile(null, 0.95):.2f} ({len(null)} draws).\n", scr.round(4).to_markdown(index=False), "\n",
          "\n### Per fold\n", pd.DataFrame(per_fold).round(4).to_markdown(index=False), "\n",
          "\n## Money — the book on all members, and on each screen's top third (bps per unit of notional)\n",
          "\n`net_cost_x2`: spread and impact doubled. The flip null: the book's own trades, each day's sides multiplied by one random sign.\n",
          money.round(3).to_markdown(index=False), "\n", "\n## Per name\n", per_name.round(4).to_markdown(index=False), "\n"]
    if hindsight:
        md[0] = f"# The hindsight diagnostic (R19) — `{run}` cut by how much a name is traded in {universe.HINDSIGHT_WINDOW[0]:%Y} (`ft2 screen --hindsight`)\n"
        md.insert(3, "\n**The screen below uses the future on purpose and can never be traded.** It asks whether the forecast looks skilled where the names are chosen knowing "
                     "which ones are still heavily traded years later. `ic_of_means`: the part of a third's IC that is the forecast's average lean times the names' average drift.\n")
        md += ["\n## The top third's cells, split by R18's `young` (described, decides nothing)\n", cross.round(4).to_markdown(index=False), "\n"]
    out = OUT / (run + HINDSIGHT_SUFFIX * bool(hindsight))
    out.mkdir(parents=True, exist_ok=True)
    (out / "screen.md").write_text("\n".join(md))
    scr.to_csv(out / "screens.csv", index=False)
    money.to_csv(out / "money.csv", index=False)
    transfer.to_csv(out / "transfer.csv", index=False)
    (out / "validity.json").write_text(json.dumps(v, indent=1))
    return "\n".join(md)
