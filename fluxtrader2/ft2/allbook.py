"""R90 (docs/PLAN.md §8): R89's saved forecast traded as an hourly long-top-tenth / short-bottom-tenth book of F5's coins — `ft2 allbook run`.

The registration is the specification; this docstring only maps it to the code.

forecast   `output/allgbm/r89/forecast.parquet` as saved (md5 checked); nothing refitted or re-scored.
rule       `decisions`: per hourly bar with n ≥ 10 forecasts, k = n // 10; +1 on the k highest, −1 on the k lowest (ties by symbol); each a
           position of size 1 (10,000 USDT), hold 288 bars; `backtest.accept` keeps one position a name.
pricing    `backtest.price` — taker (the gate), the names' own `cost_daily_wide` rows, funding on the value; `backtest.summarize` gives the
           mean net per trade with the day-clustered HAC interval; `verdict` is the gate.
described  the sides, hedged net, the old / new coins, the book without the five named coins, the months, the maker estimate, costs × 1.5.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt, folds, universe

OUT = Path("output/allbook")
REG, NAME = "R90", "r90"
FORECAST = Path("output/allgbm/r89/forecast.parquet")
FORECAST_MD5 = "0473adf9eabf1747b576c849fe484f98"
HOLD = 288
MIN_N, TENTH = 10, 10
T_ONE_SIDED = 1.645
TAKER_BPS, MAKER_BPS = 5.0, 2.0
FIVE = ("LABUSDT", "SIRENUSDT", "HOMEUSDT", "SLXUSDT", "TRXUSDT")          # R89's five largest IC contributors, named in the registration
LATE_FROM = pd.Timestamp("2026-07-02", tz="UTC")
START = pd.Timestamp("2026-01-01", tz="UTC")


def decisions(fc: pd.DataFrame) -> pd.DataFrame:
    """The rule on a forecast table (t, symbol, f): per bar with n ≥ MIN_N forecasts, k = n // TENTH; buy the k highest, sell the k lowest."""
    d = fc[["t", "symbol", "f"]].dropna().sort_values(["t", "f", "symbol"], kind="mergesort").reset_index(drop=True)
    g = d.groupby("t", sort=False)
    n = g["f"].transform("size").to_numpy()
    lo = g.cumcount().to_numpy()                                           # 0 = the lowest forecast at the bar
    k = np.where(n >= MIN_N, n // TENTH, 0)
    side = np.where(lo < k, -1, np.where(lo >= n - k, 1, 0))
    d = d[side != 0].assign(side=side[side != 0], k=k[side != 0])
    return pd.DataFrame({"t": d["t"].to_numpy(), "symbol": d["symbol"].astype(str).to_numpy(), "side": d["side"].to_numpy(), "size": 1.0, "signal": d["f"].to_numpy(),
                         "why": "tenth", "hold": HOLD, "fold": "F5", "block": 0, "k": d["k"].to_numpy()}).sort_values(["t", "symbol"], kind="mergesort").reset_index(drop=True)


def verdict(net: float, se: float) -> str:
    if not (np.isfinite(net) and np.isfinite(se) and se > 0):
        return "NOT DETECTABLE"
    if net > 0 and net / se >= T_ONE_SIDED:
        return "CLEARS"
    return "FAILS" if net + 1.96 * se < 0 else "NOT DETECTABLE"


def row(label: str, fills: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    s = bt.summarize(fills, days, HOLD)
    return {"row": label, "trades": s["trades"], "a_day": round(s["trades_per_day"], 2), "hit": s["hit"], "gross": s["gross"], "fee": s["fee"], "other_cost": s["other_cost"],
            "funding": s["funding"], "net": s["net"], "se": s["net_se"], "t": s["net"] / s["net_se"] if s["net_se"] else np.nan, "lo": s["net_lo"], "hi": s["net_hi"],
            "hedged_net": s["hedged_net"], "usdt_a_day": s["net"] * s["trades_per_day"]}


def overlaps(fills: pd.DataFrame) -> int:
    """Positions of one coin entered before its previous one's exit."""
    f = fills.sort_values(["symbol", "entry_t"])
    prev = f.groupby("symbol")["exit_t"].shift()
    return int((f["entry_t"] < prev).sum())


def run(name: str = NAME, forecast: Path | str = FORECAST, registration: str = REG, expect: bool = True, old: set | None = None) -> str:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    conf = bt._guard(["F5"], registration)
    md5 = hashlib.md5(Path(forecast).read_bytes()).hexdigest()
    fc = pd.read_parquet(forecast)
    fc["t"] = pd.to_datetime(fc["t"], utc=True)
    end = folds.bounds("F5")[1]
    names = sorted(fc["symbol"].astype(str).unique())
    M = bt.market(names, end, START)
    dec = decisions(fc)
    per_bar = dec.groupby("t").agg(k=("k", "first"), longs=("side", lambda s: int((s > 0).sum())), shorts=("side", lambda s: int((s < 0).sum())))
    in_index = bool(dec["t"].isin(M.index).all())
    dec = bt.accept(dec[dec["t"].isin(M.index)].reset_index(drop=True), M.index, None)
    C = bt.load_costs(M.index, M.columns, end, 1.0, close=M.close)
    fills = bt.price(dec, M, C, "taker", TAKER_BPS, MAKER_BPS)
    acc = int(dec["accepted"].sum())
    in_span = fills["gross_bps"].notna()                                    # the exit bar inside the market
    v = {"registration": registration, "forecast_md5": md5, "forecast_as_registered": md5 == FORECAST_MD5 if expect else None, "forecast_cells": int(len(fc)), "names": len(names),
         "bars_with_decisions": int(len(per_bar)), "k_min": int(per_bar["k"].min()), "k_max": int(per_bar["k"].max()), "sides_equal_at_every_bar": bool((per_bar["longs"] == per_bar["shorts"]).all()),
         "decisions": int(len(dec)), "decisions_on_the_market_index": in_index, "accepted": acc, "skipped_position_open": int((dec["skip"] == "position_open").sum()),
         "share_skipped": float(1 - acc / max(len(dec), 1)), "accepted_with_the_exit_inside_the_market": int(in_span.sum()),
         "cost_rows_share": float(fills.loc[in_span, "other_cost_bps"].notna().mean()), "priced_share": float(fills.loc[in_span, "net_bps"].notna().mean()),
         "entry_after_decision": bool((fills["entry_t"] > fills["t"]).all()), "overlapping_positions": overlaps(fills[in_span]),
         "hold": HOLD, "taker_bps": TAKER_BPS, "maker_bps": MAKER_BPS, "t_one_sided": T_ONE_SIDED}
    v["status"] = "PASS" if (v["forecast_as_registered"] in (None, True) and in_index and v["cost_rows_share"] >= 0.99 and v["priced_share"] >= 0.95 and v["entry_after_decision"]
                             and 1 <= v["k_min"] and v["k_max"] <= 6 and v["sides_equal_at_every_bar"] and v["overlapping_positions"] == 0) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {registration} — R89's saved forecast as an hourly long-top-tenth / short-bottom-tenth book of F5's coins, one day a position (`ft2 allbook run`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {len(names)} coins · taker {TAKER_BPS:g} bps a side + the names' own spread and impact at 10,000 USDT · net in bps per trade (= USDT)\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "read.md").write_text("\n".join(head + ["\n**The read is VOID: no fill was summarised.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    days = bt.scored_days(["F5"], M.index[-1])
    fills = fills.merge(dec[["signal"]], left_on="id", right_index=True, how="left")
    fills.to_parquet(out / "fills.parquet", index=False)
    gate = row("the book, taker (the gate)", fills, days)
    gate["verdict"] = verdict(gate["net"], gate["se"])
    if old is None:
        old = set(universe.screen_symbols()) | set(universe.screen_symbols(universe.F34_MEMBERS_CSV))
    is_old, mth = fills["symbol"].isin(old), pd.DatetimeIndex(fills["t"]).strftime("%Y-%m")
    late = pd.DatetimeIndex(fills["t"]) >= LATE_FROM
    rows = [gate, row("long side", fills[fills["side"] > 0], days), row("short side", fills[fills["side"] < 0], days),
            row("coins that were members in F1–F4", fills[is_old], days), row("coins new in 2026", fills[~is_old], days),
            row("without " + ", ".join(s.replace("USDT", "") for s in FIVE), fills[~fills["symbol"].isin(FIVE)], days),
            row("the blocks before 2026-07-02", fills[~late], days), row("the blocks from 2026-07-02", fills[late], days),
            row("exec maker (bar-simulated; an estimate)", bt.price(dec, M, C, "maker", TAKER_BPS, MAKER_BPS), days),
            row("costs × 1.5 (taker)", bt.price(dec, M, bt.load_costs(M.index, M.columns, end, 1.5, close=M.close), "taker", TAKER_BPS, MAKER_BPS), days)]
    tab = pd.DataFrame(rows)
    tab["verdict"] = tab["verdict"].fillna("described")
    by_month = pd.DataFrame([row(m, fills[mth == m], days) for m in sorted(set(mth))]).drop(columns=["a_day", "usdt_a_day"])
    per_name = fills.groupby("symbol").agg(trades=("net_bps", "size"), net_sum=("net_bps", "sum"), gross_mean=("gross_bps", "mean"), cost_mean=("other_cost_bps", "mean")).sort_values("net_sum", ascending=False)
    tab.to_csv(out / "rows.csv", index=False)
    per_name.to_csv(out / "per_name.csv")
    (out / "validity.json").write_text(json.dumps({**v, "verdict": gate["verdict"], "net": gate["net"], "se": gate["se"], "t": gate["t"]}, indent=1, default=str))
    if conf:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "allbook tenth",
                      "params": json.dumps({"hold": HOLD, "tenth": TENTH, "forecast_md5": md5})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    show = lambda d, k=2: d.round(k).to_markdown(index=False)                    # noqa: E731
    md = head + [
        f"\n## The gate — **{gate['verdict']}**: net {gate['net']:+.1f} bps a trade (se {gate['se']:.1f}, t {gate['t']:+.2f}; [{gate['lo']:+.1f}, {gate['hi']:+.1f}]) on {gate['trades']:,} positions, "
        f"{gate['a_day']} a day; gross {gate['gross']:+.1f}, fee {gate['fee']:.1f}, other cost {gate['other_cost']:.1f}, funding {gate['funding']:+.1f}; {gate['usdt_a_day']:+.0f} USDT a day at 10,000 a position\n",
        show(tab), "\n", "\n## Described (decides nothing)\n", "\n### By month\n", show(by_month), "\n",
        "\n### The ten coins that earned most and the ten that lost most (net bps summed over their positions)\n", show(pd.concat([per_name.head(10), per_name.tail(10)]).reset_index(), 1), "\n"]
    (out / "read.md").write_text("\n".join(md))
    print(f"{registration}: {gate['verdict']} — net {gate['net']:+.1f} bps a trade (t {gate['t']:+.2f}); wrote {out}/", flush=True)
    return "\n".join(md)


def main(action: str, name: str | None = None) -> None:
    if action == "run":
        run(name or NAME)
