"""P8, R75 — the exchange's squeeze flag, bought: when Binance SHORTENS a running perpetual's funding-settlement interval while the shorts
are paying the floor, does a LONG position entered at that settlement and held 1, 3 and 7 days earn, with the funding it receives, more
against the screener's members than its round trip? `ft2 fundevent fingerprint|run|check` (PLAN §8 R75 is the registration; this file is
its code and changes nothing of it; decision BV1 — F3+F4's FIRST read for the quantity, by registration, the guard rows before the market).

events     the FROZEN `ft2/fundfreq_f34.csv` (decision BU1's audit, DATA.md `fund_freq_events`; md5 as registered): 116 rows — the gate's
           cells are the 66 SHORTENINGS with `at_floor`; the five positive-funding shortenings and the 45 lengthenings are described apart.
           Nothing is added, dropped or re-dated here; an event the entry rule cannot hold is counted by reason.
entry      t0 = the settlement's own stamp (ts_known = t0); the decision bar is the 5m bar that closes at t = t0 + 5 min; the position
           is entered one bar later (the harness's latency): t0 + 10 min. LONG.
label      R28's: a = what a long earns before trading costs with the funding it pays — a negative rate PAYS the long (`listing.label_at`
           = `horizon.labels`' number); b = the mean over the members of the F3+F4 block that holds t, the name itself left out
           (`listing.excess`); y = a − b. A long earns +y.
statistic  M = the mean of y per hold (1d / 3d / 7d, the family); R28's moving-block bootstrap over calendar weeks (`listing.bootstrap`,
           seed 75); family-wise over the three holds. The sign POSITIVE: the gate reads M ≥ +B.
bar        B = the mean over the eligible cells of B_i = 2 × the name's own taker round trip on the DEARER of its entry day and the day
           before (2 legs × (fee + half spread + impact)); a name without a row on either takes its last within 7 days before, else R28's 46.
run-up     y over t0 − 24 h → t0 (no latency), the validity-of-mechanism row — read first, no gate.
guard      the rows (R75, F3) / (R75, F4) are appended to the ledger BEFORE the funding archive is re-read and BEFORE the market is loaded
           (`backtest._guard` checks the block, the once-per-question rule and a re-execution's tag; `krevent.guard_rows` writes).
validity   (1) the archive slice's fingerprint before (`fingerprint`) and after (`check`); (2) the list's md5 and every frozen row's t0 /
           prev_h / new_h re-derived from `funding_archive` by `fundfreq.changes`; (3) ≥ 90 % and ≥ 60 eligible, ≥ 90 % with their own
           cost row; (4) bars and labels ≥ 95 %; (5) members ≥ 40; (6) the label identity with `horizon.labels`, the harness and a hand
           check of 20 cells from the raw bars and the settlement rows; (7) t = t0 + 5 min and ts_known = t0 for every cell; (8) the
           settlement rows inside the hold: a cell with a gap in them is counted, over 5 % of the cells a void.

R77 (PLAN §8, decision BY1, registered 2026-11-02) runs the SAME frame through a `Spec` (R75's values the default, read at call time):
the frozen `ft2/fundep_f12.csv` (decision BY1's audit, DATA.md `fund_episodes`; 60 episodes, every row a cell, all bought), F1+F2 and
`ft2/screen_members.csv`, NO guard (the exploration folds), the rederivation by `fundep.episodes`, and the GATE ON THE 10 % TRIMMED MEAN
(`bootstrap_trimmed`: the same block draw over weeks, each draw's statistic the trimmed mean of its cells' y, k = round(0.05 × n)); the
plain mean, the median, the share above zero and the mean without the five largest beside; the splits flagged / member / first episode /
clock / the day's sum; `output/listing/r77/`. `listing.py`, `krevent.py`, `fundep.py` untouched; R75's and R76's paths unchanged.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import fundfreq, horizon, krevent, krlist, listing, universe
from .ceiling import BAR

NAME = "r75"
OUT = listing.OUT                                  # output/listing
LIST = fundfreq.LISTS["f34"]
LIST_MD5 = "287fa8ca293dd57d131306c1b3a70554"      # as registered (PLAN §8 R75)
LIST_ROWS = 116
CELLS = 66                                         # the at-floor shortenings
FOLDS = ("F3", "F4")
HOLDS = (288, 864, 2016)                           # 1, 3, 7 days — the family
WAIT = 1                                           # bars from t0 to the decision bar's close: 5 minutes
RUNUP = 288                                        # the run-up row: t0 − 24 h → t0
LATE = 288                                         # reference row: the entry a day later
TAKER_BPS = 5.0
BAR_MULT = 2.0                                     # B_i = this × the name's own round trip on the dearer day
BAR_R28 = 46.0
FALLBACK_DAYS = 7
BLOCK_WEEKS, DRAWS, SEED = 6, 10_000, 75
TRIM = 3
MIN_MEMBERS, MIN_OWN_COST, MIN_BARS, MIN_LABELS = 40, 0.90, 0.95, 0.95
MIN_ELIGIBLE, MIN_ELIGIBLE_SHARE = 55, 0.85             # the re-execution `calendar_revert` (R75's Result): the registration's 60 / 90 % could not be met by its own calendar rule on the frozen list (58 of 66, the eight December cells)
MAX_GAP_SHARE = 0.05                               # validity (8): cells with a gap in their settlement rows
GAP_TOL = 1.5                                      # a gap between consecutive settlements over this × the LARGER of the two rows' intervals is a missing row (a revert inside the hold is a row, not a gap — the re-execution `calendar_revert`)
HAND_CELLS = 20
BTC = "BTCUSDT"
STRATEGY = "fundfreq_bought"
FP_BEFORE = OUT / f"{NAME}_fingerprint_before.csv"
FP_CHECK = OUT / f"{NAME}_fingerprint_check.json"
RULE_START, FORMULA_CHANGE = fundfreq.RULE_START, fundfreq.FORMULA_CHANGE
SPLITS = {"era": None, "formula": None, "fold": None, "member_at_t0": ("member at t0", "not a member")}
DATE_COLS = ("t0", "ts_known", "perp_first", "pair_of", "notice_release")

md5 = krevent.md5
family_verdict = krevent.family_verdict
guard_rows = krevent.guard_rows


def _days(h: int) -> str:
    return f"{h // 288}d"


# ---- the frozen events ----------------------------------------------------------------------------------------------------------
def load_events(path: Path | str = LIST) -> pd.DataFrame:
    L = pd.read_csv(path)
    for c in DATE_COLS:
        if c in L:
            L[c] = pd.to_datetime(L[c], utc=True, format="ISO8601")
    L["era"] = np.where(L["t0"] < RULE_START, "notice", "rule")
    L["formula"] = np.where(L["t0"] < FORMULA_CHANGE, "before 2025-09-18", "after 2025-09-18")
    if "prior_episodes" in L:                                      # an episode list (R77): the described splits' columns
        L["first_episode"] = L["prior_episodes"].astype(int) == 0
        L["clock"] = L["interval_h"].astype(float).astype(int).astype(str) + "h"
        L["sum_half"] = np.where(L["fund_1d"].abs() >= L["fund_1d"].abs().median(), "day's sum ≥ median", "day's sum < median")
    return L


def cells(L: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(the cells, the positive-funding shortenings, the lengthenings): a shortening with the trailing day's funding negative is a cell."""
    short = L["dir"] == "shorter"
    floor = short & L["at_floor"].astype(bool)
    return (L[floor].reset_index(drop=True), L[short & ~floor].reset_index(drop=True), L[~short].reset_index(drop=True))


def rederived(L: pd.DataFrame) -> dict:
    """Validity (2): every frozen row's t0, prev_h and new_h are what `fundfreq.changes`' rule gives from `funding_archive` today."""
    try:
        C = fundfreq.changes(fundfreq.settlements())
    except Exception as e:                                         # noqa: BLE001 — recorded, and the validity fails
        return {"status": "MISSING", "why": str(e)[:200]}
    C = C.set_index(["symbol", "t0"])
    bad = []
    for r in L.itertuples(index=False):
        k = (r.symbol, r.t0)
        if k not in C.index:
            bad.append({"symbol": r.symbol, "t0": str(r.t0), "why": "no interval change at this settlement today"})
        else:
            x = C.loc[k]
            if float(x["prev_h"]) != float(r.prev_h) or float(x["new_h"]) != float(r.new_h):
                bad.append({"symbol": r.symbol, "t0": str(r.t0), "why": "the interval differs", "frozen": [float(r.prev_h), float(r.new_h)], "today": [float(x["prev_h"]), float(x["new_h"])]})
    return {"status": "PASS" if not bad else "FAIL", "rows": int(len(L)), "changes_today": int(len(C)), "bad": bad}


# ---- entries --------------------------------------------------------------------------------------------------------------------
def entries(M: bt.Market, L: pd.DataFrame, end: pd.Timestamp, first_block: pd.Timestamp, wait: int = WAIT, latency: int = bt.LATENCY, longest: int = max(HOLDS)) -> pd.DataFrame:
    """Per frozen event: the decision row (the bar closing at t0 + wait bars) and why it is or is not eligible. t0 is GIVEN by the list."""
    idx, n = M.index, len(M.index)
    cl = M.close.to_numpy()
    col = M.columns.get_indexer(L["symbol"])
    rows = []
    for c, t0 in zip(col, L["t0"]):
        t = t0 + wait * BAR
        row = int(idx.get_indexer([t])[0])
        if c < 0:
            why, row = "no bars of the name in the market", -1
        elif row < 0:
            why = "the decision bar is not in the market"
        elif idx[row] < first_block:
            why = "before the first member block"
        elif row + latency >= n or not (np.isfinite(cl[row, c]) and np.isfinite(cl[row + latency, c])):
            why = "no close at the decision or entry bar"
        else:
            x = row + latency + longest
            why = "the 7-day exit is not before the end" if x >= n or not idx[x] < end else ""
        rows.append({"t": t, "row": row, "why": why})
    out = pd.concat([L.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    out["eligible"] = out["why"] == ""
    return out


# ---- the bar: the name's own doubled round trip on the dearer of the entry day and the day before -------------------------------------
def bars_per_event(C: bt.Costs, own: np.ndarray, t: pd.DatetimeIndex, taker_bps: float = TAKER_BPS, mult: float = BAR_MULT, fallback_days: int = FALLBACK_DAYS, r28: float = BAR_R28) -> pd.DataFrame:
    """B_i = mult × 2 legs × (fee + taker_leg) on the DEARER of the entry day's row and the day before's; one of them missing, the other;
    both missing, the last row within `fallback_days` before the entry day; none, R28's constant."""
    days = pd.DatetimeIndex(C.days)
    dn = days.as_unit("ns").asi8 if days.tz is None else days.tz_convert("UTC").tz_localize(None).as_unit("ns").asi8
    one_day = 86_400 * 10 ** 9
    out = []
    for c, ti in zip(own, pd.DatetimeIndex(t)):
        day = int(np.datetime64(ti.tz_convert("UTC").floor("D").tz_localize(None), "ns").astype("int64"))
        p = int(np.searchsorted(dn, day, "right")) - 1
        leg, src, used = np.nan, "R28's 46", pd.NaT
        two = {}
        q = p
        while q >= 0 and (day - dn[q]) // one_day <= 1:                # the entry day and the day before
            v = C.taker_leg[q, c]
            if np.isfinite(v):
                two[int((day - dn[q]) // one_day)] = (float(v), pd.Timestamp(dn[q], tz="UTC"))
            q -= 1
        if two:
            back = max(two, key=lambda k: two[k][0])                   # the dearer of the two
            leg, used = two[back]
            src = "own day" if back == 0 else "day before"
        else:
            while p >= 0:
                back = (day - dn[p]) // one_day
                if back > fallback_days:
                    break
                v = C.taker_leg[p, c]
                if np.isfinite(v):
                    leg, src, used = float(v), f"within {fallback_days} d", pd.Timestamp(dn[p], tz="UTC")
                    break
                p -= 1
        b = mult * 2.0 * (taker_bps + leg) if np.isfinite(leg) else r28
        out.append({"taker_leg": leg, "cost_day": used, "B_source": src, "B_i": b})
    return pd.DataFrame(out)


# ---- the gate: the sign POSITIVE ---------------------------------------------------------------------------------------------------------
def hold_verdict(m: float, se: float, u: float, p_fw: float, m_f3: float, m_f4: float, m_trim: float, bar: float) -> str:
    if m >= bar and abs(u) >= 2 and p_fw <= 0.05 and m_f3 > 0 and m_f4 > 0 and m_trim >= bar:
        return "CLEARS"
    if m <= -bar and abs(u) >= 2 and p_fw <= 0.05 and m_f3 < 0 and m_f4 < 0 and m_trim <= -bar:
        return "CLEARS WITH THE OPPOSITE SIGN"
    if abs(m) + 1.96 * se < bar:
        return "under the bar"
    return "NOT DETECTABLE"


# ---- the funding leg: the settlement rows inside the hold (validity (6) hand check and (8)) -----------------------------------------------
def settlement_rows(S: pd.DataFrame, symbol: str, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
    """The archive's rows of the name with a < ts ≤ b — the payments a position entered at the bar closing at a and exited at b bears."""
    g = S[S["symbol"] == symbol]
    return g[(g["ts"] > a) & (g["ts"] <= b)].sort_values("ts")


def hand_a(close: np.ndarray, idx: pd.DatetimeIndex, S: pd.DataFrame, symbol: str, c: int, e: int, x: int) -> tuple[float, float, int]:
    """(a, the funding part, the settlements) from the raw bars and the settlement rows: exit ÷ entry − 1 in bps, minus Σ rate × the
    close at or before the settlement ÷ the entry close (the harness's `fundval` rule, `backtest.CHARGED` = value), each row inside the hold."""
    pe, px = close[e, c], close[x, c]
    rows = settlement_rows(S, symbol, idx[e], idx[x])
    at = np.clip(idx.searchsorted(pd.DatetimeIndex(rows["ts"]), "right") - 1, 0, None)
    col = pd.Series(close[:, c]).ffill().to_numpy()
    fund = float(np.nansum(rows["rate"].to_numpy() * 1e4 * col[at])) / pe if len(rows) else 0.0
    return (px / pe - 1.0) * 1e4 - fund, -fund, int(len(rows))


def settlement_gaps(S: pd.DataFrame, symbol: str, t0: pd.Timestamp, exit_t: pd.Timestamp, tol: float = GAP_TOL) -> dict:
    """Validity (8): the name's rows from t0 to the 7-day exit; a gap between consecutive rows over `tol` × the larger of the two rows'
    intervals is a missing row (at a revert the gap equals the later row's interval — the archive's own row, not a gap). Returns the count of
    rows, the largest gap ÷ its interval, and whether a gap was found."""
    g = S[(S["symbol"] == symbol) & (S["ts"] >= t0) & (S["ts"] <= exit_t)].sort_values("ts")
    if len(g) < 2:
        return {"n_rows": int(len(g)), "max_gap_ratio": np.nan, "gap": len(g) < 2}
    gap_h = (g["ts"].to_numpy()[1:] - g["ts"].to_numpy()[:-1]) / np.timedelta64(1, "h")
    h = g["interval_h"].to_numpy()
    ratio = gap_h / np.maximum(h[:-1], h[1:])
    return {"n_rows": int(len(g)), "max_gap_ratio": float(ratio.max()), "gap": bool((ratio > tol).any())}


# ---- the fingerprint (validity (1)) -------------------------------------------------------------------------------------------------
def fp_paths(name: str | None) -> tuple[Path, Path]:
    if not name or name == NAME:
        return FP_BEFORE, FP_CHECK
    return OUT / f"{name}_fingerprint_before.csv", OUT / f"{name}_fingerprint_check.json"


def fingerprint(name: str | None = None) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    before, _ = fp_paths(name)
    fp = krlist.fingerprint()
    fp.to_csv(before, index=False)
    return f"{len(fp)} names of {krlist.SLICE} fingerprinted → {before}"


def check(name: str | None = None) -> dict:
    fp_before, fp_check = fp_paths(name)
    if not fp_before.exists():
        raise SystemExit(f"fundevent check: no fingerprint before at {fp_before} — run `ft2 fundevent fingerprint` before the run")
    before = pd.read_csv(fp_before)
    r = krlist.fingerprint_check(before, after_fn=krlist.fingerprint)
    r["status"] = "PASS" if r["pass"] else "FAIL"
    fp_check.write_text(json.dumps(r, indent=1, default=str))
    v = OUT / (name or NAME) / "validity.json"
    if v.exists():
        V = json.loads(v.read_text())
        V["1_fingerprint_after"] = r["status"]
        v.write_text(json.dumps(V, indent=1))
    print(f"fingerprint after the run: {r['status']} — {r['names_before']} names before, {r['names_after']} after, {len(r['changed'])} changed → {fp_check}")
    return r


# ---- R77 (decision BY1): the same frame on the frozen episode list, the gate on the trimmed mean, no guard -----------------------------------
from . import fundep  # noqa: E402

NAME77 = "r77"
LIST77 = fundep.LISTS["f12"]
LIST77_MD5 = "75c0fbd0512421e67a093a338e8cbf98"    # as registered (PLAN §8 R77; frozen 7cf47a1)
LIST77_ROWS, CELLS77 = 60, 60
FOLDS77 = ("F1", "F2")
SEED77 = 77
TRIM_FRAC = 0.05                                   # the 10 % trimmed mean: round(0.05 × n) out at each end — 3 and 3 on 58
MIN_ELIGIBLE77, MIN_ELIGIBLE_SHARE77, MAX_DROPPED77 = 56, 0.90, 4
EXPECTED_DROPPED77 = {("1000FLOKIUSDT", "2024-08-30 00:00:00+00:00"), ("RDNTUSDT", "2024-08-30 16:00:00+00:00")}   # the audit's two, by the calendar
STRATEGY77 = "fundep_bought"
SPLITS77 = {"flagged_7d": ("flagged within 7 d", "not flagged"), "member_at_t0": ("member at t0", "not a member"), "first_episode": ("first episode", "a repeat"),
            "clock": None, "sum_half": None, "fold": None}


@dataclasses.dataclass
class Spec:
    """What differs between R75's read and R77's; everything else of `run` is shared and unchanged."""
    registration: str
    name: str
    title: str
    decision: str
    list: Path
    md5: str
    rows: int
    n_cells: int
    folds: tuple
    members_csv: Path | str
    strategy: str
    guard: bool
    gate: str                                      # "mean" (R75) or "trimmed" (R77)
    seed: int
    splits: dict
    cells: object                                  # L → (the cells, the positive-funding shortenings described, the lengthenings described)
    rederive: object                               # L → validity (2)'s dict
    min_eligible: int
    min_share: float
    max_dropped: int | None = None
    expected_dropped: set | None = None


def cells_all(L: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """R77: every frozen row is a cell (the list holds the bought side only); nothing described apart."""
    return L.reset_index(drop=True), L.iloc[0:0].reset_index(drop=True), L.iloc[0:0].reset_index(drop=True)


def rederived_episodes(L: pd.DataFrame) -> dict:
    """R77's validity (2): every frozen row's t0 is an episode under `fundep.episodes`' rule from `funding_archive` today (the same threshold,
    quiet window and age rule) and its fund_1d agrees to 1e-12."""
    try:
        S = fundfreq.settlements()
        T = fundep.trailing(S)
        FS = fundep.first_stamps(S)
        E = fundep.episodes(T, float(L["thr"].iloc[0]), FS["perp_first"]).set_index(["symbol", "t0"])
    except Exception as e:                                         # noqa: BLE001 — recorded, and the validity fails
        return {"status": "MISSING", "why": str(e)[:200]}
    bad = []
    for r in L.itertuples(index=False):
        k = (r.symbol, r.t0)
        if k not in E.index:
            bad.append({"symbol": r.symbol, "t0": str(r.t0), "why": "no episode at this settlement today"})
        elif abs(float(E.loc[k, "fund_1d"]) - float(r.fund_1d)) > 1e-12:
            bad.append({"symbol": r.symbol, "t0": str(r.t0), "why": "fund_1d differs", "frozen": float(r.fund_1d), "today": float(E.loc[k, "fund_1d"])})
    return {"status": "PASS" if not bad else "FAIL", "rows": int(len(L)), "episodes_today": int(len(E)), "bad": bad}


def spec_for(registration: str | None) -> Spec:
    """R77's spec by its registration; R75's otherwise — both read the module's constants at call time (the tests replace them)."""
    if registration == "R77":
        return Spec("R77", NAME77, "R77 — the extreme-funding episode, bought, without the exchange's flag: LONG at the first settlement past 2 % a day on the frozen F1+F2 episode list, the gate on the 10 % trimmed mean",
                    "BY1", LIST77, LIST77_MD5, LIST77_ROWS, CELLS77, FOLDS77, universe.MEMBERS_CSV, STRATEGY77, False, "trimmed", SEED77, SPLITS77, cells_all, rederived_episodes,
                    MIN_ELIGIBLE77, MIN_ELIGIBLE_SHARE77, MAX_DROPPED77, EXPECTED_DROPPED77)
    return Spec("R75", NAME, "R75 — the exchange's squeeze flag, bought: LONG at the at-floor shortenings of the funding interval", "BV1", LIST, LIST_MD5, LIST_ROWS, CELLS, FOLDS,
                universe.F34_MEMBERS_CSV, STRATEGY, True, "mean", SEED, SPLITS, cells, rederived, MIN_ELIGIBLE, MIN_ELIGIBLE_SHARE)


def k_trim(n: int, frac: float = TRIM_FRAC) -> int:
    return max(1, int(round(frac * n)))


def bootstrap_trimmed(Y: np.ndarray, wk: np.ndarray, W: int, frac: float = TRIM_FRAC, block: int = BLOCK_WEEKS, draws: int = DRAWS, seed: int = SEED77) -> dict:
    """R77's statistic and its noise: `listing.bootstrap`'s draw (⌈W/block⌉ circular runs of `block` consecutive weeks, cut to W), each
    draw's statistic the TRIMMED mean of the y of the cells in its weeks (k = round(frac × that draw's n) out at each end, per hold);
    se = the sd of the draws; u = M_trim ÷ se; the family-wise p two-sided over the holds."""
    fin = np.isfinite(Y)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, W, size=(draws, int(np.ceil(W / block))))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % W).reshape(draws, -1)[:, :W]
    by_week = [np.where(wk == w)[0] for w in range(W)]

    def tm(v: np.ndarray) -> float:
        v = np.sort(v[np.isfinite(v)])
        k = k_trim(len(v), frac)
        return float(v[k:-k].mean()) if len(v) > 2 * k else np.nan

    m = np.array([tm(Y[:, h]) for h in range(Y.shape[1])])
    Ms = np.empty((draws, Y.shape[1]))
    for d in range(draws):
        rows = np.concatenate([by_week[w] for w in idx[d]])
        for h in range(Y.shape[1]):
            Ms[d, h] = tm(Y[rows, h])
    Ms = Ms[np.isfinite(Ms).all(1)]
    se = Ms.std(axis=0, ddof=1)
    u = m / se
    T = (np.abs(Ms - m) / se).max(axis=1)
    return {"m": m, "se": se, "u": u, "p_fw": float((T >= np.abs(u).max()).mean()), "draws": len(Ms), "k": [k_trim(int(fin[:, h].sum()), frac) for h in range(Y.shape[1])],
            "n": fin.sum(0).astype(int)}


# ---- the run ------------------------------------------------------------------------------------------------------------------------------
def _frame(E: pd.DataFrame) -> pd.DataFrame:
    return E.rename(columns={"symbol": "contract"})


def _split_rows(E: pd.DataFrame, Y: dict, key: str, labels) -> pd.DataFrame:
    out = []
    vals = E[key]
    for v in (sorted(vals.unique(), key=str) if labels is None else (True, False)):
        m = (vals == v).to_numpy()
        name = str(v) if labels is None else labels[0 if v else 1]
        for h in HOLDS:
            y = Y[h][m]
            y = y[np.isfinite(y)]
            out.append({"split": key, "group": name, "hold": _days(h), "n": int(len(y)), "M": float(y.mean()) if len(y) else np.nan, "median": float(np.median(y)) if len(y) else np.nan,
                        "share_above_0": float((y > 0).mean()) if len(y) else np.nan, "se_plain": float(y.std(ddof=1) / np.sqrt(len(y))) if len(y) > 1 else np.nan})
    return pd.DataFrame(out)


def _labels(close, fv, rows, own, mask) -> tuple[dict, dict, dict, dict]:
    A, B, NB, Y = ({} for _ in range(4))
    for h in HOLDS:
        A[h], B[h], NB[h] = listing.excess(listing.label_at(close, fv, rows, h), own, mask)
        Y[h] = A[h] - B[h]
    return A, B, NB, Y


def run(registration: str | None, name: str | None = None, taker_bps: float = TAKER_BPS, reexecute: str | None = None, spec: Spec | None = None) -> str:
    spec = spec or spec_for(registration)
    name = name or spec.name
    fa, fb = spec.folds[0], spec.folds[-1]
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fp_before, _ = fp_paths(name)
    L = load_events(spec.list)
    list_md5 = md5(spec.list)
    cl, pos, lng = spec.cells(L)
    pre = {"1_fingerprint_before": "saved" if fp_before.exists() else "MISSING", "1_fingerprint_after": f"pending → `ft2 fundevent check{'' if name == NAME else ' --name ' + name}` after the run",
           "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == spec.md5, "2_list_rows": int(len(L)), "2_cells": int(len(cl)), "2_cells_as_registered": len(cl) == spec.n_cells,
           "2_positive_funding_shortenings_described": pos[["symbol", "t0"]].astype(str).to_dict("records"), "2_lengthenings_described": int(len(lng))}
    params = {"holds": list(HOLDS), "side": "long", "wait": WAIT, "bar_mult": BAR_MULT, "list": spec.list.name, "list_md5": list_md5, "cells": int(len(cl)), "seed": spec.seed, "gate": spec.gate}
    if spec.guard:
        conf = bt._guard(spec.folds, registration, reexecute)      # registered, and once (refuses before anything is loaded)
        tagged = bt.read_tag(registration, reexecute)
        stamp = guard_rows(bt.READS, conf, tagged, spec.strategy, params)   # the rows (R75[/tag], F3) / (…, F4) NOW — before the funding archive is re-read and before the market
        pre["6_guard"] = {"status": "PASS", "appended_at": stamp, "ledger": str(bt.READS), "folds": list(conf), "logged_as": tagged}
        print(f"guard: ({tagged}, {', '.join(conf)}) appended to {bt.READS} at {stamp}; the funding archive and the {fa}+{fb} market are loaded now", flush=True)
    else:
        if registration != spec.registration:                     # the exploration folds: no ledger row, but the read is the registration's
            raise SystemExit(f"fundevent run: {spec.name}'s read is {spec.registration}'s — pass --registration {spec.registration}")
        conf, tagged = spec.folds, (registration if not reexecute else f"{registration}/{reexecute}")
        pre["6_guard"] = {"status": "none — the exploration folds, no ledger row", "folds": list(conf), "logged_as": tagged}

    red = spec.rederive(L)                                         # validity (2), after the guard: the archive is read whole
    S = fundfreq.settlements()
    a0, end = listing.window(spec.folds)
    mem = universe.members(spec.members_csv)
    first_block = mem["block"].min()
    syms = list(dict.fromkeys([*cl["symbol"], *pos["symbol"], *lng["symbol"], *universe.screen_symbols(spec.members_csv), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, fv, idx = M.close.to_numpy(), C.fundval, M.index
    E_all = entries(M, cl, end, first_block)
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    rows, own = E["row"].to_numpy(), M.columns.get_indexer(E["symbol"])
    t = pd.DatetimeIndex(E["t"])

    # labels: the family, the run-up, the entry a day later, the benchmark of BTC
    mask, mask_late = listing.member_mask(mem, M.columns, t), listing.member_mask(mem, M.columns, t + LATE * BAR)
    btc = np.full(len(E), M.columns.get_loc(BTC))
    A, B, NB, Y = _labels(close, fv, rows, own, mask)
    YL, YB, PRICE = {}, {}, {}
    for h in HOLDS:
        lab = listing.label_at(close, fv, rows, h)
        al, bl, _ = listing.excess(listing.label_at(close, fv, rows + LATE, h), own, mask_late)
        YL[h], YB[h] = al - bl, A[h] - lab[np.arange(len(E)), btc]
        d = _days(h)
        e_, x_ = rows + bt.LATENCY, rows + bt.LATENCY + h
        with np.errstate(invalid="ignore", divide="ignore"):
            PRICE[h] = (close[x_, own] / close[e_, own] - 1.0) * 1e4
        E[f"a_{d}"], E[f"b_{d}"], E[f"n_b_{d}"], E[f"y_{d}"] = A[h], B[h], NB[h], Y[h]
        E[f"price_{d}"], E[f"funding_{d}"] = PRICE[h], A[h] - PRICE[h]
    ru_a, ru_b, ru_nb = listing.excess(listing.label_at(close, fv, rows - WAIT - RUNUP - bt.LATENCY, RUNUP), own, mask)   # enters at the bar closing at t0 − 24 h, exits at the bar closing at t0
    E["runup_a"], E["runup_b"], E["runup_y"] = ru_a, ru_b, ru_a - ru_b
    bars = bars_per_event(C, own, t, taker_bps)
    E = pd.concat([E, bars], axis=1)
    bar = float(E["B_i"].mean()) if len(E) else np.nan

    # validity, read first
    span = [float(np.isfinite(close[r:r + bt.LATENCY + max(HOLDS) + 1, c]).mean()) for r, c in zip(rows, own)]
    ident = {}
    for h in HOLDS:                                                # (6) the module's label is horizon's, and the harness's gross + funding of a long
        full = horizon.labels(M, C, h, bt.LATENCY)[1].to_numpy()
        f = listing._priced(M, C, _frame(E), h, 1, taker_bps)
        ident[h] = (float(np.nanmax(np.abs(full[rows, own] - A[h]))), float(np.nanmax(np.abs((f["gross_bps"] + f["funding_bps"]).to_numpy() - A[h]))), bool((np.isfinite(full[rows, own]) == np.isfinite(A[h])).all()))
        del full
    hand_idx = np.linspace(0, len(E) - 1, min(HAND_CELLS, len(E))).round().astype(int) if len(E) else np.array([], dtype=int)
    hand = []
    for i in hand_idx:
        for h in HOLDS:
            ha, hf, hn = hand_a(close, idx, S, E.loc[i, "symbol"], own[i], rows[i] + bt.LATENCY, rows[i] + bt.LATENCY + h)
            hand.append({"symbol": E.loc[i, "symbol"], "hold": _days(h), "a_hand": ha, "a": float(A[h][i]), "funding_hand": hf, "funding": float(E.loc[i, f"funding_{_days(h)}"]), "settlements": hn, "diff": abs(ha - float(A[h][i]))})
    hand = pd.DataFrame(hand)
    gaps = pd.DataFrame([settlement_gaps(S, s, t0, idx[r + bt.LATENCY + max(HOLDS)]) for s, t0, r in zip(E["symbol"], E["t0"], rows)]) if len(E) else pd.DataFrame(columns=["n_rows", "max_gap_ratio", "gap"])
    E["settlements_7d"], E["settlement_gap"] = gaps["n_rows"].to_numpy(), gaps["gap"].to_numpy()
    for h in HOLDS:
        E[f"settlements_{_days(h)}"] = [len(settlement_rows(S, s, idx[r + bt.LATENCY], idx[r + bt.LATENCY + h])) for s, r in zip(E["symbol"], rows)]
    dropped = E_all[~E_all["eligible"]]
    dropped_keys = {(str(a), str(b)) for a, b in zip(dropped["symbol"], dropped["t0"])}
    V = dict(pre)
    V.update({"2_rederived": red,
              "3_eligible": int(len(E)), "3_eligible_share": float(len(E) / len(cl)) if len(cl) else 0.0,
              "3_dropped": [{"symbol": a, "t0": b, "why": w} for a, b, w in zip(dropped["symbol"], dropped["t0"].astype(str), dropped["why"])],
              "3_dropped_as_named": None if spec.expected_dropped is None else bool(dropped_keys == set(spec.expected_dropped)),
              "3_own_cost_row_share": float((E["B_source"] != "R28's 46").mean()) if len(E) else 0.0, "3_B_source": E["B_source"].value_counts().to_dict(),
              "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_events_under_95pct_bars": int(sum(s < MIN_BARS for s in span)),
              "4_label_share": {_days(h): float(np.isfinite(Y[h]).mean()) if len(E) else 0.0 for h in HOLDS},
              "5_min_members": {_days(h): int(NB[h].min()) if len(E) else 0 for h in HOLDS}, "5_min_members_runup": int(ru_nb.min()) if len(E) else 0,
              "6_identity_max_abs_diff": {_days(h): ident[h][:2] for h in HOLDS}, "6_same_cells": all(ident[h][2] for h in HOLDS),
              "6_hand_cells": int(len(hand_idx)), "6_hand_max_abs_diff": float(hand["diff"].max()) if len(hand) else np.nan,
              "7_t_equals_t0_plus_5min": bool((t == pd.DatetimeIndex(E["t0"]) + WAIT * BAR).all()) if len(E) else False,
              "7_ts_known_equals_t0": bool((pd.DatetimeIndex(E["ts_known"]) == pd.DatetimeIndex(E["t0"])).all()) if len(E) else False,
              "8_cells_with_a_settlement_gap": int(E["settlement_gap"].sum()) if len(E) else 0, "8_gap_share": float(E["settlement_gap"].mean()) if len(E) else 0.0,
              "8_settlements_per_cell_1d": {"min": int(E["settlements_1d"].min()), "median": float(E["settlements_1d"].median()), "max": int(E["settlements_1d"].max())} if len(E) else {}})
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L) == spec.rows and V["2_cells_as_registered"] and red.get("status") == "PASS"
                             and V["3_eligible_share"] >= spec.min_share and len(E) >= spec.min_eligible and (spec.max_dropped is None or len(dropped) <= spec.max_dropped) and V["3_own_cost_row_share"] >= MIN_OWN_COST
                             and V["4_events_under_95pct_bars"] == 0 and min(V["4_label_share"].values()) >= MIN_LABELS
                             and min(V["5_min_members"].values()) >= MIN_MEMBERS and max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_same_cells"]
                             and V["6_hand_max_abs_diff"] <= 1e-9 and V["7_t_equals_t0_plus_5min"] and V["7_ts_known_equals_t0"] and V["8_gap_share"] <= MAX_GAP_SHARE) else "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
    E_all.to_csv(out / "cells_all.csv", index=False)
    hand.to_csv(out / "hand_check.csv", index=False)
    md = [f"# {spec.title} (`ft2 fundevent run --registration {spec.registration}`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {idx[0]:%Y-%m-%d} → {idx[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{spec.list.name}` md5 {list_md5} · {len(L)} rows, {len(cl)} cells ({len(pos)} positive-funding shortenings and {len(lng)} lengthenings described)\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 fundevent check`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nCells by what became of them:\n", E_all["why"].replace("", "eligible").value_counts().rename("cells").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the run-up row and the family are not computed." + (" The guard rows stand in the ledger: the folds are read for this question.**\n" if spec.guard else "**\n")]
        (out / "fundevent.md").write_text("\n".join(md))
        return "\n".join(md)

    # the run-up — read first, no gate
    ry = E["runup_y"].to_numpy()
    rv = ry[np.isfinite(ry)]
    q = [0.05, 0.10, 0.25, 0.5, 0.75, 0.90, 0.95]
    ru = [{"group": "all", "n": int(len(rv)), "median": float(np.median(rv)), "mean": float(rv.mean()), **{f"q{int(x * 100):02d}": float(np.quantile(rv, x)) for x in q}, "share_ge_500": float((rv >= 500).mean()),
           "share_ge_2000": float((rv >= 2000).mean()), "share_below_0": float((rv < 0).mean()), "median_a": float(np.nanmedian(E["runup_a"])), "median_b": float(np.nanmedian(E["runup_b"]))}]
    for key, labels in spec.splits.items():
        for v in (sorted(E[key].unique(), key=str) if labels is None else (True, False)):
            m = (E[key] == v).to_numpy()
            g = ry[m]
            g = g[np.isfinite(g)]
            if len(g):
                ru.append({"group": f"{key} = {v if labels is None else labels[0 if v else 1]}", "n": int(len(g)), "median": float(np.median(g)), "mean": float(g.mean()), "share_ge_500": float((g >= 500).mean()), "share_ge_2000": float((g >= 2000).mean()), "share_below_0": float((g < 0).mean())})
    ru = pd.DataFrame(ru)
    ru.to_csv(out / "runup.csv", index=False)
    little = bool(ru.loc[0, "median"] < 300)
    md += ["\n## The run-up — y over t0 − 24 h → t0 against the members (validity of mechanism; read first, decides nothing)\n", ru.round(1).to_markdown(index=False), "\n",
           f"\n{'The median run-up is under +300 bps: by the registration the flag is not a squeeze here — recorded beside the verdict, the gate unchanged.' if little else 'The median run-up is at or above +300 bps: a squeeze.'} The audit read +3,352 at the median on the 71 shortenings; R75 +3,805 on its 58.\n"]

    # the family
    wk, W = listing.weeks(t)
    Ymat = np.column_stack([Y[h] for h in HOLDS])
    bs = listing.bootstrap(Ymat, wk, W, block=BLOCK_WEEKS, draws=DRAWS, seed=spec.seed)
    bt_ = bootstrap_trimmed(Ymat, wk, W, TRIM_FRAC, block=BLOCK_WEEKS, draws=DRAWS, seed=spec.seed) if spec.gate == "trimmed" else None
    f3, f4 = (E["fold"] == fa).to_numpy(), (E["fold"] == fb).to_numpy()
    fam = []
    for k, h in enumerate(HOLDS):
        y = Y[h]
        v = y[np.isfinite(y)]
        r = {"hold": _days(h), "n": int(bs["n"][k]), "M": float(bs["m"][k]), "se": float(bs["se"][k]), "u": float(bs["u"][k]), "p_fw": float(bs["p_fw"]), "MDE": 2.8 * float(bs["se"][k]),
             f"M_{fa}": float(np.nanmean(y[f3])), f"M_{fb}": float(np.nanmean(y[f4])), "M_trim": listing.trimmed(y, TRIM), "se_week": float(bs["se_week"][k]), "se_plain": float(bs["se_plain"][k]), "B": bar,
             "funding_part": float(np.nanmean(A[h] - PRICE[h])), "price_part": float(np.nanmean(PRICE[h])),
             "median": float(np.median(v)) if len(v) else np.nan, "share_above_0": float((v > 0).mean()) if len(v) else np.nan, "M_without_5": float(np.sort(v)[:-5].mean()) if len(v) > 5 else np.nan}
        if bt_ is not None:
            kk = int(bt_["k"][k])
            r.update({"k_trim": kk, "M_trim": float(bt_["m"][k]), "se_trim": float(bt_["se"][k]), "u_trim": float(bt_["u"][k]), "p_fw_trim": float(bt_["p_fw"]), "MDE_trim": 2.8 * float(bt_["se"][k]),
                      f"M_trim_{fa}": listing.trimmed(y[f3], k_trim(int(np.isfinite(y[f3]).sum()))), f"M_trim_{fb}": listing.trimmed(y[f4], k_trim(int(np.isfinite(y[f4]).sum()))),
                      "trim_identity": abs(float(bt_["m"][k]) - listing.trimmed(y, kk))})
            r["verdict"] = hold_verdict(r["M_trim"], r["se_trim"], r["u_trim"], r["p_fw_trim"], r[f"M_trim_{fa}"], r[f"M_trim_{fb}"], r["M_trim"], bar)
            r["u_gate"] = r["u_trim"]
        else:
            r["verdict"] = hold_verdict(r["M"], r["se"], r["u"], r["p_fw"], r[f"M_{fa}"], r[f"M_{fb}"], r["M_trim"], bar)
            r["u_gate"] = r["u"]
        fam.append(r)
    fam = pd.DataFrame(fam)
    verdict, cand = family_verdict(fam.assign(u=fam["u_gate"]))
    if bt_ is not None and (fam["trim_identity"] > 1e-9).any():   # validity (6)'s last clause: the gate's statistic is listing.trimmed on the run's own y
        verdict, cand = "VOID", None
        V["6_trimmed_identity"] = "FAIL"
        V["status"] = "FAIL"
        (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
    fam.to_csv(out / "holds.csv", index=False)
    gate_note = (f"the GATE on the {int(round(2 * TRIM_FRAC * 100))} % TRIMMED mean (k = {fam['k_trim'].tolist()} out at each end; its own block bootstrap, se_trim / u_trim / p_fw_trim); the plain mean, the median, the share above zero and M without the five largest beside, deciding nothing"
                 if bt_ is not None else "the gate on the mean")
    md += [f"\n## The family — y = a − b, bps of the position; {len(E)} cells in {W} weeks; B {bar:.1f} (the mean of the names' own doubled round trips on the dearer day; R28's 46 beside); {bs['draws']:,} draws of {BLOCK_WEEKS}-week blocks; the sign POSITIVE; {gate_note}\n",
           fam.round(3).to_markdown(index=False), "\n", f"\n**Verdict: {verdict}{f' — the candidate hold {cand}' if cand else ''}.**\n",
           f"\nn in {fa} {int(f3.sum())}, in {fb} {int(f4.sum())}; events per week: mean {len(E) / W:.2f}, most {int(np.bincount(wk, minlength=W).max())}, weeks with none {int((np.bincount(wk, minlength=W) == 0).sum())}.\n"]
    E.to_csv(out / "events.csv", index=False)
    (out / "fundevent.md").write_text("\n".join(md))              # the read is on disk before anything is described
    (out / "meta.json").write_text(json.dumps({"registration": tagged, "decision": spec.decision, "unit": bt.UNIT, "charged": bt.CHARGED, "holds": HOLDS, "side": "long", "wait": WAIT, "runup": RUNUP, "bar": bar,
                                                "bar_mult": BAR_MULT, "bar_r28": BAR_R28, "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": spec.seed, "rows": int(len(L)), "cells": int(len(cl)), "eligible": int(len(E)),
                                                "weeks": W, "taker_bps": taker_bps, "list_md5": list_md5, "gate": spec.gate, "trim_frac": TRIM_FRAC if bt_ is not None else None, "verdict": verdict, "candidate_hold": cand}, indent=1))
    try:
        md += _describe(out, M, C, E, Y, A, B, PRICE, YL, YB, mem, t, wk, W, bar, pos, lng, end, first_block, taker_bps, spec.splits)
    except Exception as exc:  # noqa: BLE001 — a description that fails must not take the logged read with it
        import traceback
        md += ["\n## Described — FAILED (the read above stands; describe from events.csv)\n", "\n```\n" + "".join(traceback.format_exception(exc)) + "\n```\n"]
    E.to_csv(out / "events.csv", index=False)
    text = "\n".join(md)
    (out / "fundevent.md").write_text(text)
    return text


def _describe(out: Path, M, C, E, Y, A, B, PRICE, YL, YB, mem, t, wk, W, bar, pos, lng, end, first_block, taker_bps, splits: dict = SPLITS) -> list[str]:
    """R75's described tables — decide nothing."""
    close, fv = M.close.to_numpy(), C.fundval
    q = [0.05, 0.25, 0.5, 0.75, 0.95]
    desc, money, ref, net, parts = [], [], [], [], []
    C2 = bt.load_costs(M.index, M.columns, end, cost_mult=2.0, close=M.close)
    Ec = _frame(E)
    for h in HOLDS:
        y, d = Y[h], _days(h)
        v = y[np.isfinite(y)]
        desc.append({"hold": d, "median": np.median(v), "share_above_0": (v > 0).mean(), **{f"q{int(x * 100):02d}": np.quantile(v, x) for x in q}, "min": v.min(), "max": v.max(),
                     "mean_a": np.nanmean(A[h]), "mean_b": np.nanmean(B[h]), "median_a": np.nanmedian(A[h]), "M_trim": listing.trimmed(y, TRIM)})
        fp_, pp_ = A[h] - PRICE[h], PRICE[h]
        parts.append({"hold": d, "funding_part_mean": np.nanmean(fp_), "funding_part_median": np.nanmedian(fp_), "price_part_mean": np.nanmean(pp_), "price_part_median": np.nanmedian(pp_),
                      "price_plus_funding_mean": np.nanmean(fp_ + pp_), "corr_price_funding": float(pd.Series(fp_).corr(pd.Series(pp_))), "settlements_median": float(E[f"settlements_{d}"].median())})
        money.append({"hold": d, "mean_long": v.mean(), "mean_long_loss_capped_at_size": np.maximum(v, -1e4).mean(), "largest_single_loss": float(v.min()), "largest_single_gain": float(v.max()),
                      "cells_losing_over_half": int((v < -5000).sum()), "share_y_below_minus_5000": float((v < -5000).mean())})
        ref.append({"hold": d, "M_entry_a_day_later": float(np.nanmean(YL[h])), "median_entry_a_day_later": float(np.nanmedian(YL[h])), "M_against_BTC": float(np.nanmean(YB[h])),
                    "median_against_BTC": float(np.nanmedian(YB[h])), "M_a_alone": float(np.nanmean(A[h]))})
        for side, sname in ((1, "bought"), (-1, "sold")):
            for mult, CC in ((1, C), (2, C2)):
                f = listing._priced(M, CC, Ec, h, side, taker_bps)
                net.append({"hold": d, "side": sname, "cost": f"×{mult}", "n_priced": int(f["net_bps"].notna().sum()), "gross": f["gross_bps"].mean(), "fee": f["fee_bps"].mean(), "spread_impact": f["other_cost_bps"].mean(),
                            "funding": f["funding_bps"].mean(), "net": f["net_bps"].mean(), "net_median": f["net_bps"].median()})
        E[f"y_late_{d}"], E[f"y_btc_{d}"] = YL[h], YB[h]
    splits = pd.concat([_split_rows(E, Y, k, lab) for k, lab in splits.items()], ignore_index=True)
    ycols = [f"y_{_days(h)}" for h in HOLDS]
    qt = E.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")[ycols].agg(["size", "mean", "median"]).round(1)
    ext = pd.concat([E.nlargest(5, "y_7d"), E.nsmallest(5, "y_7d")])[["symbol", "t", "fold", "era", "member_at_t0", "runup_y", *ycols, *[f"funding_{_days(h)}" for h in HOLDS]]].round(0)
    hours = t.hour.value_counts().sort_index().rename("events").to_frame()
    bdist = {"B": bar, "B_i_min": float(E["B_i"].min()), "B_i_median": float(E["B_i"].median()), "B_i_max": float(E["B_i"].max()), "R28_constant": BAR_R28, **{f"source: {k}": int(v) for k, v in E["B_source"].value_counts().items()}}
    # y against the run-up's size
    ru, y1 = E["runup_y"].to_numpy(), Y[HOLDS[0]]
    ok = np.isfinite(ru) & np.isfinite(y1)
    hi, lo = ok & (ru >= 2000), ok & (ru < 2000)
    vs = {"corr_runup_y_1d": float(np.corrcoef(ru[ok], y1[ok])[0, 1]) if ok.sum() > 2 else np.nan, "corr_runup_y_7d": float(np.corrcoef(ru[ok & np.isfinite(Y[2016])], Y[2016][ok & np.isfinite(Y[2016])])[0, 1]) if ok.sum() > 2 else np.nan,
          **{f"runup_ge_2000_{_days(h)}": {"n": int(hi.sum()), "M": float(np.nanmean(Y[h][hi])) if hi.any() else np.nan, "median": float(np.nanmedian(Y[h][hi])) if hi.any() else np.nan} for h in HOLDS},
          **{f"runup_under_2000_{_days(h)}": {"n": int(lo.sum()), "M": float(np.nanmean(Y[h][lo])) if lo.any() else np.nan, "median": float(np.nanmedian(Y[h][lo])) if lo.any() else np.nan} for h in HOLDS}}
    # the described rows that are not cells: the positive-funding shortenings, and the lengthenings as the mirror (SOLD at the revert)
    def _rows(D: pd.DataFrame) -> pd.DataFrame:
        if not len(D):
            return D
        DA = entries(M, D, end, first_block)
        DE = DA[DA["eligible"]].reset_index(drop=True)
        if not len(DE):
            return DE
        od, dr = M.columns.get_indexer(DE["symbol"]), DE["row"].to_numpy()
        dm = listing.member_mask(mem, M.columns, pd.DatetimeIndex(DE["t"]))
        for h in HOLDS:
            a_, b_, _ = listing.excess(listing.label_at(close, fv, dr, h), od, dm)
            DE[f"y_{_days(h)}"] = a_ - b_
        ra, rb, _ = listing.excess(listing.label_at(close, fv, dr - WAIT - RUNUP - bt.LATENCY, RUNUP), od, dm)
        DE["runup_y"] = ra - rb
        return DE
    P, G = _rows(pos), _rows(lng)
    mirror = pd.DataFrame([{"hold": _days(h), "n": int(G[f"y_{_days(h)}"].notna().sum()), "M_sold": -float(G[f"y_{_days(h)}"].mean()), "median_sold": -float(G[f"y_{_days(h)}"].median()),
                            "share_sold_above_0": float((G[f"y_{_days(h)}"] < 0).mean()), "se_plain": float(G[f"y_{_days(h)}"].std(ddof=1) / np.sqrt(G[f"y_{_days(h)}"].notna().sum()))} for h in HOLDS]) if len(G) else pd.DataFrame()
    if len(P):
        P.to_csv(out / "positive_funding.csv", index=False)
    if len(G):
        G.to_csv(out / "lengthenings.csv", index=False)
    md = ["\n## Described — decides nothing\n",
          "\nThe funding part and the price part of a, apart (the mechanism's own check: a price part ≈ −(funding part) says the carry is a mirage):\n", pd.DataFrame(parts).round(1).to_markdown(index=False), "\n",
          "\nThe splits (" + "; ".join(splits["split"].unique()) + "):\n", splits.round(1).to_markdown(index=False), "\n",
          "\nThe distribution of y, and a and b apart:\n", pd.DataFrame(desc).round(1).to_markdown(index=False), "\n",
          "\nThe money of a LONG position (y; a loss capped at the position's size is a different rule, shown beside; a stop is not written in):\n", pd.DataFrame(money).round(3).to_markdown(index=False), "\n",
          f"\nEach position through the harness as a taker (fee {taker_bps} bps a leg, `costwide`'s proxy and its double; the name's own legs, no benchmark):\n", pd.DataFrame(net).round(1).to_markdown(index=False), "\n",
          "\nBy calendar quarter of the entry (events, mean, median):\n", qt.to_markdown(), "\n",
          "\nThe five largest and the five smallest y at 7 days:\n", ext.to_markdown(index=False), "\n",
          "\nThe hour of t (UTC):\n", hours.to_markdown(), "\n",
          "\nThe bar: B_i's distribution and its sources:\n", "\n```\n" + json.dumps(bdist, indent=1) + "\n```\n",
          "\ny against the run-up's size (the correlation; the halves at +2,000):\n", "\n```\n" + json.dumps(vs, indent=1) + "\n```\n",
          f"\nEvents per week ({W} weeks): " + ", ".join(str(int(x)) for x in np.bincount(wk, minlength=W)) + "\n",
          "\nThe five positive-funding shortenings (described, never cells):\n", (P[["symbol", "t0", "fold", "fund_1d", "runup_y", *ycols]].round(1).to_markdown(index=False) if len(P) else "none eligible"), "\n",
          "\nThe lengthenings as the mirror — a position SOLD at the revert's settlement, the same holds (−y):\n", (mirror.round(1).to_markdown(index=False) if len(mirror) else "none eligible"), "\n",
          "\n## Reference rows — no verdict\n", pd.DataFrame(ref).round(1).to_markdown(index=False), "\n"]
    return md


# ====================================================================================================================================
# Decision BW1 — the F5 Data line (nothing read): the 2026 months of the F5 names, the basket (F4's last block) and BTC; the funding rows
# ====================================================================================================================================
F5_LIST = fundfreq.LISTS["f5"]
F5_LIST_MD5 = "07d48cbfe77269004a1bbed3b22a8a50"   # as frozen (commit 30ef385)
BASKET_BLOCK = pd.Timestamp("2025-12-29", tz="UTC")  # F4's last member block: the hedge basket carried forward into 2026 (decision BW (lxii))
DATA_MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")
F5_END = pd.Timestamp("2026-09-15", tz="UTC")
DATA_OUT = OUT / "r76_data"


def basket_names(path: Path | str | None = None) -> list[str]:
    m = universe.members(path or universe.F34_MEMBERS_CSV)
    return sorted(m.loc[m["block"] == BASKET_BLOCK, "symbol"].astype(str))


def data_names() -> dict:
    """The names the Data line fetches: every name of the frozen F5 list (the shortenings' and the lengthenings'), the basket, BTC."""
    L = fundfreq.frozen(("f5",))
    f5 = sorted(set(L["symbol"].astype(str)))
    basket = basket_names()
    return {"f5": f5, "f5_shortenings": sorted(set(L.loc[L["dir"] == "shorter", "symbol"].astype(str))), "basket": basket, "all": sorted(set(f5) | set(basket) | {BTC})}


def funding_update(names: list[str], months=DATA_MONTHS, fetch: bool = True) -> dict:
    """The funding archive's parquet with the names' newer monthly rows appended: every old (symbol, ts) row kept to the digit, a row is
    new when its stamp is after the name's last old stamp (a name the parquet does not hold comes in whole). The zips of `months` are
    fetched first. Returns the counts and the old-row check; a changed old row is a void (SystemExit 2)."""
    from . import archive, data
    path = data.PROC / "funding_archive.parquet"
    old = pd.read_parquet(path)
    old["symbol"] = old["symbol"].astype(str)
    old["ts"] = pd.to_datetime(old["ts"], utc=True)
    rep = {"rows_before": int(len(old)), "names_before": int(old["symbol"].nunique()), "last_before": str(old["ts"].max()), "fetch": {}, "appended": {}}
    if fetch:
        rep["fetch"] = {sym: archive.fetch_monthly("fundingRate", sym, months=list(months)) for sym in names}
    last = old.groupby("symbol")["ts"].max()
    parts = []
    for sym in names:
        df = data._read_zips("fundingRate", sym)
        if df.empty:
            rep["appended"][sym] = 0
            continue
        new = pd.DataFrame({"symbol": sym, "ts": pd.to_datetime(df["calc_time"], unit="ms", utc=True).dt.round("s"), "rate": df["last_funding_rate"].astype(float), "interval_h": df["funding_interval_hours"].astype("int16")})
        if sym in last.index:
            new = new[new["ts"] > last[sym]]
        new = new.sort_values("ts").drop_duplicates(["symbol", "ts"], keep="last")
        rep["appended"][sym] = int(len(new))
        if len(new):
            parts.append(new)
    out = pd.concat([old, *parts], ignore_index=True).sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    assert not out.duplicated(["symbol", "ts"]).any()
    chk = old.merge(out, on=["symbol", "ts"], how="left", suffixes=("_o", "_n"))
    same = bool(len(chk) == len(old) and chk["rate_n"].notna().all() and np.allclose(chk["rate_o"], chk["rate_n"], atol=0, rtol=0) and (chk["interval_h_o"].to_numpy() == chk["interval_h_n"].to_numpy()).all())
    rep.update({"rows_after": int(len(out)), "names_after": int(out["symbol"].nunique()), "last_after": str(out["ts"].max()), "old_rows_identical": same,
                "last_per_name_after": {s: str(out.loc[out["symbol"] == s, "ts"].max()) for s in names}})
    if not same:
        print(json.dumps(rep, indent=1, default=str))
        raise SystemExit(2)
    out["symbol"] = out["symbol"].astype("category")
    out.to_parquet(path, index=False)
    return rep


def data_line(fetch: bool = True) -> dict:
    """Decision BW1's Data line: the archive slice's fingerprint, the 2026 monthly 5m klines of the names fetched and the slice re-ingested
    whole (every old name back row for row, or void), the funding rows appended, the coverage of the F5 events' windows and of the basket
    over 2026-01-01 → F5's end. Nothing after an event's t0 is joined to anything."""
    from . import archive, data
    DATA_OUT.mkdir(parents=True, exist_ok=True)
    N = data_names()
    rep = {"f5_list_md5": md5(F5_LIST), "f5_list_md5_as_frozen": md5(F5_LIST) == F5_LIST_MD5, "names": {k: len(v) for k, v in N.items()}, "basket_block": str(BASKET_BLOCK), "months": list(DATA_MONTHS)}
    fp = krlist.fingerprint()
    fp.to_csv(DATA_OUT / "fingerprint_before.csv", index=False)
    rep["names_fingerprinted"] = int(len(fp))
    if fetch:
        rep["fetch"] = {sym: archive.fetch_monthly("klines", sym, sub="5m", months=list(DATA_MONTHS)) for sym in N["all"]}
        rep["fetch_totals"] = {k: int(sum(v[k] for v in rep["fetch"].values())) for k in ("ok", "skip", "bad", "err", "missing")}
        rep["ingest"] = {k: str(v) for k, v in data.ingest_klines(krlist.ingest_symbols(N["all"])).items()}
    chk = krlist.fingerprint_check(fp, after_fn=krlist.fingerprint)
    (DATA_OUT / "fingerprint_check.json").write_text(json.dumps(chk, indent=1, default=str))
    rep["fingerprint"] = {"pass": chk["pass"], "changed": chk["changed"][:10], "names_before": chk["names_before"], "names_after": chk["names_after"]}
    if not chk["pass"]:
        (DATA_OUT / "data_line.json").write_text(json.dumps(rep, indent=1, default=str))
        print(json.dumps(rep, indent=1, default=str))
        raise SystemExit(2)
    rep["funding"] = funding_update(N["all"], DATA_MONTHS, fetch=fetch)
    # coverage: the F5 events' windows (fundfreq's rule) and every name over 2026-01-01 → F5's end
    L = fundfreq.frozen(("f5",))
    cov = fundfreq.coverage(L)
    cov.to_csv(DATA_OUT / "coverage_events.csv", index=False)
    have = data.load(fundfreq.SLICE, columns=["symbol", "open_time"], symbols=N["all"])
    have["open_time"] = pd.to_datetime(have["open_time"], utc=True)
    a, b = pd.Timestamp("2026-01-01", tz="UTC"), F5_END
    exp = int((b - a) / BAR)
    span = have[(have["open_time"] >= a) & (have["open_time"] < b)].groupby("symbol", observed=True).size()
    cov_names = pd.DataFrame({"symbol": N["all"]}).assign(bars=lambda d: d["symbol"].map(span).fillna(0).astype(int), expected=exp).assign(share=lambda d: d["bars"] / exp)
    cov_names["group"] = np.where(cov_names["symbol"].isin(N["basket"]), "basket", np.where(cov_names["symbol"] == BTC, "btc", "f5"))
    cov_names.to_csv(DATA_OUT / "coverage_names.csv", index=False)
    rep["coverage"] = {"events": int(len(cov)), "events_complete": int((cov["share"] >= 0.95).sum()), "events_short": cov[cov["share"] < 0.95][["symbol", "t0", "share"]].astype(str).to_dict("records"),
                       "names_over_2026": {g: {"n": int(len(d)), "median_share": float(d["share"].median()), "under_95pct": d.loc[d["share"] < 0.95, "symbol"].tolist()} for g, d in cov_names.groupby("group")}}
    (DATA_OUT / "data_line.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))
    return rep


# ====================================================================================================================================
# R76 — the confirmation read (PLAN §8 R76, decision BW1): R75's candidate BOUGHT on the frozen F5 list, 7 days, no stop, in money, once
# ====================================================================================================================================
LIST5 = fundfreq.LISTS["f5"]
LIST5_MD5 = F5_LIST_MD5
LIST5_ROWS, CELLS5 = 58, 26
CONF_FOLDS = ("F5",)
HOLD = 2016                                        # R75's candidate: 7 days
ENTRY_MULT = 2.0                                   # the entry day's legs: this × the name's proxy row (R29's rule)
HEAVY = (4.0, 2.0)                                 # the heavy reading: the entry day × 4, every other proxy cost × 2
SEED_CONFIRM = 76
MIN_CONFIRM, MIN_CONFIRM_SHARE, MIN_H_SHARE = 23, 0.90, 0.90
HAND5 = 10
STRATEGY5 = "fundfreq_bought_7d"


def cells5(L: pd.DataFrame, hold: int = HOLD) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(the cells, the described second events, the positive-funding shortenings, the lengthenings): an at-floor shortening is a cell
    unless the same name's previous cell is still open at its entry (t0 < the previous t0 + the hold + the entry's two bars) — one position
    per name while a position is open; the first kept."""
    short = L["dir"] == "shorter"
    floor = short & L["at_floor"].astype(bool)
    S = L[floor].sort_values(["t0", "symbol"]).reset_index(drop=True)
    open_until: dict[str, pd.Timestamp] = {}
    keep = []
    for r in S.itertuples(index=False):
        u = open_until.get(r.symbol)
        if u is not None and r.t0 < u:
            keep.append(False)
        else:
            keep.append(True)
            open_until[r.symbol] = r.t0 + (hold + 1 + bt.LATENCY) * BAR
    keep = np.array(keep, dtype=bool)
    return S[keep].reset_index(drop=True), S[~keep].reset_index(drop=True), L[short & ~floor].reset_index(drop=True), L[~short].reset_index(drop=True)


def bought_trades(M: bt.Market, C: bt.Costs, E: pd.DataFrame, mask: np.ndarray, taker_bps: float, entry_mult: float = ENTRY_MULT, other_mult: float = 1.0,
                  hold: int = HOLD, shift: int = 0) -> pd.DataFrame:
    """One BOUGHT unit per cell of E (its decision row `row`, + `shift` bars), the mirror of `listing.sold_trades`: `backtest.price` with the
    side +1, the entry day's legs `entry_mult` × the proxy, every other `other_mult` × it, no stop; the hedge one unit of the basket SOLD at
    the entry bar and bought back at the exit (−`listing.hedge`'s long gain − its round trip). H = own + hedge."""
    close, idx = M.close.to_numpy(), M.index
    own = M.columns.get_indexer(E["contract"])
    rows = E["row"].to_numpy() + shift
    e = rows + bt.LATENCY
    x = e + hold
    legs = listing.entry_day_legs(other_mult * C.taker_leg, C.days, idx[e].floor("D"), own, entry_mult / other_mult)
    Cs = dataclasses.replace(C, taker_leg=legs)
    dec = pd.DataFrame({"t": idx[rows], "symbol": E["contract"].to_numpy(), "side": 1, "hold": hold, "size": 1.0, "fold": E["fold"].to_numpy(), "accepted": True})
    f = bt.price(dec, M, Cs, "taker", taker_bps, 2.0)
    m = mask.copy()
    m[np.arange(len(own)), own] = False
    h = listing.hedge(close, C.fundval, other_mult * C.taker_leg, C.days, idx, e, x, m, taker_bps)
    out = pd.DataFrame({"contract": E["contract"].to_numpy(), "fold": E["fold"].to_numpy(), "t": idx[rows], "e": e, "x": x, "stopped": False, "entry_t": f["entry_t"].to_numpy(), "exit_t": f["exit_t"].to_numpy(),
                        "entry_px": f["entry_px"].to_numpy(), "exit_px": f["exit_px"].to_numpy(), "gross": f["gross_bps"].to_numpy(), "funding": f["funding_bps"].to_numpy(), "fee": f["fee_bps"].to_numpy(),
                        "spread_impact": f["other_cost_bps"].to_numpy(), "own": f["net_bps"].to_numpy(), "leg_entry": legs[C.days.get_indexer(idx[e].floor("D")), own], "leg_exit": legs[C.days.get_indexer(idx[x].floor("D")), own]})
    out = pd.concat([out, h], axis=1)
    out["hedge"] = -out["hedge_gain"] - out["hedge_cost"]
    out["H"] = out["own"] + out["hedge"]
    return out


def _arith5(M: bt.Market, C: bt.Costs, T: pd.DataFrame, own: np.ndarray, taker_bps: float) -> dict:
    """Validity (6): the harness's fill is the module's own arithmetic (R29's check, the side +1); gross + funding of the bought unit is
    `horizon.labels`' number at the decision row."""
    close = M.close.to_numpy()
    e, x = T["e"].to_numpy(), T["x"].to_numpy()
    pe, px_ = close[e, own], close[x, own]
    r = px_ / pe
    mine = {"gross": (r - 1.0) * 1e4, "funding": -(C.fundval[x, own] - C.fundval[e, own]) / pe, "fee": taker_bps + taker_bps * r,
            "spread_impact": T["leg_entry"].to_numpy() + T["leg_exit"].to_numpy() * r}
    mine["own"] = mine["gross"] - mine["fee"] - mine["spread_impact"] + mine["funding"]
    d = {k: float(np.nanmax(np.abs(v - T[k].to_numpy()))) if np.isfinite(T[k].to_numpy()).any() else 0.0 for k, v in mine.items()}
    full = horizon.labels(M, C, HOLD, bt.LATENCY)[1].to_numpy()[(e - bt.LATENCY), own]
    d["bought_gross_funding_vs_horizon_labels"] = float(np.nanmax(np.abs((T["gross"] + T["funding"]).to_numpy() - full)))
    d["hold_is_2016"] = bool(((x - e) == HOLD).all())
    return d


def _group5(T: pd.DataFrame, key: str, labels, col: str = "H") -> pd.DataFrame:
    out = []
    vals = T[key]
    for v in (sorted(vals.unique(), key=str) if labels is None else (True, False)):
        g = T.loc[vals == v, col].dropna()
        out.append({"split": key, "group": str(v) if labels is None else labels[0 if v else 1], "n": int(len(g)), "M": float(g.mean()) if len(g) else np.nan,
                    "median": float(g.median()) if len(g) else np.nan, "share_above_0": float((g > 0).mean()) if len(g) else np.nan, "se_plain": float(g.std(ddof=1) / np.sqrt(len(g))) if len(g) > 1 else np.nan})
    return pd.DataFrame(out)


def basket_members(path: Path | str | None = None) -> pd.DataFrame:
    m = universe.members(path or universe.F34_MEMBERS_CSV)
    return m[m["block"] == BASKET_BLOCK].reset_index(drop=True)


def confirm(registration: str | None, name: str = "r76", taker_bps: float = TAKER_BPS, reexecute: str | None = None) -> str:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fp_before, _ = fp_paths(name)
    L = load_events(LIST5)
    list_md5 = md5(LIST5)
    cl, twins, pos, lng = cells5(L)
    pre = {"1_fingerprint_before": "saved" if fp_before.exists() else "MISSING", "1_fingerprint_after": f"pending → `ft2 fundevent check --name {name}` after the run",
           "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == LIST5_MD5, "2_list_rows": int(len(L)), "2_at_floor_shortenings": int(len(cl) + len(twins)), "2_cells": int(len(cl)), "2_cells_as_registered": len(cl) == CELLS5,
           "2_second_events_described": twins[["symbol", "t0"]].astype(str).to_dict("records"), "2_positive_funding_described": pos[["symbol", "t0"]].astype(str).to_dict("records"), "2_lengthenings_described": int(len(lng))}
    params = {"hold": HOLD, "stop": None, "wait": WAIT, "side": "long", "entry_mult": ENTRY_MULT, "heavy": list(HEAVY), "basket_block": str(BASKET_BLOCK.date()), "list": LIST5.name, "list_md5": list_md5, "cells": int(len(cl)), "seed": SEED_CONFIRM}
    conf = bt._guard(CONF_FOLDS, registration, reexecute)          # registered, and once (refuses before anything is loaded)
    tagged = bt.read_tag(registration, reexecute)
    stamp = guard_rows(bt.READS, conf, tagged, STRATEGY5, params)  # the row (R76[/tag], F5) NOW — before the funding archive is re-read and before the market
    pre["guard"] = {"status": "PASS", "appended_at": stamp, "ledger": str(bt.READS), "folds": list(conf), "logged_as": tagged}
    print(f"guard: ({tagged}, {', '.join(conf)}) appended to {bt.READS} at {stamp}; the funding archive and the F5 market are loaded now", flush=True)

    red = rederived(L)
    S = fundfreq.settlements()
    a0, end = listing.window(CONF_FOLDS)
    mem = basket_members()
    syms = list(dict.fromkeys([*cl["symbol"], *twins["symbol"], *pos["symbol"], *lng["symbol"], *mem["symbol"].astype(str), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, idx, fv = M.close.to_numpy(), M.index, C.fundval
    E_all = entries(M, cl, end, a0, longest=HOLD)
    E_all["why"] = E_all["why"].replace({"before the first member block": "before F5's first day", "the 7-day exit is not before the end": "the 7-day exit is not before F5's end"})
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    own = M.columns.get_indexer(E["symbol"])
    rows, t = E["row"].to_numpy(), pd.DatetimeIndex(E["t"])
    mask = listing.member_mask(mem, M.columns, t)
    T = bought_trades(M, C, _frame(E), mask, taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD)
    TH = bought_trades(M, C, _frame(E), mask, taker_bps, entry_mult=HEAVY[0], other_mult=HEAVY[1], hold=HOLD)
    for k in ("t0", "ts_known", "era", "member_at_t0", "new_h", "prev_h", "fund_1d"):
        T[k], TH[k] = E[k].to_numpy(), E[k].to_numpy()

    # validity, read first
    span = [float(np.isfinite(close[r:r + bt.LATENCY + HOLD + 1, c]).mean()) for r, c in zip(rows, own)]
    d6 = _arith5(M, C, T, own, taker_bps)
    hand_idx = np.linspace(0, len(E) - 1, min(HAND5, len(E))).round().astype(int) if len(E) else np.array([], dtype=int)
    hand = pd.DataFrame([{"symbol": E.loc[i, "symbol"], "funding_hand": hand_a(close, idx, S, E.loc[i, "symbol"], own[i], rows[i] + bt.LATENCY, rows[i] + bt.LATENCY + HOLD)[1], "funding": float(T.loc[i, "funding"]),
                          "settlements": hand_a(close, idx, S, E.loc[i, "symbol"], own[i], rows[i] + bt.LATENCY, rows[i] + bt.LATENCY + HOLD)[2]} for i in hand_idx])
    if len(hand):
        hand["diff"] = (hand["funding_hand"] - hand["funding"]).abs()
    gaps = pd.DataFrame([settlement_gaps(S, s, t0, idx[r + bt.LATENCY + HOLD]) for s, t0, r in zip(E["symbol"], E["t0"], rows)]) if len(E) else pd.DataFrame(columns=["n_rows", "max_gap_ratio", "gap"])
    T["settlements_7d"], T["settlement_gap"] = gaps["n_rows"].to_numpy(), gaps["gap"].to_numpy()
    cday = C.days.get_indexer(idx[rows + bt.LATENCY].floor("D"))
    own_row = np.array([bool(p >= 0 and np.isfinite(C.taker_leg[p, c])) for p, c in zip(cday, own)])
    unpriced = T.loc[T["H"].isna(), "contract"].tolist()
    V = dict(pre)
    V.update({"2_rederived": red,
              "3_eligible": int(len(E)), "3_eligible_share": float(len(E) / len(cl)) if len(cl) else 0.0, "3_H_share": float(T["H"].notna().mean()) if len(T) else 0.0, "3_unpriced": unpriced,
              "3_own_cost_row_share": float(own_row.mean()) if len(E) else 0.0,
              "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_cells_under_95pct_bars": int(sum(v < MIN_BARS for v in span)),
              "5_min_basket": int(T["n_b"].min()) if len(T) else 0,
              "6_identity_max_abs_diff": d6, "6_hand_cells": int(len(hand_idx)), "6_hand_max_abs_diff": float(hand["diff"].max()) if len(hand) else np.nan,
              "7_t_equals_t0_plus_5min": bool((t == pd.DatetimeIndex(E["t0"]) + WAIT * BAR).all()) if len(E) else False, "7_ts_known_equals_t0": bool((pd.DatetimeIndex(E["ts_known"]) == pd.DatetimeIndex(E["t0"])).all()) if len(E) else False,
              "7_no_stop": bool(not T["stopped"].any()) if len(T) else True, "7_exits_at_or_after_end": int((pd.DatetimeIndex(T["exit_t"]) >= end).sum()) if len(T) else 0,
              "8_cells_with_a_settlement_gap": int(T["settlement_gap"].sum()) if len(T) else 0, "8_gap_share": float(T["settlement_gap"].mean()) if len(T) else 0.0,
              "8_settlements_per_cell_7d": {"min": int(T["settlements_7d"].min()), "median": float(T["settlements_7d"].median()), "max": int(T["settlements_7d"].max())} if len(T) else {}})
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L) == LIST5_ROWS and V["2_cells_as_registered"] and red.get("status") == "PASS"
                             and V["3_eligible_share"] >= MIN_CONFIRM_SHARE and len(E) >= MIN_CONFIRM and V["3_H_share"] >= MIN_H_SHARE and V["3_own_cost_row_share"] >= MIN_OWN_COST
                             and V["4_cells_under_95pct_bars"] == 0 and V["5_min_basket"] >= MIN_MEMBERS
                             and max(v for v in d6.values() if not isinstance(v, bool)) <= 1e-9 and d6["hold_is_2016"] and V["6_hand_max_abs_diff"] <= 1e-9
                             and V["7_t_equals_t0_plus_5min"] and V["7_ts_known_equals_t0"] and V["7_no_stop"] and V["7_exits_at_or_after_end"] == 0
                             and V["8_gap_share"] <= MAX_GAP_SHARE) else "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
    E_all.to_csv(out / "cells_all.csv", index=False)
    hand.to_csv(out / "hand_check.csv", index=False)
    md = [f"# R76 — the confirmation read of R75's candidate on F5: the squeeze flag bought, 7 days, in money (`ft2 fundevent confirm`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {idx[0]:%Y-%m-%d} → {idx[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{LIST5.name}` md5 {list_md5} · {len(L)} rows, {len(cl)} cells ({len(twins)} second events, {len(pos)} positive-funding, {len(lng)} lengthenings described) · the basket {BASKET_BLOCK.date()} ({len(mem)} names)\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 fundevent check --name {name}`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nCells by what became of them:\n", E_all["why"].replace("", "eligible").value_counts().rename("cells").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the number is not computed. The guard row stands in the ledger: F5 is read for this question.**\n"]
        (out / "confirm.md").write_text("\n".join(md))
        return "\n".join(md)

    # the number
    ok = T["H"].notna().to_numpy()
    N = listing.noise(T["H"].to_numpy()[ok], t[ok], seed=SEED_CONFIRM)
    m_heavy = float(TH["H"].mean())
    N.update({"M_heavy": m_heavy, "MDE": 2.8 * N["se"], "verdict": listing.verdict_confirm(N["M"], N["se"], m_heavy)})
    (out / "confirm.json").write_text(json.dumps(N, indent=1))
    T.to_csv(out / "trades.csv", index=False)
    TH.to_csv(out / "trades_heavy.csv", index=False)
    md += [f"\n## The number — H = own + hedge, bps of the bought unit; {N['n']} positions in {N['weeks']} weeks; the gate's se the larger of the bootstrap's and the week-clustered\n",
           pd.DataFrame([{k: N[k] for k in ("n", "M", "se", "u", "MDE", "M_heavy", "se_bootstrap", "se_week", "se_plain", "verdict")}]).round(3).to_markdown(index=False), "\n",
           f"\n**Verdict: {N['verdict']}.**\n"]
    (out / "confirm.md").write_text("\n".join(md))                # the read is on disk before anything is described
    (out / "meta.json").write_text(json.dumps({"registration": tagged, "decision": "BW1", "unit": bt.UNIT, "charged": bt.CHARGED, "hold": HOLD, "stop": None, "wait": WAIT, "side": "long", "entry_mult": ENTRY_MULT,
                                                "heavy": HEAVY, "basket_block": str(BASKET_BLOCK.date()), "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": SEED_CONFIRM, "rows": int(len(L)), "cells": int(len(cl)), "eligible": int(len(E)),
                                                "taker_bps": taker_bps, "list_md5": list_md5, "verdict": N["verdict"]}, indent=1))
    try:
        md += _describe5(out, M, C, E, T, TH, mem, mask, own, ok, t, taker_bps, twins, pos, lng, end, a0)
    except Exception as exc:  # noqa: BLE001 — a description that fails must not take the logged read with it
        import traceback
        md += ["\n## Described — FAILED (the read above stands; describe from trades.csv)\n", "\n```\n" + "".join(traceback.format_exception(exc)) + "\n```\n"]
    T.to_csv(out / "trades.csv", index=False)
    text = "\n".join(md)
    (out / "confirm.md").write_text(text)
    return text


def _describe5(out, M, C, E, T, TH, mem, mask, own, ok, t, taker_bps, twins, pos, lng, end, a0) -> list[str]:
    """R76's described tables — decide nothing."""
    close, idx, fv = M.close.to_numpy(), M.index, C.fundval
    rows = E["row"].to_numpy()
    parts = ["gross", "funding", "fee", "spread_impact", "own", "hedge_gain", "hedge_cost", "hedge", "H"]
    by = pd.concat([T[parts].mean().rename("mean"), T[parts].median().rename("median"), TH[parts].mean().rename("heavy mean")], axis=1).T
    by.insert(0, "n", [len(T), len(T), len(TH)])
    No = listing.noise(T["own"].to_numpy()[ok], t[ok], seed=SEED_CONFIRM)
    H = T["H"].dropna()
    tail = {"largest_loss_H": float(H.min()), "largest_gain_H": float(H.max()), "positions_losing_over_half": int((T["own"] < -5000).sum()), "M_losses_capped_at_size": float(np.maximum(T["H"].to_numpy(), -1e4)[ok].mean()),
            "share_above_0": float((H > 0).mean()), "median_H": float(H.median()), **{f"q{int(x * 100):02d}": float(H.quantile(x)) for x in (0.05, 0.25, 0.75, 0.95)}, "M_trim3": listing.trimmed(H.to_numpy(), 3),
            "M_without_largest_3": float(np.sort(H.to_numpy())[:-3].mean()) if len(H) > 3 else np.nan, "price_part_mean": float(T["gross"].mean()), "funding_part_mean": float(T["funding"].mean()),
            "price_part_median": float(T["gross"].median()), "funding_part_median": float(T["funding"].median())}
    splits = pd.concat([_group5(T, "era", None), _group5(T, "new_h", None)], ignore_index=True)
    # R75's frame on these cells (no cost): the run-up and y at the three holds against the basket's mean
    ru_a, ru_b, _ = listing.excess(listing.label_at(close, fv, rows - WAIT - RUNUP - bt.LATENCY, RUNUP), own, mask)
    ru = ru_a - ru_b
    T["runup_y"] = ru
    ys = {}
    for h in HOLDS:
        a_, b_, _ = listing.excess(listing.label_at(close, fv, rows, h), own, mask)
        ys[h] = a_ - b_
        T[f"y_{_days(h)}"] = ys[h]
    runup = {"n": int(np.isfinite(ru).sum()), "median": float(np.nanmedian(ru)), "mean": float(np.nanmean(ru)), "share_ge_500": float(np.nanmean(ru >= 500)), "share_ge_2000": float(np.nanmean(ru >= 2000)), "share_below_0": float(np.nanmean(ru < 0))}
    hi, lo = ok & (ru >= 2000), ok & ~(ru >= 2000)
    runup["H_runup_ge_2000"] = {"n": int(hi.sum()), "M": float(T.loc[hi, "H"].mean()) if hi.any() else np.nan}
    runup["H_runup_under_2000"] = {"n": int(lo.sum()), "M": float(T.loc[lo, "H"].mean()) if lo.any() else np.nan}
    yrows = pd.DataFrame([{"hold": _days(h), "n": int(np.isfinite(ys[h]).sum()), "M_y": float(np.nanmean(ys[h])), "median_y": float(np.nanmedian(ys[h])), "share_above_0": float(np.nanmean(ys[h] > 0)),
                           "se_plain": float(np.nanstd(ys[h], ddof=1) / np.sqrt(np.isfinite(ys[h]).sum()))} for h in HOLDS])
    # the described rows that are not cells: the second events, the positive-funding shortenings, the lengthenings as the sold mirror
    def _priced_rows(D: pd.DataFrame, side: int) -> pd.DataFrame:
        if not len(D):
            return D
        DA = entries(M, D, end, a0, longest=HOLD)
        DE = DA[DA["eligible"]].reset_index(drop=True)
        if not len(DE):
            return DE
        dm = listing.member_mask(mem, M.columns, pd.DatetimeIndex(DE["t"]))
        if side > 0:
            return bought_trades(M, C, _frame(DE), dm, taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD)
        return listing.sold_trades(M, C, _frame(DE), dm, taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD, level=np.inf)
    TW, TP, TG = _priced_rows(twins, 1), _priced_rows(pos, 1), _priced_rows(lng, -1)
    for nm, D in (("second_events", TW), ("positive_funding", TP), ("lengthenings_sold", TG)):
        if len(D):
            D.to_csv(out / f"{nm}.csv", index=False)
    mirror = {"n": int(TG["H"].notna().sum()), "M_H_sold": float(TG["H"].mean()), "median_H_sold": float(TG["H"].median()), "share_above_0": float((TG["H"] > 0).mean()), "se_plain": float(TG["H"].std(ddof=1) / np.sqrt(TG["H"].notna().sum()))} if len(TG) else {}
    late = E[rows + LATE + bt.LATENCY + HOLD < len(idx)].reset_index(drop=True)
    TL = bought_trades(M, C, _frame(late), listing.member_mask(mem, M.columns, pd.DatetimeIndex(late["t"]) + LATE * BAR), taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD, shift=LATE) if len(late) else pd.DataFrame({"H": []})
    mo = T.assign(m=t.tz_localize(None).to_period("M").astype(str)).groupby("m")["H"].agg(["size", "mean", "median"])
    md = ["\n## Described — decides nothing\n", "\nH's parts (the mean, the median; `heavy` = the entry day at four times the proxy, every other proxy cost doubled):\n", by.round(1).to_markdown(), "\n",
          f"\n- the bought unit alone (own): mean {No['M']:.1f}, se {No['se']:.1f} (bootstrap {No['se_bootstrap']:.1f}, week {No['se_week']:.1f}, plain {No['se_plain']:.1f}), u {No['u']:.2f}\n",
          "- H's distribution, the tail, the parts:\n", "\n```\n" + json.dumps(tail, indent=1) + "\n```\n",
          "\nThe splits (the era; the new interval):\n", splits.round(1).to_markdown(index=False), "\n",
          "\nThe run-up (y over t0 − 24 h → t0 against the basket, no cost — R75's frame) and H on its halves at +2,000 (a description, never a gate):\n", "\n```\n" + json.dumps(runup, indent=1, default=str) + "\n```\n",
          "\nR75's own number on these cells (y = a − the basket's mean, no cost; R75 on F3+F4: 1d +1,080, 3d +945, 7d +2,200) — the three holds unpriced:\n", yrows.round(1).to_markdown(index=False), "\n",
          "\nBy calendar month of the entry (positions, mean H, median H):\n", mo.round(1).to_markdown(), "\n",
          "\nThe second events of a name with a position open (described, never cells; their H by the same rule):\n", (TW[["contract", "t", "gross", "funding", "own", "hedge", "H"]].round(1).to_markdown(index=False) if len(TW) else "none"), "\n",
          "\nThe positive-funding shortenings (described):\n", (TP[["contract", "t", "gross", "funding", "own", "hedge", "H"]].round(1).to_markdown(index=False) if len(TP) else "none"), "\n",
          "\nThe lengthenings as the mirror — a unit SOLD at the revert, the same pricing, hedged:\n", "\n```\n" + json.dumps(mirror, indent=1) + "\n```\n",
          f"\n- the entry a day later, the same costs (reference): mean H {TL['H'].mean():.1f}, median {TL['H'].median():.1f} ({len(TL)} positions)\n",
          "\nThe hour of t (UTC):\n", t.hour.value_counts().sort_index().rename("positions").to_frame().to_markdown(), "\n",
          "\nThe settlements inside the hold per cell: " + json.dumps({"min": int(T["settlements_7d"].min()), "median": float(T["settlements_7d"].median()), "max": int(T["settlements_7d"].max())}) + "\n",
          "\nThe five best and the five worst positions:\n", pd.concat([T.nlargest(5, "H"), T.nsmallest(5, "H")])[["contract", "entry_t", "era", "runup_y", "gross", "funding", "own", "hedge", "H"]].round(0).to_markdown(index=False), "\n"]
    return md


def main(action: str, name: str | None = None, registration: str | None = None, reexecute: str | None = None) -> None:
    if action == "fingerprint":
        print(fingerprint(name))
    elif action == "run":
        text = run(registration, name, reexecute=reexecute)
        print(text)
        if "**VOID" in text:
            sys.exit(2)
    elif action == "check":
        r = check(name)
        if not r["pass"]:
            sys.exit(2)
    elif action == "data":
        data_line(fetch=True)
    elif action == "confirm":
        text = confirm(registration, name or "r76", reexecute=reexecute)
        print(text)
        if "**VOID" in text:
            sys.exit(2)
