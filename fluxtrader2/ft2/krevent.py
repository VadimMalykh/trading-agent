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
def fingerprint() -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    fp = krlist.fingerprint()
    fp.to_csv(FP_BEFORE, index=False)
    return f"{len(fp)} names of {krlist.SLICE} fingerprinted → {FP_BEFORE}"


def check() -> dict:
    if not FP_BEFORE.exists():
        raise SystemExit(f"krevent check: no fingerprint before at {FP_BEFORE} — run `ft2 krevent fingerprint` before the run")
    before = pd.read_csv(FP_BEFORE)
    r = krlist.fingerprint_check(before, after_fn=krlist.fingerprint)
    r["status"] = "PASS" if r["pass"] else "FAIL"
    FP_CHECK.write_text(json.dumps(r, indent=1, default=str))
    v = OUT / NAME / "validity.json"
    if v.exists():                                                   # the run's validity record carries the after-check once it exists
        V = json.loads(v.read_text())
        V["1_fingerprint_after"] = r["status"]
        v.write_text(json.dumps(V, indent=1))
    print(f"fingerprint after the run: {r['status']} — {r['names_before']} names before, {r['names_after']} after, {len(r['changed'])} changed → {FP_CHECK}")
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


def main(action: str, name: str | None = None) -> None:
    if action == "fingerprint":
        print(fingerprint())
    elif action == "run":
        text = run(name or NAME)
        print(text)
        if "**VOID" in text:
            sys.exit(2)
    elif action == "check":
        r = check()
        if not r["pass"]:
            sys.exit(2)
