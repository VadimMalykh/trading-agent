"""R100 (docs/PLAN.md §8, registered 2026-11-19): the frozen trees on the NEXT SIXTY — `ft2 next60 a`, then `ft2 next60 b`.

The registration is the specification; this docstring only maps it to the code. Written after the registration's commit, tested on
planted bars only.

cells      `SEGS`: the frozen lists `ft2/screen_next60_{pre,f34}.csv` and `screen_next60_f5_coins.csv` as the MEMBERS of `allgbm.build`
           (so every input is a rank among the bar's next-sixty cells and the label is against their mean) — THE SAMPLE; `f12` apart.
(A)        `run_a`: validity (0)–(2) first, then the FILE's forecast on each segment, `pooled_ic` over the three together (R87's
           statistic, HAC by day), `verdict100` (R89's form, the three segments > 0). The ledger row (R100, N60) once the number exists.
(B)        `run_b`: the twelve `FORMS` (hold H days × tail divisor × forecast raw / 24 h-averaged) by `allbook.positions` with the
           keywords `tenth`, `min_n`, `every`; R91's taker pricing and hedge; `form_row` (G = hedged price result + funding per
           position, before fees, costs and the hedge's 4 bps; the net); `choose` is the registration's Choice, word for word.
described  everything else in read.md / the csv files; decides nothing.

Two readings of the text, said in the Result line: (1) the 24 h-averaged forecast exists for a name only at a 00:00 bar where the name
is IN THE LIST (a cell); a name that left the list at that bar has none ("it left the list or the cover"). (2) Described (e) "the
forms on the top fifth" is read as the tail a FIFTH (k = ⌊n / 5⌋), six forms.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import allbook as ab, allgbm as ag, audit, folds, universe
from . import backtest as bt
from .ceiling import MDE_K, _ic_pooled, _ic_xs, day_lags, hac

OUT = Path("output/next60/r100")
REG, FOLD = "R100", "N60"
HERE = Path(__file__).parent
LISTS = {"pre": HERE / "screen_next60_pre.csv", "f12": HERE / "screen_next60_f12.csv", "f34": HERE / "screen_next60_f34.csv", "f5": HERE / "screen_next60_f5_coins.csv"}
LISTS_MD5 = {"screen_next60_pre.csv": "faa0653ad11a1fd3c7ad46136b370fe2", "screen_next60_f12.csv": "4837edbeb23039da9dc56be6bd8d92ac", "screen_next60_f34.csv": "a28536c06852607ecf9a3d4715826b3d",
             "screen_next60_f5.csv": "c01018ca037656edd735306515f13c40", "screen_next60_f5_coins.csv": "066099d387ec21a4690d1fbe1ee2b232"}
TABLES_MD5 = {"data/candles_5m_archive.parquet": "c94905d63ee3d9e95190377ba9f9d706", "data/funding_archive.parquet": "582259de4abf172ac6237b9f57f59799",
              "data/metrics.parquet": "6734b2553b443065714864fcbcc19fdc", "data/perp_mix_1h.parquet": "cec46ff4a86b62357e47cfa49121d965",
              "data/cost_daily_wide.parquet": "b4d2224a0e25a5039ccf87a798352587"}
SAMPLE, APART = ("pre", "f34", "f5"), "f12"
EARLY = ("pre",)                                             # the EARLY half; the LATE half is F3+F4 + F5
SCORABLE = {"pre": 656_386, "f34": 693_589, "f5": 327_533, "f12": 696_005}
LABEL_END = {"pre": pd.Timestamp("2023-05-01", tz="UTC"), "f34": pd.Timestamp("2026-01-01", tz="UTC"), "f5": pd.Timestamp("2026-09-15", tz="UTC"), "f12": folds.bounds("F2")[1]}
ABSENT = {"pre": ("hl_gap24_dev",), "f34": (), "f5": (), "f12": None}       # the Features line: the only input without a cell, on PRE; f12 is described (not checked)
ORIGIN = pd.Timestamp("2021-12-10", tz="UTC")
HOURLY = ("cbprem_dev", "cbprem_chg_1d", "krprem_dev", "spot_tb24_dev", "spot_sr24_dev", "mix_cnt24_dev", "mix_size24_dev", "hl_gap24_dev")
BLOCK = pd.Timedelta(days=30)
FORMS = [(h, d, k) for h in (1, 2, 3) for d in (10, 20) for k in ("raw", "avg")]       # (H days, the tail's divisor, the forecast)
BASE = (1, 10, "raw")
CW3_FORM, CW3_RATIO = (3, 10, "raw"), 1.5
AVG_BARS, AVG_MIN = 24, 12
LEFT = {5: "left_fifth", 10: "left_tenth", 20: "left_twentieth"}
CLAUSES = ("no_forecast", "funding", "cap", "span_end")


def seg_args(seg: str) -> dict:
    """`allgbm.build`'s arguments for a segment — the cover's own (`next60data.cover`)."""
    return {"pre": dict(members=LISTS["pre"], fold_names=(), end=universe.PRE_END, start=ag.PRE_START, grids_start=ag.PRE_GRIDS, span=ag.PRE_SPAN),
            "f12": dict(members=LISTS["f12"], fold_names=("F1", "F2"), end=None, start=None, grids_start=None, span=None),
            "f34": dict(members=LISTS["f34"], fold_names=ag.CONF_FOLDS, end=folds.bounds("F4")[1], start=ag.CONF_START, grids_start=ag.CONF_GRIDS, span=None),
            "f5": dict(members=LISTS["f5"], fold_names=("F5",), end=folds.bounds("F5")[1], start=ag.F5_START, grids_start=ag.F5_GRIDS, span=None)}[seg]


def member_lists() -> list[Path]:
    return [universe.PRE_MEMBERS_CSV, universe.MEMBERS_CSV, universe.F34_MEMBERS_CSV, universe.F5_MEMBERS_CSV]


def _md5(p: Path | str) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def _reads() -> pd.DataFrame:
    return pd.read_csv(bt.READS) if bt.READS.exists() else pd.DataFrame(columns=["registration", "fold"])


def _guard100(stage: str = "a") -> None:
    """Validity (0): the block exists without DRAFT in its heading; (A) once — no (R100, N60) row; (B) once, after (A)'s row and file."""
    m = re.search(rf"^### {REG} .*$", bt.PLAN.read_text(), flags=re.M) if bt.PLAN.exists() else None
    if not m:
        raise SystemExit(f"no '### {REG} ' block in {bt.PLAN}: write the registration before the read")
    if "DRAFT" in m.group(0):
        raise SystemExit(f"{REG}'s heading says DRAFT: no read before Vadim's word on its text")
    r = _reads()
    has = bool(((r["registration"] == REG) & (r["fold"] == FOLD)).any())
    if stage == "a":
        if has:
            raise SystemExit(f"{REG} has already read {FOLD} ({bt.READS}): the next sixty are read once")
    else:
        if not has or not (OUT / "a.json").exists():
            raise SystemExit(f"{REG} (B) is read after (A): no ({REG}, {FOLD}) row or no {OUT / 'a.json'}")
        if (OUT / "b.json").exists():
            raise SystemExit(f"{REG} (B) has been read ({OUT / 'b.json'}): once")


# ---- (A) -----------------------------------------------------------------------------------------------------------------------------
def member_cells(lists: list, names: list[str], grid: pd.DatetimeIndex) -> np.ndarray:
    """bar × name: True where the name is a member, by any of `lists`, of the block the bar falls in (a list reaches from its first
    block to 30 days after its last)."""
    out = np.zeros((len(grid), len(names)), dtype=bool)
    for p in lists:
        m = pd.read_csv(p)
        m["block"] = pd.to_datetime(m["block"], utc=True)
        inside = np.asarray((grid >= m["block"].min()) & (grid < m["block"].max() + BLOCK))
        out |= audit.member_mask(m, np.asarray(names), grid) & inside[:, None]
    return out


def pooled_ic(parts: list[tuple[np.ndarray, np.ndarray, np.ndarray]]) -> dict:
    """R87's statistic over several builds together: per build the label re-centred on the cells that have a forecast at the bar,
    the cells pooled, each day's share of the whole-sample correlation, HAC by day. A part: (f, z, the bar's day number on ONE calendar)."""
    F, Z, D = [], [], []
    for f, z, day in parts:
        zr = ag.centre(z, ~np.isnan(f) & ~np.isnan(z))
        ok = ~np.isnan(zr)
        F.append(f[ok]), Z.append(zr[ok]), D.append(np.repeat(day[:, None], f.shape[1], 1)[ok])
    F, Z, D = np.concatenate(F), np.concatenate(Z), np.concatenate(D)
    if len(F) < 200:
        return {"cells": int(len(F)), "days": 0, "ic": np.nan, "se": np.nan, "t": np.nan}
    m, se, n = hac(_ic_pooled(F, Z, D, min_cells=1), day_lags(ag.HOLD))
    return {"cells": int(len(F)), "days": n, "ic": m, "se": se, "t": m / se if se else np.nan}


def verdict100(ic: float, se: float, t: float, segs: list[float]) -> str:
    """(A)'s gate: R89's one-sided form with the IC > 0 in EACH of the three segments."""
    if all(np.isfinite(x) for x in (ic, t, *segs)) and t >= ag.T_ONE_SIDED and ic >= ag.BAR_MAKER and all(x > 0 for x in segs):
        return "CONFIRMED AT THE TAKER BAR" if ic >= ag.BAR_TAKER else "CONFIRMED"
    return "NOT CONFIRMED — CLOSED" if np.isfinite(ic) and np.isfinite(se) and ic + 1.96 * se < ag.BAR_MAKER else "NOT CONFIRMED"


def build_seg(seg: str, sources: dict | None = None, expect: bool = True, lists: list | None = None) -> dict:
    """One segment's build with its validity entries (2) and what the scoring needs; the big frames are dropped."""
    sources = ag.SOURCES if sources is None else sources
    a = seg_args(seg)
    B = ag.build(a["members"], a["fold_names"], sources, a["end"], a["start"], a["grids_start"], a["span"])
    names_ = [k for _, k in B["src_of"]]
    cols = [i for i, k in enumerate(names_) if k not in ag.DROP88]
    used = [names_[i] for i in cols]
    cov = B["cover"].set_index("feature")
    absent = tuple(k for k in used if int(cov.loc[k, "cells"]) == 0)
    grid, names, sc = B["grid"], B["names"], B["scorable"]
    mc = member_cells(member_lists() if lists is None else lists, names, grid)
    late = int((~np.isnan(B["z"]) & B["cell"] & np.asarray(B["t_end"] > LABEL_END[seg])[:, None]).sum())
    v = {"names": len(names), "rows": int(len(grid)), "first": str(grid[0]), "last": str(grid[-1]), "features": used, "same_names_as_r89": used == ag.R89_FEATURES if expect else None,
         "scorable_cells": int(sc.sum()), "scorable_as_the_cover": int(sc.sum()) == SCORABLE[seg] if expect else None, "scored_member_cells": int((sc & mc).sum()),
         "max_abs_d_causal": ag._causal(B, sources), "labels_ending_after_the_segment": late, "features_without_a_cell": list(absent),
         "absent_as_registered": absent == ABSENT[seg] if expect and ABSENT[seg] is not None else None}
    v["ok"] = bool(v["scored_member_cells"] == 0 and v["max_abs_d_causal"] in (None, 0.0) and late == 0
                   and all(v[k] in (None, True) for k in ("same_names_as_r89", "scorable_as_the_cover", "absent_as_registered")))
    hourly = [names_.index(k) for k in HOURLY if k in names_]
    has_hourly = (~np.isnan(B["X"][:, :, hourly])).any(-1) if hourly else np.zeros(sc.shape, dtype=bool)
    ever = _ever_members(lists)
    never = np.array([c not in ever for c in names])
    out = {"seg": seg, "v": v, "grid": grid, "names": names, "scorable": sc, "Xs": B["X"][sc][:, cols], "z": B["z"], "y": B["y"],
           "day": (grid.floor("D") - ORIGIN).days.to_numpy(), "has_hourly": has_hourly, "never": never, "cover": B["cover"]}
    del B
    return out


def _ever_members(lists: list | None = None) -> set:
    s: set = set()
    for p in (member_lists() if lists is None else lists):
        s |= set(pd.read_csv(p)["symbol"].astype(str))
    return s


def score(S: dict, model) -> np.ndarray:
    f = np.full(S["scorable"].shape, np.nan)
    f[S["scorable"]] = model.predict(S["Xs"])
    return f


def _seg_rows(S: dict, f: np.ndarray) -> tuple[list[dict], pd.DataFrame]:
    """Described (b) for one segment: the per-bar rank IC, the tenths, the never-members against the rest, with / without the hourly sources, by month."""
    from .horizon import _tenths
    grid, z, y, seg = S["grid"], S["z"], S["y"], S["seg"]
    day = S["day"] - S["day"].min()
    zr = ag.centre(z, ~np.isnan(f) & ~np.isnan(z))
    m_xs, se_xs, _ = hac(_ic_xs(pd.DataFrame(f), pd.DataFrame(zr), day), day_lags(ag.HOLD))
    tenths = float(np.nanmean(_tenths(f, np.where(~np.isnan(f), y, np.nan)))) if len(grid) % ag.PER_DAY == 0 else np.nan
    nv = np.broadcast_to(S["never"][None, :], f.shape)
    rows = [{"row": f"{seg}: all cells", **ag.ic_row(f, z, day), "ic_rank_per_bar": m_xs, "t_rank": m_xs / se_xs if se_xs else np.nan, "tenths_bps_a_leg": tenths},
            {"row": f"{seg}: names never a member ({int(S['never'].sum())})", **ag.ic_cells(f, z, day, nv)}, {"row": f"{seg}: names a member in another block", **ag.ic_cells(f, z, day, ~nv)},
            {"row": f"{seg}: cells with an hourly source", **ag.ic_cells(f, z, day, S["has_hourly"])}, {"row": f"{seg}: cells without", **ag.ic_cells(f, z, day, ~S["has_hourly"])}]
    month = pd.Series(grid.strftime("%Y-%m"))
    by_month = pd.DataFrame([{"seg": seg, "month": mth, **ag.ic_row(f, z, day, (month == mth).to_numpy())} for mth in sorted(month.unique())])
    return rows, by_month


def run_a(sources: dict | None = None, model_file: Path | str | None = None, expect: bool = True, lists: list | None = None) -> dict:
    import lightgbm as lgb
    _guard100("a")
    OUT.mkdir(parents=True, exist_ok=True)
    model_file = Path(model_file or ag.MODEL_FILE)
    lists_md5 = {Path(p).name: _md5(p) for p in (*LISTS.values(), HERE / "screen_next60_f5.csv")} if expect else {}
    tables_md5 = {p: _md5(p) for p in TABLES_MD5} if expect else {}
    model_md5 = _md5(model_file)
    model = lgb.Booster(model_file=str(model_file))                        # the FILE is the model: nothing is fitted
    S = {}
    for seg in (*SAMPLE, APART):
        print(f"{seg}: the cells…", flush=True)
        S[seg] = build_seg(seg, sources, expect, lists)
        S[seg]["cover"].to_csv(OUT / f"cover_{seg}.csv", index=False)
    v = {"registration": REG, "lists_md5": lists_md5, "lists_as_registered": lists_md5 == LISTS_MD5 if expect else None, "model_md5": model_md5,
         "model_as_registered": model_md5 == ag.MODEL_MD5 if expect else None, "model_features": int(model.num_feature()), "tables_md5": tables_md5,
         "tables_as_the_data_line_left_them": tables_md5 == TABLES_MD5 if expect else None, "segments": {k: {a: b for a, b in s["v"].items() if a != "features"} for k, s in S.items()},
         "bars": {"taker": ag.BAR_TAKER, "maker": ag.BAR_MAKER, "t_one_sided": ag.T_ONE_SIDED}}
    v["status"] = "PASS" if (all(s["v"]["ok"] for s in S.values()) and all(v["model_features"] == len(s["v"]["features"]) for s in S.values())
                             and all(v[k] in (None, True) for k in ("lists_as_registered", "model_as_registered", "tables_as_the_data_line_left_them"))) else "FAIL"
    (OUT / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {REG} — the frozen trees' FILE on the NEXT SIXTY (the screener's ranks 61–120): (A) the ranking, (B) twelve declared forms of a slow short book (`ft2 next60 a | b`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · bars: maker {ag.BAR_MAKER}, taker {ag.BAR_TAKER}, one-sided t ≥ {ag.T_ONE_SIDED}\n",
            f"\n## Validity (0)–(2) — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (OUT / "read_a.md").write_text("\n".join(head + ["\n**The read is VOID: no forecast and no IC was computed.**\n"]))
        print(f"validity FAIL — the read is void; wrote {OUT}/", flush=True)
        raise SystemExit(2)

    F = {seg: score(s, model) for seg, s in S.items()}
    r = pooled_ic([(F[k], S[k]["z"], S[k]["day"]) for k in SAMPLE])
    per = {k: ag.ic_row(F[k], S[k]["z"], S[k]["day"] - S[k]["day"].min()) for k in (*SAMPLE, APART)}
    gate = {**r, "mde": MDE_K * r["se"] if np.isfinite(r["se"]) else np.nan, **{f"ic_{k}": per[k]["ic"] for k in SAMPLE},
            "verdict": verdict100(r["ic"], r["se"], r["t"], [per[k]["ic"] for k in SAMPLE])}
    for seg, s in S.items():
        o = pd.DataFrame({"t": np.repeat(s["grid"].to_numpy(), len(s["names"])), "symbol": np.tile(np.asarray(s["names"]), len(s["grid"])), "f": F[seg].ravel(), "z": s["z"].ravel()})
        o[~np.isnan(o["f"])].to_parquet(OUT / f"forecast_{seg}.parquet", index=False)
    a = {"verdict": gate["verdict"], **{k: (float(x) if isinstance(x, (float, np.floating)) else x) for k, x in gate.items() if k != "verdict"},
         "apart_f12": per[APART], "forecast_md5": {seg: _md5(OUT / f"forecast_{seg}.parquet") for seg in S}}
    (OUT / "a.json").write_text(json.dumps(a, indent=1, default=str))
    bt.READS.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"read_at": [f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC"], "registration": REG, "fold": FOLD, "strategy": "next60 (A) the frozen trees, (B) twelve forms",
                  "params": json.dumps({"model_md5": model_md5, "forms": len(FORMS)})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    print(f"{REG} (A): {gate['verdict']} — IC {gate['ic']:+.4f} (se {gate['se']:.4f}, t {gate['t']:+.2f}; " + ", ".join(f"{k} {per[k]['ic']:+.4f}" for k in SAMPLE) + ")", flush=True)

    show = lambda d, k=4: d.round(k).to_markdown(index=False)                    # noqa: E731
    try:                                                                          # the described rows decide nothing: a defect in them must not cost (B) its run
        rows, months = [], []
        for seg, s in S.items():
            rr, bm = _seg_rows(s, F[seg])
            rows += rr
            months.append(bm)
        tab, by_month = pd.DataFrame(rows), pd.concat(months, ignore_index=True)
        tab.to_csv(OUT / "a_rows.csv", index=False)
        by_month.to_csv(OUT / "a_by_month.csv", index=False)
    except Exception:                                                             # noqa: BLE001
        import traceback
        traceback.print_exc()
        tab = by_month = pd.DataFrame({"described": ["FAILED — see the log; (A)'s number above stands"]})
    md = head + [f"\n## (A) the ranking on the next sixty — **{gate['verdict']}**: pooled IC {gate['ic']:+.4f} (se {gate['se']:.4f}, t {gate['t']:+.2f}, MDE {gate['mde']:.4f}) on {int(gate['cells']):,} cells, "
                 f"{int(gate['days'])} days; " + ", ".join(f"{k} {per[k]['ic']:+.4f}" for k in SAMPLE) + f"; apart, F1+F2's next sixty (the fit months) {per[APART]['ic']:+.4f} (t {per[APART]['t']:+.2f})\n",
                 "\n### Described (decides nothing): by segment, the names never a member, the hourly sources\n", show(tab), "\n", "\n### By month\n", show(by_month), "\n"]
    (OUT / "read_a.md").write_text("\n".join(md))
    print(f"wrote {OUT}/", flush=True)
    return a


# ---- (B) -----------------------------------------------------------------------------------------------------------------------------
def averaged(fc: pd.DataFrame, mem: pd.DataFrame) -> pd.DataFrame:
    """The 24 h-averaged forecast at the 00:00 bars: the mean of the name's hourly forecasts over the 24 bars ending at the bar, at least
    AVG_MIN present — for the names in the list (`mem`: block, symbol) at the bar. Long (t, symbol, f)."""
    w = fc.assign(symbol=fc["symbol"].astype(str)).pivot(index="t", columns="symbol", values="f").sort_index()
    w = w.reindex(pd.date_range(w.index[0], w.index[-1], freq="h"))
    a = w.rolling(AVG_BARS, min_periods=AVG_MIN).mean()
    a = a[a.index == a.index.floor("D")]
    a = a.where(audit.member_mask(mem, np.asarray(a.columns), a.index))
    o = a.stack().rename("f").reset_index()
    o.columns = ["t", "symbol", "f"]
    return o


def form_fc(fc: pd.DataFrame, mem: pd.DataFrame, kind: str) -> pd.DataFrame:
    return ab.midnight(fc)[["t", "symbol", "f"]] if kind == "raw" else averaged(fc, mem)


def form_positions(fcf: pd.DataFrame, fund: pd.DataFrame, h: int, div: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A form's rule on its 00:00 forecast table: `allbook.positions` with the tail the band, n ≥ max(10, div), the band clause at whole multiples of H days."""
    return ab.positions(fcf, fund, band=div, left=LEFT[div], tenth=div, min_n=max(ab.MIN_N, div), every=h * ab.HOLD)


def reopen(fcf: pd.DataFrame, fund: pd.DataFrame) -> pd.DataFrame:
    """Described (e): the literal close-and-reopen book of the base — every 00:00 tenth sold for exactly one day, the entry floor R91's."""
    d = fcf.dropna().assign(symbol=lambda x: x["symbol"].astype(str)).sort_values(["t", "f", "symbol"], kind="mergesort")
    F = ab.day_funding(fund)
    last, rows = d["t"].max(), []
    for t, g in d.groupby("t", sort=True):
        n = len(g)
        if n < ab.MIN_N or t == last:
            continue
        for s, f in zip(g["symbol"].tolist()[:n // ab.TENTH], g["f"].tolist()[:n // ab.TENTH]):
            fr = ab.last_funding(F, s, t)
            if np.isfinite(fr) and fr >= ab.FUND_ENTRY:
                rows.append({"t": t, "symbol": s, "side": -1, "size": 1.0, "signal": f, "why": "one_day", "hold": ab.HOLD, "fold": "", "block": 0})
    return pd.DataFrame(rows, columns=["t", "symbol", "side", "size", "signal", "why", "hold", "fold", "block"]).assign(accepted=True, skip="")


def check_form(dec: pd.DataFrame, fills: pd.DataFrame, div: int) -> dict:
    """Validity (3) of one form on its fills (every segment together)."""
    t = pd.DatetimeIndex(dec["t"])
    priced = fills["net_bps"].notna()
    v = {"positions": int(len(dec)), "decisions_at_midnight": bool((t == t.floor("D")).all()), "priced_share": float(priced.mean()) if len(fills) else 0.0,
         "overlapping_positions": int(sum(ab.overlaps(g) for _, g in fills[priced].groupby("seg"))), "entry_after_decision": bool((fills.loc[priced, "entry_t"] > fills.loc[priced, "t"]).all()),
         "exits_unexplained": int((~dec["why"].isin([*CLAUSES, LEFT[div]])).sum()), "holds_whole_days": bool((dec["hold"] % ab.HOLD == 0).all())}
    v["ok"] = bool(v["decisions_at_midnight"] and v["priced_share"] >= 0.95 and v["overlapping_positions"] == 0 and v["entry_after_decision"] and v["exits_unexplained"] == 0 and v["holds_whole_days"])
    return v


def _stat(x: np.ndarray, f: pd.DataFrame, days: pd.DatetimeIndex) -> tuple[float, float]:
    if not len(f):
        return np.nan, np.nan
    s = bt.trade_stats(np.asarray(x, float), f["size"].to_numpy(float), pd.DatetimeIndex(f["t"]).floor("D"), days, day_lags(ab.CAP_BARS))
    return s["mean"], s["se"]


def form_row(fills: pd.DataFrame, days: dict[str, pd.DatetimeIndex], early: tuple[str, ...] = EARLY) -> dict:
    """A form's numbers on priced fills carrying `seg`: G = hedged price result + funding per position (before fees, spread, impact and
    the hedge's 4 bps), the net = hedged net − 4; each with the day-clustered HAC se (R91's lags) on the sample and on its two halves."""
    f = fills.dropna(subset=["net_bps"])
    segs = [s for s in days if len(days[s])]
    cat = lambda ks: pd.DatetimeIndex(np.concatenate([days[k].to_numpy() for k in ks]), tz="UTC") if ks else pd.DatetimeIndex([], tz="UTC")   # noqa: E731
    all_days = cat(segs)
    G, net = (f["hedged_bps"] + f["funding_bps"]).to_numpy(), (f["hedged_net_bps"] - ab.HEDGE_BPS).to_numpy()
    out = {"positions": int(len(f)), "a_day": len(f) / max(len(all_days), 1), "crossings_a_day": 2 * len(f) / max(len(all_days), 1), "hold_days": float(f["hold"].mean() / ab.HOLD) if len(f) else np.nan}
    e = f["seg"].isin(early).to_numpy()
    for k, x in (("G", G), ("net", net)):
        out[k], out[f"{k}_se"] = _stat(x, f, all_days)
        out[f"{k}_early"], out[f"{k}_early_se"] = _stat(x[e], f[e], cat([s for s in segs if s in early]))
        out[f"{k}_late"], out[f"{k}_late_se"] = _stat(x[~e], f[~e], cat([s for s in segs if s not in early]))
    out |= {"fee": float(f["fee_bps"].mean()) if len(f) else np.nan, "other_cost": float(f["other_cost_bps"].mean()) if len(f) else np.nan,
            "funding": float(f["funding_bps"].mean()) if len(f) else np.nan, "net_unhedged": float(f["net_bps"].mean()) if len(f) else np.nan,
            "net_other_cost_x1.5": float((net - 0.5 * f["other_cost_bps"].to_numpy()).mean()) if len(f) else np.nan}
    return out


def choose(tab: pd.DataFrame, a_confirmed: bool) -> dict:
    """The registration's Choice on the forms' table (columns H, tail, fc, G, G_se, G_early, G_late): among the eleven forms other than
    the base, the candidates have G > 0 in both halves and G − G(base) ≥ their own se of G; the winner the largest G, ties to the shorter
    hold, then the tenth, then raw. No winner if there is no candidate, or if (A) is NOT CONFIRMED whatever the grid shows."""
    is_base = (tab["H"] == BASE[0]) & (tab["tail"] == BASE[1]) & (tab["fc"] == BASE[2])
    gb = float(tab.loc[is_base, "G"].iloc[0])
    o = tab[~is_base]
    c = o[(o["G_early"] > 0) & (o["G_late"] > 0) & (o["G"] - gb >= o["G_se"])].assign(_raw=lambda x: (x["fc"] != "raw").astype(int)).sort_values(["G", "H", "tail", "_raw"], ascending=[False, True, True, True], kind="mergesort")
    cands = [(int(r.H), int(r.tail), r.fc) for r in c.itertuples()]
    c3 = tab[(tab["H"] == CW3_FORM[0]) & (tab["tail"] == CW3_FORM[1]) & (tab["fc"] == CW3_FORM[2])]
    g3 = float(c3["G"].iloc[0]) if len(c3) else np.nan
    out = {"base_G": gb, "candidates": cands, "cw3_G": g3, "cw3_opened": bool(np.isfinite(g3) and g3 >= CW3_RATIO * gb)}
    if not a_confirmed:
        return {**out, "winner": None, "why": "(A) is NOT CONFIRMED: no winner whatever the grid shows"}
    if not cands:
        return {**out, "winner": None, "why": "no candidate: R99's form stands as the only slow form"}
    return {**out, "winner": cands[0], "why": "the candidate with the largest G"}


def _book(S: dict, fcf: pd.DataFrame, h: int, div: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dec, skipped = form_positions(fcf, S["fund"], h, div)
    return dec, skipped, _price(S, dec)


def _price(S: dict, dec: pd.DataFrame) -> pd.DataFrame:
    fills = bt.price(dec, S["M"], S["C"], "taker", ab.TAKER_BPS, ab.MAKER_BPS).merge(dec[["why", "hold", "signal"]], left_on="id", right_index=True, how="left")
    return fills.assign(seg=S["seg"])


def load_seg(seg: str) -> dict:
    """What (B) needs of a segment: the saved forecast, the list, the market over the forecast's days, the costs, the funding rows."""
    from . import data
    fc = pd.read_parquet(OUT / f"forecast_{seg}.parquet", columns=["t", "symbol", "f"])
    fc["t"] = pd.to_datetime(fc["t"], utc=True)
    end = seg_args(seg)["end"] or folds.bounds("F2")[1]
    names = sorted(fc["symbol"].astype(str).unique())
    M = bt.market(names, end, fc["t"].min().floor("D"))
    fund = data.load("funding_archive", columns=["symbol", "ts", "rate", "interval_h"], symbols=names)
    mem = pd.read_csv(LISTS[seg])
    mem["block"] = pd.to_datetime(mem["block"], utc=True)
    return {"seg": seg, "fc": fc, "mem": mem, "M": M, "C": bt.load_costs(M.index, M.columns, end, 1.0, close=M.close), "fund": fund[pd.to_datetime(fund["ts"], utc=True) < end],
            "days": pd.date_range(fc["t"].min().floor("D"), fc["t"].max().floor("D"), freq="D")}


def run_b() -> dict:
    _guard100("b")
    a = json.loads((OUT / "a.json").read_text())
    md5 = {seg: _md5(OUT / f"forecast_{seg}.parquet") for seg in (*SAMPLE, APART)}
    if md5 != a["forecast_md5"]:
        print("validity FAIL — a saved forecast is not (A)'s; (B) is void", flush=True)
        raise SystemExit(2)
    key = lambda h, d, k: f"h{h}_d{d}_{k}"                                        # noqa: E731
    fills, decs, val, extra, days, counts = {}, {}, {}, {}, {}, {}
    base99 = True
    for seg in (*SAMPLE, APART):
        print(f"{seg}: the market, the costs, the forms…", flush=True)
        S = load_seg(seg)
        days[seg] = S["days"]
        tabs = {k: form_fc(S["fc"], S["mem"], k) for k in ("raw", "avg")}
        for h, d, k in [*FORMS, *[(h, 5, k) for h in (1, 2, 3) for k in ("raw", "avg")]]:
            dec, skipped, f = _book(S, tabs[k], h, d)
            fills.setdefault(key(h, d, k), []).append(f)
            decs.setdefault(key(h, d, k), []).append(dec.assign(seg=seg))
            counts.setdefault(key(h, d, k), {})[seg] = {"exits": dec["why"].value_counts().to_dict(), "entries_skipped": skipped["why"].value_counts().to_dict()}
            if (h, d, k) == BASE:
                d99, _ = ab.positions99(S["fc"], S["fund"])
                base99 &= bool(len(d99) == len(dec) and (d99[["t", "symbol", "hold", "why"]].reset_index(drop=True) == dec[["t", "symbol", "hold", "why"]].reset_index(drop=True)).all().all())
        extra.setdefault("reopen", []).append(_price(S, reopen(tabs["raw"], S["fund"])))
        del S
    fills = {k: pd.concat(v, ignore_index=True) for k, v in fills.items()}
    decs = {k: pd.concat(v, ignore_index=True) for k, v in decs.items()}
    in_sample = lambda f: f[f["seg"].isin(SAMPLE)]                                # noqa: E731
    for h, d, k in FORMS:
        val[key(h, d, k)] = check_form(in_sample(decs[key(h, d, k)]), in_sample(fills[key(h, d, k)]), d)
    v = {"registration": REG, "forecast_md5": md5, "base_equals_positions99": base99, "forms": val}
    v["status"] = "PASS" if base99 and all(x["ok"] for x in val.values()) else "FAIL"
    (OUT / "validity_b.json").write_text(json.dumps(v, indent=1, default=str))
    if v["status"] != "PASS":
        (OUT / "read_b.md").write_text(f"# {REG} (B) — **VOID**: validity (3) failed (`validity_b.json`); (A) stands\n")
        print(f"validity FAIL — (B) is void; wrote {OUT}/", flush=True)
        raise SystemExit(2)

    sd = {s: days[s] for s in SAMPLE}
    rows, rows12, rows5, by_seg, by_month = [], [], [], [], []
    for h, d, k in [*FORMS, *[(h, 5, k) for h in (1, 2, 3) for k in ("raw", "avg")]]:
        f = fills[key(h, d, k)]
        f.to_parquet(OUT / f"fills_{key(h, d, k)}.parquet", index=False)
        head = {"H": h, "tail": d, "fc": k}
        (rows if d != 5 else rows5).append({**head, **form_row(in_sample(f), sd)})
        if d != 5:
            rows12.append({**head, **form_row(f[f["seg"] == APART], {APART: days[APART]}, early=())})
            for seg in SAMPLE:
                r = form_row(f[f["seg"] == seg], {seg: days[seg]}, early=())
                by_seg.append({**head, "seg": seg, **{c: r[c] for c in ("positions", "a_day", "hold_days", "G", "G_se", "net", "net_se", "fee", "other_cost", "funding")}})
            p = in_sample(f).dropna(subset=["net_bps"])
            g = p.assign(month=pd.DatetimeIndex(p["t"]).strftime("%Y-%m"), G=p["hedged_bps"] + p["funding_bps"], net=p["hedged_net_bps"] - ab.HEDGE_BPS).groupby("month").agg(positions=("G", "size"), G=("G", "mean"), net=("net", "mean")).reset_index()
            by_month.append(g.assign(**head))
    tab, tab12, tab5 = pd.DataFrame(rows), pd.DataFrame(rows12), pd.DataFrame(rows5)
    ch = choose(tab, str(a["verdict"]).startswith("CONFIRMED"))
    ro = pd.concat(extra["reopen"], ignore_index=True)
    ro.to_parquet(OUT / "fills_reopen.parquet", index=False)
    described = {"the literal close-and-reopen book of the base": form_row(in_sample(ro), sd)}
    p97 = ab.OUT / ab.NAME97 / "fills.parquet"
    if p97.exists():
        f97 = pd.read_parquet(p97).dropna(subset=["net_bps"])
        described["R97 (B): R91's hourly rule on the MEMBERS before F1 (hedged net − 4, mean a trade)"] = {"positions": int(len(f97)), "net": float((f97["hedged_net_bps"] - ab.HEDGE_BPS).mean()),
                                                                                                             "G": float((f97["hedged_bps"] + f97["funding_bps"]).mean())}
    b = {"a_verdict": a["verdict"], "choice": ch, "validity": v["status"], "described": described, "counts": counts}
    tab.to_csv(OUT / "forms.csv", index=False)
    tab12.to_csv(OUT / "forms_f12_apart.csv", index=False)
    tab5.to_csv(OUT / "forms_fifth_described.csv", index=False)
    pd.DataFrame(by_seg).to_csv(OUT / "forms_by_segment.csv", index=False)
    pd.concat(by_month, ignore_index=True).to_csv(OUT / "forms_by_month.csv", index=False)
    (OUT / "b.json").write_text(json.dumps(b, indent=1, default=str))
    show = lambda d_, k_=2: d_.round(k_).to_markdown(index=False)                # noqa: E731
    w = ch["winner"]
    md = [f"# {REG} (B) — the twelve declared forms on the next sixty (DECLARED DEVELOPMENT, no gate)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · (A): {a['verdict']} · validity (3): {v['status']} · the base equals `positions99`: {base99}\n",
          "\nWords: *G*: what a position earns against the basket of the other next-sixty coins plus its funding, bps (= USDT at 10,000), BEFORE fees, spread, impact and the hedge's 4 bps — "
          "the money it has to pay its two crossings with. *net*: after all of them. *early* = PRE, *late* = F3+F4 + F5. se: day-clustered HAC.\n",
          f"\n## The choice — **{'WINNER: hold ' + str(w[0]) + ' d, the ' + LEFT[w[1]][5:] + ', ' + w[2] if w else 'NO WINNER'}** ({ch['why']}); candidates {ch['candidates']}; "
          f"base G {ch['base_G']:+.1f}; CW3 (G of 3 d, tenth, raw = {ch['cw3_G']:+.1f} ≥ 1.5 × the base's): {'OPENED' if ch['cw3_opened'] else 'stays parked'}\n",
          show(tab), "\n", "\n## Described (decides nothing)\n", "\n### By segment\n", show(pd.DataFrame(by_seg)), "\n", "\n### F1+F2's next sixty (the model's fit months), apart\n", show(tab12), "\n",
          "\n### The tail a fifth (the reading of \"the forms on the top fifth\")\n", show(tab5), "\n", "\n### Other rows\n", "```\n", json.dumps(described, indent=1, default=str), "\n```\n",
          "\n### Exits by clause and skipped entries, per form and segment\n", "```\n", json.dumps(counts, indent=1, default=str), "\n```\n"]
    (OUT / "read_b.md").write_text("\n".join(md))
    print(f"{REG} (B): {'WINNER ' + str(w) if w else 'NO WINNER'} — {ch['why']}; base G {ch['base_G']:+.1f}; wrote {OUT}/", flush=True)
    return b


def main(action: str) -> None:
    {"a": run_a, "b": run_b}[action]()
