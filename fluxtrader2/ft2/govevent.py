"""P8, R83 — the END of a name's governance vote on Snapshot as a per-name event: the name SOLD at the first 5m bar closing after the vote
closes, held ONE DAY against the screener's members (three days described): does it fall behind its peers? `ft2 govevent fingerprint|run|check`
(PLAN §8 R83 is the registration, decision CH1; this file is its code and changes nothing of it — R80's `upgevent.py` with the event table
swapped: the FROZEN `ft2/govvotes_f12.csv`, its `cell_big` flag the gate's cells, the `cell_all` flag a second population DESCRIBED through
the same functions, the creation row in place of the INTO row, a 21-day pad, one gate hold).

events     the FROZEN `ft2/govvotes_f12.csv` (decision CG1's audit, DATA.md `gov_votes`; md5 as registered): symbol, t0 = the vote's END,
           ts_known = the proposal's creation, cell_all / cell_big, kind, passed, votes, member_at_t0. Nothing is added, dropped or re-dated
           here; a row the entry rule cannot hold is counted by reason — the three early-May ends before the first member block and
           AAVE 2024-08-31 (its 1-day exit past F2's end) are the registered drops.
entry      the decision bar is the FIRST 5m bar that closes strictly after t0 (the bar closing at floor(t0, 5 min) + 5 min); the position is
           entered one bar later (the harness's latency) — 5 … 10 minutes after the end.
label      R70's: a = what a long earns before trading costs with the funding it pays (`listing.label_at` = `horizon.labels`' number);
           b = the mean over the members of the block that holds t, the name itself left out (`listing.excess`); y = a − b. A sold
           position earns −y.
statistic  THE GATE ON THE 10 % TRIMMED MEAN of the 1-day hold ALONE (R77's, `fundevent.bootstrap_trimmed`: k = round(0.05 n) out at each end,
           the draw's statistic the trimmed mean, seed 83; the hold's own p, no family correction); the 3-day row described; the plain mean
           and its bootstrap beside, deciding nothing. The sign NEGATIVE: M_trim ≤ −B.
bar        rule (a): B = the mean over the cells of B_i = 2 × the name's own taker round trip on its entry day (`krevent.bars_per_event`;
           the 7-day fallback, else R28's 46).
rows read  first, no gate: the CREATION row (BOUGHT at the first bar closing after the proposal's creation + latency, closed at the decision
first      bar — the vote's duration later; a cell whose creation bar is outside the market has no row, counted) and the RUN-UP (y over
           t0 − 24 h → the decision bar).
validity   (1) the archive slice's fingerprint before (`fingerprint`) and after (`check`); (2) the list's md5, 3,117 rows and 334 flagged,
           every row re-derived by `govlist.events()` from the proposals on disk; (3) exactly the four named rows out, ≥ 325 cells, ≥ 75 %
           with their own cost row; (4) bars and labels ≥ 95 %; (5) members ≥ 40 on the cells each row keeps, the creation rows dropped ≤ 5;
           (6) the label identity with `horizon.labels` and the harness, the trimmed identity with `listing.trimmed`; (7) every cell's decision
           bar closes after t0 AND after the creation; the creation entry after the creation.

R84 (PLAN §8, decision CI2; `ft2 govevent run --name r84`): the same path with the Spec swapped — the FROZEN `ft2/govvotes_f34.csv`'s
`cell_big` rows (200 on 20 names), the F3+F4 members (`ft2/screen_members_f34.csv`), the 3-DAY hold THE GATE (864 bars; chosen on R83's
described 3d row — hindsight-generated, said in the registration) and the 1-day row described, seed 84, a 24-day pad, `confirm` on: the
guard rows (R84, F3) / (R84, F4), strategy `gov_sold_3d`, appended to the ledger BEFORE the market is loaded (R81's form, `backtest._guard`,
`krevent.guard_rows`); the verdict R81's `upgevent.confirm_verdict` on the one hold (CONFIRMED if M_trim ≤ −B, |u_trim| ≥ 2, F3 < 0 and
F4 < 0; NOT CONFIRMED otherwise, "under the bar" / "the opposite sign" as facts beside); the money row `upgevent.money_row` (the sold unit
through the harness at the entry day's legs × 2, hedged with the block's members, the heavy reading beside) described; the whole-vote
cells (`cell_all`) described on the cells that have bars (their months are NOT fetched by decision CI2's Data line: a name without bars
is counted out by `entries`, "no bars of the name in the market"). R83's path is byte-for-byte unchanged through `spec_r83()`.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import fundevent, govlist, horizon, krevent, krw, listing, universe
from .ceiling import BAR
from .upgevent import ENTRY_MULT81, HEAVY81, confirm_verdict, decision_close, entries, label_pair, money_row

NAME = "r83"
OUT = listing.OUT                                  # output/listing
LIST = govlist.LISTS["f12"]
LIST_MD5 = "be388f08d0b1e0ab257858659e6cbb72"      # as frozen 003389f and registered (PLAN §8 R83)
LIST_ROWS = 3117
GATE_FLAG, OTHER_FLAG = "cell_big", "cell_all"     # the gate's population (≥ 200 voters, one a name per 7 days); the whole-vote cells described
GATE_ROWS = 334
FOLDS = ("F1", "F2")
HOLDS = (288, 864)                                 # 1 day THE GATE; 3 days described
GATE_HOLD = 288
RUNUP = 288                                        # the run-up row: t0 − 24 h → the decision bar
LATE = 288                                         # reference row: the entry a day later
TAKER_BPS = 5.0
BLOCK_WEEKS, DRAWS, SEED = 6, 10_000, 83
TRIM_FRAC = fundevent.TRIM_FRAC                    # the 10 % trimmed mean: 5 % out at each end
MIN_MEMBERS, MIN_ELIGIBLE, MIN_OWN_COST, MIN_BARS, MIN_LABELS, MAX_CREATION_DROPPED = 40, 325, 0.75, 0.95, 0.95, 5
PAD_DAYS = 21                                      # the market from the folds' start minus ⌈the list's lead q99⌉ + 7 days: every creation inside it
DESCRIBED = tuple(krw.TWELVE)                      # the twelve's rows would be described, never cells (none in the list: ETH's space is an excluded id)
EXPECTED_DESCRIBED: set = set()
EXPECTED_DROPPED = {("AAVEUSDT", "2023-05-01 16:00:00+00:00"), ("CVXUSDT", "2023-05-02 00:00:38+00:00"), ("JOEUSDT", "2023-05-02 07:34:56+00:00"),
                    ("AAVEUSDT", "2024-08-31 07:20:12+00:00")}
EXPECTED_3D_DROPPED = {("APEUSDT", "2024-08-29 01:00:00+00:00"), ("ARBUSDT", "2024-08-29 18:49:11+00:00")}   # the described hold's label past F2's end, counted
BTC = "BTCUSDT"
TOP5 = ("AAVEUSDT", "APEUSDT", "ARBUSDT", "CVXUSDT", "GTCUSDT")
KINDS = ("gauge", "election", "listing", "grant", "parameter", "treasury", "other")
SPLITS = {"passed": ("passed", "failed"), "top5": ("the five busiest names", "the rest"), "member_at_t0": ("member at t0", "not a member"),
          "on_hour": ("the end on the hour", "off the hour"), "big_votes": ("voters ≥ the median", "below")}
INTO_LITTLE = 100.0                                # the creation row's median inside ±this: nothing to give back (recorded beside the verdict)
F34_ROWS, F34_BIG, F5_ROWS, F5_BIG = 2096, 200, 604, 32   # counts recorded, not priced
COUNTS83 = {"frozen rows of govvotes_f34.csv (untouched here)": F34_ROWS, "of them cell_big (F3+F4)": F34_BIG, "F5 listed, not frozen": F5_ROWS, "of them cell_big (F5)": F5_BIG}

# R84 — the confirmation read on the frozen F3+F4 list (decision CI2, PLAN §8 R84): R83's path with the list, the members, the folds, the gate
# hold and the verdict swapped — the 3-day hold THE GATE (hindsight-generated on R83's described 3d row), the 1-day row described; the guard rows
# (R84, F3) / (R84, F4) appended to the ledger BEFORE the F3+F4 market is loaded (R71's / R81's form); the money row described, deciding nothing.
NAME84 = "r84"
LIST34 = govlist.LISTS["f34"]
LIST34_MD5 = "dd392bb32e13246092c96aef718af0a2"    # as frozen 003389f (DATA.md `gov_votes`) and registered (PLAN §8 R84)
LIST34_ROWS = 2096
GATE_ROWS34 = 200                                  # the `cell_big` rows of F3+F4: 20 names, F3 139 / F4 61
FOLDS34 = ("F3", "F4")
SEED84 = 84
GATE_HOLD84 = 864                                  # 3 days THE GATE; 1 day described
EXPECTED_DROPPED34 = {("GHSTUSDT", "2025-12-30 20:15:00+00:00")}   # its 3-day exit lies past F4's end (2026-01-01) — dropped by the calendar's end, counted; none before the first member block (2024-09-03)
EXPECTED_OTHER_DROPPED34: set = set()              # the described 1-day row has a label on every cell the 3-day gate keeps
MIN_ELIGIBLE84 = 190                               # ≥ 95 % of the 199 cells (the Data line: 200 of 200 windows with bars expected)
PAD_DAYS84 = 24                                    # ⌈the list's longest lead, 22.66 d (GHST 2025-12-30)⌉ + 1: the market from 2024-08-10, every creation row inside it
STRATEGY84 = "gov_sold_3d"
TOP5_34 = ("ARBUSDT", "AAVEUSDT", "GHSTUSDT", "UNIUSDT", "GMXUSDT")   # the five busiest names of the F3+F4 big cut (38, 31, 26, 17, 16 of 200)
COUNTS84 = {"frozen rows of govvotes_f12.csv (R83's, untouched here)": LIST_ROWS, "of them cell_big (F1+F2)": GATE_ROWS, "F5 listed, not frozen": F5_ROWS, "of them cell_big (F5)": F5_BIG}


@dataclasses.dataclass
class Spec:
    registration: str
    decision: str
    title: str
    list_path: Path
    list_md5: str
    list_rows: int
    flag: str
    flag_rows: int
    other_flag: str | None
    folds: tuple[str, str]
    members_csv: Path | None
    seed: int
    expected_described: set
    expected_dropped: set
    expected_other_dropped: set                    # the cells whose label at the DESCRIBED hold is past the market's end (R83: APE and ARB 2024-08-29 at 3d)
    min_eligible: int
    pad_days: int
    gate_hold: int = GATE_HOLD                     # the one gate hold; the other of HOLDS is described
    confirm: bool = False                          # the guard rows, R81's single-hold CONFIRMED / NOT CONFIRMED verdict, the money row
    strategy: str | None = None                    # the ledger's strategy name (confirm only)
    top5: tuple[str, ...] = TOP5                   # the five busiest names of the gate's population (a described split)
    counts: dict = dataclasses.field(default_factory=lambda: dict(COUNTS83))   # counts recorded, not priced


def spec_r83() -> Spec:
    """Read at call time, so a test's monkeypatch of the module's constants applies."""
    return Spec("R83", "CH1", "R83 — the governance vote's END: the name sold at the first bar after its Snapshot vote closes, 1 day against the members (`ft2 govevent run`)",
                LIST, LIST_MD5, LIST_ROWS, GATE_FLAG, GATE_ROWS, OTHER_FLAG, FOLDS, None, SEED, EXPECTED_DESCRIBED, EXPECTED_DROPPED, EXPECTED_3D_DROPPED, MIN_ELIGIBLE, PAD_DAYS)


def spec_r84() -> Spec:
    return Spec("R84", "CI2", "R84 — the confirmation read of the governance vote's END sold at the first bar after the vote closes, 3 days (hindsight-generated) against the F3+F4 members (`ft2 govevent run --name r84`)",
                LIST34, LIST34_MD5, LIST34_ROWS, GATE_FLAG, GATE_ROWS34, OTHER_FLAG, FOLDS34, universe.F34_MEMBERS_CSV, SEED84, set(), EXPECTED_DROPPED34, EXPECTED_OTHER_DROPPED34, MIN_ELIGIBLE84, PAD_DAYS84,
                GATE_HOLD84, True, STRATEGY84, TOP5_34, dict(COUNTS84))


SPECS = {NAME: spec_r83, NAME84: spec_r84}


def _days(h: int) -> str:
    return f"{h // 288}d"


# ---- the frozen events ----------------------------------------------------------------------------------------------------------
def load_events(path: Path | str = LIST, top5: tuple[str, ...] = TOP5) -> pd.DataFrame:
    L = pd.read_csv(path)
    for c in ("t0", "ts_known", "release", "block", "perp_first", "start"):
        L[c] = pd.to_datetime(L[c], utc=True, format="ISO8601")
    for c in ("cell_all", "cell_big", "member_at_t0", "flagged"):
        L[c] = L[c].astype(bool)
    L["passed"] = L["passed"].map({True: True, False: False, "True": True, "False": False})
    t = pd.DatetimeIndex(L["t0"])
    L["on_hour"] = (t.minute == 0) & (t.second == 0)
    L["top5"] = L["symbol"].isin(top5)
    return L


def rederived(L: pd.DataFrame) -> dict:
    """Validity (2): every frozen row's t0, symbol and flags are what `govlist.events`' rule gives from the proposals on disk today."""
    try:
        E = govlist.events(write=False)
    except Exception as e:                                         # noqa: BLE001 — recorded, and the validity fails
        return {"status": "MISSING", "why": str(e)[:200]}
    E = E.drop_duplicates(["code", "symbol"]).set_index(["code", "symbol"])
    bad = []
    for r in L.itertuples(index=False):
        k = (r.code, r.symbol)
        if k not in E.index:
            bad.append({"code": r.code, "symbol": r.symbol, "why": "not a candidate today"})
        elif pd.Timestamp(E.loc[k, "t0"]) != r.t0:
            bad.append({"code": r.code, "symbol": r.symbol, "why": "t0 differs", "frozen": str(r.t0), "today": str(E.loc[k, "t0"])})
        elif E.loc[k, "why"] != "eligible":
            bad.append({"code": r.code, "symbol": r.symbol, "why": f"not eligible today: {E.loc[k, 'why']}"})
        elif bool(E.loc[k, "cell_big"]) != bool(r.cell_big) or bool(E.loc[k, "cell_all"]) != bool(r.cell_all):
            bad.append({"code": r.code, "symbol": r.symbol, "why": "the cell flags differ"})
    return {"status": "PASS" if not bad else "FAIL", "rows": int(len(L)), "bad": bad}


# ---- the statistic per hold: the trimmed gate on the hold ALONE -----------------------------------------------------------------------
def hold_rows(Y: dict, t: pd.DatetimeIndex, f1: np.ndarray, f2: np.ndarray, bar: float, seed: int, folds: tuple[str, str], gate_hold: int = GATE_HOLD) -> pd.DataFrame:
    """Per hold: the trimmed statistic with its own block bootstrap over the hold's column alone (p = the hold's own; one gate hold, no family
    correction) and the plain mean with R28's beside. The gate column marks the registered hold; the others' `verdict` is R80's rule, described."""
    fa, fb = folds
    wk, W = listing.weeks(t)
    fam = []
    for h in HOLDS:
        y = Y[h]
        Ymat = y[:, None]
        bs = listing.bootstrap(Ymat, wk, W, block=BLOCK_WEEKS, draws=DRAWS, seed=seed)
        bt_ = fundevent.bootstrap_trimmed(Ymat, wk, W, TRIM_FRAC, block=BLOCK_WEEKS, draws=DRAWS, seed=seed)
        v = y[np.isfinite(y)]
        kk = int(bt_["k"][0])
        n1, n2 = int(np.isfinite(y[f1]).sum()), int(np.isfinite(y[f2]).sum())
        r = {"hold": _days(h), "gate": h == gate_hold, "n": int(bs["n"][0]), "k_trim": kk, "M_trim": float(bt_["m"][0]), "se_trim": float(bt_["se"][0]), "u_trim": float(bt_["u"][0]), "p_trim": float(bt_["p_fw"]),
             "MDE_trim": 2.8 * float(bt_["se"][0]), f"M_trim_{fa}": listing.trimmed(y[f1], fundevent.k_trim(n1)), f"M_trim_{fb}": listing.trimmed(y[f2], fundevent.k_trim(n2)),
             "B": bar, "M": float(bs["m"][0]), "se": float(bs["se"][0]), "u": float(bs["u"][0]), "p": float(bs["p_fw"]), "MDE": 2.8 * float(bs["se"][0]), "se_week": float(bs["se_week"][0]),
             "se_plain": float(bs["se_plain"][0]), f"M_{fa}": float(np.nanmean(y[f1])), f"M_{fb}": float(np.nanmean(y[f2])), "median": float(np.median(v)) if len(v) else np.nan,
             "share_below_0": float((v < 0).mean()) if len(v) else np.nan, "M_without_k_largest": float(np.sort(v)[:-kk].mean()) if len(v) > kk > 0 else np.nan,
             "M_without_k_smallest": float(np.sort(v)[kk:].mean()) if len(v) > kk > 0 else np.nan, "trim_identity": abs(float(bt_["m"][0]) - listing.trimmed(y, kk))}
        r["verdict"] = krevent.hold_verdict(r["M_trim"], r["se_trim"], r["u_trim"], r["p_trim"], r[f"M_trim_{fa}"], r[f"M_trim_{fb}"], r["M_trim"], bar)
        fam.append(r)
    return pd.DataFrame(fam)


def gate_verdict(row: pd.Series) -> str:
    v = row["verdict"]
    return "CLOSED" if v == "under the bar" else v


def _split_rows(E: pd.DataFrame, Y: dict, key: str, labels, mask_true: np.ndarray | None = None) -> pd.DataFrame:
    out = []
    vals = E[key].astype(bool).to_numpy() if mask_true is None else mask_true
    for v in (True, False):
        m = vals == v
        name = labels[0 if v else 1]
        for h in HOLDS:
            y = Y[h][m]
            y = y[np.isfinite(y)]
            out.append({"split": key, "group": name, "hold": _days(h), "n": int(len(y)), "M_trim": listing.trimmed(y, fundevent.k_trim(len(y))) if len(y) > 2 else np.nan, "M": float(y.mean()) if len(y) else np.nan,
                        "median": float(np.median(y)) if len(y) else np.nan, "share_below_0": float((y < 0).mean()) if len(y) else np.nan, "se_plain": float(y.std(ddof=1) / np.sqrt(len(y))) if len(y) > 1 else np.nan})
    return pd.DataFrame(out)


def _group_rows(E: pd.DataFrame, Y: dict, key: str, split: str) -> pd.DataFrame:
    out = []
    for g, idx in E.groupby(key).indices.items():
        for h in HOLDS:
            y = Y[h][idx]
            y = y[np.isfinite(y)]
            out.append({"split": split, "group": str(g), "hold": _days(h), "n": int(len(y)), "M_trim": listing.trimmed(y, fundevent.k_trim(len(y))) if len(y) > 2 else np.nan,
                        "M": float(y.mean()) if len(y) else np.nan, "median": float(np.median(y)) if len(y) else np.nan, "share_below_0": float((y < 0).mean()) if len(y) else np.nan})
    return pd.DataFrame(out)


# ---- a population through the frame -------------------------------------------------------------------------------------------------
def population(M: bt.Market, C: bt.Costs, mem: pd.DataFrame, L: pd.DataFrame, end: pd.Timestamp, first_block: pd.Timestamp, taker_bps: float, gate_hold: int = GATE_HOLD) -> dict:
    """The entries, the labels at both holds, the creation row, the run-up, the reference rows and the bars for the rows of one population."""
    E_all = entries(M, L, end, first_block, longest=gate_hold, described=DESCRIBED)
    E_all["why"] = E_all["why"].str.replace("the 7-day exit", f"the {_days(gate_hold)} exit", regex=False)
    E_all["eligible"] = E_all["why"] == ""
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    close, fv = M.close.to_numpy(), C.fundval
    rows, own = E["row"].to_numpy(), M.columns.get_indexer(E["symbol"])
    t = pd.DatetimeIndex(E["t"])
    mask, mask_late = listing.member_mask(mem, M.columns, t), listing.member_mask(mem, M.columns, t + LATE * BAR)
    btc = np.full(len(E), M.columns.get_loc(BTC))
    A, B, NB, Y, YL, YB = ({} for _ in range(6))
    for h in HOLDS:
        lab = listing.label_at(close, fv, rows, h)
        A[h], B[h], NB[h] = listing.excess(lab, own, mask)
        Y[h] = A[h] - B[h]
        al, bl, _ = listing.excess(listing.label_at(close, fv, rows + LATE, h), own, mask_late)
        YL[h], YB[h] = al - bl, A[h] - lab[np.arange(len(E)), btc]
    ru = listing.excess(listing.label_at(close, fv, rows - RUNUP - bt.LATENCY, RUNUP), own, mask)          # enters at the bar closing at t − 24 h, exits at the decision bar
    r_in = E["row_into"].to_numpy()
    e_in = np.where(r_in >= 0, r_in + bt.LATENCY, -1)
    into = listing.excess(label_pair(close, fv, e_in, rows), own, mask)                                     # bought after the creation, closed at the decision bar
    bars = krevent.bars_per_event(C, own, t, taker_bps)
    for h in HOLDS:
        d = _days(h)
        E[f"a_{d}"], E[f"b_{d}"], E[f"n_b_{d}"], E[f"y_{d}"], E[f"y_late_{d}"], E[f"y_btc_{d}"] = A[h], B[h], NB[h], Y[h], YL[h], YB[h]
    E["runup_a"], E["runup_b"], E["runup_y"] = ru[0], ru[1], ru[0] - ru[1]
    E["creation_a"], E["creation_b"], E["creation_y"] = into[0], into[1], into[0] - into[1]
    E["creation_days"] = (t - pd.DatetimeIndex(E["t_into"])) / pd.Timedelta(days=1)
    E = pd.concat([E, bars], axis=1)
    E["big_votes"] = E["votes"] >= E["votes"].median()
    return {"E_all": E_all, "E": E, "A": A, "B": B, "NB": NB, "Y": Y, "YL": YL, "YB": YB, "ru": ru, "into": into, "rows": rows, "own": own, "t": t, "mask": mask}


def run(name: str = NAME, taker_bps: float = TAKER_BPS, spec: Spec | None = None) -> str:
    spec = spec or SPECS.get(name, spec_r83)()
    fa, fb = spec.folds
    gh = spec.gate_hold
    oh = [h for h in HOLDS if h != gh][0]                            # the described hold
    cand, od = _days(gh), _days(oh)
    L_full = load_events(spec.list_path, spec.top5)
    list_md5 = krevent.md5(spec.list_path)
    L = L_full[L_full[spec.flag]].reset_index(drop=True)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fp_before, _ = krevent.fp_paths(name)
    guard = None
    if spec.confirm:                                                   # R71's / R81's form: registered, once, the guard rows in the ledger BEFORE the market is loaded
        conf = bt._guard(spec.folds, spec.registration)
        params = {"holds": [gh], "stop": None, "entry_mult": ENTRY_MULT81, "heavy": list(HEAVY81), "list": spec.list_path.name, "list_md5": list_md5, "rows": int(len(L_full)), "flag": spec.flag, "flag_rows": int(len(L))}
        stamp = krevent.guard_rows(bt.READS, conf, spec.registration, spec.strategy, params)
        guard = {"status": "PASS", "appended_at": stamp, "ledger": str(bt.READS), "folds": list(conf), "logged_as": spec.registration, "strategy": spec.strategy}
        print(f"guard: ({spec.registration}, {', '.join(conf)}) appended to {bt.READS} at {stamp}; the {fa}+{fb} market is loaded now", flush=True)
    a0, end = listing.window(spec.folds)
    mem = universe.members(spec.members_csv)
    first_block = mem["block"].min()
    syms = list(dict.fromkeys([*L_full["symbol"], *universe.screen_symbols(spec.members_csv), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=spec.pad_days))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close = M.close.to_numpy()
    P = population(M, C, mem, L, end, first_block, taker_bps, gh)
    E_all, E, A, NB, Y = P["E_all"], P["E"], P["A"], P["NB"], P["Y"]
    rows, own, t = P["rows"], P["own"], P["t"]
    ru_nb, in_nb = P["ru"][2], P["into"][2]
    bar = float(E["B_i"].mean()) if len(E) else np.nan

    # validity, read first
    span = [float(np.isfinite(close[r:r + bt.LATENCY + max(HOLDS) + 1, c]).mean()) for r, c in zip(rows, own)]
    ident = {}
    for h in HOLDS:
        full = horizon.labels(M, C, h, bt.LATENCY)[1].to_numpy()
        f = listing._priced(M, C, E.rename(columns={"symbol": "contract"}), h, 1, taker_bps)
        ident[h] = (float(np.nanmax(np.abs(full[rows, own] - A[h]))) if len(E) else 0.0, float(np.nanmax(np.abs((f["gross_bps"] + f["funding_bps"]).to_numpy() - A[h]))) if len(E) else 0.0,
                    bool((np.isfinite(full[rows, own]) == np.isfinite(A[h])).all()))
        del full
    red = rederived(L_full)
    D = E_all[E_all["described"]]
    desc_set = {(r.symbol, str(r.t0)) for r in D.itertuples(index=False)}
    drop = E_all[~E_all["eligible"] & ~E_all["described"]]
    drop_set = {(r.symbol, str(r.t0)) for r in drop.itertuples(index=False)}
    y3 = Y[oh]
    d3_set = {(s, str(t0)) for s, t0, v in zip(E["symbol"], E["t0"], y3) if not np.isfinite(v)}
    cre_ok = np.isfinite(E["creation_y"].to_numpy()) if len(E) else np.array([], dtype=bool)
    V = {"1_fingerprint_before": "saved" if fp_before.exists() else "MISSING", "1_fingerprint_after": "pending → `ft2 govevent check` after the run",
         "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == spec.list_md5, "2_list_rows": int(len(L_full)), "2_flag_rows": int(len(L)), "2_rederived": red,
         "3_frozen_flagged": int(len(L)), "3_cells": int(len(E)), "3_described": sorted(desc_set), "3_described_as_registered": desc_set == spec.expected_described,
         "3_dropped": {f"{s} {t0}": w for s, t0, w in zip(drop["symbol"], drop["t0"].astype(str), drop["why"])}, "3_dropped_as_registered": drop_set == spec.expected_dropped,
         f"3_{od}_label_dropped": sorted(d3_set), f"3_{od}_dropped_as_registered": d3_set == spec.expected_other_dropped,
         "3_own_cost_row_share": float((E["B_source"] != "R28's 46").mean()) if len(E) else 0.0, "3_B_source": E["B_source"].value_counts().to_dict(),
         "3_at_46": sorted(E[E["B_source"] == "R28's 46"]["symbol"].unique().tolist()),
         "3_creation_rows_dropped": int((~cre_ok).sum()), "3_creation_rows_dropped_cells": [f"{s} {t0}" for s, t0, ok in zip(E["symbol"], E["t0"].astype(str), cre_ok) if not ok],
         "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_events_under_95pct_bars": int(sum(s < MIN_BARS for s in span)),
         "4_label_share": {_days(h): float(np.isfinite(Y[h]).mean()) if len(E) else 0.0 for h in HOLDS},
         "5_min_members": {_days(h): int(NB[h][np.isfinite(Y[h])].min()) if np.isfinite(Y[h]).any() else 0 for h in HOLDS},
         "5_min_members_runup": int(ru_nb[np.isfinite(P["ru"][0] - P["ru"][1])].min()) if len(E) and np.isfinite(P["ru"][0] - P["ru"][1]).any() else 0,
         "5_min_members_creation": int(in_nb[cre_ok].min()) if cre_ok.any() else 0,
         "6_identity_max_abs_diff": {_days(h): ident[h][:2] for h in HOLDS}, "6_same_cells": all(ident[h][2] for h in HOLDS),
         "7_decision_after_t0": bool((t > pd.DatetimeIndex(E["t0"])).all()) if len(E) else False, "7_decision_after_creation": bool((t > pd.DatetimeIndex(E["ts_known"])).all()) if len(E) else False,
         "7_creation_entry_after_creation": bool((pd.DatetimeIndex(E["t_into"]) + bt.LATENCY * BAR > pd.DatetimeIndex(E["ts_known"])).all()) if len(E) else False,
         "7_decision_within_5min_of_t0": bool(((t - pd.DatetimeIndex(E["t0"])) <= BAR).all()) if len(E) else False}
    money = None
    if spec.confirm:                                                   # the money row (R81's): the sold unit through the harness, hedged with the members — its identity with the label is validity (6)
        V["0_guard"] = guard
        T, TH, d6m = money_row(M, C, E, P["mask"], taker_bps, gh) if len(E) else (pd.DataFrame(), pd.DataFrame(), {"sold_gross_funding_vs_minus_a": np.inf, "hold_is_the_gate_hold": False, "no_stop": False, "n_priced": 0, "n": 0})
        V["6_money_row_identity"] = d6m
        V["7_exits_at_or_after_end"] = int((pd.DatetimeIndex(T["exit_t"]) >= end).sum()) if len(T) else 0
        money = (T, TH)
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L_full) == spec.list_rows and len(L) == spec.flag_rows and red.get("status") == "PASS"
                             and V["3_described_as_registered"] and V["3_dropped_as_registered"] and V[f"3_{od}_dropped_as_registered"] and len(E) >= spec.min_eligible
                             and V["3_own_cost_row_share"] >= MIN_OWN_COST and V["3_creation_rows_dropped"] <= MAX_CREATION_DROPPED
                             and V["4_events_under_95pct_bars"] == 0 and min(V["4_label_share"].values()) >= MIN_LABELS
                             and min(V["5_min_members"].values()) >= MIN_MEMBERS and V["5_min_members_runup"] >= MIN_MEMBERS and V["5_min_members_creation"] >= MIN_MEMBERS
                             and max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_same_cells"]
                             and V["7_decision_after_t0"] and V["7_decision_after_creation"] and V["7_creation_entry_after_creation"] and V["7_decision_within_5min_of_t0"]
                             and (not spec.confirm or (V["6_money_row_identity"]["sold_gross_funding_vs_minus_a"] <= 1e-9 and V["6_money_row_identity"]["hold_is_the_gate_hold"]
                                                       and V["6_money_row_identity"]["no_stop"] and V["7_exits_at_or_after_end"] == 0))) else "FAIL"
    E_all.to_csv(out / "events_all.csv", index=False)
    md = [f"# {spec.title}\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {M.index[0]:%Y-%m-%d} → {M.index[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{spec.list_path.name}` md5 {list_md5}, the gate's flag `{spec.flag}` ({len(L)} rows)\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 govevent check`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nRows by what became of them:\n", E_all["why"].replace("", "cell").value_counts().rename("rows").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the validity rows and the gate are not computed." + (" The guard rows stand in the ledger: the folds are read for this question." if spec.confirm else "") + "**\n"]
        (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
        (out / "govevent.md").write_text("\n".join(md))
        return "\n".join(md)
    f1, f2 = (E["fold"] == fa).to_numpy(), (E["fold"] == fb).to_numpy()
    fam = hold_rows(Y, t, f1, f2, bar, spec.seed, spec.folds, gh)
    g = fam[fam["gate"]].iloc[0]
    verdict = confirm_verdict(float(g["M_trim"]), float(g["se_trim"]), float(g["u_trim"]), float(g[f"M_trim_{fa}"]), float(g[f"M_trim_{fb}"]), bar) if spec.confirm else gate_verdict(g)
    V["6_trimmed_identity_max"] = float(fam["trim_identity"].max())
    if V["6_trimmed_identity_max"] > 1e-9:
        verdict, V["status"] = "VOID", "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))

    # the validity-of-mechanism rows — read first, no gate
    q = [0.05, 0.25, 0.5, 0.75, 0.95]

    def desc_row(group: str, v: np.ndarray, extra: dict | None = None) -> dict:
        v = v[np.isfinite(v)]
        r = {"group": group, "n": int(len(v)), "median": float(np.median(v)) if len(v) else np.nan, "mean": float(v.mean()) if len(v) else np.nan,
             **{f"q{int(x * 100):02d}": float(np.quantile(v, x)) if len(v) else np.nan for x in q}, "share_above_0": float((v > 0).mean()) if len(v) else np.nan, "share_ge_500": float((v >= 500).mean()) if len(v) else np.nan}
        return {**r, **(extra or {})}

    ry, iy = E["runup_y"].to_numpy(), E["creation_y"].to_numpy()
    vrows = [desc_row("CREATION row: all", iy, {"median_days": float(np.nanmedian(E["creation_days"])), "median_a": float(np.nanmedian(E["creation_a"])), "median_b": float(np.nanmedian(E["creation_b"]))}),
             desc_row("run-up t0 − 24 h: all", ry, {"median_a": float(np.nanmedian(E["runup_a"])), "median_b": float(np.nanmedian(E["runup_b"]))})]
    for key, labels in SPLITS.items():
        for v in (True, False):
            m = (E[key].astype(bool) == v).to_numpy()
            vrows.append(desc_row(f"CREATION row: {key} = {labels[0 if v else 1]}", iy[m]))
            vrows.append(desc_row(f"run-up: {key} = {labels[0 if v else 1]}", ry[m]))
    for k in KINDS:
        vrows.append(desc_row(f"CREATION row: kind = {k}", iy[(E["kind"] == k).to_numpy()]))
    vr = pd.DataFrame(vrows)
    vr.to_csv(out / "runup.csv", index=False)
    little = bool(abs(vr.loc[0, "median"]) < INTO_LITTLE)
    md += ["\n## The validity-of-mechanism rows — the CREATION row (bought at the first bar after the proposal's creation, closed at the decision bar) and the run-up over t0 − 24 h, against the members; read first, decides nothing\n",
           vr.round(1).to_markdown(index=False), "\n",
           f"\n{'The median CREATION row is inside ±100 bps: by the registration there was nothing to give back and a clear is read by rule (b)' + chr(39) + 's sentence — a ' + ('one' if gh == 288 else 'three') + '-day drift of a governed name against its peers after a scheduled hour, not the news.' if little else 'The median CREATION row is outside ±100 bps: the vote moved the name before its end.'}\n"]

    # the gate
    W = listing.weeks(t)[1]
    fam.to_csv(out / "holds.csv", index=False)
    rule = (f"CONFIRMED if M_trim ≤ −B AND |u_trim| ≥ 2 AND {fa}'s and {fb}'s trimmed means < 0; NOT CONFIRMED otherwise — under the bar when |M_trim| + 1.96 se_trim < B, the opposite sign when the mirror holds, facts beside"
            if spec.confirm else f"M_trim ≤ −B, |u_trim| ≥ 2, the hold's own p ≤ 0.05, {fa}'s and {fb}'s trimmed means < 0; CLOSED if |M_trim| + 1.96 se_trim < B")
    md += [f"\n## The gate — y = a − b, bps of the position; {len(E)} cells in {W} weeks; B {bar:.1f} (rule (a): the mean of the names' own doubled round trips on the entry day; R28's 46 beside); {DRAWS:,} draws of {BLOCK_WEEKS}-week blocks; the sign NEGATIVE; THE GATE ON THE 10 % TRIMMED MEAN OF THE {cand} HOLD ALONE ({rule}; the {od} row DESCRIBED, its `verdict` column R80's rule and not the gate) (k = {fam['k_trim'].tolist()} out at each end; the plain mean, the median, the share below zero and M without the k largest / smallest beside, deciding nothing)\n",
           fam.round(3).to_markdown(index=False), "\n", f"\n**Verdict: {verdict} — the gate hold {cand}.**\n",
           f"\nn in {fa} {int(f1.sum())}, in {fb} {int(f2.sum())}; cells per week: mean {len(E) / W:.2f}; names {E['symbol'].nunique()}.\n"]
    (out / "govevent.md").write_text("\n".join(md))                   # the read is on disk before anything is described

    # described — decides nothing
    desc, sold, ref, net = [], [], [], []
    C2 = bt.load_costs(M.index, M.columns, end, cost_mult=2.0, close=M.close)
    Ec = E.rename(columns={"symbol": "contract"})
    for h in HOLDS:
        y, d = Y[h], _days(h)
        v = y[np.isfinite(y)]
        fl = listing._priced(M, C, Ec, h, 1, taker_bps)
        desc.append({"hold": d, "median": np.median(v), "share_below_0": (v < 0).mean(), **{f"q{int(x * 100):02d}": np.quantile(v, x) for x in q}, "min": v.min(), "max": v.max(),
                     "mean_a": np.nanmean(A[h]), "mean_b": np.nanmean(P["B"][h]), "median_a": np.nanmedian(A[h]), "funding_part_of_a": float(np.nanmean(fl["funding_bps"]))})
        sold.append({"hold": d, "mean_sold": -v.mean(), "trimmed_sold": -listing.trimmed(v, fundevent.k_trim(len(v))), "mean_sold_loss_capped_at_size": np.maximum(-v, -1e4).mean(), "largest_single_loss": float(v.max()),
                     "sold_positions_losing_over_half": int((v > 5000).sum()), "share_y_over_5000": float((v > 5000).mean())})
        ref.append({"hold": d, "M_entry_a_day_later": float(np.nanmean(P["YL"][h])), "median_entry_a_day_later": float(np.nanmedian(P["YL"][h])), "M_against_BTC": float(np.nanmean(P["YB"][h])),
                    "median_against_BTC": float(np.nanmedian(P["YB"][h])), "M_a_alone": float(np.nanmean(A[h]))})
        for side, sname in ((1, "bought"), (-1, "sold")):
            for mult, CC in ((1, C), (2, C2)):
                f = listing._priced(M, CC, Ec, h, side, taker_bps)
                net.append({"hold": d, "side": sname, "cost": f"×{mult}", "n_priced": int(f["net_bps"].notna().sum()), "gross": f["gross_bps"].mean(), "fee": f["fee_bps"].mean(), "spread_impact": f["other_cost_bps"].mean(),
                            "funding": f["funding_bps"].mean(), "net": f["net_bps"].mean(), "net_median": f["net_bps"].median()})
    E.to_csv(out / "events.csv", index=False)
    splits = pd.concat([_split_rows(E, Y, k, lab) for k, lab in SPLITS.items()] + [_split_rows(E, Y, f"kind = {k}", (k, "the rest"), (E["kind"] == k).to_numpy()) for k in KINDS]
                       + [_group_rows(E, Y, "fold", "fold"), _group_rows(E, Y, "symbol", "name")], ignore_index=True)
    splits.to_csv(out / "splits.csv", index=False)
    ycols = [f"y_{_days(h)}" for h in HOLDS]
    qt = E.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")[ycols].agg(["size", "mean", "median"]).round(1)
    ext = pd.concat([E.nlargest(5, f"y_{cand}"), E.nsmallest(5, f"y_{cand}")])[["symbol", "t", "kind", "passed", "votes", "creation_y", "runup_y", *ycols]].round(0)
    hours = t.hour.value_counts().sort_index().rename("cells").to_frame()
    bdist = {"B": bar, "B_i_min": float(E["B_i"].min()), "B_i_median": float(E["B_i"].median()), "B_i_q90": float(E["B_i"].quantile(0.9)), "B_i_max": float(E["B_i"].max()), "R28_constant": krevent.BAR_R28,
             **{f"source: {k}": int(v) for k, v in E["B_source"].value_counts().items()}}
    corr = {d: float(pd.Series(iy).corr(pd.Series(Y[h]))) for d, h in zip(["1d", "3d"], HOLDS)}
    hi = iy >= np.nanmedian(iy)
    corr_split = {f"y_{cand} trimmed, CREATION row ≥ median": listing.trimmed(Y[gh][hi], fundevent.k_trim(int(np.isfinite(Y[gh][hi]).sum()))), f"y_{cand} trimmed, CREATION row < median": listing.trimmed(Y[gh][~hi], fundevent.k_trim(int(np.isfinite(Y[gh][~hi]).sum())))}
    # the SCREEN row: the gate's member cells re-cut by the member block that holds t
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    blk = starts[np.clip(starts.searchsorted(t, side="right") - 1, 0, None)]
    memb = E["member_at_t0"].to_numpy()
    scr = pd.DataFrame({"block": blk[memb], "y": Y[gh][memb]}).dropna().groupby("block")["y"].agg(["size", "mean", "median"])
    n_blocks = int(((starts >= a0) & (starts < end)).sum())
    screen = {"hold": cand, "blocks_in_window": n_blocks, "blocks_with_a_member_cell": int(len(scr)), "member_cells": int(memb.sum()), f"mean_of_block_means_{cand}": float(scr["mean"].mean()) if len(scr) else np.nan,
              f"median_of_block_means_{cand}": float(scr["mean"].median()) if len(scr) else np.nan, "blocks_with_mean_below_0": int((scr["mean"] < 0).sum())}
    scr.round(1).to_csv(out / "screen_blocks.csv")
    # the described rows (the twelve) — none expected
    drow = None
    if len(D):
        Pd = population(M, C, mem, L[L.index.isin(D.index)].reset_index(drop=True), end, first_block, taker_bps, gh)
        drow = Pd["E"][["symbol", "t0", "t", "title", *ycols, "creation_y", "runup_y", "B_i"]] if len(Pd["E"]) else None
        if drow is not None:
            drow.to_csv(out / "described_rows.csv", index=False)
    # the whole-vote cells — the same functions, a described population, never the gate
    other_md = []
    if spec.other_flag:
        Lo = L_full[L_full[spec.other_flag]].reset_index(drop=True)
        Po = population(M, C, mem, Lo, end, first_block, taker_bps, gh)
        Eo, Yo = Po["E"], Po["Y"]
        oo = out / spec.other_flag
        oo.mkdir(exist_ok=True)
        Po["E_all"].to_csv(oo / "events_all.csv", index=False)
        Eo.to_csv(oo / "events.csv", index=False)
        if len(Eo) >= 3:
            fo1, fo2 = (Eo["fold"] == fa).to_numpy(), (Eo["fold"] == fb).to_numpy()
            bar_o = float(Eo["B_i"].mean())
            famo = hold_rows(Yo, Po["t"], fo1, fo2, bar_o, spec.seed, spec.folds, gh)
            famo["verdict"] = "described: " + famo["verdict"]
            famo.to_csv(oo / "holds.csv", index=False)
            so = pd.concat([_split_rows(Eo, Yo, k, lab) for k, lab in SPLITS.items()] + [_group_rows(Eo, Yo, "fold", "fold")], ignore_index=True)
            so.to_csv(oo / "splits.csv", index=False)
            vo = Yo[gh][np.isfinite(Yo[gh])]
            cro = Eo["creation_y"].to_numpy()
            other_md = [f"\n## The whole-vote cells (`{spec.other_flag}`): {len(Eo)} cells on {Eo['symbol'].nunique()} names, B {bar_o:.1f} (own rows {float((Eo['B_source'] != 'R28' + chr(39) + 's 46').mean()):.1%}); the same trimmed statistic, se, u and p — a DESCRIBED population, never the gate; rows out: {Po['E_all'][~Po['E_all']['eligible']]['why'].value_counts().to_dict()}\n",
                        famo.round(3).to_markdown(index=False), "\n", f"\nthe CREATION row's median {float(np.nanmedian(cro)):.1f} (n {int(np.isfinite(cro).sum())}); the money of the sold unit at {cand}: mean {-vo.mean():.1f}, trimmed {-listing.trimmed(vo, fundevent.k_trim(len(vo))):.1f}, the largest single loss {float(vo.max()):.0f}\n",
                        "\nthe splits:\n", so.round(1).to_markdown(index=False), "\n"]
    counts = dict(spec.counts)
    money_md = []
    if money is not None:                                              # the money row (R81's form): described, deciding nothing
        T, TH = money
        T.to_csv(out / "trades.csv", index=False)
        TH.to_csv(out / "trades_heavy.csv", index=False)
        Hv = T["H"].to_numpy()
        ok = np.isfinite(Hv)
        hr = {"hold": cand, "n_priced": int(ok.sum()), "M_H": float(Hv[ok].mean()), "M_trim_H": listing.trimmed(Hv[ok], fundevent.k_trim(int(ok.sum()))), "median_H": float(np.median(Hv[ok])), "share_H_above_0": float((Hv[ok] > 0).mean()),
              "M_own": float(T["own"].mean()), "M_hedge": float(T["hedge"].mean()), "M_gross": float(T["gross"].mean()), "M_funding": float(T["funding"].mean()), "M_fee": float(T["fee"].mean()), "M_spread_impact": float(T["spread_impact"].mean()),
              "M_H_heavy": float(TH["H"].mean()), "M_trim_H_heavy": listing.trimmed(TH["H"].dropna().to_numpy(), fundevent.k_trim(int(TH["H"].notna().sum()))), "min_members_hedge": int(T["n_b"].min()), "largest_single_loss_H": float(-Hv[ok].min()) if ok.any() else np.nan}
        pd.DataFrame([hr]).to_csv(out / "money_row.csv", index=False)
        money_md = [f"\n## The money row — the SOLD unit through the harness at the entry day's legs × {ENTRY_MULT81} the proxy, hedged with the block's members bought (H = own + hedge, bps of the position; the heavy reading × {HEAVY81[0]} / × {HEAVY81[1]} beside), held {cand}; described, deciding nothing; no stop\n",
                    pd.DataFrame([hr]).round(1).to_markdown(index=False), "\n"]
    md += ["\n## Described — decides nothing\n",
           *money_md,
           "\nThe splits (passed / failed; the five busiest names / the rest; members at t0; the end on the hour; voters ≥ the median; each kind against the rest; the folds; each name) — the trimmed mean, the plain, the median:\n", splits.round(1).to_markdown(index=False), "\n",
           "\nThe distribution of y, and a and b apart:\n", pd.DataFrame(desc).round(1).to_markdown(index=False), "\n",
           "\nThe money of a SOLD position (−y; the trimmed beside; a loss capped at the position's size is a different rule, shown beside; a stop is not written in):\n", pd.DataFrame(sold).round(3).to_markdown(index=False), "\n",
           f"\nEach position through the harness as a taker (fee {taker_bps} bps a leg, `costwide`'s proxy and its double; the name's own legs, no benchmark):\n", pd.DataFrame(net).round(1).to_markdown(index=False), "\n",
           "\nBy calendar quarter of the entry (cells, mean, median):\n", qt.to_markdown(), "\n",
           f"\nThe five largest and the five smallest y at {cand}:\n", ext.to_markdown(index=False), "\n",
           "\nThe hour of t (UTC):\n", hours.to_markdown(), "\n",
           f"\nThe CREATION row against the drift: the correlation of creation_y with y per hold, and y_{cand}'s trimmed mean on the cells with a creation row at or above the median against the rest (a fact, not a rule):\n",
           "\n```\n" + json.dumps({"corr": corr, **corr_split}, indent=1) + "\n```\n",
           "\nThe bar: B_i's distribution and its sources:\n", "\n```\n" + json.dumps(bdist, indent=1) + "\n```\n",
           f"\nThe SCREEN row — the gate's member cells re-cut by the member block that holds t (the mean y_{cand} per block; `screen_blocks.csv`):\n", "\n```\n" + json.dumps(screen, indent=1) + "\n```\n",
           "\nThe described rows (the twelve's; none expected):\n", "none" if drow is None else drow.round(1).to_markdown(index=False), "\n",
           "\nCounts recorded, not priced:\n", "\n```\n" + json.dumps(counts, indent=1, default=str) + "\n```\n",
           "\n## Reference rows — no verdict (the entry a day later; against BTC; a alone)\n", pd.DataFrame(ref).round(1).to_markdown(index=False), "\n",
           *other_md]
    (out / "meta.json").write_text(json.dumps({"registration": spec.registration, "decision": spec.decision, "unit": bt.UNIT, "charged": bt.CHARGED, "holds": HOLDS, "gate_hold": gh, "confirm": spec.confirm, "strategy": spec.strategy, "runup": RUNUP, "bar": bar, "bar_mult": krevent.BAR_MULT,
                                                "bar_r28": krevent.BAR_R28, "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": spec.seed, "trim_frac": TRIM_FRAC, "frozen": int(len(L_full)), "flagged": int(len(L)), "cells": int(len(E)), "weeks": W,
                                                "taker_bps": taker_bps, "list_md5": list_md5, "verdict": verdict, "gate_hold_name": cand, "creation_little": little, "folds": list(spec.folds), "pad_days": spec.pad_days}, indent=1))
    text = "\n".join(md)
    (out / "govevent.md").write_text(text)
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
        sys.exit(f"govevent: unknown action {action}")
