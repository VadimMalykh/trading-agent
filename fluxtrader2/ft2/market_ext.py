"""R30 — the US index and the ETF flows as MARKET-direction and sizing information (PLAN §8 R30).
`ft2 ceiling --target basket --family index` → output/market_index.md, output/market_index/
`ft2 ceiling --target basket --family etf --folds F2` → output/market_etf.md, output/market_etf/

R6's frame (`market.py`), unchanged: the equal-weight basket's vol-standardised forward log move at 1h / 4h / 1d on the
5-minute grid, the whole-sample uncentred IC with a HAC t over days and per calendar year, 200 circular whole-day shifts of
the label series as the null (the same draws for every number). What this module adds:

  family A (index)   six DIRECTION features — the Nasdaq 100's move over 1h / 4h / 24h (open hours), its move into the close
                     in force (closed hours), and how far the basket has LAGGED the index over 4h and 24h — and two SIZING
                     features (open / closed, the index's own volatility over σ_ix) read against the |move| target, with a
                     PARTIAL on R6's volratio_4h. The index's known-from and open/closed rules are R26's (`audit_index.Minutes`).
  family B (flows)   three DIRECTION features from the last KNOWN daily spot-ETF total (R27's known-at d + 1 09:00 UTC):
                     the flow, its five-day sum, the flow where it is large. F2 only — the series is cut to the fold's whole
                     days so the null's shifts are circular inside F2.
  the family bar     per family, per draw the largest |t| over ALL its rows (features × horizons): one p for the family.
  validity (1)       R6's seventeen features are screened in the same call with the same shifts and compared, number by
                     number, with the saved `output/market/screen.parquet` and `screen_null.parquet` (the index run).
  the money view     in ACTUAL returns: the basket's mean next-4h / next-1d simple return after a state, by year.

Every feature at a 5m bar t uses only what is known at t (asserted on every bar for the index minute and the flow).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import folds, market
from .audit_index import FLOW_BIG, FLOW_DAYS, FLOW_KNOWN, GAP_MINUTES, INDEX, KNOWN_AFTER, REF_INDEX, Minutes, _beta, load_minutes
from .ceiling import HORIZONS, MDE_K, basket, day_lags, hac
from .market import HZ, PER_DAY, cond_mean, encode, ic_stats

FAMILIES = {"index": {"direction": ["ix_1h", "ix_4h", "ix_24h", "ix_gap", "lag_4h", "lag_24h"], "sizing": ["ix_open", "ix_vol"]},
            "etf": {"direction": ["flow", "flow_5d", "flow_big"], "sizing": []}}
FOLDS = {"index": market.FOLDS, "etf": ("F2",)}
HALVES = {"F2": pd.Timestamp("2024-05-01", tz="UTC")}     # family B's parts: the two halves of F2 (R27's split)
SIGMA_DAYS, SIGMA_MIN_HOURS = 30, 200     # σ_ix: the last 30 days of hours open at both ends, ≥ 200 of them; b: the same days, hours open at t
B_HOURS = 24                              # b: the slope of the basket's 24-hour σ-unit move on the index's (amended 2026-10-08 before any real bar was read:
                                          # the 1-hour contemporaneous slope misses a slow follower — the test on made-up bars read it with the wrong sign)
VOL_HOURS, VOL_MIN_HOURS = 24, 12         # ix_vol: the sd of the index's 1h moves over its last 24 traded hours, ≥ 12
PARTIAL_BAR = 0.05                        # sizing: what the index must add to R6's volratio_4h
FLOW_SCALE = FLOW_BIG                     # one sd of the daily total (R27): flow = F / 300, so the ±5 clip is five sd
HOUR = pd.Timedelta("1h")
SIGNED = {"ix_1h", "ix_4h", "ix_24h", "ix_gap", "lag_4h", "lag_24h", "flow", "flow_5d", "flow_big"}


def out_paths(family: str) -> tuple[Path, Path]:
    return Path(f"output/market_{family}.md"), Path(f"output/market_{family}")


# ---- the index on the 5m grid ----------------------------------------------------------------------------------------------
def _hourly(mi: Minutes, hidx: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """On the hourly grid: the index's 1h move on hours open at both ends (bps), its 24h move on hours open at H, σ_ix, the
    24-traded-hour sd over σ_ix."""
    now, back, back24 = mi.at(hidx), mi.at(hidx - HOUR), mi.at(hidx - B_HOURS * HOUR)
    m1 = np.where(now["open"] & back["open"], (now["lc"] - back["lc"]) * 1e4, np.nan)
    m24 = np.where(now["open"], (now["lc"] - back24["lc"]) * 1e4, np.nan)
    s = pd.Series(m1)
    sigma = s.rolling(SIGMA_DAYS * 24, min_periods=SIGMA_MIN_HOURS).std().to_numpy()
    v = s.dropna()
    vol = v.rolling(VOL_HOURS, min_periods=VOL_MIN_HOURS).std().reindex(range(len(s))).ffill().to_numpy()   # the last 24 TRADED hours ending ≤ H
    return {"m1": m1, "m24": m24, "sigma": sigma, "vol": vol / sigma}


def features_index(idx: pd.DatetimeIndex, F6: dict[str, pd.Series], mi: Minutes) -> tuple[dict[str, pd.Series], dict[str, np.ndarray]]:
    """R30's eight index features on the 5m grid `idx`; `F6` R6's features (mret_1h, mret_4h, mret_1d are used).
    Returns (features, the index's own series on the grid: open, age_min, row, m_4h, gap)."""
    hidx = pd.date_range(idx[0].floor("h"), idx[-1], freq="1h")
    H = _hourly(mi, hidx)
    rc = F6["mret_1d"].reindex(hidx).to_numpy()[:, None]                     # the basket's 24-hour σ-unit move
    ri = H["m24"] / (H["sigma"] * np.sqrt(B_HOURS))                         # the index's, on hours open at H
    b = _beta(rc, ri, SIGMA_DAYS * 24, SIGMA_MIN_HOURS)[:, 0]
    to_grid = lambda a: pd.Series(a, index=hidx).reindex(idx, method="ffill").to_numpy()     # noqa: E731
    sigma, b5, vol = to_grid(H["sigma"]), to_grid(b), to_grid(H["vol"])
    now = mi.at(idx)
    back = {h: mi.at(idx - h * HOUR) for h in (1, 4, 24)}
    m = {h: (now["lc"] - back[h]["lc"]) * 1e4 for h in (1, 4, 24)}
    is_open = now["open"]
    ix = {"ix_1h": np.where(is_open & back[1]["open"], m[1], np.nan) / sigma,
          "ix_4h": np.where(is_open & back[4]["open"], m[4], np.nan) / (sigma * 2.0),
          "ix_24h": np.where(is_open, m[24], np.nan) / (sigma * np.sqrt(24.0)),
          "ix_gap": np.where(~is_open & (now["row"] >= 0), now["gap"] * 1e4, np.nan) / (sigma * np.sqrt(GAP_MINUTES / 60.0))}
    ix["lag_4h"] = b5 * ix["ix_4h"] - F6["mret_4h"].to_numpy()
    ix["lag_24h"] = b5 * ix["ix_24h"] - F6["mret_1d"].to_numpy()
    ix["ix_open"] = is_open.astype(float)
    ix["ix_vol"] = np.where(is_open, vol, np.nan)
    F = {k: pd.Series(v, index=idx).replace([np.inf, -np.inf], np.nan) for k, v in ix.items()}
    own = {"open": is_open, "age_min": now["age_min"], "row": now["row"], "m_4h": m[4], "gap": now["gap"], "b": b5, "sigma": sigma}
    return F, own


def ix_1h_frame(idx: pd.DatetimeIndex, end: pd.Timestamp, mi: Minutes | None = None) -> pd.DataFrame:
    """R31 (`rules.IndexHour`, attached by `backtest.EXTRAS["ix_1h"]`): R30's `ix_1h` alone, on the harness's bar index `idx`,
    from the minutes known before `end` — the same three lines as `features_index` (σ_ix on the hourly grid, the move over the
    last hour where the index is open at t and at t − 1 h), so the rule trades the number R30 screened. One column, `ix_1h`."""
    mi = load_minutes(INDEX, end) if mi is None else mi
    hidx = pd.date_range(idx[0].floor("h"), idx[-1], freq="1h")
    sigma = pd.Series(_hourly(mi, hidx)["sigma"], index=hidx).reindex(idx, method="ffill").to_numpy()
    now, back = mi.at(idx), mi.at(idx - HOUR)
    m1 = (now["lc"] - back["lc"]) * 1e4
    f = np.where(now["open"] & back["open"], m1, np.nan) / sigma
    return pd.DataFrame({"ix_1h": f}, index=idx).replace([np.inf, -np.inf], np.nan)


def check_known_index(idx: pd.DatetimeIndex, mi: Minutes, own: dict) -> dict:
    """Validity (2): on every bar the minute in force was known at t (ts + 1 min ≤ t)."""
    row = own["row"]
    ok = row >= 0
    late = int((mi.ts[row[ok]] + KNOWN_AFTER > idx[ok]).sum())
    return {"bars": int(len(idx)), "with_minute": int(ok.sum()), "used_before_known": late}


# ---- the flows on the 5m grid ----------------------------------------------------------------------------------------------
def features_etf(idx: pd.DatetimeIndex, flows: pd.Series, end: pd.Timestamp) -> tuple[dict[str, pd.Series], dict[str, np.ndarray]]:
    """R30's three flow features on the 5m grid: the last KNOWN daily total F (known from day + FLOW_KNOWN), its five-day sum,
    and F where |F| ≥ FLOW_BIG — each over FLOW_SCALE (F5 over FLOW_SCALE·√5). Returns (features, {F, F5, known_at})."""
    fl = flows[flows.index + FLOW_KNOWN <= end].sort_index()
    known = pd.DatetimeIndex(fl.index) + FLOW_KNOWN
    i = known.searchsorted(idx, side="right") - 1
    ok = i >= 0
    pick = lambda v: np.where(ok, np.asarray(v, dtype=float)[np.clip(i, 0, None)], np.nan)      # noqa: E731
    F = pick(fl.to_numpy())
    F5 = pick(fl.rolling(FLOW_DAYS, min_periods=FLOW_DAYS).sum().to_numpy())
    kn = (known.tz_convert("UTC").tz_localize(None) if known.tz is not None else known).to_numpy()
    kat = np.where(ok, kn[np.clip(i, 0, None)], np.datetime64("NaT"))
    feats = {"flow": F / FLOW_SCALE, "flow_5d": F5 / (FLOW_SCALE * np.sqrt(FLOW_DAYS)), "flow_big": np.where(np.abs(F) >= FLOW_BIG, F, np.nan) / FLOW_SCALE}
    return {k: pd.Series(v, index=idx) for k, v in feats.items()}, {"F": F, "F5": F5, "known_at": kat, "n_known": int(len(fl))}


def check_known_etf(idx: pd.DatetimeIndex, own: dict) -> dict:
    kat = own["known_at"]
    t = (idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx).to_numpy()
    ok = ~np.isnat(kat)
    late = int((kat[ok] > t[ok]).sum())
    return {"bars": int(len(idx)), "with_flow": int(ok.sum()), "used_before_known": late}


# ---- the cut to a fold's whole days (family B) ---------------------------------------------------------------------------
def cut_days(D: dict, F: dict[str, pd.Series], s: np.ndarray) -> tuple[dict, dict[str, pd.Series], np.ndarray]:
    """Everything restricted to the whole days from the first scored bar's day to the last's: the null's shifts are then
    circular inside the fold."""
    idx = D["blr"].index
    lo, hi = idx[s][0].floor("D"), idx[s][-1].floor("D") + pd.Timedelta(days=1)
    m = (idx >= lo) & (idx < hi)
    cut = lambda x: x[m] if isinstance(x, (pd.Series, pd.DataFrame)) else x       # noqa: E731
    D2 = {k: ({h: cut(v) for h, v in val.items()} if isinstance(val, dict) else cut(val)) for k, val in D.items()}
    return D2, {k: cut(v) for k, v in F.items()}, s[m]


# ---- the family-wise p across horizons, the parts, the partial --------------------------------------------------------------
def family_p(null: pd.DataFrame, bet: str, names: list[str], t_real: np.ndarray) -> tuple[np.ndarray, dict]:
    """One family: per draw the largest |t| over names × horizons; p = the share of draws at or above each real |t|."""
    nz = null[(null["draw"] > 0) & (null["bet"] == bet) & null["feature"].isin(names)].dropna(subset=["t"])
    mx = nz.assign(a=nz["t"].abs()).groupby("draw")["a"].max()
    p = np.array([(1 + int((mx >= abs(a)).sum())) / (len(mx) + 1) for a in t_real])
    return p, {"bar_mean": float(mx.mean()), "bar_p95": float(mx.quantile(0.95)), "draws": int(len(mx)), "rows": int(len(t_real))}


def parts_of(sidx: pd.DatetimeIndex, family: str, fold_names) -> np.ndarray:
    """Per scored DAY: the calendar year (family A) or the half of the fold (family B)."""
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    dates = pd.date_range(sidx[0].floor("D"), periods=int(day.max()) + 1, freq="D")
    if family == "etf":
        split = HALVES[folds.order(fold_names)[-1]]
        return np.where(dates < split, "H1", "H2")
    return dates.year.astype(str).to_numpy()


def part_ics(D: dict, F: dict[str, pd.Series], signed: set[str], s: np.ndarray, names: list[str], parts: np.ndarray, bet: str = "directional") -> pd.DataFrame:
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    fd, fa = encode({k: F[k] for k in names}, signed, s)
    rows = []
    for h in HZ:
        z = D["z"][h].to_numpy()[s]
        y = z if bet == "directional" else (pd.Series(np.abs(z)).rank(pct=True) - 0.5).to_numpy()
        for k in names:
            r = ic_stats((fd if bet == "directional" else fa)[k], y, day, day_lags(HORIZONS[h]), {"part": parts})
            vals = {p: float(v) for p, v in r["part"].items()}
            rows.append({"bet": bet, "horizon": h, "feature": k, **{f"ic_{p}": vals.get(p, np.nan) for p in dict.fromkeys(parts)},
                         "parts_same_sign": bool(len({np.sign(v) for v in vals.values() if np.isfinite(v)}) == 1 and all(np.isfinite(v) for v in vals.values()))})
    return pd.DataFrame(rows)


def partial_ics(D: dict, F: dict[str, pd.Series], s: np.ndarray, names: list[str], control: str = "volratio_4h") -> pd.DataFrame:
    """Sizing: the IC of each feature's rank with the |move| rank's residual on the control's rank (one coefficient, the
    scored bars), per horizon, with the HAC t and se."""
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    year = pd.date_range(sidx[0].floor("D"), periods=int(day.max()) + 1, freq="D").year.astype(str).to_numpy()
    rank = lambda x: (pd.Series(x).rank(pct=True) - 0.5).to_numpy()     # noqa: E731
    xc = rank(F[control][s].to_numpy())
    rows = []
    for h in HZ:
        y = rank(np.abs(D["z"][h].to_numpy()[s]))
        ok = ~np.isnan(y) & ~np.isnan(xc)
        beta = float(np.nansum((xc[ok] - xc[ok].mean()) * (y[ok] - y[ok].mean())) / np.nansum((xc[ok] - xc[ok].mean()) ** 2))
        res = np.where(ok, y - y[ok].mean() - beta * (xc - xc[ok].mean()), np.nan)
        for k in names:
            f = F[k][s].to_numpy()
            r = ic_stats(rank(f) if not np.isnan(f).all() else f, res, day, day_lags(HORIZONS[h]), {"year": year})
            rows.append({"horizon": h, "feature": k, "partial_ic": r["ic"], "partial_t": r["t"], "partial_se": r["ic_se"], "control_beta": beta,
                         "partial_years_same_sign": int(sum(np.sign(v) == np.sign(r["ic"]) for v in r["year"].values())), "partial_years": len(r["year"])})
    return pd.DataFrame(rows)


# ---- the verdicts ------------------------------------------------------------------------------------------------------------
def bars_from(mv: pd.DataFrame) -> dict[str, float]:
    """R6's #7 bar per horizon: the smaller of "maker, all bars" and "taker, most volatile tenth"."""
    need = mv[((mv["exec"] == "maker") & (mv["bars"] == "all bars")) | ((mv["exec"] == "taker") & (mv["bars"] != "all bars"))]
    return {h: float(g["ic_needed"].min()) for h, g in need.groupby("horizon")}


def verdict_direction(r: pd.Series, bar: float) -> str:
    se = r["ic_mde"] / MDE_K
    if r["p_family"] <= 0.05 and r["parts_same_sign"] and abs(r["ic"]) >= bar:
        return "CLEARS"
    if abs(r["ic"]) + 1.96 * se < bar:
        return "CLOSED"
    return "NOT DETECTABLE"


def verdict_sizing(r: pd.Series) -> str:
    if r["p_family"] <= 0.05 and r["parts_same_sign"] and r["partial_ic"] >= PARTIAL_BAR and r["partial_t"] >= MDE_K:
        return "CLEARS"
    if abs(r["partial_ic"]) + 1.96 * r["partial_se"] < PARTIAL_BAR:
        return "NOT ADDING"
    return "NOT DETECTABLE"


# ---- validity (1): R6 reproduced ----------------------------------------------------------------------------------------------
def r6_reproduction(sc: pd.DataFrame, null: pd.DataFrame, names: list[str], saved: Path = market.OUT_DIR) -> dict:
    """R6's rows of this run against the saved screen: ic, t, the per-year ICs (every bet × horizon) and every draw's t at 4h."""
    if not (saved / "screen.parquet").exists() or not (saved / "screen_null.parquet").exists():
        return {"status": "MISSING", "note": f"{saved}/screen.parquet or screen_null.parquet not found"}
    old, oldn = pd.read_parquet(saved / "screen.parquet"), pd.read_parquet(saved / "screen_null.parquet")
    key = ["bet", "horizon", "feature"]
    yrs = [c for c in old.columns if c.isdigit()]
    a = sc[sc["feature"].isin(names)].set_index(key)
    b = old[old["feature"].isin(names)].set_index(key)
    cols = ["ic", "t", *[c for c in yrs if c in a.columns]]
    j = a[cols].join(b[cols], rsuffix="_r6", how="inner")
    diff = {c: float((j[c] - j[f"{c}_r6"]).abs().max()) for c in cols}
    n4 = null[(null["horizon"] == market.PRIMARY) & null["feature"].isin(names)].set_index([*key, "draw"])["t"]
    o4 = oldn[(oldn["horizon"] == market.PRIMARY) & oldn["feature"].isin(names)].set_index([*key, "draw"])["t"]
    jn = pd.concat([n4.rename("new"), o4.rename("old")], axis=1, join="inner")
    diff["null_t_4h"] = float((jn["new"] - jn["old"]).abs().max())
    missing = int(len(b) - len(j))
    status = "PASS" if missing == 0 and len(j) == len(b) and len(jn) == len(o4) and all(v <= 1e-6 for v in diff.values()) else "FAIL"
    return {"status": status, "rows_compared": int(len(j)), "rows_r6": int(len(b)), "null_rows_compared": int(len(jn)), "null_rows_r6": int(len(o4)),
            "max_abs_diff": diff}


# ---- described --------------------------------------------------------------------------------------------------------------------
def actual_fwd(P: dict, h: str) -> pd.Series:
    """The basket's forward SIMPLE return over h, bps (the mean of the pairs' simple returns; ≥ MIN_PAIRS)."""
    k = HORIZONS[h]
    return basket((P["close"].shift(-k) / P["close"] - 1.0) * 1e4)


def money_view(P: dict, D: dict, F: dict[str, pd.Series], s: np.ndarray, states: dict[str, np.ndarray], parts: np.ndarray) -> pd.DataFrame:
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    part_of_bar = parts[day]
    rows = []
    for h in ("4h", "1d"):
        y = actual_fwd(P, h).reindex(idx).to_numpy()[s]
        for sname, on in states.items():
            for period, pm in [("all", np.ones(len(y), dtype=bool)), *[(p, part_of_bar == p) for p in dict.fromkeys(parts)]]:
                rows.append({"horizon": h, "state": sname, "period": period, **cond_mean(y, on[s] & pm, day, day_lags(HORIZONS[h]))})
    return pd.DataFrame(rows)


def size_view(P: dict, D: dict, s: np.ndarray, is_open: np.ndarray, parts: np.ndarray) -> pd.DataFrame:
    """The mean |next-1h move| of the basket, bps (actual), on open and on closed bars, by part."""
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    part_of_bar = parts[day]
    y = np.abs(actual_fwd(P, "1h").reindex(idx).to_numpy()[s])
    rows = []
    for sname, on in (("open", is_open[s]), ("closed", ~is_open[s]), ("every bar", np.ones(len(y), dtype=bool))):
        for period, pm in [("all", np.ones(len(y), dtype=bool)), *[(p, part_of_bar == p) for p in dict.fromkeys(parts)]]:
            rows.append({"state": sname, "period": period, **cond_mean(y, on & pm, day, day_lags(HORIZONS["1h"]))})
    return pd.DataFrame(rows)


def coverage(F: dict[str, pd.Series], s: np.ndarray, names: list[str]) -> pd.DataFrame:
    idx = F[names[0]].index[s]
    mon = np.asarray(idx.tz_localize(None).to_period("M").astype(str))
    return pd.DataFrame({k: pd.Series(F[k][s].notna().to_numpy(), index=idx).groupby(mon).mean() for k in names})


def reference_rows(D: dict, F: dict[str, pd.Series], signed: set[str], s: np.ndarray, names: list[str], tag: str) -> pd.DataFrame:
    """Real-only ICs (no null) of the given features at every horizon, both bets."""
    idx = D["blr"].index
    sidx = idx[s]
    day = (sidx.floor("D") - sidx[0].floor("D")).days.to_numpy()
    fd, fa = encode({k: F[k] for k in names}, signed, s)
    rows = []
    for h in HZ:
        z = D["z"][h].to_numpy()[s]
        for bet, y, enc in (("directional", z, fd), ("vol", (pd.Series(np.abs(z)).rank(pct=True) - 0.5).to_numpy(), fa)):
            for k in names:
                r = ic_stats(enc[k], y, day, day_lags(HORIZONS[h]))
                rows.append({"row": tag, "bet": bet, "horizon": h, "feature": k, "ic": r["ic"], "t": r["t"], "days": r["days"]})
    return pd.DataFrame(rows)


# ---- assemble -------------------------------------------------------------------------------------------------------------------
def run(family: str, taker_bps: float, maker_bps: float, fee_source: str, symbols: list[str], fold_names=None, draws: int = market.DRAWS) -> str:
    from . import data, etf
    from .backtest import PRE_START
    if family not in FAMILIES:
        raise SystemExit(f"no family {family}")
    fold_names = folds.order(fold_names or FOLDS[family])
    if bad := [f for f in fold_names if f not in market.FOLDS]:
        raise SystemExit(f"ceiling reads exploration data only; refused: {bad}")
    if family == "etf" and list(fold_names) != list(FOLDS["etf"]):
        raise SystemExit(f"--family etf reads {FOLDS['etf']} only (R30)")
    out_md, out_dir = out_paths(family)
    out_dir.mkdir(parents=True, exist_ok=True)
    end = folds.bounds(market.FOLDS[-1])[1]                     # every source cut at the end of F2, whatever the family reads
    print("panel…", flush=True)
    P = market.panel(symbols, end, PRE_START)
    idx, cols = P["close"].index, P["close"].columns
    D = market.derive(P)
    fu = data.load("funding_archive", columns=["symbol", "ts", "rate"], symbols=list(cols))
    fu = fu[fu["ts"] < end].assign(symbol=lambda x: x["symbol"].astype(str))
    F6, signed6 = market.features(P, D, fu.pivot(index="ts", columns="symbol", values="rate") * 1e4)
    s_all = market.scored_mask(idx, market.FOLDS)
    s = market.scored_mask(idx, fold_names)
    names_d, names_s = FAMILIES[family]["direction"], FAMILIES[family]["sizing"]
    validity: dict = {"family": family, "folds": list(fold_names)}
    refs = []
    if family == "index":
        mi = load_minutes(INDEX, end)
        F, own = features_index(idx, F6, mi)
        validity["known"] = check_known_index(idx, mi, own)
        try:
            Fr, _ = features_index(idx, F6, load_minutes(REF_INDEX, end))
            refs.append(("US500 in place of US100", Fr))
        except FileNotFoundError:
            pass
        is_open = own["open"]
    else:
        flows = etf.totals("BTC")
        F, own = features_etf(idx, flows, end)
        kat_s, F_s = own["known_at"][s], own["F"][s]
        validity["known"] = {**check_known_etf(idx, own), "flow_days_known_in_fold": int(len(np.unique(kat_s[~np.isnan(F_s)])))}
        is_open = None
    validity["known"]["status"] = "PASS" if validity["known"]["used_before_known"] == 0 else "FAIL"

    # #7 the bar — R6's table on R6's bars, whatever the family reads
    print("#7 move vs cost…", flush=True)
    vr = F6["volratio_4h"]
    mv = market.move_vs_cost(D, market.basket_cost(idx, cols, end, taker_bps, maker_bps), s_all, (vr >= vr[s_all].quantile(1 - market.TOP)).to_numpy())
    bars = bars_from(mv)

    # the screen: the family's features and R6's seventeen, one call, the same shifts
    Fall = {**F, **F6}
    signed = SIGNED | signed6
    Dx, Fx, sx = (cut_days(D, Fall, s) if family == "etf" else (D, Fall, s))
    sidx = Dx["blr"].index[sx]
    n_days = len(Dx["blr"].index) // PER_DAY
    validity["bars"] = {"scored": int(sx.sum()), "days": int(len(np.unique(sidx.floor("D")))), "series_days": int(n_days),
                        "first": str(sidx[0]), "last": str(sidx[-1]), "whole_days": bool(len(Dx["blr"].index) == n_days * PER_DAY)}
    print(f"screen: {len(Fall)} features × {len(HZ)} horizons × 2 bets × {draws} shifts on {n_days} days…", flush=True)
    sc, null = market.screen(Dx, Fx, signed, sx, draws)
    parts = parts_of(sidx, family, fold_names)
    pi = part_ics(Dx, Fx, signed, sx, names_d, parts)
    rows = sc[(sc["bet"] == "directional") & sc["feature"].isin(names_d)].merge(pi, on=["bet", "horizon", "feature"])
    rows["p_family"], fam_d = family_p(null, "directional", names_d, rows["t"].to_numpy())
    rows["bar"] = rows["horizon"].map(bars)
    rows["ic_se"] = rows["ic_mde"] / MDE_K
    rows["upper"] = rows["ic"].abs() + 1.96 * rows["ic_se"]
    rows["verdict"] = [verdict_direction(r, r["bar"]) for _, r in rows.iterrows()]
    bars_md = {"direction": fam_d}
    if names_s:
        ps = part_ics(Dx, Fx, signed, sx, names_s, parts, bet="vol")
        pr = partial_ics(Dx, Fx, sx, names_s)
        srows = sc[(sc["bet"] == "vol") & sc["feature"].isin(names_s)].merge(ps, on=["bet", "horizon", "feature"]).merge(pr, on=["horizon", "feature"])
        srows["p_family"], fam_s = family_p(null, "vol", names_s, srows["t"].to_numpy())
        srows["ic_se"] = srows["ic_mde"] / MDE_K
        srows["verdict"] = [verdict_sizing(r) for _, r in srows.iterrows()]
        bars_md["sizing"] = fam_s
    else:
        srows = pd.DataFrame()
    validity["r6"] = r6_reproduction(sc, null, list(F6)) if family == "index" else {"status": "N/A", "note": "the F2 cut is not R6's sample; the frame is checked by the index run"}
    validity["status"] = "PASS" if validity["known"]["status"] == "PASS" and validity["bars"]["whole_days"] and validity["r6"]["status"] in ("PASS", "N/A") else "FAIL"

    # described
    print("described…", flush=True)
    ref = [reference_rows(Dx, Fx, signed, sx, list(F6), "R6's features (this run)")]
    for tag, Fr in refs:
        Frx = cut_days(D, Fr, s)[1] if family == "etf" else Fr
        ref.append(reference_rows(Dx, Frx, signed, sx, list(Fr), tag))
    ref = pd.concat(ref, ignore_index=True)
    cov = coverage(Fx, sx, [*names_d, *names_s])
    Px = {k: (v[(v.index >= Dx["blr"].index[0]) & (v.index <= Dx["blr"].index[-1])] if family == "etf" else v) for k, v in P.items()}
    if family == "index":
        g = {k: Fx[k].to_numpy() for k in ("ix_4h", "ix_gap", "lag_4h")}
        op = is_open
        states = {"index rose ≥ 1σ over 4h (open)": g["ix_4h"] >= 1, "index fell ≥ 1σ over 4h (open)": g["ix_4h"] <= -1,
                  "gap up ≥ 1σ (closed)": g["ix_gap"] >= 1, "gap down ≥ 1σ (closed)": g["ix_gap"] <= -1,
                  "basket lagged the index by ≥ 1σ over 4h": g["lag_4h"] >= 1, "basket ran ahead of the index by ≥ 1σ over 4h": g["lag_4h"] <= -1,
                  "open bars": op, "closed bars": ~op, "every bar": np.ones(len(op), dtype=bool)}
        states = {k: np.nan_to_num(v.astype(float), nan=0.0).astype(bool) for k, v in states.items()}
        sv = size_view(Px, Dx, sx, op, parts)
        age = pd.Series(own["age_min"][s], index=idx[s])
        age_tab = age.groupby(idx[s].dayofweek * 24 + idx[s].hour).mean().rename("age_min").reset_index().rename(columns={"index": "hour_of_week"})
    else:
        Fv = own["F"]
        Fvx = Fv[(idx >= Dx["blr"].index[0]) & (idx <= Dx["blr"].index[-1])]
        states = {"after an inflow day": Fvx > 0, "after an outflow day": Fvx < 0, f"after a large inflow (≥ {FLOW_BIG:g})": Fvx >= FLOW_BIG,
                  f"after a large outflow (≤ −{FLOW_BIG:g})": Fvx <= -FLOW_BIG, "every bar": np.ones(len(Fvx), dtype=bool)}
        states = {k: np.nan_to_num(v.astype(float), nan=0.0).astype(bool) for k, v in states.items()}
        sv, age_tab = pd.DataFrame(), pd.DataFrame()
    mo = money_view(Px, Dx, Fx, sx, states, parts)

    for name, df in (("screen", rows), ("screen_sizing", srows), ("screen_all", sc), ("screen_null", null), ("reference", ref), ("coverage", cov.reset_index()),
                     ("money_view", mo), ("size_view", sv), ("minute_age", age_tab), ("move_vs_cost", mv.assign(**{"from": mv["from"].astype(str)}))):
        if len(df):
            df.to_parquet(out_dir / f"{name}.parquet", index=False)
    (out_dir / "validity.json").write_text(json.dumps(validity, indent=1, default=str))

    show = lambda df, digits=4: df.round(digits).to_markdown(index=False)      # noqa: E731
    part_cols = [c for c in rows.columns if c.startswith("ic_") and c not in ("ic_mde", "ic_se")]
    md = [f"# R30 — the {'US index' if family == 'index' else 'ETF flows'} as market-direction{' and sizing' if names_s else ''} information on the basket "
          f"(`ft2 ceiling --target basket --family {family}`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC\n",
          f"\n**Folds read:** {'+'.join(fold_names)}; every source cut at {end:%Y-%m-%d}. Scored bars {sidx[0]:%Y-%m-%d} → {sidx[-1]:%Y-%m-%d} ({int(sx.sum()):,}; "
          f"{validity['bars']['days']} days; the series {n_days} whole days); {draws} circular day shifts. Fees (input): taker {taker_bps}, maker {maker_bps} bps — {fee_source}.\n",
          f"\n## Validity — **{validity['status']}**\n", "```\n" + json.dumps(validity, indent=1, default=str) + "\n```\n",
          "\n## The bar (R6's #7, recomputed on R6's bars): the smaller of maker-all-bars and taker-most-volatile-tenth\n",
          "\n".join(f"- {h}: {b:.4f}" for h, b in bars.items()) + "\n",
          "\n## Direction — the family, per number\n",
          f"family bar (the largest |t| over the family's rows per draw): mean {fam_d['bar_mean']:.2f}, p95 **{fam_d['bar_p95']:.2f}** on {fam_d['draws']} draws, {fam_d['rows']} rows.\n",
          show(rows[["horizon", "feature", "ic", "t", "ic_se", "ic_mde", "upper", "bar", "p_single", "p_family", *part_cols, "parts_same_sign", "months_same_sign", "days", "verdict"]]), "\n"]
    if len(srows):
        md += ["\n## Sizing — the |move| target, per number, with the partial on volratio_4h\n",
               f"family bar: mean {bars_md['sizing']['bar_mean']:.2f}, p95 **{bars_md['sizing']['bar_p95']:.2f}**.\n",
               show(srows[["horizon", "feature", "ic", "t", "ic_se", "p_family", *[c for c in srows.columns if c.startswith('ic_') and c not in ('ic_mde', 'ic_se')],
                           "parts_same_sign", "partial_ic", "partial_t", "partial_se", "partial_years_same_sign", "partial_years", "verdict"]]), "\n"]
    md += ["\n## Described — decides nothing\n", "\n### R6's features in this run, and the reference index (real-only ICs; no null)\n", show(ref), "\n",
           "\n### The money view — the basket's mean next-4h / next-1d SIMPLE return, bps before costs\n", "mean (t) [days]; blank = fewer than 50 bars or 5 days.\n"]
    cell = lambda r: "" if np.isnan(r["mean"]) else f"{r['mean']:+.1f} ({r['mean'] / r['se']:+.1f}) [{r['days']}]"   # noqa: E731
    pcols = ["all", *dict.fromkeys(parts)]
    md += [mo.assign(cell=mo.apply(cell, axis=1)).pivot(index=["horizon", "state"], columns="period", values="cell")[pcols].reset_index().to_markdown(index=False), "\n"]
    if len(sv):
        md += ["\n### Sizing in plain bps — the basket's mean |next-1h move|, open against closed\n",
               sv.assign(cell=sv.apply(cell, axis=1)).pivot(index="state", columns="period", values="cell")[pcols].reset_index().to_markdown(index=False), "\n"]
    md += ["\n### Coverage of bars per month\n", cov.round(3).to_markdown(), "\n"]
    if len(age_tab):
        md += ["\n### The age of the index minute in force, minutes, per hour of the week (0 = Monday 00:00 UTC)\n", show(age_tab, 1), "\n"]
    md += ["\n### #7 (R6's table, this run)\n", show(mv), "\n"]
    text = "\n".join(md)
    out_md.write_text(text)
    return text
