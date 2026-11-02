"""Decision BY1 (2026-11-02; PLAN P8 decision BY, fact (lxxiv)) — the EXTREME trailing-day funding of a running perpetual WITHOUT the
exchange's flag, as a per-name EVENT population: the source audit, `ft2 fundep events|audit`. Nothing here joins a bar AFTER an episode's t0
to anything; no fold is read for a label; nothing is priced; nothing is registered. `scripts/by_count3.py` is the count this module is the
tested form of (524 episodes at ≥ 2 % a day on 230 names; the count's age rule reproduced as a described row).

episode    per name, the 24-hour rolling sum of the settled rate over `funding_archive` (DATA.md; `(symbol, ts) → rate, interval_h`),
           the window (ts − 24 h, ts] — the settlement's own rate counted, it is public at its stamp; t0 = the FIRST settlement at which
           |sum| ≥ THRESHOLD (2 % a day), and a new episode starts only after QUIET (14 days) without a settlement at or over the threshold
           — a run of extreme days is ONE episode, its t0 the first crossing. The name ≥ PERP_AGE (30 days) old at t0 — the EARLIER of its
           first 5m bar in `candles_5m_archive` and its first settlement (the slice holds some non-members from 2023-04 only; the first
           settlement is the better bound for them; `fundfreq` took the bar first). KNOWN-AT: t0 is the settlement's own stamp (`fundingTime`);
           `ts_known` = t0; a registration's decision bar is the first 5m bar that CLOSES after t0, the position entered one bar later.
side       `bought` when the sum is NEGATIVE (the shorts paid — a long receives the funding; 511 of 524 at the count), `sold` when positive
           (13 since 2023 — the cap is asymmetric; a described mirror, not a cell).
flags      `rate_t0` and `interval_h` (the settlement's own), `fund_1d` / `n_1d` (the sum and the rows in the window), `fund_7d`, `prior_episodes`
           and `days_since_prior` (the name's earlier episodes at this threshold), the contract's age, the fold of t0, `member_at_t0` (a member
           of the screener's block that holds t0 — F1+F2's and F3+F4's blocks; F5 has none), the FLAG: `flag_t0` / `flag_lag_h` / `flagged_7d`
           (a `fundfreq` SHORTENING of the name within ± FLAG_WINDOW of t0 — the exchange's answer; `flag_lag_h` = t0 − the shortening's stamp,
           negative when the flag came after the crossing), `cap_share_7d` / `cap_rate` (fundfreq's trigger row: the share of the 7 days'
           settlements at ≥ 95 % of the name's largest |rate| before t0).
eligible   the contract ≥ PERP_AGE old at t0 (else a launch, R28's population) and t0 inside F1 … F5; FP / F0 and after F5's end are listed
           and described, not frozen. The lists per fold pair: output/fundep/fundep_f12.csv (F1+F2, R77's), _f34.csv (F3+F4, R78's), _f5.csv
           (F5, a later confirmation's) — frozen by hand as ft2/fundep_<tag>.csv and committed BEFORE any bar after a t0 is read for anything.
audit      the frozen lists' md5 and counts (fold × side, members, the flagged, F1+F2 per month, the quantiles, the hour of day, the prior
           episodes); the ELIGIBILITY RULE run on the frozen F1+F2 list against R75's frame BEFORE a registration's thresholds are written
           (README 0o (i)): the calendar (the decision bar t0 + 5 min at or after the first member block; the 7-day exit from t0 + 10 min
           before F2's end), the bars (≥ 95 % of the 5m bars over t0 − 2 d → t0 + 8 d in the slice), the cost rows (`cost_daily_wide` on the
           entry day or the day before, else within 7 days before — R75's B_i rule) — every dropped cell NAMED with its reason; the F3+F4 and
           F5 lists' bars in hand and the (name, month) files a Data line would fetch (R78's); the described thresholds (1 %, 3 %) by fold;
           the count's age rule (the first settlement alone) beside → output/fundep/audit.md / .json, DATA.md `fund_episodes`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import data, folds, fundfreq
from . import coinbase as cb

THRESHOLD = 0.02                                   # |the 24-hour sum of the settled rate| at t0, as a fraction (0.02 = 2 % a day)
DESCRIBED = (0.01, 0.03)                           # the thresholds counted beside, never frozen
QUIET = pd.Timedelta(days=14)                      # a new episode after this long without a settlement at or over the threshold
PERP_AGE = fundfreq.PERP_AGE
WINDOW = fundfreq.WINDOW                           # t0 − 2 d → t0 + 8 d: the bars a registration in R75's frame needs
BAR = fundfreq.BAR
HOUR, DAY = fundfreq.HOUR, fundfreq.DAY
EXPECTED_BARS = fundfreq.EXPECTED_BARS
FLAG_WINDOW = pd.Timedelta(days=7)
CAP_FRAC = fundfreq.CAP_FRAC
WAIT, LATENCY = 1, 1                               # R75's: the decision bar closes at t0 + 5 min, the entry one bar later
LONGEST = pd.Timedelta(days=7)
COST_FALLBACK = pd.Timedelta(days=7)
MIN_SHARE = 0.95
TAGS = {"F1": "f12", "F2": "f12", "F3": "f34", "F4": "f34", "F5": "f5"}
FOLDS_OF = {"f12": ("F1", "F2"), "f34": ("F3", "F4"), "f5": ("F5",)}
LISTS = {tag: Path(__file__).with_name(f"fundep_{tag}.csv") for tag in ("f12", "f34", "f5")}
OUT = Path("output/fundep")
SLICE = fundfreq.SLICE
ORDER = ["pre", "FP", "F0", "F1", "F2", "F3", "F4", "F5", "post"]
LIST_COLS = ["symbol", "base", "mult", "t0", "ts_known", "fold", "side", "thr", "rate_t0", "interval_h", "fund_1d", "n_1d", "fund_7d", "prior_episodes",
             "days_since_prior", "perp_first", "perp_first_source", "perp_age_days", "member_at_t0", "flag_t0", "flag_lag_h", "flagged_7d", "cap_share_7d", "cap_rate"]
DATE_COLS = ("t0", "ts_known", "perp_first", "flag_t0")


def member_symbols() -> pd.DataFrame:
    return fundfreq.member_symbols()


def fold_of(ts: pd.Timestamp) -> str:
    f = fundfreq.fold_of(ts)
    if f is not None:
        return f
    return "pre" if ts < folds.bounds("FP", embargoed=False)[0] else "post"


# ---- the trailing sums and the episodes -----------------------------------------------------------------------------------------
def trailing(S: pd.DataFrame) -> pd.DataFrame:
    """Per settlement row the 24-hour and 7-day sums of the rate over (ts − window, ts] and the rows in the day's window."""
    S = S.sort_values(["symbol", "ts"]).reset_index(drop=True)
    parts = []
    for sym, g in S.groupby("symbol", sort=False):
        x = g.set_index("ts")["rate"]
        d1 = x.rolling("24h").sum()
        parts.append(pd.DataFrame({"fund_1d": d1.to_numpy(), "n_1d": x.rolling("24h").count().to_numpy().astype(int), "fund_7d": x.rolling("7D").sum().to_numpy()}, index=g.index))
    T = pd.concat(parts).sort_index()
    return pd.concat([S, T], axis=1)


def first_stamps(S: pd.DataFrame) -> pd.DataFrame:
    """Per symbol the contract's first known stamp: the EARLIER of its first 5m bar in the slice and its first settlement, with the source."""
    syms = sorted(set(S["symbol"]))
    pf = fundfreq.perp_first(syms, S).set_index("symbol")
    fs = S.groupby("symbol")["ts"].min()
    out = []
    for s in syms:
        bar_t, src = pf.loc[s, "perp_first"], pf.loc[s, "perp_first_source"]
        set_t = fs[s]
        if src == "archive 5m" and pd.notna(bar_t) and bar_t <= set_t:
            out.append({"symbol": s, "perp_first": bar_t, "perp_first_source": "archive 5m", "first_settlement": set_t})
        else:
            out.append({"symbol": s, "perp_first": set_t, "perp_first_source": "funding", "first_settlement": set_t})
    return pd.DataFrame(out).set_index("symbol")


def episodes(T: pd.DataFrame, thr: float, first: pd.Series) -> pd.DataFrame:
    """The episodes at `thr`: per name the first settlement with |fund_1d| ≥ thr after QUIET without one, the name ≥ PERP_AGE old by `first`
    (symbol → stamp). Returns t0 and the settlement's own flags; the prior episodes counted."""
    rows = []
    for sym, g in T.groupby("symbol", sort=False):
        f0 = first.get(sym, pd.NaT)
        if pd.isna(f0):
            continue
        hit = g[(g["fund_1d"].abs() >= thr) & ((g["ts"] - f0) >= PERP_AGE)]
        last, prior, prev_t0 = None, 0, None
        for r in hit.itertuples(index=False):
            if last is None or (r.ts - last) > QUIET:
                rows.append({"symbol": sym, "t0": r.ts, "rate_t0": float(r.rate), "interval_h": float(r.interval_h), "fund_1d": float(r.fund_1d), "n_1d": int(r.n_1d),
                             "fund_7d": float(r.fund_7d), "prior_episodes": prior, "days_since_prior": float((r.ts - prev_t0) / DAY) if prev_t0 is not None else np.nan})
                prior += 1
                prev_t0 = r.ts
            last = r.ts
    cols = ["symbol", "t0", "rate_t0", "interval_h", "fund_1d", "n_1d", "fund_7d", "prior_episodes", "days_since_prior"]
    E = pd.DataFrame(rows, columns=cols)
    if len(E):
        E["t0"] = pd.to_datetime(E["t0"], utc=True)
    E["thr"] = thr
    E["side"] = np.where(E["fund_1d"] < 0, "bought", "sold")
    return E.sort_values(["t0", "symbol"]).reset_index(drop=True)


def cap_rows(E: pd.DataFrame, S: pd.DataFrame) -> pd.DataFrame:
    """fundfreq's trigger row per episode: the largest |rate| the name settled before t0 and the share of the 7 days' settlements at ≥ 95 % of it."""
    by = {s: g for s, g in S.groupby("symbol", sort=False)}
    share, cap = [], []
    for r in E.itertuples(index=False):
        g = by[r.symbol]
        before = g[g["ts"] < r.t0]
        c = before["rate"].abs().max() if len(before) else np.nan
        d7 = before[before["ts"] >= r.t0 - 7 * DAY]
        cap.append(float(c) if c == c else np.nan)
        share.append(float((d7["rate"].abs() >= CAP_FRAC * c).mean()) if len(d7) and c and c > 0 else np.nan)
    return pd.DataFrame({"cap_share_7d": share, "cap_rate": cap}, index=E.index)


def flag_join(E: pd.DataFrame, S: pd.DataFrame) -> pd.DataFrame:
    """The exchange's flag beside each episode: the nearest `fundfreq` SHORTENING of the name within ± FLAG_WINDOW of t0."""
    C = fundfreq.changes(S)
    sh = C[C["dir"] == "shorter"] if len(C) else C
    by = {s: pd.DatetimeIndex(g["t0"]).sort_values() for s, g in sh.groupby("symbol")} if len(sh) else {}
    ft, lag = [], []
    for r in E.itertuples(index=False):
        t = by.get(r.symbol)
        if t is None or not len(t):
            ft.append(pd.NaT); lag.append(np.nan); continue
        d = (t - r.t0)
        i = int(np.argmin(np.abs(d.to_numpy())))
        if abs(d[i]) <= FLAG_WINDOW:
            ft.append(t[i]); lag.append(float((r.t0 - t[i]) / HOUR))
        else:
            ft.append(pd.NaT); lag.append(np.nan)
    out = pd.DataFrame({"flag_t0": pd.to_datetime(pd.Series(ft, index=E.index), utc=True), "flag_lag_h": lag}, index=E.index)
    out["flagged_7d"] = out["flag_t0"].notna()
    return out


def events(thr: float = THRESHOLD, write: bool = True) -> pd.DataFrame:
    S = fundfreq.settlements()
    T = trailing(S)
    FS = first_stamps(S)
    E = episodes(T, thr, FS["perp_first"])
    M = member_symbols()
    E["base"] = E["symbol"].map(cb.base)
    E["mult"] = E["symbol"].map(cb.mult_of)
    E["perp_first"] = E["symbol"].map(FS["perp_first"])
    E["perp_first_source"] = E["symbol"].map(FS["perp_first_source"])
    E["perp_age_days"] = (E["t0"] - E["perp_first"]).dt.days
    E["fold"] = E["t0"].map(fold_of)
    E["ts_known"] = E["t0"]
    E["member_at_t0"] = [fundfreq.member_at(M, s, t) for s, t in zip(E["symbol"], E["t0"])]
    E = pd.concat([E, flag_join(E, S), cap_rows(E, S)], axis=1)
    E["why"] = np.where(E["fold"].isin(list(TAGS)), "eligible", "outside F1 … F5 (listed, described, not frozen)")
    E = E[[*LIST_COLS, "why"]].sort_values(["t0", "symbol"]).reset_index(drop=True)
    # the described rows: the count's age rule (the first settlement alone) and the other thresholds, counts only
    desc = {"count_rule_first_settlement": {str(k): int(v) for k, v in episodes(T, thr, FS["first_settlement"]).assign(fold=lambda d: d["t0"].map(fold_of)).groupby("fold").size().items()}}
    for d in DESCRIBED:
        Ed = episodes(T, d, FS["perp_first"]).assign(fold=lambda x: x["t0"].map(fold_of))
        desc[f"thr_{d:g}"] = {"episodes": int(len(Ed)), "names": int(Ed["symbol"].nunique()), "by_fold": {str(k): int(v) for k, v in Ed.groupby("fold").size().items()},
                              "bought": int((Ed["side"] == "bought").sum())}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        E.to_csv(OUT / "events.csv", index=False)
        el = E[E["why"] == "eligible"]
        for tag in LISTS:
            el[el["fold"].map(TAGS) == tag][LIST_COLS].to_csv(OUT / f"fundep_{tag}.csv", index=False)
        (OUT / "events_described.json").write_text(json.dumps(desc, indent=1))
        print(summary(E, desc))
    return E


def _byfold(s: pd.Series) -> str:
    return " ".join(f"{k} {int(v)}" for k, v in s.reindex(ORDER, fill_value=0).items() if v)


def summary(E: pd.DataFrame, desc: dict | None = None) -> str:
    el = E[E["why"] == "eligible"]
    thr = float(E["thr"].iloc[0]) if len(E) else THRESHOLD
    lines = [f"{len(E)} episodes at |fund_1d| ≥ {thr:.0%} a day on {E['symbol'].nunique()} names (the contract ≥ {PERP_AGE.days} d old at t0); by fold: {_byfold(E.groupby('fold').size())}",
             f"eligible (t0 in F1 … F5): {len(el)} — F1+F2 {int(el['fold'].isin(['F1', 'F2']).sum())}, F3+F4 {int(el['fold'].isin(['F3', 'F4']).sum())}, F5 {int((el['fold'] == 'F5').sum())}"]
    if len(el):
        lines.append("eligible by fold × side:\n" + el.groupby(["fold", "side"]).size().unstack(fill_value=0).to_string())
        lines.append(f"members at t0 {int(el['member_at_t0'].sum())}; flagged within ± {FLAG_WINDOW.days} d {int(el['flagged_7d'].sum())} "
                     f"(by fold: {_byfold(el[el['flagged_7d']].groupby('fold').size())}); |fund_1d| at t0 q10 / q50 / q90 "
                     + " / ".join(f"{v * 100:.2f}" for v in el["fund_1d"].abs().quantile([0.1, 0.5, 0.9])) + " % a day; first episodes {} of {}".format(int((el["prior_episodes"] == 0).sum()), len(el)))
        f12 = el[el["fold"].isin(["F1", "F2"])]
        if len(f12):
            lines.append("F1+F2 per month: " + json.dumps(f12.groupby(f12["t0"].dt.strftime("%Y-%m")).size().to_dict()))
    if desc:
        lines.append("described: " + json.dumps(desc))
    return "\n".join(lines)


def frozen(tags=("f12", "f34", "f5")) -> pd.DataFrame:
    parts = []
    for tag in tags:
        p = LISTS[tag]
        if p.exists():
            d = pd.read_csv(p)
            if not len(d):
                continue                                           # an empty list (no episode in its folds) adds no rows and no object dtypes
            for c in DATE_COLS:
                d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601")
            parts.append(d.assign(list=tag))
    if not parts:
        raise SystemExit(f"fundep: no frozen list at {list(LISTS.values())} — run `ft2 fundep events`, freeze the lists, commit")
    return pd.concat(parts, ignore_index=True)


# ---- the eligibility rule on a frozen list, R75's frame, BEFORE a registration's thresholds are written ------------------------------------
def coverage(L: pd.DataFrame) -> pd.DataFrame:
    return fundfreq.coverage(L.assign(dir=L["side"]))


def cost_presence(L: pd.DataFrame) -> pd.DataFrame:
    """Per cell whether `cost_daily_wide` holds a finite taker leg for the name on the entry day or the day before (R75's B_i), else within
    COST_FALLBACK before (R75's fallback), else none (R28's constant would be used)."""
    from .cost import DAILY_WIDE
    out = pd.DataFrame({"symbol": L["symbol"].to_numpy(), "t0": L["t0"].to_numpy(), "cost_source": "none"})
    if not Path(DAILY_WIDE).exists():
        return out
    w = pd.read_parquet(DAILY_WIDE, columns=["symbol", "day", "spread_cal_bps", "imp_10000"])
    w["symbol"] = w["symbol"].astype(str)
    w["day"] = fundfreq._utc(w["day"]).dt.floor("D")
    ok = w[np.isfinite(w["spread_cal_bps"]) & np.isfinite(w["imp_10000"])]
    by = {s: np.sort(g["day"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]")) for s, g in ok.groupby("symbol")}
    src = []
    for r in L.itertuples(index=False):
        entry_day = (r.t0 + (WAIT + LATENCY) * BAR).floor("D")
        d = by.get(r.symbol, np.array([], dtype="datetime64[ns]"))
        e = np.datetime64(entry_day.tz_localize(None), "ns")
        if len(d) and (np.searchsorted(d, e, "right") - np.searchsorted(d, e - np.timedelta64(1, "D"))) > 0:
            src.append("own day or the day before")
        elif len(d) and (np.searchsorted(d, e, "right") - np.searchsorted(d, e - np.timedelta64(COST_FALLBACK.days, "D"))) > 0:
            src.append(f"within {COST_FALLBACK.days} d")
        else:
            src.append("none")
    out["cost_source"] = src
    return out


def eligibility(L: pd.DataFrame, tag: str, M: pd.DataFrame) -> pd.DataFrame:
    """R75's frame on the list of `tag`: the calendar against the folds' window and the first member block, the bars, the cost rows; every cell
    with its reason ('' = eligible)."""
    fl = FOLDS_OF[tag]
    a0, end = folds.bounds(fl[0], embargoed=False)[0], folds.bounds(fl[-1], embargoed=False)[1]
    blocks = M[M["block"] < end]["block"] if len(M) else pd.Series(dtype="datetime64[ns, UTC]")
    first_block = blocks[blocks >= a0 - 31 * DAY].min() if len(blocks) else pd.NaT
    cov = coverage(L).set_index(["symbol", "t0"])["share"]
    cost = cost_presence(L).set_index(["symbol", "t0"])["cost_source"]
    rows = []
    for r in L.itertuples(index=False):
        t = r.t0 + WAIT * BAR
        entry = t + LATENCY * BAR
        share = float(cov.get((r.symbol, r.t0), 0.0))
        cs = cost.get((r.symbol, r.t0), "none")
        if pd.notna(first_block) and t < first_block:
            why = "before the first member block"
        elif not (entry + LONGEST < end):
            why = "the 7-day exit is not before the end"
        elif share < MIN_SHARE:
            why = f"bars under {MIN_SHARE:.0%} in the window"
        else:
            why = ""
        rows.append({"symbol": r.symbol, "t0": r.t0, "fold": r.fold, "side": r.side, "member_at_t0": bool(r.member_at_t0), "flagged_7d": bool(r.flagged_7d), "t": t, "entry": entry,
                     "exit_7d": entry + LONGEST, "bars_share": share, "cost_source": cs, "why": why})
    out = pd.DataFrame(rows)
    out["eligible"] = out["why"] == ""
    out["first_block"], out["window_end"] = first_block, end
    return out


def data_need(L: pd.DataFrame) -> dict:
    """The (name, month) 5m files a Data line would fetch for the list's windows short of bars (R78's Data line; BU1's route)."""
    from . import archive, krlist
    cov = coverage(L)
    cov["months"] = [archive.months_between((t + WINDOW[0]).date(), (t + WINDOW[1] - BAR).date()) for t in cov["t0"]]
    need = krlist.missing_months(cov)
    return {"events": int(len(cov)), "complete": int((cov["share"] >= MIN_SHARE).sum()), "names_short": len(need), "files": int(sum(len(v) for v in need.values())),
            "by_fold": {str(k): {"events": int(len(g)), "complete": int((g["share"] >= MIN_SHARE).sum())} for k, g in cov.groupby("fold")}, "need": need}


def audit(today: pd.Timestamp | None = None) -> str:
    today = today or pd.Timestamp.now("UTC")
    L = frozen()
    M = member_symbols()
    OUT.mkdir(parents=True, exist_ok=True)
    desc = json.loads((OUT / "events_described.json").read_text()) if (OUT / "events_described.json").exists() else None
    md5s = {tag: {"md5": _md5(p), "rows": int((L["list"] == tag).sum())} for tag, p in LISTS.items() if p.exists()}
    by_fs = L.groupby(["fold", "side"]).size().unstack(fill_value=0)
    by_fm = L.groupby(["fold", "member_at_t0"]).size().unstack(fill_value=0)
    by_ff = L.groupby(["fold", "flagged_7d"]).size().unstack(fill_value=0)
    by_fi = L.groupby(["fold", L["interval_h"].astype(int).astype(str) + "h"]).size().unstack(fill_value=0)
    f12 = L[L["list"] == "f12"]
    per_month = f12.groupby(f12["t0"].dt.strftime("%Y-%m")).size().to_dict()
    q = lambda s, qs=(0.1, 0.5, 0.9): {str(k): float(v) for k, v in s.quantile(qs).round(4).items()}
    hod = pd.DatetimeIndex(L["t0"]).hour.value_counts().sort_index()
    lag = L["flag_lag_h"].dropna()
    # the eligibility rule on the frozen F1+F2 list; the calendar and the bars on F3+F4 and F5 beside (their bars are the Data line's)
    EL = {tag: eligibility(L[L["list"] == tag].reset_index(drop=True), tag, M) for tag in LISTS if (L["list"] == tag).any()}
    for tag, e in EL.items():
        e.to_csv(OUT / f"eligibility_{tag}.csv", index=False)
    need = {tag: data_need(L[L["list"] == tag].reset_index(drop=True)) for tag in ("f34", "f5") if (L["list"] == tag).any()}
    e12 = EL.get("f12", pd.DataFrame(columns=["eligible", "why", "cost_source", "symbol", "t0"]))
    J = {"generated": f"{today:%Y-%m-%d %H:%M} UTC", "threshold": float(L["thr"].iloc[0]), "quiet_days": QUIET.days, "perp_age_days": PERP_AGE.days, "lists": md5s,
         "episodes": int(len(L)), "distinct_names": int(L["symbol"].nunique()),
         "by_fold_side": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fs.iterrows()},
         "by_fold_member_at_t0": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fm.iterrows()},
         "by_fold_flagged_7d": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_ff.iterrows()},
         "by_fold_interval_at_t0": {str(k): {str(c): int(v) for c, v in r.items()} for k, r in by_fi.iterrows()},
         "f12_per_month": per_month, "fund_1d_abs_pct_q10_50_90": {k: v * 100 for k, v in q(L["fund_1d"].abs()).items()}, "rate_t0_abs_pct_q10_50_90": {k: v * 100 for k, v in q(L["rate_t0"].abs()).items()},
         "n_1d_q10_50_90": q(L["n_1d"]), "fund_7d_abs_pct_q10_50_90": {k: v * 100 for k, v in q(L["fund_7d"].abs()).items()}, "perp_age_days_q10_50_90": q(L["perp_age_days"]),
         "perp_first_source": L["perp_first_source"].value_counts().to_dict(), "prior_episodes": L["prior_episodes"].value_counts().sort_index().to_dict(),
         "days_since_prior_q10_50_90": q(L["days_since_prior"].dropna()) if L["days_since_prior"].notna().any() else None,
         "cap_share_7d_q10_50_90": q(L["cap_share_7d"].dropna()) if L["cap_share_7d"].notna().any() else None, "t0_hour_utc": {int(k): int(v) for k, v in hod.items()},
         "flag_lag_h": {"n": int(len(lag)), "q10_50_90": q(lag) if len(lag) else None, "flag_after_crossing": int((lag < 0).sum()), "flag_before_crossing": int((lag > 0).sum())},
         "eligibility_f12": {"cells": int(len(e12)), "eligible": int(e12["eligible"].sum()), "by_reason": e12["why"].replace("", "eligible").value_counts().to_dict(),
                             "dropped": e12[~e12["eligible"]][["symbol", "t0", "why", "bars_share"]].astype(str).to_dict("records"),
                             "cost_source_of_the_eligible": e12[e12["eligible"]]["cost_source"].value_counts().to_dict(),
                             "eligible_bought": int((e12["eligible"] & (e12["side"] == "bought")).sum()) if len(e12) else 0,
                             "eligible_members": int((e12["eligible"] & e12["member_at_t0"]).sum()) if len(e12) else 0, "eligible_flagged": int((e12["eligible"] & e12["flagged_7d"]).sum()) if len(e12) else 0,
                             "eligible_by_fold": {str(k): int(v) for k, v in e12[e12["eligible"]].groupby("fold").size().items()} if len(e12) else {},
                             "first_block": str(e12["first_block"].iloc[0]) if len(e12) else None, "window_end": str(e12["window_end"].iloc[0]) if len(e12) else None},
         "calendar_f34_f5": {tag: {"cells": int(len(e)), "calendar_ok": int((~e["why"].isin(["before the first member block", "the 7-day exit is not before the end"])).sum()),
                                   "by_reason": e["why"].replace("", "eligible").value_counts().to_dict()} for tag, e in EL.items() if tag != "f12"},
         "data_line_need": need, "described": desc,
         "known_at": "t0 = the first settlement at which the 24-hour sum of the settled rate reaches the threshold, public at its own stamp (funding_archive's fundingTime); the decision bar of a registration is the first 5m bar that closes after t0, the entry one bar later; nothing after t0 is read here"}
    (OUT / "audit.json").write_text(json.dumps(J, indent=1, default=str))
    md = [f"# fundep — the extreme trailing-day funding of a running perpetual WITHOUT the exchange's flag, as a per-name event population (decision BY1)",
          f"generated {J['generated']} · the frozen lists {json.dumps(md5s)} · threshold {J['threshold']:.0%} a day, a new episode after {QUIET.days} quiet days, the contract ≥ {PERP_AGE.days} d old", "",
          f"**{len(L)} episodes on {J['distinct_names']} names** — by fold × side:", by_fs.to_string(), "", "## By fold × member at t0", by_fm.to_string(), "",
          f"## By fold × flagged (a fundfreq shortening of the name within ± {FLAG_WINDOW.days} d)", by_ff.to_string(), "", "## By fold × the settlement interval at t0", by_fi.to_string(), "",
          "## F1+F2 per month", json.dumps(per_month), "",
          "## |fund_1d| at t0, % a day (q10 / q50 / q90)", json.dumps(J["fund_1d_abs_pct_q10_50_90"]), "the rate at t0, % a settlement: " + json.dumps(J["rate_t0_abs_pct_q10_50_90"]),
          "rows in the day's window: " + json.dumps(J["n_1d_q10_50_90"]) + "; |fund_7d| % " + json.dumps(J["fund_7d_abs_pct_q10_50_90"]), "",
          "## The contract's age at t0 (days, q10 / q50 / q90) and the first stamp's source", json.dumps(J["perp_age_days_q10_50_90"]) + " " + json.dumps(J["perp_first_source"]), "",
          "## Prior episodes of the name at this threshold (count → episodes); days since the prior", json.dumps(J["prior_episodes"]) + " " + json.dumps(J["days_since_prior_q10_50_90"]), "",
          "## The trigger row (cap_share_7d q10 / q50 / q90)", json.dumps(J["cap_share_7d_q10_50_90"]), "", "## The hour of t0 (UTC)", hod.to_string(), "",
          "## The flag's lag (t0 − the shortening's stamp, hours; negative = the flag came after the crossing)", json.dumps(J["flag_lag_h"]), "",
          f"## The eligibility rule on the frozen F1+F2 list (R75's frame: the decision bar at t0 + 5 min, the entry at t0 + 10 min, the 7-day exit before F2's end; bars ≥ {MIN_SHARE:.0%} over t0 − 2 d → t0 + 8 d)",
          json.dumps({k: v for k, v in J["eligibility_f12"].items() if k != "dropped"}), "", "Every dropped cell:", (pd.DataFrame(J["eligibility_f12"]["dropped"]).to_markdown(index=False) if J["eligibility_f12"]["dropped"] else "none"), "",
          "## F3+F4 and F5: the calendar, and the bars a Data line would fetch (R78's)", json.dumps(J["calendar_f34_f5"]), json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "need"} for k, v in need.items()}), "",
          "## Described: the count's age rule (the first settlement alone) and the thresholds 1 % / 3 %", json.dumps(desc), "", "## Known-at", J["known_at"]]
    (OUT / "audit.md").write_text("\n".join(md))
    return "\n".join(md)


def _md5(p: Path) -> str:
    import hashlib
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def main(action: str, threshold: float = THRESHOLD) -> None:
    if action == "events":
        events(threshold)
    elif action == "audit":
        print(audit())
    else:
        sys.exit(f"fundep: unknown action {action}")
