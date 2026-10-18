"""R51 (PLAN §8): token unlocks on the members — what a name does against the block's members over the week INTO a promised cliff
and over the 1 / 3 / 7 days AFTER it. R28's label (listing.label_at / excess), the known-at rule of the source audit (events.promised:
an unlock as the LAST archived page at least 7 days before it dated it), the null every admissible whole-day shift of the event dates.

select     the point-in-time event lists from data/unlock_asof.parquet on the members of F1+F2 (f12) and F3+F4 (f34) → output/audit/
           r51_unlocks/events_{f12,f34}.csv, frozen as ft2/unlocks_{f12,f34}.csv and committed BEFORE any bar is loaded. No price is read.
stage1     F1+F2: the four rows, the shift null, the gate; described; → stage1.md / stage1.json / validity.json / rows.csv / shifts.parquet.
stage2     F3+F4, only for the rows stage 1 cleared (stage1.json's `cleared`), one-sided with the signs fixed; else the NOTHING TO CONFIRM stub.

The script changes nothing of the registration; the registration is the guard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import backtest as bt  # noqa: E402
from ft2 import events, folds, horizon, listing, universe  # noqa: E402
from ft2.ceiling import MDE_K  # noqa: E402

OUT = Path("output/audit/r51_unlocks")
FT2 = Path(__file__).resolve().parents[1] / "ft2"
FROZEN = {"f12": FT2 / "unlocks_f12.csv", "f34": FT2 / "unlocks_f34.csv"}
MEMBERS = {"f12": FT2 / "screen_members.csv", "f34": FT2 / "screen_members_f34.csv"}
STAGE_FOLDS = {"f12": ("F1", "F2"), "f34": ("F3", "F4")}
STATE_DAILY = Path("output/backtest/r47_mech/daily.parquet")
BAR = pd.Timedelta("5min")
DAY = pd.Timedelta(days=1)
PER_DAY = 288
INTO_DAYS = 7
ROWS = {"into_7d": 7 * PER_DAY, "after_1d": PER_DAY, "after_3d": 3 * PER_DAY, "after_7d": 7 * PER_DAY}
GAP_DAYS = INTO_DAYS + 7 + 1                      # a shifted event never within 15 days of its own date
BAR_BPS = listing.BAR_BPS                         # 46: twice a member's taker round trip
U_BAR, P_BAR = 2.0, 0.05
MIN_MEMBERS, MIN_LABELS, MIN_BARS, MIN_SHIFT_LABELLED, MIN_EVENTS = 40, 0.95, 0.95, 0.90, 20
DRAWS, SEED = 10_000, 51
TAKER_BPS = 5.0
BTC = "BTCUSDT"
INSIDER_RE = r"team|investor|advisor|founder|private|seed|series|strategic|backer|contributor|insider|employee|core"
COLS = ["perp", "ticker", "pid", "name", "day", "pct_max", "tokens", "recipients", "asof", "lead_days", "fold", "today"]


# ---- select: the point-in-time event lists (no price) --------------------------------------------------------------------------
def members_df(csv: Path | str, tag: str) -> pd.DataFrame:
    m = pd.read_csv(csv, usecols=["block", "symbol"]).assign(universe=tag)
    m["block"] = pd.to_datetime(m["block"], utc=True)
    m["ticker"] = m["symbol"].map(events.base)
    return m


def promised_events(fin: pd.DataFrame, asof: pd.DataFrame, mem: pd.DataFrame, min_pct: float = events.MIN_PCT, lead: pd.Timedelta = events.LEAD) -> pd.DataFrame:
    """The cliffs on a member WHILE it is a member, each as the LAST snapshot at least `lead` before it dated it (events.promised), one
    event per (perpetual, day); `today` = how today's schedule has it (same / amount / not as dated)."""
    asof = events.align(asof, fin)
    fin = events.fill_symbols(fin, asof)
    cd = events.cliff_days(fin)
    covered = {at: set(g["pid"]) for at, g in asof.groupby("asof")}
    acd = events.cliff_days(asof[asof["kind"] == "cliff"], by=("asof",))
    pr = events.promised(acd[acd["pct_max"] >= min_pct], covered, lead).assign(key=lambda x: x["symbol"], fold=lambda x: events.fold_of(x["day"]))
    prm = events.in_blocks(pr, "day", mem).drop_duplicates(["pid", "day"]).reset_index(drop=True)
    if not len(prm):
        return pd.DataFrame(columns=COLS)
    prm["today"] = events._match(prm, cd).replace({"moved": "not as dated", "absent": "not as dated"})
    prm["lead_days"] = ((prm["day"] - prm["asof"]) / DAY).round(3)
    out = prm.rename(columns={"key": "ticker"})[COLS].drop_duplicates(["perp", "day"]).sort_values(["day", "perp"]).reset_index(drop=True)
    return out


def hindsight_events(fin: pd.DataFrame, asof: pd.DataFrame, mem: pd.DataFrame, promised: pd.DataFrame, min_pct: float = events.MIN_PCT) -> pd.DataFrame:
    """Today's file's cliffs on a member that the snapshots did NOT promise — what a read from today's file would have added (a reference)."""
    asof = events.align(asof, fin)
    fin = events.fill_symbols(fin, asof)
    cd = events.cliff_days(fin)
    big = cd[cd["pct_max"] >= min_pct].assign(key=lambda x: x["symbol"], fold=lambda x: events.fold_of(x["day"]))
    onm = events.in_blocks(big, "day", mem).drop_duplicates(["pid", "day"]).reset_index(drop=True)
    have = set(zip(promised["perp"], pd.DatetimeIndex(promised["day"])))
    keep = [(p, d) not in have for p, d in zip(onm["perp"], pd.DatetimeIndex(onm["day"]))]
    return onm[keep].drop_duplicates(["perp", "day"]).sort_values(["day", "perp"]).reset_index(drop=True)


def fingerprint(paths=(events.UNLOCKS, events.ASOF)) -> dict:
    out = {}
    for p in paths:
        p = Path(p)
        out[p.name] = {"rows": int(len(pd.read_parquet(p))), "md5": hashlib.md5(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
    return out


def select(out: Path = OUT) -> dict:
    fin, asof = pd.read_parquet(events.UNLOCKS), pd.read_parquet(events.ASOF)
    out.mkdir(parents=True, exist_ok=True)
    res = {"fingerprint": fingerprint(), "written": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    for tag, csv in MEMBERS.items():
        ev = promised_events(fin, asof, members_df(csv, tag))
        ev.to_csv(out / f"events_{tag}.csv", index=False)
        res[tag] = {"events": int(len(ev)), "names": int(ev["perp"].nunique()), "by_fold": ev["fold"].value_counts().sort_index().to_dict(),
                    "today": ev["today"].value_counts().to_dict(), "ge_1pct": int((ev["pct_max"] >= 1).sum()), "lead_days_min": float(ev["lead_days"].min()) if len(ev) else None}
        print(f"{tag}: {len(ev)} events on {ev['perp'].nunique()} names, by fold {res[tag]['by_fold']}, today {res[tag]['today']} → {out / f'events_{tag}.csv'}", flush=True)
    (out / "events_fingerprint.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def load_events(path: Path | str) -> pd.DataFrame:
    ev = pd.read_csv(path)
    ev["day"] = pd.to_datetime(ev["day"], utc=True, format="ISO8601")
    ev["asof"] = pd.to_datetime(ev["asof"], utc=True, format="ISO8601")
    return ev


# ---- the frame: the window, the midnights, the labels at every midnight ---------------------------------------------------------
def stage_window(fold_names) -> tuple[pd.Timestamp, pd.Timestamp]:
    fold_names = folds.order(fold_names)
    return folds.bounds(fold_names[0])[0], folds.bounds(fold_names[-1])[1]


def event_days(a: pd.Timestamp, b: pd.Timestamp, into_days: int = INTO_DAYS, after_days: int = 7) -> pd.DatetimeIndex:
    """Every UTC day D the window can hold whole: D − into ≥ a and D's after_7d exit (D + after + one bar) < b."""
    d0 = (a + into_days * DAY).ceil("D")
    d1 = (b - after_days * DAY - 2 * BAR).floor("D")
    return pd.date_range(d0, d1, freq="D", tz="UTC") if d1 >= d0 else pd.DatetimeIndex([], tz="UTC")


def shifts(span: int, gap: int = GAP_DAYS) -> np.ndarray:
    return np.arange(gap, span - gap + 1)


class Frame:
    """The market, the costs, the labels of every name at every midnight of the window for each row's hold, the block's members at
    each midnight. Rows are read off this table for the real dates and for every shifted date."""

    def __init__(self, M: bt.Market, C: bt.Costs, mem: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp):
        self.M, self.C, self.mem, self.a, self.b = M, C, mem, a, b
        self.days = event_days(a, b)
        first = (a - INTO_DAYS * DAY).ceil("D") if len(self.days) else a.ceil("D")
        self.mid = pd.date_range(first, (b - BAR).floor("D"), freq="D", tz="UTC")           # every midnight whose bar the market has
        self.mid_row = M.index.get_indexer(self.mid)
        self.mid = self.mid[self.mid_row >= 0]
        self.mid_row = self.mid_row[self.mid_row >= 0]
        close, fv = M.close.to_numpy(), C.fundval
        self.L = {h: listing.label_at(close, fv, self.mid_row, h) for h in sorted(set(ROWS.values()))}      # midnight × name
        self.mask = listing.member_mask(mem, M.columns, self.mid)
        self.span = len(self.days)

    def mid_index(self, days: pd.DatetimeIndex) -> np.ndarray:
        return self.mid.get_indexer(pd.DatetimeIndex(days))

    def rows(self, perps: np.ndarray, days: pd.DatetimeIndex) -> dict:
        """Per row: a, b, n_b and y = a − b for the events (perp, day); NaN where the market has no bar or label."""
        own = self.M.columns.get_indexer(perps)
        out = {}
        for name, h in ROWS.items():
            at = self.mid_index(pd.DatetimeIndex(days) - (INTO_DAYS * DAY if name.startswith("into") else pd.Timedelta(0)))
            ok = (at >= 0) & (own >= 0)
            a = np.full(len(own), np.nan)
            b, nb = a.copy(), np.zeros(len(own), dtype=int)
            if ok.any():
                A = self.L[h][at[ok]]
                aa, bb, n = listing.excess(A, own[ok], self.mask[at[ok]])
                a[ok], b[ok], nb[ok] = aa, bb, n
            out[name] = {"a": a, "b": b, "n_b": nb, "y": a - b}
        return out

    def shifted_days(self, days: pd.DatetimeIndex, k: int) -> pd.DatetimeIndex:
        d0 = self.days[0]
        pos = ((pd.DatetimeIndex(days) - d0).days.to_numpy() + k) % self.span
        return d0 + pd.to_timedelta(pos, unit="D")


def eligible(ev: pd.DataFrame, fr: Frame) -> pd.DataFrame:
    e = ev.copy()
    e["eligible"] = e["day"].isin(fr.days) & e["perp"].isin(fr.M.columns)
    e["why"] = np.where(e["eligible"], "", np.where(~e["perp"].isin(fr.M.columns), "no bars for the name", "the window cannot hold the week into and the week after"))
    return e


# ---- the statistic ---------------------------------------------------------------------------------------------------------------
def shift_null(fr: Frame, perps: np.ndarray, days: pd.DatetimeIndex, ks: np.ndarray, min_labelled: float = MIN_SHIFT_LABELLED) -> pd.DataFrame:
    rows = []
    for k in ks:
        r = fr.rows(perps, fr.shifted_days(days, int(k)))
        rec = {"shift": int(k)}
        for name in ROWS:
            y = r[name]["y"]
            rec[name] = float(np.nanmean(y)) if np.isfinite(y).any() else np.nan
            rec[f"{name}_labelled"] = float(np.isfinite(y).mean())
        rows.append(rec)
    d = pd.DataFrame(rows)
    d["kept"] = (d[[f"{n}_labelled" for n in ROWS]].min(axis=1) >= min_labelled)
    return d


def family(real: dict, null: pd.DataFrame, fold_of_event: np.ndarray, fold_names, signs: dict | None = None) -> pd.DataFrame:
    """Per row: M, centre, se, M_c, u, the per-fold M_c, the trimmed M_c, MDE; the family-wise p over the rows (two-sided, or one-sided
    with `signs` fixed over the rows in `signs`)."""
    kept = null[null["kept"]]
    cen = kept[list(ROWS)].mean()
    se = kept[list(ROWS)].std(ddof=1)
    tab = []
    for name in ROWS:
        y = real[name]["y"]
        m = float(np.nanmean(y))
        mc = m - cen[name]
        r = {"row": name, "n": int(np.isfinite(y).sum()), "M": m, "centre": float(cen[name]), "se": float(se[name]), "M_c": mc, "u": mc / se[name] if se[name] > 0 else np.nan,
             "MDE": MDE_K * float(se[name]), "lower": mc - 1.96 * se[name], "upper": mc + 1.96 * se[name], "M_trim_c": listing.trimmed(y) - cen[name]}
        for f in fold_names:
            yf = y[fold_of_event == f]
            r[f"M_c_{f}"] = float(np.nanmean(yf)) - cen[name] if np.isfinite(yf).any() else np.nan
        r["median"] = float(np.nanmedian(y))
        r["share_below_0"] = float((y[np.isfinite(y)] < 0).mean())
        tab.append(r)
    tab = pd.DataFrame(tab).set_index("row")
    U = (kept[list(ROWS)] - cen) / se                                   # shift × row
    if signs is None:
        T = U.abs().max(axis=1)
        obs = tab["u"].abs().max()
        floor = 1.0 / (len(kept) + 1)                                 # no shift reached it: "under 1 in (shifts + 1)", never a literal zero
        tab["p_single"] = [max(float((U[n].abs() >= abs(tab.loc[n, "u"])).mean()), floor) for n in ROWS]
        tab["p_family"] = max(float((T >= obs).mean()), floor)
        tab["signed_u"] = np.nan
    else:
        keys = list(signs)
        S = pd.Series(signs)
        US = U[keys] * S
        tab["signed_u"] = [tab.loc[n, "u"] * signs[n] if n in signs else np.nan for n in ROWS]
        obs = tab.loc[keys, "signed_u"].max()
        floor = 1.0 / (len(kept) + 1)
        tab["p_single"] = [max(float((US[n] >= tab.loc[n, "signed_u"]).mean()), floor) if n in signs else np.nan for n in ROWS]
        tab["p_family"] = [max(float((US.max(axis=1) >= obs).mean()), floor) if n in signs else np.nan for n in ROWS]
    tab["shifts_kept"] = int(len(kept))
    return tab.reset_index()


def verdict1(r: dict, fold_names, bar: float = BAR_BPS) -> str:
    f1, f2 = (r[f"M_c_{f}"] for f in fold_names[:2]) if len(fold_names) >= 2 else (r["M_c"], r["M_c"])
    return listing.verdict(r["M_c"], r["se"], r["u"], r["p_family"], f1, f2, r["M_trim_c"], bar)


def verdict2(mc: float, se: float, p: float, sign: int, fact: float, su: float, trim_c: float) -> str:
    if not np.isfinite(mc) or not se > 0:
        return "NOT READABLE"
    if p <= P_BAR and su >= U_BAR and np.sign(trim_c) == sign:
        return "CLEARS"
    if np.isfinite(fact) and sign * (mc + sign * 1.96 * se) < sign * fact / 2:
        return "REFUTED"
    if abs(mc) < MDE_K * se:
        return "NOT DETECTABLE"
    return "NOT CLEAR"


# ---- validity ----------------------------------------------------------------------------------------------------------------------
def _identity(fr: Frame, E: pd.DataFrame, real: dict, taker_bps: float) -> dict:
    """(3) the module's label equals horizon.labels at the same cells and the harness's gross + funding of a long."""
    out = {}
    own = fr.M.columns.get_indexer(E["perp"])
    for name, h in ROWS.items():
        t = pd.DatetimeIndex(E["day"]) - (INTO_DAYS * DAY if name.startswith("into") else pd.Timedelta(0))
        rows = fr.M.index.get_indexer(t)
        full = horizon.labels(fr.M, fr.C, h, bt.LATENCY)[1].to_numpy()
        ref = full[rows, own]
        del full
        dec = pd.DataFrame({"t": t, "symbol": E["perp"].to_numpy(), "side": 1, "hold": h, "size": 1.0, "fold": E["fold"].to_numpy(), "accepted": True})
        f = bt.price(dec, fr.M, fr.C, "taker", taker_bps, 2.0)
        paid = (f["gross_bps"] + f["funding_bps"]).to_numpy()
        a = real[name]["a"]
        ok = np.isfinite(a)
        out[name] = {"max_abs_diff_horizon": float(np.nanmax(np.abs(ref[ok] - a[ok]))) if ok.any() else 0.0,
                     "max_abs_diff_harness": float(np.nanmax(np.abs(paid[ok] - a[ok]))) if ok.any() else 0.0,
                     "same_cells": bool((np.isfinite(ref) == ok).all())}
    return out


def _bars_share(fr: Frame, E: pd.DataFrame) -> np.ndarray:
    close, idx = fr.M.close.to_numpy(), fr.M.index
    own = fr.M.columns.get_indexer(E["perp"])
    s = []
    for d, c in zip(pd.DatetimeIndex(E["day"]), own):
        r0, r1 = idx.searchsorted(d - INTO_DAYS * DAY), idx.searchsorted(d + 7 * DAY + 2 * BAR)
        s.append(float(np.isfinite(close[r0:r1, c]).mean()) if c >= 0 and r1 > r0 else 0.0)
    return np.array(s)


def validity(tag: str, ev: pd.DataFrame, E: pd.DataFrame, fr: Frame, real: dict, null: pd.DataFrame, ks: np.ndarray, repro: dict, fp: dict, ident: dict, min_members: int, min_events: int) -> dict:
    lead = (E["day"] - E["asof"]) / DAY
    v = {"registration": "R51", "stage_tag": tag, "folds": [f for f in STAGE_FOLDS[tag]], "window": [str(fr.a), str(fr.b)],
         "1_list_reproduces": repro, "1_fingerprint": fp,
         "2_asof_at_or_before_D_minus_7d": bool((E["asof"] <= E["day"] - INTO_DAYS * DAY).all()), "2_lead_days_min": float(lead.min()) if len(E) else None, "2_lead_days_median": float(lead.median()) if len(E) else None,
         "3_identity": ident,
         "events_frozen": int(len(ev)), "events_eligible": int(len(E)), "events_dropped": ev[~ev["eligible"]]["why"].value_counts().to_dict() if "eligible" in ev else {},
         "4_label_share": {n: float(np.isfinite(real[n]["y"]).mean()) for n in ROWS}, "4_min_share_of_bars": float(_bars_share(fr, E).min()) if len(E) else 0.0,
         "5_min_members": {n: int(real[n]["n_b"][np.isfinite(real[n]["y"])].min()) if np.isfinite(real[n]["y"]).any() else 0 for n in ROWS},
         "6_days_in_window": int(fr.span), "6_shifts": int(len(ks)), "6_shifts_expected": int(fr.span - 2 * GAP_DAYS + 1), "6_shifts_kept": int(null["kept"].sum()), "6_shifts_dropped": int((~null["kept"]).sum()),
         "6_min_labelled_on_kept": float(null[null["kept"]][[f"{n}_labelled" for n in ROWS]].min().min()) if null["kept"].any() else 0.0}
    ok3 = all(d["max_abs_diff_horizon"] <= 1e-9 and d["max_abs_diff_harness"] <= 1e-9 and d["same_cells"] for d in ident.values())
    v["status"] = "PASS" if (repro["same"] and v["2_asof_at_or_before_D_minus_7d"] and ok3 and len(E) >= min_events and min(v["4_label_share"].values()) >= MIN_LABELS
                             and v["4_min_share_of_bars"] >= MIN_BARS and min(v["5_min_members"].values()) >= min_members and v["6_shifts"] == v["6_shifts_expected"]
                             and v["6_shifts_kept"] >= 20) else "FAIL"
    return v


def reproduce(frozen: pd.DataFrame, fresh: pd.DataFrame) -> dict:
    a = frozen.assign(day=pd.DatetimeIndex(frozen["day"])).set_index(["perp", "day"]).sort_index()
    b = fresh.assign(day=pd.DatetimeIndex(fresh["day"])).set_index(["perp", "day"]).sort_index()
    same_keys = a.index.equals(b.index)
    same_vals = bool(same_keys and np.allclose(a["pct_max"].to_numpy(), b["pct_max"].to_numpy(), atol=1e-9) and (pd.DatetimeIndex(a["asof"]) == pd.DatetimeIndex(b["asof"])).all())
    return {"frozen": int(len(a)), "fresh": int(len(b)), "same_keys": bool(same_keys), "same": same_vals}


# ---- described -----------------------------------------------------------------------------------------------------------------------
def _state(days: pd.DatetimeIndex, daily: Path | None) -> np.ndarray:
    if daily is None or not Path(daily).exists():
        return np.zeros(len(days), dtype=int)
    d = pd.read_parquet(daily)[["day", "state"]].set_index("day")["state"]
    return d.reindex(pd.DatetimeIndex(days).floor("D")).fillna(0).to_numpy().astype(int)


def _split(real: dict, cen: pd.Series, groups: dict[str, np.ndarray]) -> list[dict]:
    out = []
    for g, m in groups.items():
        rec = {"split": g, "n": int(m.sum())}
        for name in ROWS:
            y = real[name]["y"][m]
            rec[name] = float(np.nanmean(y)) - cen[name] if np.isfinite(y).any() else np.nan
        out.append(rec)
    return out


def described(fr: Frame, E: pd.DataFrame, real: dict, tab: pd.DataFrame, fold_names, state_daily: Path | None, taker_bps: float, hind: pd.DataFrame | None) -> dict:
    cen = tab.set_index("row")["centre"]
    days = pd.DatetimeIndex(E["day"])
    y7 = real["after_7d"]["y"]
    q = [0.05, 0.25, 0.5, 0.75, 0.95]
    dist = []
    for name in ROWS:
        y = real[name]["y"]
        v = y[np.isfinite(y)]
        dist.append({"row": name, "n": len(v), "M": v.mean(), "median": np.median(v), "share_below_0": (v < 0).mean(), **{f"q{int(x * 100):02d}": np.quantile(v, x) for x in q},
                     "min": v.min(), "max": v.max(), "trimmed": listing.trimmed(y), "mean_a": float(np.nanmean(real[name]["a"])), "mean_b": float(np.nanmean(real[name]["b"]))})
    groups = {}
    for f in fold_names:
        groups[f"fold {f}"] = (E["fold"] == f).to_numpy()
    qtr = days.tz_localize(None).to_period("Q").astype(str)
    for qq in sorted(set(qtr)):
        groups[f"quarter {qq}"] = (qtr == qq)
    groups["size ≥ 1 % of max supply"] = (E["pct_max"] >= 1).to_numpy()
    groups["size 0.1–1 %"] = (E["pct_max"] < 1).to_numpy()
    for st in ("same", "amount", "not as dated"):
        groups[f"today: {st}"] = (E["today"] == st).to_numpy()
    ins = E["recipients"].fillna("").str.lower().str.contains(INSIDER_RE, regex=True).to_numpy()
    groups["recipients name insiders (team / investors …)"] = ins
    groups["recipients other or unnamed"] = ~ins
    s90 = _state(days, state_daily)
    groups["S90 +1 at D (after a rising quarter)"] = s90 > 0
    groups["S90 −1 at D (after a falling quarter)"] = s90 < 0
    for wd, lab in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        groups[f"weekday {lab}"] = (days.dayofweek == wd)
    top = E["perp"].value_counts()
    groups["without the three names with the most events"] = ~E["perp"].isin(top.index[:3]).to_numpy()
    splits = pd.DataFrame(_split(real, cen, groups))
    names = top.head(10).rename("events").to_frame()
    names["M_c_after_7d"] = [float(np.nanmean(y7[(E["perp"] == p).to_numpy()])) - cen["after_7d"] for p in names.index]
    names["M_c_into_7d"] = [float(np.nanmean(real["into_7d"]["y"][(E["perp"] == p).to_numpy()])) - cen["into_7d"] for p in names.index]
    # the money through the harness: a SOLD position, the name's own legs
    money = []
    try:
        C2 = bt.load_costs(fr.M.index, fr.M.columns, fr.b, cost_mult=2.0, close=fr.M.close)
    except Exception:                                                  # the made-up world has no cost table: the ×1 rows only
        C2 = None
    for name in ("into_7d", "after_7d", "after_1d"):
        t = days - (INTO_DAYS * DAY if name.startswith("into") else pd.Timedelta(0))
        for side, sname in ((-1, "sold"), (1, "bought")):
            for mult, CC in ((1, fr.C), (2, C2)):
                if CC is None:
                    continue
                dec = pd.DataFrame({"t": t, "symbol": E["perp"].to_numpy(), "side": side, "hold": ROWS[name], "size": 1.0, "fold": E["fold"].to_numpy(), "accepted": True})
                f = bt.price(dec, fr.M, CC, "taker", taker_bps, 2.0)
                money.append({"row": name, "side": sname, "cost": f"×{mult}", "n_priced": int(f["net_bps"].notna().sum()), "gross": f["gross_bps"].mean(), "fee": f["fee_bps"].mean(),
                              "spread_impact": f["other_cost_bps"].mean(), "funding": f["funding_bps"].mean(), "net": f["net_bps"].mean(), "net_median": f["net_bps"].median(), "hedged_net": f["hedged_net_bps"].mean()})
    # reference rows
    own = fr.M.columns.get_indexer(E["perp"])
    btc = fr.M.columns.get_loc(BTC) if BTC in fr.M.columns else -1
    ref = []
    for name, h in ROWS.items():
        at = fr.mid_index(days - (INTO_DAYS * DAY if name.startswith("into") else pd.Timedelta(0)))
        a = real[name]["a"]
        rec = {"row": name, "M_c (the family)": float(tab.set_index("row").loc[name, "M_c"]), "a alone": float(np.nanmean(a))}
        if btc >= 0:
            yb = a - fr.L[h][np.where(at >= 0, at, 0), btc]
            yb[at < 0] = np.nan
            rec["M against BTC"] = float(np.nanmean(yb))
        if name.startswith("after"):
            r1 = fr.rows(E["perp"].to_numpy(), days + DAY)[name]["y"]
            rec["M entered a day later (D + 1)"] = float(np.nanmean(r1))
        else:
            r0 = fr.rows(E["perp"].to_numpy(), days - INTO_DAYS * DAY)[name]["y"]
            rec["M the week before (D − 14 → D − 7, a control)"] = float(np.nanmean(r0))
        ref.append(rec)
    hind_rows = []
    if hind is not None and len(hind):
        H = hind[hind["day"].isin(fr.days) & hind["perp"].isin(fr.M.columns)]
        if len(H):
            rh = fr.rows(H["perp"].to_numpy(), pd.DatetimeIndex(H["day"]))
            hind_rows = [{"row": n, "n": int(np.isfinite(rh[n]["y"]).sum()), "M": float(np.nanmean(rh[n]["y"])), "M_c (the family's centre)": float(np.nanmean(rh[n]["y"])) - cen[n],
                          "median": float(np.nanmedian(rh[n]["y"]))} for n in ROWS]
    return {"dist": pd.DataFrame(dist), "splits": splits, "names": names.reset_index().rename(columns={"index": "perp"}), "money": pd.DataFrame(money), "ref": pd.DataFrame(ref),
            "hindsight": pd.DataFrame(hind_rows), "n_hindsight": int(len(hind)) if hind is not None else 0}


# ---- the stages --------------------------------------------------------------------------------------------------------------------
def _frame(tag: str, ev: pd.DataFrame, members_csv: Path | str, fold_names, market=None, window=None):
    a, b = window or stage_window(fold_names)
    mem = universe.members(members_csv)
    syms = sorted(set(ev["perp"]) | set(universe.screen_symbols(members_csv)) | {BTC})
    if market is None:
        M = bt.market(syms, b, a - (INTO_DAYS + 1) * DAY)
        C = bt.load_costs(M.index, M.columns, b, close=M.close)
    else:
        M, C = market
    return Frame(M, C, mem, a, b)


def _head(title: str, fr: Frame, E: pd.DataFrame, ks, v: dict) -> list[str]:
    return [f"# R51 — {title}\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(E)} events on {E['perp'].nunique()} names · window {fr.a:%Y-%m-%d} → {fr.b:%Y-%m-%d}, {fr.span} event days · "
            f"{len(ks)} shifts (gap {GAP_DAYS} days) · unit {bt.UNIT}, charged on {bt.CHARGED}\n", f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]


def stage1(frozen: Path | str = FROZEN["f12"], members_csv: Path | str = MEMBERS["f12"], fold_names=STAGE_FOLDS["f12"], out: Path = OUT, state_daily: Path | None = STATE_DAILY,
           taker_bps: float = TAKER_BPS, min_members: int = MIN_MEMBERS, min_events: int = MIN_EVENTS, market=None, tables=None, draws: int = DRAWS, window=None) -> dict:
    """tables: (fin, asof) for the made-up world; the real run reads events.UNLOCKS / events.ASOF."""
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    tag = "f12"
    fold_names = folds.order(fold_names)
    ev = load_events(frozen)
    fin, asof = tables if tables is not None else (pd.read_parquet(events.UNLOCKS), pd.read_parquet(events.ASOF))
    memdf = members_df(members_csv, tag)
    fresh = promised_events(fin, asof, memdf)
    repro = reproduce(ev, fresh)
    fp = fingerprint() if tables is None else {}
    fr = _frame(tag, ev, members_csv, fold_names, market, window)
    ev = eligible(ev, fr)
    E = ev[ev["eligible"]].reset_index(drop=True)
    real = fr.rows(E["perp"].to_numpy(), pd.DatetimeIndex(E["day"]))
    ks = shifts(fr.span)
    null = shift_null(fr, E["perp"].to_numpy(), pd.DatetimeIndex(E["day"]), ks)
    ident = _identity(fr, E, real, taker_bps)
    v = validity(tag, ev, E, fr, real, null, ks, repro, fp, ident, min_members, min_events)
    v["stage"] = 1
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    ev.to_csv(out / "events_labelled.csv", index=False)
    head = _head(f"token unlocks on the members, stage 1 ({'+'.join(fold_names)})", fr, E, ks, v)
    if v["status"] != "PASS":
        (out / "stage1.md").write_text("\n".join(head + ["\n**The read is VOID: nothing of the family was computed.**\n"]))
        print("validity FAIL — stage 1 is void", flush=True)
        raise SystemExit(2)
    tab = family(real, null, E["fold"].to_numpy(), fold_names)
    tab["verdict"] = [verdict1(r, fold_names) for r in tab.to_dict("records")]
    tab["bar"] = BAR_BPS
    # R28's bootstrap and the plain se, described beside
    wk, W = listing.weeks(pd.DatetimeIndex(E["day"]))
    bs = listing.bootstrap(np.column_stack([real[n]["y"] for n in ROWS]), wk, W, draws=draws, seed=SEED)
    tab["se_bootstrap_weeks"], tab["se_plain"], tab["p_fw_bootstrap"] = bs["se"], bs["se_plain"], bs["p_fw"]
    hind = hindsight_events(fin, asof, memdf, ev)
    D = described(fr, E, real, tab, fold_names, state_daily, taker_bps, hind)
    cleared = [{"row": r["row"], "sign": int(np.sign(r["M_c"])), "M_c": float(r["M_c"]), "se": float(r["se"]), "u": float(r["u"])} for r in tab.to_dict("records") if r["verdict"] == "CLEARS"]
    summary = {"registration": "R51", "stage": 1, "validity": v, "rows": tab.to_dict("records"), "cleared": cleared, "run_stage2": bool(cleared), "verdicts": tab["verdict"].value_counts().to_dict(),
               "described": {k: (d.to_dict("records") if isinstance(d, pd.DataFrame) else d) for k, d in D.items()}, "seconds": round(time.time() - t0, 1), "written": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    (out / "stage1.json").write_text(json.dumps(summary, indent=1, default=str))
    tab.to_csv(out / "rows.csv", index=False)
    null.to_parquet(out / "shifts.parquet", index=False)
    for n in ROWS:
        for k in ("a", "b", "n_b", "y"):
            E[f"{k}_{n}"] = real[n][k]
    E.to_csv(out / "events_labelled.csv", index=False)
    (out / "stage1.md").write_text("\n".join(head + _report(summary, tab, D, fold_names)))
    print(f"R51 stage 1: {len(cleared)} of {len(tab)} clear; stage 2 {'runs' if cleared else 'is not run'}; wrote {out}/", flush=True)
    return summary


def _report(s: dict, tab: pd.DataFrame, D: dict, fold_names) -> list[str]:
    show = lambda df, k=1: df.round(k).to_markdown(index=False)       # noqa: E731
    main = ["row", "n", "M", "centre", "M_c", "se", "u", "MDE", "lower", "upper", "M_trim_c", *[f"M_c_{f}" for f in fold_names], "p_single", "p_family", "bar", "verdict"]
    more = ["row", "n", "median", "share_below_0", "se_bootstrap_weeks", "se_plain", "p_fw_bootstrap", "shifts_kept"]
    cl = s["cleared"]
    return ["\nWords: an event is a promised cliff day D on a member (the last archived page at least 7 days before D dated it). *into_7d* is a LONG of the name entered at "
            "D − 7 d 00:05 UTC and held to D 00:05, against the mean of the block's members over the same bars (y = a − b, bps of the position; a sold position earns −y); "
            "*after_1d / 3d / 7d* the same entered at D 00:05. *centre* is the mean of the row over every whole-day shift of the event dates, *M_c* = M − centre, *u* = M_c / se, "
            "*p_family* the share of shifts on which the best of the four rows did at least as well. Bar 46 bps (twice a member's taker round trip). A NEGATIVE M_c means the name "
            "fell against its peers.\n",
            f"\n## The family — four rows: **{len(cl)} CLEARS** ({json.dumps(s['verdicts'])}); stage 2 {'RUNS on the cleared rows' if cl else 'is NOT run — F3+F4 stays unread for unlocks'}\n",
            show(tab[main], 2), "\n", "\n### Described beside (decides nothing): the median, the share below zero, R28's week bootstrap and the plain se\n", show(tab[more], 2), "\n",
            "\n## Described — the distribution of y (bps), a and b apart\n", show(D["dist"]), "\n",
            "\n## Described — M_c by fold, quarter, size, what today's schedule says of the event, recipients, S90, weekday, without the top names\n", show(D["splits"]), "\n",
            "\n## Described — the names with the most events\n", show(D["names"]), "\n",
            "\n## Described — the money through the harness (the name's own legs as a taker, no benchmark; `costwide`'s proxy and its double)\n", show(D["money"]) if len(D["money"]) else "(no cost table)", "\n",
            "\n## Reference rows — no verdict\n", show(D["ref"]), "\n",
            f"\n## Reference — the hindsight set: today's file's cliffs on the members that the snapshots did not promise ({D['n_hindsight']} events; why it is not the family)\n",
            show(D["hindsight"]) if len(D["hindsight"]) else "(none in the window)", "\n"]


def stage2(frozen: Path | str = FROZEN["f34"], members_csv: Path | str = MEMBERS["f34"], fold_names=STAGE_FOLDS["f34"], out: Path = OUT, taker_bps: float = TAKER_BPS,
           min_members: int = MIN_MEMBERS, min_events: int = MIN_EVENTS, market=None, tables=None, window=None) -> dict:
    t0 = time.time()
    s1 = json.loads((out / "stage1.json").read_text())                 # (7) stage 1 on disk first; the cleared rows read from it
    cleared = s1["cleared"]
    if not cleared:
        res = {"registration": "R51", "stage": 2, "verdict": "NOTHING TO CONFIRM", "confirmed": False, "stage1_written": s1["written"], "rows": [], "note": "stage 1 cleared nothing; F3+F4 not read for unlocks"}
        (out / "stage2.json").write_text(json.dumps(res, indent=1))
        (out / "stage2.md").write_text("# R51 — stage 2\n\n**NOTHING TO CONFIRM** — stage 1 cleared nothing; F3+F4 was not read for unlocks.\n")
        print("R51 stage 2: NOTHING TO CONFIRM (stage 1 cleared nothing); F3+F4 not read", flush=True)
        return res
    tag = "f34"
    fold_names = folds.order(fold_names)
    ev = load_events(frozen)
    fin, asof = tables if tables is not None else (pd.read_parquet(events.UNLOCKS), pd.read_parquet(events.ASOF))
    memdf = members_df(members_csv, tag)
    repro = reproduce(ev, promised_events(fin, asof, memdf))
    fp = fingerprint() if tables is None else {}
    fr = _frame(tag, ev, members_csv, fold_names, market, window)
    ev = eligible(ev, fr)
    E = ev[ev["eligible"]].reset_index(drop=True)
    real = fr.rows(E["perp"].to_numpy(), pd.DatetimeIndex(E["day"]))
    ks = shifts(fr.span)
    null = shift_null(fr, E["perp"].to_numpy(), pd.DatetimeIndex(E["day"]), ks)
    ident = _identity(fr, E, real, taker_bps)
    v = validity(tag, ev, E, fr, real, null, ks, repro, fp, ident, min_members, min_events)
    v.update({"stage": 2, "cleared_from_stage1": cleared, "stage1_written": s1["written"]})
    (out / "validity_f34.json").write_text(json.dumps(v, indent=1, default=str))
    head = _head(f"stage 2, the confirmation on {'+'.join(fold_names)}'s promised events, the rows stage 1 cleared", fr, E, ks, v)
    if v["status"] != "PASS":
        (out / "stage2.md").write_text("\n".join(head + ["\n**The read is VOID: nothing was computed on F3+F4.**\n"]))
        print("validity FAIL — stage 2 is void", flush=True)
        raise SystemExit(2)
    signs = {c["row"]: int(c["sign"]) for c in cleared}
    tab = family(real, null, E["fold"].to_numpy(), fold_names, signs=signs)
    fact = {c["row"]: float(c["M_c"]) for c in cleared}
    tab["verdict"] = [verdict2(r["M_c"], r["se"], r["p_family"], signs[r["row"]], fact[r["row"]], r["signed_u"], r["M_trim_c"]) if r["row"] in signs else "(not cleared in stage 1 — described)" for r in tab.to_dict("records")]
    confirmed = bool((tab[tab["row"].isin(signs)]["verdict"] == "CLEARS").any())
    res = {"registration": "R51", "stage": 2, "verdict": "CONFIRMED" if confirmed else "NOT CONFIRMED", "confirmed": confirmed, "validity": v, "rows": tab.to_dict("records"), "cleared_from_stage1": cleared,
           "stage1_written": s1["written"], "seconds": round(time.time() - t0, 1), "written": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    (out / "stage2.json").write_text(json.dumps(res, indent=1, default=str))
    tab.to_csv(out / "rows_f34.csv", index=False)
    null.to_parquet(out / "shifts_f34.parquet", index=False)
    main = ["row", "n", "M", "centre", "M_c", "se", "signed_u", "MDE", "lower", "upper", "M_trim_c", *[f"M_c_{f}" for f in fold_names], "p_single", "p_family", "verdict"]
    (out / "stage2.md").write_text("\n".join(head + [f"\n## Verdict: **{res['verdict']}** — the cleared rows one-sided with the signs fixed from stage 1 ({json.dumps(signs)})\n", tab[main].round(2).to_markdown(index=False), "\n"]))
    print(f"R51 stage 2: {res['verdict']}; wrote {out}/", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["select", "stage1", "stage2"])
    args = ap.parse_args()
    {"select": select, "stage1": stage1, "stage2": stage2}[args.stage]()


if __name__ == "__main__":
    main()
