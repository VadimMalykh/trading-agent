"""Decision CY1 (PLAN P8, 2026-11-19): the wide names' cost rows REFITTED on CX1's measurements, checked on held-out names, rebuilt,
and the money rows of R90, R97 (B) and R100 (B) re-priced on their SAVED fills. The method is PLAN's "CY1 — the method" block,
committed before any number here was computed. No market, no forecast and no rule is run again.

  cells    CX1's cells again with the lowest fill-fraction bin's k from the means and a censored side at its lower bound
           → output/cycost/cells.parquet
  check    `cost.wide`'s regression, every NAME weighing the same, fitted on the twelve + half of the wide names; the other
           half's tier medians of predicted / measured leg at 10,000 must lie inside 1/1.5 … 1.5 — else exit 2 → check.md
  rebuild  the final fit on all names → output/cycost/coef.json; data/cost_daily_wide.parquet re-computed from each row's own
           features (the old file kept as cost_daily_wide_before_cy1.parquet) → rebuild.md
  reexec   the saved fills re-priced by `backtest.price`'s arithmetic — the old file must reproduce the stored costs — and each
           read's own statistic on the old and the new columns → reexec.md, reexec.json, fills/"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import cost, cxcost as cx, data

OUT = Path("output/cycost")
BEFORE = data.PROC / "cost_daily_wide_before_cy1.parquet"
TARGETS = ["spread_cal_bps"] + [f"imp_{n}" for n in cx.NOTIONALS]
FEATURES = cost.WIDE_FEATURES
SRC = "proxy_wide_cy1"
TOL = 1e-6
N = 10_000


def _md5(p) -> str:
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def old_file() -> Path:
    return BEFORE if BEFORE.exists() else cost.DAILY_WIDE


# ---- the measured cells ------------------------------------------------------------------------
def k_fixed(v: pd.DataFrame) -> pd.Series:
    """CX1's calibration factors with the lowest bin taken from the MEANS (its median truth is 0: CX1's defect (e))."""
    k = v["k"].astype(float).copy()
    k[cx.F_LABELS[0]] = float(v.loc[cx.F_LABELS[0], "k_mean"])
    return k


def cells() -> pd.DataFrame:
    v = pd.read_csv(cx.OUT / "validity.csv", index_col=0)
    c = cx.cells(k_fixed(v), bound=True, cost_path=old_file())
    OUT.mkdir(parents=True, exist_ok=True)
    c.to_parquet(OUT / "cells.parquet", index=False)
    return c


def wide_rows(c: pd.DataFrame) -> pd.DataFrame:
    """The measured cells as fit rows: the cost row's features, the measured spread and impacts as the targets."""
    ok = c["has_depth"] & c["has_tape"] & c["has_cost"] & (c["range_bps"] > 0) & (c["dollar_vol"] > 0) & (c["tick_bps"] > 0)
    x = c[ok]
    o = pd.DataFrame({"symbol": x["symbol"].astype(str), "day": x["day"], **{f: x[f] for f in FEATURES}, "spread_cal_bps": x["spread_meas"],
                      **{f"imp_{n}": x[f"imp_meas_{n}"] for n in cx.NOTIONALS}, **{f"cens_{n}": x[f"cens_{n}"].astype(bool) for n in cx.NOTIONALS}})
    o["tier"] = pd.cut(o["dollar_vol"], cx.TIER_EDGES, labels=cx.TIER_LABELS, right=False)
    return o.reset_index(drop=True)


def twelve_rows() -> pd.DataFrame:
    """The twelve's tape days exactly as `cost.wide` takes them."""
    d = pd.read_parquet(cost.DAILY)
    d["symbol"] = d["symbol"].astype(str)
    reg = cost.regimes(("candles_5m_archive", "candles_5m"), sorted(set(d.loc[d["spread_src"] == "tape", "symbol"])))
    reg = reg[(reg["range_bps"] > 0) & (reg["dollar_vol"] > 0) & (reg["tick_bps"] > 0)]
    t = d[(d["spread_src"] == "tape") & (d["spread_cal_bps"] > 0)].merge(reg[["symbol", "day", "tick_bps"]], on=["symbol", "day"], how="inner")
    t = t[(t["range_bps"] > 0) & (t["dollar_vol"] > 0)]
    return t[["symbol", "day", *FEATURES, *TARGETS]].reset_index(drop=True)


# ---- the regression ----------------------------------------------------------------------------
def _X(f: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(f))] + [np.log(f[c].to_numpy(dtype="float64")) for c in FEATURES])


def fit(m: pd.DataFrame, targets: list[str] = TARGETS) -> dict[str, list[float]]:
    """`cost.wide`'s log regression per target, every NAME weighing the same (a row's weight = 1 / the name's rows with the target)."""
    out = {}
    for tg in targets:
        y = m[tg].to_numpy(dtype="float64")
        a = m[np.isfinite(y) & (y > 0)]
        w = np.sqrt(1.0 / a.groupby("symbol")[tg].transform("size").to_numpy(dtype="float64"))
        b, *_ = np.linalg.lstsq(_X(a) * w[:, None], np.log(a[tg].to_numpy(dtype="float64")) * w, rcond=None)
        out[tg] = [float(x) for x in b]
    return out


def predict(coef: dict, f: pd.DataFrame) -> pd.DataFrame:
    X = _X(f)
    o = pd.DataFrame({tg: np.exp(X @ np.asarray(b)) for tg, b in coef.items() if tg in TARGETS}, index=f.index)
    if "spread_cal_bps" in o:
        o["spread_cal_bps"] = np.maximum(o["spread_cal_bps"], f["tick_bps"].to_numpy(dtype="float64"))      # never below the day's tick
    return o


# ---- the check ---------------------------------------------------------------------------------
def halves(names) -> tuple[list[str], list[str]]:
    s = sorted(set(names))
    return s[0::2], s[1::2]                                   # (the fit half, the HELD-OUT half)


def _ratios(coef: dict, held: pd.DataFrame) -> pd.DataFrame:
    p = predict(coef, held)
    rows = []
    for t in cx.TIER_LABELS:
        r = {"tier": t}
        for n in cx.NOTIONALS:
            m = ((held["tier"] == t) & ~held[f"cens_{n}"] & np.isfinite(held[f"imp_{n}"])).to_numpy()
            pred, meas = (p["spread_cal_bps"] / 2 + p[f"imp_{n}"]).to_numpy()[m], (held["spread_cal_bps"] / 2 + held[f"imp_{n}"]).to_numpy()[m]
            if n == N:
                r["cells"], r["names"] = int(m.sum()), int(held.loc[m, "symbol"].nunique())
            r[f"ratio_{n}"] = float(np.median(pred / meas)) if m.any() else np.nan
            if n == N:
                r["ratio_of_sums"] = float(pred.sum() / meas.sum()) if m.any() else np.nan
                r["leg_pred"], r["leg_meas"] = (float(np.median(pred)), float(np.median(meas))) if m.any() else (np.nan, np.nan)
        rows.append(r)
    return pd.DataFrame(rows).set_index("tier")


def check_tables(tw: pd.DataFrame, wd: pd.DataFrame) -> dict:
    a, b = halves(wd["symbol"])
    main = _ratios(fit(pd.concat([tw, wd[wd["symbol"].isin(a)]], ignore_index=True)), wd[wd["symbol"].isin(b)])
    swap = _ratios(fit(pd.concat([tw, wd[wd["symbol"].isin(b)]], ignore_index=True)), wd[wd["symbol"].isin(a)])
    r = main.loc[cx.RULE_TIERS, f"ratio_{N}"]
    ok = bool(np.isfinite(r).all() and ((r >= 1 / cx.BAND) & (r <= cx.BAND)).all())
    return {"status": "PASS" if ok else "FAIL", "main": main, "swap": swap, "fit_names": len(a), "held_names": len(b)}


def check() -> dict:
    c = pd.read_parquet(OUT / "cells.parquet")
    tw, wd = twelve_rows(), wide_rows(c)
    t = check_tables(tw, wd)
    full = fit(pd.concat([tw, wd], ignore_index=True))
    p12 = predict(full, tw)
    twelve = pd.DataFrame({"symbol": tw["symbol"], "ratio": ((p12["spread_cal_bps"] / 2 + p12[f"imp_{N}"]) / (tw["spread_cal_bps"] / 2 + tw[f"imp_{N}"])).to_numpy()}).groupby("symbol")["ratio"].median()
    insample = _ratios(full, wd)
    cens = {str(n): int(wd[f"cens_{n}"].sum()) for n in cx.NOTIONALS}
    j = {"status": t["status"], "band": [1 / cx.BAND, cx.BAND], "tape_days_of_the_twelve": int(len(tw)), "wide_cells": int(len(wd)), "wide_names": int(wd["symbol"].nunique()),
         "fit_names": t["fit_names"], "held_names": t["held_names"], "cells_at_the_lower_bound": cens,
         "held_out_ratio_10000": t["main"][f"ratio_{N}"].to_dict(), "swapped_ratio_10000": t["swap"][f"ratio_{N}"].to_dict(), "sample_md5": _md5(cx.SAMPLE)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "check.json").write_text(json.dumps(j, indent=1))
    md = ["# CY1 — the check of the refitted cost proxy on HELD-OUT wide names (PLAN P8 decision CY1)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
          f"\n## {t['status']} — the four rule tiers' medians of predicted / measured leg at 10,000 on the held-out half must lie inside 1/{cx.BAND} … {cx.BAND}\n",
          f"\nFit set: {len(tw):,} tape days of the twelve + the measured cells of {t['fit_names']} wide names; held out: {t['held_names']} names. Cells entering at the lower bound "
          f"(the order above the ±1 % band) by notional: {cens} — in the fit, not in the ratios.\n",
          "\n## The held-out half (the gate)\n", t["main"].round(3).to_markdown(), "\n", "\n## The halves swapped (described)\n", t["swap"].round(3).to_markdown(), "\n",
          "\n## The final fit (all names) on its own cells (described — in sample)\n", insample.round(3).to_markdown(), "\n",
          "\n## The twelve under the final fit: median predicted / actual leg at 10,000 a pair (described — they are never priced by this file)\n", twelve.round(3).to_frame().T.to_markdown(), "\n"]
    (OUT / "check.md").write_text("\n".join(md))
    print("\n".join(md), flush=True)
    if t["status"] != "PASS":
        print("CY1 check FAIL — nothing is rebuilt, nothing re-priced", flush=True)
        raise SystemExit(2)
    return j


# ---- the rebuild -------------------------------------------------------------------------------
def tape_symbols() -> set[str]:
    """The names `backtest.load_costs` prices from the tape's files — the wide file's rows of these are never read."""
    s = set(pd.read_parquet(cost.DAILY, columns=["symbol"])["symbol"].astype(str))
    if cost.DAILY_PRE.exists():
        s |= set(pd.read_parquet(cost.DAILY_PRE, columns=["symbol"])["symbol"].astype(str))
    return s


def apply(w: pd.DataFrame, coef: dict, keep: set[str]) -> pd.DataFrame:
    """The wide file with the coefficients' targets re-computed from each row's own features; rows of `keep` untouched."""
    o = w.copy()
    sym = o["symbol"].astype(str)
    m = (~sym.isin(keep) & (o["range_bps"] > 0) & (o["dollar_vol"] > 0) & (o["tick_bps"] > 0)).to_numpy()
    p = predict(coef, o[m])
    for tg in p.columns:
        o.loc[m, tg] = p[tg].to_numpy()
    src = o["spread_src"].astype(str).to_numpy(dtype=object)
    src[m] = SRC
    o["spread_src"] = pd.Categorical(src) if str(w["spread_src"].dtype) == "category" else src
    return o


def rebuild() -> str:
    j = json.loads((OUT / "check.json").read_text())
    if j["status"] != "PASS":
        raise SystemExit("the check did not pass: nothing is rebuilt")
    c = pd.read_parquet(OUT / "cells.parquet")
    tw, wd = twelve_rows(), wide_rows(c)
    coef = fit(pd.concat([tw, wd], ignore_index=True))
    meta = {"decision": "CY1", "features": ["const", *FEATURES], "coef": coef, "tape_days_of_the_twelve": int(len(tw)), "wide_cells": int(len(wd)), "wide_names": int(wd["symbol"].nunique()),
            "sample_md5": _md5(cx.SAMPLE), "weights": "every name the same", "spread_floor": "the day's tick"}
    (OUT / "coef.json").write_text(json.dumps(meta, indent=1))
    if not BEFORE.exists():
        shutil.copy2(cost.DAILY_WIDE, BEFORE)
    w = pd.read_parquet(BEFORE)
    keep = tape_symbols()
    o = apply(w, coef, keep)
    rest = [x for x in w.columns if x not in (*TARGETS, "spread_src")]
    same = bool(len(o) == len(w) and list(o.columns) == list(w.columns) and o[rest].equals(w[rest]))
    changed = (o["spread_src"].astype(str) == SRC).to_numpy()
    if not same:
        raise SystemExit("the rebuild changed a column it must not: nothing written")
    tmp = cost.DAILY_WIDE.with_suffix(".cy1.tmp")
    o.to_parquet(tmp, index=False)
    tmp.replace(cost.DAILY_WIDE)
    x = pd.DataFrame({"year": pd.DatetimeIndex(w["day"]).year, "tier": pd.cut(w["dollar_vol"], cx.TIER_EDGES, labels=cx.TIER_LABELS, right=False),
                      "old": (w["spread_cal_bps"] / 2 + w[f"imp_{N}"]).to_numpy(), "new": (o["spread_cal_bps"] / 2 + o[f"imp_{N}"]).to_numpy(),
                      "old_imp": w[f"imp_{N}"].to_numpy(), "new_imp": o[f"imp_{N}"].to_numpy(), "old_spread": w["spread_cal_bps"].to_numpy(), "new_spread": o["spread_cal_bps"].to_numpy()})[changed]
    by = x.groupby(["year", "tier"], observed=True).agg(rows=("old", "size"), leg_old=("old", "median"), leg_new=("new", "median"), imp_old=("old_imp", "median"), imp_new=("new_imp", "median"),
                                                         spread_old=("old_spread", "median"), spread_new=("new_spread", "median"))
    by["new_over_old"] = by["leg_new"] / by["leg_old"]
    cross = int((o.loc[changed, f"imp_{N}"] > w.loc[changed, "imp_25000"]).sum()) if "imp_25000" in w else -1
    text = "\n".join(["# CY1 — the wide names' cost rows rebuilt from the refitted proxy (PLAN P8 decision CY1)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
                      f"\n{len(w):,} rows, {w['symbol'].nunique()} names; re-computed {int(changed.sum()):,} rows of {o.loc[changed, 'symbol'].nunique()} names (`spread_src` = `{SRC}`); "
                      f"untouched {int((~changed).sum()):,} rows (names priced from the tape's own files). Every other column identical: {same}. "
                      f"Rows where the new impact at 10,000 exceeds the OLD impact at 25,000 (the larger notionals were not measured and keep their columns): {cross:,}.\n",
                      f"\nold file `{BEFORE}` md5 {_md5(BEFORE)}; new file `{cost.DAILY_WIDE}` md5 {_md5(cost.DAILY_WIDE)}.\n",
                      "\n## Coefficients (log target on const, log range_bps, log dollar_vol, log tick_bps; every name the same weight)\n",
                      pd.DataFrame(coef, index=["const", *FEATURES]).T.round(4).to_markdown(), "\n",
                      "\n## The taker leg beyond the fee at 10,000 (half-spread + impact, bps), medians of the re-computed rows by year and turnover tier\n", by.round(3).to_markdown(), "\n"])
    (OUT / "rebuild.md").write_text(text)
    print(text, flush=True)
    return text


# ---- the re-execution on the saved fills -------------------------------------------------------
def leg_table(w: pd.DataFrame, keep: set[str]) -> pd.Series:
    """`backtest.load_costs`'s taker leg (half the calibrated spread + impact at 10,000) of the wide file's rows, by (symbol, day)."""
    w = w[~w["symbol"].astype(str).isin(keep)]
    return pd.Series((w["spread_cal_bps"] / 2 + w[f"imp_{N}"]).to_numpy(), index=pd.MultiIndex.from_arrays([w["symbol"].astype(str).to_numpy(), pd.DatetimeIndex(pd.to_datetime(w["day"], utc=True)).as_unit("ns")]))


def other_cost(f: pd.DataFrame, legs: pd.Series) -> np.ndarray:
    """`backtest.price`'s other cost of a taker position: the entry day's leg + the exit day's leg × exit price / entry price."""
    sym = f["symbol"].astype(str).to_numpy()
    day = lambda c: pd.DatetimeIndex(pd.to_datetime(f[c], utc=True)).floor("D").as_unit("ns")      # noqa: E731
    e = legs.reindex(pd.MultiIndex.from_arrays([sym, day("entry_t")])).to_numpy()
    x = legs.reindex(pd.MultiIndex.from_arrays([sym, day("exit_t")])).to_numpy()
    return e + x * (f["exit_px"].to_numpy(dtype="float64") / f["entry_px"].to_numpy(dtype="float64"))


def reprice(f: pd.DataFrame, old: pd.Series, new: pd.Series, keep: set[str]) -> tuple[pd.DataFrame, dict]:
    """The fills with the wide names' other cost replaced; (fills, the validity of the arithmetic on the OLD file)."""
    stored = f["other_cost_bps"].to_numpy(dtype="float64")
    wide = (~f["symbol"].astype(str).isin(keep)).to_numpy() & np.isfinite(stored)
    again, fresh = other_cost(f, old), other_cost(f, new)
    dev = np.abs(again[wide] - stored[wide])
    v = {"positions": int(len(f)), "priced": int(np.isfinite(f["net_bps"]).sum()), "wide_positions": int(wide.sum()), "old_file_max_dev_bps": float(np.nanmax(dev)) if wide.any() else 0.0,
         "old_file_unmatched": int((~np.isfinite(again[wide])).sum()), "new_file_unmatched": int((~np.isfinite(fresh[wide])).sum())}
    v["ok"] = bool(v["old_file_unmatched"] == 0 and v["new_file_unmatched"] == 0 and v["old_file_max_dev_bps"] <= TOL)
    g = f.copy()
    new_other = np.where(wide, fresh, stored)
    delta = stored - new_other
    g["other_cost_bps"] = new_other
    for c in ("net_bps", "hedged_net_bps"):
        g[c] = g[c].to_numpy(dtype="float64") + np.where(wide, delta, 0.0)
    v["other_old_mean"], v["other_new_mean"] = float(np.nanmean(stored[np.isfinite(f["net_bps"])])), float(np.nanmean(new_other[np.isfinite(f["net_bps"])]))
    return g, v


def _close(a: float, b: float, tol: float = 0.05) -> bool:
    return bool(np.isfinite(a) and np.isfinite(b) and abs(a - b) <= tol)


def reexec() -> dict:
    from . import allbook as ab, backtest as bt, folds, next60 as n6
    if not BEFORE.exists():
        raise SystemExit("no before-copy: the rebuild has not run")
    w_new = pd.read_parquet(cost.DAILY_WIDE)
    if not (w_new["spread_src"].astype(str) == SRC).any():
        raise SystemExit("the cost file is not the rebuilt one")
    keep = tape_symbols()
    old, new = leg_table(pd.read_parquet(BEFORE), keep), leg_table(w_new, keep)
    (OUT / "fills").mkdir(parents=True, exist_ok=True)
    res, md = {"old_file_md5": _md5(BEFORE), "new_file_md5": _md5(cost.DAILY_WIDE)}, []

    # R90 — the hourly long-top / short-bottom book on F5, the gate the unhedged net a trade
    f = pd.read_parquet(ab.FILLS90)
    g, v = reprice(f, old, new, keep)
    days = bt.scored_days(["F5"], folds.bounds("F5")[1] - bt.BAR)
    rows = []
    for label, m in (("the book, taker (the gate)", slice(None)), ("long side", f["side"] > 0), ("short side", f["side"] < 0)):
        a, b = ab.row(label, f[m], days), ab.row(label, g[m], days)
        rows.append({"row": label, "trades": a["trades"], "gross": a["gross"], "fee": a["fee"], "other_old": a["other_cost"], "other_new": b["other_cost"], "funding": a["funding"],
                     "net_old": a["net"], "se_old": a["se"], "net_new": b["net"], "se_new": b["se"], "t_new": b["t"], "verdict_old": ab.verdict(a["net"], a["se"]), "verdict_new": ab.verdict(b["net"], b["se"]),
                     "hedged_net_old": a["hedged_net"], "hedged_net_new": b["hedged_net"]})
    printed = pd.read_csv(ab.OUT / "r90" / "rows.csv").iloc[0]
    v["reproduces_printed"] = _close(rows[0]["net_old"], float(printed["net"])) and _close(rows[0]["se_old"], float(printed["se"]))
    t90 = pd.DataFrame(rows)
    if v["ok"]:
        g.to_parquet(OUT / "fills" / "r90.parquet", index=False)
    res["R90"] = {"validity": v, "rows": rows}
    md += ["\n## R90 — the hourly book on F5 (gate: the net a trade, taker)\n", f"arithmetic on the old file: {json.dumps(v)}\n", t90.round(2).to_markdown(index=False), "\n"]

    # R97 (B) — R91's rule on the members before F1, the gate the hedged net − 4 a trade
    f = pd.read_parquet(ab.OUT / ab.NAME97 / "fills.parquet")
    g, v = reprice(f, old, new, keep)
    a0, b0, mid = ab.pre_span()
    days = pd.date_range(a0, b0 - pd.Timedelta(1, "ns"), freq="D")
    so, sn = ab.hedged_stats(f, days, mid), ab.hedged_stats(g, days, mid)
    so["verdict"], sn["verdict"] = ab.verdict91(so["mean"], so["se"], so["first_half"], so["last_half"]), ab.verdict91(sn["mean"], sn["se"], sn["first_half"], sn["last_half"])
    gate = json.loads((ab.OUT / ab.NAME97 / "gate.json").read_text())
    v["reproduces_printed"] = _close(so["mean"], float(gate["mean"]), 1e-6) and _close(so["se"], float(gate["se"]), 1e-6)
    p = f.dropna(subset=["net_bps"])
    extra = {"G": float((p["hedged_bps"] + p["funding_bps"]).mean()), "fee": float(p["fee_bps"].mean())}
    if v["ok"]:
        g.to_parquet(OUT / "fills" / "r97.parquet", index=False)
    res["R97 (B)"] = {"validity": v, "old": so, "new": sn, **extra}
    md += ["\n## R97 (B) — R91's hourly rule on the members before F1 (gate: the hedged net − 4 a trade)\n", f"arithmetic on the old file: {json.dumps(v)}\n",
           pd.DataFrame([{"file": "old", **so}, {"file": "rebuilt", **sn}]).round(2).to_markdown(index=False), f"\nG (before fees, spread, impact, hedge) {extra['G']:+.1f}; fee {extra['fee']:.1f}\n"]

    # R100 (B) — the twelve declared forms on the next sixty
    sd = {}
    for seg in n6.SAMPLE:
        t = pd.to_datetime(pd.read_parquet(n6.OUT / f"forecast_{seg}.parquet", columns=["t"])["t"], utc=True)
        sd[seg] = pd.date_range(t.min().floor("D"), t.max().floor("D"), freq="D")
    printed = pd.read_csv(n6.OUT / "forms.csv")
    rows, vals, by_seg, repro = [], {}, [], True
    for h, d, k in n6.FORMS:
        key = f"h{h}_d{d}_{k}"
        f = pd.read_parquet(n6.OUT / f"fills_{key}.parquet")
        g, v = reprice(f, old, new, keep)
        vals[key] = v
        ins = lambda z: z[z["seg"].isin(n6.SAMPLE)]                                # noqa: E731
        a, b = n6.form_row(ins(f), sd), n6.form_row(ins(g), sd)
        pr = printed[(printed["H"] == h) & (printed["tail"] == d) & (printed["fc"] == k)].iloc[0]
        repro &= _close(a["net"], float(pr["net"]), 1e-6) and _close(a["G"], float(pr["G"]), 1e-6)
        rows.append({"H": h, "tail": d, "fc": k, "positions": a["positions"], "G": a["G"], "G_se": a["G_se"], "G_early": a["G_early"], "G_late": a["G_late"], "fee": a["fee"],
                     "other_old": a["other_cost"], "other_new": b["other_cost"], "net_old": a["net"], "se_old": a["net_se"], "net_new": b["net"], "se_new": b["net_se"],
                     "t_new": b["net"] / b["net_se"] if b["net_se"] else np.nan, "net_new_early": b["net_early"], "net_new_late": b["net_late"]})
        if (h, d, k) == n6.BASE:
            for seg in n6.SAMPLE:
                ra, rb = n6.form_row(f[f["seg"] == seg], {seg: sd[seg]}, early=()), n6.form_row(g[g["seg"] == seg], {seg: sd[seg]}, early=())
                by_seg.append({"seg": seg, "positions": ra["positions"], "G": ra["G"], "other_old": ra["other_cost"], "other_new": rb["other_cost"], "net_old": ra["net"], "se_old": ra["net_se"],
                               "net_new": rb["net"], "se_new": rb["net_se"]})
        if v["ok"]:
            g.to_parquet(OUT / "fills" / f"r100_{key}.parquet", index=False)
    tab = pd.DataFrame(rows)
    a_ok = str(json.loads((n6.OUT / "a.json").read_text())["verdict"]).startswith("CONFIRMED")
    ch = n6.choose(tab[["H", "tail", "fc", "G", "G_se", "G_early", "G_late"]], a_ok)
    allv = {"ok": bool(all(x["ok"] for x in vals.values())), "reproduces_printed": bool(repro), "old_file_max_dev_bps": float(max(x["old_file_max_dev_bps"] for x in vals.values())),
            "wide_positions_share_base": vals["h1_d10_raw"]["wide_positions"] / max(vals["h1_d10_raw"]["positions"], 1)}
    res["R100 (B)"] = {"validity": allv, "forms": rows, "base_by_segment": by_seg, "choice": {"winner": ch["winner"], "why": ch["why"]}}
    md += ["\n## R100 (B) — the twelve declared forms on the next sixty (G = before fees, spread, impact and the hedge; net = after all)\n", f"arithmetic on the old file: {json.dumps(allv)}\n",
           f"\nThe choice (on G — the costs do not enter it): {'WINNER ' + str(ch['winner']) if ch['winner'] else 'NO WINNER'} — {ch['why']}\n", tab.round(2).to_markdown(index=False), "\n",
           "\n### The base by segment\n", pd.DataFrame(by_seg).round(2).to_markdown(index=False), "\n"]

    good = all(res[k]["validity"]["ok"] and res[k]["validity"]["reproduces_printed"] for k in ("R90", "R97 (B)", "R100 (B)"))
    res["status"] = "PASS" if good else "FAIL"
    head = ["# CY1 — the money rows of R90, R97 (B), R100 (B) re-priced on the rebuilt cost rows (PLAN P8 decision CY1)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n## Validity — read first: **{res['status']}** (the old file reproduces every stored cost to {TOL:g} bps, and the old columns give the printed numbers again)\n",
            f"\nold cost file md5 {res['old_file_md5']}; rebuilt {res['new_file_md5']}. The same saved positions; only the wide names' spread-and-impact cost and the nets change. "
            "A re-priced row licenses nothing (PLAN, CY1's method (7)).\n"]
    (OUT / "reexec.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "reexec.md").write_text("\n".join(head + md))
    print("\n".join(head + md), flush=True)
    if not good:
        raise SystemExit(2)
    return res


def main(action: str) -> None:
    if action == "cells":
        c = cells()
        w = wide_rows(c)
        print(f"{len(c):,} name-days; fit rows {len(w):,} ({w['symbol'].nunique()} names); at the lower bound by notional: { {n: int(w[f'cens_{n}'].sum()) for n in cx.NOTIONALS} }")
    elif action == "check":
        check()
    elif action == "rebuild":
        rebuild()
    elif action == "reexec":
        reexec()
    else:
        raise SystemExit(f"unknown action {action}")
