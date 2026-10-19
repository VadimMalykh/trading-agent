"""R60 — the Coinbase spot premium per name as a ceiling screen on the twelve, in P2's frame (PLAN §8 R60).

`ft2 ceiling --target pairs --family coinbase` → output/ceiling_coinbase.md, output/ceiling_coinbase/.

ONE source: `data/coinbase_1h.parquet` (AT2's ingest, DATA.md `coinbase_1h`) — Coinbase Exchange's hourly USD bars per product with
`ts_known` = the bar's start + 1 h — through `coinbase.premium`: the USDT-adjusted premium in bps at each hour's end (Coinbase's close
over Binance's 5m close ending at the same stamp, the USDT-USD close divided out, the 1000× contract divided). The series per name is
put on a full hourly grid of `ts_known` (a missing hour is NaN; a value is carried over at most STALE missing hours). THREE bar × name
features on P2's 5m panel, each read at the bar t from the LAST hourly bar whose ts_known + MARGIN (one 5m bar, the serving lag's
margin) ≤ t — the grid's hour floor(t − 5 min):
    cbprem          the adjusted level — DESCRIBED, not gated (a series this slow is flattered by a day-shuffle null, R6; judged by
                    the shift null's p alone);
    cbprem_dev      = (cbprem − its mean over the trailing MONTH = 720 hourly bars, ≥ MIN_MONTH of them present) / the trailing sd —
                    THE registered feature (a name bid up on Coinbase against its own month);
    cbprem_chg_1d   = (cbprem − the premium LAG_1D = 24 hourly bars earlier) / the same sd — the second registered feature.
The names: LIQUID (8); every other column is NaN in the registered frames (ZEC / WLD are thin-book noise by the audit, PEPE / WLD /
HYPE have no F1+F2 bars). A DESCRIBED row (`<feature>_zec`) repeats the two features with ZEC's column in — no nulls, no verdict.
The frame is P2's exactly: `ceiling.panel` on the twelve, `derive`, F1+F2 embargoed as the scored sample, `ceiling.ic_screen`'s
statistics on every horizon; the bet of the question is the RELATIVE cross-sectional Spearman. Two nulls on each of the three features:
P2's day shuffles (`ceiling._null_feature`, seed 0 — the draws P2 made) and R6's whole-day circular shifts of the labels
(`book_ext.shift_feature`). The FAMILY = the two registered features × 4h / 1d on the relative bet — FOUR cells: per null the
family-wise p of a cell is the share of draws whose largest |t| over the four is at or above the cell's real |t|; `p_family` is the
larger of the two nulls'. Gate on each registered feature, relative, 1d: CLEARS if p_family ≤ 0.05 AND the IC is NEGATIVE (SIGN: a
name bid up on Coinbase has had its flow and gives back against its peers) AND the same sign in F1 and in F2 AND |IC| ≥ P2's #7
relative maker bar at 1d, recomputed here (`ceiling.bar_cost` / `move_vs_cost`); CLOSED if |IC| + 1.96 se < that bar; else NOT
DETECTABLE. The opposite sign with p_family ≤ 0.05 is "CLEARS WITH THE OPPOSITE SIGN" — a hypothesis, nothing licensed. 4h is
reported inside the family, not gated. Validity FIRST: (1) before any premium value is joined to a label — P2's `ret_1d` rows and
its day-shuffle null reproduce `output/ceiling/ic.parquet` and `noise_ic.parquet` to TOL; (2) known-at — on EVERY scored cell the
hourly bar used has ts_known + MARGIN ≤ t, and N_CHECK random scored cells of the registered names recomputed straight from the
premium rows equal the frame's values; (3) coverage — COVER_MIN per name on the scored cells, ≥ MIN_PAIRS names on ≥ 95 % of the
scored bars. FAIL on any → `validity.json` says so, exit 2, no row of the registered features is written. No confirmation fold is read.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import ceiling, coinbase as cb, folds
from .book_ext import SHIFT_MIN, fold_ics, shift_feature
from .ceiling import HORIZONS, MDE_K, MIN_PAIRS, NULL_HORIZONS, Z_CLIP, _null_feature

OUT_MD = Path("output/ceiling_coinbase.md")
OUT_DIR = Path("output/ceiling_coinbase")
SAVED = ceiling.OUT_DIR                   # P2's output/ceiling/: ic.parquet, noise_ic.parquet, move_vs_cost.parquet
P2_ROW = "ret_1d"                         # the P2 per-pair candle feature whose rows and null prove the frame is P2's
LVL, DEV, CHG = "cbprem", "cbprem_dev", "cbprem_chg_1d"
REGISTERED = (DEV, CHG)
LIQUID = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT"]
DESCRIBED_IN = ["ZECUSDT"]                # the described row adds these names (no nulls, no verdict)
COVER_MIN = {s: 0.90 for s in LIQUID} | {"XRPUSDT": 0.65}      # XRP relisted on Coinbase 2023-07-13: F1 70 % by the audit
BARS_MIN_SHARE = 0.95                     # the share of scored bars on which ≥ MIN_PAIRS registered names must be present
HOUR = pd.Timedelta("1h")
MARGIN = ceiling.BAR                      # one 5m bar after ts_known before the hourly bar may be read
MONTH = 30 * 24                           # the trailing month, in hourly bars
MIN_MONTH = MONTH // 2
LAG_1D = 24                               # hourly bars
STALE = 2                                 # a value is carried over at most this many missing hours
HZ = NULL_HORIZONS                        # 1h, 4h, 1d — the nulls' horizons
FAMILY_HZ = ("4h", "1d")
PRIMARY = "1d"
BET = "relative"
SIGN = -1.0                               # the registered sign: a name bid up on Coinbase gives back against its peers
N_CHECK = 2000
TOL = 1e-6
DRAWS = ceiling.DRAWS


# ---- the hourly series and the features ----------------------------------------------------------------------------------------------
def hourly(symbols: list[str], path: Path | str = cb.PARQUET) -> pd.DataFrame:
    """The adjusted premium (bps) per name on a full hourly grid of `ts_known` — NaN where the hour is missing; the names in
    `symbols` that have Coinbase rows, in `symbols`' order."""
    d = cb.load(path)
    d = d[d["symbol"].isna() | d["symbol"].isin(symbols)]
    stamps = pd.DatetimeIndex(sorted(d["ts_known"].unique()))
    have = [s for s in symbols if s in set(d["symbol"].dropna().astype(str))]
    bn = cb.binance_close_at(have, stamps) if have else pd.DataFrame(index=stamps)
    P = cb.premium(d, bn)
    W = P.pivot(index="ts_known", columns="symbol", values="prem_adj_bps")
    grid = pd.date_range(W.index.min().floor("h"), W.index.max().floor("h"), freq="h")
    return W.reindex(index=grid, columns=[s for s in have if s in W.columns])


def features_hourly(G: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """On the hourly grid: the level, its deviation from the trailing month, its 24-h change over the trailing sd. A window counts
    the bars present (≥ MIN_MONTH of MONTH); the lagged bar must itself be present."""
    m = G.rolling(MONTH, min_periods=MIN_MONTH).mean()
    sd = G.rolling(MONTH, min_periods=MIN_MONTH).std()
    return {LVL: G, DEV: (G - m) / sd, CHG: (G - G.shift(LAG_1D)) / sd}


def keys(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The hourly bar read at each 5m bar t: the last ts_known with ts_known + MARGIN ≤ t."""
    return (idx - MARGIN).floor("h")


def to_panel(H: pd.DataFrame, idx: pd.DatetimeIndex, cols: list[str]) -> pd.DataFrame:
    """A grid frame → P2's 5m panel on `cols` (NaN columns for names without the source), a value carried over ≤ STALE missing hours."""
    out = H.ffill(limit=STALE).reindex(keys(idx))
    out.index = idx
    return out.reindex(columns=cols)


def used_hours(G: pd.DataFrame, idx: pd.DatetimeIndex, cols: list[str]) -> pd.DataFrame:
    """Per 5m cell: the ts_known actually used, in whole hours since the epoch (NaN where no bar is within STALE hours)."""
    h = (G.index.asi8 // 3_600_000_000_000).astype(float)
    U = pd.DataFrame({c: np.where(G[c].notna(), h, np.nan) for c in G.columns}, index=G.index)
    return to_panel(U, idx, cols)


def features(idx: pd.DatetimeIndex, cols: list[str], names: list[str], path: Path | str = cb.PARQUET) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """(the three 5m frames on `cols` for the names in `names` that have the source, the used-hour frame, the hourly grid)."""
    G = hourly(names, path)
    H = features_hourly(G)
    return {k: to_panel(v, idx, cols) for k, v in H.items()}, used_hours(G, idx, cols), G


def restrict(F: dict[str, pd.DataFrame], names: list[str]) -> dict[str, pd.DataFrame]:
    """The frames with every column outside `names` set to NaN (the registered set; the described set)."""
    return {k: v.where(np.broadcast_to(v.columns.isin(names)[None, :], v.shape)) for k, v in F.items()}


# ---- validity ------------------------------------------------------------------------------------------------------------------------
def reproduction(sc: pd.DataFrame, null: pd.DataFrame, saved: Path = SAVED, feature: str = P2_ROW, tol: float = TOL) -> dict:
    """P2's row `feature` against P2's saved screen: every bet × horizon's ic and t (`ic.parquet`) and the day-shuffle null's ic and t
    per draw (`noise_ic.parquet`, the draws this run made)."""
    if not (saved / "ic.parquet").exists() or not (saved / "noise_ic.parquet").exists():
        return {"status": "MISSING", "note": f"{saved}/ic.parquet or noise_ic.parquet not found"}
    key = ["bet", "horizon", "feature"]
    old = pd.read_parquet(saved / "ic.parquet")
    old = old[old["feature"] == feature].set_index(key)
    new = sc[sc["feature"] == feature].set_index(key)
    j = new[["ic", "t"]].join(old[["ic", "t"]], rsuffix="_p2", how="inner")
    diff = {c: float((j[c] - j[f"{c}_p2"]).abs().max()) if len(j) else np.nan for c in ("ic", "t")}
    oldn = pd.read_parquet(saved / "noise_ic.parquet")
    oldn = oldn[(oldn["feature"] == feature) & (oldn["draw"] > 0)].set_index([*key, "draw"])
    newn = null[null["draw"] > 0].set_index([*key, "draw"])
    jn = newn[["ic", "t"]].join(oldn[["ic", "t"]], rsuffix="_p2", how="inner").dropna()
    diff |= {f"null_{c}": float((jn[c] - jn[f"{c}_p2"]).abs().max()) if len(jn) else np.nan for c in ("ic", "t")}
    ok = len(j) == len(old) > 0 and len(jn) == len(newn.dropna()) > 0 and all(np.isfinite(v) and v <= tol for v in diff.values())
    return {"status": "PASS" if ok else "FAIL", "feature": feature, "rows_compared": int(len(j)), "rows_p2": int(len(old)),
            "null_rows_compared": int(len(jn)), "null_rows_this_run": int(len(newn.dropna())), "max_abs_diff": diff}


def recompute_cell(g: pd.Series, t: pd.Timestamp) -> tuple[float, float, float, float]:
    """(level, dev, chg, the used hour) at the 5m bar t straight from one name's premium rows `g` (indexed by ts_known, the rows
    present), with the module's definitions applied by hand: the last row with ts_known ≤ t − MARGIN and not older than STALE hours
    after it; the trailing MONTH grid bars ending at that row (≥ MIN_MONTH present) for the mean and sd; the row LAG_1D hours earlier."""
    key = (t - MARGIN).floor("h")
    before = g.loc[:key]
    if before.empty or key - before.index[-1] > STALE * HOUR:
        return np.nan, np.nan, np.nan, np.nan
    k0, v = before.index[-1], float(before.iloc[-1])
    win = before.loc[k0 - (MONTH - 1) * HOUR:]
    used = float(k0.value // 3_600_000_000_000)
    if len(win) < MIN_MONTH:
        return v, np.nan, np.nan, used
    m, sd = float(win.mean()), float(win.std(ddof=1))
    prev = g.get(k0 - LAG_1D * HOUR, np.nan)
    return v, (v - m) / sd, (v - float(prev)) / sd, used


def known_at(F: dict[str, pd.DataFrame], U: pd.DataFrame, G: pd.DataFrame, s: np.ndarray, names: list[str], n_check: int = N_CHECK,
             seed: int = 0, tol: float = 1e-9) -> dict:
    """Validity (2): on every scored cell with a value the hourly bar used has ts_known + MARGIN ≤ t (asserted); `n_check` random
    scored cells of `names` recomputed by `recompute_cell` equal the frames' values (NaN = NaN)."""
    idx = F[LVL].index[s]
    th = ((idx - MARGIN).asi8 // 3_600_000_000_000).astype(float)        # the latest hour whose bar may be read at t
    cols = [c for c in names if c in F[LVL].columns]
    Us = U[s][cols].to_numpy()
    has = F[LVL][s][cols].notna().to_numpy()
    late = has & ~(Us <= th[:, None])
    stale = has & (th[:, None] - Us > STALE)
    rng = np.random.default_rng(seed)
    ii, jj = rng.integers(0, len(idx), n_check), rng.integers(0, len(cols), n_check)
    series = {c: G[c].dropna() for c in cols if c in G.columns}
    worst = 0.0
    for i, j in zip(ii, jj):
        c, t = cols[j], idx[i]
        got = [float(F[k][c].loc[t]) for k in (LVL, DEV, CHG)] + [float(U[c].loc[t])]
        exp = recompute_cell(series[c], t) if c in series else (np.nan,) * 4
        for a, b in zip(got, exp):
            worst = max(worst, 0.0 if np.isnan(a) and np.isnan(b) else abs(a - b) if np.isfinite(a) and np.isfinite(b) else np.inf)
    ok = not late.any() and not stale.any() and worst <= tol
    return {"status": "PASS" if ok else "FAIL", "cells_with_a_value": int(has.sum()), "cells_read_too_early": int(late.sum()),
            "cells_older_than_stale": int(stale.sum()), "recomputed": int(n_check), "max_abs_diff": float(worst), "margin": str(MARGIN), "stale_hours": STALE}


def coverage(F: dict[str, pd.DataFrame], s: np.ndarray, cover_min: dict[str, float] = COVER_MIN, min_pairs: int = MIN_PAIRS,
             bars_min_share: float = BARS_MIN_SHARE) -> dict:
    """Validity (3): the registered features' share of the scored cells per name against `cover_min`; the share of scored bars with
    ≥ `min_pairs` names present."""
    both = F[DEV][s].notna() & F[CHG][s].notna()
    by_name = {c: round(float(both[c].mean()), 4) for c in cover_min if c in both.columns}
    short = {c: v for c, v in by_name.items() if v < cover_min[c]} | {c: 0.0 for c in cover_min if c not in both.columns}
    bars = float((both.sum(axis=1) >= min_pairs).mean())
    ok = not short and bars >= bars_min_share
    return {"status": "PASS" if ok else "FAIL", "by_name": by_name, "under_minimum": short, "min_by_name": cover_min,
            "bars_with_min_pairs": round(bars, 4), "bars_min_share": bars_min_share}


# ---- the family, the verdict -----------------------------------------------------------------------------------------------------
def family_p(null: pd.DataFrame, cells: list[tuple[str, str]], t_real: dict[tuple[str, str], float], bet: str = BET) -> tuple[dict, dict]:
    """(the family-wise p per cell, the null's bar): per draw the largest |t| over `cells` ((feature, horizon) on `bet`)."""
    nz = null[(null["draw"] > 0) & (null["bet"] == bet)].dropna(subset=["t"])
    nz = nz[np.array([(f, h) in cells for f, h in zip(nz["feature"], nz["horizon"])], dtype=bool)]
    mx = nz.assign(a=nz["t"].abs()).groupby("draw")["a"].max()
    pf = {c: (1 + int((mx >= abs(t)).sum())) / (len(mx) + 1) for c, t in t_real.items()}
    return pf, {"bar_t_mean": float(mx.mean()), "bar_t_p95": float(mx.quantile(0.95)), "draws": int(len(mx))}


def single_p(null: pd.DataFrame, bet: str, feature: str, h: str, t: float) -> float:
    own = null[(null["draw"] > 0) & (null["bet"] == bet) & (null["feature"] == feature) & (null["horizon"] == h)]["t"].abs().dropna()
    return (1 + int((own >= abs(t)).sum())) / (len(own) + 1) if len(own) else np.nan


def verdict(ic: float, se: float, p_family: float, same_sign_folds: bool, bar: float) -> str:
    if p_family <= 0.05 and same_sign_folds and abs(ic) >= bar:
        return "CLEARS" if ic * SIGN > 0 else "CLEARS WITH THE OPPOSITE SIGN"
    if abs(ic) + 1.96 * se < bar:
        return "CLOSED"
    return "NOT DETECTABLE"


def describe_names(F: dict[str, pd.DataFrame], s: np.ndarray, names: list[str]) -> pd.DataFrame:
    """Per name on the scored cells: the level's mean and sd, the registered features' sd, the coverage."""
    rows = []
    for c in names:
        if c not in F[LVL].columns:
            continue
        lv, dv, ch = (F[k][s][c] for k in (LVL, DEV, CHG))
        rows.append({"symbol": c, "cells": int(lv.notna().sum()), "lvl_mean_bps": lv.mean(), "lvl_sd_bps": lv.std(), "dev_sd": dv.std(), "chg_sd": ch.std(),
                     "cover_dev": float(dv.notna().mean()), "cover_chg": float(ch.notna().mean())})
    return pd.DataFrame(rows)


# ---- the run --------------------------------------------------------------------------------------------------------------------------
def run(taker_bps: float, maker_bps: float, fee_source: str, symbols: list[str], draws: int = DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN,
        saved: Path = SAVED, jobs: int = 1, path: Path | str = cb.PARQUET, liquid: list[str] = LIQUID, described_in: list[str] = DESCRIBED_IN,
        cover_min: dict[str, float] = COVER_MIN, n_check: int = N_CHECK, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    from joblib import Parallel, delayed
    out_dir.mkdir(parents=True, exist_ok=True)
    print("panel…", flush=True)
    P = ceiling.panel(symbols)
    D = ceiling.derive(P)
    idx, cols, s = D["lr"].index, list(D["lr"].columns), D["scored"]
    sidx = idx[s]
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}
    validity = {"registration": "R60", "folds": list(folds.EXPLORATION), "scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))),
                "pairs": cols, "registered_names": [c for c in liquid if c in cols], "first": str(sidx[0]), "last": str(sidx[-1]), "draws": draws,
                "seed": seed, "shift_min": shift_min, "source": str(path)}

    # validity (1) FIRST, before any premium value is joined to a label: P2's ret_1d row and its null against P2's saved screen
    print(f"validity (1): P2's `{P2_ROW}` row, its {draws} day shuffles, against {saved}/…", flush=True)
    f_p2 = ceiling.dir_features(D)[P2_ROW]
    sc_p2, daily_p2 = ceiling.ic_screen(D, {P2_ROW: f_p2}, set())
    null_p2 = _null_feature(P2_ROW, f_p2[s], Zs, Zr, draws, seed)
    validity["reproduction"] = reproduction(sc_p2, null_p2, saved)
    if validity["reproduction"]["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source, sidx, s, cols)

    # the source → the three frames; validity (2) known-at and (3) coverage on the registered names, before any IC of theirs
    print("the hourly premium → the three frames…", flush=True)
    F_all, U, G = features(idx, cols, liquid + described_in, path)
    F = restrict(F_all, liquid)
    validity["known_at"] = known_at(F, U, G, s, liquid, n_check, seed)
    validity["coverage"] = coverage(F, s, cover_min)
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in ("reproduction", "known_at", "coverage")) else "FAIL"
    if validity["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source, sidx, s, cols)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    head = _head(validity, taker_bps, maker_bps, fee_source, sidx, s, cols)

    # the screen: the level and the two registered features on the registered names; the described row with ZEC in
    print("screen: the level, the deviation, the 24-h change; the described row…", flush=True)
    sc_new, daily_new = ceiling.ic_screen(D, F, set())
    F_desc = restrict(F_all, liquid + described_in)
    sc_desc, daily_desc = ceiling.ic_screen(D, {f"{k}_zec": F_desc[k] for k in REGISTERED}, set())
    sc, daily = pd.concat([sc_p2, sc_new, sc_desc], ignore_index=True), pd.concat([daily_p2, daily_new, daily_desc], ignore_index=True)
    print(f"nulls: {draws} day shuffles (P2's) and {draws} whole-day shifts (R6's) on three features…", flush=True)
    null_shuffle = pd.concat([null_p2, *Parallel(n_jobs=jobs)(delayed(_null_feature)(k, F[k][s], Zs, Zr, draws, seed) for k in (LVL, DEV, CHG))], ignore_index=True)
    null_shift = pd.concat(Parallel(n_jobs=jobs)(delayed(shift_feature)(k, F[k], D, s, draws, seed, shift_min) for k in (LVL, DEV, CHG)), ignore_index=True)

    # the bar: P2's #7 recomputed on the twelve, the relative rows
    print("#7 the bar…", flush=True)
    ct, cm = ceiling.bar_cost(idx, cols, taker_bps, maker_bps)
    mv, _ = ceiling.move_vs_cost(D, ct, cm)
    bars = mv[mv["bet"] == BET].set_index("horizon")
    saved_mv = pd.read_parquet(saved / "move_vs_cost.parquet") if (saved / "move_vs_cost.parquet").exists() else None

    # the rows
    rows = sc.merge(fold_ics(daily), on=["bet", "horizon", "feature"], how="left")
    rows["ic_se"] = rows["ic_mde"] / MDE_K
    rows["bar_maker"] = rows["horizon"].map(bars["ic_needed_maker"])
    rows["bar_taker"] = rows["horizon"].map(bars["ic_needed_taker"])
    for c in ("p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift"):
        rows[c] = np.nan
    for i, r in rows.iterrows():
        if r["feature"] in (LVL, DEV, CHG, P2_ROW) and r["bet"] in ("directional", "relative") and r["horizon"] in HZ:
            rows.loc[i, "p_single_shuffle"] = single_p(null_shuffle, r["bet"], r["feature"], r["horizon"], r["t"])
            rows.loc[i, "p_single_shift"] = single_p(null_shift, r["bet"], r["feature"], r["horizon"], r["t"]) if r["feature"] != P2_ROW else np.nan
    cells = [(f, h) for f in REGISTERED for h in FAMILY_HZ]
    fam_rows = rows[(rows["bet"] == BET) & np.array([(f, h) in cells for f, h in zip(rows["feature"], rows["horizon"])])]
    t_real = {(r["feature"], r["horizon"]): r["t"] for _, r in fam_rows.iterrows()}
    pf1, b1 = family_p(null_shuffle, cells, t_real)
    pf2, b2 = family_p(null_shift, cells, t_real)
    for i, r in fam_rows.iterrows():
        rows.loc[i, ["p_fw_shuffle", "p_fw_shift"]] = [pf1[r["feature"], r["horizon"]], pf2[r["feature"], r["horizon"]]]
    rows["p_family"] = rows[["p_fw_shuffle", "p_fw_shift"]].max(axis=1)
    rows["verdict"] = ""
    for i, r in rows.loc[fam_rows.index].iterrows():
        v = verdict(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), r["bar_maker"])
        rows.loc[i, "verdict"] = v if r["horizon"] == PRIMARY else v + " (reported, not gated)"
    rows.loc[rows["feature"] == LVL, "verdict"] = "described (the level; the shift null's p)"
    rows.loc[rows["feature"] == P2_ROW, "verdict"] = "validity (P2's row)"
    rows.loc[rows["feature"].str.endswith("_zec"), "verdict"] = "described (ZEC in, no nulls)"
    desc = describe_names(F_all, s, liquid + described_in)

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    mv.to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    desc.to_parquet(out_dir / "names.parquet", index=False)

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker", "bar_taker", "verdict"]
    g = {f: rows[(rows["feature"] == f) & (rows["bet"] == BET) & (rows["horizon"] == PRIMARY)].iloc[0] for f in REGISTERED}
    md = head + [f"\n## Verdict by R60's gate — {BET}, {PRIMARY}: " + "; ".join(f"`{f}` **{g[f]['verdict']}**" for f in REGISTERED) + "\n"]
    for f in REGISTERED:
        r = g[f]
        md.append(f"\n`{f}`: IC {r['ic']:+.4f} (t {r['t']:+.2f}, se {r['ic_se']:.4f}, MDE {r['ic_mde']:.4f}); p_family {r['p_family']:.3f} (day shuffles "
                  f"{r['p_fw_shuffle']:.3f}, whole-day shifts {r['p_fw_shift']:.3f}; single {r['p_single_shuffle']:.3f} / {r['p_single_shift']:.3f}); F1 {r['ic_F1']:+.4f}, "
                  f"F2 {r['ic_F2']:+.4f} ({'same sign' if r['folds_same_sign'] else 'signs differ'}); months the same sign {r['months_same_sign']:.2f}; the bar "
                  f"{r['bar_maker']:.4f} maker / {r['bar_taker']:.4f} taker; the registered sign {'negative' if SIGN < 0 else 'positive'}.\n")
    fam = rows["feature"].isin([LVL, DEV, CHG]) & rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])
    md += ["\n## The family (relative, 4h / 1d) with the level and the directional bet beside — the nulls' horizons\n",
           "`p_fw_*` = the share of a null's draws whose largest |t| over the FOUR family cells is at or above the real |t| (family cells only); `p_single_*` = the cell "
           "alone; `p_family` = the larger of the two nulls' family-wise p. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. Bars: P2's #7 "
           f"`ic_needed` on the {BET} bet at the horizon, recomputed on the twelve; the gate compares |IC| with `bar_maker` at {PRIMARY}.\n",
           show(rows[fam][cols_show]), "\n",
           "\n## Everything else (reported): 15m, the vol bet, P2's validity row, the described row with ZEC in\n",
           show(rows[~fam][cols_show[:12] + ["verdict"]]), "\n",
           "\n## The nulls' family bars (largest |t| over the four cells, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           "\n## The names on the scored cells\n", show(desc), "\n",
           f"\n## #7 the bar, recomputed ({BET})\n", show(mv[mv["bet"] == BET][["horizon", "cells", "abs_move_mean", "taker_rt", "maker_rt", "ic_needed_taker", "ic_needed_maker"]]), "\n"]
    if saved_mv is not None:
        sm = saved_mv[(saved_mv["bet"] == BET) & (saved_mv["horizon"] == PRIMARY)].iloc[0]
        md.append(f"\nP2's saved bar at {PRIMARY}: maker {sm['ic_needed_maker']:.4f}, taker {sm['ic_needed_taker']:.4f} (this run: {bars.loc[PRIMARY, 'ic_needed_maker']:.4f} / {bars.loc[PRIMARY, 'ic_needed_taker']:.4f}).\n")
    out_md.write_text("".join(md))
    print("; ".join(f"{f} {BET} {PRIMARY}: {g[f]['verdict']}" for f in REGISTERED) + f"; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


def _head(validity: dict, taker_bps, maker_bps, fee_source, sidx, s, cols) -> list[str]:
    return [f"# R60 — the Coinbase spot premium per name, a ceiling screen on the twelve (`ft2 ceiling --target pairs --family coinbase`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed), P2's cells; every source cut at {ceiling.END:%Y-%m-%d}. Scored bars "
            f"{sidx[0]:%Y-%m-%d} → {sidx[-1]:%Y-%m-%d} ({int(s.sum()):,} × {len(cols)} pairs; the registered names {', '.join(validity['registered_names'])}). "
            f"Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source, sidx, s, cols):
    validity["status"] = "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head(validity, taker_bps, maker_bps, fee_source, sidx, s, cols) + ["\n**The read is VOID: no row of the registered features was computed.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)
