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
         "entry_after_decision": bool((fills.loc[in_span, "entry_t"] > fills.loc[in_span, "t"]).all()), "overlapping_positions": overlaps(fills[in_span]),
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
    elif action == "tapefetch":
        if name == NAME93:
            _guard93(REG93)
            tapefetch(fills=FILLS91, fills_md5=None, tape=TAPE93, strict=False)
        else:
            tapefetch()
    elif action == "tape":
        maker93() if name == NAME93 else tape_run(name or NAME92)


# ====================================================================================================================================
# R91 (docs/PLAN.md §8): the FORWARD test on F6 — the frozen trees' least-liked coins sold and HELD while they stay in the tail,
# funding-aware, hedged. The rule and its pricing are written here on 2026-11-11, after the registration's commit, and tested on
# planted bars only: the rule is NEVER run on F5's cells (R90's gate), and on F6 once, at the read (on or after 2027-03-18).
# ====================================================================================================================================
REG91, NAME91 = "R91", "r91"
F6_START, F6_END = pd.Timestamp("2026-09-17", tz="UTC"), pd.Timestamp("2027-03-16", tz="UTC")
FIFTH = 5
FUND_ENTRY, FUND_EXIT = -10.0, -30.0                         # bps a day: the last funding rate known at t × 24 / its interval hours
CAP_BARS = 7 * 288
HEDGE_BPS = 4.0
HALF = pd.Timedelta(days=90)
MODEL_MD5 = "816b994c136fda82eb36ceca88580d36"


def day_funding(fund: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per symbol: the funding events' stamps (ns, sorted) and each rate scaled to a day, bps."""
    f = fund.assign(symbol=fund["symbol"].astype(str), ts=pd.to_datetime(fund["ts"], utc=True)).sort_values(["symbol", "ts"])
    return {s: (pd.DatetimeIndex(g["ts"]).as_unit("ns").asi8, (g["rate"].to_numpy(float) * 1e4 * 24.0 / g["interval_h"].to_numpy(float)))
            for s, g in f.groupby("symbol", sort=False)}


def last_funding(F: dict, sym: str, t: pd.Timestamp) -> float:
    """The last funding rate stamped at or before t, bps a day; NaN when the coin has no row yet."""
    if sym not in F:
        return np.nan
    ts, r = F[sym]
    p = np.searchsorted(ts, pd.Timestamp(t).as_unit("ns").value, "right") - 1
    return float(r[p]) if p >= 0 else np.nan


def positions(fc: pd.DataFrame, fund: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """R91's rule on a forecast table (t, symbol, f; hourly bars): the SHORT positions (one row each: the entry bar t, the hold in 5m
    bars, the exit's clause in `why`) and the entries the funding floor skipped. Per bar, in the registration's order: (1) exits —
    no forecast, funding below FUND_EXIT, held CAP_BARS, out of the lowest ⌊n / FIFTH⌋ (when n ≥ MIN_N); (2) entries — the lowest
    ⌊n / TENTH⌋ without a position, unless the last funding is below FUND_ENTRY or absent. Positions open at the last bar close there."""
    d = fc[["t", "symbol", "f"]].dropna().assign(symbol=lambda x: x["symbol"].astype(str)).sort_values(["t", "f", "symbol"], kind="mergesort")
    F = day_funding(fund)
    open_: dict[str, tuple[pd.Timestamp, float]] = {}
    rows, skipped = [], []
    cap = pd.Timedelta(minutes=5 * CAP_BARS)

    def close(s, t, why):
        t0, f0 = open_.pop(s)
        rows.append({"t": t0, "symbol": s, "side": -1, "size": 1.0, "signal": f0, "why": why, "hold": int((t - t0) / pd.Timedelta(minutes=5)), "fold": "F6", "block": 0})
    t = None
    for t, g in d.groupby("t", sort=True):
        syms, fs = g["symbol"].tolist(), g["f"].tolist()
        n = len(syms)
        have = set(syms)
        fifth = set(syms[:n // FIFTH]) if n >= MIN_N else None
        for s in sorted(open_):
            fr = last_funding(F, s, t)
            if s not in have:
                close(s, t, "no_forecast")
            elif np.isfinite(fr) and fr < FUND_EXIT:
                close(s, t, "funding")
            elif t - open_[s][0] >= cap:
                close(s, t, "cap")
            elif fifth is not None and s not in fifth:
                close(s, t, "left_fifth")
        if n >= MIN_N:
            for s, f in zip(syms[:n // TENTH], fs[:n // TENTH]):
                if s in open_:
                    continue
                fr = last_funding(F, s, t)
                if not np.isfinite(fr) or fr < FUND_ENTRY:
                    skipped.append({"t": t, "symbol": s, "f": f, "funding_bps_day": fr, "why": "funding_floor" if np.isfinite(fr) else "no_funding_row"})
                    continue
                open_[s] = (t, f)
    for s in sorted(open_):
        close(s, t, "span_end")
    dec = pd.DataFrame(rows, columns=["t", "symbol", "side", "size", "signal", "why", "hold", "fold", "block"])
    dec = dec[dec["hold"] > 0].sort_values(["t", "symbol"], kind="mergesort").reset_index(drop=True)
    return dec.assign(accepted=True, skip=""), pd.DataFrame(skipped, columns=["t", "symbol", "f", "funding_bps_day", "why"])


def verdict91(mean: float, se: float, first: float, last: float) -> str:
    if not (np.isfinite(mean) and np.isfinite(se) and se > 0):
        return "NOT DETECTABLE"
    if mean > 0 and mean / se >= T_ONE_SIDED and first > 0 and last > 0:
        return "CLEARS"
    return "FAILS" if mean + 1.96 * se < 0 else "NOT DETECTABLE"


def _guard91(registration: str) -> None:
    import re
    if not bt.PLAN.exists() or not re.search(rf"^### {registration} ", bt.PLAN.read_text(), flags=re.M):
        raise SystemExit(f"no '### {registration} ' block in {bt.PLAN}: write the registration before the read")
    if pd.Timestamp.now("UTC") < F6_END:
        raise SystemExit(f"{registration} is read once, after F6's last bar ({F6_END:%Y-%m-%d}); a look is the read")
    r = pd.read_csv(bt.READS) if bt.READS.exists() else pd.DataFrame(columns=["registration", "fold"])
    if ((r["registration"] == registration) & (r["fold"] == "F6")).any():
        raise SystemExit(f"{registration} has already read F6 ({bt.READS}): a fold is read once per question")


def hedged_stats(fills: pd.DataFrame, days: pd.DatetimeIndex) -> dict:
    """The gate's statistic: the mean of (hedged net − HEDGE_BPS) per trade, day-clustered HAC with the 7-day cap's lags."""
    from .ceiling import day_lags
    f = fills.dropna(subset=["net_bps"])
    x = f["hedged_net_bps"].to_numpy() - HEDGE_BPS
    s = bt.trade_stats(x, f["size"].to_numpy(), pd.DatetimeIndex(f["t"]).floor("D"), days, day_lags(CAP_BARS))
    t = pd.DatetimeIndex(f["t"])
    mid = days[0] + HALF
    return {"trades": int(len(f)), "mean": s["mean"], "se": s["se"], "t": s["mean"] / s["se"] if s["se"] else np.nan, "lo": s["lo"], "hi": s["hi"],
            "first_half": float(x[t < mid].mean()) if (t < mid).any() else np.nan, "last_half": float(x[t >= mid].mean()) if (t >= mid).any() else np.nan}


def forward(forecast: Path | str, name: str = NAME91, registration: str = REG91, guard: bool = True, start: pd.Timestamp = F6_START, end: pd.Timestamp = F6_END) -> dict:
    """R91's read: the positions of the rule on the F6 forecast, priced as a taker with the names' own costs and funding, the hedged
    gate. Returns the gate's row; writes fills, the skipped entries, validity (3)–(4) and the verdict. The Data line, the member
    lists, the cover and the described rows are the read session's (PLAN §8 R91, Code)."""
    from . import data
    if guard:
        _guard91(registration)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    fc = pd.read_parquet(forecast)
    fc["t"] = pd.to_datetime(fc["t"], utc=True)
    fc = fc[(fc["t"] >= start) & (fc["t"] < end)]
    names = sorted(fc["symbol"].astype(str).unique())
    M = bt.market(names, end, start)
    fund = data.load("funding_archive", columns=["symbol", "ts", "rate", "interval_h"], symbols=names)
    dec, skipped = positions(fc, fund[pd.to_datetime(fund["ts"], utc=True) < end])
    skipped.to_csv(out / "skipped.csv", index=False)
    C = bt.load_costs(M.index, M.columns, end, 1.0, close=M.close)
    fills = bt.price(dec, M, C, "taker", TAKER_BPS, MAKER_BPS).merge(dec[["why", "hold", "signal"]], left_on="id", right_index=True, how="left")
    priced = fills["net_bps"].notna()
    v = {"registration": registration, "span": [str(start), str(end)], "names": len(names), "positions": int(len(dec)), "priced_share": float(priced.mean()) if len(fills) else 0.0,
         "overlapping_positions": overlaps(fills[priced]), "entry_after_decision": bool((fills.loc[priced, "entry_t"] > fills.loc[priced, "t"]).all()),
         "exits_by_clause": dec["why"].value_counts().to_dict(), "exits_unexplained": int((~dec["why"].isin(["no_forecast", "funding", "cap", "left_fifth", "span_end"])).sum()),
         "entries_skipped": skipped["why"].value_counts().to_dict(), "hold_bars_median": float(dec["hold"].median()) if len(dec) else np.nan,
         "share_at_the_cap": float((dec["why"] == "cap").mean()) if len(dec) else np.nan}
    v["status"] = "PASS" if (v["priced_share"] >= 0.95 and v["overlapping_positions"] == 0 and v["entry_after_decision"] and v["exits_unexplained"] == 0) else "FAIL"
    (out / "validity_book.json").write_text(json.dumps(v, indent=1, default=str))
    if v["status"] != "PASS":
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)
    days = pd.date_range(start, end - pd.Timedelta(1, "ns"), freq="D")
    fills.to_parquet(out / "fills.parquet", index=False)
    g = hedged_stats(fills, days)
    g["verdict"] = verdict91(g["mean"], g["se"], g["first_half"], g["last_half"])
    (out / "gate.json").write_text(json.dumps({**g, "validity": v}, indent=1, default=str))
    if guard:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": ["F6"], "strategy": "allbook short_held",
                      "params": json.dumps({"fifth": FIFTH, "tenth": TENTH, "fund_entry": FUND_ENTRY, "fund_exit": FUND_EXIT, "cap_bars": CAP_BARS, "hedge_bps": HEDGE_BPS})}).to_csv(
            bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    print(f"{registration}: {g['verdict']} — hedged net {g['mean']:+.1f} bps a trade (t {g['t']:+.2f}) on {g['trades']} positions; wrote {out}/", flush=True)
    return g


# ====================================================================================================================================
# R92 (docs/PLAN.md §8): the MAKER at the TRADE level on R90's book — every leg of the saved positions as a resting order at a price
# inferred from the archive's prints (no order book exists for these names), filled by THROUGH (a print strictly beyond the price: the
# headline, a lower bound on fills) or AT-TOUCH (THROUGH, or the prints at the price reach the order's own quantity: an empty queue).
# Nothing of the book is re-decided: the positions, sides, instants, funding and market move are R90's.
# ====================================================================================================================================
REG92, NAME92 = "R92", "r92"
FILLS90 = OUT / "r90" / "fills.parquet"
FILLS90_MD5 = "fa69150b0d2761b9360a26f4082fcbe4"
WAIT_NS = 15 * 60 * 10**9                                    # the harness's MAKER_WAIT of 3 bars
NOTIONAL = 10_000.0
TAPE = Path("data/r92_tape")
D_STANDS, D_KIND = -5.0, -15.0                               # the gate's cuts on THROUGH minus the bar-simulated maker, bps a trade
RULES = {"thr": "THROUGH", "at": "AT-TOUCH"}


def tape_legs(fills: pd.DataFrame, strict: bool = True) -> pd.DataFrame:
    """The two legs of every priced position: id, leg (e / x), symbol, s (the instant R90 priced), buy, bar_px (the close it priced), day.
    `strict` (R92): a leg whose 15 minutes cross midnight raises; R93 passes False and reads the flag `ok` (such a leg stays a taker leg)."""
    p = fills.dropna(subset=["net_bps"])
    sym, side = p["symbol"].astype(str).to_numpy(), p["side"].to_numpy()
    L = pd.concat([pd.DataFrame({"id": p["id"].to_numpy(), "leg": "e", "symbol": sym, "s": pd.DatetimeIndex(p["entry_t"]), "buy": side > 0, "bar_px": p["entry_px"].to_numpy()}),
                   pd.DataFrame({"id": p["id"].to_numpy(), "leg": "x", "symbol": sym, "s": pd.DatetimeIndex(p["exit_t"]), "buy": side < 0, "bar_px": p["exit_px"].to_numpy()})], ignore_index=True)
    L["day"] = L["s"].dt.floor("D")
    L["ok"] = (L["s"] + pd.Timedelta(WAIT_NS, "ns")).dt.floor("D") == L["day"]
    if strict and not L["ok"].all():
        raise ValueError("tape_legs: a leg's 15-minute window crosses midnight — one daily file a leg is the registration's reading")
    return L


def tape_touch(px: np.ndarray, sell: np.ndarray, a: int, buy: bool, tick: float) -> tuple[float, int]:
    """(the resting price, the index of the print it came from) from the first `a` prints (those before s). A buy: the last print whose
    aggressor sold, unless a buying print came after it at or below it (→ that price − a tick); no selling print → the last buying
    print − a tick. A sell is the mirror. (nan, −1) with no print."""
    if a <= 0:
        return np.nan, -1
    iS = np.flatnonzero(sell[:a])
    iB = np.flatnonzero(~sell[:a])
    iS, iB = (int(iS[-1]) if len(iS) else -1), (int(iB[-1]) if len(iB) else -1)
    if buy:
        if iS < 0 or (iB > iS and px[iB] <= px[iS]):
            return float(px[iB] - tick), iB
        return float(px[iS]), iS
    if iB < 0 or (iS > iB and px[iS] >= px[iB]):
        return float(px[iS] + tick), iS
    return float(px[iB]), iB


def tape_day(t: np.ndarray, px: np.ndarray, qty: np.ndarray, sell: np.ndarray, legs: pd.DataFrame) -> pd.DataFrame:
    """The fates of one name-day's legs. `t` the prints' stamps (ns, sorted), `sell` the aggressor sold; `legs` rows of `tape_legs`."""
    gaps = np.diff(np.unique(px))
    tick = float(gaps.min()) if len(gaps) else np.nan
    rows = []
    for g in legs.itertuples(index=False):
        s = pd.Timestamp(g.s).value
        a, b = int(np.searchsorted(t, s, "left")), int(np.searchsorted(t, s + WAIT_NS, "left"))
        P, src = tape_touch(px, sell, a, bool(g.buy), tick)
        row = {"id": g.id, "leg": g.leg, "symbol": g.symbol, "s": g.s, "buy": bool(g.buy), "prints_before": a, "prints_in_window": b - a, "tick": tick,
               "pre_px": float(px[a - 1]) if a > 0 else np.nan}
        if not (np.isfinite(P) and P > 0):
            rows.append({**row, "sim": False})
            continue
        wp, wq, ws = px[a:b], qty[a:b], sell[a:b]
        eps = 1e-9 * P
        beyond = np.flatnonzero(wp < P - eps) if g.buy else np.flatnonzero(wp > P + eps)
        at = (np.abs(wp - P) <= eps) & (ws if g.buy else ~ws)
        done = np.flatnonzero(np.cumsum(np.where(at, wq, 0.0)) >= NOTIONAL / P * (1 - 1e-12))
        i_thr = int(beyond[0]) if len(beyond) else -1
        cands = [i for i in (i_thr, int(done[0]) if len(done) else -1) if i >= 0]
        i_at = min(cands) if cands else -1
        # R93's volume rules: the OPPOSITE aggressor's quantity strictly beyond P (`vol`, the gate's: a fill no queue at P could have stopped) and
        # at or beyond P (`vola`, described) reaching the order's own
        opp = ws if g.buy else ~ws
        own = NOTIONAL / P * (1 - 1e-12)
        bey = opp & ((wp < P - eps) if g.buy else (wp > P + eps))
        atb = opp & ((wp <= P + eps) if g.buy else (wp >= P - eps))
        d_vol, d_vola = np.flatnonzero(np.cumsum(np.where(bey, wq, 0.0)) >= own), np.flatnonzero(np.cumsum(np.where(atb, wq, 0.0)) >= own)
        i_vol, i_vola = (int(d_vol[0]) if len(d_vol) else -1), (int(d_vola[0]) if len(d_vola) else -1)
        rows.append({**row, "sim": True, "P": P, "src_age_s": (s - int(t[src])) / 1e9, "cross_px": float(px[b - 1]),
                     "thr": i_thr >= 0, "thr_s": (int(t[a + i_thr]) - s) / 1e9 if i_thr >= 0 else np.nan,
                     "at": i_at >= 0, "at_s": (int(t[a + i_at]) - s) / 1e9 if i_at >= 0 else np.nan,
                     "vol": i_vol >= 0, "vol_s": (int(t[a + i_vol]) - s) / 1e9 if i_vol >= 0 else np.nan,
                     "vola": i_vola >= 0, "vola_s": (int(t[a + i_vola]) - s) / 1e9 if i_vola >= 0 else np.nan})
    return pd.DataFrame(rows)


def _tape_load(zp: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One aggTrades zip → (t ns sorted, price, qty, the aggressor sold). Files with and without a header line are read alike."""
    import zipfile
    cols = ["agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"]
    with zipfile.ZipFile(zp) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            head = f.readline().decode()
        with z.open(name) as f:
            d = pd.read_csv(f, header=0 if not head[:1].isdigit() else None, names=cols, usecols=["price", "quantity", "transact_time", "is_buyer_maker"],
                            dtype={"price": float, "quantity": float, "transact_time": "int64"})
    t = d["transact_time"].to_numpy() * 1_000_000
    o = np.argsort(t, kind="stable")
    sell = d["is_buyer_maker"].astype(str).str.lower().isin(["true", "1"]).to_numpy()
    return t[o], d["price"].to_numpy()[o], d["quantity"].to_numpy()[o], sell[o]


def tapefetch(workers: int = 6, fills: Path | None = None, fills_md5: str | None = "r92", tape: Path | None = None, strict: bool = True) -> dict:
    """The VM's fetch-and-simulate, resumable: per name-day holding a leg, the archive's aggTrades zip (checksum verified), the legs'
    fates → <tape>/<SYM>/<day>.parquet, the zip deleted (its sha256 in the rows). A name-day without a file stays absent. The defaults are
    R92's (R90's fills, their registered md5, data/r92_tape); R93 passes R91's fills, no md5 (they are made in the read's session), its own
    folder and `strict` False (a leg whose window crosses midnight is left out: it stays a taker leg)."""
    from concurrent.futures import ThreadPoolExecutor
    from . import archive
    fills, tape = fills or FILLS90, tape or TAPE
    fills_md5 = FILLS90_MD5 if fills_md5 == "r92" else fills_md5
    if fills_md5 is not None and hashlib.md5(Path(fills).read_bytes()).hexdigest() != fills_md5:
        raise SystemExit(f"{fills}: not the fills R92 registered")
    L = tape_legs(pd.read_parquet(fills), strict)
    L = L[L["ok"]]
    jobs = [(s, d, g) for (s, d), g in L.groupby(["symbol", "day"], sort=True)]

    def one(job) -> str:
        sym, day, g = job
        dest = tape / sym / f"{day:%Y-%m-%d}.parquet"
        if dest.exists():
            return "skip"
        name = f"{sym}-aggTrades-{day:%Y-%m-%d}.zip"
        zp = archive.ROOT / "aggTrades" / sym / name
        st = archive._fetch(f"data/futures/um/daily/aggTrades/{sym}/{name}", zp)
        if st in ("err", "bad"):
            return st
        try:
            out = tape_day(*_tape_load(zp), g)
        except Exception as e:  # noqa: BLE001
            print(f"  parse {name}: {e!r}", flush=True)
            return "parse"
        out["sha256"] = archive._sha256(zp)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        out.to_parquet(tmp, index=False)
        tmp.replace(dest)
        zp.unlink(missing_ok=True)
        zp.with_suffix(".zip.ok").unlink(missing_ok=True)
        return "ok"

    counts = {"ok": 0, "skip": 0, "err": 0, "bad": 0, "parse": 0}
    print(f"tapefetch: {len(jobs)} name-days, {len(L)} legs…", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for n, st in enumerate(ex.map(one, jobs), 1):
            counts[st] += 1
            if n % 250 == 0:
                print(f"  {n}/{len(jobs)} {counts}", flush=True)
    print(f"tapefetch: {counts}", flush=True)
    return counts


def reprice(f: pd.DataFrame, pe: np.ndarray, px: np.ndarray, fee_e: np.ndarray, fee_x: np.ndarray, oth_e: np.ndarray, oth_x: np.ndarray) -> pd.DataFrame:
    """`backtest.price`'s arithmetic on given leg prices, fees and other costs; the funding and the market move stay the fills' own."""
    s, mkt = f["side"].to_numpy(float), f["mkt_bps"].to_numpy()
    r = px / pe
    out = f.copy()
    out["entry_px"], out["exit_px"] = pe, px
    out["gross_bps"] = s * (r - 1.0) * 1e4
    out["fee_bps"], out["other_cost_bps"] = fee_e + fee_x * r, oth_e + oth_x * r
    out["hedged_bps"] = out["gross_bps"] - s * mkt
    out["net_bps"] = out["gross_bps"] - out["fee_bps"] - out["other_cost_bps"] + out["funding_bps"]
    out["hedged_net_bps"] = out["net_bps"] - s * mkt
    return out


def verdict92(n: float, d: float) -> str:
    if not (np.isfinite(n) and np.isfinite(d)):
        return "NOT READ"
    if d < D_KIND or n < 0:
        return "THE MAKER PATH IS CLOSED AT THIS RULE"
    return "TOO KIND" if d < D_STANDS else "THE ESTIMATE STANDS"


def tape_run(name: str = NAME92, registration: str = REG92) -> str:
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    conf = bt._guard(["F5"], registration)
    md5 = hashlib.md5(FILLS90.read_bytes()).hexdigest()
    saved = pd.read_parquet(FILLS90)
    fc = pd.read_parquet(FORECAST)
    fc["t"] = pd.to_datetime(fc["t"], utc=True)
    end = folds.bounds("F5")[1]
    M = bt.market(sorted(fc["symbol"].astype(str).unique()), end, START)
    dec = decisions(fc)
    dec = bt.accept(dec[dec["t"].isin(M.index)].reset_index(drop=True), M.index, None)
    C = bt.load_costs(M.index, M.columns, end, 1.0, close=M.close)
    tk = bt.price(dec, M, C, "taker", TAKER_BPS, MAKER_BPS)
    same = bool(len(tk) == len(saved) and (tk["id"].to_numpy() == saved["id"].to_numpy()).all() and (tk["side"].to_numpy() == saved["side"].to_numpy()).all()
                and (pd.DatetimeIndex(tk["entry_t"]) == pd.DatetimeIndex(saved["entry_t"])).all() and (pd.DatetimeIndex(tk["exit_t"]) == pd.DatetimeIndex(saved["exit_t"])).all()
                and np.allclose(tk["net_bps"].to_numpy(), saved["net_bps"].to_numpy(), rtol=0, atol=1e-6, equal_nan=True))
    f = saved.dropna(subset=["net_bps"]).reset_index(drop=True)
    L = tape_legs(saved)
    files = sorted(TAPE.glob("*/*.parquet"))
    R = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True) if files else pd.DataFrame(columns=["id", "leg", "sim"])
    for c in ("P", "cross_px", "src_age_s", "thr", "at", "thr_s", "at_s"):
        if c not in R:
            R[c] = np.nan
    L = L.merge(R.drop(columns=[c for c in ("symbol", "s", "buy") if c in R]), on=["id", "leg"], how="left")
    has = L["sim"].notna()
    L["sim"] = L["sim"].fillna(False).astype(bool)
    nd = L.drop_duplicates(["symbol", "day"])
    clock = (L.loc[has, "pre_px"] - L.loc[has, "bar_px"]).abs() <= 1e-9 * L.loc[has, "bar_px"].abs()
    # the taker legs' other cost, as backtest.price picks it: the day of the leg's instant
    j = M.columns.get_indexer(f["symbol"])
    def oth(ts):
        dpos = C.days.get_indexer(pd.DatetimeIndex(ts).floor("D"))
        return np.where(dpos >= 0, C.taker_leg[np.maximum(dpos, 0), j], np.nan)
    oe, ox = oth(f["entry_t"]), oth(f["exit_t"])
    five = np.full(len(f), TAKER_BPS)
    arith = reprice(f, f["entry_px"].to_numpy(), f["exit_px"].to_numpy(), five, five, oe, ox)
    d_arith = float(np.abs(arith["net_bps"].to_numpy() - f["net_bps"].to_numpy()).max())
    E, X = (L[L["leg"] == k].set_index("id").reindex(f["id"]) for k in ("e", "x"))
    both = (E["sim"].to_numpy(bool)) & (X["sim"].to_numpy(bool))
    v = {"registration": registration, "fills_md5": md5, "fills_as_registered": md5 == FILLS90_MD5, "decisions_rebuilt_identical": same, "positions": int(len(f)), "legs": int(len(L)),
         "name_days": int(len(nd)), "name_days_with_a_file": int(has[nd.index].sum()), "files_share": float(has[nd.index].mean()),
         "legs_with_a_file": int(has.sum()), "clock_share": float(clock.mean()) if has.any() else 0.0, "arithmetic_max_abs_diff": d_arith,
         "both_legs_simulated": int(both.sum()), "both_share": float(both.mean()), "wait_min": 15, "notional": NOTIONAL}
    v["status"] = "PASS" if (v["fills_as_registered"] and same and v["files_share"] >= 0.99 and v["clock_share"] >= 0.99 and d_arith <= 1e-6 and v["both_share"] >= 0.98) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    head = [f"# {registration} — the maker at the trade level on R90's book (`ft2 allbook tape`)\n",
            f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · R90's {len(f):,} priced positions · each leg a resting order at a price inferred from the prints, 15 minutes, then crossing · net in bps per trade (= USDT)\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n"]
    if v["status"] != "PASS":
        (out / "read.md").write_text("\n".join(head + ["\n**The read is VOID: no leg was summarised.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    days = bt.scored_days(["F5"], M.index[-1])
    fb, oe, ox, E, X = f[both].reset_index(drop=True), oe[both], ox[both], E[both], X[both]
    mk = bt.price(dec, M, C, "maker", TAKER_BPS, MAKER_BPS).set_index("id").reindex(fb["id"]).reset_index()
    books = {"taker (R90's gate, the same positions)": fb, "maker, bar-simulated (R90's estimate, the same positions)": mk}
    for k, lab in RULES.items():
        fe, fx = E[k].to_numpy(bool), X[k].to_numpy(bool)
        books[f"maker at the trade level, {lab}"] = reprice(fb, np.where(fe, E["P"].to_numpy(), E["cross_px"].to_numpy()), np.where(fx, X["P"].to_numpy(), X["cross_px"].to_numpy()),
                                                           np.where(fe, MAKER_BPS, TAKER_BPS), np.where(fx, MAKER_BPS, TAKER_BPS), np.where(fe, 0.0, oe), np.where(fx, 0.0, ox))
    labs = list(books)
    tab = pd.DataFrame([row(k, b, days) for k, b in books.items()])
    thr, bar = books[labs[2]], books[labs[1]]
    from .ceiling import day_lags
    ds = bt.trade_stats(thr["net_bps"].to_numpy() - bar["net_bps"].to_numpy(), fb["size"].to_numpy(), pd.DatetimeIndex(fb["t"]).floor("D"), days, day_lags(HOLD))
    n_thr = float(tab.loc[2, "net"])
    gate = {"N": n_thr, "se": float(tab.loc[2, "se"]), "t": float(tab.loc[2, "t"]), "D": ds["mean"], "D_se": ds["se"], "bar_maker": float(tab.loc[1, "net"]), "taker": float(tab.loc[0, "net"]),
            "at_touch": float(tab.loc[3, "net"]), "sentence": verdict92(n_thr, ds["mean"]), "r90_words": verdict(n_thr, float(tab.loc[2, "se"]))}
    # described
    Lb = L[L["id"].isin(fb["id"])].copy()
    Lb["kind"] = np.where(Lb["leg"] == "e", "entry", "exit") + np.where(Lb["buy"], " buy", " sell")
    sgn = np.where(Lb["buy"], 1.0, -1.0)
    Lb["better_than_close_bps"] = sgn * (Lb["bar_px"] - Lb["P"]) / Lb["bar_px"] * 1e4       # positive: the resting price is better than the bar's close
    Lb["drift15_bps"] = sgn * (Lb["cross_px"] - Lb["P"]) / Lb["P"] * 1e4                    # negative: the price 15 minutes on is against the filled order
    def legrow(lab, g):
        r = {"legs": lab, "n": int(len(g))}
        for k in RULES:
            fl = g[k].astype(bool)
            r |= {f"{k}_fill": float(fl.mean()), f"{k}_better": float(g.loc[fl, "better_than_close_bps"].mean()), f"{k}_drift15": float(g.loc[fl, "drift15_bps"].mean()),
                  f"{k}_fill_s_median": float(g.loc[fl, f"{k}_s"].median())}
        return r | {"unfilled_thr_drift15": float(g.loc[~g["thr"].astype(bool), "drift15_bps"].mean()), "src_age_s_median": float(g["src_age_s"].median()), "src_age_s_p90": float(g["src_age_s"].quantile(0.9))}
    legs_tab = pd.DataFrame([legrow("all", Lb)] + [legrow(k, g) for k, g in Lb.groupby("kind")])
    old = set(universe.screen_symbols()) | set(universe.screen_symbols(universe.F34_MEMBERS_CSV))
    is_old, mth = thr["symbol"].isin(old), pd.DatetimeIndex(thr["t"]).strftime("%Y-%m")
    at_ = books[labs[3]]
    splits = pd.DataFrame([row("THROUGH: long side", thr[thr["side"] > 0], days), row("THROUGH: short side", thr[thr["side"] < 0], days),
                           row("THROUGH: coins that were members in F1–F4", thr[is_old], days), row("THROUGH: coins new in 2026", thr[~is_old], days),
                           row("AT-TOUCH: long side", at_[at_["side"] > 0], days), row("AT-TOUCH: short side", at_[at_["side"] < 0], days),
                           row("bar-simulated: short side", bar[bar["side"] < 0], days)])
    by_month = pd.DataFrame([row(m, thr[mth == m], days) for m in sorted(set(mth))]).drop(columns=["a_day", "usdt_a_day"])
    tab.to_csv(out / "rows.csv", index=False)
    splits.to_csv(out / "splits.csv", index=False)
    legs_tab.to_csv(out / "legs.csv", index=False)
    L.to_parquet(out / "legs.parquet", index=False)
    thr.to_parquet(out / "fills_through.parquet", index=False)
    (out / "validity.json").write_text(json.dumps({**v, "gate": gate}, indent=1, default=str))
    if conf:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "allbook tenth maker_tape",
                      "params": json.dumps({"wait_min": 15, "fills_md5": md5})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    show = lambda d, k=2: d.round(k).to_markdown(index=False)                    # noqa: E731
    md = head + [
        f"\n## The gate — **{gate['sentence']}**: THROUGH nets {gate['N']:+.1f} bps a trade (se {gate['se']:.1f}, t {gate['t']:+.2f}; R90's words: {gate['r90_words']}) against the bar-simulated maker's "
        f"{gate['bar_maker']:+.1f} on the same {len(fb):,} positions: D = {gate['D']:+.1f} (paired se {gate['D_se']:.1f}); AT-TOUCH {gate['at_touch']:+.1f}; the taker {gate['taker']:+.1f}\n",
        show(tab), "\n", "\n## Described (decides nothing)\n", "\n### The legs: fill share, the filled price against the bar's close (bps, + = better), the price 15 minutes on against a filled order (− = adverse)\n",
        show(legs_tab), "\n", "\n### Splits\n", show(splits), "\n", "\n### THROUGH by month\n", show(by_month), "\n"]
    (out / "read.md").write_text("\n".join(md))
    print(f"{registration}: {gate['sentence']} — THROUGH {gate['N']:+.1f} (t {gate['t']:+.2f}), D {gate['D']:+.1f}, AT-TOUCH {gate['at_touch']:+.1f}; wrote {out}/", flush=True)
    return "\n".join(md)


# ====================================================================================================================================
# R93 (docs/PLAN.md §8): the MAKER execution of R91's forward rule on F6 — R91's positions unchanged, every leg a resting order by R92's
# method, the gate's fill rule VOLUME-BEYOND (the opposite aggressor's quantity STRICTLY beyond the resting price reaching the order's own:
# a fill no queue at the price could have stopped). Written 2026-11-13 after the registration's commit and tested on planted prints only;
# read once, in R91's session, after `forward` has written R91's fills and its ledger row.
# ====================================================================================================================================
REG93, NAME93 = "R93", "r93"
FILLS91 = OUT / NAME91 / "fills.parquet"
TAPE93 = Path("data/r93_tape")
RULES93 = {"vol": "VOLUME-BEYOND (the gate)", "vola": "VOLUME-AT", "thr": "THROUGH", "at": "AT-TOUCH"}
MIN_BOTH93 = 0.95


def _guard93(registration: str = REG93) -> None:
    import re
    if not bt.PLAN.exists() or not re.search(rf"^### {registration} ", bt.PLAN.read_text(), flags=re.M):
        raise SystemExit(f"no '### {registration} ' block in {bt.PLAN}: write the registration before the read")
    if pd.Timestamp.now("UTC") < F6_END:
        raise SystemExit(f"{registration} is read once, after F6's last bar ({F6_END:%Y-%m-%d}); a look is the read")
    r = pd.read_csv(bt.READS) if bt.READS.exists() else pd.DataFrame(columns=["registration", "fold"])
    if ((r["registration"] == registration) & (r["fold"] == "F6")).any():
        raise SystemExit(f"{registration} has already read F6 ({bt.READS}): a fold is read once per question")
    if not ((r["registration"] == REG91) & (r["fold"] == "F6")).any():
        raise SystemExit(f"{registration} is read after {REG91}'s gate is written: no ({REG91}, F6) row in {bt.READS}")


def maker_books(f: pd.DataFrame, L: pd.DataFrame, oe: np.ndarray, ox: np.ndarray) -> dict[str, pd.DataFrame]:
    """R91's priced fills `f` re-priced per fill rule from the legs' fates `L` (rows of `tape_legs` merged with `tape_day`'s columns; `sim`
    False = not simulated). A filled leg: the resting price, the maker fee, no other cost; a simulated leg not filled: the last print of
    its window, the taker fee and the coin's taker leg (`oe` / `ox`); a leg NOT simulated: R91's own taker leg at R91's price."""
    E, X = (L[L["leg"] == k].set_index("id").reindex(f["id"]) for k in ("e", "x"))
    se, sx = E["sim"].eq(True).to_numpy(), X["sim"].eq(True).to_numpy()
    pe0, px0 = f["entry_px"].to_numpy(float), f["exit_px"].to_numpy(float)
    out = {}
    for k in RULES93:
        fe, fx = se & E[k].eq(True).to_numpy(), sx & X[k].eq(True).to_numpy()
        pe = np.where(fe, E["P"].to_numpy(float), np.where(se, E["cross_px"].to_numpy(float), pe0))
        px = np.where(fx, X["P"].to_numpy(float), np.where(sx, X["cross_px"].to_numpy(float), px0))
        out[k] = reprice(f, pe, px, np.where(fe, MAKER_BPS, TAKER_BPS), np.where(fx, MAKER_BPS, TAKER_BPS), np.where(fe, 0.0, oe), np.where(fx, 0.0, ox)).assign(fill_e=fe, fill_x=fx)
    return out


def maker93(name: str = NAME93, registration: str = REG93, guard: bool = True) -> dict:
    """R93's read: validity, the gate (R91's form on the VOLUME-BEYOND fills), the ledger row, the rule rows. The other described rows
    (the bar-simulated maker, the leg table, the coins' split) are the read session's, from `legs.parquet` and the saved books."""
    if guard:
        _guard93(registration)
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    v91 = json.loads((OUT / NAME91 / "validity_book.json").read_text())
    md5 = hashlib.md5(FILLS91.read_bytes()).hexdigest()
    saved = pd.read_parquet(FILLS91)
    f = saved.dropna(subset=["net_bps"]).reset_index(drop=True)
    names = sorted(f["symbol"].astype(str).unique())
    M = bt.market(names, F6_END, F6_START)
    C = bt.load_costs(M.index, M.columns, F6_END, 1.0, close=M.close)
    L = tape_legs(saved, strict=False)
    files = sorted(TAPE93.glob("*/*.parquet"))
    R = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True) if files else pd.DataFrame(columns=["id", "leg", "sim"])
    for c in ("P", "cross_px", "src_age_s", "pre_px", *RULES93, *(f"{k}_s" for k in RULES93)):
        if c not in R:
            R[c] = np.nan
    L = L.merge(R.drop(columns=[c for c in ("symbol", "s", "buy") if c in R]), on=["id", "leg"], how="left")
    has = L["sim"].notna()
    L["why_taker"] = np.where(~L["ok"], "the window crosses midnight", np.where(~has, "no file", np.where(~L["sim"].eq(True), "no print before s", "")))
    L["sim"] = L["sim"].eq(True) & L["ok"]
    nd = L[L["ok"]].drop_duplicates(["symbol", "day"])
    clock = (L.loc[has, "pre_px"] - L.loc[has, "bar_px"]).abs() <= 1e-9 * L.loc[has, "bar_px"].abs()
    j = M.columns.get_indexer(f["symbol"])

    def oth(ts):
        dpos = C.days.get_indexer(pd.DatetimeIndex(ts).floor("D"))
        return np.where(dpos >= 0, C.taker_leg[np.maximum(dpos, 0), j], np.nan)
    oe, ox = oth(f["entry_t"]), oth(f["exit_t"])
    five = np.full(len(f), TAKER_BPS)
    d_arith = float(np.abs(reprice(f, f["entry_px"].to_numpy(), f["exit_px"].to_numpy(), five, five, oe, ox)["net_bps"].to_numpy() - f["net_bps"].to_numpy()).max()) if len(f) else np.inf
    E, X = (L[L["leg"] == k].set_index("id").reindex(f["id"]) for k in ("e", "x"))
    both = E["sim"].to_numpy(bool) & X["sim"].to_numpy(bool)
    v = {"registration": registration, "r91_validity": v91.get("status"), "r91_fills_md5": md5, "positions": int(len(f)), "legs": int(len(L)), "name_days": int(len(nd)),
         "files_share": float(has[nd.index].mean()) if len(nd) else 0.0, "clock_share": float(clock.mean()) if has.any() else 0.0, "arithmetic_max_abs_diff": d_arith,
         "both_legs_simulated": int(both.sum()), "both_share": float(both.mean()) if len(f) else 0.0, "taker_legs_by_reason": L.loc[L["why_taker"] != "", "why_taker"].value_counts().to_dict(),
         "wait_min": 15, "notional": NOTIONAL}
    v["status"] = "PASS" if (v["r91_validity"] == "PASS" and v["files_share"] >= 0.99 and v["clock_share"] >= 0.99 and d_arith <= 1e-6 and v["both_share"] >= MIN_BOTH93) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1, default=str))
    if v["status"] != "PASS":
        (out / "read.md").write_text(f"# {registration}\n\n## Validity: FAIL\n\n```\n{json.dumps(v, indent=1, default=str)}\n```\n\n**The read is VOID: no leg was summarised.**\n")
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)
    days = pd.date_range(F6_START, F6_END - pd.Timedelta(1, "ns"), freq="D")
    books = maker_books(f, L, oe, ox)
    rows = []
    for k, b in {"taker": f, **books}.items():
        rows.append({"row": "R91's taker (its gate, beside)" if k == "taker" else RULES93[k], **hedged_stats(b, days), "net_unhedged": float(b["net_bps"].mean()), "gross": float(b["gross_bps"].mean()),
                     "fee": float(b["fee_bps"].mean()), "other_cost": float(b["other_cost_bps"].mean()), "funding": float(b["funding_bps"].mean()),
                     "fill_e": float(b["fill_e"].mean()) if "fill_e" in b else 0.0, "fill_x": float(b["fill_x"].mean()) if "fill_x" in b else 0.0})
    tab = pd.DataFrame(rows)
    g = dict(rows[1])
    g["verdict"] = verdict91(g["mean"], g["se"], g["first_half"], g["last_half"])
    tab.to_csv(out / "rows.csv", index=False)
    L.to_parquet(out / "legs.parquet", index=False)
    books["vol"].to_parquet(out / "fills_volume.parquet", index=False)
    (out / "gate.json").write_text(json.dumps({**g, "validity": v}, indent=1, default=str))
    if guard:
        bt.READS.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": ["F6"], "strategy": "allbook short_held maker_volume",
                      "params": json.dumps({"wait_min": 15, "rule": "volume_beyond", "r91_fills_md5": md5})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    mth = pd.DatetimeIndex(books["vol"]["t"]).strftime("%Y-%m")
    by_month = pd.DataFrame([{"month": m, **hedged_stats(books["vol"][mth == m], days)} for m in sorted(set(mth))])
    md = [f"# {registration} — the maker execution of R91's rule on F6 (`ft2 allbook tape --name r93`)\n", f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1, default=str), "\n```\n",
          f"\n## The gate — **{g['verdict']}**: hedged net − {HEDGE_BPS:g} = {g['mean']:+.1f} bps a trade (se {g['se']:.1f}, t {g['t']:+.2f}; halves {g['first_half']:+.1f} / {g['last_half']:+.1f}) on {g['trades']} positions, VOLUME-BEYOND\n",
          tab.round(2).to_markdown(index=False), "\n", "\n## Described (decides nothing): VOLUME-BEYOND by month\n", by_month.round(2).to_markdown(index=False), "\n"]
    (out / "read.md").write_text("\n".join(md))
    print(f"{registration}: {g['verdict']} — hedged net {g['mean']:+.1f} bps a trade (t {g['t']:+.2f}); wrote {out}/", flush=True)
    return g
