"""P8, R85 — the exchange's OWN on-chain balance jump as a per-name event: a member SOLD at the first 5m bar closing after the day's balance
point is KNOWN (t0 + the lag), held ONE DAY against the screener's members (three days described): does it fall behind its peers?
`ft2 cexevent fingerprint|run|check` (PLAN §8 R85 is the registration, decision CL1 2026-11-09; this file is its code and changes nothing of
it — R83's `govevent.py` with the event table swapped: the FROZEN `ft2/cexflow_f12.csv`, the gate's rows the MEMBERS' INFLOW cells
(`member_at_t0`, `cell`, `side = in`), the members' OUTFLOW cells bought and the non-members' inflow cells DESCRIBED through the same functions,
the LAG row in place of the creation row, a 7-day pad, one gate hold).

gate (a)   `output/cexflow/knownat.json` from the 2026-11-13 fetch (the 09 → 13 pair) reads IDENTICAL — else the run is VOID before the
           market is loaded (the known-at probe, decision CK (cxix) / CL).
gate (b)   LAG_H — the hour the day's 00:00 point is in the adapter's file: 8 h, or 6 h if one 06:00 UTC probe (`scripts/cexflow_hourprobe.sh`)
           shows the day's point before `run`; the value must equal PLAN §8 R85's "Gate (b) line" — the chain's log prints it.
events     the FROZEN `ft2/cexflow_f12.csv` (decision CK1's audit, DATA.md `cex_balance`; md5 as registered): symbol, t0 = ts_known = the 00:00 UTC
           stamp, side, member_at_t0, cell, flag_10 / flag_20, list_commit, usd_before, chains_n, repeat_n. Nothing is added, dropped or re-dated
           here; a row the entry rule cannot hold is counted by reason — MATIC 2024-08-29's 3-day exit past F2's end is the registered drop.
entry      the decision bar is the FIRST 5m bar that closes strictly after t0 + LAG_H (08:05 UTC for a 00:00 stamp); the position is entered one
           bar later (the harness's latency).
label      R70's: a = what a long earns before trading costs with the funding it pays (`listing.label_at` = `horizon.labels`' number);
           b = the mean over the members of the block that holds t, the name itself left out (`listing.excess`); y = a − b. A sold
           position earns −y.
statistic  THE GATE ON THE 10 % TRIMMED MEAN of the 1-day hold ALONE (R77's, `fundevent.bootstrap_trimmed`: k = round(0.05 n) out at each end,
           the draw's statistic the trimmed mean, seed 85; the hold's own p, no family correction); the 3-day row described; the plain mean
           beside. The bar rule (a): B = the mean of the names' own doubled taker round trips on the t0 day (`krevent.bars_per_event`; the 7-day
           fallback, else R28's 46).
rows read  first, no gate: the RUN-UP (y over t0 − 24 h → the decision bar: the deposit's day plus the lag hours) and the LAG row (y from the
first      first bar closing after t0 to the decision bar: what moved before anyone could know).
validity   (0) gate (a) and gate (b); (1) the archive slice's fingerprint before (`fingerprint`) and after (`check`); (2) the list's md5, 1,159 rows
           and 121 gate rows, every row re-derived by `cexflow.events()` from the parquet on disk; (3) exactly the named rows out, ≥ 115 cells,
           ≥ 90 % with their own cost row; (4) bars and labels ≥ 95 %; (5) members ≥ 40 on every cell and on the run-up and lag rows; (6) the
           label identity with `horizon.labels` and the harness, the trimmed identity with `listing.trimmed`; (7) every cell's decision bar
           closes after t0 + the lag and within 5 min of it; the lag row's entry bar closes after t0.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import cexflow, fundevent, govevent, horizon, krevent, krw, listing, universe
from .ceiling import BAR
from .govevent import HOLDS, _group_rows, _split_rows, gate_verdict, hold_rows
from .upgevent import ENTRY_MULT81, HEAVY81, decision_close, entries, label_pair, money_row

NAME = "r85"
OUT = listing.OUT                                  # output/listing
LIST = cexflow.LISTS["f12"]
LIST_MD5 = "21789095c70d8f927d6fe5aa36981721"      # as frozen b2e7671 and registered (PLAN §8 R85)
LIST_ROWS = 1159
GATE_ROWS = 121                                    # the members' inflow cells of F1+F2: 23 names, F1 65 / F2 56
OUTFLOW_ROWS, NONMEMBER_ROWS = 96, 211             # the described populations (the mirror bought; the non-members' inflow cells on the cells with bars)
FOLDS = ("F1", "F2")
GATE_HOLD = 288                                    # 1 day THE GATE; 3 days (HOLDS[1]) described
LAG_H = 6                                          # gate (b): the hour the day's point is known — PLAN §8 R85's "Gate (b) line"; 6 by the 06:00 UTC probe of 2026-11-11 (8 before it)
LAG_ALLOWED = (6, 8)
LATE = 288                                         # reference row: the entry a day later
TAKER_BPS = 5.0
BLOCK_WEEKS, DRAWS, SEED = 6, 10_000, 85
TRIM_FRAC = fundevent.TRIM_FRAC
MIN_MEMBERS, MIN_ELIGIBLE, MIN_OWN_COST, MIN_BARS, MIN_LABELS = 40, 115, 0.90, 0.95, 0.95
PAD_DAYS = 7                                       # the market from the folds' start minus 7 days: the run-up row needs the day before t0; no creation row
DESCRIBED = tuple(krw.TWELVE)                      # the twelve's rows would be described, never cells (none in the gate's rows: non-members or excluded)
EXPECTED_DESCRIBED: set = set()
EXPECTED_DROPPED: set = set()                      # no row dropped at 1d by the window's two ends
EXPECTED_3D_DROPPED = {("MATICUSDT", "2024-08-29 00:00:00+00:00")}   # the described hold's label past F2's end, counted
BTC = "BTCUSDT"
TOP5 = ("AXSUSDT", "TRXUSDT", "MKRUSDT", "1000FLOKIUSDT", "APEUSDT")   # 61 of the 121
SPLITS = {"flag_10": ("|change| ≥ 10 %", "5 … 10 %"), "flag_20": ("|change| ≥ 20 %", "under 20 %"), "list_commit": ("a wallet-list commit day", "no commit"),
          "revert_3d": ("the balance back within 3 stamps (post-t0)", "not reverted"), "top5": ("the five busiest names", "the rest"),
          "big_usd": ("usd_before ≥ the median", "below"), "multi_chain": ("more than one chain", "one chain"), "repeat": ("a repeat jump of the series", "the first jump")}
RUNUP_LITTLE = 100.0                               # the run-up's median inside ±this: nothing to give back (recorded beside the verdict)
KNOWNAT = cexflow.OUT / "knownat.json"             # gate (a)'s file
KNOWNAT_MIN_DATE = pd.Timestamp("2026-11-13", tz="UTC")
EVENTS_CSV = cexflow.OUT / "events.csv"            # `revert_3d` (post-t0, described) lives here, never in the frozen list
F34_ROWS, F34_GATE, F34_WITH_BARS, F5_ROWS, F5_GATE = 2955, 184, 181, 4234, 11
COUNTS85 = {"frozen rows of cexflow_f34.csv (untouched here)": F34_ROWS, "of them the members' inflow cells (F3+F4)": F34_GATE, "of them with bars": F34_WITH_BARS,
            "F5 listed, not frozen": F5_ROWS, "of them the members' inflow cells (F5)": F5_GATE}

# R94 — the confirmation read on the frozen F3+F4 list (decision CM1, PLAN §8 R94): R85's path with the Spec swapped — BOTH sides' member cells,
# each SOLD, the 3-day hold THE GATE (hindsight-generated on R85's described rows), the F3+F4 members, the checks that read no bar made BEFORE
# the guard rows (R94, F3) / (R94, F4), the verdict with both folds AND both sides negative, the money row described.
NAME94 = "r94"
LIST34 = cexflow.LISTS["f34"]
LIST34_MD5 = "05209c7d0a2c55120fc9f1048b73848b"    # as frozen b2e7671 and registered (PLAN §8 R94)
LIST34_ROWS = 2955
POP_ROWS94 = 336                                   # the members' cells, in 184 + out 152
EXCLUDED94 = ("MATICUSDT",)                        # out by name: the perpetual's bars end 2024-09-11 09:45 UTC (six rows) — reported, never priced
GATE_ROWS94 = 330                                  # the population without MATIC's six
FOLDS34 = ("F3", "F4")
SEED94 = 94
GATE_HOLD94 = 864                                  # 3 days THE GATE; 1 day described
EXPECTED_DROPPED94 = {("XLMUSDT", "2025-12-29 00:00:00+00:00"), ("XLMUSDT", "2025-12-30 00:00:00+00:00"), ("DOTUSDT", "2025-12-31 00:00:00+00:00"),
                      ("PUMPUSDT", "2025-12-31 00:00:00+00:00")}   # the 3-day exit not before 2026-01-01: 326 cells
MIN_ELIGIBLE94 = 310
STRATEGY94 = "cex_sold_3d"
TOP5_94 = ("XLMUSDT", "FARTCOINUSDT", "SUIUSDT", "TONUSDT", "1000FLOKIUSDT")   # 134 of the 336
SPLITS94 = {**SPLITS, "side_in": ("the balance ROSE (inflow)", "the balance FELL (outflow)"), "near7": ("another cell of the name within the 7 days before", "none")}
COUNTS94 = {"frozen rows of cexflow_f34.csv": LIST34_ROWS, "of them the members' cells, both sides (the population)": POP_ROWS94, "the other rows (non-members, non-cells) — untouched": LIST34_ROWS - POP_ROWS94,
            "F5 listed, not frozen — untouched": F5_ROWS}


@dataclasses.dataclass
class Spec:
    registration: str
    decision: str
    title: str
    list_path: Path
    list_md5: str
    list_rows: int
    gate_rows: int
    folds: tuple[str, str]
    members_csv: Path | None
    seed: int
    lag_h: int
    expected_described: set
    expected_dropped: set
    expected_other_dropped: set
    min_eligible: int
    pad_days: int
    gate_hold: int = GATE_HOLD
    top5: tuple[str, ...] = TOP5
    counts: dict = dataclasses.field(default_factory=lambda: dict(COUNTS85))
    knownat: Path = KNOWNAT
    knownat_min_date: pd.Timestamp = KNOWNAT_MIN_DATE
    sides: tuple[str, ...] = ("in",)               # the gate's sides (R94: both, each sold)
    confirm: bool = False                          # R94: the pre-guard checks, the guard rows, `confirm_verdict94`, the sides' rows, the money row
    strategy: str | None = None
    excluded: tuple[str, ...] = ()                 # names out of the population by the registration (reported, never priced)
    pop_rows: int | None = None                    # the population before `excluded`
    splits: dict = dataclasses.field(default_factory=lambda: dict(SPLITS))


def spec_r85() -> Spec:
    """Read at call time, so a test's monkeypatch of the module's constants applies."""
    return Spec("R85", "CL1", "R85 — the exchange's own balance jump: a member sold at the first bar after the day's point is known (t0 + the lag), 1 day against the members (`ft2 cexevent run`)",
                LIST, LIST_MD5, LIST_ROWS, GATE_ROWS, FOLDS, None, SEED, LAG_H, EXPECTED_DESCRIBED, EXPECTED_DROPPED, EXPECTED_3D_DROPPED, MIN_ELIGIBLE, PAD_DAYS, GATE_HOLD, TOP5, dict(COUNTS85), KNOWNAT, KNOWNAT_MIN_DATE)


def spec_r94() -> Spec:
    return Spec("R94", "CM1", "R94 — the confirmation read of the exchange-balance kind: a member whose balance moved ≥ 5 % either way sold at t0 + the lag, 3 days (hindsight-generated) against the F3+F4 members (`ft2 cexevent run --name r94`)",
                LIST34, LIST34_MD5, LIST34_ROWS, GATE_ROWS94, FOLDS34, universe.F34_MEMBERS_CSV, SEED94, LAG_H, set(), EXPECTED_DROPPED94, set(), MIN_ELIGIBLE94, PAD_DAYS, GATE_HOLD94, TOP5_94, dict(COUNTS94),
                KNOWNAT, KNOWNAT_MIN_DATE, ("in", "out"), True, STRATEGY94, EXCLUDED94, POP_ROWS94, dict(SPLITS94))


def confirm_verdict94(m_trim: float, se_trim: float, u_trim: float, p: float, m_fa: float, m_fb: float, m_in: float, m_out: float, bar: float) -> str:
    """R94's gate on the one hold: CONFIRMED if M_trim ≤ −B, |u_trim| ≥ 2, p ≤ 0.05, both folds' trimmed means < 0 AND both sides' < 0."""
    if m_trim <= -bar and abs(u_trim) >= 2 and p <= 0.05 and m_fa < 0 and m_fb < 0 and m_in < 0 and m_out < 0:
        return "CONFIRMED"
    if m_trim >= bar and abs(u_trim) >= 2:
        return "NOT CONFIRMED — the opposite sign"
    if abs(m_trim) + 1.96 * se_trim < bar:
        return "NOT CONFIRMED — under the bar"
    return "NOT CONFIRMED"


SPECS = {NAME: spec_r85, NAME94: spec_r94}


def _days(h: int) -> str:
    return f"{h // 288}d"


# ---- the frozen events ----------------------------------------------------------------------------------------------------------
def load_events(path: Path | str = LIST, top5: tuple[str, ...] = TOP5, events_csv: Path | None = None, sides: tuple[str, ...] = ("in",)) -> pd.DataFrame:
    L = pd.read_csv(path)
    for c in ("t0", "ts_known", "release", "block", "perp_first"):
        L[c] = pd.to_datetime(L[c], utc=True, format="ISO8601")
    for c in ("cell", "member_at_t0", "flag_10", "flag_20", "list_commit"):
        L[c] = L[c].astype(str).str.lower().eq("true")
    L["gate"] = L["member_at_t0"] & L["cell"] & L["side"].isin(sides)
    L["side_in"] = L["side"] == "in"
    mc = L[L["member_at_t0"] & L["cell"]].sort_values(["symbol", "t0"])                   # a member cell with another (either side) of its name in the 7 days before
    L["near7"] = (mc.groupby("symbol")["t0"].diff() < pd.Timedelta(days=7)).reindex(L.index, fill_value=False)
    L["outflow"] = L["member_at_t0"] & L["cell"] & (L["side"] == "out")
    L["nonmember_in"] = ~L["member_at_t0"] & L["cell"] & (L["side"] == "in")
    L["top5"] = L["symbol"].isin(top5)
    L["big_usd"] = L["usd_before"] >= L.loc[L["gate"], "usd_before"].median()
    L["multi_chain"] = L["chains_n"] > 1
    L["repeat"] = L["repeat_n"] > 0
    ev = events_csv if events_csv is not None else EVENTS_CSV
    L["revert_3d"] = False
    L["revert_source"] = "skipped: no events.csv"
    if Path(ev).exists():
        R = pd.read_csv(ev, usecols=["code", "symbol", "revert_3d"]).drop_duplicates(["code", "symbol"])
        m = L.merge(R, on=["code", "symbol"], how="left", suffixes=("", "_ev"))
        L["revert_3d"] = m["revert_3d_ev"].astype(str).str.lower().eq("true").to_numpy()
        L["revert_source"] = str(ev)
    return L


def rederived(L: pd.DataFrame) -> dict:
    """Validity (2): every frozen row's t0, symbol, side and `cell` flag are what `cexflow.events`' rule gives from the parquet on disk today."""
    try:
        E = cexflow.events(write=False)
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
        elif E.loc[k, "side"] != r.side or bool(E.loc[k, "cell"]) != bool(r.cell):
            bad.append({"code": r.code, "symbol": r.symbol, "why": "the side or the cell flag differs"})
    return {"status": "PASS" if not bad else "FAIL", "rows": int(len(L)), "bad": bad}


def knownat_gate(path: Path, min_date: pd.Timestamp) -> dict:
    """Gate (a): the known-at probe's verdict file — IDENTICAL, nothing differing, no stamp removed, and the newer file fetched on or after the
    registered day (the date in its name)."""
    if not Path(path).exists():
        return {"status": "FAIL", "why": f"no {path} — the 2026-11-13 fetch and `ft2 cexflow knownat` first"}
    k = json.loads(Path(path).read_text())
    files = k.get("files", [])
    m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{8})", Path(files[-1]).name) if files else None
    newer = pd.Timestamp(m.group(1), tz="UTC") if m else pd.NaT
    ok = str(k.get("verdict", "")).startswith("IDENTICAL") and k.get("differ", 1) == 0 and not k.get("stamps_only_in_older") and len(files) == 2 and pd.notna(newer) and newer >= min_date
    return {"status": "PASS" if ok else "FAIL", "verdict": k.get("verdict"), "differ": k.get("differ"), "stamps_only_in_older": k.get("stamps_only_in_older"), "files": files,
            "newer_file_date": str(newer.date()) if pd.notna(newer) else None, "min_date": str(min_date.date()), "in_both": k.get("in_both"), "live_point_older": k.get("live_point_older")}


# ---- a population through the frame -------------------------------------------------------------------------------------------------
def population(M: bt.Market, C: bt.Costs, mem: pd.DataFrame, L: pd.DataFrame, end: pd.Timestamp, first_block: pd.Timestamp, taker_bps: float, lag_h: int, gate_hold: int = GATE_HOLD) -> dict:
    """The entries at t0 + the lag, the labels at both holds, the run-up and lag rows, the reference rows and the bars for the rows of one population."""
    lag = pd.Timedelta(hours=lag_h)
    Ls = L.copy()
    Ls["t0_frozen"] = Ls["t0"]
    Ls["t0"] = Ls["t0"] + lag                                      # the decision is taken when the point is KNOWN
    Ls["ts_known"] = Ls["t0"]
    E_all = entries(M, Ls, end, first_block, longest=gate_hold, described=DESCRIBED)
    E_all["why"] = E_all["why"].str.replace("the 7-day exit", f"the {_days(gate_hold)} exit", regex=False)
    E_all["eligible"] = E_all["why"] == ""
    E_all["t0"] = E_all["t0_frozen"]                               # the frozen t0 back in its column; t_known beside
    E_all["t_known"] = E_all["t0"] + lag
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
    runup = 288 + 12 * lag_h + 1                                  # from the bar closing at t0 − 24 h to the decision bar
    ru = listing.excess(listing.label_at(close, fv, rows - runup - bt.LATENCY, runup), own, mask)
    e_lag = np.array([int(M.index.get_indexer([decision_close(x)])[0]) for x in pd.DatetimeIndex(E["t0"])]) if len(E) else np.array([], dtype=int)   # the first bar closing after t0 (00:05)
    lagrow = listing.excess(label_pair(close, fv, e_lag, rows), own, mask)                                   # from the stamp's first bar to the decision bar, no latency
    bars = krevent.bars_per_event(C, own, t, taker_bps)
    for h in HOLDS:
        d = _days(h)
        E[f"a_{d}"], E[f"b_{d}"], E[f"n_b_{d}"], E[f"y_{d}"], E[f"y_late_{d}"], E[f"y_btc_{d}"] = A[h], B[h], NB[h], Y[h], YL[h], YB[h]
    E["runup_a"], E["runup_b"], E["runup_y"] = ru[0], ru[1], ru[0] - ru[1]
    E["lag_a"], E["lag_b"], E["lag_y"] = lagrow[0], lagrow[1], lagrow[0] - lagrow[1]
    E["lag_row"] = e_lag
    E = pd.concat([E, bars], axis=1)
    return {"E_all": E_all, "E": E, "A": A, "B": B, "NB": NB, "Y": Y, "YL": YL, "YB": YB, "ru": ru, "lagrow": lagrow, "rows": rows, "own": own, "t": t, "mask": mask}


def _desc_population(M, C, mem, L, end, first_block, taker_bps, spec, out: Path, label: str, sign_note: str) -> list[str]:
    """A described population through the same functions — the trimmed statistic, se, u and p, the splits, the money of the unit; never the gate."""
    gh = spec.gate_hold
    fa, fb = spec.folds
    P = population(M, C, mem, L, end, first_block, taker_bps, spec.lag_h, gh)
    E, Y = P["E"], P["Y"]
    out.mkdir(exist_ok=True)
    P["E_all"].to_csv(out / "events_all.csv", index=False)
    E.to_csv(out / "events.csv", index=False)
    why = P["E_all"][~P["E_all"]["eligible"]]["why"].value_counts().to_dict()
    if len(E) < 3:
        return [f"\n## {label}: {len(E)} cells with bars of {len(L)} frozen rows — too few to describe; rows out: {why}\n"]
    f1, f2 = (E["fold"] == fa).to_numpy(), (E["fold"] == fb).to_numpy()
    bar = float(E["B_i"].mean())
    fam = hold_rows(Y, P["t"], f1, f2, bar, spec.seed, spec.folds, gh)
    fam["verdict"] = "described: " + fam["verdict"]
    fam.to_csv(out / "holds.csv", index=False)
    sp = pd.concat([_split_rows(E, Y, k, lab) for k, lab in SPLITS.items()] + [_group_rows(E, Y, "fold", "fold"), _group_rows(E, Y, "symbol", "name")], ignore_index=True)
    sp.to_csv(out / "splits.csv", index=False)
    v = Y[gh][np.isfinite(Y[gh])]
    return [f"\n## {label}: {len(E)} cells on {E['symbol'].nunique()} names of {len(L)} frozen rows, B {bar:.1f} (own rows {float((E['B_source'] != 'R28' + chr(39) + 's 46').mean()):.1%}); {sign_note}; the same trimmed statistic, se, u and p — a DESCRIBED population, never the gate; rows out: {why}\n",
            fam.round(3).to_markdown(index=False), "\n",
            f"\nthe run-up's median {float(np.nanmedian(E['runup_y'])):.1f}, the lag row's median {float(np.nanmedian(E['lag_y'])):.1f}; the unit at {_days(gh)}: mean y {v.mean():.1f}, trimmed {listing.trimmed(v, fundevent.k_trim(len(v))):.1f}, the largest |y| {float(np.abs(v).max()):.0f}\n",
            "\nthe splits:\n", sp.round(1).to_markdown(index=False), "\n"]


def run(name: str = NAME, taker_bps: float = TAKER_BPS, spec: Spec | None = None) -> str:
    spec = spec or SPECS.get(name, spec_r85)()
    fa, fb = spec.folds
    gh = spec.gate_hold
    oh = [h for h in HOLDS if h != gh][0]
    cand, od = _days(gh), _days(oh)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    # validity (0) — gate (a) and gate (b), BEFORE the market is loaded
    ka = knownat_gate(spec.knownat, spec.knownat_min_date)
    V0 = {"0_gate_a_knownat": ka, "0_gate_b_lag_h": spec.lag_h, "0_gate_b_lag_allowed": spec.lag_h in LAG_ALLOWED}
    print(f"gate (a): {ka['status']} — {ka.get('verdict', ka.get('why'))}; gate (b): the lag {spec.lag_h} h (PLAN §8 R85's Gate (b) line must say the same)", flush=True)
    if ka["status"] != "PASS" or not V0["0_gate_b_lag_allowed"]:
        V0["status"] = "FAIL"
        (out / "validity.json").write_text(json.dumps(V0, indent=1, default=str))
        md = f"# {spec.title}\n\n## Validity: FAIL at gate (a) / (b) — the market was NOT loaded\n\n```\n{json.dumps(V0, indent=1, default=str)}\n```\n\n**VOID — the known-at gate did not pass; nothing was read.**\n"
        (out / "cexevent.md").write_text(md)
        return md
    L_full = load_events(spec.list_path, spec.top5, sides=spec.sides)
    list_md5 = krevent.md5(spec.list_path)
    L_pop = L_full[L_full["gate"]].reset_index(drop=True)
    L = L_pop[~L_pop["symbol"].isin(spec.excluded)].reset_index(drop=True)
    Lx = L_pop[L_pop["symbol"].isin(spec.excluded)].reset_index(drop=True)
    red = rederived(L_full)
    fp_before, _ = krevent.fp_paths(name)
    guard = None
    if spec.confirm:
        # the checks that read no bar, BEFORE the guard rows: a failure here voids without spending the folds
        pre = {"2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == spec.list_md5, "2_list_rows": int(len(L_full)), "2_population_rows": int(len(L_pop)), "2_gate_rows": int(len(L)),
               "2_rederived": red, "1_fingerprint_before": "saved" if fp_before.exists() else "MISSING"}
        if not (pre["2_list_md5_as_registered"] and len(L_full) == spec.list_rows and len(L_pop) == spec.pop_rows and len(L) == spec.gate_rows and red.get("status") == "PASS" and fp_before.exists()):
            V0 = {**V0, **pre, "status": "FAIL"}
            (out / "validity.json").write_text(json.dumps(V0, indent=1, default=str))
            md = f"# {spec.title}\n\n## Validity: FAIL before the guard rows — the market was NOT loaded and the folds are NOT spent\n\n```\n{json.dumps(V0, indent=1, default=str)}\n```\n\n**VOID — a check that reads no bar failed; no guard row was written, nothing was read.**\n"
            (out / "cexevent.md").write_text(md)
            return md
        conf = bt._guard(spec.folds, spec.registration)
        params = {"holds": [gh], "stop": None, "entry_mult": ENTRY_MULT81, "heavy": list(HEAVY81), "list": spec.list_path.name, "list_md5": list_md5, "rows": int(len(L_full)), "sides": list(spec.sides), "gate_rows": int(len(L)), "lag_h": spec.lag_h}
        stamp = krevent.guard_rows(bt.READS, conf, spec.registration, spec.strategy, params)
        guard = {"status": "PASS", "appended_at": stamp, "ledger": str(bt.READS), "folds": list(conf), "logged_as": spec.registration, "strategy": spec.strategy}
        print(f"guard: ({spec.registration}, {', '.join(conf)}) appended to {bt.READS} at {stamp}; the {fa}+{fb} market is loaded now", flush=True)
    a0, end = listing.window(spec.folds)
    mem = universe.members(spec.members_csv)
    first_block = mem["block"].min()
    syms = list(dict.fromkeys([*(L_pop if spec.confirm else L_full)["symbol"].dropna(), *universe.screen_symbols(spec.members_csv), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=spec.pad_days))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close = M.close.to_numpy()
    P = population(M, C, mem, L, end, first_block, taker_bps, spec.lag_h, gh)
    E_all, E, A, NB, Y = P["E_all"], P["E"], P["A"], P["NB"], P["Y"]
    rows, own, t = P["rows"], P["own"], P["t"]
    ru_nb, lag_nb = P["ru"][2], P["lagrow"][2]
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
    D = E_all[E_all["described"]]
    desc_set = {(r.symbol, str(r.t0)) for r in D.itertuples(index=False)}
    drop = E_all[~E_all["eligible"] & ~E_all["described"]]
    drop_set = {(r.symbol, str(r.t0)) for r in drop.itertuples(index=False)}
    y3 = Y[oh]
    d3_set = {(s, str(t0)) for s, t0, v in zip(E["symbol"], E["t0"], y3) if not np.isfinite(v)}
    t_known = pd.DatetimeIndex(E["t_known"]) if len(E) else pd.DatetimeIndex([])
    lag_ok = np.isfinite(E["lag_y"].to_numpy()) if len(E) else np.array([], dtype=bool)
    ru_ok = np.isfinite(E["runup_y"].to_numpy()) if len(E) else np.array([], dtype=bool)
    V = {**V0,
         "1_fingerprint_before": "saved" if fp_before.exists() else "MISSING", "1_fingerprint_after": "pending → `ft2 cexevent check` after the run",
         "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == spec.list_md5, "2_list_rows": int(len(L_full)), "2_gate_rows": int(len(L)), "2_rederived": red,
         "3_frozen_gate_rows": int(len(L)), "3_cells": int(len(E)), "3_described": sorted(desc_set), "3_described_as_registered": desc_set == spec.expected_described,
         "3_dropped": {f"{s} {t0}": w for s, t0, w in zip(drop["symbol"], drop["t0"].astype(str), drop["why"])}, "3_dropped_as_registered": drop_set == spec.expected_dropped,
         f"3_{od}_label_dropped": sorted(d3_set), f"3_{od}_dropped_as_registered": d3_set == spec.expected_other_dropped,
         "3_own_cost_row_share": float((E["B_source"] != "R28's 46").mean()) if len(E) else 0.0, "3_B_source": E["B_source"].value_counts().to_dict(),
         "3_at_46": sorted(E[E["B_source"] == "R28's 46"]["symbol"].unique().tolist()),
         "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_events_under_95pct_bars": int(sum(s < MIN_BARS for s in span)),
         "4_label_share": {_days(h): float(np.isfinite(Y[h]).sum() / max(len(E) - (len(d3_set & spec.expected_other_dropped) if h == oh else 0), 1)) if len(E) else 0.0 for h in HOLDS},   # the registered other-hold drops counted, not failed
         "5_min_members": {_days(h): int(NB[h][np.isfinite(Y[h])].min()) if np.isfinite(Y[h]).any() else 0 for h in HOLDS},
         "5_min_members_runup": int(ru_nb[ru_ok].min()) if ru_ok.any() else 0, "5_min_members_lag": int(lag_nb[lag_ok].min()) if lag_ok.any() else 0,
         "5_runup_rows_dropped": int((~ru_ok).sum()), "5_lag_rows_dropped": int((~lag_ok).sum()),
         "6_identity_max_abs_diff": {_days(h): ident[h][:2] for h in HOLDS}, "6_same_cells": all(ident[h][2] for h in HOLDS),
         "7_decision_after_t0_plus_lag": bool((t > t_known).all()) if len(E) else False, "7_decision_within_5min_of_t0_plus_lag": bool(((t - t_known) <= BAR).all()) if len(E) else False,
         "7_lag_row_entry_after_t0": bool((M.index[E["lag_row"].to_numpy()] > pd.DatetimeIndex(E["t0"])).all()) if len(E) else False,
         "7_lag_row_entry_before_decision": bool((E["lag_row"].to_numpy() < rows).all()) if len(E) else False,
         "revert_source": str(L_full["revert_source"].iloc[0]) if len(L_full) else None}
    money = None
    if spec.confirm:
        V["0_guard"] = guard
        V["2_population_rows"] = int(len(L_pop))
        # the names out by the registration: what the bars say of them — reported, never priced; a finite gate-hold label is a void (the count was wrong)
        xr, x_finite = {}, 0
        if len(Lx):
            Lxs = Lx.assign(t0=Lx["t0"] + pd.Timedelta(hours=spec.lag_h))
            Lxs["ts_known"] = Lxs["t0"]
            Ex = entries(M, Lxs, end, first_block, longest=gh, described=DESCRIBED)
            for r_, t0_ in zip(Ex.itertuples(index=False), Lx["t0"]):
                fin = False
                if r_.why == "":
                    fin = bool(np.isfinite(listing.label_at(close, C.fundval, np.array([r_.row]), gh)[0, M.columns.get_loc(r_.symbol)]))
                x_finite += fin
                xr[f"{r_.symbol} {t0_} {r_.side}"] = (r_.why or "a decision and an entry bar") + ("; a FINITE gate-hold label" if fin else "; no gate-hold label")
        V["3_excluded_by_name"] = xr
        V["3_excluded_with_a_finite_label"] = int(x_finite)
        T, TH, d6m = money_row(M, C, E, P["mask"], taker_bps, gh) if len(E) else (pd.DataFrame(), pd.DataFrame(), {"sold_gross_funding_vs_minus_a": np.inf, "hold_is_the_gate_hold": False, "no_stop": False, "n_priced": 0, "n": 0})
        V["6_money_row_identity"] = d6m
        V["7_exits_at_or_after_end"] = int((pd.DatetimeIndex(T["exit_t"]) >= end).sum()) if len(T) else 0
        money = (T, TH)
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L_full) == spec.list_rows and len(L) == spec.gate_rows and red.get("status") == "PASS"
                             and V["3_described_as_registered"] and V["3_dropped_as_registered"] and V[f"3_{od}_dropped_as_registered"] and len(E) >= spec.min_eligible
                             and V["3_own_cost_row_share"] >= MIN_OWN_COST
                             and V["4_events_under_95pct_bars"] == 0 and min(V["4_label_share"].values()) >= MIN_LABELS
                             and min(V["5_min_members"].values()) >= MIN_MEMBERS and V["5_min_members_runup"] >= MIN_MEMBERS and V["5_min_members_lag"] >= MIN_MEMBERS
                             and V["5_runup_rows_dropped"] == 0 and V["5_lag_rows_dropped"] == 0
                             and max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_same_cells"]
                             and V["7_decision_after_t0_plus_lag"] and V["7_decision_within_5min_of_t0_plus_lag"] and V["7_lag_row_entry_after_t0"] and V["7_lag_row_entry_before_decision"]
                             and (not spec.confirm or (V["3_excluded_with_a_finite_label"] == 0 and V["6_money_row_identity"]["sold_gross_funding_vs_minus_a"] <= 1e-9 and V["6_money_row_identity"]["hold_is_the_gate_hold"]
                                                       and V["6_money_row_identity"]["no_stop"] and V["7_exits_at_or_after_end"] == 0))) else "FAIL"
    E_all.to_csv(out / "events_all.csv", index=False)
    md = [f"# {spec.title}\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {M.index[0]:%Y-%m-%d} → {M.index[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{spec.list_path.name}` md5 {list_md5}, the gate's rows (member, cell, in) {len(L)} · the lag {spec.lag_h} h (the decision bar closes at {spec.lag_h:02d}:05 UTC)\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 cexevent check`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nRows by what became of them:\n", E_all["why"].replace("", "cell").value_counts().rename("rows").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the validity rows and the gate are not computed." + (" The guard rows stand in the ledger: the folds are read for this question." if spec.confirm else "") + "**\n"]
        (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
        (out / "cexevent.md").write_text("\n".join(md))
        return "\n".join(md)
    f1, f2 = (E["fold"] == fa).to_numpy(), (E["fold"] == fb).to_numpy()
    fam = hold_rows(Y, t, f1, f2, bar, spec.seed, spec.folds, gh)
    g = fam[fam["gate"]].iloc[0]
    verdict = gate_verdict(g)
    sides_md = []
    if spec.confirm:                                                   # the sides apart: their trimmed means' signs are two of the gate's conditions
        s_in = E["side_in"].to_numpy(bool)
        m_side = {nm: listing.trimmed(Y[gh][mk], fundevent.k_trim(int(np.isfinite(Y[gh][mk]).sum()))) for nm, mk in (("in", s_in), ("out", ~s_in))}
        verdict = confirm_verdict94(float(g["M_trim"]), float(g["se_trim"]), float(g["u_trim"]), float(g["p_trim"]), float(g[f"M_trim_{fa}"]), float(g[f"M_trim_{fb}"]), m_side["in"], m_side["out"], bar)
        st = []
        for nm, mk in (("in", s_in), ("out", ~s_in)):
            fs = hold_rows({h: Y[h][mk] for h in HOLDS}, t[mk], f1[mk], f2[mk], float(E.loc[mk, "B_i"].mean()), spec.seed, spec.folds, gh)
            fs.insert(0, "side", nm)
            fs["verdict"] = "described: " + fs["verdict"]
            st.append(fs)
        st = pd.concat(st, ignore_index=True)
        st.to_csv(out / "sides.csv", index=False)
        sides_md = [f"\n## The sides apart (every cell SOLD) — the gate reads only the SIGN of each side's trimmed mean at {cand}: in {m_side['in']:.1f}, out {m_side['out']:.1f}; the rest of the table described\n", st.round(3).to_markdown(index=False), "\n"]
    V["6_trimmed_identity_max"] = float(fam["trim_identity"].max())
    if V["6_trimmed_identity_max"] > 1e-9:
        verdict, V["status"] = "VOID", "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))

    # the validity-of-mechanism rows — read first, no gate
    q = [0.05, 0.25, 0.5, 0.75, 0.95]

    def desc_row(group: str, v: np.ndarray, extra: dict | None = None) -> dict:
        v = v[np.isfinite(v)]
        r = {"group": group, "n": int(len(v)), "median": float(np.median(v)) if len(v) else np.nan, "mean": float(v.mean()) if len(v) else np.nan,
             **{f"q{int(x * 100):02d}": float(np.quantile(v, x)) if len(v) else np.nan for x in q}, "share_above_0": float((v > 0).mean()) if len(v) else np.nan}
        return {**r, **(extra or {})}

    ry, ly = E["runup_y"].to_numpy(), E["lag_y"].to_numpy()
    vrows = [desc_row("RUN-UP t0 − 24 h → the decision bar: all", ry, {"median_a": float(np.nanmedian(E["runup_a"])), "median_b": float(np.nanmedian(E["runup_b"]))}),
             desc_row("LAG row t0 + 5 min → the decision bar: all", ly, {"median_a": float(np.nanmedian(E["lag_a"])), "median_b": float(np.nanmedian(E["lag_b"]))})]
    for key, labels in spec.splits.items():
        for v in (True, False):
            m = (E[key].astype(bool) == v).to_numpy()
            vrows.append(desc_row(f"RUN-UP: {key} = {labels[0 if v else 1]}", ry[m]))
            vrows.append(desc_row(f"LAG row: {key} = {labels[0 if v else 1]}", ly[m]))
    vr = pd.DataFrame(vrows)
    vr.to_csv(out / "runup.csv", index=False)
    little = bool(abs(vr.loc[0, "median"]) < RUNUP_LITTLE)
    md += ["\n## The validity-of-mechanism rows — the RUN-UP (a long over t0 − 24 h → the decision bar: the deposit's day plus the lag hours) and the LAG row (the first bar after the stamp → the decision bar: what moved before anyone could know), against the members; read first, decides nothing\n",
           vr.round(1).to_markdown(index=False), "\n",
           f"\n{'The median RUN-UP is inside ±100 bps: by the registration there was nothing to give back and a clear is read by rule (b)' + chr(39) + 's sentence — a one-day drift of a member against its peers after a day its exchange balance jumped, not a sale observed.' if little else 'The median RUN-UP is outside ±100 bps: the name moved against its peers on the deposit' + chr(39) + 's day.'}\n"]

    # the gate
    W = listing.weeks(t)[1]
    fam.to_csv(out / "holds.csv", index=False)
    rule = (f"CONFIRMED if M_trim ≤ −B AND |u_trim| ≥ 2 AND p ≤ 0.05 AND {fa}'s and {fb}'s trimmed means < 0 AND the inflow cells' and the outflow cells' trimmed means < 0; NOT CONFIRMED otherwise"
            if spec.confirm else f"M_trim ≤ −B, |u_trim| ≥ 2, the hold's own p ≤ 0.05, {fa}'s and {fb}'s trimmed means < 0; CLOSED if |M_trim| + 1.96 se_trim < B (unreachable here)")
    md += [f"\n## The gate — y = a − b, bps of the position; {len(E)} cells in {W} weeks; B {bar:.1f} (rule (a): the mean of the names' own doubled round trips on the t0 day; R28's 46 beside); {DRAWS:,} draws of {BLOCK_WEEKS}-week blocks; the sign NEGATIVE; THE GATE ON THE 10 % TRIMMED MEAN OF THE {cand} HOLD ALONE ({rule}; the {od} row DESCRIBED, its `verdict` column R80's rule and not the gate) (k = {fam['k_trim'].tolist()} out at each end; the plain mean, the median, the share below zero and M without the k largest / smallest beside, deciding nothing)\n",
           fam.round(3).to_markdown(index=False), "\n", f"\n**Verdict: {verdict} — the gate hold {cand}.**\n",
           f"\nn in {fa} {int(f1.sum())}, in {fb} {int(f2.sum())}; cells per week: mean {len(E) / W:.2f}; names {E['symbol'].nunique()}.\n", *sides_md]
    (out / "cexevent.md").write_text("\n".join(md))                   # the read is on disk before anything is described

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
    splits = pd.concat([_split_rows(E, Y, k, lab) for k, lab in spec.splits.items()] + [_group_rows(E, Y, "fold", "fold"), _group_rows(E, Y, "symbol", "name")], ignore_index=True)
    splits.to_csv(out / "splits.csv", index=False)
    ycols = [f"y_{_days(h)}" for h in HOLDS]
    qt = E.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")[ycols].agg(["size", "mean", "median"]).round(1)
    ext = pd.concat([E.nlargest(5, f"y_{cand}"), E.nsmallest(5, f"y_{cand}")])[["symbol", "t", "change", "usd_jump", "flag_20", "revert_3d", "runup_y", "lag_y", *ycols]].round(0)
    hours = t.hour.value_counts().sort_index().rename("cells").to_frame()
    bdist = {"B": bar, "B_i_min": float(E["B_i"].min()), "B_i_median": float(E["B_i"].median()), "B_i_q90": float(E["B_i"].quantile(0.9)), "B_i_max": float(E["B_i"].max()), "R28_constant": krevent.BAR_R28,
             **{f"source: {k}": int(v) for k, v in E["B_source"].value_counts().items()}}
    corr = {d: float(pd.Series(ry).corr(pd.Series(Y[h]))) for d, h in zip(["1d", "3d"], HOLDS)}
    # the SCREEN row: the gate's cells re-cut by the member block that holds t
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    blk = starts[np.clip(starts.searchsorted(t, side="right") - 1, 0, None)]
    scr = pd.DataFrame({"block": blk, "y": Y[gh]}).dropna().groupby("block")["y"].agg(["size", "mean", "median"])
    n_blocks = int(((starts >= a0) & (starts < end)).sum())
    screen = {"hold": cand, "blocks_in_window": n_blocks, "blocks_with_a_member_cell": int(len(scr)), "member_cells": int(len(E)), f"mean_of_block_means_{cand}": float(scr["mean"].mean()) if len(scr) else np.nan,
              f"median_of_block_means_{cand}": float(scr["mean"].median()) if len(scr) else np.nan, "blocks_with_mean_below_0": int((scr["mean"] < 0).sum())}
    scr.round(1).to_csv(out / "screen_blocks.csv")
    drow = None
    if len(D):
        Pd = population(M, C, mem, L[L.index.isin(D.index)].reset_index(drop=True), end, first_block, taker_bps, spec.lag_h, gh)
        drow = Pd["E"][["symbol", "t0", "t", *ycols, "runup_y", "lag_y", "B_i"]] if len(Pd["E"]) else None
        if drow is not None:
            drow.to_csv(out / "described_rows.csv", index=False)
    other_md, money_md = [], []
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
    if not spec.confirm:
        other_md += _desc_population(M, C, mem, L_full[L_full["outflow"]].reset_index(drop=True), end, first_block, taker_bps, spec, out / "outflow", "The members' OUTFLOW cells, BOUGHT (the mirror)", "a bought position earns +y: a positive M_trim is the mirror earning")
        other_md += _desc_population(M, C, mem, L_full[L_full["nonmember_in"]].reset_index(drop=True), end, first_block, taker_bps, spec, out / "nonmembers", "The NON-MEMBERS' inflow cells (the cells whose bars are in the slice)", "a sold position earns −y, as the gate's")
    md += ["\n## Described — decides nothing\n", *money_md,
           "\nThe splits (the size flags; a wallet-list commit day; the revert within three stamps (post-t0); the five busiest names / the rest; usd_before ≥ the median; more than one chain; a repeat jump; the folds; each name) — the trimmed mean, the plain, the median:\n", splits.round(1).to_markdown(index=False), "\n",
           "\nThe distribution of y, and a and b apart:\n", pd.DataFrame(desc).round(1).to_markdown(index=False), "\n",
           "\nThe money of a SOLD position (−y; the trimmed beside; a loss capped at the position's size is a different rule, shown beside; a stop is not written in):\n", pd.DataFrame(sold).round(3).to_markdown(index=False), "\n",
           f"\nEach position through the harness as a taker (fee {taker_bps} bps a leg, `costwide`'s proxy and its double; the name's own legs, no benchmark):\n", pd.DataFrame(net).round(1).to_markdown(index=False), "\n",
           "\nBy calendar quarter of the entry (cells, mean, median):\n", qt.to_markdown(), "\n",
           f"\nThe five largest and the five smallest y at {cand}:\n", ext.to_markdown(index=False), "\n",
           "\nThe hour of t (UTC):\n", hours.to_markdown(), "\n",
           "\nThe RUN-UP against the drift: the correlation of runup_y with y per hold (a fact, not a rule):\n", "\n```\n" + json.dumps(corr, indent=1) + "\n```\n",
           "\nThe bar: B_i's distribution and its sources:\n", "\n```\n" + json.dumps(bdist, indent=1) + "\n```\n",
           f"\nThe SCREEN row — the gate's cells re-cut by the member block that holds t (the mean y_{cand} per block; `screen_blocks.csv`):\n", "\n```\n" + json.dumps(screen, indent=1) + "\n```\n",
           "\nThe described rows (the twelve's; none expected):\n", "none" if drow is None else drow.round(1).to_markdown(index=False), "\n",
           "\nCounts recorded, not priced:\n", "\n```\n" + json.dumps(dict(spec.counts), indent=1, default=str) + "\n```\n",
           "\n## Reference rows — no verdict (the entry a day later; against BTC; a alone)\n", pd.DataFrame(ref).round(1).to_markdown(index=False), "\n",
           *other_md]
    (out / "meta.json").write_text(json.dumps({"registration": spec.registration, "decision": spec.decision, "unit": bt.UNIT, "charged": bt.CHARGED, "holds": HOLDS, "gate_hold": gh, "lag_h": spec.lag_h, "runup_bars": 288 + 12 * spec.lag_h + 1,
                                                "bar": bar, "bar_mult": krevent.BAR_MULT, "bar_r28": krevent.BAR_R28, "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": spec.seed, "trim_frac": TRIM_FRAC, "frozen": int(len(L_full)),
                                                "gate_rows": int(len(L)), "cells": int(len(E)), "weeks": W, "taker_bps": taker_bps, "list_md5": list_md5, "verdict": verdict, "gate_hold_name": cand, "runup_little": little, "confirm": spec.confirm, "strategy": spec.strategy, "sides": list(spec.sides),
                                                "folds": list(spec.folds), "pad_days": spec.pad_days, "knownat": ka}, indent=1, default=str))
    text = "\n".join(md)
    (out / "cexevent.md").write_text(text)
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
        sys.exit(f"cexevent: unknown action {action}")
