"""R50 (PLAN §8): BTC's last hour as per-name information — does a name that lagged BTC's hour catch up against its peers over the next
1h / 4h / 1d (lead_1h, sign +), and does BTC's hour carry on through the high-beta names (bx_1h, two-sided)? R26's / R37's frame.

    python scripts/r50_btchour.py stage1      → output/audit/r50_btchour/{stage1.md, stage1.json, features.csv, reference.csv, shifts.parquet, validity.json}
    python scripts/r50_btchour.py stage2      → … {stage2.md, stage2.json, features_f34.csv, shifts_f34.parquet}   (only for the cells stage 1 cleared)

frame      STAGE 1: OUTSIDE = R18's cells (`audit.frame` on r18_transferbook_1d, the hourly bars of F1+F2, 188 members) as the membership mask;
           THE TWELVE = `audit_index.cells_twelve` on the same grid (BTC's own cells NaN: its beta is 1 and its lag 0 by definition).
           STAGE 2: the F3+F4 members by block (`ft2/screen_members_f34.csv`) on F3+F4's hourly grid; the twelve on F3+F4 checked against R16's forecast.
features   per name and hourly bar t, known at t: beta_btc = the 720-hour slope of the name's hourly return on BTC's (≥ 200 pairs; R27's `_beta`);
           lead_1h = (beta_btc × b_1h − r_1h) / σ_1h; bx_1h = beta_btc × b_1h / σ_1h; the reference rev_1h = −r_1h / σ_1h (R37's plain reversal),
           beta_btc alone. σ_1h = σ_1w·√12.
labels     z_h = the log move from the close one bar after t to the close h bars later over σ_1w·√h, clipped at ±5, h = 12, 48, 288.
statistic  `ceiling._ic_xs` (per bar the Spearman across the names present, averaged per day, the mean over days); null every admissible
           whole-day shift (gap 32); centre, se, IC_c, u; family-wise p over the twelve family numbers; the paired Δ of lead_1h against rev_1h.
gate       CLEARS if |u| ≥ 2, p_family ≤ 0.05, one sign in the folds, and for lead_1h IC_c > 0 and u_Δ ≥ 2 (it ADDS); lead without ADDS "CLEARS AS
           THE PLAIN REVERSAL"; lead with IC_c < 0 "CLEARS WITH THE OPPOSITE SIGN"; CLOSED if |IC_c| + 1.96 se < 0.02; else NOT DETECTABLE.
           Stage 2 on the cleared cells with their signs fixed, one-sided: CONFIRMED / NOT CONFIRMED; NOTHING TO CONFIRM if stage 1 cleared nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import audit, audit_index, folds, horizon, universe  # noqa: E402
from ft2 import backtest as bt  # noqa: E402
from ft2.ceiling import MDE_K, MIN_PAIRS, Z_CLIP, Z_TOP, _ic_xs, day_lags, hac  # noqa: E402
from ft2.forecast import _derive  # noqa: E402

OUT = audit.OUT / "r50_btchour"
RUN_F12 = "r18_transferbook_1d"
TWELVE_RUN_F12 = audit_index.TWELVE_RUN                     # r14_ridgebook_1d_ho12 (its decisions' cells)
TWELVE_RUN_F34 = "r16_ridgebook_1d_ho12_f34"
PAIRS_FROM = Path("output/backtest/r42_ridgebook_1d_ho12_f5/meta.json")
MEMBERS_F34 = Path(__file__).resolve().parents[1] / "ft2" / "screen_members_f34.csv"
STATE_DAILY = Path("output/backtest/r47_mech/daily.parquet")
BTC = "BTCUSDT"
HOLDS = (12, 48, 288)
H1 = 12
BETA_DAYS, BETA_MIN_HOURS = 30, 200
GAP = BETA_DAYS + 1 + 1                                     # days: beta's window + the longest hold (1d) + 1
FAMILY = ["lead_1h", "bx_1h"]
PLAIN = "rev_1h"
REFS = [PLAIN, "beta_btc"]
SIGN = {"lead_1h": 1, "bx_1h": 0}                           # the registered sign (0: two-sided)
U_BAR, P_BAR, IC_CLOSED, COVER_BAR = 2.0, 0.05, 0.02, 0.95
COST = {"outside": 18.0, "twelve": 12.3}                   # bps a taker round trip (R20 D3, P1)
MAKER = 8.4                                                 # the twelve's measured maker round trip (R39)
MONEY_BAR = {("outside", 12): 0.14, ("outside", 48): 0.045, ("outside", 288): 0.033, ("twelve", 12): 0.10, ("twelve", 48): 0.034, ("twelve", 288): 0.029}
SESSIONS = {"00-08": range(0, 8), "08-13": range(8, 13), "13-21": range(13, 21), "21-24": range(21, 24)}
PER_DAY = horizon.PER_DAY
WARM = pd.Timedelta(days=BETA_DAYS + 2)


# ---- the features ---------------------------------------------------------------------------------------------------------------------------
def features(hidx: pd.DatetimeIndex, names: list[str], close_h: pd.DataFrame, btc_h: pd.Series, sig_h: pd.DataFrame,
             beta_days: int = BETA_DAYS, min_hours: int = BETA_MIN_HOURS) -> tuple[dict[str, pd.DataFrame], np.ndarray]:
    """The family and the reference features on the hourly grid `hidx` × `names`, from the names' and BTC's hourly closes (the bar closed at t,
    known at t) and σ_1h; returns them and BTC's own hourly move b_1h (bps) on the grid."""
    rc = (np.log(close_h) - np.log(close_h.shift(1))).to_numpy() * 1e4
    rb = (np.log(btc_h) - np.log(btc_h.shift(1))).to_numpy(dtype=float) * 1e4
    beta = audit_index._beta(rc, rb, beta_days * 24, min_hours)
    if BTC in names:
        beta[:, names.index(BTC)] = np.nan
    s = sig_h.to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        F = {"lead_1h": (beta * rb[:, None] - rc) / s, "bx_1h": beta * rb[:, None] / s, PLAIN: -rc / s, "beta_btc": beta}
    wrap = lambda v: pd.DataFrame(v, index=hidx, columns=names).replace([np.inf, -np.inf], np.nan)      # noqa: E731
    return {k: wrap(v) for k, v in F.items()}, rb


def _universe(tag: str, A: dict, holds=HOLDS, btc_5m: pd.Series | None = None) -> dict:
    """One universe's features, labels at every hold and BTC's hour on its grid."""
    M, names, grid, cell, latency = A["M"], A["names"], A["grid"], A["cell"], A["latency"]
    n_frame = int(cell.to_numpy().sum())
    if BTC in names:                                                           # BTC's own cells are NOT cells here (its beta 1, its lag 0 by definition)
        cell = cell.copy()
        cell[BTC] = False
        cell = cell.where(cell.sum(axis=1) >= MIN_PAIRS, False)
    idx = M.index[M.index >= grid[0] - WARM]
    close = M.close.loc[idx, names]
    sig = _derive(close)["sig"]["1w"]
    btc = (M.close[BTC] if BTC in M.close.columns else btc_5m).reindex(idx)
    hmask = (idx.minute == 0) & (idx.second == 0)
    hidx = idx[hmask]
    F, rb = features(hidx, names, close.loc[hidx], btc.loc[hidx], (sig * np.sqrt(H1)).loc[hidx])
    at = hidx.get_indexer(grid)
    cut = lambda d: {k: v.iloc[at].where(cell) for k, v in d.items()}       # noqa: E731
    Fg = cut(F)
    Z = {h: (bt.labels(M, h, latency).loc[idx, names] / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).loc[grid].where(cell).to_numpy() for h in holds}
    n_cells = max(int(cell.to_numpy().sum()), 1)
    cover = {k: float(Fg[k].notna().to_numpy().sum() / n_cells) for k in FAMILY}
    yb = {h: bt.labels(M, h, latency).loc[grid, names].where(cell) for h in holds}
    move = {h: float(yb[h].sub(yb[h].mean(axis=1), axis=0).abs().stack().mean()) for h in holds}
    return {"tag": tag, "F": Fg, "Z": Z, "b_1h": rb[at], "grid": grid, "cell": cell, "names": names, "A": A, "cover": cover, "move": move,
            "cells": {"frame": n_frame, "read": int(cell.to_numpy().sum()), "btc_dropped": int(n_frame - cell.to_numpy().sum())}}


# ---- the F3+F4 members' cells ----------------------------------------------------------------------------------------------------------------
def cells_members(csv: Path | str, fold_names=("F3", "F4"), latency: int = bt.LATENCY, hold: int = 288, start_before: pd.Timedelta = pd.Timedelta(days=40)) -> dict:
    """The frozen members by block on the hourly grid of the folds: a cell where the name is a member of the block containing t, has a close at t
    and a σ_1w; bars with fewer than MIN_PAIRS such names hold no cell."""
    fold_names = folds.order(fold_names)
    mem = universe.members(csv)
    symbols = sorted(mem["symbol"].unique())
    a = min(folds.bounds(f)[0] for f in fold_names)
    end = max(folds.bounds(f)[1] for f in fold_names)
    M = bt.market(symbols, end, start=a - start_before)
    names = list(M.columns)
    t5 = pd.Series(M.index, index=M.index)
    scored = np.zeros(len(M.index), dtype=bool)
    for f in fold_names:
        scored |= folds.mask(t5, f).to_numpy()
    grid = M.index[scored & (M.index.minute == 0) & (M.index.second == 0)]
    idx = M.index[M.index >= grid[0] - audit.WARMUP]
    sig = _derive(M.close.loc[idx, names])["sig"]["1w"]
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    blk = starts[np.clip(starts.searchsorted(grid, side="right") - 1, 0, None)]
    member = pd.DataFrame(False, index=grid, columns=names)
    for b, g in mem.groupby("block"):
        rows = blk == b
        member.loc[rows, [s for s in g["symbol"] if s in member.columns]] = True
    has = M.close.loc[grid, names].notna() & (sig.loc[grid] > 0)
    cell = member & has
    cell = cell.where(cell.sum(axis=1) >= MIN_PAIRS, False)
    pairs_ok = int(cell.to_numpy().sum())
    v = {"status": "PASS" if pairs_ok > 0 and (grid >= a).all() and (grid < end).all() else "FAIL", "cells": pairs_ok, "names": int((cell.sum(axis=0) > 0).sum()),
         "names_in_csv": len(symbols), "bars": int(len(grid)), "bars_under_min_pairs": int((cell.sum(axis=1) == 0).sum()), "blocks": int(len(starts)),
         "min_names_at_a_bar": int(cell.sum(axis=1)[cell.sum(axis=1) > 0].min()) if pairs_ok else 0,
         "cells_not_members": int((cell & ~member).to_numpy().sum()), "cells_outside_folds": int((~pd.Series(scored, index=M.index).loc[grid]).sum())}
    return {"M": M, "names": names, "grid": grid, "cell": cell, "validity": v, "end": end, "fold_names": fold_names, "hold": hold, "latency": latency, "run_dir": None}


# ---- the statistics ------------------------------------------------------------------------------------------------------------------------
def _table(U: list[dict], holds, ks: np.ndarray, day: np.ndarray, fold_names, feats: list[str], refs: list[str], jobs: int, family_keys=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every feature × hold × universe under the real labels and every shift: the table of rows and the shift frame."""
    from joblib import Parallel, delayed
    want = {u["tag"]: [k for k in (*feats, *refs) if k in u["F"]] for u in U}
    jobs_ = [(u["tag"], k, h, u["F"][k], u["Z"][h]) for u in U for k in want[u["tag"]] for h in holds if family_keys is None or (u["tag"], k, h) in family_keys or k in refs]
    res = Parallel(n_jobs=jobs, verbose=0)(delayed(audit_index._ic_shifts)(f"{t}:{k}:{h}", F, Z, ks, day) for t, k, h, F, Z in jobs_)
    d = pd.concat([r for r, _ in res], ignore_index=True)
    d[["universe", "feature", "hold"]] = d["feature"].str.split(":", expand=True)
    d["hold"] = d["hold"].astype(int)
    key = ["universe", "feature", "hold"]
    real = d[d["shift"] == 0].set_index(key)["ic"]
    null = d[d["shift"] > 0]
    st = null.groupby(key)["ic"].agg(centre="mean", se="std")
    null = null.join(st, on=key)
    null["u"] = (null["ic"] - null["centre"]) / null["se"]
    fam_keys = family_keys if family_keys is not None else {(t, k, h) for t in want for k in feats for h in holds}
    fam_null = null[[(t, k, h) in fam_keys for t, k, h in zip(null["universe"], null["feature"], null["hold"])]]
    mx = fam_null.assign(a=fam_null["u"].abs()).groupby("shift")["a"].max() if len(fam_null) else pd.Series(dtype=float)
    wide = d.pivot_table(index="shift", columns=key, values="ic")
    dates = pd.date_range(day_start(U[0]["grid"]), periods=int(day.max()) + 1, freq="D")
    part = audit_index._parts(dates, fold_names, "index")
    parts = [p for p in dict.fromkeys(part) if p]
    rows = []
    for (t, k, h, F, Z), (_, ic_daily) in zip(jobs_, res):
        u_ = [u for u in U if u["tag"] == t][0]
        c, e = float(st.loc[(t, k, h), "centre"]), float(st.loc[(t, k, h), "se"])
        ic = float(real[(t, k, h)])
        own = null[(null["universe"] == t) & (null["feature"] == k) & (null["hold"] == h)]
        per_part = {p: float(np.nanmean(ic_daily[(part == p).to_numpy()])) if np.isfinite(ic_daily[(part == p).to_numpy()]).any() else np.nan for p in parts}
        m_hac, se_hac, _ = hac(ic_daily, day_lags(h))
        u_delta, d0 = np.nan, np.nan
        if k == "lead_1h" and (t, PLAIN, h) in wide.columns:
            dl = wide[(t, k, h)] - wide[(t, PLAIN, h)]
            d0, dn = float(dl.loc[0]), dl.loc[dl.index > 0]
            u_delta = (d0 - float(dn.mean())) / float(dn.std()) if dn.std() else np.nan
            d0 = d0 - float(dn.mean())
        is_fam = (t, k, h) in fam_keys
        n_cells = max(int(u_["cell"].to_numpy().sum()), 1)
        row = {"universe": t, "feature": k, "hold": h, "family": is_fam, "coverage": float(F.notna().to_numpy().sum() / n_cells), "ic": ic, "centre": c, "ic_c": ic - c,
               "se": e, "u": (ic - c) / e if e else np.nan, "t_hac": m_hac / se_hac if se_hac else np.nan, "days": int(np.isfinite(ic_daily).sum()),
               **{f"ic_{p}": per_part[p] for p in parts}, "parts_same_sign": bool(len({np.sign(per_part[p]) for p in parts if np.isfinite(per_part[p])}) == 1),
               "mde": MDE_K * e, "upper": abs(ic - c) + 1.96 * e, "p_single": (1 + int((own["u"].abs() >= abs((ic - c) / e)).sum())) / (len(own) + 1) if e else np.nan,
               "p_family": (1 + int((mx >= abs((ic - c) / e)).sum())) / (len(mx) + 1) if (is_fam and e and len(mx)) else np.nan,
               "delta_vs_plain": d0, "u_delta": u_delta, "money_bar": MONEY_BAR.get((t, h), np.nan)}
        rows.append(row)
    return pd.DataFrame(rows), d


def day_start(grid: pd.DatetimeIndex) -> pd.Timestamp:
    return grid[0].floor("D")


def verdict1(r: dict) -> str:
    """Stage 1's verdict as registered."""
    if not r["family"]:
        return "reference"
    base = abs(r["u"]) >= U_BAR and r["p_family"] <= P_BAR and r["parts_same_sign"]
    if r["feature"] == "lead_1h":
        if base and r["ic_c"] > 0:
            return "CLEARS" if r["u_delta"] >= U_BAR else "CLEARS AS THE PLAIN REVERSAL"
        if base and r["ic_c"] < 0:
            return "CLEARS WITH THE OPPOSITE SIGN"
    elif base:
        return "CLEARS"
    return "CLOSED" if abs(r["ic_c"]) + 1.96 * r["se"] < IC_CLOSED else "NOT DETECTABLE"


def _refs(u: dict, holds, day: np.ndarray, state: np.ndarray | None) -> list[dict]:
    """Described rows: the family split by BTC's sign, by S90 and by session; the run's forecast; the break-even IC."""
    rows = []
    b = u["b_1h"]
    hours = np.asarray(pd.DatetimeIndex(u["grid"]).hour)
    for h in holds:
        Z = u["Z"][h]
        def row(name, F, mask=None):
            m, t_ = audit_index._ic_on(F, Z, day, mask, hold=h)
            x = F if mask is None else F.where(pd.Series(mask, index=F.index), axis=0)
            rows.append({"universe": u["tag"], "hold": h, "row": name, "ic": m, "t_hac": t_, "cells": int(x.notna().to_numpy().sum())})
        for k in FAMILY:
            row(f"{k} after a BTC rise (b_1h > 0)", u["F"][k], b > 0)
            row(f"{k} after a BTC fall (b_1h < 0)", u["F"][k], b < 0)
            if state is not None:
                row(f"{k} after a rising quarter (S90 +1)", u["F"][k], state > 0)
                row(f"{k} after a falling quarter (S90 −1)", u["F"][k], state < 0)
            for s_, hrs in SESSIONS.items():
                row(f"{k} at {s_} UTC", u["F"][k], np.isin(hours, list(hrs)))
        cost = COST.get(u["tag"], np.nan)
        rows.append({"universe": u["tag"], "hold": h, "row": "break-even IC for the top tenth, taker", "ic": cost / (Z_TOP * 1.2533 * u["move"][h]), "t_hac": np.nan,
                     "cells": int(u["cell"].to_numpy().sum()), "note": f"round trip {cost} bps against a mean |move against peers| of {u['move'][h]:.0f} bps"})
        if u["tag"] == "twelve" and h >= 48:
            rows.append({"universe": u["tag"], "hold": h, "row": "break-even IC for the top tenth, maker", "ic": MAKER / (Z_TOP * 1.2533 * u["move"][h]), "t_hac": np.nan,
                         "cells": int(u["cell"].to_numpy().sum())})
    A_ = u["A"]
    if u["tag"] == "outside" and "o" in A_:
        zh = A_["o"].pivot(index="t", columns="symbol", values="zhat").reindex(index=u["grid"], columns=u["names"])
        for h in holds:
            m_, t_ = audit_index._ic_on(zh, u["Z"][h], day, hold=h)
            rows.append({"universe": u["tag"], "hold": h, "row": "the run's forecast (R18's candle ridge)", "ic": m_, "t_hac": t_, "cells": int(zh.notna().to_numpy().sum())})
    elif A_.get("run_dir") is not None and (A_["run_dir"] / "forecast.parquet").exists():
        o = pd.read_parquet(A_["run_dir"] / "forecast.parquet")
        zh = o.assign(zhat=o["f_bps"] / o["sigma_h"]).pivot_table(index="t", columns="symbol", values="zhat").reindex(index=u["grid"], columns=u["names"])
        for h in holds:
            m_, t_ = audit_index._ic_on(zh, u["Z"][h], day, hold=h)
            rows.append({"universe": u["tag"], "hold": h, "row": "R14's held-out forecast", "ic": m_, "t_hac": t_, "cells": int(zh.notna().to_numpy().sum())})
    return rows


def _state(grid: pd.DatetimeIndex, daily: Path | None) -> np.ndarray | None:
    if daily is None or not Path(daily).exists():
        return None
    d = pd.read_parquet(daily)[["day", "state"]].set_index("day")["state"]
    return d.reindex(pd.DatetimeIndex(grid).floor("D")).fillna(0).to_numpy().astype(int)


def _btc(A: dict, B: dict) -> pd.Series:
    """BTC's 5m close: from whichever market holds it, else its own panel over the span."""
    for X in (B, A):
        if BTC in X["M"].close.columns:
            return X["M"].close[BTC]
    idx = A["M"].index.union(B["M"].index)
    return bt.market([BTC], idx[-1] + audit.BAR, start=idx[0]).close[BTC]


def _grid_checks(U: list[dict], gap: int) -> tuple[dict, np.ndarray, np.ndarray, int]:
    grid = U[0]["grid"]
    for u in U[1:]:
        if not u["grid"].equals(grid):
            raise SystemExit("the universes' grids differ: the shifts could not be the same")
    nd = len(grid) // PER_DAY
    day = audit._day(grid)
    whole = bool(len(grid) == nd * PER_DAY and (np.bincount(day)[np.bincount(day) > 0] == PER_DAY).all())
    ks = horizon.shifts(nd, gap)
    b = np.vstack([u["b_1h"] for u in U])
    same_btc = float(np.nanmax(np.abs(b - b[0]))) if len(U) > 1 else 0.0
    v = {"whole_days": whole, "days": nd, "shifts": int(len(ks)), "shifts_expected": nd - 2 * gap + 1, "gap_days": gap, "btc_hour_max_abs_diff": same_btc}
    return v, ks, day, nd


# ---- stage 1 ----------------------------------------------------------------------------------------------------------------------------------
def stage1(run: str = RUN_F12, pairs: list[str] | None = None, members: str | None = None, twelve_run: str | None = TWELVE_RUN_F12, holds=HOLDS,
           fold_names=None, jobs: int = 4, out: Path = OUT, gap: int = GAP, state_daily: Path | None = STATE_DAILY, min_shifts: int = 20) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    A = audit.frame(run, members)
    fold_names = folds.order(fold_names or A["fold_names"])
    if list(fold_names) != list(A["fold_names"]):
        A = audit_index._cut(A, fold_names)
    pairs = pairs or json.loads(PAIRS_FROM.read_text())["pairs"]
    B = audit_index.cells_twelve(pairs, fold_names, A["hold"], A["latency"], run=twelve_run)
    btc_5m = _btc(A, B)
    U = [_universe("outside", A, holds, btc_5m), _universe("twelve", B, holds, btc_5m)]
    gv, ks, day, nd = _grid_checks(U, gap)
    v = {"registration": "R50", "stage": 1, "run": run, "folds": list(fold_names), "holds": list(holds), **gv,
         "outside": {**A["validity"], "cover": U[0]["cover"], "cells_read": U[0]["cells"]}, "twelve": {**B["validity"], "cover": U[1]["cover"], "cells_read": U[1]["cells"]}}
    v["status"] = "PASS" if (A["validity"]["status"] == "PASS" and B["validity"]["status"] == "PASS" and gv["whole_days"] and gv["shifts"] == gv["shifts_expected"]
                             and gv["shifts"] >= min_shifts and gv["btc_hour_max_abs_diff"] == 0.0 and all(c >= COVER_BAR for u in U for c in u["cover"].values())) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# R50 — BTC's last hour as per-name information, stage 1 (`{run}` and the twelve, {'+'.join(fold_names)})\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · " + " · ".join(f"{u['tag']}: {len(u['names'])} names, {int(u['cell'].to_numpy().sum()):,} cells" for u in U)
            + f" · {nd} days · {len(ks)} shifts (gap {gap} days)\n", f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "stage1.md").write_text("\n".join(head + ["\n**The read is VOID: nothing of the family was computed.**\n"]))
        print("validity FAIL — stage 1 is void", flush=True)
        raise SystemExit(2)
    tab, d = _table(U, holds, ks, day, fold_names, FAMILY, REFS, jobs)
    tab["verdict"] = [verdict1(r) for r in tab.to_dict("records")]
    state = _state(U[0]["grid"], state_daily)
    refs = pd.DataFrame([r for u in U for r in _refs(u, holds, day, state)])
    fam = tab[tab["family"]]
    cleared = [{"universe": r["universe"], "feature": r["feature"], "hold": int(r["hold"]), "sign": int(np.sign(r["ic_c"])), "ic_c": float(r["ic_c"]), "se": float(r["se"]),
                "u": float(r["u"]), "u_delta": float(r["u_delta"]) if np.isfinite(r["u_delta"]) else None} for r in fam.to_dict("records") if r["verdict"] == "CLEARS"]
    mx = d[(d["shift"] > 0)]
    summary = {"registration": "R50", "stage": 1, "validity": v, "rows": tab.to_dict("records"), "cleared": cleared, "run_stage2": bool(cleared),
               "verdicts": fam["verdict"].value_counts().to_dict(), "seconds": round(time.time() - t0, 1), "written": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    (out / "stage1.json").write_text(json.dumps(summary, indent=1, default=str))
    tab.to_csv(out / "features.csv", index=False)
    refs.to_csv(out / "reference.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "stage1.md").write_text("\n".join(head + _report1(summary, tab, refs, U)))
    print(f"R50 stage 1: {len(cleared)} of {len(fam)} clear; stage 2 {'runs' if cleared else 'is not run'}; wrote {out}/", flush=True)
    return summary


def _report1(s: dict, tab: pd.DataFrame, refs: pd.DataFrame, U: list[dict]) -> list[str]:
    fam, ref = tab[tab["family"]], tab[~tab["family"]]
    show = lambda df, k=4: df.round(k).to_markdown(index=False)       # noqa: E731
    main = ["universe", "feature", "hold", "coverage", "ic", "centre", "ic_c", "se", "u", "t_hac", "p_single", "p_family", "mde", "upper", "delta_vs_plain", "u_delta", "money_bar", "verdict"]
    parts = [c for c in tab.columns if c.startswith("ic_F")]
    more = ["universe", "feature", "hold", "days", *parts, "parts_same_sign"]
    cl = s["cleared"]
    return ["\nWords: *lead_1h* is what BTC's last hour, through the name's 30-day beta to BTC, said the name should have moved, minus what it did, in the name's own hourly "
            "sigmas — positive when the name lagged a rise or out-fell a fall; the CATCH-UP hypothesis is a positive IC. *bx_1h* is BTC's hour through the name's beta — carry-on (+) "
            "or over-reaction (−). *rev_1h* is the plain hourly reversal (R37), the known sub-cost fact lead_1h must ADD to: *delta_vs_plain* and *u_delta* are lead_1h's IC_c "
            "minus rev_1h's on the same cells and shifts, and that over its own spread. *IC* ranks across the names present; *centre* is the IC when the moves come from other days; "
            "*ic_c* = IC − centre; *u* = ic_c / se; *p_family* the share of shifts on which the BEST of the twelve did at least as well. *money_bar*: the IC at which the top tenth "
            "pays its round trip at that horizon on that universe (the gate's licensing bar).\n",
            f"\n## The family — twelve numbers: **{len(cl)} CLEARS** ({json.dumps(s['verdicts'])}); stage 2 {'RUNS on the cleared cells' if cl else 'is NOT run — F3+F4 stays unread for this family'}\n",
            show(fam[main]), "\n", "\n### Described (decides nothing)\n", show(fam[more]), "\n",
            "\n## Reference rows — the plain reversal and beta alone (no verdict)\n", show(ref[main[:-1]]), "\n", show(ref[more]), "\n",
            "\n## Described — the splits, the forecasts and the break-even ICs\n", show(refs), "\n"]


# ---- stage 2 ----------------------------------------------------------------------------------------------------------------------------------
def verdict2(D: float, sd: float, p: float, sign: int, fact: float, u_delta: float | None, needs_delta: bool, su: float = np.inf) -> str:
    if not np.isfinite(D) or not sd > 0:
        return "NOT READABLE"
    if p <= P_BAR and su >= U_BAR and (not needs_delta or (u_delta is not None and np.isfinite(u_delta) and u_delta >= U_BAR)):
        return "CLEARS"
    if p <= P_BAR and su >= U_BAR and needs_delta:
        return "CLEARS AS THE PLAIN REVERSAL"
    if np.isfinite(fact) and sign * (D + sign * 1.96 * sd) < sign * fact / 2:
        return "REFUTED"
    return "NOT DETECTABLE" if abs(D) < MDE_K * sd else "NOT CLEAR"


def stage2(members_csv: Path | str = MEMBERS_F34, pairs: list[str] | None = None, twelve_run: str | None = TWELVE_RUN_F34, fold_names=("F3", "F4"), jobs: int = 4,
           out: Path = OUT, gap: int = GAP, min_shifts: int = 20, cells_outside: dict | None = None, cells_twelve: dict | None = None) -> dict:
    """The confirmation on F3+F4, only for the cells stage 1 cleared (read from stage1.json — validity (6))."""
    t0 = time.time()
    s1 = json.loads((out / "stage1.json").read_text())
    cleared = s1["cleared"]
    if not cleared:
        summary = {"registration": "R50", "stage": 2, "verdict": "NOTHING TO CONFIRM", "confirmed": False, "note": "stage 1 cleared nothing: F3+F4 not read", "stage1_written": s1["written"]}
        (out / "stage2.json").write_text(json.dumps(summary, indent=1))
        (out / "stage2.md").write_text("# R50 — stage 2\n\n**NOTHING TO CONFIRM** — stage 1 cleared nothing; F3+F4 was not read for this family.\n")
        return summary
    fold_names = folds.order(fold_names)
    holds = sorted({int(c["hold"]) for c in cleared})
    tags = {c["universe"] for c in cleared}
    A = cells_outside or cells_members(members_csv, fold_names)
    pairs = pairs or json.loads(PAIRS_FROM.read_text())["pairs"]
    B = cells_twelve or audit_index.cells_twelve(pairs, fold_names, 288, bt.LATENCY, run=twelve_run)
    btc_5m = _btc(A, B)
    U = [_universe("outside", A, holds, btc_5m), _universe("twelve", B, holds, btc_5m)]
    gv, ks, day, nd = _grid_checks(U, gap)
    v = {"registration": "R50", "stage": 2, "folds": list(fold_names), "holds": holds, "cleared_from_stage1": cleared, "stage1_written": s1["written"], **gv,
         "outside": {**A["validity"], "cover": U[0]["cover"], "cells_read": U[0]["cells"]}, "twelve": {**B["validity"], "cover": U[1]["cover"], "cells_read": U[1]["cells"]}}
    v["status"] = "PASS" if (A["validity"]["status"] == "PASS" and B["validity"]["status"] == "PASS" and A["validity"].get("cells_not_members", 0) == 0
                             and A["validity"].get("cells_outside_folds", 0) == 0 and gv["whole_days"] and gv["shifts"] == gv["shifts_expected"] and gv["shifts"] >= min_shifts
                             and gv["btc_hour_max_abs_diff"] == 0.0 and all(c >= COVER_BAR for u in U for c in u["cover"].values())) else "FAIL"
    head = [f"# R50 — stage 2, the confirmation on {'+'.join(fold_names)} (the members by block and the twelve), the cells stage 1 cleared\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · " + " · ".join(f"{u['tag']}: {len(u['names'])} names, {int(u['cell'].to_numpy().sum()):,} cells" for u in U)
            + f" · {nd} days · {len(ks)} shifts\n", f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "stage2.md").write_text("\n".join(head + ["\n**The read is VOID: nothing was computed on F3+F4.**\n"]))
        (out / "validity_f34.json").write_text(json.dumps(v, indent=1, default=str))
        print("validity FAIL — stage 2 is void", flush=True)
        raise SystemExit(2)
    keys = {(c["universe"], c["feature"], int(c["hold"])) for c in cleared}
    U = [u for u in U if u["tag"] in tags]
    tab, d = _table(U, holds, ks, day, fold_names, FAMILY, [PLAIN], jobs, family_keys=keys)
    # the one-sided family over the cleared set, with the signs fixed
    null = d[d["shift"] > 0].copy()
    key = ["universe", "feature", "hold"]
    st = null.groupby(key)["ic"].agg(centre="mean", se="std")
    null = null.join(st, on=key)
    sign_of = {(c["universe"], c["feature"], int(c["hold"])): (1 if c["sign"] >= 0 else -1) for c in cleared}
    null["su"] = [(r.ic - r.centre) / r.se * sign_of.get((r.universe, r.feature, int(r.hold)), 0) for r in null.itertuples()]
    fam_null = null[[(t, k, h) in keys for t, k, h in zip(null["universe"], null["feature"], null["hold"])]]
    mx = fam_null.groupby("shift")["su"].max()
    rows = []
    for c in cleared:
        k_ = (c["universe"], c["feature"], int(c["hold"]))
        r = tab[(tab["universe"] == k_[0]) & (tab["feature"] == k_[1]) & (tab["hold"] == k_[2])].iloc[0]
        sg = sign_of[k_]
        own = null[(null["universe"] == k_[0]) & (null["feature"] == k_[1]) & (null["hold"] == k_[2])]
        su = sg * r["u"]
        p1 = (1 + int((own["su"] >= su).sum())) / (len(own) + 1)
        pf = (1 + int((mx >= su).sum())) / (len(mx) + 1)
        needs = k_[1] == "lead_1h"
        rows.append({**{k: r[k] for k in ("universe", "feature", "hold", "coverage", "ic", "centre", "ic_c", "se", "u", "t_hac", "days", "parts_same_sign", "mde", "delta_vs_plain", "u_delta", "money_bar")},
                     "sign": sg, "signed_u": su, "p_one_sided": p1, "p_family": pf, "stage1_ic_c": c["ic_c"], "lo": r["ic_c"] - 1.96 * r["se"], "hi": r["ic_c"] + 1.96 * r["se"],
                     "verdict": verdict2(float(r["ic_c"]), float(r["se"]), pf, sg, float(c["ic_c"]), float(r["u_delta"]) if np.isfinite(r["u_delta"]) else None, needs, su)})
    res = pd.DataFrame(rows)
    confirmed = bool((res["verdict"] == "CLEARS").any())
    licensed = [{**r, "licensed": bool(abs(r["ic_c"]) >= r["money_bar"])} for r in res[res["verdict"] == "CLEARS"].to_dict("records")]
    summary = {"registration": "R50", "stage": 2, "validity": v, "rows": res.to_dict("records"), "confirmed": confirmed, "verdict": "CONFIRMED" if confirmed else "NOT CONFIRMED",
               "cleared_confirmed": licensed, "seconds": round(time.time() - t0, 1)}
    (out / "stage2.json").write_text(json.dumps(summary, indent=1, default=str))
    (out / "validity_f34.json").write_text(json.dumps(v, indent=1, default=str))
    tab.to_csv(out / "features_f34.csv", index=False)
    d.to_parquet(out / "shifts_f34.parquet", index=False)
    show = lambda df, k=4: df.round(k).to_markdown(index=False)       # noqa: E731
    md = head + [f"\n## **{summary['verdict']}** — {len(cleared)} cleared cell(s) read once on {'+'.join(fold_names)} with their stage-1 signs, one-sided; the family-wise p over the cleared set\n",
                 show(res), "\n", "\n(a CLEARS at or above its money_bar licenses one priced registration on F5; below it, a described fact)\n",
                 "\n## Every row computed on F3+F4 (the cleared cells and the plain reversal beside)\n", show(tab[[c for c in tab.columns if c != "family"]]), "\n"]
    (out / "stage2.md").write_text("\n".join(md))
    print(f"R50 stage 2: {summary['verdict']}; wrote {out}/", flush=True)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["stage1", "stage2"])
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    s = stage1(jobs=a.jobs) if a.stage == "stage1" else stage2(jobs=a.jobs)
    print((OUT / f"{a.stage}.md").read_text())
    return s


if __name__ == "__main__":
    main()
