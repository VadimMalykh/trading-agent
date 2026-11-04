"""P8, R80 — the scheduled network upgrade of a name, SOLD at the first 5m bar closing after the exchange's stated hour: does the name
give back against the screener's members over the next 1, 3 and 7 days? `ft2 upgevent fingerprint|run|check` (PLAN §8 R80 is the
registration; this file is its code and changes nothing of it; decision CD1 — every row of the frozen F1+F2 list is the gate's cell but
ETHUSDT's (one of the twelve, described) and KLAYUSDT 2024-08-29's (its 7-day exit past F2's end, dropped by the calendar)).

events     the FROZEN `ft2/upgrades_f12.csv` (decision CD1's audit, DATA.md `upgrade_events`; md5 as registered): symbol, t0 = the upgrade's
           stated time, ts_known = the notice's release, hardfork, multi, repeat_n, member_at_t0, t_suspend. Nothing is added, dropped or
           re-dated here; a row the entry rule cannot hold is counted by reason.
entry      the decision bar is the FIRST 5m bar that closes strictly after t0 (the bar closing at floor(t0, 5 min) + 5 min); the position is
           entered one bar later (the harness's latency) — 5 … 10 minutes after the stated hour.
label      R70's: a = what a long earns before trading costs with the funding it pays (`listing.label_at` = `horizon.labels`' number);
           b = the mean over the members of the block that holds t, the name itself left out (`listing.excess`); y = a − b. A sold
           position earns −y.
statistic  THE GATE ON THE 10 % TRIMMED MEAN (R77's, `fundevent.bootstrap_trimmed`: k = round(0.05 n) out at each end, the draw's statistic
           the trimmed mean, seed 80); the plain mean and its bootstrap beside, deciding nothing. The sign NEGATIVE: M_trim ≤ −B.
bar        R70's B: the mean over the cells of B_i = 2 × the name's own taker round trip on its entry day (`krevent.bars_per_event`; the
           7-day fallback, else R28's 46).
rows read  first, no gate: the RUN-UP (y over t0 − 24 h → the decision bar) and the INTO row (BOUGHT at the first bar closing after the
first      notice's release + latency, closed at the decision bar — the "rumour" leg with a known exit).
validity   (1) the archive slice's fingerprint before (`fingerprint`) and after (`check`); (2) the list's md5, 93 rows, every row re-derived by
           `upgrades.events()` from the catalog and the bodies on disk; (3) exactly the two named rows out, 91 cells, ≥ 75 % with their own
           cost row; (4) bars and labels ≥ 95 %; (5) members ≥ 40; (6) the label identity with `horizon.labels` and the harness, the trimmed
           identity with `listing.trimmed`; (7) every cell's decision bar closes after t0 AND after ts_known; the INTO entry after the release.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import fundevent, horizon, krevent, krlist, krw, listing, universe, upgrades
from .ceiling import BAR

NAME = "r80"
OUT = listing.OUT                                  # output/listing
LIST = upgrades.LISTS["f12"]
LIST_MD5 = "511494694fdf206c30738eff20e4a2d9"      # as registered (PLAN §8 R80)
LIST_ROWS = 93
FOLDS = ("F1", "F2")
HOLDS = (288, 864, 2016)                           # 1, 3, 7 days — the family
RUNUP = 288                                        # the run-up row: t0 − 24 h → the decision bar
LATE = 288                                         # reference row: the entry a day later
TAKER_BPS = 5.0
BLOCK_WEEKS, DRAWS, SEED = 6, 10_000, 80
TRIM_FRAC = fundevent.TRIM_FRAC                    # the 10 % trimmed mean: 5 % out at each end
MIN_MEMBERS, MIN_ELIGIBLE, MIN_OWN_COST, MIN_BARS, MIN_LABELS = 40, 90, 0.75, 0.95, 0.95
DESCRIBED = tuple(krw.TWELVE)                      # the twelve's rows are described, never cells
EXPECTED_DESCRIBED = {("ETHUSDT", "2024-03-13 13:55:00+00:00")}
EXPECTED_DROPPED = {("KLAYUSDT", "2024-08-29 01:30:00+00:00")}
BTC = "BTCUSDT"
SPLITS = {"hardfork": ("hard fork", "upgrade only"), "first": ("first notice", "repeat"), "member_at_t0": ("member at t0", "not a member"), "multi": ("two-chain notice", "single")}
INTO_LITTLE = 100.0                                # the INTO row's median under this: little to give back (recorded beside the verdict)

# R81 — the confirmation read on the frozen F3+F4 list (decision CE1, PLAN §8 R81): R80's path with the list, the members, the folds and the
# verdict swapped — ONE gate hold (1 day, R80's candidate), 3d / 7d described rows; the twelve's rows described (ETH 2025-05-07 Pectra,
# ETH 2025-11-26 Fusaka, ADA 2025-01-29 Plomin; ADA 2024-09-01 Chang lies before the members' first block — dropped by the calendar, counted);
# the guard rows (R81, F3) / (R81, F4) appended to the ledger BEFORE the
# F3+F4 market is loaded (R71's form, `krevent.guard_rows`); the money row — the sold unit through the harness at the entry day's doubled
# proxy, hedged with the block's members (`listing.sold_trades`, H = own + hedge), the heavy reading ×4 / ×2 beside — described, deciding nothing.
NAME81 = "r81"
LIST34 = upgrades.LISTS["f34"]
LIST34_MD5 = "da570f4c030b8887c5e8bdc2b89a81cf"    # as frozen 2026-11-04 (DATA.md `upgrade_events`) and registered (PLAN §8 R81)
LIST34_ROWS = 105
FOLDS34 = ("F3", "F4")
SEED81 = 81
GATE_HOLDS81 = (288,)                              # the clearing hold of R80; 3d and 7d described
EXPECTED_DESCRIBED34 = {("ADAUSDT", "2025-01-29 21:45:00+00:00"), ("ETHUSDT", "2025-05-07 10:05:00+00:00"), ("ETHUSDT", "2025-11-26 06:00:00+00:00")}
EXPECTED_DROPPED34 = {("ADAUSDT", "2024-09-01 21:45:00+00:00")}   # ADA's Chang row: t0 two days BEFORE the F3+F4 members' first block (2024-09-03) — dropped by the calendar, counted (the twelve's fourth row); every 7-day exit of the 105 lies before 2026-01-01
MIN_ELIGIBLE81 = 96                                # ≥ 95 % of the 101 cells (written after the Data line's audit: 105 of 105 windows complete, 4 rows the twelve's)
ENTRY_MULT81, HEAVY81 = 2.0, (4.0, 2.0)            # the money row: the entry day's legs at twice the proxy; the heavy reading ×4 / ×2 (R71's)
STRATEGY81 = "upgrade_sold_1d"


@dataclasses.dataclass
class Spec:
    """What differs between R80's read and R81's; everything else of `run` is shared and unchanged (R77's `Spec` pattern)."""
    registration: str
    decision: str
    title: str
    list_path: Path
    list_md5: str
    list_rows: int
    folds: tuple[str, str]
    members_csv: Path | None
    seed: int
    expected_described: set
    expected_dropped: set
    min_eligible: int
    gate_holds: tuple[int, ...]
    confirm: bool                                  # the guard rows, the single-hold CONFIRMED / NOT CONFIRMED verdict, the money row
    other_list: Path | None


def spec_r80() -> Spec:
    """Read at call time, so a test's monkeypatch of the module's constants applies (R77's `spec_for`)."""
    return Spec("R80", "CD1", "R80 — the scheduled network upgrade of a name, sold at the first bar after the stated hour (`ft2 upgevent run`)",
                LIST, LIST_MD5, LIST_ROWS, FOLDS, None, SEED, EXPECTED_DESCRIBED, EXPECTED_DROPPED, MIN_ELIGIBLE, HOLDS, False, upgrades.LISTS["f34"])


def spec_r81() -> Spec:
    return Spec("R81", "CE1", "R81 — the confirmation read of the scheduled network upgrade sold at the first bar after the stated hour, 1 day, on F3+F4 (`ft2 upgevent run --name r81`)",
                LIST34, LIST34_MD5, LIST34_ROWS, FOLDS34, universe.F34_MEMBERS_CSV, SEED81, EXPECTED_DESCRIBED34, EXPECTED_DROPPED34, MIN_ELIGIBLE81, GATE_HOLDS81, True, upgrades.LISTS["f12"])


SPECS = {NAME: spec_r80, NAME81: spec_r81}


def confirm_verdict(m_trim: float, se_trim: float, u_trim: float, m_fa: float, m_fb: float, bar: float) -> str:
    """R81's gate on the one hold: CONFIRMED if M_trim ≤ −B, |u_trim| ≥ 2 and both folds' trimmed means < 0; the opposite sign recorded as
    such; NOT CONFIRMED otherwise (with "under the bar" when the interval lies inside ±B — a fact beside, the verdict stays NOT CONFIRMED)."""
    if m_trim <= -bar and abs(u_trim) >= 2 and m_fa < 0 and m_fb < 0:
        return "CONFIRMED"
    if m_trim >= bar and abs(u_trim) >= 2 and m_fa > 0 and m_fb > 0:
        return "NOT CONFIRMED — the opposite sign"
    if abs(m_trim) + 1.96 * se_trim < bar:
        return "NOT CONFIRMED — under the bar"
    return "NOT CONFIRMED"


def _days(h: int) -> str:
    return f"{h // 288}d"


# ---- the frozen events ----------------------------------------------------------------------------------------------------------
def load_events(path: Path | str = LIST) -> pd.DataFrame:
    L = pd.read_csv(path)
    for c in ("t0", "ts_known", "release", "block", "perp_first", "t_suspend", "title_date"):
        L[c] = pd.to_datetime(L[c], utc=True, format="ISO8601")
    L["first"] = L["repeat_n"] == 0
    return L


def rederived(L: pd.DataFrame) -> dict:
    """Validity (2): every frozen row's t0 and symbol are what `upgrades.events`' rule gives from the catalog and the bodies on disk today."""
    try:
        E = upgrades.events(write=False)
    except Exception as e:                                         # noqa: BLE001 — recorded, and the validity fails
        return {"status": "MISSING", "why": str(e)[:200]}
    E = E.set_index(["code", "symbol"])
    bad = []
    for r in L.itertuples(index=False):
        k = (r.code, r.symbol)
        if k not in E.index:
            bad.append({"code": r.code, "symbol": r.symbol, "why": "not a candidate today"})
        elif pd.Timestamp(E.loc[k, "t0"]) != r.t0:
            bad.append({"code": r.code, "symbol": r.symbol, "why": "t0 differs", "frozen": str(r.t0), "today": str(E.loc[k, "t0"])})
        elif E.loc[k, "why"] != "eligible":
            bad.append({"code": r.code, "symbol": r.symbol, "why": f"not eligible today: {E.loc[k, 'why']}"})
    return {"status": "PASS" if not bad else "FAIL", "rows": int(len(L)), "bad": bad}


# ---- entries --------------------------------------------------------------------------------------------------------------------
def decision_close(t0: pd.Timestamp) -> pd.Timestamp:
    """The first 5m bar that CLOSES strictly after t0: the bar closing at floor(t0, 5 min) + 5 min."""
    return t0.floor("5min") + BAR


def first_close_after(ts: pd.Timestamp) -> pd.Timestamp:
    return decision_close(ts)


def entries(M: bt.Market, L: pd.DataFrame, end: pd.Timestamp, first_block: pd.Timestamp, latency: int = bt.LATENCY, longest: int = max(HOLDS), described: tuple[str, ...] = DESCRIBED) -> pd.DataFrame:
    """Per frozen row: the decision row (the first bar closing after t0) and why it is or is not a cell; the twelve's rows described."""
    idx, n = M.index, len(M.index)
    cl = M.close.to_numpy()
    col = M.columns.get_indexer(L["symbol"])
    rows = []
    for c, sym, t0, rel in zip(col, L["symbol"], L["t0"], L["ts_known"]):
        t = decision_close(t0)
        row = int(idx.get_indexer([t])[0])
        t_in = first_close_after(rel)
        row_in = int(idx.get_indexer([t_in])[0])
        if c < 0:
            why, row = "no bars of the name in the market", -1
        elif row < 0:
            why = "the decision bar is not in the market"
        elif idx[row] < first_block:
            why = "before the folds' first member block"
        elif row + latency >= n or not (np.isfinite(cl[row, c]) and np.isfinite(cl[row + latency, c])):
            why = "no close at the decision or entry bar"
        else:
            x = row + latency + longest
            why = "the 7-day exit is not before the end" if x >= n or not idx[x] < end else ""
        if why == "" and sym in described:
            why = "described: one of the twelve"
        rows.append({"t": t, "row": row, "t_into": t_in, "row_into": row_in, "why": why})
    out = pd.concat([L.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    out["eligible"] = out["why"] == ""
    out["described"] = out["why"] == "described: one of the twelve"
    return out


def label_pair(close: np.ndarray, fundval: np.ndarray, e: np.ndarray, x: np.ndarray) -> np.ndarray:
    """`listing.label_at`'s number between given entry and exit rows per event (every column): exit ÷ entry − 1 minus the funding a long
    pays, bps of the size at entry; NaN where a row is outside the market or x ≤ e."""
    n = len(close)
    ok = (e >= 0) & (x > e) & (x < n)
    e_, x_ = np.where(ok, e, 0), np.where(ok, x, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        pe = close[e_]
        y = (close[x_] / pe - 1.0) * 1e4 - (fundval[x_] - fundval[e_]) / pe
    y[~ok] = np.nan
    return y


# ---- the gate: the trimmed statistic ------------------------------------------------------------------------------------------
def trimmed_family(Y: dict, t: pd.DatetimeIndex, f1: np.ndarray, f2: np.ndarray, bar: float, seed: int = SEED, folds: tuple[str, str] = FOLDS) -> tuple[pd.DataFrame, dict, dict]:
    """Per hold the trimmed statistic with its own block bootstrap (the gate) and the plain mean with R28's (beside); the fold columns named
    after `folds` (F1 / F2 for R80, F3 / F4 for R81)."""
    fa, fb = folds
    wk, W = listing.weeks(t)
    Ymat = np.column_stack([Y[h] for h in HOLDS])
    bs = listing.bootstrap(Ymat, wk, W, block=BLOCK_WEEKS, draws=DRAWS, seed=seed)
    bt_ = fundevent.bootstrap_trimmed(Ymat, wk, W, TRIM_FRAC, block=BLOCK_WEEKS, draws=DRAWS, seed=seed)
    fam = []
    for k, h in enumerate(HOLDS):
        y = Y[h]
        v = y[np.isfinite(y)]
        kk = int(bt_["k"][k])
        r = {"hold": _days(h), "n": int(bs["n"][k]), "k_trim": kk, "M_trim": float(bt_["m"][k]), "se_trim": float(bt_["se"][k]), "u_trim": float(bt_["u"][k]), "p_fw_trim": float(bt_["p_fw"]),
             "MDE_trim": 2.8 * float(bt_["se"][k]), f"M_trim_{fa}": listing.trimmed(y[f1], fundevent.k_trim(int(np.isfinite(y[f1]).sum()))), f"M_trim_{fb}": listing.trimmed(y[f2], fundevent.k_trim(int(np.isfinite(y[f2]).sum()))),
             "B": bar, "M": float(bs["m"][k]), "se": float(bs["se"][k]), "u": float(bs["u"][k]), "p_fw": float(bs["p_fw"]), "MDE": 2.8 * float(bs["se"][k]), "se_week": float(bs["se_week"][k]),
             "se_plain": float(bs["se_plain"][k]), f"M_{fa}": float(np.nanmean(y[f1])), f"M_{fb}": float(np.nanmean(y[f2])), "median": float(np.median(v)) if len(v) else np.nan,
             "share_below_0": float((v < 0).mean()) if len(v) else np.nan, "M_without_5_largest": float(np.sort(v)[:-5].mean()) if len(v) > 5 else np.nan,
             "M_without_5_smallest": float(np.sort(v)[5:].mean()) if len(v) > 5 else np.nan, "trim_identity": abs(float(bt_["m"][k]) - listing.trimmed(y, kk))}
        r["verdict"] = krevent.hold_verdict(r["M_trim"], r["se_trim"], r["u_trim"], r["p_fw_trim"], r[f"M_trim_{fa}"], r[f"M_trim_{fb}"], r["M_trim"], bar)
        fam.append(r)
    fam = pd.DataFrame(fam)
    return fam, bs, bt_


def _split_rows(E: pd.DataFrame, Y: dict, key: str, labels) -> pd.DataFrame:
    out = []
    vals = E[key].astype(bool)
    for v in (True, False):
        m = (vals == v).to_numpy()
        name = labels[0 if v else 1]
        for h in HOLDS:
            y = Y[h][m]
            y = y[np.isfinite(y)]
            out.append({"split": key, "group": name, "hold": _days(h), "n": int(len(y)), "M_trim": listing.trimmed(y, fundevent.k_trim(len(y))) if len(y) > 2 else np.nan, "M": float(y.mean()) if len(y) else np.nan,
                        "median": float(np.median(y)) if len(y) else np.nan, "share_below_0": float((y < 0).mean()) if len(y) else np.nan, "se_plain": float(y.std(ddof=1) / np.sqrt(len(y))) if len(y) > 1 else np.nan})
    return pd.DataFrame(out)


# ---- the run ------------------------------------------------------------------------------------------------------------------------------
def money_row(M: bt.Market, C: bt.Costs, E: pd.DataFrame, mask: np.ndarray, taker_bps: float, hold: int, entry_mult: float = ENTRY_MULT81, heavy: tuple[float, float] = HEAVY81) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """R81's money row (described, deciding nothing): the sold unit through the harness at the entry day's legs × `entry_mult` the proxy, hedged
    with the block's members bought (`listing.sold_trades`, H = own + hedge); the heavy reading beside; the arithmetic identity of the harness's
    fill with the module's own (R71's `_arith`): gross + funding of the sold position = −a of the same cell."""
    Ec = E.rename(columns={"symbol": "contract"})
    T = listing.sold_trades(M, C, Ec, mask, taker_bps, entry_mult=entry_mult, other_mult=1.0, hold=hold, level=np.inf)
    TH = listing.sold_trades(M, C, Ec, mask, taker_bps, entry_mult=heavy[0], other_mult=heavy[1], hold=hold, level=np.inf)
    a = E[f"a_{_days(hold)}"].to_numpy()
    d = {"sold_gross_funding_vs_minus_a": float(np.nanmax(np.abs((T["gross"] + T["funding"]).to_numpy() + a))) if np.isfinite(a).any() else 0.0,
         "hold_is_the_gate_hold": bool(((T["x"] - T["e"]) == hold).all()), "no_stop": bool(not T["stopped"].any()), "n_priced": int(T["H"].notna().sum()), "n": int(len(T))}
    return T, TH, d


def run(name: str = NAME, taker_bps: float = TAKER_BPS, spec: Spec | None = None) -> str:
    spec = spec or SPECS.get(name, spec_r80)()
    fa, fb = spec.folds
    L = load_events(spec.list_path)
    list_md5 = krevent.md5(spec.list_path)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fp_before, _ = krevent.fp_paths(name)
    guard = None
    if spec.confirm:                                                   # R71's form: registered, once, the guard rows in the ledger BEFORE the market is loaded
        conf = bt._guard(spec.folds, spec.registration)
        tagged = bt.read_tag(spec.registration, None)
        params = {"holds": list(spec.gate_holds), "stop": None, "entry_mult": ENTRY_MULT81, "heavy": list(HEAVY81), "list": spec.list_path.name, "list_md5": list_md5, "rows": int(len(L))}
        stamp = krevent.guard_rows(bt.READS, conf, tagged, STRATEGY81, params)
        guard = {"status": "PASS", "appended_at": stamp, "ledger": str(bt.READS), "folds": list(conf), "logged_as": tagged}
        print(f"guard: ({tagged}, {', '.join(conf)}) appended to {bt.READS} at {stamp}; the {fa}+{fb} market is loaded now", flush=True)
    a0, end = listing.window(spec.folds)
    mem = universe.members(spec.members_csv)
    first_block = mem["block"].min()
    syms = list(dict.fromkeys([*L["symbol"], *universe.screen_symbols(spec.members_csv), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, fv = M.close.to_numpy(), C.fundval
    E_all = entries(M, L, end, first_block)
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    D = E_all[E_all["described"]].reset_index(drop=True)

    def labels_for(F: pd.DataFrame) -> tuple[dict, dict, dict, dict, dict, dict, np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
        rows, own = F["row"].to_numpy(), M.columns.get_indexer(F["symbol"])
        t = pd.DatetimeIndex(F["t"])
        mask, mask_late = listing.member_mask(mem, M.columns, t), listing.member_mask(mem, M.columns, t + LATE * BAR)
        btc = np.full(len(F), M.columns.get_loc(BTC))
        A, B, NB, Y, YL, YB = ({} for _ in range(6))
        for h in HOLDS:
            lab = listing.label_at(close, fv, rows, h)
            A[h], B[h], NB[h] = listing.excess(lab, own, mask)
            Y[h] = A[h] - B[h]
            al, bl, _ = listing.excess(listing.label_at(close, fv, rows + LATE, h), own, mask_late)
            YL[h], YB[h] = al - bl, A[h] - lab[np.arange(len(F)), btc]
        ru = listing.excess(listing.label_at(close, fv, rows - RUNUP - bt.LATENCY, RUNUP), own, mask)        # enters at the bar closing at t − 24 h, exits at the decision bar
        r_in = F["row_into"].to_numpy()
        e_in = np.where(r_in >= 0, r_in + bt.LATENCY, -1)
        into = listing.excess(label_pair(close, fv, e_in, rows), own, mask)                                   # bought after the notice, closed at the decision bar
        sus = np.array([int(M.index.get_indexer([decision_close(x)])[0]) if pd.notna(x) else -1 for x in F["t_suspend"]])
        sus_y = {}
        for h in HOLDS:
            a_s, b_s, _ = listing.excess(listing.label_at(close, fv, sus, h), own, listing.member_mask(mem, M.columns, pd.DatetimeIndex([M.index[r] if r >= 0 else t[i] for i, r in enumerate(sus)])))
            sus_y[h] = a_s - b_s
        bars = krevent.bars_per_event(C, own, t, taker_bps)
        return A, B, NB, Y, YL, YB, ru, into, sus_y, bars

    A, B, NB, Y, YL, YB, (ru_a, ru_b, ru_nb), (in_a, in_b, in_nb), SUS, bars = labels_for(E)
    rows, own, t = E["row"].to_numpy(), M.columns.get_indexer(E["symbol"]), pd.DatetimeIndex(E["t"])
    for h in HOLDS:
        d = _days(h)
        E[f"a_{d}"], E[f"b_{d}"], E[f"n_b_{d}"], E[f"y_{d}"], E[f"y_suspend_{d}"] = A[h], B[h], NB[h], Y[h], SUS[h]
    E["runup_a"], E["runup_b"], E["runup_y"] = ru_a, ru_b, ru_a - ru_b
    E["into_a"], E["into_b"], E["into_y"] = in_a, in_b, in_a - in_b
    E["into_days"] = (t - pd.DatetimeIndex(E["t_into"])) / pd.Timedelta(days=1)
    E = pd.concat([E, bars], axis=1)
    bar = float(E["B_i"].mean()) if len(E) else np.nan

    # validity, read first
    span = [float(np.isfinite(close[r:r + bt.LATENCY + max(HOLDS) + 1, c]).mean()) for r, c in zip(rows, own)]
    ident = {}
    for h in HOLDS:
        full = horizon.labels(M, C, h, bt.LATENCY)[1].to_numpy()
        f = listing._priced(M, C, E.rename(columns={"symbol": "contract"}), h, 1, taker_bps)
        ident[h] = (float(np.nanmax(np.abs(full[rows, own] - A[h]))), float(np.nanmax(np.abs((f["gross_bps"] + f["funding_bps"]).to_numpy() - A[h]))), bool((np.isfinite(full[rows, own]) == np.isfinite(A[h])).all()))
        del full
    red = rederived(L)
    desc_set = {(r.symbol, str(r.t0)) for r in D.itertuples(index=False)}
    drop = E_all[~E_all["eligible"] & ~E_all["described"]]
    drop_set = {(r.symbol, str(r.t0)) for r in drop.itertuples(index=False)}
    V = {"1_fingerprint_before": "saved" if fp_before.exists() else "MISSING", "1_fingerprint_after": "pending → `ft2 upgevent check` after the run",
         "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == spec.list_md5, "2_list_rows": int(len(L)), "2_rederived": red,
         "3_frozen": int(len(L)), "3_cells": int(len(E)), "3_described": sorted(desc_set), "3_described_as_registered": desc_set == spec.expected_described,
         "3_dropped": {f"{s} {t0}": w for s, t0, w in zip(drop["symbol"], drop["t0"].astype(str), drop["why"])}, "3_dropped_as_registered": drop_set == spec.expected_dropped,
         "3_own_cost_row_share": float((E["B_source"] != "R28's 46").mean()) if len(E) else 0.0, "3_B_source": E["B_source"].value_counts().to_dict(),
         "3_at_46": sorted(E[E["B_source"] == "R28's 46"]["symbol"].unique().tolist()),
         "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_events_under_95pct_bars": int(sum(s < MIN_BARS for s in span)),
         "4_label_share": {_days(h): float(np.isfinite(Y[h]).mean()) for h in HOLDS},
         "5_min_members": {_days(h): int(NB[h].min()) if len(E) else 0 for h in HOLDS}, "5_min_members_runup": int(ru_nb.min()) if len(E) else 0, "5_min_members_into": int(in_nb.min()) if len(E) else 0,
         "6_identity_max_abs_diff": {_days(h): ident[h][:2] for h in HOLDS}, "6_same_cells": all(ident[h][2] for h in HOLDS),
         "7_decision_after_t0": bool((t > pd.DatetimeIndex(E["t0"])).all()) if len(E) else False, "7_decision_after_release": bool((t > pd.DatetimeIndex(E["ts_known"])).all()) if len(E) else False,
         "7_into_entry_after_release": bool((pd.DatetimeIndex(E["t_into"]) + bt.LATENCY * BAR > pd.DatetimeIndex(E["ts_known"])).all()) if len(E) else False,
         "7_decision_within_5min_of_t0": bool(((t - pd.DatetimeIndex(E["t0"])) <= BAR).all()) if len(E) else False}
    money = None
    if spec.confirm:
        V["0_guard"] = guard
        mask_e = listing.member_mask(mem, M.columns, t)
        T, TH, d6m = money_row(M, C, E, mask_e, taker_bps, spec.gate_holds[0])
        V["6_money_row_identity"] = d6m
        V["7_exits_at_or_after_end"] = int((pd.DatetimeIndex(T["exit_t"]) >= end).sum()) if len(T) else 0
        money = (T, TH)
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L) == spec.list_rows and red.get("status") == "PASS"
                             and V["3_described_as_registered"] and V["3_dropped_as_registered"] and len(E) >= spec.min_eligible and V["3_own_cost_row_share"] >= MIN_OWN_COST
                             and V["4_events_under_95pct_bars"] == 0 and min(V["4_label_share"].values()) >= MIN_LABELS
                             and min(V["5_min_members"].values()) >= MIN_MEMBERS and V["5_min_members_runup"] >= MIN_MEMBERS and V["5_min_members_into"] >= MIN_MEMBERS
                             and max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_same_cells"]
                             and V["7_decision_after_t0"] and V["7_decision_after_release"] and V["7_into_entry_after_release"] and V["7_decision_within_5min_of_t0"]
                             and (not spec.confirm or (V["6_money_row_identity"]["sold_gross_funding_vs_minus_a"] <= 1e-9 and V["6_money_row_identity"]["hold_is_the_gate_hold"]
                                                       and V["6_money_row_identity"]["no_stop"] and V["7_exits_at_or_after_end"] == 0))) else "FAIL"
    E_all.to_csv(out / "events_all.csv", index=False)
    md = [f"# {spec.title}\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {M.index[0]:%Y-%m-%d} → {M.index[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{spec.list_path.name}` md5 {list_md5}\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 upgevent check`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nRows by what became of them:\n", E_all["why"].replace("", "cell").value_counts().rename("rows").to_frame().to_markdown(), "\n"]

    # the family on the trimmed statistic (computed before the void test so a FAIL still writes nothing of it)
    if V["status"] != "PASS":
        md += ["\n**VOID — the validity rows and the family are not computed." + (" The guard rows stand in the ledger: the folds are read for this question." if spec.confirm else "") + "**\n"]
        (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
        (out / "upgevent.md").write_text("\n".join(md))
        return "\n".join(md)
    f1, f2 = (E["fold"] == fa).to_numpy(), (E["fold"] == fb).to_numpy()
    fam, bs, bt_ = trimmed_family(Y, t, f1, f2, bar, seed=spec.seed, folds=spec.folds)
    if spec.confirm:                                                   # ONE gate hold; the other holds' rows are described (their `verdict` column is R80's family rule, not the gate)
        g = fam[fam["hold"] == _days(spec.gate_holds[0])].iloc[0]
        verdict = confirm_verdict(float(g["M_trim"]), float(g["se_trim"]), float(g["u_trim"]), float(g[f"M_trim_{fa}"]), float(g[f"M_trim_{fb}"]), bar)
        cand = _days(spec.gate_holds[0])
        fam["gate"] = fam["hold"] == cand
    else:
        verdict, cand = krevent.family_verdict(fam.assign(u=fam["u_trim"]))
    V["6_trimmed_identity_max"] = float(fam["trim_identity"].max())
    if V["6_trimmed_identity_max"] > 1e-9:
        verdict, cand, V["status"] = "VOID", None, "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))

    # the validity-of-mechanism rows — read first, no gate
    q = [0.05, 0.25, 0.5, 0.75, 0.95]

    def desc_row(group: str, v: np.ndarray, extra: dict | None = None) -> dict:
        v = v[np.isfinite(v)]
        r = {"group": group, "n": int(len(v)), "median": float(np.median(v)) if len(v) else np.nan, "mean": float(v.mean()) if len(v) else np.nan,
             **{f"q{int(x * 100):02d}": float(np.quantile(v, x)) if len(v) else np.nan for x in q}, "share_above_0": float((v > 0).mean()) if len(v) else np.nan, "share_ge_500": float((v >= 500).mean()) if len(v) else np.nan}
        return {**r, **(extra or {})}

    ry, iy = E["runup_y"].to_numpy(), E["into_y"].to_numpy()
    vrows = [desc_row("INTO row: all", iy, {"median_days": float(np.nanmedian(E["into_days"])), "median_a": float(np.nanmedian(E["into_a"])), "median_b": float(np.nanmedian(E["into_b"]))}),
             desc_row("run-up t0 − 24 h: all", ry, {"median_a": float(np.nanmedian(E["runup_a"])), "median_b": float(np.nanmedian(E["runup_b"]))})]
    for key, labels in SPLITS.items():
        for v in (True, False):
            m = (E[key].astype(bool) == v).to_numpy()
            vrows.append(desc_row(f"INTO row: {key} = {labels[0 if v else 1]}", iy[m]))
            vrows.append(desc_row(f"run-up: {key} = {labels[0 if v else 1]}", ry[m]))
    vr = pd.DataFrame(vrows)
    vr.to_csv(out / "runup.csv", index=False)
    little = bool(vr.loc[0, "median"] < INTO_LITTLE)
    md += ["\n## The validity-of-mechanism rows — the INTO row (bought at the first bar after the notice, closed at the decision bar) and the run-up over t0 − 24 h, against the members; read first, decides nothing\n",
           vr.round(1).to_markdown(index=False), "\n",
           f"\n{'The median INTO row is under +100 bps: by the registration there is little to give back and NOT DETECTABLE is the likely verdict whatever the sign.' if little else 'The median INTO row is at or above +100 bps: a run-up to give back exists.'}\n"]

    # the family
    W = listing.weeks(t)[1]
    fam.to_csv(out / "holds.csv", index=False)
    gate_note = (f"THE GATE ON THE 10 % TRIMMED MEAN OF THE {cand} HOLD ALONE (R80's candidate; M_trim ≤ −B, |u_trim| ≥ 2, {fa}'s and {fb}'s trimmed means < 0; no family-wise p — the 3d and 7d rows are DESCRIBED, their `verdict` column R80's family rule and not the gate)"
                 if spec.confirm else "THE GATE ON THE 10 % TRIMMED MEAN")
    md += [f"\n## The family — y = a − b, bps of the position; {len(E)} cells in {W} weeks; B {bar:.1f} (the mean of the names' own doubled round trips; R28's 46 beside); {DRAWS:,} draws of {BLOCK_WEEKS}-week blocks; the sign NEGATIVE; {gate_note} (k = {fam['k_trim'].tolist()} out at each end, its own block bootstrap: M_trim / se_trim / u_trim / p_fw_trim; the plain mean, the median, the share below zero and M without the five largest / smallest beside, deciding nothing)\n",
           fam.round(3).to_markdown(index=False), "\n", f"\n**Verdict: {verdict}{(' — the ' + ('gate' if spec.confirm else 'candidate') + ' hold ' + cand) if cand else ''}.**\n",
           f"\nn in {fa} {int(f1.sum())}, in {fb} {int(f2.sum())}; cells per week: mean {len(E) / W:.2f}; names {E['symbol'].nunique()}.\n"]
    (out / "upgevent.md").write_text("\n".join(md))                   # the read is on disk before anything is described

    # described — decides nothing
    desc, sold, ref, net = [], [], [], []
    C2 = bt.load_costs(M.index, M.columns, end, cost_mult=2.0, close=M.close)
    Ec = E.rename(columns={"symbol": "contract"})
    for h in HOLDS:
        y, d = Y[h], _days(h)
        v = y[np.isfinite(y)]
        fl = listing._priced(M, C, Ec, h, 1, taker_bps)
        desc.append({"hold": d, "median": np.median(v), "share_below_0": (v < 0).mean(), **{f"q{int(x * 100):02d}": np.quantile(v, x) for x in q}, "min": v.min(), "max": v.max(),
                     "mean_a": np.nanmean(A[h]), "mean_b": np.nanmean(B[h]), "median_a": np.nanmedian(A[h]), "funding_part_of_a": float(np.nanmean(fl["funding_bps"]))})
        sold.append({"hold": d, "mean_sold": -v.mean(), "trimmed_sold": -listing.trimmed(v, fundevent.k_trim(len(v))), "mean_sold_loss_capped_at_size": np.maximum(-v, -1e4).mean(), "largest_single_loss": float(v.max()),
                     "sold_positions_losing_over_half": int((v > 5000).sum()), "share_y_over_5000": float((v > 5000).mean())})
        sv = SUS[h][np.isfinite(SUS[h])]
        ref.append({"hold": d, "M_entry_a_day_later": float(np.nanmean(YL[h])), "median_entry_a_day_later": float(np.nanmedian(YL[h])), "M_against_BTC": float(np.nanmean(YB[h])),
                    "median_against_BTC": float(np.nanmedian(YB[h])), "M_a_alone": float(np.nanmean(A[h])), "n_suspend_entry": int(len(sv)), "M_trim_suspend_entry": listing.trimmed(sv, fundevent.k_trim(len(sv))) if len(sv) > 2 else np.nan,
                    "M_suspend_entry": float(sv.mean()) if len(sv) else np.nan})
        for side, sname in ((1, "bought"), (-1, "sold")):
            for mult, CC in ((1, C), (2, C2)):
                f = listing._priced(M, CC, Ec, h, side, taker_bps)
                net.append({"hold": d, "side": sname, "cost": f"×{mult}", "n_priced": int(f["net_bps"].notna().sum()), "gross": f["gross_bps"].mean(), "fee": f["fee_bps"].mean(), "spread_impact": f["other_cost_bps"].mean(),
                            "funding": f["funding_bps"].mean(), "net": f["net_bps"].mean(), "net_median": f["net_bps"].median()})
        E[f"y_late_{d}"], E[f"y_btc_{d}"] = YL[h], YB[h]
    E.to_csv(out / "events.csv", index=False)
    splits = pd.concat([_split_rows(E, Y, k, lab) for k, lab in SPLITS.items()], ignore_index=True)
    fold_rows = pd.DataFrame([{"split": "fold", "group": f, "hold": _days(h), "n": int(np.isfinite(Y[h][(E['fold'] == f).to_numpy()]).sum()), "M_trim": listing.trimmed(Y[h][(E["fold"] == f).to_numpy()], fundevent.k_trim(int(np.isfinite(Y[h][(E['fold'] == f).to_numpy()]).sum()))),
                               "M": float(np.nanmean(Y[h][(E["fold"] == f).to_numpy()])), "median": float(np.nanmedian(Y[h][(E["fold"] == f).to_numpy()]))} for f in spec.folds for h in HOLDS])
    splits = pd.concat([splits, fold_rows], ignore_index=True)
    splits.to_csv(out / "splits.csv", index=False)
    ycols = [f"y_{_days(h)}" for h in HOLDS]
    qt = E.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")[ycols].agg(["size", "mean", "median"]).round(1)
    ext = pd.concat([E.nlargest(5, "y_7d"), E.nsmallest(5, "y_7d")])[["symbol", "t", "hardfork", "first", "into_y", "runup_y", *ycols]].round(0)
    hours = t.hour.value_counts().sort_index().rename("cells").to_frame()
    bdist = {"B": bar, "B_i_min": float(E["B_i"].min()), "B_i_median": float(E["B_i"].median()), "B_i_max": float(E["B_i"].max()), "R28_constant": krevent.BAR_R28, **{f"source: {k}": int(v) for k, v in E["B_source"].value_counts().items()}}
    corr = {d: float(pd.Series(iy).corr(pd.Series(Y[h]))) for d, h in zip(["1d", "3d", "7d"], HOLDS)}
    hi = iy >= np.nanmedian(iy)
    corr_split = {f"y_1d trimmed, INTO row ≥ median": listing.trimmed(Y[288][hi], fundevent.k_trim(int(np.isfinite(Y[288][hi]).sum()))), "y_1d trimmed, INTO row < median": listing.trimmed(Y[288][~hi], fundevent.k_trim(int(np.isfinite(Y[288][~hi]).sum())))}
    # the described rows (the twelve)
    drow = None
    if len(D):
        Ad, Bd, NBd, Yd, YLd, YBd, (rd_a, rd_b, _), (id_a, id_b, _), SUSd, bars_d = labels_for(D)
        drow = D[["symbol", "t0", "t", "title"]].copy()
        for h in HOLDS:
            drow[f"y_{_days(h)}"] = Yd[h]
        drow["into_y"], drow["runup_y"], drow["B_i"] = id_a - id_b, rd_a - rd_b, bars_d["B_i"].to_numpy()
        drow.to_csv(out / "described_rows.csv", index=False)
    counts = {f"frozen rows of `{spec.other_list.name}` (untouched here)": int(len(pd.read_csv(spec.other_list))) if spec.other_list is not None and spec.other_list.exists() else None, "F5 listed, not frozen": 29}
    # the money row (R81): the sold unit through the harness, hedged with the members — described, deciding nothing
    money_md = []
    if money is not None:
        T, TH = money
        T.to_csv(out / "trades.csv", index=False)
        TH.to_csv(out / "trades_heavy.csv", index=False)
        Hv = T["H"].to_numpy()
        ok = np.isfinite(Hv)
        hr = {"n_priced": int(ok.sum()), "M_H": float(Hv[ok].mean()), "M_trim_H": listing.trimmed(Hv[ok], fundevent.k_trim(int(ok.sum()))), "median_H": float(np.median(Hv[ok])), "share_H_above_0": float((Hv[ok] > 0).mean()),
              "M_own": float(T["own"].mean()), "M_hedge": float(T["hedge"].mean()), "M_gross": float(T["gross"].mean()), "M_funding": float(T["funding"].mean()), "M_fee": float(T["fee"].mean()), "M_spread_impact": float(T["spread_impact"].mean()),
              "M_H_heavy": float(TH["H"].mean()), "M_trim_H_heavy": listing.trimmed(TH["H"].dropna().to_numpy(), fundevent.k_trim(int(TH["H"].notna().sum()))), "min_members_hedge": int(T["n_b"].min()), "largest_single_loss_H": float(-Hv[ok].min()) if ok.any() else np.nan}
        money_md = [f"\n## The money row — the SOLD unit through the harness at the entry day's legs × {ENTRY_MULT81} the proxy, hedged with the block's members bought (H = own + hedge, bps of the position; the heavy reading × {HEAVY81[0]} / × {HEAVY81[1]} beside); described, deciding nothing; no stop\n",
                    pd.DataFrame([hr]).round(1).to_markdown(index=False), "\n"]
    md += ["\n## Described — decides nothing\n",
           *money_md,
           "\nThe splits (hard fork / upgrade only; a name's first notice / repeat; members at t0; two-chain notices; the folds) — the trimmed mean, the plain, the median:\n", splits.round(1).to_markdown(index=False), "\n",
           "\nThe distribution of y, and a and b apart:\n", pd.DataFrame(desc).round(1).to_markdown(index=False), "\n",
           "\nThe money of a SOLD position (−y; the trimmed beside; a loss capped at the position's size is a different rule, shown beside; a stop is not written in):\n", pd.DataFrame(sold).round(3).to_markdown(index=False), "\n",
           f"\nEach position through the harness as a taker (fee {taker_bps} bps a leg, `costwide`'s proxy and its double; the name's own legs, no benchmark):\n", pd.DataFrame(net).round(1).to_markdown(index=False), "\n",
           "\nBy calendar quarter of the entry (cells, mean, median):\n", qt.to_markdown(), "\n",
           "\nThe five largest and the five smallest y at 7 days:\n", ext.to_markdown(index=False), "\n",
           "\nThe hour of t (UTC):\n", hours.to_markdown(), "\n",
           "\nThe INTO row against the give-back: the correlation of into_y with y per hold, and y_1d's trimmed mean on the cells with an INTO row at or above the median against the rest (a fact, not a rule):\n",
           "\n```\n" + json.dumps({"corr": corr, **corr_split}, indent=1) + "\n```\n",
           "\nThe bar: B_i's distribution and its sources:\n", "\n```\n" + json.dumps(bdist, indent=1) + "\n```\n",
           "\nThe described rows (the twelve's; every number the cells have, no gate):\n", "none" if drow is None else drow.round(1).to_markdown(index=False), "\n",
           "\nCounts recorded, not priced:\n", "\n```\n" + json.dumps(counts, indent=1, default=str) + "\n```\n",
           "\n## Reference rows — no verdict (the entry a day later; against BTC; a alone; the entry at the deposit suspension's stamp — the same sold unit, a described entry)\n", pd.DataFrame(ref).round(1).to_markdown(index=False), "\n"]
    (out / "meta.json").write_text(json.dumps({"registration": spec.registration, "decision": spec.decision, "unit": bt.UNIT, "charged": bt.CHARGED, "holds": HOLDS, "gate_holds": list(spec.gate_holds), "runup": RUNUP, "bar": bar, "bar_mult": krevent.BAR_MULT,
                                                "bar_r28": krevent.BAR_R28, "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": spec.seed, "trim_frac": TRIM_FRAC, "frozen": int(len(L)), "cells": int(len(E)), "weeks": W,
                                                "taker_bps": taker_bps, "list_md5": list_md5, "verdict": verdict, "candidate_hold": cand, "into_little": little, "folds": list(spec.folds)}, indent=1))
    text = "\n".join(md)
    (out / "upgevent.md").write_text(text)
    return text


def main(action: str, name: str | None = None) -> None:
    if action == "fingerprint":
        print(krevent.fingerprint(name or NAME))
    elif action == "run":
        text = run(name or NAME)
        print(text)
        if "**VOID" in text or '"status": "FAIL"' in text:
            sys.exit(2)
    elif action == "check":
        r = krevent.check(name or NAME)
        if not r["pass"]:
            sys.exit(2)
    else:
        sys.exit(f"upgevent: unknown action {action}")
