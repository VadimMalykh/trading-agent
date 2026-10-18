"""AA5 (PLAN P8, decision AG's AG1): the spot-hedged funding carry's arithmetic — a DESCRIBED row. No registration, no gate, no verdict,
no fold spent. What a short perpetual hedged with a spot long would have collected in funding on the twelve (F1–F5) and on the screener's
members while members (F1–F4), by fold and by S90; whether the names paying the most keep paying (point-in-time top quartile by trailing
30-day funding against its realised next 30 days); the premium index's level and 30-day change as the hedge's mark-to-market; and the
money of a 10,000 USDT-a-leg position in the top-quartile set, rebalanced every 30 days, after the perp's taker costs, an ASSUMED spot
taker cost (stated) and the premium's move.

    python scripts/aa5_carry.py            → output/audit/aa5_carry/{carry.md, carry.json, by_fold.csv, by_state.csv, persistence.csv,
                                             premium.csv, money.csv, money_blocks.csv, funding_daily.parquet}

The funding is read through the harness's `load_costs` on a daily grid — the same cumulated series the harness charges a position — so
a day's funding here is exactly what a position open through that day pays or receives.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import backtest as bt  # noqa: E402
from ft2 import data, folds  # noqa: E402

OUT = Path("output/audit/aa5_carry")
TWELVE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "ZECUSDT", "1000PEPEUSDT", "WLDUSDT", "HYPEUSDT"]
FT2 = Path(__file__).resolve().parents[1] / "ft2"
MEMBERS = {"F1": FT2 / "screen_members.csv", "F2": FT2 / "screen_members.csv", "F3": FT2 / "screen_members_f34.csv", "F4": FT2 / "screen_members_f34.csv"}
FOLDS_TWELVE = ("F1", "F2", "F3", "F4", "F5")
FOLDS_MEMBERS = ("F1", "F2", "F3", "F4")
STATE_DAILY = Path("output/backtest/r47_mech/daily.parquet")
PREMIUM = Path("data/premium.parquet")
DAY = pd.Timedelta(days=1)
BLOCK_DAYS = 30                 # the members' block and the carry's rebalance
LOOKBACK_DAYS = 30              # the trailing window that picks the names paying the most
MIN_LOOKBACK = 20               # a name needs this many funded days in the window to be ranked
TOP_SHARE = 0.25                # the top quartile
NOTIONAL = 10_000.0             # USDT a leg
PERP_FEE_BPS = 5.0              # the harness's taker fee a side
SPOT_FEE_BPS = 10.0             # ASSUMED: Binance spot's VIP0 taker fee a side; the spot's half-spread and impact ASSUMED equal to the perp's
ANNUAL = 365.0 / BLOCK_DAYS


# ---- the series --------------------------------------------------------------------------------------------------------------------
def day_grid(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(start.floor("D"), end.floor("D"), freq="D", tz="UTC", inclusive="left", name="day")


def daily_funding(C: bt.Costs, days: pd.DatetimeIndex, cols) -> pd.DataFrame:
    """bps of the position's value a SHORT receives on each day [d, d+1): the difference of the harness's cumulated series, which must
    have been loaded on the index `days − 1 ns` plus one more such instant (events stamped < d)."""
    cum = C.fundcum
    assert cum.shape[0] == len(days) + 1, "daily_funding: load the costs on cost_index(days)"
    return pd.DataFrame(np.diff(cum, axis=0), index=days, columns=cols)


def cost_index(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(list(days) + [days[-1] + DAY]) - pd.Timedelta(1, "ns")


def membership(days: pd.DatetimeIndex, cols, blocks: pd.DataFrame | None) -> pd.DataFrame:
    """day × name: True while the name is a member (a block's 30 days); every day for a fixed universe (blocks None)."""
    M = pd.DataFrame(blocks is None, index=days, columns=cols)
    if blocks is not None:
        M[:] = False
        for b, g in blocks.groupby("block"):
            sel = (days >= b) & (days < b + BLOCK_DAYS * DAY)
            M.loc[sel, [s for s in g["symbol"] if s in M.columns]] = True
    return M


def taker_leg_daily(C: bt.Costs, days: pd.DatetimeIndex, cols) -> pd.DataFrame:
    """bps a side, fee excluded (half the spread + impact at NOTIONAL), on the day grid (the last known day carried forward)."""
    return pd.DataFrame(C.taker_leg, index=C.days, columns=cols).reindex(days, method="ffill")


def premium_daily(symbols: list[str], days: pd.DatetimeIndex, path: Path = PREMIUM) -> pd.DataFrame:
    """day × name, bps: the premium index (perpetual over the spot index − 1) on the day's last 5m bar; NaN where the file has no name."""
    if not path.exists():
        return pd.DataFrame(np.nan, index=days, columns=symbols)
    p = pd.read_parquet(path, filters=[("symbol", "in", symbols)])
    p["symbol"] = p["symbol"].astype(str)
    p = p[(p["open_time"].dt.hour == 23) & (p["open_time"].dt.minute == 55)]
    P = p.assign(day=p["open_time"].dt.floor("D")).pivot(index="day", columns="symbol", values="premium") * 1e4
    return P.reindex(index=days, columns=symbols)


def state_daily(days: pd.DatetimeIndex, path: Path | None = STATE_DAILY) -> pd.Series:
    if path is None or not Path(path).exists():
        return pd.Series(0, index=days)
    d = pd.read_parquet(path, columns=["day", "state"])
    return pd.Series(d["state"].to_numpy(), index=pd.DatetimeIndex(d["day"])).reindex(days).fillna(0).astype(int)


def fold_of_day(days: pd.DatetimeIndex, fold_names) -> pd.Series:
    f = pd.Series("", index=days)
    for name in fold_names:
        a, b = folds.bounds(name, embargoed=False)
        f[(days >= a) & (days < b)] = name
    return f


# ---- the tables --------------------------------------------------------------------------------------------------------------------
def _ann(x):                     # bps a day → % a year
    return float(x) * 365.0 / 100.0


def by_group(F: pd.DataFrame, M: pd.DataFrame, groups: dict[str, np.ndarray], universe: str) -> pd.DataFrame:
    rows = []
    for g, sel in groups.items():
        X = F[sel].where(M[sel])
        v = X.stack().dropna()
        if not len(v):
            continue
        per_name = X.mean()
        per_name = per_name[X.notna().sum() >= MIN_LOOKBACK]
        rows.append({"universe": universe, "group": g, "name_days": int(len(v)), "names": int(len(per_name)), "days": int(sel.sum()),
                     "mean_pct_yr": _ann(v.mean()), "median_name_pct_yr": _ann(per_name.median()), "p10_name_pct_yr": _ann(per_name.quantile(0.1)),
                     "p90_name_pct_yr": _ann(per_name.quantile(0.9)), "share_days_negative": float((v < 0).mean()), "mean_bps_day": float(v.mean()), "sd_bps_day": float(v.std())})
    return pd.DataFrame(rows)


def block_starts(days: pd.DatetimeIndex, first: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    first = days[0] if first is None else first
    return pd.DatetimeIndex([d for d in pd.date_range(first, days[-1], freq=f"{BLOCK_DAYS}D") if d + BLOCK_DAYS * DAY <= days[-1] + DAY])


def top_sets(F: pd.DataFrame, M: pd.DataFrame, starts: pd.DatetimeIndex) -> dict[pd.Timestamp, list[str]]:
    """Point-in-time: at block start b the top quartile of the names that are members ON b, ranked by the mean funding over
    [b − LOOKBACK, b) — days before b only; a name needs MIN_LOOKBACK funded days there."""
    sets = {}
    for b in starts:
        if b - LOOKBACK_DAYS * DAY < F.index[0]:
            continue
        win = F[(F.index >= b - LOOKBACK_DAYS * DAY) & (F.index < b)]
        here = M.loc[b] if b in M.index else pd.Series(False, index=F.columns)
        cand = win.loc[:, here[here].index]
        ok = cand.notna().sum() >= MIN_LOOKBACK
        trail = cand.mean()[ok]
        k = max(int(np.ceil(TOP_SHARE * len(trail))), 1) if len(trail) else 0
        sets[b] = list(trail.sort_values(ascending=False).index[:k]) if k else []
    return sets


def persistence(F: pd.DataFrame, M: pd.DataFrame, sets: dict, fold_of: pd.Series) -> pd.DataFrame:
    rows = []
    for b, top in sets.items():
        sel = (F.index >= b) & (F.index < b + BLOCK_DAYS * DAY)
        X = F[sel].where(M[sel])
        allv = X.stack().dropna()
        topv = X[top].stack().dropna() if top else pd.Series(dtype=float)
        trail = F[(F.index >= b - LOOKBACK_DAYS * DAY) & (F.index < b)][top].stack().dropna() if top else pd.Series(dtype=float)
        rows.append({"block": b, "fold": fold_of.get(b, ""), "n_top": len(top), "n_all": int(X.notna().any().sum()), "trailing_top_pct_yr": _ann(trail.mean()) if len(trail) else np.nan,
                     "next_top_pct_yr": _ann(topv.mean()) if len(topv) else np.nan, "next_all_pct_yr": _ann(allv.mean()) if len(allv) else np.nan,
                     "next_rest_pct_yr": _ann(X.drop(columns=top).stack().dropna().mean()) if len(allv) else np.nan})
    return pd.DataFrame(rows)


def premium_table(P: pd.DataFrame, M: pd.DataFrame, fold_of: pd.Series, universe: str) -> pd.DataFrame:
    rows = []
    for f in sorted(set(fold_of) - {""}):
        sel = (fold_of == f).to_numpy()
        X = P[sel].where(M[sel])
        v = X.stack().dropna()
        d30 = (P.shift(-BLOCK_DAYS) - P)[sel].where(M[sel]).stack().dropna()
        rows.append({"universe": universe, "fold": f, "names_with_premium": int(X.notna().any().sum()), "names": int(M[sel].any().sum()), "mean_bps": float(v.mean()) if len(v) else np.nan,
                     "median_bps": float(v.median()) if len(v) else np.nan, "d30_mean_bps": float(d30.mean()) if len(d30) else np.nan, "d30_sd_bps": float(d30.std()) if len(d30) else np.nan,
                     "d30_p05_bps": float(d30.quantile(0.05)) if len(d30) else np.nan, "d30_p95_bps": float(d30.quantile(0.95)) if len(d30) else np.nan})
    return pd.DataFrame(rows)


def money(F: pd.DataFrame, TL: pd.DataFrame, P: pd.DataFrame, sets: dict, fold_of: pd.Series, perp_fee: float = PERP_FEE_BPS, spot_fee: float = SPOT_FEE_BPS) -> pd.DataFrame:
    """Per block and name in the set: the funding received over the hold, the perp's and the spot's entry + exit costs (a name held
    from the previous block pays no re-entry; a name leaving pays its exit at the end), the premium's move against the short, the net
    — bps of ONE leg's notional. The block's row is the equal-weighted mean over its names."""
    rows = []
    prev: set[str] = set()
    items = sorted(sets.items())
    for i, (b, top) in enumerate(items):
        nxt = set(items[i + 1][1]) if i + 1 < len(items) else set()
        sel = (F.index >= b) & (F.index < b + BLOCK_DAYS * DAY)
        last = F.index[sel][-1]
        for s in top:
            fund = float(F.loc[sel, s].sum(min_count=1))
            tl_in, tl_out = float(TL.loc[b, s]) if np.isfinite(TL.loc[b, s]) else 0.0, float(TL.loc[last, s]) if np.isfinite(TL.loc[last, s]) else 0.0
            enter, leave = s not in prev, s not in nxt
            perp_cost = (perp_fee + tl_in) * enter + (perp_fee + tl_out) * leave
            spot_cost = (spot_fee + tl_in) * enter + (spot_fee + tl_out) * leave
            p0, p1 = P.loc[b - DAY, s] if (b - DAY) in P.index else np.nan, P.loc[last, s]
            dprem = -(p1 - p0) if np.isfinite(p0) and np.isfinite(p1) else np.nan                    # the short gains when the premium falls
            rows.append({"block": b, "fold": fold_of.get(b, ""), "year": b.year, "symbol": s, "funding_bps": fund, "perp_cost_bps": perp_cost, "spot_cost_bps": spot_cost,
                         "dprem_bps": dprem, "entered": enter, "left": leave, "net_bps": fund - perp_cost - spot_cost + (dprem if np.isfinite(dprem) else 0.0), "premium_held": bool(np.isfinite(dprem))})
        prev = set(top)
    return pd.DataFrame(rows)


def money_summary(mb: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    if not len(mb):
        return pd.DataFrame(rows)
    blocks = mb.groupby("block").agg(fold=("fold", "first"), year=("year", "first"), n=("symbol", "size"), funding=("funding_bps", "mean"), perp_cost=("perp_cost_bps", "mean"),
                                     spot_cost=("spot_cost_bps", "mean"), dprem=("dprem_bps", "mean"), net=("net_bps", "mean"), premium_share=("premium_held", "mean"), turnover=("entered", "mean"))
    for g, x in list(blocks.groupby(by)) + [("all", blocks)]:
        rows.append({by: str(g), "blocks": int(len(x)), "names_a_block": float(x["n"].mean()), "funding_bps_block": float(x["funding"].mean()), "perp_cost_bps_block": float(x["perp_cost"].mean()),
                     "spot_cost_bps_block": float(x["spot_cost"].mean()), "dprem_bps_block": float(x["dprem"].mean()), "premium_share": float(x["premium_share"].mean()), "turnover": float(x["turnover"].mean()),
                     "net_bps_block": float(x["net"].mean()), "net_sd_bps_block": float(x["net"].std()) if len(x) > 1 else np.nan, "share_blocks_negative": float((x["net"] < 0).mean()),
                     "net_pct_yr_one_leg": float(x["net"].mean()) * ANNUAL / 100.0, "net_pct_yr_both_legs_capital": float(x["net"].mean()) * ANNUAL / 200.0,
                     "usdt_yr_at_10k_a_leg": float(x["net"].mean()) * ANNUAL / 1e4 * NOTIONAL})
    return pd.DataFrame(rows)


# ---- the run -----------------------------------------------------------------------------------------------------------------------
def universe_frames(name: str, fold_names, costs=None, premium=None, state_path=STATE_DAILY) -> dict:
    a = folds.bounds(fold_names[0], embargoed=False)[0] - LOOKBACK_DAYS * DAY                       # the lookback before the first block
    b = folds.bounds(fold_names[-1], embargoed=False)[1]
    days = day_grid(a, b)
    if name == "twelve":
        cols, blocks = pd.Index(TWELVE), None
    else:
        parts = [pd.read_csv(path, usecols=["block", "symbol"]).assign(block=lambda x: pd.to_datetime(x["block"], utc=True)) for path in dict.fromkeys(MEMBERS[f] for f in fold_names)]
        blocks = pd.concat(parts, ignore_index=True).drop_duplicates()
        cols = pd.Index(sorted(set(blocks["symbol"])))
    C = costs if costs is not None else bt.load_costs(cost_index(days), cols, b + DAY)
    F = daily_funding(C, days, cols)
    M = membership(days, cols, blocks)
    TL = taker_leg_daily(C, days, cols)
    P = premium if premium is not None else premium_daily(list(cols), days)
    fold_of = fold_of_day(days, fold_names)
    st = state_daily(days, state_path)
    return {"name": name, "days": days, "cols": cols, "F": F, "M": M & F.notna(), "TL": TL, "P": P, "fold_of": fold_of, "state": st, "first_block": folds.bounds(fold_names[0], embargoed=False)[0]}


def describe(U: dict) -> dict:
    F, M, fold_of, st = U["F"], U["M"], U["fold_of"], U["state"]
    scored = (fold_of != "").to_numpy()
    groups = {f"fold {f}": (fold_of == f).to_numpy() for f in sorted(set(fold_of) - {""})}
    groups["all folds"] = scored
    by_fold = by_group(F, M, groups, U["name"])
    sg = {"S90 +1 (after a rising quarter)": scored & (st > 0).to_numpy(), "S90 −1 (after a falling quarter)": scored & (st < 0).to_numpy()}
    for f in sorted(set(fold_of) - {""}):
        sg[f"{f} · S90 +1"] = (fold_of == f).to_numpy() & (st > 0).to_numpy()
        sg[f"{f} · S90 −1"] = (fold_of == f).to_numpy() & (st < 0).to_numpy()
    by_state = by_group(F, M, sg, U["name"])
    starts = block_starts(U["days"], U["first_block"])
    sets = top_sets(F, M, starts)
    pers = persistence(F, M, sets, fold_of)
    prem = premium_table(U["P"], M, fold_of, U["name"])
    mb = money(F, U["TL"], U["P"], sets, fold_of)
    return {"by_fold": by_fold, "by_state": by_state, "persistence": pers, "premium": prem, "money_blocks": mb,
            "money_by_fold": money_summary(mb, "fold").assign(universe=U["name"]), "money_by_year": money_summary(mb, "year").assign(universe=U["name"]),
            "names_top": pd.Series([s for v in sets.values() for s in v]).value_counts().head(12).rename("blocks_in_top").reset_index().rename(columns={"index": "symbol"}),
            "sets": {str(k.date()): v for k, v in sets.items()}}


def _md(D: dict, U: dict) -> str:
    show = lambda df, k=2: df.round(k).to_markdown(index=False) if len(df) else "(none)"  # noqa: E731
    pers = D["persistence"]
    pfold = pers.groupby("fold")[["trailing_top_pct_yr", "next_top_pct_yr", "next_all_pct_yr", "next_rest_pct_yr"]].mean().reset_index() if len(pers) else pers
    return "\n".join([f"\n# {U['name']}: {len(U['cols'])} names, {U['days'][0].date()} → {U['days'][-1].date()}, {int(U['M'].to_numpy().sum()):,} funded member-days\n",
                      "\n## By fold — the funding a SHORT receives, % a year of the position's value (equal weight over name-days; a NEGATIVE share is the days the short paid)\n", show(D["by_fold"]),
                      "\n## By S90 at the day (R45's state: the sign of the twelve's basket's trailing 90-day move)\n", show(D["by_state"]),
                      "\n## The names paying the most — point-in-time: the top quartile by the TRAILING 30 days' funding, then its realised NEXT 30 days against the universe's (means over blocks)\n", show(pfold),
                      f"\nMost often in the top quartile: {', '.join(f'{r.symbol} {r.blocks_in_top}' for r in D['names_top'].itertuples())}\n",
                      "\n## The basis leg — the premium index (perpetual over the spot index), bps: its level and its 30-day change (the hedge's mark-to-market; the short gains when it falls)\n", show(D["premium"]),
                      f"\n## The money — {NOTIONAL:,.0f} USDT a leg, short perp / long spot in the top-quartile set, rebalanced every {BLOCK_DAYS} days: funding − perp taker costs ({PERP_FEE_BPS:.0f} bps fee + the harness's half-spread and impact, a side) − spot costs (ASSUMED {SPOT_FEE_BPS:.0f} bps fee + the same half-spread and impact, a side; no borrow) − the premium's move (0 where no premium is held) — bps of ONE leg's notional a block; the % a year on BOTH legs' capital at 1× margin\n",
                      "### by fold\n", show(D["money_by_fold"]), "\n### by calendar year\n", show(D["money_by_year"]), "\n"])


def run(out: Path = OUT, universes=(("twelve", FOLDS_TWELVE), ("members", FOLDS_MEMBERS))) -> dict:
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    md = [f"# AA5 — the spot-hedged funding carry's arithmetic (a described row; decision AG's AG1)\n\ngenerated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · "
          "funding from `data/funding_archive.parquet` through the harness's `load_costs` on a daily grid · the premium from `data/premium.parquet` · S90 from `output/backtest/r47_mech/daily.parquet`\n"
          "\nWords: *funding* is what a SHORT perpetual receives (bps of the position's value; the sum of the day's settlements; negative = the short paid). *% a year* multiplies a day's mean by 365. "
          "Nothing here is a forecast or a verdict: the sign of the carry is known; the row says how much, on which names, in which state, and what a hedged position would have netted after stated costs.\n"]
    res, frames = {}, {}
    for name, fold_names in universes:
        U = universe_frames(name, fold_names)
        D = describe(U)
        md.append(_md(D, U))
        res[name] = {k: (v.to_dict("records") if isinstance(v, pd.DataFrame) else v) for k, v in D.items() if k != "money_blocks"}
        for k in ("by_fold", "by_state", "persistence", "premium", "money_blocks", "money_by_fold", "money_by_year"):
            frames.setdefault(k, []).append(D[k].assign(universe=name) if "universe" not in D[k] else D[k])
        U["F"].where(U["M"]).stack().rename("funding_bps").reset_index().assign(universe=name).to_parquet(out / f"funding_daily_{name}.parquet", index=False)
    for k, v in frames.items():
        pd.concat(v, ignore_index=True).to_csv(out / f"{k}.csv", index=False)
    res["seconds"] = round(time.time() - t0, 1)
    res["written"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    res["assumptions"] = {"perp_fee_bps_a_side": PERP_FEE_BPS, "spot_fee_bps_a_side_ASSUMED": SPOT_FEE_BPS, "spot_half_spread_and_impact": "ASSUMED equal to the perp's taker_leg",
                          "margin": "1x: the capital is both legs' notional", "borrow": "none (the spot is bought with cash)", "block_days": BLOCK_DAYS, "lookback_days": LOOKBACK_DAYS, "top_share": TOP_SHARE}
    (out / "carry.json").write_text(json.dumps(res, indent=1, default=str))
    (out / "carry.md").write_text("\n".join(md))
    print(f"AA5: wrote {out}/ in {res['seconds']} s", flush=True)
    return res


if __name__ == "__main__":
    run()
