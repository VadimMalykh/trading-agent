"""P8 — R53: the members' own ridge (PLAN §8 R53, P8 decision AI).

§0's goal is a model that trades names it was not trained on. R14 fitted the candle ridge on the twelve and held it out among
them; R18 took the twelve's model to the screener's members (nothing); R12/R13 fitted it on forty names fixed in 2022 (nothing).
This module fits the same ridge ON the members and holds it out among them, and scores the twelve with a model that never saw
them — §0's sentence verbatim.

`membersbook` (a strategy, through the harness like any other)
    `forecast.RidgeBook` in every respect not named here (the 12 candle columns, the residual label, grid 12, RidgeCV over
    `ceiling.ALPHAS` without intercept, refit every block on all rows whose labels ended before it, min_bps, cap, the sizing).
      training rows    a MEMBER's cells while it is a member of the block the bar falls in (`universe.members`, R18's mask) —
                       never a cell of an EXCLUDED name (the twelve), never a bar outside a name's membership. Meta counts the
                       rows used and, of them, the excluded and the non-member ones (both must be zero: validity (2)).
      peers            the relative features and the label's mean are against the block's members present at the bar
                       (≥ min_pairs), the excluded names left out — the market a members-only host would hold.
      hold-out         `groups` static groups of the members (the sorted member names, every `groups`-th), a member scored by
                       the model fitted without its group; the excluded names scored by a FIFTH model fitted on all members'
                       rows (the deployable one). In forecast.parquet a member's `group` is 0 … groups − 1, an excluded name's
                       is TWELVE (9).
      traded           member cells while members and the excluded names' cells alike, at |f| ≥ min_bps, one position per
                       name; the read prices the two books apart.

`read` (`ft2 membersbook <run>`) → output/membersbook/<run>/read.md (+ csvs, validity.json)
    validity    (2) the meta's counters; (3) every member cell with a forecast is a block member (the mask recomputed);
                (4) the groups hold the member names evenly and no name is in two; (5) the label is `backtest.labels` on
                every cell; (6) at hold 288, R18's forecast file holds ≥ 95 % of this run's member cells; (7) the excluded
                names' cells carry the TWELVE tag. (1), the causal check, is the harness's at run time.
    (A)         the held-out IC on the members' cells — `ceiling._ic_pooled` of ẑ with the realised z minus the mean over the
                members present at the bar (≥ min_pairs, 5), t clustered by day — pooled, per fold, per group.
    (B)         the same on the excluded names' cells (their residual against the excluded names present), per fold, per name.
    (C)         at hold 288: against R18's forecast on the same member cells (its group 0), the day-paired difference and its t.
    (D)         `ic_needed` per universe and execution from the run's own numbers (P2 #7's formula): the universe's priced
                trades' mean round trip ÷ (Z_TOP × 1.2533 × the mean |label| in bps over the universe's cells).
    (M)         the books, members and excluded apart (`screen.book`): taker and maker, net [95 %], hedged net, the flip null,
                costs doubled, per fold, long / short.
    verdict     per universe (the registered gate): CLEARS / REAL, NOT FUNDED / CLOSED / NOT DETECTABLE, t bar T_BAR.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import folds, universe
from .ceiling import MIN_PAIRS, Z_CLIP, Z_TOP, _ic_pooled, basket, day_lags, dir_features, hac
from .forecast import LOOKBACK, RidgeBook, _cells, _derive
from .screen import SCORED, book

OUT = Path("output/membersbook")
R18_FORECAST = Path("output/backtest/r18_transferbook_1d/forecast.parquet")
TWELVE = 9                   # `group` of an excluded name's cells in forecast.parquet
FULL = "full"                # the fifth model: fitted on all members' rows, scores the excluded names
T_BAR = 2.24                 # one-sided bar for a family of four at 5 %
R18_COVER = 0.95             # validity (6): the share of this run's member cells R18's file must hold


class MembersBook(RidgeBook):
    name = "membersbook"

    def __init__(self, hold: int = 288, min_bps: float = 15.0, cap: float = 2.0, groups: int = 4, grid: int = 12, min_pairs: int = 5,
                 exclude: str = "", members: str = ""):
        super().__init__(hold=hold, min_bps=min_bps, cap=cap, groups=groups, grid=grid, min_pairs=min_pairs, holdout=True, features="candle")
        from .__main__ import PAIRS
        self.exclude = str(exclude)                          # "" = the twelve; else names joined by commas (the tests)
        self.members = str(members)                          # "" = universe.MEMBERS_CSV
        self._excl = self.exclude.split(",") if self.exclude else list(PAIRS)
        self._mem: pd.DataFrame | None = None
        self._grp: dict[str, int] | None = None
        self.train_rows = 0                                  # meta counters, summed over every fit (the real walk and the noise floor's)
        self.train_rows_excluded = 0
        self.train_rows_nonmember = 0

    # ---- who is who ------------------------------------------------------------------------------------------------------------
    def _table(self) -> pd.DataFrame:
        if self._mem is None:
            self._mem = universe.members(self.members or None)
            names = sorted(set(self._mem["symbol"]) - set(self._excl))
            self._grp = {s: i % self.groups for i, s in enumerate(names)}
        return self._mem

    def _group_cols(self, cols: np.ndarray) -> np.ndarray:
        """Per column: the member's static group, or −1 for an excluded name (and for a name that is in neither list)."""
        self._table()
        return np.array([self._grp.get(c, -1) if c not in self._excl else -1 for c in cols], dtype=int)

    def _member_mask(self, cols: np.ndarray, ts: pd.DatetimeIndex) -> np.ndarray:
        """bar × pair: is the pair a member of the block the bar falls in? Never an excluded name."""
        m = self._table()
        starts = pd.DatetimeIndex(sorted(m["block"].unique()))
        table = np.zeros((len(starts) + 1, len(cols)), dtype=bool)                # the last row: before the first block, nobody
        b, j = starts.get_indexer(m["block"]), pd.Index(cols).get_indexer(m["symbol"])
        table[b[j >= 0], j[j >= 0]] = True
        table[:, np.isin(cols, self._excl)] = False
        return table[starts.searchsorted(ts, side="right") - 1]

    # ---- features: RidgeBook's, the relative ones against the block's members present ------------------------------------------
    def _ensure(self, M: bt.Market) -> None:
        idx = M.index
        g = np.flatnonzero(self._grid(idx))
        missing = [p for p in g if idx[p] not in self._pos]
        if not missing:
            return
        start = max(int(missing[0]) - LOOKBACK, 0)
        D = _derive(M.close.iloc[start:])
        F = dir_features(D)
        cols = np.asarray(M.columns, dtype=str)
        mem = pd.DataFrame(self._member_mask(cols, idx[start:]), index=idx[start:], columns=M.columns)
        for k in [k for k in F if k.startswith("relret_")]:
            own = F["ret_" + k.split("_", 1)[1]]
            F[k] = own.sub(basket(own.where(mem)), axis=0)
        X, S = _cells(F, D["sig"]["1w"])
        X[~np.isfinite(X)] = np.nan
        for p in missing:
            self._pos[idx[p]] = len(self._ts)
            self._ts.append(idx[p])
            self._X.append(X[p - start])
            self._S.append(S[p - start])

    # ---- fit: one ridge per rotation on the other groups' member rows, and the full one -----------------------------------------
    def fit(self, M: bt.Market, y: pd.DataFrame, now: pd.Timestamp) -> None:
        if self._last_now is not None and now <= self._last_now:
            self._walks += 1
        self._last_now = now
        self._ensure(M)
        ts = y.index[self._grid(y.index)]
        ts = ts[np.array([t in self._pos for t in ts], dtype=bool)]
        self._models = {**{g: None for g in range(self.groups)}, FULL: None}
        if not len(ts):
            return
        cols = np.asarray(M.columns, dtype=str)
        X, S = self._rows(ts)                                # (rows × pair × feat), (rows × pair)
        sig_h = np.where(S > 0, S, np.nan) * np.sqrt(self.hold)
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.clip(y.loc[ts].to_numpy() / sig_h, -Z_CLIP, Z_CLIP)
        mem = self._member_mask(cols, ts)
        gcol = self._group_cols(cols)
        self._sigma_ref = float(np.nanmedian(np.where(mem, sig_h, np.nan))) if (mem & np.isfinite(sig_h)).any() else np.nan
        Xt = X.reshape(-1, self.n_feat)
        feat_ok = ~np.isnan(Xt).any(1).reshape(mem.shape)
        for g in [*range(self.groups), FULL]:
            tr = mem if g == FULL else mem & (gcol != g)[None, :]
            zt = np.where(tr, z, np.nan)
            n = (~np.isnan(zt)).sum(1, keepdims=True)
            mean = np.where(n >= self.min_pairs, np.nansum(zt, 1, keepdims=True) / np.maximum(n, 1), np.nan)
            zr = zt - mean
            used = ~np.isnan(zr) & feat_ok
            self.train_rows += int(used.sum())
            self.train_rows_excluded += int(used[:, np.isin(cols, self._excl)].sum())
            self.train_rows_nonmember += int((used & ~mem).sum())
            self._models[g] = self._ridge(Xt, zr.ravel())

    # ---- decide: a member by the model that never saw its group, an excluded name by the full model -----------------------------
    def _forecast(self, M: bt.Market, a: pd.Timestamp, b: pd.Timestamp):
        self._ensure(M)
        idx = M.index
        ts = idx[self._grid(idx) & (idx >= a) & (idx < b)]
        if not len(ts):
            z = np.zeros((0, len(M.columns)))
            return ts, z, z, z
        X, S = self._rows(ts)
        sig_h = np.where(S > 0, S, np.nan) * np.sqrt(self.hold)
        gcol = self._group_cols(np.asarray(M.columns, dtype=str))
        zhat = np.full(S.shape, np.nan)
        for g, m in self._models.items():
            if m is None:
                continue
            mu, sd, coef = m
            c = (gcol < 0) if g == FULL else (gcol == g)
            if c.any():
                zhat[:, c] = ((X[:, c, :] - mu) / sd) @ coef
        with np.errstate(invalid="ignore"):
            f = zhat * sig_h
        f[~np.isfinite(f)] = np.nan
        f[np.isnan(M.close.loc[ts].to_numpy())] = np.nan
        return ts, f, sig_h, np.full(S.shape, np.nan)

    def decide(self, M: bt.Market, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
        ts, f_all, sig_h, _ = self._forecast(M, a, b)
        cols = np.asarray(M.columns, dtype=str)
        gcol = self._group_cols(cols)
        mem = self._member_mask(cols, ts) if len(ts) else np.zeros(f_all.shape, dtype=bool)
        excl = np.repeat(np.isin(cols, self._excl)[None, :], len(ts), 0)
        f = np.where(mem | excl, f_all, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            on = np.abs(f) >= self.min_bps
            size = np.clip((np.abs(f) / self.min_bps) * (self._sigma_ref / sig_h) ** 2, 0.25, self.cap)
        side = pd.DataFrame(np.where(on, np.sign(f) * size, 0.0), index=ts, columns=M.columns)
        if self._walks == 0 and len(ts):
            grp = np.where(excl, TWELVE, np.repeat(gcol[None, :], len(ts), 0))
            keep = (mem | excl).ravel()
            self._oos.append(pd.DataFrame({"t": np.repeat(ts, len(cols)), "symbol": np.tile(cols, len(ts)), "group": grp.ravel(),
                                           "f_bps": f.ravel(), "sigma_h": sig_h.ravel(), "f_ref_bps": np.nan})[keep])
        return bt.decisions_from(side, a, b, signal=pd.DataFrame(f, index=ts, columns=M.columns),
                                 why=f"ridge fitted on the members, held out by group; the excluded names by the full model; |f| ≥ {self.min_bps:g} bps")


STRATEGIES = {MembersBook.name: MembersBook}


# ---- the read ---------------------------------------------------------------------------------------------------------------------
def _ic(o: pd.DataFrame, nd: int, lags: int) -> dict:
    if len(o) < 200:
        return {"cells": len(o), "days": 0, "ic": np.nan, "se": np.nan, "t": np.nan}
    m, se, n = hac(_ic_pooled(o["zhat"].to_numpy(), o["zres"].to_numpy(), o["day"].to_numpy(), min_cells=1), lags)
    return {"cells": len(o), "days": n, "ic": m, "se": se, "t": m / se if se else np.nan}


def cells(run: Path, M: bt.Market, hold: int, latency: int, fold_names, mem: pd.DataFrame, min_pairs: int = MIN_PAIRS) -> pd.DataFrame:
    """The run's forecast cells with the realised move, the residual against the cell's own universe (members among the members
    present, excluded names among the excluded present), the fold, the block and the day."""
    o = pd.read_parquet(run / "forecast.parquet")
    y = bt.labels(M, hold, latency)
    o["y_bps"] = y.to_numpy()[M.index.get_indexer(o["t"]), M.columns.get_indexer(o["symbol"])]
    o["z"] = np.clip(o["y_bps"] / o["sigma_h"], -Z_CLIP, Z_CLIP)
    o["zhat"] = o["f_bps"] / o["sigma_h"]
    t = pd.Series(pd.DatetimeIndex(o["t"]), index=o.index)
    o["fold"] = ""
    for f in fold_names:
        o.loc[folds.mask(t, f).to_numpy(), "fold"] = f
    o = o[o["zhat"].notna() & o["z"].notna() & (o["fold"] != "")].copy()
    o["universe"] = np.where(o["group"] == TWELVE, "twelve", "members")
    g = o.groupby(["t", "universe"])["z"]
    o["zres"] = (o["z"] - g.transform("mean")).where(g.transform("size") >= min_pairs)
    o = o.dropna(subset=["zres"]).copy()
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    o["block"] = starts[starts.searchsorted(pd.DatetimeIndex(o["t"]), side="right") - 1]
    o["day"] = (pd.DatetimeIndex(o["t"]).floor("D") - pd.DatetimeIndex(o["t"]).min().floor("D")).days
    return o.reset_index(drop=True)


def validity(run: Path, o: pd.DataFrame, mem: pd.DataFrame, meta: dict, excl: list[str], reference: Path | None) -> dict:
    p = meta["params"]
    used = int(p.get("train_rows", 0))
    v = {"train_rows": used, "train_rows_excluded": int(p.get("train_rows_excluded", -1)), "train_rows_nonmember": int(p.get("train_rows_nonmember", -1))}
    v["(2) training rows of excluded names and outside membership"] = "PASS" if used > 0 and v["train_rows_excluded"] == 0 and v["train_rows_nonmember"] == 0 else "FAIL"
    m = o[o["universe"] == "members"].merge(mem[["block", "symbol"]].drop_duplicates().assign(ok=True), on=["block", "symbol"], how="left")
    v["member_cells_outside_blocks"] = int((~m["ok"].fillna(False).astype(bool)).sum())
    v["(3) every member cell is a block member"] = "PASS" if v["member_cells_outside_blocks"] == 0 else "FAIL"
    grp = o[o["universe"] == "members"].groupby("symbol")["group"].agg(["nunique", "first"])
    sizes = grp["first"].value_counts().sort_index()
    names = sorted(set(mem["symbol"]) - set(excl))
    v["groups"] = {int(k): int(n) for k, n in sizes.items()}
    v["(4) groups even, no name in two"] = "PASS" if (grp["nunique"] == 1).all() and set(grp.index) <= set(names) and (sizes.max() - sizes.min() <= 1) and len(sizes) == int(p["groups"]) else "FAIL"
    v["(5) label"] = "PASS"                                                       # `cells` computes y from backtest.labels on every cell
    v["(7) excluded names carry the TWELVE tag"] = "PASS" if set(o.loc[o["symbol"].isin(excl), "group"].unique()) <= {TWELVE} and set(o.loc[o["group"] == TWELVE, "symbol"]) <= set(excl) else "FAIL"
    if int(p["hold"]) == 288 and reference is not None and reference.exists():
        r = pd.read_parquet(reference, columns=["t", "symbol", "group", "f_bps"])
        r = r[(r["group"] == SCORED) & r["f_bps"].notna()]
        j = o[o["universe"] == "members"][["t", "symbol"]].merge(r[["t", "symbol"]].assign(ok=True), on=["t", "symbol"], how="left")
        v["r18_cover"] = float(j["ok"].fillna(False).astype(bool).mean())
        v["(6) R18's file covers this run's member cells"] = "PASS" if v["r18_cover"] >= R18_COVER else "FAIL"
    else:
        v["r18_cover"] = np.nan
        v["(6) R18's file covers this run's member cells"] = "n/a (hold ≠ 288 or no reference)"
    v["status"] = "PASS" if all(x == "PASS" for k, x in v.items() if k.startswith("(") and x != "n/a (hold ≠ 288 or no reference)") else "FAIL"
    return v


def paired_r18(o: pd.DataFrame, reference: Path, nd: int, lags: int) -> dict:
    """(C): the members' model against R18's forecast on the common member cells, the day-paired difference of the two ICs."""
    r = pd.read_parquet(reference, columns=["t", "symbol", "group", "f_bps", "sigma_h"])
    r = r[(r["group"] == SCORED) & r["f_bps"].notna()]
    r["zhat_ref"] = r["f_bps"] / r["sigma_h"]
    c = o[o["universe"] == "members"].merge(r[["t", "symbol", "zhat_ref"]], on=["t", "symbol"], how="inner")
    if len(c) < 200:
        return {"common_cells": len(c)}
    A = (c["zhat"].to_numpy(), c["zhat_ref"].to_numpy(), c["zres"].to_numpy(), c["day"].to_numpy())
    d_own, d_ref = _ic_pooled(A[0], A[2], A[3], min_cells=1), _ic_pooled(A[1], A[2], A[3], min_cells=1)
    m, se, n = hac(d_own - d_ref, lags)
    own, ref = hac(d_own, lags), hac(d_ref, lags)
    return {"common_cells": len(c), "days": n, "ic_members_model": own[0], "t_members_model": own[0] / own[1] if own[1] else np.nan,
            "ic_r18_model": ref[0], "t_r18_model": ref[0] / ref[1] if ref[1] else np.nan, "diff": m, "se": se, "t": m / se if se else np.nan}


def ic_needed(o: pd.DataFrame, fills: dict[str, pd.DataFrame], excl: list[str]) -> pd.DataFrame:
    """(D): P2 #7's formula on the run's own numbers, per universe and execution."""
    rows = []
    for u in ("members", "twelve"):
        ou = o[o["universe"] == u]
        sd = float(ou["y_bps"].abs().mean()) * 1.2533 if len(ou) else np.nan
        for e, f in fills.items():
            fu = f[f["symbol"].isin(excl) == (u == "twelve")].dropna(subset=["net_bps"])
            rt = float(np.average(fu["fee_bps"] + fu["other_cost_bps"], weights=fu["size"])) if len(fu) else np.nan
            rows.append({"universe": u, "exec": e, "trades": len(fu), "round_trip_bps": rt, "abs_label_mean_bps": sd / 1.2533, "ic_needed": rt / (Z_TOP * sd) if sd else np.nan})
    return pd.DataFrame(rows)


def verdict(row: dict, per_fold: pd.DataFrame, need_maker: float) -> str:
    ic, se, t = row["ic"], row["se"], row["t"]
    if not np.isfinite(t):
        return "UNREAD"
    both = bool((per_fold["ic"] > 0).all()) if len(per_fold) else False
    if t >= T_BAR and np.isfinite(need_maker) and ic >= need_maker and both:
        return "CLEARS"
    if t >= T_BAR:
        return "REAL, NOT FUNDED" if (not np.isfinite(need_maker) or ic < need_maker) else "REAL (a fold negative)"
    if np.isfinite(need_maker) and ic + 1.96 * se < need_maker:
        return "CLOSED"
    return "NOT DETECTABLE"


def read(run: str, draws: int = 200, members: str | None = None, reference: Path | str | None = R18_FORECAST, seed: int = 0) -> str:
    from .__main__ import PAIRS
    run_dir = bt.OUT / run
    meta = json.loads((run_dir / "meta.json").read_text())
    p, fold_names = meta["params"], meta["folds"]
    hold, latency = int(p["hold"]), int(meta["latency_bars"])
    excl = p["exclude"].split(",") if p.get("exclude") else list(PAIRS)
    mem = universe.members(members or p.get("members") or None)
    end = folds.bounds(fold_names[-1])[1]
    M = bt.market(meta["pairs"], end)
    lags = day_lags(hold)
    reference = Path(reference) if reference else None
    o = cells(run_dir, M, hold, latency, fold_names, mem, int(p["min_pairs"]))
    nd = int(o["day"].max()) + 1
    v = validity(run_dir, o, mem, meta, excl, reference)

    rows = []
    for u in ("members", "twelve"):
        ou = o[o["universe"] == u]
        rows.append({"universe": u, "scope": "all", **_ic(ou, nd, lags)})
        rows += [{"universe": u, "scope": f, **_ic(ou[ou["fold"] == f], nd, lags)} for f in fold_names]
        if u == "members":
            rows += [{"universe": u, "scope": f"group {g}", **_ic(ou[ou["group"] == g], nd, lags)} for g in sorted(ou["group"].unique())]
    ic = pd.DataFrame(rows)
    per_name = pd.DataFrame([{"universe": d["universe"].iloc[0], "symbol": s, "group": int(d["group"].iloc[0]), "blocks": int(d["block"].nunique()),
                              **{k: x for k, x in _ic(d, nd, lags).items() if k in ("cells", "ic", "t")}, "share_on": float((d["f_bps"].abs() >= p["min_bps"]).mean())}
                             for s, d in o.groupby("symbol")]).sort_values(["universe", "ic"], ascending=[True, False])
    paired = paired_r18(o, reference, nd, lags) if hold == 288 and reference is not None and reference.exists() else {"common_cells": 0}

    execs = [e for e in ("taker", "maker") if (run_dir / f"fills_{e}.parquet").exists()]
    fills = {e: pd.read_parquet(run_dir / f"fills_{e}.parquet") for e in execs}
    need = ic_needed(o, fills, excl)
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    dec["block"] = starts[starts.searchsorted(pd.DatetimeIndex(dec["t"]), side="right") - 1]
    C, C2 = bt.load_costs(M.index, M.columns, end, meta["cost_mult"], M.close), bt.load_costs(M.index, M.columns, end, 2 * meta["cost_mult"], M.close)
    days = bt.scored_days(fold_names, M.index[-1])
    keep_m = mem[["block", "symbol"]].drop_duplicates()
    keep_m = keep_m[~keep_m["symbol"].isin(excl)]
    keep_x = pd.DataFrame([(b, s) for b in starts for s in excl], columns=["block", "symbol"])
    money = pd.DataFrame([{"book": n, **r} for n, k in (("members", keep_m), ("twelve", keep_x))
                          for r in book(dec, k, M, C, C2, days, hold, execs, meta["taker_bps"], meta["maker_bps"], latency, draws, seed)])

    verdicts = []
    for u in ("members", "twelve"):
        row = ic[(ic["universe"] == u) & (ic["scope"] == "all")].iloc[0].to_dict()
        pf = ic[(ic["universe"] == u) & ic["scope"].isin(fold_names)]
        nm = need[(need["universe"] == u) & (need["exec"] == "maker")]["ic_needed"]
        nt = need[(need["universe"] == u) & (need["exec"] == "taker")]["ic_needed"]
        need_maker = float(nm.iloc[0]) if len(nm) else np.nan
        verdicts.append({"universe": u, "hold": hold, "ic": row["ic"], "se": row["se"], "t": row["t"], "upper": row["ic"] + 1.96 * row["se"] if np.isfinite(row["se"]) else np.nan,
                         "mde": bt.MDE_K * row["se"] if np.isfinite(row["se"]) else np.nan, "ic_needed_taker": float(nt.iloc[0]) if len(nt) else np.nan, "ic_needed_maker": need_maker,
                         "folds_positive": bool((pf["ic"] > 0).all()) if len(pf) else False, "verdict": verdict(row, pf, need_maker)})
    verdicts = pd.DataFrame(verdicts)

    out = OUT / run
    out.mkdir(parents=True, exist_ok=True)
    ic.to_csv(out / "ic.csv", index=False)
    per_name.to_csv(out / "per_name.csv", index=False)
    need.to_csv(out / "ic_needed.csv", index=False)
    money.to_csv(out / "money.csv", index=False)
    verdicts.to_csv(out / "verdicts.csv", index=False)
    pd.DataFrame([paired]).to_csv(out / "paired_r18.csv", index=False)
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    h = {288: "1d", 48: "4h"}.get(hold, f"{hold} bars")
    md = [f"# The members' own ridge — `{run}` (`ft2 membersbook`, R53), hold {h}\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · run generated {meta['generated']} · folds {'+'.join(fold_names)} · "
          f"{(o['universe'] == 'members').sum():,} member cells of {o.loc[o['universe'] == 'members', 'symbol'].nunique()} names, "
          f"{(o['universe'] == 'twelve').sum():,} cells of the {len(excl)} excluded names, {nd} days · params {p}\n",
          "\nWords: *IC* is the correlation between the forecast and the move that followed, against the other names of the same universe at the same bar; "
          "a member is scored by a model fitted without its group, an excluded name by the model fitted on all members. *t* is the IC over its "
          f"day-to-day standard error; the bar is {T_BAR} (one-sided, a family of four). *ic_needed* is the IC at which trading the top tenth of "
          "forecasts breaks even on this run's own costs (P2 #7's formula). bps = 0.01 %; net is after fees, spread, impact and funding; hedged net is net against the market.\n",
          "\n## Validity\n", f"\n**{v['status']}**\n", "```\n" + json.dumps(v, indent=1, default=str) + "\n```\n",
          "\n## Verdicts (the registered gate)\n", verdicts.round(4).to_markdown(index=False), "\n",
          "\n## (A), (B) The IC — pooled, per fold, per held-out group\n", ic.round(4).to_markdown(index=False), "\n",
          "\n## (D) ic_needed from the run's own numbers\n", need.round(4).to_markdown(index=False), "\n"]
    if paired.get("common_cells", 0) >= 200:
        md += ["\n## (C) Paired against R18's forecast (the twelve's model) on the same member cells\n",
               f"\n**Members' model − R18's: {paired['diff']:+.4f}, t {paired['t']:.2f}** over {paired['days']} days, {paired['common_cells']:,} common cells "
               f"(members' model {paired['ic_members_model']:+.4f}, t {paired['t_members_model']:.2f}; R18's {paired['ic_r18_model']:+.4f}, t {paired['t_r18_model']:.2f}).\n"]
    else:
        md += ["\n## (C) Paired against R18's forecast\n", f"\nnot read (hold {h}, or no reference file; common cells {paired.get('common_cells', 0)}).\n"]
    md += ["\n## (M) The books, members and the excluded names apart\n", money.round(2).to_markdown(index=False), "\n",
           "\n## Per name\n", per_name.round(4).to_markdown(index=False), "\n"]
    txt = "\n".join(md)
    (out / "read.md").write_text(txt)
    return txt
