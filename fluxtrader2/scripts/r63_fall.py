"""R63 (PLAN §8): BTC's fall and the high-beta names, confirmed ONCE on F3+F4's members — after BTC's last hour fell, do the names with the
highest beta to it give back part of that fall against their peers over the next 1h / 4h / 1d? R50's `bx_1h` on the after-fall half of the
bars, the sign fixed NEGATIVE from R50's described row; the after-rise half described beside, outside the family.

    python scripts/r63_fall.py run [--jobs 4]      → output/audit/r63_fall/{validity.json, validity_f12.csv, result.json, result.md, rows.csv, shifts.parquet}

order      (1) the F1+F2 reproduction: this module's mask path on R50's stage-1 frame (R18's cells) must give R50's `reference.csv` rows
           "bx_1h after a BTC fall / rise" (ic, t_hac, cells) at 1h / 4h / 1d to 1e-6 — before any F3+F4 bar is loaded; FAIL → exit 2, nothing
           else is touched. (5) the guard: the rows (R63, F3) and (R63, F4) are appended to output/backtest/confirmation_reads.csv, and the
           run refuses if R63 is already there (once). Then F3+F4's members are loaded (R50's `cells_members` on the frozen csv), (2) R50's
           stage-2 checks, (3) the mask asserted; FAIL → exit 2 and the read is VOID (the guard rows stay: a rerun needs them removed by
           hand and the void recorded in PLAN). Only then the family is computed.
feature    R50's `bx_1h` = beta_btc × b_1h / σ_1h on the hourly grid (`r50_btchour.features`), masked to the bars where b_1h < 0.
statistic  R50's: the cross-sectional Spearman per bar, averaged per day; every whole-day shift ≥ GAP = 32 days; centre, se, IC_c, u; per shift
           the largest SIGNED u (−u) over the three cells → the family-wise p, one-sided. The HAC t beside.
gate       per cell CLEARS if −u ≥ 2 AND p_family ≤ 0.05; CLOSED if |IC_c| + 1.96 se < 0.02; else NOT DETECTABLE (MDE 2.8 se). CONFIRMED if any
           cell CLEARS. A CLEARS at or above its money bar (0.14 / 0.045 / 0.033, R50's `MONEY_BAR["outside"]`) licenses ONE priced registration
           on F5; below it, a confirmed fact, nothing priced.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import audit, audit_index, folds  # noqa: E402
from ft2 import backtest as bt  # noqa: E402
from ft2.ceiling import MDE_K, Z_TOP, hac, day_lags  # noqa: E402


def _r50():
    spec = importlib.util.spec_from_file_location("r50_btchour", Path(__file__).resolve().parent / "r50_btchour.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


R50 = _r50()
REG = "R63"
OUT = audit.OUT / "r63_fall"
REF_CSV = R50.OUT / "reference.csv"                          # R50's described rows (stage 1, F1+F2)
FEATURE = "bx_1h"
HOLDS = R50.HOLDS                                            # (12, 48, 288)
GAP = R50.GAP                                                # 32 days
SIGN = -1                                                    # the registered sign: the high-beta names give back part of the fall
U_BAR, P_BAR, IC_CLOSED, COVER_BAR = R50.U_BAR, R50.P_BAR, R50.IC_CLOSED, R50.COVER_BAR
MONEY_BAR = {h: R50.MONEY_BAR[("outside", h)] for h in HOLDS}
FALL, RISE = "fall", "rise"
ROW = {FALL: f"{FEATURE} after a BTC fall (b_1h < 0)", RISE: f"{FEATURE} after a BTC rise (b_1h > 0)"}
TOL = 1e-6
PARAMS = {"feature": FEATURE, "mask": "b_1h < 0", "sign": SIGN, "holds": list(HOLDS), "universe": "members_f34", "gap_days": GAP}


# ---- the halves -------------------------------------------------------------------------------------------------------------------------------
def masks(b: np.ndarray) -> dict[str, np.ndarray]:
    """The after-fall and after-rise halves of the bars; b_1h = 0 (or unknown) belongs to neither."""
    return {FALL: b < 0, RISE: b > 0}


def half(F: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    return F.where(pd.Series(mask, index=F.index), axis=0)


def half_rows(u: dict, holds=HOLDS, day: np.ndarray | None = None) -> pd.DataFrame:
    """R50's described rows by the mask path: ic and HAC t of bx_1h on each half at each hold, with the cells."""
    day = audit._day(u["grid"]) if day is None else day
    rows = []
    for h in holds:
        for side, m in masks(u["b_1h"]).items():
            ic, t_ = audit_index._ic_on(u["F"][FEATURE], u["Z"][h], day, m, hold=h)
            rows.append({"hold": h, "row": ROW[side], "ic": ic, "t_hac": t_, "cells": int(half(u["F"][FEATURE], m).notna().to_numpy().sum())})
    return pd.DataFrame(rows)


def reproduce(got: pd.DataFrame, ref: pd.DataFrame, tol: float = TOL) -> dict:
    """Validity (1): the mask path's rows against R50's reference rows (universe outside), to `tol` on ic and t_hac, the cells exact."""
    r = ref[(ref["universe"] == "outside") & ref["row"].isin(ROW.values())][["hold", "row", "ic", "t_hac", "cells"]]
    m = got.merge(r, on=["hold", "row"], how="outer", suffixes=("", "_ref"), indicator=True)
    d_ic = (m["ic"] - m["ic_ref"]).abs()
    d_t = (m["t_hac"] - m["t_hac_ref"]).abs()
    ok = bool(len(m) == len(got) == 2 * len(HOLDS) and (m["_merge"] == "both").all() and (d_ic <= tol).all() and (d_t <= tol).all() and (m["cells"] == m["cells_ref"]).all())
    return {"status": "PASS" if ok else "FAIL", "rows": int(len(m)), "max_abs_d_ic": float(d_ic.max()), "max_abs_d_t": float(d_t.max()),
            "cells_equal": bool((m["cells"] == m["cells_ref"]).all()), "table": m.drop(columns="_merge").to_dict("records")}


def mask_check(u: dict) -> dict:
    """Validity (3): every family cell at a bar with b_1h < 0, every described cell at one with b_1h > 0; the counts add up."""
    F, b = u["F"][FEATURE], u["b_1h"]
    M = masks(b)
    fall, rise = half(F, M[FALL]), half(F, M[RISE])
    at = lambda X, cond: int((X.notna().to_numpy() & ~cond[:, None]).sum())          # noqa: E731  cells of X at bars where cond fails
    n_bx = int(F.notna().to_numpy().sum())
    n_fall, n_rise = int(fall.notna().to_numpy().sum()), int(rise.notna().to_numpy().sum())
    n_zero = int((F.notna().to_numpy() & (b == 0)[:, None]).sum())
    n_unknown = n_bx - n_fall - n_rise - n_zero                                       # b_1h not finite at the bar (bx_1h is then NaN too)
    v = {"fall_cells_at_non_fall_bars": at(fall, M[FALL]), "rise_cells_at_non_rise_bars": at(rise, M[RISE]), "cells_bx": n_bx, "cells_fall": n_fall,
         "cells_rise": n_rise, "cells_b_zero": n_zero, "cells_b_unknown": n_unknown, "bars_fall": int(M[FALL].sum()), "bars_rise": int(M[RISE].sum()),
         "bars_zero": int((b == 0).sum()), "bars": int(len(b))}
    v["status"] = "PASS" if v["fall_cells_at_non_fall_bars"] == 0 and v["rise_cells_at_non_rise_bars"] == 0 and n_fall + n_rise + n_zero + n_unknown == n_bx and n_unknown == 0 and n_fall > 0 else "FAIL"
    return v


# ---- the guard --------------------------------------------------------------------------------------------------------------------------------
def guard(reads: Path = bt.READS, plan: Path = bt.PLAN, fold_names=("F3", "F4"), registration: str = REG) -> str:
    """Validity (5): the registration block exists, the folds have not been read for it; the rows are appended NOW, before any F3+F4 bar."""
    if not plan.exists() or not re.search(rf"^### {registration} ", plan.read_text(), flags=re.M):
        raise SystemExit(f"no '### {registration} ' block in {plan}: write the registration before the read")
    if reads.exists():
        r = pd.read_csv(reads)
        again = sorted(set(r.loc[r["registration"] == registration, "fold"].astype(str)) & set(fold_names))
        if again:
            print(f"{registration} has already read {again} ({reads}): a fold is read once per question — refused", flush=True)
            raise SystemExit(2)
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    reads.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"read_at": stamp, "registration": registration, "fold": list(fold_names), "strategy": f"{FEATURE}_{FALL}", "params": json.dumps(PARAMS)}
                 ).to_csv(reads, mode="a", header=not reads.exists(), index=False)
    return stamp


# ---- the statistic ----------------------------------------------------------------------------------------------------------------------------
def family(u: dict, ks: np.ndarray, day: np.ndarray, fold_names, holds=HOLDS, jobs: int = 4, sign: int = SIGN) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The three family cells (the fall half × holds, the sign fixed) and the three described rise cells under the real labels and every shift."""
    from joblib import Parallel, delayed
    M = masks(u["b_1h"])
    jobs_ = [(side, h, half(u["F"][FEATURE], M[side]), u["Z"][h]) for side in (FALL, RISE) for h in holds]
    res = Parallel(n_jobs=jobs, verbose=0)(delayed(audit_index._ic_shifts)(f"{side}:{h}", F, Z, ks, day) for side, h, F, Z in jobs_)
    d = pd.concat([r for r, _ in res], ignore_index=True)
    d[["side", "hold"]] = d["feature"].str.split(":", expand=True)
    d["hold"] = d["hold"].astype(int)
    key = ["side", "hold"]
    real = d[d["shift"] == 0].set_index(key)["ic"]
    null = d[d["shift"] > 0].copy()
    st = null.groupby(key)["ic"].agg(centre="mean", se="std")
    null = null.join(st, on=key)
    null["u"] = (null["ic"] - null["centre"]) / null["se"]
    fam = null[null["side"] == FALL]
    mx = fam.assign(su=sign * fam["u"]).groupby("shift")["su"].max()                    # per shift the largest SIGNED u over the three family cells
    dates = pd.date_range(R50.day_start(u["grid"]), periods=int(day.max()) + 1, freq="D")
    part = audit_index._parts(dates, fold_names, "index")
    parts = [p for p in dict.fromkeys(part) if p]
    n_cells = max(int(u["cell"].to_numpy().sum()), 1)
    rows = []
    for (side, h, F, Z), (_, ic_daily) in zip(jobs_, res):
        c, e = float(st.loc[(side, h), "centre"]), float(st.loc[(side, h), "se"])
        ic = float(real[(side, h)])
        ic_c = ic - c
        uu = ic_c / e if e else np.nan
        own = null[(null["side"] == side) & (null["hold"] == h)]
        m_hac, se_hac, _ = hac(ic_daily, day_lags(h))
        per_part = {p: float(np.nanmean(ic_daily[(part == p).to_numpy()])) if np.isfinite(ic_daily[(part == p).to_numpy()]).any() else np.nan for p in parts}
        is_fam = side == FALL
        su = sign * uu if is_fam else np.nan
        row = {"side": side, "feature": FEATURE, "hold": h, "family": is_fam, "sign": sign if is_fam else 0, "cells": int(F.notna().to_numpy().sum()),
               "coverage": float(F.notna().to_numpy().sum() / n_cells), "ic": ic, "centre": c, "ic_c": ic_c, "se": e, "u": uu, "signed_u": su,
               "t_hac": m_hac / se_hac if se_hac else np.nan, "days": int(np.isfinite(ic_daily).sum()), **{f"ic_{p}": per_part[p] for p in parts},
               "parts_same_sign": bool(len({np.sign(per_part[p]) for p in parts if np.isfinite(per_part[p])}) == 1),
               "lo": ic_c - 1.96 * e, "hi": ic_c + 1.96 * e, "mde": MDE_K * e, "money_bar": MONEY_BAR[h],
               "p_one_sided": (1 + int((sign * own["u"] >= su).sum())) / (len(own) + 1) if is_fam and e else np.nan,
               "p_two_sided": (1 + int((own["u"].abs() >= abs(uu)).sum())) / (len(own) + 1) if e else np.nan,
               "p_family": (1 + int((mx >= su).sum())) / (len(mx) + 1) if is_fam and e else np.nan}
        row["verdict"] = verdict(row) if is_fam else "described"
        row["licensed"] = bool(row["verdict"] == "CLEARS" and sign * ic_c >= MONEY_BAR[h])
        rows.append(row)
    return pd.DataFrame(rows), d


def verdict(r: dict) -> str:
    """The registered gate, one-sided on the fixed sign."""
    if not np.isfinite(r["u"]) or not r["se"] > 0:
        return "NOT READABLE"
    if r["signed_u"] >= U_BAR and r["p_family"] <= P_BAR:
        return "CLEARS"
    if abs(r["ic_c"]) + 1.96 * r["se"] < IC_CLOSED:
        return "CLOSED"
    return "NOT DETECTABLE"


# ---- the run ----------------------------------------------------------------------------------------------------------------------------------
def _btc_series(A: dict) -> pd.Series:
    return R50._btc(A, A)


def run(members_csv: Path | str = R50.MEMBERS_F34, fold_names=("F3", "F4"), f12_run: str = R50.RUN_F12, f12_members: str | None = None, ref_csv: Path = REF_CSV,
        out: Path = OUT, gap: int = GAP, min_shifts: int = 20, jobs: int = 4, reads: Path = bt.READS, plan: Path = bt.PLAN, holds=HOLDS, skip_f12: bool = False) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    fold_names = folds.order(fold_names)
    v: dict = {"registration": REG, "folds": list(fold_names), "holds": list(holds), "feature": FEATURE, "sign": SIGN, "params": PARAMS}
    # (1) the F1+F2 reproduction — before any F3+F4 bar
    if skip_f12:
        v["1_reproduction"] = {"status": "SKIPPED (test)"}
    else:
        ref = pd.read_csv(ref_csv)
        A1 = audit.frame(f12_run, f12_members)
        u1 = R50._universe("outside", A1, holds, _btc_series(A1))
        got = half_rows(u1, holds)
        v["1_reproduction"] = {"run": f12_run, "folds": list(A1["fold_names"]), **reproduce(got, ref)}
        got.to_csv(out / "validity_f12.csv", index=False)
        del A1, u1
        if v["1_reproduction"]["status"] != "PASS":
            v["status"] = "FAIL"
            v["void"] = "validity (1): the mask path does not reproduce R50's described rows on F1+F2 — nothing of F3+F4 was loaded; the guard rows were NOT appended"
            (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
            (out / "result.md").write_text(f"# {REG}\n\n**VOID at validity (1)** — {v['void']}\n\n```\n{json.dumps(v['1_reproduction'], indent=1, default=str)}\n```\n")
            print("validity (1) FAIL — the read is void before F3+F4", flush=True)
            raise SystemExit(2)
    # (5) the guard — the rows appended now
    v["5_guard"] = {"reads": str(reads), "read_at": guard(reads, plan, fold_names)}
    # F3+F4's members
    A = R50.cells_members(members_csv, fold_names)
    u = R50._universe("outside", A, holds, _btc_series(A))
    gv, ks, day, nd = R50._grid_checks([u], gap)
    v["2_cells"] = {**A["validity"], "cover": u["cover"][FEATURE], "cells_read": u["cells"], **gv, "cover_bar": COVER_BAR, "min_shifts": min_shifts}
    v["2_cells"]["status"] = "PASS" if (A["validity"]["status"] == "PASS" and A["validity"]["cells_not_members"] == 0 and A["validity"]["cells_outside_folds"] == 0
                                       and A["validity"]["min_names_at_a_bar"] >= 5 and u["cover"][FEATURE] >= COVER_BAR and gv["whole_days"]
                                       and gv["shifts"] == gv["shifts_expected"] and gv["shifts"] >= min_shifts) else "FAIL"
    v["3_mask"] = mask_check(u)
    v["status"] = "PASS" if v["2_cells"]["status"] == "PASS" and v["3_mask"]["status"] == "PASS" else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {REG} — BTC's fall and the high-beta names: `{FEATURE}` after a BTC fall on {'+'.join(fold_names)}'s members, read once (sign fixed {SIGN:+d})\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(u['names'])} names, {int(u['cell'].to_numpy().sum()):,} cells · {nd} days · {len(ks)} shifts (gap {gap} days)"
            f" · guard rows appended {v['5_guard']['read_at']}\n", f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps({k: v_ for k, v_ in v.items() if k != 'params'}, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "result.md").write_text("\n".join(head + [f"\n**The read is VOID at validity (2) or (3): nothing of the family was computed on {'+'.join(fold_names)}.** The guard rows stay; a rerun needs them removed by hand and the void recorded in PLAN.\n"]))
        print("validity FAIL — the read is void", flush=True)
        raise SystemExit(2)
    tab, d = family(u, ks, day, fold_names, holds, jobs)
    fam = tab[tab["family"]]
    confirmed = bool((fam["verdict"] == "CLEARS").any())
    beside = pd.DataFrame([{"hold": h, "row": "break-even IC for the top tenth, taker (these bars)", "ic": R50.COST["outside"] / (Z_TOP * 1.2533 * u["move"][h]),
                            "note": f"round trip {R50.COST['outside']} bps against a mean |move against peers| of {u['move'][h]:.0f} bps"} for h in holds])
    summary = {"registration": REG, "validity": v, "rows": tab.to_dict("records"), "confirmed": confirmed, "verdict": "CONFIRMED" if confirmed else "NOT CONFIRMED",
               "licensed": [r for r in fam.to_dict("records") if r["licensed"]], "verdicts": fam["verdict"].value_counts().to_dict(),
               "break_even_these_bars": beside.to_dict("records"), "seconds": round(time.time() - t0, 1), "written": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    (out / "result.json").write_text(json.dumps(summary, indent=1, default=str))
    tab.to_csv(out / "rows.csv", index=False)
    d.to_parquet(out / "shifts.parquet", index=False)
    (out / "result.md").write_text("\n".join(head + _report(summary, tab, beside)))
    print(f"{REG}: {summary['verdict']} ({json.dumps(summary['verdicts'])}); licensed {len(summary['licensed'])}; wrote {out}/", flush=True)
    return summary


def _report(s: dict, tab: pd.DataFrame, beside: pd.DataFrame) -> list[str]:
    show = lambda df, k=4: df.round(k).to_markdown(index=False)       # noqa: E731
    main = ["side", "hold", "cells", "coverage", "ic", "centre", "ic_c", "se", "u", "signed_u", "t_hac", "p_one_sided", "p_family", "lo", "hi", "mde", "money_bar", "verdict", "licensed"]
    parts = [c for c in tab.columns if c.startswith("ic_F")]
    more = ["side", "hold", "days", *parts, "parts_same_sign", "p_two_sided"]
    fam, des = tab[tab["family"]], tab[~tab["family"]]
    lic = s["licensed"]
    return ["\nWords: *bx_1h* is BTC's last hour through the name's 30-day beta, in the name's own hourly sigmas, here only on the bars where that hour was DOWN — "
            "negative, most negative for the highest-beta names. The registered sign is NEGATIVE: a negative IC means the most negative names (the highest beta) do best "
            "against their peers over the next hours — they give back part of the fall. *centre* is the IC when the moves come from other days, *ic_c* = IC − centre, "
            "*u* = ic_c / se, *signed_u* = −u, *p_family* the share of shifts on which the best of the three family cells did at least as well, one-sided. *money_bar*: "
            "R50's break-even IC for the top tenth at taker on the members (0.14 / 0.045 / 0.033): a CLEARS at or above it licenses one priced registration on F5; below it, "
            "a confirmed fact, nothing priced.\n",
            f"\n## The family — three cells, one-sided on the fixed sign: **{s['verdict']}** ({json.dumps(s['verdicts'])}); "
            + (f"**{len(lic)} cell(s) at or above the money bar** — one priced registration on F5 is licensed" if lic else "nothing at or above its money bar — nothing priced")
            + "\n", show(fam[main]), "\n", "\n### Parts (F3 and F4 apart; decides nothing)\n", show(fam[more]), "\n",
            "\n## Described beside — the after-rise half (sign free, outside the family)\n", show(des[[c for c in main if c not in ("signed_u", "p_one_sided", "p_family", "licensed")]]), "\n",
            show(des[more]), "\n", "\n## Described — the break-even IC on these bars (R50's formula; the gate uses the registered bars above)\n", show(beside), "\n"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["run"])
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    s = run(jobs=a.jobs)
    print((OUT / "result.md").read_text())
    return s


if __name__ == "__main__":
    main()
