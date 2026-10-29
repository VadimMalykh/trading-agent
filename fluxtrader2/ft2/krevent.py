"""P8, R70 — the Korean listing of an existing perpetual, sold from the close of its first KRW hour: does the name give back against
the screener's members over the next 1, 3 and 7 days? `ft2 krevent fingerprint|run|check` (PLAN §8 R70 is the registration; this file
is its code and changes nothing of it; decision BN2 — every event of the frozen F1+F2 list is the gate's cell).

events     the FROZEN `ft2/krlistings_f12.csv` (decision BM1's audit, DATA.md `krw_listings`; md5 as registered): venue, market, symbol,
           t0 = the venue's first hourly bar's START, ts_known = t0 + 1 h, first_korean, member_at_t0. Nothing is added, dropped or
           re-dated here; an event the entry rule cannot hold is counted by reason.
entry      the decision bar is the 5m bar that closes at t = t0 + 60 min (= ts_known); the position is entered one bar later (the
           harness's latency) — 65 minutes after the venue's first bar.
label      R28's: a = what a long earns before trading costs with the funding it pays (`listing.label_at` = `horizon.labels`' number);
           b = the mean over the members of the block that holds t, the name itself left out (`listing.excess`); y = a − b. A sold
           position earns −y.
statistic  M = the mean of y per hold (1d / 3d / 7d, the family); R28's moving-block bootstrap over calendar weeks (`listing.bootstrap`,
           seed 70); family-wise over the three holds. The sign NEGATIVE: the gate reads M ≤ −B.
bar        B = the mean over the eligible events of B_i = 2 × the name's own taker round trip on its entry day from the cost rows
           (2 legs × (fee + half spread + impact)); a name without a row that day takes its last within 7 days before, else R28's 46.
run-up     y over t0 − 24 h → t0 (no latency), the validity-of-mechanism row — read first, no gate.
validity   (1) the archive slice's fingerprint before (`fingerprint`) and after (`check`) the run; (2) the list's md5 and its t0 re-derived
           from the KRW parquets; (3) ≥ 90 % and ≥ 45 eligible, ≥ 90 % with their own cost row; (4) bars and labels ≥ 95 %; (5) members
           ≥ 40; (6) the label identity with `horizon.labels` and the harness; (7) t = ts_known for every eligible event.

R71 — `ft2 krevent confirm --registration R71` (PLAN §8 R71; decision BO1): the confirmation read of R70's candidate on the frozen F3+F4 list,
once. ONE rule: sold at the same entry, held 288 bars, NO stop; priced by `listing.sold_trades` (R29's path unchanged: the entry day's legs
at twice the name's proxy row, the heavy reading ×4 / ×2 beside), hedged with the F3+F4 block's members (`listing.hedge`); H = own + hedge,
M its mean, u on the larger of the bootstrap's and the week-clustered se (`listing.noise`, seed 71). The cells: the 69 frozen rows less the
three same-name same-hour twins (one position each; the Bithumb row kept) and less the twelve's two events (described, not cells) → 64.
The guard rows (R71, F3) / (R71, F4) are appended to the ledger BEFORE the market is loaded (`score_ext.guard`). `recheck`: the same path
on the F1+F2 list at the plain proxy reproduces R70's harness pricing (validity (3)) — no F3+F4 bar.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import events, horizon, krlist, krw, listing, universe
from .ceiling import BAR

NAME = "r70"
OUT = listing.OUT                                  # output/listing
LIST = krlist.LISTS["f12"]
LIST_MD5 = "60c07189b687566b8cc9d95b57f3caf6"      # as registered (PLAN §8 R70)
LIST_ROWS = 52
FOLDS = ("F1", "F2")
HOLDS = (288, 864, 2016)                           # 1, 3, 7 days — the family
WAIT = 12                                          # bars from t0 to the decision bar's close: 60 minutes
RUNUP = 288                                        # the run-up row: t0 − 24 h → t0
LATE = 288                                         # reference row: the entry a day later
TAKER_BPS = 5.0
BAR_MULT = 2.0                                     # B_i = this × the name's own round trip
BAR_R28 = 46.0                                     # R28's constant: the fallback for a name without a cost row, and a described comparison
FALLBACK_DAYS = 7
BLOCK_WEEKS, DRAWS, SEED = 6, 10_000, 70
TRIM = 3
MIN_MEMBERS, MIN_ELIGIBLE, MIN_ELIGIBLE_SHARE, MIN_OWN_COST, MIN_BARS, MIN_LABELS = 40, 45, 0.90, 0.90, 0.95, 0.95
BTC = "BTCUSDT"
HL_AUDIT = Path("output/hl_audit.json")
FP_BEFORE = OUT / f"{NAME}_fingerprint_before.csv"
FP_CHECK = OUT / f"{NAME}_fingerprint_check.json"
SPLITS = {"first_korean": ("first listing", "second venue"), "venue": None, "member_at_t0": ("member at t0", "not a member")}

# R71, the confirmation read
LIST34 = krlist.LISTS["f34"]
LIST34_MD5 = "6222d4361b78b91ac59b2c199d2e1da0"    # as registered (PLAN §8 R71)
LIST34_ROWS = 69
CONF_FOLDS = ("F3", "F4")
HOLD = 288                                         # R70's candidate: 1 day
ENTRY_MULT = 2.0                                   # the entry day's legs: this × the name's proxy row (R29's rule)
HEAVY = (4.0, 2.0)                                 # the heavy reading: the entry day × 4, every other proxy cost × 2
SEED_CONFIRM = 71
MIN_CONFIRM, MIN_CONFIRM_SHARE, MIN_H_SHARE = 58, 0.90, 0.90
DESCRIBED = tuple(krw.TWELVE)                      # the twelve are untouched by every gate: their events are described rows, not cells
STRATEGY = "krlisting_sold_1d"
R70_DIR = OUT / NAME
R70_CHECK = OUT / "r71_r70_check.json"
R70_SOLD_X1_NET = 201.9                            # R70's report: the sold position's net through the harness at the proxy (51 priced), printed to 0.1


def _days(h: int) -> str:
    return f"{h // 288}d"


def md5(path: Path | str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ---- the frozen events ----------------------------------------------------------------------------------------------------------
def load_events(path: Path | str = LIST) -> pd.DataFrame:
    L = pd.read_csv(path)
    for c in ("t0", "ts_known", "perp_first", "other_venue_t0"):
        L[c] = pd.to_datetime(L[c], utc=True, format="ISO8601")
    return L


def rederived(L: pd.DataFrame) -> dict:
    """Validity (2): every frozen row's t0 is what `krlist.events`' rule gives from the KRW parquets today."""
    try:
        E = krlist.events(write=False).set_index(["venue", "market"])
    except Exception as e:                                         # noqa: BLE001 — recorded, and the validity fails
        return {"status": "MISSING", "why": str(e)[:200]}
    bad = []
    for r in L.itertuples(index=False):
        k = (r.venue, r.market)
        if k not in E.index:
            bad.append({"venue": r.venue, "market": r.market, "why": "not a candidate today"})
        elif pd.Timestamp(E.loc[k, "t0"]) != r.t0:
            bad.append({"venue": r.venue, "market": r.market, "why": "t0 differs", "frozen": str(r.t0), "today": str(E.loc[k, "t0"])})
        elif E.loc[k, "why"] != "eligible":
            bad.append({"venue": r.venue, "market": r.market, "why": f"not eligible today: {E.loc[k, 'why']}"})
    return {"status": "PASS" if not bad else "FAIL", "rows": int(len(L)), "bad": bad}


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
            why = "before F1's first member block"
        elif row + latency >= n or not (np.isfinite(cl[row, c]) and np.isfinite(cl[row + latency, c])):
            why = "no close at the decision or entry bar"
        else:
            x = row + latency + longest
            why = "the 7-day exit is not before the end" if x >= n or not idx[x] < end else ""
        rows.append({"t": t, "row": row, "why": why})
    out = pd.concat([L.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    out["eligible"] = out["why"] == ""
    return out


# ---- the bar: the name's own doubled round trip on the entry day -------------------------------------------------------------------
def bars_per_event(C: bt.Costs, own: np.ndarray, t: pd.DatetimeIndex, taker_bps: float = TAKER_BPS, mult: float = BAR_MULT, fallback_days: int = FALLBACK_DAYS, r28: float = BAR_R28) -> pd.DataFrame:
    """B_i = mult × 2 legs × (fee + taker_leg) from the row of the entry day; else the last row within `fallback_days` before; else R28's constant."""
    days = pd.DatetimeIndex(C.days)
    dn = days.as_unit("ns").asi8 if days.tz is None else days.tz_convert("UTC").tz_localize(None).as_unit("ns").asi8
    out = []
    for c, ti in zip(own, pd.DatetimeIndex(t)):
        day = int(np.datetime64(ti.tz_convert("UTC").floor("D").tz_localize(None), "ns").astype("int64"))
        p = int(np.searchsorted(dn, day, "right")) - 1
        leg, src, used = np.nan, "R28's 46", pd.NaT
        while p >= 0:
            back = (day - dn[p]) // (86_400 * 10 ** 9)
            if back > fallback_days:
                break
            v = C.taker_leg[p, c]
            if np.isfinite(v):
                leg, src, used = float(v), ("own day" if back == 0 else f"within {fallback_days} d"), pd.Timestamp(dn[p], tz="UTC")
                break
            p -= 1
        b = mult * 2.0 * (taker_bps + leg) if np.isfinite(leg) else r28
        out.append({"taker_leg": leg, "cost_day": used, "B_source": src, "B_i": b})
    return pd.DataFrame(out)


# ---- the gate ---------------------------------------------------------------------------------------------------------------------
def hold_verdict(m: float, se: float, u: float, p_fw: float, m_f1: float, m_f2: float, m_trim: float, bar: float) -> str:
    if m <= -bar and abs(u) >= 2 and p_fw <= 0.05 and m_f1 < 0 and m_f2 < 0 and m_trim <= -bar:
        return "CLEARS"
    if m >= bar and abs(u) >= 2 and p_fw <= 0.05 and m_f1 > 0 and m_f2 > 0 and m_trim >= bar:
        return "CLEARS WITH THE OPPOSITE SIGN"
    if abs(m) + 1.96 * se < bar:
        return "under the bar"
    return "NOT DETECTABLE"


def family_verdict(fam: pd.DataFrame) -> tuple[str, str | None]:
    """(the verdict, the candidate hold): CLEARS on the clearing hold with the largest |u|; the opposite sign recorded as such; CLOSED only
    when every hold's interval lies inside ±B; NOT DETECTABLE otherwise."""
    cl = fam[fam["verdict"] == "CLEARS"]
    if len(cl):
        return "CLEARS", str(cl.loc[cl["u"].abs().idxmax(), "hold"])
    op = fam[fam["verdict"] == "CLEARS WITH THE OPPOSITE SIGN"]
    if len(op):
        return "CLEARS WITH THE OPPOSITE SIGN", str(op.loc[op["u"].abs().idxmax(), "hold"])
    if (fam["verdict"] == "under the bar").all():
        return "CLOSED", None
    return "NOT DETECTABLE", None


# ---- the fingerprint (validity (1)) -------------------------------------------------------------------------------------------------
def fp_paths(name: str | None) -> tuple[Path, Path]:
    """The fingerprint files of a run: R70's registered names for the default, `<name>_fingerprint_*` for another registration (R71)."""
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
        raise SystemExit(f"krevent check: no fingerprint before at {fp_before} — run `ft2 krevent fingerprint` before the run")
    before = pd.read_csv(fp_before)
    r = krlist.fingerprint_check(before, after_fn=krlist.fingerprint)
    r["status"] = "PASS" if r["pass"] else "FAIL"
    fp_check.write_text(json.dumps(r, indent=1, default=str))
    v = OUT / (name or NAME) / "validity.json"
    if v.exists():                                                   # the run's validity record carries the after-check once it exists
        V = json.loads(v.read_text())
        V["1_fingerprint_after"] = r["status"]
        v.write_text(json.dumps(V, indent=1))
    print(f"fingerprint after the run: {r['status']} — {r['names_before']} names before, {r['names_after']} after, {len(r['changed'])} changed → {fp_check}")
    return r


# ---- counts recorded, not priced --------------------------------------------------------------------------------------------------------
def hl_first_rows_by_fold(path: Path = HL_AUDIT) -> dict:
    if not path.exists():
        return {"status": "MISSING"}
    cov = pd.DataFrame(json.load(path.open())["cover"])
    f = pd.to_datetime(cov["first"], utc=True, errors="coerce")
    return events.fold_of(f).value_counts().sort_index().to_dict()


# ---- the run ------------------------------------------------------------------------------------------------------------------------------
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
                        "share_below_0": float((y < 0).mean()) if len(y) else np.nan, "se_plain": float(y.std(ddof=1) / np.sqrt(len(y))) if len(y) > 1 else np.nan})
    return pd.DataFrame(out)


def run(name: str = NAME, taker_bps: float = TAKER_BPS) -> str:
    a0, end = listing.window(FOLDS)
    L = load_events(LIST)
    list_md5 = md5(LIST)
    mem = universe.members()
    first_block = mem["block"].min()
    syms = list(dict.fromkeys([*L["symbol"], *universe.screen_symbols(), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, fv = M.close.to_numpy(), C.fundval
    E_all = entries(M, L, end, first_block)
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    rows, own = E["row"].to_numpy(), M.columns.get_indexer(E["symbol"])
    t = pd.DatetimeIndex(E["t"])
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)

    # labels: the family, the run-up, the entry a day later, the benchmark of BTC
    mask, mask_late = listing.member_mask(mem, M.columns, t), listing.member_mask(mem, M.columns, t + LATE * BAR)
    btc = np.full(len(E), M.columns.get_loc(BTC))
    A, B, NB, Y, YL, YB = ({} for _ in range(6))
    for h in HOLDS:
        lab = listing.label_at(close, fv, rows, h)
        A[h], B[h], NB[h] = listing.excess(lab, own, mask)
        Y[h] = A[h] - B[h]
        al, bl, _ = listing.excess(listing.label_at(close, fv, rows + LATE, h), own, mask_late)
        YL[h], YB[h] = al - bl, A[h] - lab[np.arange(len(E)), btc]
        d = _days(h)
        E[f"a_{d}"], E[f"b_{d}"], E[f"n_b_{d}"], E[f"y_{d}"] = A[h], B[h], NB[h], Y[h]
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
        f = listing._priced(M, C, E.rename(columns={"symbol": "contract"}), h, 1, taker_bps)
        ident[h] = (float(np.nanmax(np.abs(full[rows, own] - A[h]))), float(np.nanmax(np.abs((f["gross_bps"] + f["funding_bps"]).to_numpy() - A[h]))), bool((np.isfinite(full[rows, own]) == np.isfinite(A[h])).all()))
        del full
    red = rederived(L)
    V = {"1_fingerprint_before": "saved" if FP_BEFORE.exists() else "MISSING", "1_fingerprint_after": "pending → `ft2 krevent check` after the run",
         "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == LIST_MD5, "2_list_rows": int(len(L)), "2_rederived": red,
         "3_frozen": int(len(L)), "3_eligible": int(len(E)), "3_eligible_share": float(len(E) / len(L)) if len(L) else 0.0,
         "3_own_cost_row_share": float((E["B_source"] != "R28's 46").mean()) if len(E) else 0.0, "3_B_source": E["B_source"].value_counts().to_dict(),
         "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_events_under_95pct_bars": int(sum(s < MIN_BARS for s in span)),
         "4_label_share": {_days(h): float(np.isfinite(Y[h]).mean()) for h in HOLDS},
         "5_min_members": {_days(h): int(NB[h].min()) if len(E) else 0 for h in HOLDS}, "5_min_members_runup": int(ru_nb.min()) if len(E) else 0,
         "6_identity_max_abs_diff": {_days(h): ident[h][:2] for h in HOLDS}, "6_same_cells": all(ident[h][2] for h in HOLDS),
         "7_t_equals_ts_known": bool((t == pd.DatetimeIndex(E["ts_known"])).all()) if len(E) else False}
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L) == LIST_ROWS and red.get("status") == "PASS"
                             and V["3_eligible_share"] >= MIN_ELIGIBLE_SHARE and len(E) >= MIN_ELIGIBLE and V["3_own_cost_row_share"] >= MIN_OWN_COST
                             and V["4_events_under_95pct_bars"] == 0 and min(V["4_label_share"].values()) >= MIN_LABELS
                             and min(V["5_min_members"].values()) >= MIN_MEMBERS and max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_same_cells"]
                             and V["7_t_equals_ts_known"]) else "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
    E_all.to_csv(out / "events_all.csv", index=False)
    md = [f"# R70 — the Korean listing of an existing perpetual, sold from its first KRW hour (`ft2 krevent run`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {M.index[0]:%Y-%m-%d} → {M.index[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{LIST.name}` md5 {list_md5}\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 krevent check`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nEvents by what became of them:\n", E_all["why"].replace("", "eligible").value_counts().rename("events").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the run-up row and the family are not computed.**\n"]
        (out / "krevent.md").write_text("\n".join(md))
        return "\n".join(md)

    # the run-up — read first, no gate
    ry = E["runup_y"].to_numpy()
    rv = ry[np.isfinite(ry)]
    q = [0.05, 0.25, 0.5, 0.75, 0.95]
    ru = [{"group": "all", "n": int(len(rv)), "median": float(np.median(rv)), "mean": float(rv.mean()), **{f"q{int(x * 100):02d}": float(np.quantile(rv, x)) for x in q}, "share_ge_500": float((rv >= 500).mean()),
           "share_below_0": float((rv < 0).mean()), "median_a": float(np.nanmedian(E["runup_a"])), "median_b": float(np.nanmedian(E["runup_b"]))}]
    for key, labels in SPLITS.items():
        for v in (sorted(E[key].unique(), key=str) if labels is None else (True, False)):
            m = (E[key] == v).to_numpy()
            g = ry[m]
            g = g[np.isfinite(g)]
            if len(g):
                ru.append({"group": f"{key} = {v if labels is None else labels[0 if v else 1]}", "n": int(len(g)), "median": float(np.median(g)), "mean": float(g.mean()), "share_ge_500": float((g >= 500).mean()), "share_below_0": float((g < 0).mean())})
    ru = pd.DataFrame(ru)
    ru.to_csv(out / "runup.csv", index=False)
    little = bool(ru.loc[0, "median"] < 300)
    md += ["\n## The run-up — y over t0 − 24 h → t0 against the members (validity of mechanism; read first, decides nothing)\n", ru.round(1).to_markdown(index=False), "\n",
           f"\n{'The median run-up is under +300 bps: by the registration there is little to give back and NOT DETECTABLE is the likely verdict whatever the sign.' if little else 'The median run-up is at or above +300 bps: a pump to give back exists.'}\n"]

    # the family
    wk, W = listing.weeks(t)
    Ymat = np.column_stack([Y[h] for h in HOLDS])
    bs = listing.bootstrap(Ymat, wk, W, block=BLOCK_WEEKS, draws=DRAWS, seed=SEED)
    f1, f2 = (E["fold"] == "F1").to_numpy(), (E["fold"] == "F2").to_numpy()
    fam = []
    for k, h in enumerate(HOLDS):
        y = Y[h]
        r = {"hold": _days(h), "n": int(bs["n"][k]), "M": float(bs["m"][k]), "se": float(bs["se"][k]), "u": float(bs["u"][k]), "p_fw": float(bs["p_fw"]), "MDE": 2.8 * float(bs["se"][k]),
             "M_F1": float(np.nanmean(y[f1])), "M_F2": float(np.nanmean(y[f2])), "M_trim": listing.trimmed(y, TRIM), "se_week": float(bs["se_week"][k]), "se_plain": float(bs["se_plain"][k]), "B": bar}
        r["verdict"] = hold_verdict(r["M"], r["se"], r["u"], r["p_fw"], r["M_F1"], r["M_F2"], r["M_trim"], bar)
        fam.append(r)
    fam = pd.DataFrame(fam)
    verdict, cand = family_verdict(fam)
    fam.to_csv(out / "holds.csv", index=False)
    md += [f"\n## The family — y = a − b, bps of the position; {len(E)} events in {W} weeks; B {bar:.1f} (the mean of the names' own doubled round trips; R28's 46 beside); {bs['draws']:,} draws of {BLOCK_WEEKS}-week blocks; the sign NEGATIVE\n",
           fam.round(3).to_markdown(index=False), "\n", f"\n**Verdict: {verdict}{f' — the candidate hold {cand}' if cand else ''}.**\n",
           f"\nn in F1 {int(f1.sum())}, in F2 {int(f2.sum())}; events per week: mean {len(E) / W:.2f}, most {int(np.bincount(wk, minlength=W).max())}, weeks with none {int((np.bincount(wk, minlength=W) == 0).sum())}.\n"]

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
        sold.append({"hold": d, "mean_sold": -v.mean(), "mean_sold_loss_capped_at_size": np.maximum(-v, -1e4).mean(), "largest_single_loss": float(v.max()), "sold_positions_losing_over_half": int((v > 5000).sum()),
                     "share_y_over_5000": float((v > 5000).mean())})
        ref.append({"hold": d, "M_entry_a_day_later": float(np.nanmean(YL[h])), "median_entry_a_day_later": float(np.nanmedian(YL[h])), "M_against_BTC": float(np.nanmean(YB[h])),
                    "median_against_BTC": float(np.nanmedian(YB[h])), "M_a_alone": float(np.nanmean(A[h]))})
        for side, sname in ((1, "bought"), (-1, "sold")):
            for mult, CC in ((1, C), (2, C2)):
                f = listing._priced(M, CC, Ec, h, side, taker_bps)
                net.append({"hold": d, "side": sname, "cost": f"×{mult}", "n_priced": int(f["net_bps"].notna().sum()), "gross": f["gross_bps"].mean(), "fee": f["fee_bps"].mean(), "spread_impact": f["other_cost_bps"].mean(),
                            "funding": f["funding_bps"].mean(), "net": f["net_bps"].mean(), "net_median": f["net_bps"].median()})
        E[f"y_late_{d}"], E[f"y_btc_{d}"] = YL[h], YB[h]
    E.to_csv(out / "events.csv", index=False)
    splits = pd.concat([_split_rows(E, Y, k, lab) for k, lab in SPLITS.items()], ignore_index=True)
    splits.to_csv(out / "splits.csv", index=False)
    ycols = [f"y_{_days(h)}" for h in HOLDS]
    qt = E.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")[ycols].agg(["size", "mean", "median"]).round(1)
    ext = pd.concat([E.nlargest(5, "y_7d"), E.nsmallest(5, "y_7d")])[["symbol", "venue", "t", "first_korean", "runup_y", *ycols, *[f"a_{_days(h)}" for h in HOLDS]]].round(0)
    hours = t.hour.value_counts().sort_index().rename("events").to_frame()
    bdist = {"B": bar, "B_i_min": float(E["B_i"].min()), "B_i_median": float(E["B_i"].median()), "B_i_max": float(E["B_i"].max()), "R28_constant": BAR_R28, **{f"source: {k}": int(v) for k, v in E["B_source"].value_counts().items()}}
    twelve = sorted(set(L["symbol"]) & set(krw.TWELVE))
    counts = {"the twelve's own Korean listings in the frozen F1+F2 list": twelve or "none", "Hyperliquid first rows by fold (output/hl_audit.json cover; a venue's ramp, not priced)": hl_first_rows_by_fold()}
    md += ["\n## Described — decides nothing\n",
           "\nThe splits (BN1's cell — the first Korean listing per name — as a row; the venues; members at t0):\n", splits.round(1).to_markdown(index=False), "\n",
           "\nThe distribution of y, and a and b apart:\n", pd.DataFrame(desc).round(1).to_markdown(index=False), "\n",
           "\nThe money of a SOLD position (−y; a loss capped at the position's size is a different rule, shown beside; a stop is not written in):\n", pd.DataFrame(sold).round(3).to_markdown(index=False), "\n",
           f"\nEach position through the harness as a taker (fee {taker_bps} bps a leg, `costwide`'s proxy and its double; the name's own legs, no benchmark):\n", pd.DataFrame(net).round(1).to_markdown(index=False), "\n",
           "\nBy calendar quarter of the entry (events, mean, median):\n", qt.to_markdown(), "\n",
           "\nThe five largest and the five smallest y at 7 days:\n", ext.to_markdown(index=False), "\n",
           "\nThe hour of t (UTC):\n", hours.to_markdown(), "\n",
           "\nThe bar: B_i's distribution and its sources:\n", "\n```\n" + json.dumps(bdist, indent=1) + "\n```\n",
           "\nCounts recorded, not priced:\n", "\n```\n" + json.dumps(counts, indent=1, default=str) + "\n```\n",
           "\n## Reference rows — no verdict\n", pd.DataFrame(ref).round(1).to_markdown(index=False), "\n"]
    (out / "meta.json").write_text(json.dumps({"registration": "R70", "decision": "BN2", "unit": bt.UNIT, "charged": bt.CHARGED, "holds": HOLDS, "wait": WAIT, "runup": RUNUP, "bar": bar, "bar_mult": BAR_MULT,
                                                "bar_r28": BAR_R28, "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": SEED, "frozen": int(len(L)), "eligible": int(len(E)), "weeks": W, "taker_bps": taker_bps,
                                                "list_md5": list_md5, "verdict": verdict, "candidate_hold": cand}, indent=1))
    text = "\n".join(md)
    (out / "krevent.md").write_text(text)
    return text



# ====================================================================================================================================
# R71 — the confirmation read (PLAN §8 R71): R29's path on the frozen F3+F4 list, 1 day, no stop, once
# ====================================================================================================================================
def cells(L: pd.DataFrame, described: tuple[str, ...] = DESCRIBED) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(the cells, the twins dropped, the described rows): a same-name same-hour pair is ONE position — the first row by venue order
    (bithumb, upbit) kept, the other listed as its twin; a name of the twelve is a described row, never a cell."""
    order = {"bithumb": 0, "upbit": 1}
    L = L.assign(_o=L["venue"].map(order).fillna(9)).sort_values(["t0", "_o", "market"]).drop(columns="_o").reset_index(drop=True)
    desc = L[L["symbol"].isin(described)]
    rest = L[~L["symbol"].isin(described)]
    dup = rest.duplicated(["symbol", "t0"], keep="first")
    return rest[~dup].reset_index(drop=True), rest[dup].reset_index(drop=True), desc.reset_index(drop=True)


def _frame(E: pd.DataFrame) -> pd.DataFrame:
    return E.rename(columns={"symbol": "contract"})


def _arith(M: bt.Market, C: bt.Costs, T: pd.DataFrame, own: np.ndarray, taker_bps: float) -> dict:
    """Validity (6): the harness's fill is the module's own arithmetic (R29's check); gross + funding of the sold position is −`horizon.labels`."""
    close = M.close.to_numpy()
    e, x = T["e"].to_numpy(), T["x"].to_numpy()
    pe, px_ = close[e, own], close[x, own]
    r = px_ / pe
    mine = {"gross": -(r - 1.0) * 1e4, "funding": (C.fundval[x, own] - C.fundval[e, own]) / pe, "fee": taker_bps + taker_bps * r,
            "spread_impact": T["leg_entry"].to_numpy() + T["leg_exit"].to_numpy() * r}
    mine["own"] = mine["gross"] - mine["fee"] - mine["spread_impact"] + mine["funding"]
    d = {k: float(np.nanmax(np.abs(v - T[k].to_numpy()))) if np.isfinite(T[k].to_numpy()).any() else 0.0 for k, v in mine.items()}
    full = horizon.labels(M, C, HOLD, bt.LATENCY)[1].to_numpy()[(e - bt.LATENCY), own]
    d["sold_gross_funding_vs_minus_horizon_labels"] = float(np.nanmax(np.abs((T["gross"] + T["funding"]).to_numpy() + full)))
    d["hold_is_288"] = bool(((x - e) == HOLD).all())
    return d


def recheck(taker_bps: float = TAKER_BPS) -> dict:
    """Validity (3) of R71: the confirmation's path on R70's F1+F2 events at the plain proxy (entry day ×1) gives R70's harness pricing — per
    event the own net = `listing._priced`'s sold ×1 net (R70's call) to 1e-9 and gross + funding = −a_1d of R70's events.csv to 1e-9; the
    mean own over the priced events = R70's report's +201.9 to the report's 0.1. No F3+F4 bar is loaded (the market ends at F2's end)."""
    a0, end = listing.window(FOLDS)
    L = load_events(LIST)
    mem = universe.members()
    syms = list(dict.fromkeys([*L["symbol"], *universe.screen_symbols(), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    E_all = entries(M, L, end, mem["block"].min())
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    mask = listing.member_mask(mem, M.columns, pd.DatetimeIndex(E["t"]))
    T = listing.sold_trades(M, C, _frame(E), mask, taker_bps, entry_mult=1.0, other_mult=1.0, hold=HOLD, level=np.inf)
    P = listing._priced(M, C, _frame(E), HOLD, -1, taker_bps)
    r70 = pd.read_csv(R70_DIR / "events.csv")[["venue", "market", "a_1d"]] if (R70_DIR / "events.csv").exists() else None
    out = {"eligible": int(len(E)), "priced": int(T["own"].notna().sum())}
    if r70 is None:
        out.update({"status": "FAIL", "why": f"no {R70_DIR / 'events.csv'} — R70's read is the reference"})
    else:
        j = E[["venue", "market"]].merge(r70, on=["venue", "market"], how="left")
        own_vs_priced = float(np.nanmax(np.abs(T["own"].to_numpy() - P["net_bps"].to_numpy())))
        gf_vs_a = float(np.nanmax(np.abs((T["gross"] + T["funding"]).to_numpy() + j["a_1d"].to_numpy())))
        mean_own = float(T["own"].mean())
        out.update({"own_vs_r70_priced_max_abs": own_vs_priced, "gross_funding_vs_minus_a_1d_max_abs": gf_vs_a, "mean_own_x1": mean_own,
                    "r70_report_sold_x1_net": R70_SOLD_X1_NET, "mean_own_diff": abs(mean_own - R70_SOLD_X1_NET), "same_cells": bool((np.isfinite(T["own"].to_numpy()) == np.isfinite(P["net_bps"].to_numpy())).all()),
                    "a_1d_rows_matched": int(j["a_1d"].notna().sum()), "exits_before_end": bool((pd.DatetimeIndex(T["exit_t"]) < end).all())})
        out["status"] = "PASS" if (own_vs_priced <= 1e-9 and gf_vs_a <= 1e-9 and out["mean_own_diff"] <= 0.05 and out["same_cells"] and out["a_1d_rows_matched"] == len(E) and out["exits_before_end"]) else "FAIL"
    OUT.mkdir(parents=True, exist_ok=True)
    R70_CHECK.write_text(json.dumps(out, indent=1, default=str))
    return out


def _group_rows(T: pd.DataFrame, key: str, labels, col: str = "H") -> pd.DataFrame:
    out = []
    vals = T[key]
    for v in (sorted(vals.unique(), key=str) if labels is None else (True, False)):
        g = T.loc[vals == v, col].dropna()
        out.append({"split": key, "group": str(v) if labels is None else labels[0 if v else 1], "n": int(len(g)), "M": float(g.mean()) if len(g) else np.nan,
                    "median": float(g.median()) if len(g) else np.nan, "share_above_0": float((g > 0).mean()) if len(g) else np.nan, "se_plain": float(g.std(ddof=1) / np.sqrt(len(g))) if len(g) > 1 else np.nan})
    return pd.DataFrame(out)


def confirm(registration: str | None, name: str = "r71", taker_bps: float = TAKER_BPS) -> str:
    from . import score_ext                                        # imported here: its guard is R63 / R66's, the rows appended before the market
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fp_before, _ = fp_paths(name)
    L = load_events(LIST34)
    list_md5 = md5(LIST34)
    cl, twins, desc = cells(L, DESCRIBED)
    red = rederived(L)                                             # validity (2): the KRW parquets' first bars — no price of a name
    r70chk = json.loads(R70_CHECK.read_text()).get("status") if R70_CHECK.exists() else "MISSING"
    pre = {"1_fingerprint_before": "saved" if fp_before.exists() else "MISSING", "1_fingerprint_after": f"pending → `ft2 krevent check --name {name}` after the run",
           "2_list_md5": list_md5, "2_list_md5_as_registered": list_md5 == LIST34_MD5, "2_list_rows": int(len(L)), "2_rederived": red,
           "2_cells": int(len(cl)), "2_twins_dropped": twins[["venue", "market", "symbol", "t0"]].astype(str).to_dict("records"), "2_described_not_cells": desc[["venue", "market", "symbol", "t0"]].astype(str).to_dict("records"),
           "3_r70_recheck": r70chk}
    params = {"hold": HOLD, "stop": None, "wait": WAIT, "entry_mult": ENTRY_MULT, "heavy": list(HEAVY), "list": LIST34.name, "list_md5": list_md5, "cells": int(len(cl))}
    conf = bt._guard(CONF_FOLDS, registration)                     # registered, and once (refuses before anything is loaded)
    stamp = score_ext.guard(bt.READS, bt.PLAN, CONF_FOLDS, registration, STRATEGY, params)      # the rows (R71, F3) / (R71, F4) NOW, before the market
    pre["7_guard"] = {"status": "PASS", "appended_at": stamp, "ledger": str(bt.READS), "folds": list(conf)}
    print(f"guard: ({registration}, {', '.join(conf)}) appended to {bt.READS} at {stamp}; the F3+F4 market is loaded now", flush=True)

    a0, end = listing.window(CONF_FOLDS)
    mem = universe.members(universe.F34_MEMBERS_CSV)
    syms = list(dict.fromkeys([*cl["symbol"], *desc["symbol"], *universe.screen_symbols(universe.F34_MEMBERS_CSV), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, idx = M.close.to_numpy(), M.index
    fv = C.fundval
    E_all = entries(M, cl, end, mem["block"].min(), longest=HOLD)
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    own = M.columns.get_indexer(E["symbol"])
    rows, t = E["row"].to_numpy(), pd.DatetimeIndex(E["t"])
    mask = listing.member_mask(mem, M.columns, t)
    T = listing.sold_trades(M, C, _frame(E), mask, taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD, level=np.inf)
    TH = listing.sold_trades(M, C, _frame(E), mask, taker_bps, entry_mult=HEAVY[0], other_mult=HEAVY[1], hold=HOLD, level=np.inf)
    for k in ("venue", "market", "first_korean", "member_at_t0", "ts_known"):
        T[k], TH[k] = E[k].to_numpy(), E[k].to_numpy()

    # validity, read first
    span = [float(np.isfinite(close[r:r + bt.LATENCY + HOLD + 1, c]).mean()) for r, c in zip(rows, own)]
    d6 = _arith(M, C, T, own, taker_bps)
    unpriced = T.loc[T["H"].isna(), "contract"].tolist()
    V = dict(pre)
    V.update({"4_cells": int(len(cl)), "4_eligible": int(len(E)), "4_eligible_share": float(len(E) / len(cl)) if len(cl) else 0.0,
              "5_cells_under_95pct_bars": int(sum(v < MIN_BARS for v in span)), "5_H_share": float(T["H"].notna().mean()) if len(T) else 0.0, "5_unpriced": unpriced,
              "5_min_members": int(T["n_b"].min()) if len(T) else 0, "6_identity_max_abs_diff": d6,
              "7_t_equals_ts_known": bool((t == pd.DatetimeIndex(E["ts_known"])).all()) if len(E) else False, "7_exits_at_or_after_end": int((pd.DatetimeIndex(T["exit_t"]) >= end).sum()) if len(T) else 0,
              "7_no_stop": bool(not T["stopped"].any()) if len(T) else True})
    V["status"] = "PASS" if (V["1_fingerprint_before"] == "saved" and V["2_list_md5_as_registered"] and len(L) == LIST34_ROWS and red.get("status") == "PASS" and r70chk == "PASS"
                             and V["4_eligible_share"] >= MIN_CONFIRM_SHARE and len(E) >= MIN_CONFIRM and V["5_cells_under_95pct_bars"] == 0 and V["5_H_share"] >= MIN_H_SHARE
                             and V["5_min_members"] >= MIN_MEMBERS and max(v for v in d6.values() if not isinstance(v, bool)) <= 1e-9 and d6["hold_is_288"]
                             and V["7_t_equals_ts_known"] and V["7_exits_at_or_after_end"] == 0 and V["7_no_stop"]) else "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1, default=str))
    E_all.to_csv(out / "cells_all.csv", index=False)
    md = [f"# R71 — the confirmation read of the Korean listing, sold from its first KRW hour, 1 day (`ft2 krevent confirm`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {idx[0]:%Y-%m-%d} → {idx[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names · the list `{LIST34.name}` md5 {list_md5} · {len(L)} rows, {len(cl)} cells ({len(twins)} twins, {len(desc)} described)\n",
          f"\n## Validity: {V['status']} (the fingerprint after the run is `ft2 krevent check --name {name}`'s)\n", "\n```\n" + json.dumps(V, indent=1, default=str) + "\n```\n",
          "\nCells by what became of them:\n", E_all["why"].replace("", "eligible").value_counts().rename("cells").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the number is not computed. The guard rows stand in the ledger: the folds are read for this question.**\n"]
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
    md += [f"\n## The number — H = own + hedge, bps of the position; {N['n']} trades in {N['weeks']} weeks; the gate's se the larger of the bootstrap's and the week-clustered\n",
           pd.DataFrame([{k: N[k] for k in ("n", "M", "se", "u", "MDE", "M_heavy", "se_bootstrap", "se_week", "se_plain", "verdict")}]).round(3).to_markdown(index=False), "\n",
           f"\n**Verdict: {N['verdict']}.**\n"]
    (out / "confirm.md").write_text("\n".join(md))                # the read is on disk before anything is described
    try:
        md += _describe_r71(M, C, E, T, TH, mem, mask, own, ok, t, taker_bps, desc, twins, end)
    except Exception as exc:  # noqa: BLE001 — a description that fails must not take the logged read with it
        import traceback
        md += ["\n## Described — FAILED (the read above stands; describe from trades.csv)\n", "\n```\n" + "".join(traceback.format_exception(exc)) + "\n```\n"]
    T.to_csv(out / "trades.csv", index=False)                      # with the described columns (run-up, y rows) when the description ran
    (out / "meta.json").write_text(json.dumps({"registration": registration, "decision": "BO1", "unit": bt.UNIT, "charged": bt.CHARGED, "hold": HOLD, "stop": None, "wait": WAIT, "entry_mult": ENTRY_MULT,
                                                "heavy": HEAVY, "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": SEED_CONFIRM, "rows": int(len(L)), "cells": int(len(cl)), "eligible": int(len(E)),
                                                "taker_bps": taker_bps, "list_md5": list_md5, "verdict": N["verdict"]}, indent=1))
    text = "\n".join(md)
    (out / "confirm.md").write_text(text)
    return text


def _describe_r71(M, C, E, T, TH, mem, mask, own, ok, t, taker_bps, desc, twins, end) -> list[str]:
    """R71's described tables — decide nothing."""
    close, idx, fv = M.close.to_numpy(), M.index, C.fundval
    rows = E["row"].to_numpy()
    parts = ["gross", "funding", "fee", "spread_impact", "own", "hedge_gain", "hedge_cost", "hedge", "H"]
    by = pd.concat([T[parts].mean().rename("all"), *[T.loc[T["fold"] == f, parts].mean().rename(f) for f in CONF_FOLDS], TH[parts].mean().rename("heavy")], axis=1).T
    by.insert(0, "n", [len(T), *[int((T["fold"] == f).sum()) for f in CONF_FOLDS], len(TH)])
    No = listing.noise(T["own"].to_numpy()[ok], t[ok], seed=SEED_CONFIRM)
    q = T.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")["H"].agg(["size", "mean", "median"])
    H = T["H"].dropna()
    tail = {"largest_loss_H": float(H.min()), "trades_losing_over_half_the_size": int((T["own"] < -5000).sum()), "M_losses_capped_at_size": float(np.maximum(T["H"].to_numpy(), -1e4)[ok].mean()),
            "share_above_0": float((H > 0).mean()), "median_H": float(H.median()), **{f"q{int(x * 100):02d}": float(H.quantile(x)) for x in (0.05, 0.25, 0.75, 0.95)}, "best_H": float(H.max())}
    splits = pd.concat([_group_rows(T, k, lab) for k, lab in SPLITS.items()], ignore_index=True)
    # the run-up row (R70's frame, no cost) and H on its halves; R70's own number on these cells; the 3- and 7-day y rows unpriced
    ru_a, ru_b, _ = listing.excess(listing.label_at(close, fv, rows - WAIT - RUNUP - bt.LATENCY, RUNUP), own, mask)
    ru = ru_a - ru_b
    T["runup_y"] = ru
    hi, lo = ok & (ru >= 500), ok & ~(ru >= 500)
    ys = {}
    for h in (HOLD, 864, 2016):
        a_, b_, _ = listing.excess(listing.label_at(close, fv, rows, h), own, mask)
        ys[h] = a_ - b_
    T["y_1d"], T["y_3d"], T["y_7d"] = ys[HOLD], ys[864], ys[2016]
    runup = {"n": int(np.isfinite(ru).sum()), "median": float(np.nanmedian(ru)), "mean": float(np.nanmean(ru)), "share_ge_500": float(np.nanmean(ru >= 500)), "share_below_0": float(np.nanmean(ru < 0)),
             "H_runup_ge_500": {"n": int(hi.sum()), "M": float(T.loc[hi, "H"].mean()) if hi.any() else np.nan, "se_plain": float(T.loc[hi, "H"].std(ddof=1) / np.sqrt(hi.sum())) if hi.sum() > 1 else np.nan},
             "H_runup_under_500": {"n": int(lo.sum()), "M": float(T.loc[lo, "H"].mean()) if lo.any() else np.nan, "se_plain": float(T.loc[lo, "H"].std(ddof=1) / np.sqrt(lo.sum())) if lo.sum() > 1 else np.nan},
             "by_venue_median": {v: float(np.nanmedian(ru[(E["venue"] == v).to_numpy()])) for v in sorted(E["venue"].unique())}}
    yrows = pd.DataFrame([{"hold": _days(h), "n": int(np.isfinite(ys[h]).sum()), "M_y": float(np.nanmean(ys[h])), "median_y": float(np.nanmedian(ys[h])), "share_below_0": float(np.nanmean(ys[h] < 0)),
                           "se_plain": float(np.nanstd(ys[h], ddof=1) / np.sqrt(np.isfinite(ys[h]).sum()))} for h in (HOLD, 864, 2016)])
    # the twelve's events: described, never cells
    D_all = entries(M, desc, end, mem["block"].min(), longest=HOLD) if len(desc) else desc
    D = D_all[D_all["eligible"]].reset_index(drop=True) if len(desc) else desc
    if len(D):
        TD = listing.sold_trades(M, C, _frame(D), listing.member_mask(mem, M.columns, pd.DatetimeIndex(D["t"])), taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD, level=np.inf)
        od = M.columns.get_indexer(D["symbol"])
        a_, b_, _ = listing.excess(listing.label_at(close, fv, D["row"].to_numpy(), HOLD), od, listing.member_mask(mem, M.columns, pd.DatetimeIndex(D["t"])))
        TD["y_1d"] = a_ - b_
        twelve = TD[["contract", "t", "gross", "funding", "own", "hedge", "H", "y_1d"]].round(1).to_markdown(index=False)
    else:
        twelve = "none eligible"
    late = E[rows + LATE + bt.LATENCY + HOLD < len(idx)].reset_index(drop=True)
    TL = listing.sold_trades(M, C, _frame(late), listing.member_mask(mem, M.columns, pd.DatetimeIndex(late["t"]) + LATE * BAR), taker_bps, entry_mult=ENTRY_MULT, other_mult=1.0, hold=HOLD, level=np.inf, shift=LATE)
    md = ["\n## Described — decides nothing\n", "\nM's parts (means; `heavy` = the entry day at four times the proxy, every other proxy cost doubled):\n", by.round(1).to_markdown(), "\n",
          f"\n- the sold position alone (own): mean {No['M']:.1f}, se {No['se']:.1f} (bootstrap {No['se_bootstrap']:.1f}, week {No['se_week']:.1f}, plain {No['se_plain']:.1f}), u {No['u']:.2f}\n",
          "- the sold side's tail and H's distribution:\n", "\n```\n" + json.dumps(tail, indent=1) + "\n```\n",
          "\nThe splits (the venues; the first and the second listings; members at t0):\n", splits.round(1).to_markdown(index=False), "\n",
          "\nThe run-up (y over t0 − 24 h → t0 against the members, no cost — R70's frame) and H on its halves (a description, never a gate):\n", "\n```\n" + json.dumps(runup, indent=1, default=str) + "\n```\n",
          "\nR70's own number on these cells (y = a − b, no cost; R70 on F1+F2: 1d −241.5, 3d −202.8, 7d −146.3) and the 3- and 7-day rows unpriced:\n", yrows.round(1).to_markdown(index=False), "\n",
          "\nBy calendar quarter of the entry (trades, mean H, median H):\n", q.round(1).to_markdown(), "\n",
          "\nThe twelve's events (described, never cells; their H by the same rule):\n", twelve, "\n",
          "\nThe twins dropped (one position per same-name same-hour pair):\n", (twins[["venue", "market", "symbol", "t0"]].to_markdown(index=False) if len(twins) else "none"), "\n",
          f"\n- the entry a day later, the same costs (reference): mean H {TL['H'].mean():.1f}, median {TL['H'].median():.1f} ({len(TL)} trades)\n",
          "\nThe hour of t (UTC):\n", t.hour.value_counts().sort_index().rename("trades").to_frame().to_markdown(), "\n",
          "\nThe five best and the five worst trades:\n", pd.concat([T.nlargest(5, "H"), T.nsmallest(5, "H")])[["contract", "venue", "entry_t", "first_korean", "runup_y", "gross", "funding", "own", "hedge", "H"]].round(0).to_markdown(index=False), "\n"]
    return md


def main(action: str, name: str | None = None, registration: str | None = None) -> None:
    if action == "fingerprint":
        print(fingerprint(name))
    elif action == "run":
        text = run(name or NAME)
        print(text)
        if "**VOID" in text:
            sys.exit(2)
    elif action == "check":
        r = check(name)
        if not r["pass"]:
            sys.exit(2)
    elif action == "recheck":
        r = recheck()
        print(json.dumps(r, indent=1, default=str))
        if r["status"] != "PASS":
            sys.exit(2)
    elif action == "confirm":
        text = confirm(registration, name or "r71")
        print(text)
        if "**VOID" in text:
            sys.exit(2)
