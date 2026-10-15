"""R41 — the funding settlement (PLAN §8 R41): does the funding a name is about to pay move its price into the 8-hour settlement and back
after, against its peers, on R18's screener-member cells and on the twelve?

`ft2 audit r18_transferbook_1d --family settle --twelve` → output/audit/<run>_settle/

frame       R37's (`audit_flow`): OUTSIDE = `audit.frame`'s cells (hourly bars of F1+F2, the block's members) as the membership mask;
            THE TWELVE = `audit_index.cells_twelve` on the same grid. The EVENT cells per name, S its settlement times (`funding_archive`'s
            `ts` — the schedule the exchange publishes in advance): INTO = the cell t = S − 1 h, AFTER = the cell t = S. A CONTROL cell is
            a cell with no settlement at t − 1 h, t, t + 1 h or t + 2 h.
labels      z_h = the log move from the close one bar after t to the close h bars later over σ_1w·√h, clipped at ±5 (`bt.labels`), at
            h = SLOTS["into"] = 11 (S − 55 min → S: the hour into the settlement, nothing after it), 12 and 48 for AFTER. Money in
            ACTUAL returns against the bar's peers (`horizon.labels`): INTO without funding (flat at S), AFTER with funding on value.
ingredients per name and bar, known strictly before t (a premium bar stamped open_time is used from its close):
              P         = the mean premium index (bps) over the period in force, (S_prev, t], over the bars present (NaN under P_COVER)
              fund_due  = P + clip(I − P, −CLAMP, +CLAMP), I = I_8H × interval_h / 8 — the rate due at the next settlement (Binance's formula)
              prem_dev  = the last bar's premium − its trailing-DEV_DAYS mean (N1's form)
              funding_last = the rate settled at the last settlement strictly before t (R20's feature)
              move_1h   = R37's: the hour's log return in the name's sigmas
family      fund_due, signed by the slot (SIGN: −1 into, +1 after) so that a POSITIVE IC is the payment-avoidance story, on the event
            cells: three slots × two universes = SIX numbers.
reference   P, prem_dev, funding_last signed the same way on the same cells; rev_1h = −move_1h (the plain reversal) on the same cells and
            the paired Δ against it under the same shifts (u_Δ); the run's forecast on the event cells; and the CONTROL: the family on the
            control cells — a clear whose control clears at half its size is "NOT THE SETTLEMENT'S".
money       the FIFTHS on each event bar with ≥ FIFTH_MIN names: INTO short the top fifth of fund_due, long the bottom; AFTER the reverse;
            bps a position against the peers, HAC se over days, the shift null; by interval and by settlement hour; the 5-minute PROFILE
            from S − 55 to S + 60 min signed by the INTO side.
validity    the frame's; whole days and the shift count; fund_due on ≥ COVER_BAR of the event cells; the FORMULA — at every settlement with
            ≥ FORMULA_MIN names the Spearman between fund_due(S − 1 h) and the settled rate, its median ≥ FORMULA_RHO and the share of
            (name, S) within 1 bp ≥ FORMULA_WITHIN; exit 2 = void.
gate        R37's, plus the control: CLEARS if |u| ≥ 2 AND p_family ≤ 0.05 AND one sign in F1 and F2 AND IC_c > 0 AND u_Δ ≥ 2 AND the control
            does not clear at half the size; "CLEARS AS THE PLAIN REVERSAL", "NOT THE SETTLEMENT'S", "CLEARS WITH THE OPPOSITE SIGN",
            CLOSED (|IC_c| + 1.96 se < 0.02), NOT DETECTABLE.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import audit, audit_index, data, horizon
from . import backtest as bt
from .audit_flow import GAP, H1, IC_CLOSED, P_BAR, PER_DAY, U_BAR
from .ceiling import BAR, MDE_K, MIN_PAIRS, Z_CLIP, _ic_xs, day_lags, hac
from .forecast import _derive

OUT = audit.OUT
SLOTS = {"into": 11, "after_1h": 12, "after_4h": 48}        # slot → hold in bars
SIGN = {"into": -1.0, "after_1h": 1.0, "after_4h": 1.0}       # the payers' side lags into the settlement and comes back after
FAMILY = "fund_due"
PRESSURE = ["fund_due", "P", "prem_dev", "funding_last"]      # signed by the slot
PLAIN = "rev_1h"
EVENT, CONTROL = "event", "control"
CLAMP, I_8H = 5.0, 1.0                                        # bps: funding = P + clip(I − P, −CLAMP, +CLAMP), I = I_8H × interval_h / 8
P_COVER = 0.6                                                 # P needs this share of the period's bars so far
DEV_DAYS = 30
COVER_BAR = {"outside": 0.95, "twelve": 0.90}
FORMULA_RHO, FORMULA_WITHIN, FORMULA_MIN, FORMULA_MIN_S = 0.8, 0.5, 10, 20
FIFTH_MIN = 10                                                # names in an event bar for the fifths
PROFILE = 12                                                  # 5-minute bars either side of S in the profile
COST = {"outside": 18.0, "twelve": 12.3}                      # bps a taker round trip (R20 D3; P1)
HOUR = pd.Timedelta("1h")
NS_BAR, NS_HOUR = int(BAR / pd.Timedelta("1ns")), int(HOUR / pd.Timedelta("1ns"))


# ---- the ingredients --------------------------------------------------------------------------------------------------------------------
def ingredients(idx: pd.DatetimeIndex, names: list[str], close: pd.DataFrame, end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """The ingredients, the event masks and the schedule on the 5m index `idx` (the bar closed at t), each known strictly before t."""
    notes: list[str] = []
    lr = np.log(close)
    sig = _derive(close)["sig"]["1w"]
    move_1h = (lr.diff(H1) * 1e4) / (sig * np.sqrt(H1)).where(sig > 0)
    nan = lambda: pd.DataFrame(np.nan, index=idx, columns=names)          # noqa: E731
    no = lambda: pd.DataFrame(False, index=idx, columns=names)            # noqa: E731
    I = {"P": nan(), "fund_due": nan(), "prem_dev": nan(), "funding_last": nan(), "move_1h": move_1h, "interval": nan(), "rate_S": nan()}
    masks = {"into": no(), "after": no(), "near": no()}
    pw = None
    try:
        pr = data.load("premium", columns=["symbol", "open_time", "premium"], symbols=names)
        pr = pr[(pr["open_time"] + BAR <= end) & (pr["open_time"] + BAR >= idx[0] - pd.Timedelta(days=DEV_DAYS + 1))]
        full = (pr.assign(symbol=pr["symbol"].astype(str), t=pr["open_time"] + BAR, p=pr["premium"] * 1e4)
                .pivot(index="t", columns="symbol", values="p").reindex(columns=names).sort_index())
        dev = full - full.rolling(f"{DEV_DAYS}D", min_periods=DEV_DAYS * 288 // 2).mean()
        I["prem_dev"] = dev.reindex(idx)
        pw = full.reindex(idx)
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("premium absent: P, fund_due and prem_dev are NaN")
    try:
        fu = data.load("funding_archive", columns=["symbol", "ts", "rate", "interval_h"], symbols=names)
        fu = fu[fu["ts"] <= end + pd.Timedelta(days=2)]                    # the schedule reaches past the last bar; a rate is read only at or after its time
        fu = fu.assign(symbol=fu["symbol"].astype(str)).sort_values(["symbol", "ts"])
    except (FileNotFoundError, ValueError, KeyError):
        notes.append("funding_archive absent: no schedule — every mask is empty")
        return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in I.items()} | masks, notes
    tt = idx.asi8
    arr = {k: I[k].to_numpy() for k in ("P", "fund_due", "funding_last", "interval", "rate_S")}
    marr = {k: masks[k].to_numpy() for k in masks}
    for j, sym in enumerate(names):
        f = fu[fu["symbol"] == sym]
        if f.empty:
            continue
        S = pd.DatetimeIndex(f["ts"]).asi8
        iv, rt = f["interval_h"].to_numpy(dtype=float), f["rate"].to_numpy(dtype=float) * 1e4
        pid = np.searchsorted(S, tt, side="left")                           # settlements strictly before t: the period of the bar closing at t is (S_prev, S_next]
        has_prev, has_next = pid > 0, pid < len(S)
        S_prev = np.where(has_prev, S[np.clip(pid - 1, 0, len(S) - 1)], 0)
        S_next = np.where(has_next, S[np.clip(pid, 0, len(S) - 1)], 0)
        is_S = has_next & (S_next == tt)
        marr["after"][:, j] = is_S
        marr["into"][:, j] = has_next & ~is_S & (S_next - tt == NS_HOUR)
        marr["near"][:, j] = np.isin(tt + NS_HOUR, S) | is_S | np.isin(tt + 2 * NS_HOUR, S) | np.isin(tt - NS_HOUR, S)
        arr["interval"][:, j] = np.where(has_next, iv[np.clip(pid, 0, len(S) - 1)], iv[-1])
        arr["rate_S"][:, j] = np.where(is_S, rt[np.clip(pid, 0, len(S) - 1)], np.nan)
        arr["funding_last"][:, j] = np.where(has_prev, rt[np.clip(pid - 1, 0, len(S) - 1)], np.nan)
        if pw is not None:
            p = pw.iloc[:, j].to_numpy(dtype=float)
            ok = np.isfinite(p)
            cs = pd.Series(np.where(ok, p, 0.0)).groupby(pid).cumsum().to_numpy()
            cn = pd.Series(ok.astype(float)).groupby(pid).cumsum().to_numpy()
            expect = np.where(has_prev, (tt - S_prev) / NS_BAR, np.nan)
            good = has_prev & (cn > 0) & (cn >= P_COVER * expect)
            with np.errstate(invalid="ignore", divide="ignore"):
                P = np.where(good, cs / np.where(cn > 0, cn, 1.0), np.nan)
            Ii = I_8H * arr["interval"][:, j] / 8.0
            arr["P"][:, j] = P
            arr["fund_due"][:, j] = P + np.clip(Ii - P, -CLAMP, CLAMP)
    for k, a in arr.items():
        I[k] = pd.DataFrame(a, index=idx, columns=names)
    for k, a in marr.items():
        masks[k] = pd.DataFrame(a, index=idx, columns=names)
    return {k: v.replace([np.inf, -np.inf], np.nan) for k, v in I.items()} | masks, notes


def features_settle(I: dict[str, pd.DataFrame], cell: pd.DataFrame) -> dict[tuple[str, str, str], pd.DataFrame]:
    """(feature, slot, cells) → the feature on those cells of the grid, signed by the slot where it is a pressure. `I` is on the grid."""
    ev = {"into": I["into"] & cell, "after_1h": I["after"] & cell, "after_4h": I["after"] & cell}
    ctrl = cell & ~I["near"]
    F: dict[tuple[str, str, str], pd.DataFrame] = {}
    for s in SLOTS:
        for k in PRESSURE:
            F[(k, s, EVENT)] = (SIGN[s] * I[k]).where(ev[s])
        F[(PLAIN, s, EVENT)] = (-I["move_1h"]).where(ev[s])
        F[(FAMILY, s, CONTROL)] = (SIGN[s] * I[FAMILY]).where(ctrl)
        F[(PLAIN, s, CONTROL)] = (-I["move_1h"]).where(ctrl)
    return F


# ---- the universes ----------------------------------------------------------------------------------------------------------------------
def _universe(tag: str, A: dict) -> dict:
    M, names, grid, cell, end, latency = A["M"], A["names"], A["grid"], A["cell"], A["end"], A["latency"]
    idx = M.index[M.index >= grid[0] - audit.WARMUP]
    close = M.close.loc[idx, names]
    I5, notes = ingredients(idx, names, close, end)
    at = idx.get_indexer(grid)
    I = {k: v.iloc[at] for k, v in I5.items()}
    I["fund_due_prev_h"] = I5["fund_due"].shift(H1).iloc[at]            # the INTO cell's value, read at the settlement for the formula check
    F = features_settle(I, cell)
    sig = _derive(close)["sig"]["1w"]
    holds = sorted(set(SLOTS.values()))
    Z = {h: (bt.labels(M, h, latency).loc[idx, names] / (sig * np.sqrt(h)).where(sig > 0)).clip(-Z_CLIP, Z_CLIP).iloc[at].where(cell).to_numpy() for h in holds}
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    Y = {}
    for s, h in SLOTS.items():
        y0, y1 = horizon.labels(M, C, h, latency)
        y = (y0 if s == "into" else y1).loc[grid, names].where(cell)           # INTO is flat at S and pays no funding; AFTER carries it
        Y[s] = y.sub(y.mean(axis=1), axis=0).to_numpy()
    ev_cells = int(((I["into"] | I["after"]) & cell).to_numpy().sum())
    cover = float((I["fund_due"].notna() & (I["into"] | I["after"]) & cell).to_numpy().sum() / max(ev_cells, 1))
    sched = _schedule(I, cell)
    lr5 = np.log(close)
    return {"tag": tag, "F": F, "I": I, "Z": Z, "Y": Y, "grid": grid, "cell": cell, "names": names, "A": A, "cover": cover, "notes": notes,
            "event_cells": ev_cells, "schedule": sched, "formula": _formula(I, cell), "lr5": lr5, "idx": idx}


def _schedule(I: dict, cell: pd.DataFrame) -> dict:
    """The settlements on the cells: how many, the share at 00/08/16 UTC, the interval mix."""
    aft = (I["after"] & cell)
    n = int(aft.to_numpy().sum())
    hours = pd.Series(np.repeat(aft.index.hour.to_numpy(), aft.shape[1]).reshape(aft.shape)[aft.to_numpy()])
    iv = pd.Series(I["interval"].to_numpy()[aft.to_numpy()])
    return {"settlements_on_cells": n, "share_at_00_08_16": float(hours.isin([0, 8, 16]).mean()) if n else np.nan,
            "interval_mix": {str(int(k)): int(v) for k, v in iv.value_counts().items()} if n else {}}


def _formula(I: dict, cell: pd.DataFrame) -> dict:
    """At every settlement with ≥ FORMULA_MIN names: the Spearman across names between fund_due at S − 1 h and the settled rate at S, and
    the share of (name, S) within 1 bp; the same with fund_due at S (the full period) described."""
    aft = (I["after"] & cell).to_numpy()
    rate = I["rate_S"].to_numpy()
    out = {}
    for tag, F in (("at_S_minus_1h", I["fund_due_prev_h"].to_numpy()), ("at_S", I["fund_due"].to_numpy())):
        ok = aft & np.isfinite(F) & np.isfinite(rate)
        n = ok.sum(1)
        rows = np.flatnonzero(n >= FORMULA_MIN)
        rhos = []
        for r in rows:
            a, b = F[r, ok[r]], rate[r, ok[r]]
            ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
            if ra.std() > 0 and rb.std() > 0:
                rhos.append(float(np.corrcoef(ra, rb)[0, 1]))
        within = float((np.abs(F[ok] - rate[ok]) <= 1.0).mean()) if ok.any() else np.nan
        out[tag] = {"settlements": int(len(rows)), "pairs": int(ok.sum()), "rho_median": float(np.median(rhos)) if rhos else np.nan,
                    "rho_p10": float(np.quantile(rhos, 0.1)) if rhos else np.nan, "within_1bp": within}
    m = out["at_S_minus_1h"]
    m["assessable"] = bool(m["settlements"] >= FORMULA_MIN_S)
    m["status"] = ("PASS" if (m["rho_median"] >= FORMULA_RHO and m["within_1bp"] >= FORMULA_WITHIN) else "FAIL") if m["assessable"] else "NOT ASSESSABLE"
    return out


# ---- the money ------------------------------------------------------------------------------------------------------------------------------
def fifths(X: np.ndarray, slot: str) -> np.ndarray:
    """The position per cell on each bar with ≥ FIFTH_MIN names: SIGN[slot] × (+1 on the top fifth of X, −1 on the bottom fifth), 0 elsewhere."""
    pos = np.zeros(X.shape)
    ok = np.isfinite(X)
    n = ok.sum(1)
    for r in np.flatnonzero(n >= FIFTH_MIN):
        k = int(np.ceil(n[r] / 5))
        order = np.argsort(np.where(ok[r], X[r], np.nan))                # NaN sort last
        pos[r, order[:k]] = -SIGN[slot]
        pos[r, order[n[r] - k:n[r]]] = SIGN[slot]
    return pos


def _money(pos: np.ndarray, Y: np.ndarray, day: np.ndarray, ks: np.ndarray, group: np.ndarray | None = None) -> dict:
    """The mean of pos × Y over the positions per bar (on the cells of `group` if given), per day, HAC over days; the shift null of the
    labels with the positions fixed."""
    P = pos if group is None else np.where(group, pos, 0.0)
    live = (P != 0) & np.isfinite(Y)
    n = live.sum(1).astype(float)

    def m_day(y):
        with np.errstate(invalid="ignore", divide="ignore"):
            bar = np.where(n > 0, np.nansum(np.where(live, P * y, 0.0), 1) / n, np.nan)
        return pd.Series(bar).groupby(day).mean().reindex(range(int(day.max()) + 1)).to_numpy()
    real = m_day(Y)
    m, se_h, nd = hac(real, 2)
    nulls = np.array([float(np.nanmean(m_day(Y[horizon.shifted(len(Y), int(k))]))) for k in ks]) if len(ks) else np.array([np.nan])
    centre, se = float(np.nanmean(nulls)), float(np.nanstd(nulls, ddof=1)) if len(nulls) > 1 else np.nan
    return {"positions": int(live.sum()), "bars": int((n > 0).sum()), "bps": float(np.nanmean(real)), "se_hac": se_h, "days": int(nd),
            "centre": centre, "se_shift": se, "u": (float(np.nanmean(real)) - centre) / se if se else np.nan}


def _profile(u: dict, day: np.ndarray) -> pd.DataFrame:
    """The 5-minute profile around the settlement on the INTO fifths: the mean over positions of side × the name's 5m log return against
    the event names' mean, from S − 55 to S + 60 min; mean and HAC se over days."""
    grid, idx, lr5, names = u["grid"], u["idx"], u["lr5"], u["names"]
    pos = fifths(u["I"]["fund_due"].where(u["I"]["into"] & u["cell"]).to_numpy(), "into")
    r5 = (lr5.diff() * 1e4).to_numpy()
    at = idx.get_indexer(grid)
    rows = []
    live_bar = (pos != 0).any(1)
    for o in range(1, 2 * PROFILE + 1):
        src = at + o
        okr = live_bar & (src < len(idx))
        R = np.full(pos.shape, np.nan)
        R[okr] = r5[src[okr]]
        ev = (pos != 0) | (np.isfinite(u["I"]["fund_due"].where(u["I"]["into"] & u["cell"]).to_numpy()))
        Rm = R - np.nanmean(np.where(ev, R, np.nan), axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            bar = np.nansum(np.where(pos != 0, pos * Rm, 0.0), 1) / np.where((pos != 0).sum(1) > 0, (pos != 0).sum(1), np.nan)
        d = pd.Series(bar).groupby(day).mean().reindex(range(int(day.max()) + 1)).to_numpy()
        m, se, nd = hac(d, 1)
        rows.append({"offset_min": (o - PROFILE) * 5, "bps": m, "se_hac": se, "days": nd})
    df = pd.DataFrame(rows)
    df["cum_bps"] = df["bps"].cumsum()
    return df


# ---- the verdict --------------------------------------------------------------------------------------------------------------------------
def verdict(r: dict) -> str:
    base = abs(r["u"]) >= U_BAR and r["p_family"] <= P_BAR and r["parts_same_sign"]
    if base and r["ic_c"] > 0:
        if not (r["u_delta"] >= U_BAR):
            return "CLEARS AS THE PLAIN REVERSAL"
        if abs(r.get("control_u", 0.0)) >= U_BAR and abs(r.get("control_ic_c", 0.0)) >= 0.5 * abs(r["ic_c"]):
            return "NOT THE SETTLEMENT'S"
        return "CLEARS"
    if base and r["ic_c"] < 0:
        return "CLEARS WITH THE OPPOSITE SIGN"
    return "CLOSED" if abs(r["ic_c"]) + 1.96 * r["se"] < IC_CLOSED else "NOT DETECTABLE"


# ---- the read ------------------------------------------------------------------------------------------------------------------------------
def run(run: str, pairs: list[str] | None = None, twelve: bool = True, members: str | None = None, jobs: int = 4, name: str | None = None) -> str:
    from joblib import Parallel, delayed
    A = audit.frame(run, members)
    fold_names, grid = A["fold_names"], A["grid"]
    U = [_universe("outside", A)]
    if twelve:
        B = audit_index.cells_twelve(pairs or [], fold_names, A["hold"], A["latency"])
        if not B["grid"].equals(grid):
            raise SystemExit("the twelve's grid is not the run's: the shifts could not be the same")
        U.append(_universe("twelve", B))
    nd = len(grid) // PER_DAY
    day = audit._day(grid)
    whole = bool(len(grid) == nd * PER_DAY and (np.bincount(day)[np.bincount(day) > 0] == PER_DAY).all())
    ks = horizon.shifts(nd, GAP)
    v = {u["tag"]: {**u["A"]["validity"], "event_cells": u["event_cells"], "fund_due_cover": u["cover"], "cover_bar": COVER_BAR[u["tag"]],
                    "schedule": u["schedule"], "formula": u["formula"], "notes": u["notes"]} for u in U}
    v.update({"registration": "R41", "whole_days": whole, "days": nd, "shifts": len(ks), "shifts_expected": nd - 2 * GAP + 1, "gap_days": GAP,
              "slots": SLOTS, "folds": list(fold_names), "run": run})
    ok_u = all(v[u["tag"]]["status"] == "PASS" and u["cover"] >= COVER_BAR[u["tag"]] and u["formula"]["at_S_minus_1h"]["status"] != "FAIL" for u in U)
    ok_f = U[0]["formula"]["at_S_minus_1h"]["status"] == "PASS"                   # the members' settlements must be assessable and pass
    v["status"] = "PASS" if (ok_u and ok_f and whole and len(ks) == nd - 2 * GAP + 1 and len(ks) >= 20) else "FAIL"
    out = OUT / (name or f"{run}_settle")
    out.mkdir(parents=True, exist_ok=True)
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    sizes = " · ".join(f"{u['tag']}: {len(u['names'])} names, {int(u['cell'].to_numpy().sum()):,} cells, {u['event_cells']:,} event cells, fund_due on {u['cover']:.1%}" for u in U)
    head = [f"# R41 — the funding settlement: into it and after it — the cells of `{run}`{' and the twelve' if twelve else ''} (`ft2 audit --family settle`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · folds {'+'.join(fold_names)} · {sizes} · {nd} days · {len(ks)} shifts (gap {GAP} days)\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "audit.md").write_text("\n".join(head + ["\n**The read is VOID: nothing of the family was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    jobs_ = [(u["tag"], k, s, c, F, u["Z"][SLOTS[s]]) for u in U for (k, s, c), F in u["F"].items()]
    print(f"audit --family settle: {len(jobs_)} feature×slot×cells×universe × {len(ks)} shifts on {nd} days…", flush=True)
    res = Parallel(n_jobs=jobs, verbose=5)(delayed(audit_index._ic_shifts)(f"{t}:{k}:{s}:{c}", F, Z, ks, day) for t, k, s, c, F, Z in jobs_)
    d = pd.concat([r for r, _ in res], ignore_index=True)
    d[["universe", "feature", "slot", "cells"]] = d["feature"].str.split(":", expand=True)
    key = ["universe", "feature", "slot", "cells"]
    real = d[d["shift"] == 0].set_index(key)["ic"]
    null = d[d["shift"] > 0]
    st = null.groupby(key)["ic"].agg(centre="mean", se="std")
    null = null.join(st, on=key)
    null["u"] = (null["ic"] - null["centre"]) / null["se"]
    fam_null = null[(null["feature"] == FAMILY) & (null["cells"] == EVENT)]
    mx = fam_null.assign(a=fam_null["u"].abs()).groupby("shift")["a"].max()
    wide_ic = d.pivot_table(index="shift", columns=key, values="ic")
    dates = pd.date_range(grid[0].floor("D"), periods=int(day.max()) + 1, freq="D")
    month = dates.tz_localize(None).to_period("M")
    part = audit_index._parts(dates, fold_names, "index")
    parts = [p for p in dict.fromkeys(part) if p]
    rows = []
    for (t, k, s, c, F, Z), (_, ic_daily) in zip(jobs_, res):
        cen, e = float(st.loc[(t, k, s, c), "centre"]), float(st.loc[(t, k, s, c), "se"])
        ic = float(real[(t, k, s, c)])
        own = null[(null["universe"] == t) & (null["feature"] == k) & (null["slot"] == s) & (null["cells"] == c)]
        per_part = {p: float(np.nanmean(ic_daily[(part == p).to_numpy()])) for p in parts}
        mm = pd.Series(ic_daily).groupby(np.asarray(month)).mean().dropna()
        m_hac, se_hac, _ = hac(ic_daily, day_lags(SLOTS[s]))
        dl = wide_ic[(t, k, s, c)] - wide_ic[(t, PLAIN, s, c)]
        d0, dn = float(dl.loc[0]), dl.loc[dl.index > 0]
        u_delta = (d0 - float(dn.mean())) / float(dn.std()) if k != PLAIN and dn.std() else np.nan
        has = F.notna().to_numpy()
        u_ = U[[x["tag"] for x in U].index(t)]
        base_cells = int(((u_["I"]["into"] | u_["I"]["after"]) & u_["cell"]).to_numpy().sum()) if c == EVENT else int((u_["cell"] & ~u_["I"]["near"]).to_numpy().sum())
        rows.append({"universe": t, "feature": k, "slot": s, "hold": SLOTS[s], "cells": c, "family": k == FAMILY and c == EVENT, "n_cells": int(has.sum()),
                     "coverage": float(has.sum() / max(base_cells, 1)), "ic": ic, "centre": cen, "ic_c": ic - cen, "se": e, "u": (ic - cen) / e if e else np.nan,
                     "t_hac": m_hac / se_hac if se_hac else np.nan, "days": int(np.isfinite(ic_daily).sum()), **{f"ic_{p}": per_part[p] for p in parts},
                     "parts_same_sign": bool(len({np.sign(per_part[p]) for p in parts}) == 1), "months_same_sign": float((np.sign(mm) == np.sign(ic - cen)).mean()) if len(mm) else np.nan,
                     "mde": MDE_K * e, "upper": abs(ic - cen) + 1.96 * e, "p_single": (1 + int((own["u"].abs() >= abs((ic - cen) / e)).sum())) / (len(own) + 1),
                     "p_family": (1 + int((mx >= abs((ic - cen) / e)).sum())) / (len(mx) + 1), "delta_vs_plain": d0 - float(dn.mean()) if k != PLAIN else np.nan, "u_delta": u_delta})
    tab = pd.DataFrame(rows)
    ctrl = tab[(tab["feature"] == FAMILY) & (tab["cells"] == CONTROL)].set_index(["universe", "slot"])
    tab["control_ic_c"] = [float(ctrl.loc[(r.universe, r.slot), "ic_c"]) if r.family else np.nan for r in tab.itertuples()]
    tab["control_u"] = [float(ctrl.loc[(r.universe, r.slot), "u"]) if r.family else np.nan for r in tab.itertuples()]
    tab["verdict"] = [verdict(r._asdict()) if r.family else ("control" if r.cells == CONTROL else "reference") for r in tab.itertuples()]
    fam_tab, ref_tab, ctl_tab = tab[tab["family"]], tab[~tab["family"] & (tab["cells"] == EVENT)], tab[tab["cells"] == CONTROL]

    # the money: the fifths per slot and universe, by interval and by the settlement hour; the profile; the run's forecast on the event cells
    mon, prof, ref_rows = [], [], []
    for u in U:
        t, I = u["tag"], u["I"]
        iv = I["interval"].to_numpy()
        hour_of_S = pd.Series(grid).dt.hour.to_numpy()
        for s in SLOTS:
            mask = (I["into"] if s == "into" else I["after"]) & u["cell"]
            pos = fifths(I["fund_due"].where(mask).to_numpy(), s)
            hS = ((hour_of_S + 1) % 24) if s == "into" else hour_of_S
            base = {"universe": t, "slot": s, "hold": SLOTS[s], "cost_round_trip": COST.get(t, np.nan)}
            mon.append({**base, "cut": "all", **_money(pos, u["Y"][s], day, ks)})
            for h_, lab in ((8, "8h names"), (4, "4h names")):
                mon.append({**base, "cut": lab, **_money(pos, u["Y"][s], day, ks[:0], group=(iv == h_))})
            for hh in (0, 8, 16):
                mon.append({**base, "cut": f"S at {hh:02d} UTC", **_money(pos, u["Y"][s], day, ks[:0], group=np.broadcast_to((hS == hh)[:, None], pos.shape))})
            mon.append({**base, "cut": "S at other hours", **_money(pos, u["Y"][s], day, ks[:0], group=np.broadcast_to((~np.isin(hS, [0, 8, 16]))[:, None], pos.shape))})
        p = _profile(u, day)
        p.insert(0, "universe", t)
        prof.append(p)
        if t == "outside":
            zh = u["A"]["o"].pivot(index="t", columns="symbol", values="zhat").reindex(index=grid, columns=u["names"])
            for s in SLOTS:
                mask = ((I["into"] if s == "into" else I["after"]) & u["cell"]).to_numpy()
                m_, t_ = audit_index._ic_on(zh.where(pd.DataFrame(mask, index=grid, columns=u["names"])), u["Z"][SLOTS[s]], day, hold=SLOTS[s])
                ref_rows.append({"universe": t, "row": "the run's forecast (R18's candle ridge) on the event cells", "slot": s, "ic": m_, "t_hac": t_})
    money = pd.DataFrame(mon)
    profile = pd.concat(prof, ignore_index=True)
    ref2 = pd.DataFrame(ref_rows)

    clears = fam_tab[fam_tab["verdict"] == "CLEARS"]
    show = lambda df, k=4: df.round(k).to_markdown(index=False)                        # noqa: E731
    main = ["universe", "feature", "slot", "cells", "n_cells", "coverage", "ic", "centre", "ic_c", "se", "u", "t_hac", "p_single", "p_family", "mde", "upper", "delta_vs_plain", "u_delta"]
    more = ["universe", "feature", "slot", "days", *(f"ic_{p}" for p in parts), "parts_same_sign", "months_same_sign"]
    md = head + [
        "\nWords: *fund_due* is the funding rate due at the name's next settlement (bps), the period's mean premium index clamped by Binance's formula; *P* that mean "
        "unclamped; *prem_dev* the last premium against its 30-day mean; *funding_last* the previous settled rate; *rev_1h* the plain reversal of the last hour. A feature is "
        "SIGNED by its slot: − into the settlement (the payers lag), + after it (they come back), so a positive IC is the hypothesis. *into*: the cell an hour before S with "
        "the label ending AT S (11 bars); *after_1h*, *after_4h*: the cell at S. *IC* is the correlation, across the names in an event at one moment, between the feature and "
        "the move that followed; *centre* the IC when the moves come from other days (time of day kept), *ic_c* = IC − centre, *se* its spread, *u* = ic_c / se; *p (family)*: the "
        "share of shifts in which the BEST of the six did at least as well; *delta_vs_plain*, *u_delta*: against the plain reversal on the same cells and shifts. *control*: the "
        "same feature on hourly cells with no settlement near — a clear that the control shares at half its size is not the settlement's.\n",
        f"\n## The family — six numbers: **{len(clears)} of {len(fam_tab)} clear the gate** (|u| ≥ {U_BAR:g}, family-wise p ≤ {P_BAR:g}, one sign in {', '.join(parts)}, ic_c > 0, "
        f"u_Δ ≥ {U_BAR:g} against the plain reversal, the control not at half the size){': ' + ', '.join(f'{a} {b}' for a, b in zip(clears['universe'], clears['slot'])) if len(clears) else ''}. "
        f"Over the shifts the best of the six reaches |u| {mx.mean():.2f} on average, {mx.quantile(0.95):.2f} one time in twenty.\n",
        show(fam_tab[main + ["control_ic_c", "control_u", "verdict"]]), "\n",
        "\n### Described (decides nothing)\n", show(fam_tab[more]), "\n",
        "\n## The control — the family on hourly cells with no settlement near (described)\n", show(ctl_tab[main + ["verdict"]]), "\n",
        "\n## Reference rows — the raw premium, N1's deviation, the previous rate, the plain reversal (no verdict)\n", show(ref_tab[main]), "\n", show(ref_tab[more]), "\n",
        show(ref2) if len(ref2) else "", "\n",
        f"\n## The money — the fifths (described, actual returns against the peers, before trading costs; INTO without funding, AFTER with funding on value)\n",
        f"\nOn each event bar with ≥ {FIFTH_MIN} names: INTO short the top fifth of fund_due and long the bottom fifth from S − 55 min to S; AFTER long the top fifth and short "
        "the bottom from S + 5 min for an hour and for four. *bps*: the mean a position earns against the bar's peers; *se_hac* over days; *centre*, *se_shift*, *u*: the "
        "same under the shifts of the labels (the 'all' rows only). Against *cost_round_trip*, a taker's.\n",
        show(money), "\n",
        f"\n## The profile — the INTO fifths' side × the 5-minute move against the event's names, from S − 55 to S + 60 min (described; bps a bar, HAC se over days)\n",
        show(profile), "\n",
        *(f"\n- {u['tag']}: a taker round trip costs about {COST.get(u['tag'], float('nan')):.1f} bps on these names (R20 / P1); the schedule on the cells: {json.dumps(u['schedule'])}; "
          f"the formula check: {json.dumps(u['formula']['at_S_minus_1h'])}.\n" for u in U)]
    text = "\n".join(md)
    (out / "audit.md").write_text(text)
    tab.to_csv(out / "features.csv", index=False)
    money.to_csv(out / "money.csv", index=False)
    profile.to_csv(out / "profile.csv", index=False)
    ref2.to_csv(out / "reference.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "null_max_u_p95": float(mx.quantile(0.95))}, indent=1, default=str))
    print(f"R41: {len(clears)} of {len(fam_tab)} clear; wrote {out}/", flush=True)
    return text
