"""R67 (docs/PLAN.md §8, decision BG's BG1, registered 2026-10-22): the Coinbase deviation `cbprem_dev` at a 3- and 7-day hold on the
members' F1+F2 cells — R62's frame, list and checks (`cb_ext.frames`, `known_at`, `block_coverage`; none edited), the long labels
appended beside P2's four horizons in `ceiling.derive`'s form (`extend`), the IC through `ceiling.ic_screen` with the horizon dictionary
as an argument, both nulls at the two holds (the day-shuffle gap raised to GAP = 15 ≥ the 1w lookback + the 7d label; the shifts
≥ SHIFT_MIN = 60 > the 30-day window + 7), the gate R62's with the TWELVE's relative maker bar at each hold computed in the run from
`ceiling.panel(twelve)`'s own |move| (`bars_twelve`; the same code must give R60's saved 1d bar within BAR_TOL) and the threshold halved
to P_FAMILY = 0.025 — the price of setting R62's "no other horizon on these cells" clause aside once. Validity in order, before any long
label is joined to a member's deviation: (1) the lists, (2) R62's six features' saved rows through the extended path at the OLD horizons
(`reproduction_r62`), (3) 2,000 long labels by hand and no label at or past the panel's end (`label_check`), (4) the bars, (5) known-at,
(6) membership and coverage, (7) the nulls' gaps. Described beside, no gate (BG2): R61's money-shape rows on the members at 1d and 3d —
deciles of the rank, R61's sd buckets, the top-minus-bottom unit at every bar and at the daily bar net of the members' TAKER (the proxy's
two round trips) and of the ratio-maker (RATIO_MAKER × it, fact (xxix) — an estimate), the tails' medians, R61's triggers — and R61's
decision line with the taker as the cost ("worth its own registration" only at ≥ NET_BAR net taker with u ≥ U_BAR on ≥ MIN_DAYS days and
both folds' gross positive). The 1d row of the same frame is reported beside the family (R62's number, reproduced), not a cell of it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import ceiling, coinbase as cb, folds
from .book_ext import SHIFT_MIN, fold_ics, shift_feature, taker_bar
from .cb_ext import (BAR_TOL, BAR_TWELVE, BET, BLOCK_MIN_NAMES, CHG, DEV, DRAWS, LVL, MEMBERS_OUT_DIR, MEMBERS_SLICES, MEMBERS_START, N_CHECK,
                     OUT_DIR as R60_DIR, PRIMARY, R62_CSV, R62_SIGN, THIN, TIGHT, VOL, block_coverage, block_ics, family_p, frames, known_at,
                     r62_list, reproduction_r62, screen_frames_r62, single_p)
from .ceiling import HORIZONS, MDE_K, MIN_PAIRS, W, Z_CLIP, _null_feature, day_lags, hac

HOLDS = {"3d": 864, "7d": 2016}                      # the registered holds, in 5m bars
ALL_H = {**HORIZONS, **HOLDS}                        # P2's four and the two holds, in one dictionary
FAMILY = ("3d", "7d")                                # the family: DEV × 3d / 7d, relative
GAP = 15                                             # the day-shuffle gap: ≥ the 1w lookback (7 d) + the 7d label
P_FAMILY = 0.025                                     # the halved threshold — R62's clause's price
RATIO_MAKER = 0.48                                   # the members' maker bar as a share of their taker bar (fact (xxix); an estimate)
EXPECTED = {"maker": {"3d": 0.009, "7d": 0.006}, "taker": {"3d": 0.020, "7d": 0.0125}}       # written at registration, checked by eye
OUT_MD = Path("output/ceiling_hold_members.md")
OUT_DIR = Path("output/ceiling_hold_members")
BG2_H = ("1d", "3d")                                 # the description's horizons
EDGES = [-np.inf, -2.0, -1.0, 0.0, 1.0, 2.0, np.inf]                                        # R61's sd buckets
LABELS = ["≤ −2", "−2 … −1", "−1 … 0", "0 … 1", "1 … 2", "≥ 2"]
TOP_THETAS = (0.5, 1.0, 1.5, 2.0)
GAP_THETAS = (1.0, 2.0, 3.0, 4.0)
NAMED = (("top", 1.0), ("gap", 2.0))
DAILY = (0, 5)                                       # the daily decision bar a rule would use: 00:05 UTC
NET_BAR, U_BAR, MIN_DAYS = 15.0, 1.0, 100            # R61's bar, with the members' taker as the cost
TOL_LABEL = 1e-9


def _md5(path: Path | str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ---- the long labels -----------------------------------------------------------------------------------------------------------------------
def extend(D: dict, holds: dict[str, int] = HOLDS) -> dict:
    """`ceiling.derive`'s label dictionaries with the holds appended: fwd = (lr.shift(−k) − lr) × 1e4, res = fwd − the basket, z = fwd /
    (sig_1w × √k), zres = z − its basket — the 1d label's form at k = 864 / 2,016; NaN wherever t + k lies past the panel's end."""
    lr, sig = D["lr"], D["sig"]["1w"]
    for h, k in holds.items():
        f = (lr.shift(-k) - lr) * 1e4
        D["fwd"][h] = f
        D["res"][h] = f.sub(ceiling.basket(f), axis=0)
        z = f / (sig * np.sqrt(k))
        D["z"][h] = z
        D["zres"][h] = z.sub(ceiling.basket(z), axis=0)
    return D


def label_check(D: dict, P: dict, s: np.ndarray, n_check: int = N_CHECK, seed: int = 0, holds: dict[str, int] = HOLDS, end: pd.Timestamp = ceiling.END,
                tol: float = TOL_LABEL) -> dict:
    """Validity (3): `n_check` random scored cells with a label at each hold recomputed from the panel's close — ln(close[t + k] / close[t])
    × 1e4; the relative = the cell's minus the bar's mean over the names with a label (≥ MIN_PAIRS); the z = the label over the sd of the last
    2,016 one-bar returns × √k — to `tol`; on every bar the label is NaN wherever t + k is at or past the panel's end; the panel ends at
    or before `end`."""
    rng = np.random.default_rng(seed)
    C = P["close"]
    idx, cols = D["lr"].index, list(D["lr"].columns)
    n = len(idx)
    r1 = D["r1"].to_numpy()
    out = {"status": "PASS", "panel_end": str(idx[-1]), "end": str(end), "panel_ends_in_time": bool(idx[-1] <= end), "holds": {}}
    for h, k in holds.items():
        F, R, Z = D["fwd"][h], D["res"][h], D["z"][h]
        tail_nan = bool(F.iloc[n - k:].notna().to_numpy().sum() == 0) if k <= n else bool(F.notna().to_numpy().sum() == 0)
        has = np.flatnonzero(s & F.notna().any(axis=1).to_numpy())
        pick = rng.choice(has, size=min(n_check, len(has)), replace=False) if len(has) else np.array([], dtype=int)
        dmax = {"fwd": 0.0, "res": 0.0, "z": 0.0}
        done = 0
        for i in pick:
            js = np.flatnonzero(F.iloc[i].notna().to_numpy())
            if not len(js):
                continue
            j = int(rng.choice(js))
            c0, c1 = float(C.iat[i, j]), float(C.iat[i + k, j])
            f_hand = np.log(c1 / c0) * 1e4
            row = F.iloc[i].to_numpy()
            ok = ~np.isnan(row)
            r_hand = f_hand - row[ok].mean() if ok.sum() >= MIN_PAIRS else np.nan
            w = r1[i - W["1w"] + 1:i + 1, j]
            w = w[~np.isnan(w)]
            sd = np.std(w, ddof=1) if len(w) >= int(W["1w"] * 0.8) else np.nan
            z_hand = f_hand / (sd * np.sqrt(k)) if np.isfinite(sd) else np.nan
            for key, hand, got in (("fwd", f_hand, float(F.iat[i, j])), ("res", r_hand, float(R.iat[i, j])), ("z", z_hand, float(Z.iat[i, j]))):
                d = 0.0 if (np.isnan(hand) and np.isnan(got)) else abs(hand - got)
                dmax[key] = max(dmax[key], float(d) if np.isfinite(d) else np.inf)
            done += 1
        ok_h = tail_nan and done > 0 and all(v <= tol for v in dmax.values())
        out["holds"][h] = {"status": "PASS" if ok_h else "FAIL", "bars": k, "recomputed": done, "max_abs_diff": dmax, "tail_all_nan": tail_nan,
                           "cells_with_a_label": int(F[s].notna().to_numpy().sum())}
        if not ok_h:
            out["status"] = "FAIL"
    if not out["panel_ends_in_time"]:
        out["status"] = "FAIL"
    return out


# ---- the bars at the holds ----------------------------------------------------------------------------------------------------------------
def bars_twelve(twelve: list[str], taker_bps: float, maker_bps: float, holds: dict[str, int] = HOLDS, r60: Path = R60_DIR, tol: float = BAR_TOL) -> tuple[dict, pd.DataFrame]:
    """The twelve's relative bars at every horizon and hold — P2's #7 on `ceiling.panel(twelve)`'s F1+F2 cells with the measured maker
    (`move_vs_cost`'s formula, the horizon dictionary extended). Validity (4): the 1d maker bar equals R60's saved within `tol`."""
    P = ceiling.panel(twelve)
    D = extend(ceiling.derive(P), holds)
    ct, cm = ceiling.bar_cost(D["lr"].index, list(D["lr"].columns), taker_bps, maker_bps)
    mv, _ = ceiling.move_vs_cost(D, ct, cm, {**HORIZONS, **holds})
    rel = mv[mv["bet"] == BET].set_index("horizon")
    saved = pd.read_parquet(r60 / "move_vs_cost.parquet") if (r60 / "move_vs_cost.parquet").exists() else None
    saved_1d = np.nan
    if saved is not None:
        sm = saved[(saved["bet"] == BET) & (saved["horizon"] == PRIMARY)]
        saved_1d = float(sm["ic_needed_maker"].iloc[0]) if len(sm) else np.nan
    got_1d = float(rel.loc[PRIMARY, "ic_needed_maker"])
    ok = np.isfinite(saved_1d) and abs(got_1d - saved_1d) <= tol
    return {"status": "PASS" if ok else ("MISSING" if saved is None else "FAIL"), "bar_1d_this_run": got_1d, "bar_1d_r60_saved": saved_1d, "bar_twelve_constant": BAR_TWELVE,
            "maker": {h: float(rel.loc[h, "ic_needed_maker"]) for h in rel.index}, "taker_twelve": {h: float(rel.loc[h, "ic_needed_taker"]) for h in rel.index},
            "abs_move_mean": {h: float(rel.loc[h, "abs_move_mean"]) for h in rel.index}, "expected": EXPECTED}, mv


# ---- the verdict -----------------------------------------------------------------------------------------------------------------------------
def verdict_r67(ic: float, se: float, p_family: float, same_sign_folds: bool, bar: float, p_max: float = P_FAMILY, sign: float = R62_SIGN) -> str:
    """R62's verdict with the threshold as an argument (P_FAMILY = 0.025, the clause's price) and the bar at the hold."""
    if p_family <= p_max and same_sign_folds and abs(ic) >= bar:
        return "CLEARS" if ic * sign > 0 else "CLEARS WITH THE OPPOSITE SIGN"
    if abs(ic) + 1.96 * se < bar:
        return "CLOSED"
    return "NOT DETECTABLE"


# ---- BG2: R61's money shape on the members -------------------------------------------------------------------------------------------------
def labels_members(D: dict, dev: pd.DataFrame, s: np.ndarray, h: str, ct: pd.DataFrame) -> dict:
    """On the scored bars: the forward return at `h` (bps), the deviation (member cells only), the relative label centred on the names
    present with both (≥ MIN_PAIRS), the taker round trip per cell from the proxy, the day index, the HAC lags."""
    idx = D["lr"].index[s]
    fwd, dv, c = D["fwd"][h][s], dev[s], ct[s]
    ok = dv.notna() & fwd.notna()
    n = ok.sum(axis=1)
    ok = ok.where(n >= MIN_PAIRS, False)
    fwd, dv = fwd.where(ok), dv.where(ok)
    rel = fwd.sub(fwd.mean(axis=1), axis=0)
    day = (idx.floor("D") - idx[0].floor("D")).days.to_numpy()
    return {"h": h, "idx": idx, "fwd": fwd, "rel": rel, "dev": dv, "ct": c.where(ok), "n": n.where(n >= MIN_PAIRS), "day": day, "lags": day_lags(ALL_H[h])}


def _daily(x: pd.Series, day: np.ndarray) -> np.ndarray:
    return x.groupby(day).mean().reindex(range(int(day.max()) + 1)).to_numpy()


def _stat(x: pd.Series, day: np.ndarray, lags: int) -> dict:
    dm = _daily(x, day)
    _, se, nd = hac(dm, lags)
    m = float(np.nanmean(dm)) if np.isfinite(dm).any() else np.nan
    return {"mean": m, "se": se, "u": m / se if se else np.nan, "days": nd, "cells": int(x.notna().sum())}


def _fold_means(x: pd.Series, idx: pd.DatetimeIndex, day: np.ndarray, lags: int, daily: bool = False) -> dict:
    out = {}
    for f in folds.EXPLORATION:
        a, b = folds.bounds(f)
        m = np.asarray((idx >= a) & (idx < b))
        if not m.any():
            out[f"gross_{f}"] = np.nan
        elif daily:
            out[f"gross_{f}"] = hac(x[m].dropna().to_numpy(), lags)[0]
        else:
            out[f"gross_{f}"] = hac(_daily(x[m], day[m] - day[m].min()), lags)[0]
    return out


def by_decile(L: dict) -> pd.DataFrame:
    """Decile 1 (the highest deviation among the names present at the bar) … 10: the bar's mean relative label over the decile's cells,
    the daily mean, HAC; the top-minus-bottom spread and the linear fit's spread."""
    dv, rel, day = L["dev"], L["rel"], L["day"]
    rk = dv.rank(axis=1, ascending=False, pct=True)
    dec = np.ceil(rk * 10).clip(1, 10)
    rows = []
    for d in range(1, 11):
        m = dec == d
        v = rel.where(m).sum(axis=1) / m.sum(axis=1).replace(0, np.nan)
        rows.append({"decile": d, **_stat(v, day, L["lags"]), "cells": int(m.to_numpy().sum())})
    out = pd.DataFrame(rows)
    slope = np.polyfit(out["decile"], out["mean"], 1)[0] if out["mean"].notna().all() else np.nan
    out["linear_spread"] = -slope * 9
    out["top_minus_bottom"] = out["mean"].iloc[0] - out["mean"].iloc[-1]
    return out


def by_bucket(L: dict) -> pd.DataFrame:
    dv, rel, fwd, day = L["dev"], L["rel"], L["fwd"], L["day"]
    cells = int(dv.notna().to_numpy().sum())
    rows = []
    for lo, hi, lab in zip(EDGES[:-1], EDGES[1:], LABELS):
        m = (dv >= lo) & (dv < hi)
        cnt = m.sum(axis=1).replace(0, np.nan)
        v = rel.where(m).sum(axis=1) / cnt
        a = fwd.abs().where(m).sum(axis=1) / cnt
        med = float(np.nanmedian(rel.where(m).to_numpy())) if m.to_numpy().any() else np.nan
        rows.append({"bucket": lab, **_stat(v, day, L["lags"]), "cells": int(m.to_numpy().sum()), "share": float(m.to_numpy().sum() / max(cells, 1)),
                     "median_rel": med, "abs_move_mean": float(np.nanmean(a)) if np.isfinite(a).any() else np.nan})
    return pd.DataFrame(rows)


def unit_series(L: dict) -> pd.DataFrame:
    """Per scored bar with ≥ MIN_PAIRS names: the top name's forward return minus the bottom's, their deviations, the two names' taker
    round trips from the proxy (NaN where a name has no cost)."""
    dv, fwd, c = L["dev"], L["fwd"], L["ct"]
    has = dv.notna().sum(axis=1) >= MIN_PAIRS
    filled = dv.where(has, 0.0).fillna(-np.inf)
    top, bot = filled.idxmax(axis=1), filled.replace(-np.inf, np.inf).idxmin(axis=1)
    ii = np.arange(len(dv))
    tj, bj = dv.columns.get_indexer(top.fillna(dv.columns[0])), dv.columns.get_indexer(bot.fillna(dv.columns[0]))
    f, d, cc = fwd.to_numpy(), dv.to_numpy(), c.to_numpy()
    w = lambda a: pd.Series(a, index=L["idx"]).where(has)                 # noqa: E731
    return pd.DataFrame({"spread": w(f[ii, tj] - f[ii, bj]), "top_ret": w(f[ii, tj]), "bottom_ret": w(f[ii, bj]), "top": top.where(has), "bottom": bot.where(has),
                         "top_dev": w(d[ii, tj]), "bottom_dev": w(d[ii, bj]), "cost_taker": w(cc[ii, tj] + cc[ii, bj]), "day": L["day"]})


def unit_stats(u: pd.DataFrame, lags: int, daily: bool, ratio: float = RATIO_MAKER) -> dict:
    """Gross, net of the two names' taker round trips and of `ratio` × them; se, u, days, the folds, the share of positive days, the
    medians of the spread and of each leg's return."""
    x, c = u["spread"], u["cost_taker"]
    nt, nm = x - c, x - ratio * c
    if daily:
        m, se, nd = hac(x.dropna().to_numpy(), lags)
        st = {"gross": m, "se": se, "u": m / se if se else np.nan, "days": nd, "cells": int(x.notna().sum()), "net_taker": float(np.nanmean(nt)) if nt.notna().any() else np.nan,
              "net_ratio_maker": float(np.nanmean(nm)) if nm.notna().any() else np.nan}
        fm = _fold_means(x, u.index, u["day"].to_numpy(), lags, daily=True)
        pos = float((x.dropna() > 0).mean()) if x.notna().any() else np.nan
    else:
        s_ = _stat(x, u["day"].to_numpy(), lags)
        st = {"gross": s_["mean"], "se": s_["se"], "u": s_["u"], "days": s_["days"], "cells": s_["cells"],
              "net_taker": float(np.nanmean(_daily(nt, u["day"].to_numpy()))) if nt.notna().any() else np.nan,
              "net_ratio_maker": float(np.nanmean(_daily(nm, u["day"].to_numpy()))) if nm.notna().any() else np.nan}
        fm = _fold_means(x, u.index, u["day"].to_numpy(), lags)
        dm = _daily(x, u["day"].to_numpy())
        pos = float(np.nanmean(dm > 0)) if np.isfinite(dm).any() else np.nan
    st["cost_taker_mean"] = float(np.nanmean(c)) if c.notna().any() else np.nan
    st |= fm
    st |= {"share_days_positive": pos, "median_spread": float(np.nanmedian(x)) if x.notna().any() else np.nan,
           "median_top_ret": float(np.nanmedian(u["top_ret"])) if u["top_ret"].notna().any() else np.nan,
           "median_bottom_ret": float(np.nanmedian(u["bottom_ret"])) if u["bottom_ret"].notna().any() else np.nan}
    return st


def triggers(ud: pd.DataFrame, lags: int) -> pd.DataFrame:
    rows = []
    for kind, thetas in (("top", TOP_THETAS), ("gap", GAP_THETAS)):
        for th in thetas:
            m = (ud["top_dev"] >= th) if kind == "top" else ((ud["top_dev"] - ud["bottom_dev"]) >= th)
            rows.append({"trigger": kind, "theta": th, "named": (kind, th) in NAMED, **unit_stats(ud[m], lags, daily=True)})
    return pd.DataFrame(rows)


def decide_bg2(daily: dict, trig: pd.DataFrame) -> tuple[str, str]:
    """R61's line with the members' TAKER as the cost: the daily unit or a named trigger at ≥ NET_BAR net taker, u ≥ U_BAR, ≥ MIN_DAYS days
    (the unconditional unit's days count as they are), both folds' gross positive."""
    both = lambda r: all(np.isfinite(r[f"gross_{f}"]) and r[f"gross_{f}"] > 0 for f in folds.EXPLORATION)        # noqa: E731
    if np.isfinite(daily["net_taker"]) and daily["net_taker"] >= NET_BAR and daily["u"] >= U_BAR and both(daily):
        return "A TAIL RULE IS WORTH ITS OWN REGISTRATION", "the unconditional daily unit"
    for _, r in trig[trig["named"]].iterrows():
        if np.isfinite(r["net_taker"]) and r["net_taker"] >= NET_BAR and r["u"] >= U_BAR and r["days"] >= MIN_DAYS and both(r):
            return "A TAIL RULE IS WORTH ITS OWN REGISTRATION", f"the trigger {r['trigger']} ≥ {r['theta']:g}"
    return "CLOSED IN MONEY ON THE MEMBERS", f"neither the unconditional daily unit nor a named trigger reaches net taker ≥ +{NET_BAR:g} with u ≥ {U_BAR:g} and both folds positive"


def bg2(D: dict, dev: pd.DataFrame, s: np.ndarray, ct: pd.DataFrame, horizons: tuple[str, ...] = BG2_H) -> dict:
    """The description at each horizon: deciles, buckets, the unit at every bar and at the daily bar, the triggers, the decision line."""
    out = {}
    for h in horizons:
        L = labels_members(D, dev, s, h, ct)
        u = unit_series(L)
        at_daily = (u.index.hour == DAILY[0]) & (u.index.minute == DAILY[1])
        ud = u[at_daily]
        every, daily = unit_stats(u, L["lags"], daily=False), unit_stats(ud, L["lags"], daily=True)
        trig = triggers(ud, L["lags"])
        verdict, why = decide_bg2(daily, trig)
        out[h] = {"deciles": by_decile(L), "buckets": by_bucket(L), "unit_every_bar": every, "unit_daily": daily, "triggers": trig, "unit_daily_series": ud,
                  "decision": verdict, "why": why, "bars": int(L["n"].notna().sum()), "lags": L["lags"]}
    return out


# ---- the run -----------------------------------------------------------------------------------------------------------------------------------
def run_r67(taker_bps: float, maker_bps: float, fee_source: str, twelve: list[str], draws: int = DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN, jobs: int = 1,
            path: Path | str = cb.MEMBERS_PARQUET, csv: Path | str = R62_CSV, members_csv: Path | str | None = None, r62: Path = MEMBERS_OUT_DIR, r60: Path = R60_DIR,
            slices: tuple[str, ...] = MEMBERS_SLICES, mult: dict[str, float] | None = None, n_check: int = N_CHECK, start: pd.Timestamp = MEMBERS_START,
            block_min_names: int = BLOCK_MIN_NAMES, gap: int = GAP, p_max: float = P_FAMILY, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    """R67. Validity (1) … (7) in the registered order, the family screen and its nulls only after; BG2 described beside."""
    from joblib import Parallel, delayed
    from .universe import MEMBERS_CSV
    out_dir.mkdir(parents=True, exist_ok=True)
    L = r62_list(csv)
    kept = L["kept"]
    mpath = members_csv or MEMBERS_CSV
    validity = {"registration": "R67", "folds": list(folds.EXPLORATION), "draws": draws, "seed": seed, "shift_min": shift_min, "gap": gap, "source": str(path),
                "universe_file": {"path": str(csv), "md5": L["md5"], "n_kept": L["n_kept"], "n_rows": L["n_rows"], "consistent": L["consistent"],
                                  "status": "PASS" if L["consistent"] and L["n_kept"] > 0 else "FAIL"},
                "members_file": {"path": str(mpath), "md5": _md5(mpath)},
                "gate": {"p_family_max": p_max, "sign": R62_SIGN, "family": [(DEV, h) for h in FAMILY], "holds_bars": HOLDS, "bar": "the twelve's relative maker bar at the hold (bars['maker'])"}}
    if validity["universe_file"]["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # the members' frame (R62's), the holds appended; validity (2): R62's saved rows at the OLD horizons through the extended path
    print("the members' panel and R62's frames; the holds appended…", flush=True)
    fr = frames(L, "coinbase", path, slices, mult, mpath, start)
    D, idx, cols, s, F, M, m = fr["D"], fr["idx"], fr["cols"], fr["s"], fr["F"], fr["M"], fr["m"]
    P_close = {"close": D["lr"].pipe(np.exp)}                     # the panel's close back from lr (exact: lr = log(close))
    D = extend(D, HOLDS)
    sidx = idx[s]
    validity |= {"scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))), "names_in_panel": len(cols), "first": str(sidx[0]), "last": str(sidx[-1]),
                 "kept_in_panel": int(sum(c in cols for c in kept))}
    print(f"validity (2): R62's six features at P2's four horizons against {r62}/screen.parquet…", flush=True)
    sc_old, _ = ceiling.ic_screen(D, screen_frames_r62(fr), set(), HORIZONS)
    validity["reproduction_r62"] = reproduction_r62(sc_old, r62)
    if validity["reproduction_r62"]["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # validity (3) the long labels by hand; (4) the bars; (5) known-at; (6) membership and coverage; (7) the nulls' gaps — before any IC at a hold
    print("validity (3): the long labels by hand…", flush=True)
    validity["label_check"] = label_check(D, P_close, s, n_check, seed, HOLDS)
    print("validity (4): the twelve's bars at the holds…", flush=True)
    validity["bars"], mv_twelve = bars_twelve(twelve, taker_bps, maker_bps, HOLDS, r60)
    print("validity (5) … (7)…", flush=True)
    validity["known_at"] = known_at(fr["F_kept"], fr["U"], fr["G"], s, kept, n_check, seed)
    validity["membership"] = {"status": "PASS" if bool((F[DEV].notna() & ~M).to_numpy().sum() == 0) else "FAIL",
                              "values_off_membership": int((F[DEV].notna() & ~M).to_numpy().sum()), "values_on": int(F[DEV][s].notna().to_numpy().sum())}
    validity["coverage"], B = block_coverage(F[DEV], s, m, kept, block_min_names)
    lookback_days, longest_days = W["1w"] // 288, max(HOLDS.values()) // 288
    validity["nulls"] = {"status": "PASS" if gap >= lookback_days + longest_days and shift_min > 30 + longest_days else "FAIL", "gap": gap,
                         "gap_needed": lookback_days + longest_days, "shift_min": shift_min, "shift_min_needed_above": 30 + longest_days}
    checks = ("universe_file", "reproduction_r62", "label_check", "bars", "known_at", "membership", "coverage", "nulls")
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in checks) else "FAIL"
    if validity["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    B.to_parquet(out_dir / "blocks.parquet", index=False)
    del fr["F_all"], fr["F_kept"], fr["F_desc"], sc_old
    head = _head(validity, taker_bps, maker_bps, fee_source)

    # the family screen (the 1d row beside), the nulls at the holds
    print(f"screen: {DEV} at every horizon and the holds; nulls at {FAMILY}: {draws} day shuffles (gap {gap}) and {draws} whole-day shifts…", flush=True)
    sc, daily = ceiling.ic_screen(D, {DEV: F[DEV]}, set(), ALL_H)
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in FAMILY}
    Zr = {h: D["zres"][h][s].to_numpy() for h in FAMILY}
    null_shuffle, null_shift = Parallel(n_jobs=min(jobs, 2) if jobs > 1 else 1)(
        [delayed(_null_feature)(DEV, F[DEV][s], Zs, Zr, draws, seed, ALL_H, gap), delayed(shift_feature)(DEV, F[DEV], D, s, draws, seed, shift_min, FAMILY, ALL_H)])

    print("the bars on the members; BG2's rows…", flush=True)
    ct, _ = ceiling.bar_cost(idx, cols, taker_bps, maker_bps)
    bars_taker = {h: taker_bar(D, ct, h) for h in ALL_H}
    cost_cover = float(ct[s].notna().to_numpy().mean())
    bars_maker = validity["bars"]["maker"]

    rows = sc.merge(fold_ics(daily, folds.EXPLORATION, ALL_H), on=["bet", "horizon", "feature"], how="left")
    rows["ic_se"] = rows["ic_mde"] / MDE_K
    rows["bar_maker_twelve"] = rows["horizon"].map(bars_maker)
    rows["bar_taker_members"] = rows["horizon"].map(bars_taker)
    rows["bar_ratio_maker_members"] = rows["bar_taker_members"] * RATIO_MAKER
    for c in ("p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift"):
        rows[c] = np.nan
    for i, r in rows.iterrows():
        if r["bet"] in ("directional", "relative") and r["horizon"] in FAMILY:
            rows.loc[i, "p_single_shuffle"] = single_p(null_shuffle, r["bet"], DEV, r["horizon"], r["t"])
            rows.loc[i, "p_single_shift"] = single_p(null_shift, r["bet"], DEV, r["horizon"], r["t"])
    cells = [(DEV, h) for h in FAMILY]
    fam_rows = rows[(rows["bet"] == BET) & rows["horizon"].isin(FAMILY)]
    t_real = {(DEV, r["horizon"]): r["t"] for _, r in fam_rows.iterrows()}
    pf1, b1 = family_p(null_shuffle, cells, t_real)
    pf2, b2 = family_p(null_shift, cells, t_real)
    for i, r in fam_rows.iterrows():
        rows.loc[i, ["p_fw_shuffle", "p_fw_shift"]] = [pf1[DEV, r["horizon"]], pf2[DEV, r["horizon"]]]
    rows["p_family"] = rows[["p_fw_shuffle", "p_fw_shift"]].max(axis=1)
    rows["verdict"] = ""
    for i, r in rows.loc[fam_rows.index].iterrows():
        rows.loc[i, "verdict"] = verdict_r67(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), bars_maker[r["horizon"]], p_max)
    rows.loc[(rows["horizon"] == PRIMARY) & (rows["bet"] == BET), "verdict"] = "reported (R62's 1d row, reproduced; not a cell of this family)"
    bi = {h: block_ics(daily, m, feature=DEV, h=h) for h in FAMILY}

    desc = bg2(D, F[DEV], s, ct, BG2_H)

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    pd.DataFrame({"horizon": list(ALL_H), "bar_maker_twelve": [bars_maker[h] for h in ALL_H], "ic_needed_taker_members": [bars_taker[h] for h in ALL_H],
                  "bar_ratio_maker_members": [bars_taker[h] * RATIO_MAKER for h in ALL_H], "cost_cover": cost_cover}).to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    mv_twelve.to_parquet(out_dir / "move_vs_cost_twelve.parquet", index=False)
    Bb = B.copy()
    for h in FAMILY:
        Bb = Bb.merge(bi[h].rename(columns={"ic": f"ic_{h}", "se": f"se_{h}", "days": f"days_{h}"}), on="block", how="left")
    Bb.to_parquet(out_dir / "blocks.parquet", index=False)
    for h, d in desc.items():
        for k in ("deciles", "buckets", "triggers", "unit_daily_series"):
            d[k].to_parquet(out_dir / f"bg2_{k}_{h}.parquet", index=k == "unit_daily_series")
    bg2_json = {h: {k: v for k, v in d.items() if k in ("unit_every_bar", "unit_daily", "decision", "why", "bars", "lags")} for h, d in desc.items()}
    (out_dir / "bg2.json").write_text(json.dumps(bg2_json, indent=1, default=str))

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker_twelve", "bar_taker_members", "bar_ratio_maker_members", "verdict"]
    g = {h: rows[(rows["bet"] == BET) & (rows["horizon"] == h)].iloc[0] for h in (*FAMILY, PRIMARY)}
    md = head + [f"\n## Verdict by R67's gate — `{DEV}`, {BET}, on the kept members: **3d {g['3d']['verdict']}; 7d {g['7d']['verdict']}**\n"]
    for h in FAMILY:
        r = g[h]
        md.append(f"\n{h}: IC {r['ic']:+.4f} (t {r['t']:+.2f}, se {r['ic_se']:.4f}, MDE {r['ic_mde']:.4f}); p_family {r['p_family']:.3f} against {p_max} (day shuffles {r['p_fw_shuffle']:.3f}, "
                  f"whole-day shifts {r['p_fw_shift']:.3f}; single {r['p_single_shuffle']:.3f} / {r['p_single_shift']:.3f}); F1 {r['ic_F1']:+.4f}, F2 {r['ic_F2']:+.4f} "
                  f"({'same sign' if r['folds_same_sign'] else 'signs differ'}); months the same sign {r['months_same_sign']:.2f}; the gate's bar {bars_maker[h]:.4f} (the twelve's "
                  f"relative maker bar at {h}, this run's number; expected ≈ {EXPECTED['maker'][h]}); the members' taker bar {bars_taker[h]:.4f} (expected ≈ {EXPECTED['taker'][h]}), "
                  f"the ratio-maker {bars_taker[h] * RATIO_MAKER:.4f}; the registered sign {'positive' if R62_SIGN > 0 else 'negative'}.\n")
    r1 = g[PRIMARY]
    md.append(f"\nThe 1d row beside (R62's, reproduced): IC {r1['ic']:+.4f} (t {r1['t']:+.2f}), F1 {r1['ic_F1']:+.4f} / F2 {r1['ic_F2']:+.4f}; the cost proxy covers {cost_cover:.0%} of the scored cells.\n")
    fam = rows["horizon"].isin(FAMILY) & rows["bet"].isin(["directional", "relative"])
    md += ["\n## The family (relative, 3d / 7d) with the directional bet beside — the registered feature\n",
           "`p_fw_*` = the share of a null's draws whose largest |t| over the TWO family cells is at or above the real |t|; `p_single_*` = the cell alone; `p_family` = the larger "
           f"of the two nulls' family-wise p, against {p_max}. `bar_maker_twelve` = the gate's number at the hold; `bar_taker_members` = the members' taker bar from their cost "
           f"proxy; `bar_ratio_maker_members` = {RATIO_MAKER} × it (an estimate, fact (xxix)).\n", show(rows[fam][cols_show]), "\n",
           "\n## The same feature at P2's horizons on the same frame (reported; the 1d row is R62's)\n", show(rows[~fam][cols_show[:12] + ["bar_maker_twelve", "bar_taker_members", "verdict"]]), "\n",
           "\n## The twelve's bars at every horizon and hold (validity (4))\n", show(mv_twelve[mv_twelve["bet"] == BET][["horizon", "cells", "abs_move_p50", "abs_move_mean", "taker_rt", "maker_rt", "ic_needed_taker", "ic_needed_maker"]]), "\n",
           "\n## The nulls' family bars (largest |t| over the two cells, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           "\n## By block — the kept members present and the relative IC at 3d / 7d inside the block (described)\n", show(Bb.assign(block=lambda d: d["block"].dt.date)), "\n"]
    md.append("\n## BG2 — R61's money shape on the members (described, no gate; the cost = the two names' TAKER round trips from the proxy; the ratio-maker beside)\n")
    for h, d in desc.items():
        md += [f"\n### {h} — **{d['decision']}** ({d['why']}); {d['bars']:,} scored bars with ≥ {MIN_PAIRS} names; HAC lags {d['lags']}\n",
               "\nThe unit at every scored bar (the top name's forward return minus the bottom's; daily means, HAC):\n", "```\n", json.dumps(d["unit_every_bar"], indent=1, default=str), "\n```\n",
               f"\nThe unit at the daily bar {DAILY[0]:02d}:{DAILY[1]:02d} UTC:\n", "```\n", json.dumps(d["unit_daily"], indent=1, default=str), "\n```\n",
               "\nBy decile of the deviation's rank among the names present (1 = the highest):\n", show(d["deciles"]), "\n",
               "\nBy bucket of the deviation (sd units), the median relative return beside the mean:\n", show(d["buckets"]), "\n",
               "\nR61's triggers at the daily bar:\n", show(d["triggers"]), "\n"]
    out_md.write_text("".join(md))
    print(f"{DEV} {BET} on the members: 3d {g['3d']['verdict']}; 7d {g['7d']['verdict']}; BG2 at 1d: {desc['1d']['decision']}; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


def _head(validity: dict, taker_bps, maker_bps, fee_source) -> list[str]:
    return [f"# R67 — the Coinbase deviation at a 3- and 7-day hold on the members (`ft2 ceiling --target pairs --family hold --universe members`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(validity['folds'])} (embargoed) on the members' cells — R62's frame, the holds appended. The universe `{validity['universe_file']['path']}` "
            f"(md5 {validity['universe_file']['md5']}, {validity['universe_file']['n_kept']} kept); the members `{validity['members_file']['path']}` (md5 {validity['members_file']['md5']}). "
            f"The gate: p_family ≤ {validity['gate']['p_family_max']} (halved — R62's horizon clause set aside once), the sign {'positive' if validity['gate']['sign'] > 0 else 'negative'}, "
            f"both folds, |IC| ≥ the twelve's relative maker bar at the hold. Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source):
    validity["status"] = "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head(validity, taker_bps, maker_bps, fee_source) + ["\n**The read is VOID: no IC at a hold was computed on the members.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)
