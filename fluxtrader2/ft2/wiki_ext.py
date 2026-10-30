"""R72 (P8 decision BQ1, 2026-10-30, docs/PLAN.md §8) — the attention screen: R62's screen on the screener's F1+F2 members that have a STRICT
Wikipedia article (`ft2/wiki_articles.csv`, source own / chain / company — a proxy is NOT a cell), the source `data/wiki_views.parquet`
(DATA.md `wiki_views`; BP1's fetch, NOT re-fetched for this read).

The registered feature, DAILY, joined to P2's 5m cells at the known-at stamp:
  wiki_dev      `wiki.dev` on the name's daily views: X = log(1 + views) (the article's count plus its redirects'), the deviation from the
                trailing MONTH_D = 30 days' mean over their sd, ≥ MIN_MONTH_D = 15 days present (the first value on the article's 15th day),
                the sd ≤ 0 → NaN. Day d's value is read at `ts_known(d)` = d + KNOWN_AT_H hours (the parquet's column: 48 h, or 36 h if the two
                UTC-morning probes allowed it — `wiki.KNOWN_AT_H`, the one allowed edit of `wiki`), it stands at every cell t with ts_known(d)
                + MARGIN ≤ t < ts_known(d) + CARRY_H + MARGIN (the hour grid's floor(t − MARGIN), carried ≤ CARRY_H − 1 = 23 hours), and it
                is NOT carried past that: a cell reads the LATEST stamped day, at most 24 h past its stamp, else NaN.
The family = the feature × 1d on the RELATIVE bet (ONE cell; no 4h — a daily count read at D+2 cannot speak to a 4h bar); the sign fixed
NEGATIVE (R72_SIGN: a name read far above its month two days ago falls behind its peers over the next day); both nulls at DRAWS; p_family =
the larger of the two nulls' p on the one cell; the gate R62's (`cb_ext.verdict_r62`: p_family ≤ 0.05, the sign, both folds, |IC| ≥
BAR_TWELVE 0.0159). The universe = the 38 names derived IN CODE from the two frozen files (`names_r72`) and asserted against the registered
list (NAMES_R72); a name's cells are those where it is a member of the bar's block (`cb_ext.membership`).
Described beside, no nulls, no verdict: `wiki_lvl` (X minus the trailing 30-day mean, no sd), `wiki_dev_3d` (the registered feature at a 3-day
horizon through R67's `extend`), `wiki_dev_old` (the registered feature on the names whose article existed before F1's start — the parquet's
first day before 2023-05-01), `wiki_dev_proxy` (APE, the one F1+F2 member whose article is a proxy), `wiki_dev_twelve` (the twelve's strict
articles on P2's cells of the twelve's panel — BB's clause: a described row, never a cell), per name the share of scored cells whose day had
0 views (`names.parquet`); the directional and the vol bets of every row.

Validity, read first, void (exit 2) on any FAIL, before any view is joined to a label: (4) the frozen inputs — the two files' md5, the 38
names, the parquet's fingerprint (rows, symbols, first and last day; the SUM of `views` written, the record); (6) the stamp — `ts_known` − day
one constant over all rows, 36 or 48 h, equal to `wiki.KNOWN_AT_H`; (1) R62's saved screen reproduced through `cb_ext.frames` on the Coinbase
members' source (no nulls) and R60's saved bar within BAR_TOL; (2) known-at on the wiki frame — every scored cell with a value read at or after
its day's stamp and under 24 h past it, N_CHECK scored MEMBER cells of the 38 recomputed straight from the parquet's rows (log1p, the trailing
30 calendar days ≥ 15 present, the latest stamped day) to TOL_HAND; (3) membership asserted and R62's `block_coverage` at BLOCK_MIN_R72 = 10
names on ≥ 90 % of every block's scored bars, ≥ MIN_PAIRS names on ≥ 95 % of the bars; (5) strictness — no proxy, none of the twelve in the
registered frame, the three-name Terra tie present as three identical daily series; the nulls' admissibility (the shifts ≥ 60 > 31, the
shuffle gap ≥ 8). `cb_ext` and `wiki` are not edited; R62's helpers are called, none copied."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cb_ext as cx
from . import ceiling, coinbase as cb, folds, krw, wiki
from .book_ext import SHIFT_MIN, fold_ics, shift_feature, taker_bar
from .cb_ext import BAR_TOL, BAR_TWELVE, BET, HZ, MARGIN, MEMBERS_SLICES, MEMBERS_START, N_CHECK, PRIMARY
from .ceiling import HORIZONS, MDE_K, MIN_PAIRS, NULL_GAP, Z_CLIP, _null_feature
from .hold_ext import extend
from .spot_ext import GAP_MIN, SHIFT_FLOOR, TOL_HAND

DEV = "wiki_dev"                                          # registered
LVL, DEV3, OLD, PROXY, TWELVE_ROW = "wiki_lvl", "wiki_dev_3d", "wiki_dev_old", "wiki_dev_proxy", "wiki_dev_twelve"       # described
REGISTERED = (DEV,)
FAMILY_CELLS = [(DEV, PRIMARY)]
R72_SIGN = -1.0                                           # a name read far above its month two days ago falls behind its peers the next day
CARRY_H = 24                                              # a day's value stands this many hours past its stamp and no longer
STAMPS_ALLOWED = (36, 48)                                 # the two values the probe's rule may set; nothing in between
HOLD_3D = {"3d": 864}                                     # R67's `extend`: the 3d label, in 5m bars
ALL_H = {**HORIZONS, **HOLD_3D}
BLOCK_MIN_R72 = 10                                        # validity (3): the defect floor on a source that covers a fifth of the members
STRICT = ("own", "chain", "company")
HOUR = pd.Timedelta("1h")
F1_START = pd.Timestamp(folds.FOLDS["F1"][0], tz="UTC")   # `wiki_dev_old`: an article whose first day is before this
ARTICLES_CSV = wiki.ARTICLES
MEMBERS_CSV = Path(__file__).with_name("screen_members.csv")
OUT_MD = Path("output/ceiling_wiki_members.md")
OUT_DIR = Path("output/ceiling_wiki_members")
# the registration's constants (R72's Universe, Data and Validity (4) lines): the run derives and compares, the read compares with PLAN
EXPECT = {"md5_articles": "3b09d77ae18555e36ae8388acabde388", "md5_members": "0e55255d37412d3b63a021d3c8a732ab",
          "names": ["1000LUNCUSDT", "1000SHIBUSDT", "1INCHUSDT", "AAVEUSDT", "ALGOUSDT", "APTUSDT", "ARKMUSDT", "AXSUSDT", "BCHUSDT", "BNBUSDT", "CHZUSDT", "CKBUSDT",
                    "DOTUSDT", "EOSUSDT", "ETCUSDT", "FILUSDT", "GRTUSDT", "HBARUSDT", "ICXUSDT", "IMXUSDT", "INJUSDT", "IOTAUSDT", "LTCUSDT", "LUNA2USDT", "MANAUSDT",
                    "MATICUSDT", "NEARUSDT", "NEOUSDT", "PEOPLEUSDT", "PYTHUSDT", "STRKUSDT", "SUIUSDT", "TONUSDT", "TRXUSDT", "UNIUSDT", "USTCUSDT", "XLMUSDT", "XMRUSDT"],
          "rows": 93_994, "symbols": 66, "first_day": "2021-12-01", "last_day": "2026-10-28",
          "tie": ["1000LUNCUSDT", "LUNA2USDT", "USTCUSDT"], "proxy_member": "APEUSDT"}


def _md5(path: Path | str) -> str:
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# ---- the universe from the two frozen files ---------------------------------------------------------------------------------------------
def names_r72(members_csv: Path | str = MEMBERS_CSV, articles_csv: Path | str = ARTICLES_CSV) -> dict:
    """The member symbols whose base has a STRICT article (sorted); the proxy members; the article and source per symbol; the md5s."""
    A = wiki.frozen(articles_csv)
    A = A[A["article"].astype(bool)]
    src = dict(zip(A["base"], A["source"])) if "source" in A.columns else dict.fromkeys(A["base"], "own")
    art = dict(zip(A["base"], A["article"]))
    m = pd.read_csv(members_csv, usecols=["block", "symbol"])
    syms = sorted(set(m["symbol"]))
    strict = [s for s in syms if src.get(cb.base(s)) in STRICT]
    proxy = [s for s in syms if src.get(cb.base(s)) == "proxy"]
    return {"names": strict, "proxy": proxy, "article": {s: art[cb.base(s)] for s in strict + proxy}, "source": {s: src[cb.base(s)] for s in strict + proxy},
            "md5_members": _md5(members_csv), "md5_articles": _md5(articles_csv), "n_members": len(syms)}


def fingerprint(d: pd.DataFrame) -> dict:
    """The parquet's identity: rows, symbols, the first and the last day, the sum of `views` (the record — DATA.md holds no sum), the stamp."""
    lag = (pd.DatetimeIndex(d["ts_known"]) - pd.DatetimeIndex(d["day"])) / HOUR
    return {"rows": int(len(d)), "symbols": int(d["symbol"].nunique()), "articles": int(d["article"].nunique()), "first_day": str(d["day"].min().date()),
            "last_day": str(d["day"].max().date()), "views_sum": int(d["views"].sum()), "stamp_h": sorted({float(x) for x in np.unique(lag)})}


# ---- the daily series and the join at the stamp -------------------------------------------------------------------------------------------
def daily(d: pd.DataFrame, names: list[str]) -> dict[str, pd.DataFrame]:
    """Day × symbol frames on `names` from the parquet's rows: `views`, the stamp `ts_known`, the deviation (`wiki.dev`), the level, the
    zero-view flag. A symbol's days are the parquet's (a full daily grid from the later of START and the article's creation)."""
    x = d[d["symbol"].isin(names)]
    grid = pd.date_range(x["day"].min(), x["day"].max(), freq="D")                      # calendar days: a missing day is NaN and counts as absent
    V = x.pivot(index="day", columns="symbol", values="views").reindex(grid)
    K = x.pivot(index="day", columns="symbol", values="ts_known").reindex(grid)
    X = np.log1p(V)
    lvl = X - X.rolling(wiki.MONTH_D, min_periods=wiki.MIN_MONTH_D).mean()
    return {"views": V, "ts_known": K, DEV: wiki.dev(V), LVL: lvl, "zero": (V == 0).astype(float).where(V.notna())}


def to_hourly(W: pd.DataFrame, K: pd.DataFrame) -> pd.DataFrame:
    """A day × symbol frame → the hourly grid of ts_known: each day's value at the hour of its stamp, NaN elsewhere."""
    parts = {}
    for c in W.columns:
        k = K[c].dropna()
        parts[c] = pd.Series(W[c].reindex(k.index).to_numpy(), index=pd.DatetimeIndex(pd.to_datetime(k.to_numpy(), utc=True)))
    H = pd.DataFrame(parts)
    grid = pd.date_range(H.index.min().floor("h"), H.index.max().floor("h") + (CARRY_H - 1) * HOUR, freq="h")
    return H.reindex(grid)


def to_panel(H: pd.DataFrame, idx: pd.DatetimeIndex, cols: list[str]) -> pd.DataFrame:
    """The hourly grid → P2's 5m cells: the value at floor(t − MARGIN), a day's value carried ≤ CARRY_H − 1 hours past its stamp."""
    out = H.ffill(limit=CARRY_H - 1).reindex(cx.keys(idx))
    out.index = idx
    return out.reindex(columns=cols)


def used_hours(H: pd.DataFrame, idx: pd.DatetimeIndex, cols: list[str]) -> pd.DataFrame:
    """Per 5m cell the stamp hour actually read, in whole hours since the epoch (NaN where none within CARRY_H)."""
    h = (H.index.asi8 // 3_600_000_000_000).astype(float)
    U = pd.DataFrame({c: np.where(H[c].notna(), h, np.nan) for c in H.columns}, index=H.index)
    return to_panel(U, idx, cols)


def frames_wiki(d: pd.DataFrame, names: list[str], idx: pd.DatetimeIndex, cols: list[str]) -> dict:
    """The 5m frames on `cols` for `names`: the deviation, the level, the zero flag, the used stamp hour; the daily frames beside."""
    Dd = daily(d, names)
    Hd = {k: to_hourly(Dd[k], Dd["ts_known"]) for k in (DEV, LVL, "zero", "views")}       # `views` is on every row: its hourly grid marks the stamps read
    F = {k: to_panel(Hd[k], idx, cols) for k in (DEV, LVL, "zero")}
    return {"F": F, "U": used_hours(Hd["views"], idx, cols), "daily": Dd, "hourly": Hd}


def frames_r72(names: list[str], extra: list[str], d: pd.DataFrame, slices: tuple[str, ...], members_csv: Path | str | None, start: pd.Timestamp = MEMBERS_START,
               end: pd.Timestamp | None = None) -> dict:
    """R62's members' frame on the wiki source: the panel on `names` + `extra` (the proxy row's name), the frames masked to `names` and to
    membership, the proxy's frame masked to membership, the used hours."""
    end = end or ceiling.END
    panel_names = sorted(set(names) | set(extra))
    P = cx.member_panel(panel_names, start, end, slices)
    D = ceiling.derive(P)
    idx, cols, s = D["lr"].index, list(D["lr"].columns), D["scored"]
    W = frames_wiki(d, panel_names, idx, cols)
    M, m = cx.membership(idx, cols, members_csv)
    F = cx.mask_members(cx.restrict(W["F"], names), M)
    Fx = cx.mask_members(cx.restrict(W["F"], extra), M) if extra else None
    return {"names": names, "extra": extra, "P": P, "D": D, "idx": idx, "cols": cols, "s": s, "F_all": W["F"], "F": F, "Fx": Fx, "U": W["U"], "daily": W["daily"],
            "hourly": W["hourly"], "M": M, "m": m}


# ---- validity (2): known-at and the feature by hand -------------------------------------------------------------------------------------
def hand_value(rows: pd.DataFrame, t: pd.Timestamp) -> tuple[float, float]:
    """(the deviation read at the 5m bar t, the stamp hour used) straight from one symbol's parquet rows: the latest day whose ts_known +
    MARGIN ≤ t, read only if t < its ts_known + CARRY_H + MARGIN; X = log1p(views) over the trailing MONTH_D calendar days ending at that day,
    ≥ MIN_MONTH_D of them present, the mean and the sd (ddof 1) by numpy; the sd ≤ 0 → NaN."""
    k = pd.DatetimeIndex(rows["ts_known"])
    ok = k + MARGIN <= t
    if not ok.any():
        return np.nan, np.nan
    i = int(np.flatnonzero(ok)[-1])
    if t >= k[i] + CARRY_H * HOUR + MARGIN:
        return np.nan, np.nan
    used = float(k[i].value // 3_600_000_000_000)
    day = pd.Timestamp(rows["day"].iloc[i])
    w = rows[(pd.DatetimeIndex(rows["day"]) > day - wiki.MONTH_D * wiki.DAY) & (pd.DatetimeIndex(rows["day"]) <= day)]
    if len(w) < wiki.MIN_MONTH_D:
        return np.nan, used
    x = np.log1p(w["views"].to_numpy(dtype=float))
    sd = float(np.std(x, ddof=1))
    return (float(np.log1p(float(rows["views"].iloc[i])) - x.mean()) / sd if sd > 0 else np.nan), used


def hand_check(fr: dict, d: pd.DataFrame, n_check: int = N_CHECK, seed: int = 0, tol: float = TOL_HAND) -> dict:
    """Validity (2b): `n_check` random scored MEMBER cells of the registered names — the frame's value and its used hour equal `hand_value`'s."""
    F, U, s, idx, names, M = fr["F"], fr["U"], fr["s"], fr["idx"], fr["names"], fr["M"]
    sidx = idx[s]
    cols = [c for c in names if c in F[DEV].columns]
    rng = np.random.default_rng(seed)
    Ms = M[s][cols].to_numpy()
    cand_i, cand_j = rng.integers(0, len(sidx), 4 * n_check), rng.integers(0, len(cols), 4 * n_check)
    on = Ms[cand_i, cand_j]
    ii, jj = cand_i[on][:n_check], cand_j[on][:n_check]
    rows_of = {c: g.sort_values("day").reset_index(drop=True) for c, g in d[d["symbol"].isin(cols)].groupby("symbol")}
    worst, n_val, n_nan = 0.0, 0, 0
    for i, j in zip(ii, jj):
        c, t = cols[j], sidx[i]
        got, u = float(F[DEV][c].loc[t]), float(U[c].loc[t])
        exp, exp_u = hand_value(rows_of[c], t) if c in rows_of else (np.nan, np.nan)
        worst = max(worst, 0.0 if (np.isnan(u) and np.isnan(exp_u)) else abs(u - exp_u) if np.isfinite(u) and np.isfinite(exp_u) else np.inf)
        if np.isnan(got) and np.isnan(exp):
            n_nan += 1
            continue
        n_val += 1
        worst = max(worst, abs(got - exp) if np.isfinite(got) and np.isfinite(exp) else np.inf)
    return {"status": "PASS" if worst <= tol and len(ii) == n_check else "FAIL", "recomputed": int(len(ii)), "cells_with_a_value": n_val, "cells_nan_both": n_nan,
            "max_abs_diff": float(worst), "names_checked": int(len(set(cols[j] for j in jj))), "tol": tol}


def known_at(fr: dict) -> dict:
    """Validity (2a): on every scored cell with a value the stamp used has ts_known + MARGIN ≤ t and t < ts_known + CARRY_H + MARGIN."""
    F, U, s, idx, names = fr["F"], fr["U"], fr["s"], fr["idx"], fr["names"]
    sidx = idx[s]
    th = ((sidx - MARGIN).asi8 // 3_600_000_000_000).astype(float)
    cols = [c for c in names if c in F[DEV].columns]
    Us, has = U[s][cols].to_numpy(), F[DEV][s][cols].notna().to_numpy()
    early = has & ~(Us <= th[:, None])
    old = has & (th[:, None] - Us >= CARRY_H)
    unknown = has & ~np.isfinite(Us)
    return {"status": "PASS" if not (early.any() or old.any() or unknown.any()) else "FAIL", "cells_with_a_value": int(has.sum()), "cells_read_too_early": int(early.sum()),
            "cells_older_than_carry": int(old.sum()), "cells_without_a_used_hour": int(unknown.sum()), "margin": str(MARGIN), "carry_hours": CARRY_H}


# ---- validity (5): strictness ---------------------------------------------------------------------------------------------------------------
def strictness(fr: dict, L: dict, twelve: list[str], tie: list[str]) -> dict:
    """No proxy and none of the twelve among the registered frame's names with a value; the tie's names present as columns with identical
    daily deviation series (NaN = NaN)."""
    F, s = fr["F"], fr["s"]
    with_value = [c for c in F[DEV].columns if F[DEV][s][c].notna().any()]
    bad_proxy = [c for c in with_value if L["source"].get(c) == "proxy" or c in L["proxy"]]
    bad_twelve = [c for c in with_value if c in set(twelve)]
    Dd = fr["daily"][DEV]
    tie_in = [c for c in tie if c in Dd.columns]
    same = bool(len(tie_in) == len(tie) > 0 and all(Dd[tie_in[0]].equals(Dd[c]) for c in tie_in[1:]))
    return {"status": "PASS" if not bad_proxy and not bad_twelve and same else "FAIL", "names_with_a_value": len(with_value), "proxy_in_frame": bad_proxy,
            "twelve_in_frame": bad_twelve, "tie": tie, "tie_in_frame": tie_in, "tie_identical_series": same}


# ---- the run ----------------------------------------------------------------------------------------------------------------------------------
def run_r72(taker_bps: float, maker_bps: float, fee_source: str, twelve: list[str], draws: int = ceiling.DRAWS, seed: int = 0, shift_min: int = SHIFT_MIN, jobs: int = 1,
            path: Path | str = wiki.PARQUET, cb_path: Path | str = cb.MEMBERS_PARQUET, r62: Path = cx.MEMBERS_OUT_DIR, r60: Path = cx.OUT_DIR, cb_csv: Path | str = cx.R62_CSV,
            members_csv: Path | str = MEMBERS_CSV, articles_csv: Path | str = ARTICLES_CSV, slices: tuple[str, ...] = MEMBERS_SLICES, mult: dict[str, float] | None = None,
            n_check: int = N_CHECK, start: pd.Timestamp = MEMBERS_START, end: pd.Timestamp | None = None, block_min_names: int = BLOCK_MIN_R72, gap: int = NULL_GAP,
            shift_floor: int = SHIFT_FLOOR, expect: dict = EXPECT, known_at_h: int | None = None, out_md: Path = OUT_MD, out_dir: Path = OUT_DIR) -> str:
    from joblib import Parallel, delayed
    out_dir.mkdir(parents=True, exist_ok=True)
    end = end or ceiling.END
    known_at_h = wiki.KNOWN_AT_H if known_at_h is None else known_at_h
    L = names_r72(members_csv, articles_csv)
    names, proxy = L["names"], [s for s in L["proxy"] if s == expect.get("proxy_member")] or L["proxy"][:1]
    d = wiki.load(path)
    fp = fingerprint(d)
    validity = {"registration": "R72", "folds": list(folds.EXPLORATION), "draws": draws, "seed": seed, "shift_min": shift_min, "gap": gap, "source": str(path),
                "gate": {"bar_twelve": BAR_TWELVE, "sign": R72_SIGN, "family": FAMILY_CELLS, "p_max": 0.05}}
    # (4) the frozen inputs and the parquet's fingerprint; (6) the stamp — before anything else is read
    validity["inputs"] = {"articles": {"path": str(articles_csv), "md5": L["md5_articles"], "expected": expect["md5_articles"]},
                          "members": {"path": str(members_csv), "md5": L["md5_members"], "expected": expect["md5_members"], "n_members": L["n_members"]},
                          "names": names, "n_names": len(names), "names_expected": list(expect["names"]), "proxy_members": L["proxy"], "proxy_row": proxy,
                          "fingerprint": fp, "fingerprint_expected": {k: expect[k] for k in ("rows", "symbols", "first_day", "last_day")},
                          "status": "PASS" if L["md5_articles"] == expect["md5_articles"] and L["md5_members"] == expect["md5_members"] and names == list(expect["names"])
                          and all(fp[k] == expect[k] for k in ("rows", "symbols", "first_day", "last_day")) else "FAIL"}
    validity["stamp"] = {"stamp_h_in_parquet": fp["stamp_h"], "known_at_h": known_at_h, "allowed": list(STAMPS_ALLOWED), "probes": [{k: v for k, v in p.items() if k != "views"} for p in wiki.probes()],
                         "status": "PASS" if fp["stamp_h"] == [float(known_at_h)] and known_at_h in STAMPS_ALLOWED else "FAIL"}
    validity["nulls"] = {"status": "PASS" if shift_min > shift_floor and gap >= GAP_MIN else "FAIL", "shift_min": shift_min, "shift_floor": shift_floor, "gap": gap, "gap_min": GAP_MIN}
    if any(validity[k]["status"] != "PASS" for k in ("inputs", "stamp", "nulls")):
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # (1) R62's frame reproduced through cb_ext.frames on the Coinbase members' source, no nulls; R60's saved bar
    print(f"validity (1): R62's frame on the Coinbase members — the six features against {r62}/screen.parquet…", flush=True)
    Lcb = cx.r62_list(cb_csv)
    frc = cx.frames(Lcb, "coinbase", cb_path, slices, mult, members_csv, start, end)
    sc_cb, _ = ceiling.ic_screen(frc["D"], cx.screen_frames_r62(frc), set())
    validity["reproduction"] = cx.reproduction_r62(sc_cb, r62) | {"cb_list": {"path": str(cb_csv), "md5": Lcb["md5"], "n_kept": Lcb["n_kept"]}}
    del frc, sc_cb
    saved_mv = pd.read_parquet(r60 / "move_vs_cost.parquet") if (r60 / "move_vs_cost.parquet").exists() else None
    if saved_mv is not None:
        sm = saved_mv[(saved_mv["bet"] == BET) & (saved_mv["horizon"] == PRIMARY)]
        validity["gate"]["bar_r60_saved"] = float(sm["ic_needed_maker"].iloc[0]) if len(sm) else np.nan
        validity["gate"]["bar_status"] = "PASS" if len(sm) and abs(float(sm["ic_needed_maker"].iloc[0]) - BAR_TWELVE) <= BAR_TOL else "FAIL"
    else:
        validity["gate"]["bar_status"] = "MISSING"
    if validity["reproduction"]["status"] != "PASS" or validity["gate"]["bar_status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)

    # the wiki frame on the members; (2) known-at and by hand, (3) membership and coverage, (5) strictness — before any IC
    print("the members' panel and the wiki frames…", flush=True)
    fr = frames_r72(names, proxy, d, slices, members_csv, start, end)
    D, idx, cols, s, F, M, m = fr["D"], fr["idx"], fr["cols"], fr["s"], fr["F"], fr["M"], fr["m"]
    sidx = idx[s]
    validity |= {"scored_bars": int(s.sum()), "days": int(len(np.unique(sidx.floor("D")))), "names_in_panel": len(cols), "first": str(sidx[0]), "last": str(sidx[-1]),
                 "names_in_parquet": int(sum(c in set(d["symbol"]) for c in names)), "names_with_a_value": int(sum(F[DEV][s][c].notna().any() for c in names if c in cols))}
    print("validity (2): known-at; the feature by hand…", flush=True)
    validity["known_at"] = known_at(fr)
    validity["hand"] = hand_check(fr, d, n_check, seed)
    off = int((F[DEV].notna() & ~M).to_numpy().sum())
    validity["membership"] = {"status": "PASS" if off == 0 else "FAIL", "values_off_membership": off, "values_on": int(F[DEV][s].notna().to_numpy().sum()),
                              "values_before_the_mask": int(fr["F_all"][DEV][s][[c for c in names if c in cols]].notna().to_numpy().sum())}
    validity["coverage"], B = cx.block_coverage(F[DEV], s, m, names, block_min_names)
    validity["strictness"] = strictness(fr, L, twelve, list(expect["tie"]))
    first_day = fr["daily"]["views"].apply(lambda c: c.first_valid_index())
    old = sorted(c for c in names if c in first_day.index and pd.Timestamp(first_day[c]) < F1_START)
    validity["old_names"] = {"names": old, "n": len(old), "young": sorted(set(names) - set(old)), "rule": f"the parquet's first day before {F1_START.date()}"}
    checks = ("inputs", "stamp", "nulls", "reproduction", "known_at", "hand", "membership", "coverage", "strictness")
    validity["status"] = "PASS" if all(validity[k]["status"] == "PASS" for k in checks) and validity["gate"]["bar_status"] == "PASS" else "FAIL"
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    if validity["status"] != "PASS":
        return _void(validity, out_md, out_dir, taker_bps, maker_bps, fee_source)
    B.to_parquet(out_dir / "blocks.parquet", index=False)
    head = _head(validity, taker_bps, maker_bps, fee_source)

    # the screen: the registered feature; the described rows beside; the 3d horizon; the twelve
    print("screen: the registered feature; the level, the old names, the proxy; the 3d horizon…", flush=True)
    feats = {DEV: F[DEV], LVL: F[LVL], OLD: cx.restrict({OLD: F[DEV]}, old)[OLD]}
    if fr["Fx"] is not None:
        feats[PROXY] = fr["Fx"][DEV]
    sc, daily_ = ceiling.ic_screen(D, feats, set())
    D = extend(D, HOLD_3D)
    sc3, daily3 = ceiling.ic_screen(D, {DEV3: F[DEV]}, set(), HOLD_3D)
    Zs = {h: D["z"][h][s].clip(-Z_CLIP, Z_CLIP).to_numpy() for h in HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in HZ}
    print(f"nulls on {DEV}: {draws} day shuffles and {draws} whole-day shifts…", flush=True)
    null_shuffle, null_shift = Parallel(n_jobs=min(jobs, 2) if jobs > 1 else 1, prefer="threads")(
        [delayed(_null_feature)(DEV, F[DEV][s], Zs, Zr, draws, seed, gap=gap), delayed(shift_feature)(DEV, F[DEV], D, s, draws, seed, shift_min)])
    desc = describe_names(fr, L, old)
    print("the twelve's described row on P2's cells…", flush=True)
    sc12, daily12, twelve_strict = twelve_row(d, twelve, L, articles_csv)

    print("the bars…", flush=True)
    ct, _ = ceiling.bar_cost(idx, cols, taker_bps, maker_bps)
    bars_taker = {h: taker_bar(D, ct, h) for h in ALL_H}
    cost_cover = float(ct[s].notna().to_numpy().mean())

    key = ["bet", "horizon", "feature"]
    parts = [sc.merge(fold_ics(daily_), on=key, how="left"), sc3.merge(fold_ics(daily3, k_of=ALL_H), on=key, how="left")]
    if len(sc12):
        parts.append(sc12.merge(fold_ics(daily12), on=key, how="left"))
    rows = pd.concat(parts, ignore_index=True)
    daily_all = pd.concat([daily_, daily3, daily12], ignore_index=True)
    rows["ic_se"] = rows["ic_mde"] / MDE_K
    rows["bar_maker_twelve"] = np.where(rows["horizon"] == PRIMARY, BAR_TWELVE, np.nan)
    rows["bar_taker_members"] = rows["horizon"].map(bars_taker)
    for c in ("p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift"):
        rows[c] = np.nan
    for i, r in rows.iterrows():
        if r["feature"] in REGISTERED and r["bet"] in ("directional", "relative") and r["horizon"] in HZ:
            rows.loc[i, "p_single_shuffle"] = cx.single_p(null_shuffle, r["bet"], r["feature"], r["horizon"], r["t"])
            rows.loc[i, "p_single_shift"] = cx.single_p(null_shift, r["bet"], r["feature"], r["horizon"], r["t"])
    fam_rows = rows[(rows["bet"] == BET) & rows["feature"].isin(REGISTERED) & (rows["horizon"] == PRIMARY)]
    t_real = {(r["feature"], r["horizon"]): r["t"] for _, r in fam_rows.iterrows()}
    pf1, b1 = cx.family_p(null_shuffle, FAMILY_CELLS, t_real)
    pf2, b2 = cx.family_p(null_shift, FAMILY_CELLS, t_real)
    for i, r in fam_rows.iterrows():
        rows.loc[i, ["p_fw_shuffle", "p_fw_shift"]] = [pf1[r["feature"], r["horizon"]], pf2[r["feature"], r["horizon"]]]
    rows["p_family"] = rows[["p_fw_shuffle", "p_fw_shift"]].max(axis=1)
    rows["verdict"] = ""
    for i, r in rows.loc[fam_rows.index].iterrows():
        rows.loc[i, "verdict"] = cx.verdict_r62(r["ic"], r["ic_se"], r["p_family"], bool(r["folds_same_sign"]), BAR_TWELVE, R72_SIGN)
    rep = rows["feature"].isin(REGISTERED) & (rows["horizon"] != PRIMARY) & rows["bet"].isin(["directional", "relative"]) & rows["horizon"].isin(HZ)
    rows.loc[rep, "verdict"] = "reported, not gated"
    words = {LVL: "described (the level: log(1 + views) minus its trailing 30-day mean, no sd)",
             DEV3: "described (the registered feature at a 3-day horizon, R67's label; no null)",
             OLD: f"described (the registered feature on the {len(old)} names whose article existed before F1's start)",
             PROXY: f"described (the proxy article's deviation on {', '.join(proxy) or '—'} — one name: the relative bet is undefined, the directional one reported; never a cell)",
             TWELVE_ROW: f"described (the twelve's {len(twelve_strict)} strict articles on P2's cells of the twelve's panel — BB's clause)"}
    for f_, w in words.items():
        rows.loc[rows["feature"] == f_, "verdict"] = w
    bi = cx.block_ics(daily_, m, feature=DEV)

    rows.to_parquet(out_dir / "screen.parquet", index=False)
    daily_all.to_parquet(out_dir / "ic_daily.parquet", index=False)
    null_shuffle.to_parquet(out_dir / "null_shuffle.parquet", index=False)
    null_shift.to_parquet(out_dir / "null_shift.parquet", index=False)
    pd.DataFrame({"horizon": list(bars_taker), "ic_needed_taker_members": list(bars_taker.values()), "bar_maker_twelve": BAR_TWELVE, "cost_cover": cost_cover}).to_parquet(out_dir / "move_vs_cost.parquet", index=False)
    desc.to_parquet(out_dir / "names.parquet", index=False)
    Bb = B.merge(bi.rename(columns={"ic": "ic_wiki_dev", "se": "se_wiki_dev", "days": "days_wiki_dev"}), on="block", how="left")
    Bb.to_parquet(out_dir / "blocks.parquet", index=False)

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)                    # noqa: E731
    cols_show = ["bet", "horizon", "feature", "ic", "t", "ic_se", "ic_mde", "days", "months_same_sign", "ic_F1", "ic_F2", "folds_same_sign",
                 "p_single_shuffle", "p_single_shift", "p_fw_shuffle", "p_fw_shift", "p_family", "bar_maker_twelve", "bar_taker_members", "verdict"]
    g = rows[(rows["feature"] == DEV) & (rows["bet"] == BET) & (rows["horizon"] == PRIMARY)].iloc[0]
    md = head + [f"\n## Verdict by R72's gate — the one cell, `{DEV}`, {BET}, {PRIMARY}, on the {len(names)} members with a strict article\n",
                 f"\n- **`{DEV}`: {g['verdict']}** — IC {g['ic']:+.4f} (t {g['t']:+.2f}, se {g['ic_se']:.4f}, MDE {g['ic_mde']:.4f}); p_family {g['p_family']:.3f} (day shuffles "
                 f"{g['p_fw_shuffle']:.3f}, whole-day shifts {g['p_fw_shift']:.3f}; single {g['p_single_shuffle']:.3f} / {g['p_single_shift']:.3f}); F1 {g['ic_F1']:+.4f}, F2 {g['ic_F2']:+.4f} "
                 f"({'same sign' if g['folds_same_sign'] else 'signs differ'}); months the same sign {g['months_same_sign']:.2f}; the interval [{g['ic'] - 1.96 * g['ic_se']:+.4f}, {g['ic'] + 1.96 * g['ic_se']:+.4f}] against the bar {BAR_TWELVE}.\n",
                 f"\nThe gate's bar {BAR_TWELVE} (the twelve's maker bar at {PRIMARY}, a number); the members' own taker bar {bars_taker[PRIMARY]:.4f} (the cost proxy covers {cost_cover:.0%} of the scored cells); "
                 f"the registered sign {'positive' if R72_SIGN > 0 else 'negative'}; the stamp ts_known = day + {known_at_h} h; the parquet's sum of views {fp['views_sum']:,}.\n"]
    fam = rows["feature"].isin(REGISTERED) & rows["horizon"].isin(HZ) & rows["bet"].isin(["directional", "relative"])
    md += ["\n## The family (relative, 1d — the registered feature) with 1h / 4h and the directional bet beside\n",
           "`p_fw_*` = the share of a null's draws whose |t| on the ONE cell is at or above the real |t|; `p_single_*` = the same cell at the other horizons; `p_family` = the larger of the two nulls' "
           "p. `ic_F1`, `ic_F2` = the HAC mean of the daily IC inside each fold. `bar_maker_twelve` = the gate's number; `bar_taker_members` = the members' taker bar from their cost proxy.\n",
           show(rows[fam][cols_show]), "\n",
           "\n## Described beside (no nulls, no verdict): the level, the 3d horizon, the old names, the proxy, the twelve; 15m and the vol bet\n", show(rows[~fam][cols_show[:12] + ["bar_taker_members", "verdict"]]), "\n",
           "\n## The nulls' bars (|t| on the cell, per draw)\n", "```\n", json.dumps({"shuffle": b1, "shift": b2}, indent=1), "\n```\n",
           f"\n## By block — the names present and the relative {PRIMARY} IC of the feature inside the block (described)\n", show(Bb.assign(block=lambda d_: d_["block"].dt.date)), "\n",
           "\n## The names on their member cells (the zero-view share = the share of scored cells with a value whose day had 0 views)\n", show(desc), "\n"]
    out_md.write_text("".join(md))
    print(f"{DEV}: {g['verdict']}; wrote {out_md} and {out_dir}/", flush=True)
    return "".join(md)


def twelve_row(d: pd.DataFrame, twelve: list[str], L: dict, articles_csv: Path | str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """BB's clause: the twelve's STRICT articles on P2's cells of the twelve's panel (`ceiling.panel`, no membership) — one described row."""
    A = wiki.frozen(articles_csv)
    A = A[A["article"].astype(bool)]
    src = dict(zip(A["base"], A["source"])) if "source" in A.columns else dict.fromkeys(A["base"], "own")
    strict = [s for s in twelve if src.get(cb.base(s)) in STRICT and s in set(d["symbol"])]
    D12 = ceiling.derive(ceiling.panel(twelve))
    idx, cols = D12["lr"].index, list(D12["lr"].columns)
    if not strict:
        return pd.DataFrame(columns=["bet", "horizon", "feature", "ic", "t", "days", "months_same_sign", "ic_mde"]), pd.DataFrame(columns=["bet", "horizon", "feature", "day", "ic"]), strict
    W = frames_wiki(d, strict, idx, cols)
    sc12, daily12 = ceiling.ic_screen(D12, {TWELVE_ROW: cx.restrict(W["F"], strict)[DEV]}, set())
    return sc12, daily12, strict


def describe_names(fr: dict, L: dict, old: list[str]) -> pd.DataFrame:
    F, s, names, extra = fr["F"], fr["s"], fr["names"], fr["extra"]
    first_day = fr["daily"]["views"].apply(lambda c: c.first_valid_index())
    rows = []
    for c in names + extra:
        if c not in F[DEV].columns:
            continue
        src = F if c in names else fr["Fx"]
        dv, lv, z = src[DEV][s][c], src[LVL][s][c], src["zero"][s][c]
        has = dv.notna()
        rows.append({"symbol": c, "article": L["article"].get(c, ""), "source": L["source"].get(c, ""), "role": "registered" if c in names else "proxy (described)",
                     "first_day": str(pd.Timestamp(first_day[c]).date()) if c in first_day.index and pd.notna(first_day[c]) else None, "old": c in old,
                     "cells": int(has.sum()), "cover": float(has.mean()), "dev_sd": dv.std(), "lvl_mean": lv.mean(), "share_zero_views": float(z[has].mean()) if has.any() else np.nan})
    return pd.DataFrame(rows)


def _head(validity: dict, taker_bps, maker_bps, fee_source) -> list[str]:
    return [f"# R72 — the attention screen: Wikipedia pageviews' deviation on the screener's F1+F2 members with a strict article (`ft2 ceiling --target pairs --family wiki --universe members`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
            f"\n**Folds read:** {'+'.join(folds.EXPLORATION)} (embargoed) on the members' cells (a name's cells while a member of the bar's block); every source cut at "
            f"{ceiling.END:%Y-%m-%d}. The universe: {validity['inputs']['n_names']} names from `{validity['inputs']['members']['path']}` (md5 {validity['inputs']['members']['md5']}) × "
            f"`{validity['inputs']['articles']['path']}` (md5 {validity['inputs']['articles']['md5']}, strict articles). The quantity: `{DEV}` — log(1 + the day's views) against its trailing "
            f"30 days in sd units, read at day + {validity['stamp']['known_at_h']} h, carried ≤ 24 h. Fees (input): taker {taker_bps} bps, maker {maker_bps} bps — {fee_source}.\n",
            f"\n## Validity — read first: **{validity.get('status', 'FAIL')}**\n", "```\n", json.dumps(validity, indent=1, default=str), "\n```\n"]


def _void(validity: dict, out_md: Path, out_dir: Path, taker_bps, maker_bps, fee_source):
    validity["status"] = "FAIL"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))
    out_md.write_text("".join(_head(validity, taker_bps, maker_bps, fee_source) + ["\n**The read is VOID: no row of the registered feature was computed on the members.**\n"]))
    print(f"validity FAIL — the read is void; wrote {out_md}", flush=True)
    raise SystemExit(2)
