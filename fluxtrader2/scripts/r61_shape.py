"""R61 (PLAN §8) — the money shape of R60's found sign on F1+F2: a DESCRIPTION, nothing gated, no fold spent.

    python scripts/r61_shape.py            → output/r61_shape.md, output/r61/{by_rank,by_bucket,unit,daily,triggers}.parquet, r61.json

R60's frames exactly (`cb_ext.features` on P2's panel, F1+F2 embargoed as the scored bars, the 8 liquid names, the hourly bar read from
ts_known + 5 min on). The label: the name's 1d forward return in bps (`D["fwd"]["1d"]`) minus the mean over the liquid names present at
t (≥ MIN_PAIRS) — "relative". Tables: by `cbprem_dev` rank (1 = the highest; the bars where all 8 names have a value) and by the level's
rank, with the linear spread (7 × the slope of the mean on the rank) beside the observed top minus bottom; by deviation bucket, the mean
|1d move| beside; the UNIT = the top name's forward return minus the bottom name's at every scored bar, gross and net of two maker /
taker round trips (R60's saved `move_vs_cost` at 1d), a day-block HAC se, per fold; the same at the ONE decision bar a day (00:05 UTC);
triggers at the daily bar (the top's deviation ≥ θ; the gap ≥ θ). What decides AV2 (named in the registration): WORTH A RULE if at the
daily bar, net of two maker round trips, the unconditional unit ≥ NET_BAR with u ≥ U_BAR and both folds' gross positive, OR a NAMED
trigger (top ≥ 1, gap ≥ 2) is ≥ NET_BAR net with u ≥ U_BAR on ≥ MIN_DAYS days and both folds positive; else CLOSED IN MONEY.
Validity first: (1) the relative 1d Spearman IC of `cbprem_dev` recomputed on these frames equals R60's `screen.parquet` row to 1e-6;
(2) known-at asserted again on the frames; (3) the relative label sums to zero on every bar with all names. FAIL → exit 2, VOID."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import cb_ext as cx, ceiling, coinbase as cb, folds  # noqa: E402
from ft2.ceiling import MIN_PAIRS, day_lags, hac  # noqa: E402

OUT_MD = Path("output/r61_shape.md")
OUT_DIR = Path("output/r61")
R60 = Path("output/ceiling_coinbase")
EDGES = [-np.inf, -2.0, -1.0, 0.0, 1.0, 2.0, np.inf]
LABELS = ["≤ −2", "−2 … −1", "−1 … 0", "0 … 1", "1 … 2", "≥ 2"]
TOP_THETAS = (0.5, 1.0, 1.5, 2.0)
GAP_THETAS = (1.0, 2.0, 3.0, 4.0)
NAMED = (("top", 1.0), ("gap", 2.0))          # the two triggers that may decide AV2
DAILY = (0, 5)                                # the decision bar a rule would use: 00:05 UTC
NET_BAR, U_BAR, MIN_DAYS = 15.0, 1.0, 100
LAGS = day_lags(288)
TOL = 1e-6


def frame(symbols: list[str], liquid: list[str] = cx.LIQUID, path=cb.PARQUET):
    P = ceiling.panel(symbols)
    D = ceiling.derive(P)
    F_all, U, G = cx.features(D["lr"].index, list(D["lr"].columns), liquid, path)
    return D, cx.restrict(F_all, liquid), U, G


def labels(D: dict, F: dict, liquid: list[str]) -> dict:
    """On the scored bars: the forward 1d return, the relative label (centred on the liquid names present, ≥ MIN_PAIRS), the
    deviation and the level, the count present, the day index."""
    s = D["scored"]
    idx = D["lr"].index[s]
    cols = [c for c in liquid if c in D["lr"].columns]
    fwd, dev, lvl = D["fwd"]["1d"][cols][s], F[cx.DEV][cols][s], F[cx.LVL][cols][s]
    ok = (dev.notna() & fwd.notna())
    n = ok.sum(axis=1)
    ok = ok.where(n >= MIN_PAIRS, False)
    fwd, dev, lvl = fwd.where(ok), dev.where(ok), lvl.where(ok)
    rel = fwd.sub(fwd.mean(axis=1), axis=0)
    day = (idx.floor("D") - idx[0].floor("D")).days.to_numpy()
    return {"idx": idx, "cols": cols, "fwd": fwd, "rel": rel, "dev": dev, "lvl": lvl, "n": n, "day": day, "full": (n == len(cols)).to_numpy()}


def _daily(x: pd.Series, day: np.ndarray) -> np.ndarray:
    return x.groupby(day).mean().reindex(range(int(day.max()) + 1)).to_numpy()


def _stat(x: pd.Series, day: np.ndarray) -> dict:
    """The mean of the daily means (whatever the count), the HAC se once 20 days exist."""
    dm = _daily(x, day)
    m, se, nd = hac(dm, LAGS)
    m = float(np.nanmean(dm)) if np.isfinite(dm).any() else np.nan
    return {"mean": m, "se": se, "u": m / se if se else np.nan, "days": nd, "cells": int(x.notna().sum())}


def _fold_means(x: pd.Series, idx: pd.DatetimeIndex, day: np.ndarray) -> dict:
    out = {}
    for f in folds.EXPLORATION:
        a, b = folds.bounds(f)
        m = np.asarray((idx >= a) & (idx < b))
        out[f"gross_{f}"] = hac(_daily(x[m], day[m] - day[m].min()), LAGS)[0] if m.sum() else np.nan
    return out


def by_rank(L: dict, which: str) -> pd.DataFrame:
    """Rank 1 … k by `which` (dev or lvl), 1 = the highest, on the bars with all names: the mean relative return, se, cells."""
    full = L["full"]
    x, rel, day = L[which][full], L["rel"][full], L["day"][full]
    rk = x.rank(axis=1, ascending=False, method="first")
    rows = []
    for r in range(1, len(L["cols"]) + 1):
        v = rel.where(rk == r).sum(axis=1).where((rk == r).any(axis=1))          # the one cell of rank r per bar
        rows.append({"by": which, "rank": r, **_stat(v, day)})
    out = pd.DataFrame(rows)
    slope = np.polyfit(out["rank"], out["mean"], 1)[0] if out["mean"].notna().all() else np.nan
    out["linear_spread"] = -slope * (len(out) - 1)
    out["top_minus_bottom"] = out["mean"].iloc[0] - out["mean"].iloc[-1]
    return out


def by_bucket(L: dict) -> pd.DataFrame:
    dev, rel, fwd, day = L["dev"], L["rel"], L["fwd"], L["day"]
    cells = int(dev.notna().to_numpy().sum())
    rows = []
    for lo, hi, lab in zip(EDGES[:-1], EDGES[1:], LABELS):
        m = (dev >= lo) & (dev < hi)
        v = rel.where(m).sum(axis=1) / m.sum(axis=1).replace(0, np.nan)             # the bar's mean over the cells in the bucket
        a = fwd.abs().where(m).sum(axis=1) / m.sum(axis=1).replace(0, np.nan)
        st = _stat(v, day)
        rows.append({"bucket": lab, **st, "cells": int(m.to_numpy().sum()), "share": float(m.to_numpy().sum() / cells), "abs_move_mean": float(a.mean())})
    return pd.DataFrame(rows)


def unit_series(L: dict) -> pd.DataFrame:
    """Per scored bar with ≥ MIN_PAIRS names: the top name's forward return minus the bottom name's, their deviations, the gap."""
    dev, fwd = L["dev"], L["fwd"]
    has = dev.notna().sum(axis=1) >= MIN_PAIRS
    filled = dev.where(has, 0.0).fillna(-np.inf)                                        # a bar without names: a placeholder, masked below
    top, bot = filled.idxmax(axis=1), filled.replace(-np.inf, np.inf).idxmin(axis=1)
    ii = np.arange(len(dev))
    tj, bj = dev.columns.get_indexer(top.fillna(dev.columns[0])), dev.columns.get_indexer(bot.fillna(dev.columns[0]))
    f, d = fwd.to_numpy(), dev.to_numpy()
    spread = pd.Series(f[ii, tj] - f[ii, bj], index=L["idx"]).where(has)
    return pd.DataFrame({"spread": spread, "top": top.where(has), "bottom": bot.where(has), "top_dev": pd.Series(d[ii, tj], index=L["idx"]).where(has),
                         "bottom_dev": pd.Series(d[ii, bj], index=L["idx"]).where(has), "day": L["day"]})


def unit_stats(u: pd.DataFrame, maker_rt: float, taker_rt: float, daily: bool) -> dict:
    x = u["spread"]
    if daily:
        m, se, nd = hac(x.dropna().to_numpy(), LAGS)
        st = {"mean": m, "se": se, "u": m / se if se else np.nan, "days": nd, "cells": int(x.notna().sum())}
        fm = {}
        for f in folds.EXPLORATION:
            a, b = folds.bounds(f)
            mm = np.asarray((u.index >= a) & (u.index < b))
            fm[f"gross_{f}"] = hac(x[mm].dropna().to_numpy(), LAGS)[0] if mm.sum() else np.nan
        pos = float((x.dropna() > 0).mean()) if x.notna().any() else np.nan
    else:
        st = _stat(x, u["day"].to_numpy())
        fm = _fold_means(x, u.index, u["day"].to_numpy())
        dm = _daily(x, u["day"].to_numpy())
        pos = float(np.nanmean(dm > 0)) if np.isfinite(dm).any() else np.nan
    return {"gross": st["mean"], "se": st["se"], "u": st["u"], "days": st["days"], "cells": st["cells"], "net_maker": st["mean"] - 2 * maker_rt,
            "net_taker": st["mean"] - 2 * taker_rt, **fm, "share_days_positive": pos}


def triggers(ud: pd.DataFrame, maker_rt: float, taker_rt: float) -> pd.DataFrame:
    rows = []
    for kind, thetas in (("top", TOP_THETAS), ("gap", GAP_THETAS)):
        for th in thetas:
            m = (ud["top_dev"] >= th) if kind == "top" else ((ud["top_dev"] - ud["bottom_dev"]) >= th)
            st = unit_stats(ud[m], maker_rt, taker_rt, daily=True)
            rows.append({"trigger": kind, "theta": th, "named": (kind, th) in NAMED, **st})
    return pd.DataFrame(rows)


def decide(daily: dict, trig: pd.DataFrame) -> tuple[str, str]:
    both = lambda r: all(np.isfinite(r[f"gross_{f}"]) and r[f"gross_{f}"] > 0 for f in folds.EXPLORATION)        # noqa: E731
    if daily["net_maker"] >= NET_BAR and daily["u"] >= U_BAR and both(daily):
        return "WORTH A RULE", "the unconditional daily unit"
    for _, r in trig[trig["named"]].iterrows():
        if r["net_maker"] >= NET_BAR and r["u"] >= U_BAR and r["days"] >= MIN_DAYS and both(r):
            return "WORTH A RULE", f"the trigger {r['trigger']} ≥ {r['theta']:g}"
    return "CLOSED IN MONEY", "neither the unconditional daily unit nor a named trigger reaches net maker ≥ +15 with u ≥ 1 and both folds positive"


def validity(D: dict, F: dict, U: pd.DataFrame, G: pd.DataFrame, L: dict, liquid: list[str], r60: Path = R60) -> dict:
    v = {"registration": "R61", "folds": list(folds.EXPLORATION), "scored_bars": int(D["scored"].sum()), "names": L["cols"], "bars_with_all_names": int(L["full"].sum())}
    if not (r60 / "screen.parquet").exists() or not (r60 / "move_vs_cost.parquet").exists():
        v["reproduction"] = {"status": "MISSING", "note": f"{r60}/screen.parquet or move_vs_cost.parquet not found"}
    else:
        sc, _ = ceiling.ic_screen(D, {cx.DEV: F[cx.DEV]}, set())
        new = sc[(sc["bet"] == "relative") & (sc["horizon"] == "1d")].iloc[0]
        old = pd.read_parquet(r60 / "screen.parquet")
        old = old[(old["feature"] == cx.DEV) & (old["bet"] == "relative") & (old["horizon"] == "1d")].iloc[0]
        diff = {c: float(abs(new[c] - old[c])) for c in ("ic", "t")}
        mv = pd.read_parquet(r60 / "move_vs_cost.parquet")
        mv = mv[(mv["bet"] == "relative") & (mv["horizon"] == "1d")].iloc[0]
        v["reproduction"] = {"status": "PASS" if all(d <= TOL for d in diff.values()) else "FAIL", "ic_this_run": float(new["ic"]), "ic_r60": float(old["ic"]),
                             "max_abs_diff": diff, "maker_rt": float(mv["maker_rt"]), "taker_rt": float(mv["taker_rt"])}
    v["known_at"] = cx.known_at(F, U, G, D["scored"], liquid, n_check=500)
    centred = float(L["rel"][L["full"]].sum(axis=1).abs().max()) if L["full"].any() else np.nan
    v["centred"] = {"status": "PASS" if np.isfinite(centred) and centred <= TOL else "FAIL", "max_abs_row_sum": centred}
    v["status"] = "PASS" if all(v[k]["status"] == "PASS" for k in ("reproduction", "known_at", "centred")) else "FAIL"
    return v


def run(symbols: list[str], liquid: list[str] = cx.LIQUID, path=cb.PARQUET, r60: Path = R60, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("panel, R60's frames…", flush=True)
    D, F, U, G = frame(symbols, liquid, path)
    L = labels(D, F, liquid)
    print("validity…", flush=True)
    v = validity(D, F, U, G, L, liquid, r60)
    (out_dir / "r61.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# R61 — the money shape of R60's found sign on F1+F2 (`scripts/r61_shape.py`; a description, nothing gated)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed), R60's cells; the names {', '.join(L['cols'])}; {int(D['scored'].sum()):,} scored bars, "
            f"{int(L['full'].sum()):,} with all names. The label: the 1d forward return (bps) minus the liquid names' mean at t.\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        out_md.write_text("".join(head + ["\n**The read is VOID.**\n"]))
        print(f"validity FAIL — void; wrote {out_md}", flush=True)
        raise SystemExit(2)
    maker_rt, taker_rt = v["reproduction"]["maker_rt"], v["reproduction"]["taker_rt"]
    print("the tables…", flush=True)
    br = pd.concat([by_rank(L, "dev"), by_rank(L, "lvl")], ignore_index=True)
    bb = by_bucket(L)
    u = unit_series(L)
    every = unit_stats(u, maker_rt, taker_rt, daily=False)
    ud = u[(u.index.hour == DAILY[0]) & (u.index.minute == DAILY[1])]
    daily = unit_stats(ud, maker_rt, taker_rt, daily=True)
    tr = triggers(ud, maker_rt, taker_rt)
    verdict, why = decide(daily, tr)
    res = {"verdict": verdict, "why": why, "every_bar": every, "daily": daily, "maker_rt": maker_rt, "taker_rt": taker_rt, "net_bar": NET_BAR, "u_bar": U_BAR, "min_days": MIN_DAYS,
           "linear_spread_dev": float(br[br["by"] == "dev"]["linear_spread"].iloc[0]), "top_minus_bottom_dev": float(br[br["by"] == "dev"]["top_minus_bottom"].iloc[0]),
           "linear_spread_lvl": float(br[br["by"] == "lvl"]["linear_spread"].iloc[0]), "top_minus_bottom_lvl": float(br[br["by"] == "lvl"]["top_minus_bottom"].iloc[0])}
    v["result"] = res
    (out_dir / "r61.json").write_text(json.dumps(v, indent=1, default=str))
    br.to_parquet(out_dir / "by_rank.parquet", index=False)
    bb.to_parquet(out_dir / "by_bucket.parquet", index=False)
    u.reset_index().rename(columns={"index": "t"}).to_parquet(out_dir / "unit.parquet", index=False)
    ud.reset_index().rename(columns={"index": "t"}).to_parquet(out_dir / "daily.parquet", index=False)
    tr.to_parquet(out_dir / "triggers.parquet", index=False)
    show = lambda df, digits=2: df.round(digits).to_markdown(index=False)      # noqa: E731
    ue = pd.DataFrame([{"where": "every scored bar", **every}, {"where": f"the daily bar {DAILY[0]:02d}:{DAILY[1]:02d} UTC", **daily}])
    md = head + [
        f"\n## What it decides (AV2): **{verdict}** — {why}\n",
        f"\nThe unit (the top name by `cbprem_dev` long, the bottom short, a day): at the daily bar gross {daily['gross']:+.1f} bps (se {daily['se']:.1f}, u {daily['u']:.2f}, "
        f"{daily['days']} days; F1 {daily['gross_F1']:+.1f}, F2 {daily['gross_F2']:+.1f}), net of two maker round trips ({maker_rt:.2f} each) {daily['net_maker']:+.1f}, "
        f"net taker {daily['net_taker']:+.1f}; {daily['share_days_positive']:.0%} of days positive. At every scored bar gross {every['gross']:+.1f} (se {every['se']:.1f}, u {every['u']:.2f}), "
        f"net maker {every['net_maker']:+.1f}. The linear spread implied by the rank means {res['linear_spread_dev']:+.1f} against the observed top minus bottom "
        f"{res['top_minus_bottom_dev']:+.1f} (by the level's rank: {res['linear_spread_lvl']:+.1f} / {res['top_minus_bottom_lvl']:+.1f}). The bar for a rule, named in the registration: "
        f"net maker ≥ +{NET_BAR:.0f} with u ≥ {U_BAR:.0f} and both folds positive (≥ {MIN_DAYS} days on a named trigger).\n",
        "\n## The unit, every bar and the daily bar\n", show(ue), "\n",
        "\n## Triggers at the daily bar (the named two decide; the rest describe the shape)\n", show(tr), "\n",
        "\n## By rank (1 = the highest), on the bars with all names — by the deviation and by the level\n", show(br), "\n",
        "\n## By deviation bucket, every scored bar — the relative return and the size of the move\n", show(bb, 3), "\n"]
    out_md.write_text("".join(md))
    print(f"R61: {verdict} — {why}; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


if __name__ == "__main__":
    from ft2.__main__ import PAIRS
    run(list(PAIRS))
