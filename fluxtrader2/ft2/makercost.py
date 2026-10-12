"""R39 — the maker cost at the TRADE level on the twelve (PLAN §8 R39): a 10,000-USDT order resting at the touch, last in its level's queue,
filled FIFO by the trades that follow, the drift after the fill — against P1's minute-level numbers and the harness's bar-level maker.

`ft2 makercost --start 2026-08-15 --end 2026-08-28` → output/makercost/<start>_<end>/

inputs      the archive's daily aggTrades zips (`ft2 archive aggTrades …`; `data/raw/external/binance/aggTrades/<SYM>/<SYM>-aggTrades-<day>.zip`:
            price, quantity, transact_time (ms, the exchange's clock), is_buyer_maker — true: the aggressor SOLD into the bid);
            the raw ladder exports (`data/raw/levels/<day>/levels.csv.gz`: symbol, ts, …, bids, asks as JSON [[price, qty], …] best first) for
            the touch's price AND quantity per ~12-s snapshot; `data/ladder/<SYM>.parquet` for the mid and the slippage of a 10,000-USDT
            market order (`slip_buy_10000`, `slip_sell_10000`, bps of mid incl. the half-spread) at the crossing instant; the tape parts
            (`data/tape/parts/<SYM>/<day>.parquet`) for the validity reproduction; `data/cost_daily.parquet` for P1's day numbers; the 5m
            candles for the harness's maker on the same placements.
placement   every 5-minute bar close s of the window, both sides: a BUY at the best bid P_b(s), a SELL at the best ask P_a(s), from the last
            snapshot with ts ≤ s (none within SNAP_MAX_AGE → the placement is skipped and counted); q = NOTIONAL / P; Q0 = the quantity
            already at the level (FIFO: the order is last; cancellations ahead are unobservable → the fill share is a lower bound).
fill        the first trade time t in (s, s + WAIT] at which (a) the cumulative quantity of same-side trades AT P (a buy: is_buyer_maker true
            at P_b) reaches Q0 + q, or (b) a trade prints beyond the level (a buy: below P_b). Partial = (a)'s cumulative ≥ Q0 but < Q0 + q.
cost        filled: MAKER_BPS − adv, adv = (mid(s + WAIT) − P) / P × 1e4 for a buy ((P − mid) / P for a sell; negative = bad for the maker);
            unfilled: TAKER_BPS + slip_<side>_10000 at s + WAIT (the crossing), the MISSED MOVE (the mid's move against the order since s)
            reported apart. Effective round trip = 2 × the mean leg cost. The harness's maker on the same instants: rest at the 5m CLOSE at
            s, fill if a later bar's low (high) trades strictly through within MAKER_WAIT bars; else cross at the close 3 bars on.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive, data
from .backtest import MAKER_WAIT
from .ceiling import BAR

OUT = Path("output/makercost")
NOTIONAL = 10_000
WAIT = pd.Timedelta("15min")
STEP = pd.Timedelta("5min")
SNAP_MAX_AGE = pd.Timedelta("60s")
TAKER_BPS, MAKER_BPS = 5.0, 2.0
COVER_BAR = 0.95
TOL = 1e-6
FIRST = re.compile(r"^\s*\[\s*\[\s*\"?([0-9.eE+-]+)\"?\s*,\s*\"?([0-9.eE+-]+)\"?")   # the first [price, qty] of a JSON ladder


# ---- inputs -------------------------------------------------------------------------------------------------------------------------------
def trades_file(sym: str, day: pd.Timestamp) -> Path:
    return archive.ROOT / "aggTrades" / sym / f"{sym}-aggTrades-{day:%Y-%m-%d}.zip"


def load_trades(sym: str, day: pd.Timestamp) -> pd.DataFrame:
    """One name-day's trades: t (ns, UTC), price, qty, sell (the aggressor sold)."""
    with zipfile.ZipFile(trades_file(sym, day)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            d = pd.read_csv(f, usecols=["price", "quantity", "transact_time", "is_buyer_maker"], dtype={"price": float, "quantity": float, "transact_time": "int64"})
    sell = d["is_buyer_maker"].astype(str).str.lower().isin(["true", "1"]).to_numpy()
    return pd.DataFrame({"t": pd.to_datetime(d["transact_time"].to_numpy(), unit="ms", utc=True), "price": d["price"].to_numpy(), "qty": d["quantity"].to_numpy(), "sell": sell})


def load_touch(day: pd.Timestamp, symbols: list[str], src: Path | None = None, chunksize: int = 50_000) -> pd.DataFrame:
    """The touch per snapshot of one day's raw ladder export: symbol, ts, bid, bid_qty, ask, ask_qty."""
    src = src or data.RAW / "levels" / f"{day:%Y-%m-%d}" / "levels.csv.gz"
    out = []
    for chunk in pd.read_csv(src, usecols=["symbol", "ts", "bids", "asks"], chunksize=chunksize, dtype={"bids": str, "asks": str}):
        chunk = chunk[chunk["symbol"].isin(symbols)]
        if chunk.empty:
            continue
        def first(col):
            m = [FIRST.match(x) if isinstance(x, str) else None for x in chunk[col].to_numpy()]
            return np.array([float(g.group(1)) if g else np.nan for g in m]), np.array([float(g.group(2)) if g else np.nan for g in m])
        bp, bq = first("bids")
        ap, aq = first("asks")
        out.append(pd.DataFrame({"symbol": chunk["symbol"].to_numpy(), "ts": pd.to_datetime(chunk["ts"].to_numpy(), utc=True, format="ISO8601"),
                                 "bid": bp, "bid_qty": bq, "ask": ap, "ask_qty": aq}))
    if not out:
        return pd.DataFrame(columns=["symbol", "ts", "bid", "bid_qty", "ask", "ask_qty"])
    return pd.concat(out, ignore_index=True).sort_values(["symbol", "ts"]).reset_index(drop=True)


# ---- the fill ------------------------------------------------------------------------------------------------------------------------------
def fill_time(t: np.ndarray, price: np.ndarray, qty: np.ndarray, sell: np.ndarray, side: str, P: float, Q0: float, q: float) -> tuple[int, bool, float]:
    """(the index of the filling trade or −1, partial, the same-side quantity traded at the level) for an order of `q` at `P` with `Q0`
    ahead of it, over the trades given (time-ordered, all after the placement). A buy fills when sells at P reach Q0 + q or a trade prints
    below P; a sell when buys at P reach Q0 + q or a trade prints above P."""
    at = np.abs(price - P) <= 1e-9 * abs(P)
    same = at & (sell if side == "buy" else ~sell)
    cum = np.cumsum(np.where(same, qty, 0.0))
    done = np.flatnonzero(cum >= Q0 + q)
    beyond = np.flatnonzero(price < P - 1e-9 * abs(P)) if side == "buy" else np.flatnonzero(price > P + 1e-9 * abs(P))
    cands = ([int(done[0])] if len(done) else []) + ([int(beyond[0])] if len(beyond) else [])
    i = min(cands) if cands else -1
    traded = float(cum[-1]) if len(cum) else 0.0
    return i, bool(i < 0 and traded >= Q0), traded


def placements(sym: str, touch: pd.DataFrame, lad: pd.DataFrame, tr: pd.DataFrame, candles: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    """Every 5m bar close of `day`, both sides: the resting order's fate. `touch` the day's snapshots of this name (ts, bid, bid_qty, ask,
    ask_qty), `lad` the ladder parquet rows of this name (ts, mid, slip_buy_10000, slip_sell_10000), `tr` the day's trades plus the first
    WAIT of the next day, `candles` the 5m closes/highs/lows of this name."""
    grid = pd.date_range(day, day + pd.Timedelta(days=1) - STEP, freq=STEP)
    tt = tr["t"].astype("int64").to_numpy(); px, qq, sl = tr["price"].to_numpy(), tr["qty"].to_numpy(), tr["sell"].to_numpy()
    sts = touch["ts"].astype("int64").to_numpy(); lts = lad["ts"].astype("int64").to_numpy()      # UTC ns: the searches below
    cl, lo, hi = (candles[c].reindex(grid.union(candles.index)).to_numpy() for c in ("close", "low", "high"))
    cidx = grid.union(candles.index)
    rows = []
    for s in grid:
        i = int(np.searchsorted(sts, s.value, "right")) - 1
        age = (s - touch["ts"].iloc[i]) if i >= 0 else pd.NaT
        j15 = int(np.searchsorted(lts, (s + WAIT).value, "right")) - 1
        a, b = int(np.searchsorted(tt, s.value, "right")), int(np.searchsorted(tt, (s + WAIT).value, "right"))
        gi = cidx.get_loc(s)
        for side in ("buy", "sell"):
            row = {"symbol": sym, "s": s, "side": side, "snap_age_s": age.total_seconds() if i >= 0 else np.nan}
            if i < 0 or age > SNAP_MAX_AGE or j15 < 0:
                rows.append({**row, "skipped": True})
                continue
            P = float(touch["bid"].iloc[i] if side == "buy" else touch["ask"].iloc[i])
            Q0 = float(touch["bid_qty"].iloc[i] if side == "buy" else touch["ask_qty"].iloc[i])
            if not (np.isfinite(P) and np.isfinite(Q0) and P > 0):
                rows.append({**row, "skipped": True})
                continue
            q = NOTIONAL / P
            mid_s = float((touch["bid"].iloc[i] + touch["ask"].iloc[i]) / 2)
            k, partial, traded = fill_time(tt[a:b], px[a:b], qq[a:b], sl[a:b], side, P, Q0, q)
            mid15 = float(lad["mid"].iloc[j15])
            slip15 = float(lad["slip_buy_10000" if side == "buy" else "slip_sell_10000"].iloc[j15])
            adv = ((mid15 - P) if side == "buy" else (P - mid15)) / P * 1e4            # negative: bad for the maker (P1's definition: against the resting price)
            missed = ((mid15 - mid_s) if side == "buy" else (mid_s - mid15)) / mid_s * 1e4 if np.isfinite(mid_s) and mid_s > 0 else np.nan   # the mid's move since placement, positive: it ran away from an unfilled order
            filled = k >= 0
            leg = (MAKER_BPS - adv) if filled else (TAKER_BPS + slip15)
            # the harness's maker on the same instant: rest at the 5m close, fill if a later bar trades strictly through within MAKER_WAIT bars
            p0 = cl[gi]
            fut = (lo if side == "buy" else hi)[gi + 1:gi + 1 + MAKER_WAIT]
            h_fill = bool(np.nanmin(fut) < p0) if side == "buy" and np.isfinite(fut).any() else (bool(np.nanmax(fut) > p0) if np.isfinite(fut).any() else False)
            c3 = cl[gi + MAKER_WAIT] if gi + MAKER_WAIT < len(cl) else np.nan
            h_adv = ((c3 - p0) if side == "buy" else (p0 - c3)) / p0 * 1e4 if np.isfinite(c3) and np.isfinite(p0) else np.nan
            rows.append({**row, "skipped": False, "P": P, "Q0": Q0, "q": q, "queue_x": Q0 / q, "filled": filled, "partial": partial, "traded_at_level": traded,
                         "t_fill_s": (tr["t"].iloc[a + k] - s).total_seconds() if filled else np.nan, "swept": bool(filled and not (np.abs(px[a + k] - P) <= 1e-9 * abs(P))),
                         "adv_bps": adv, "slip15_bps": slip15, "missed_bps": missed, "leg_cost_bps": leg, "leg_cost_with_missed_bps": leg + (0.0 if filled else missed),
                         "h_fill": h_fill, "h_adv_bps": h_adv, "h_leg_cost_bps": (MAKER_BPS - h_adv) if h_fill else (TAKER_BPS + slip15)})
    return pd.DataFrame(rows)


# ---- the read -------------------------------------------------------------------------------------------------------------------------------
def _summ(g: pd.DataFrame) -> dict:
    d = g[~g["skipped"]]
    by_day = d.groupby(pd.DatetimeIndex(d["s"]).floor("D"))["leg_cost_bps"].mean()
    se = float(by_day.std(ddof=1) / np.sqrt(len(by_day))) if len(by_day) > 1 else np.nan
    f = d[d["filled"]]
    return {"placements": int(len(g)), "skipped": int(g["skipped"].sum()), "fill_share": float(d["filled"].mean()), "partial_share": float(d["partial"].mean()),
            "swept_share_of_fills": float(f["swept"].mean()) if len(f) else np.nan, "t_fill_median_s": float(f["t_fill_s"].median()) if len(f) else np.nan,
            "queue_x_median": float(d["queue_x"].median()), "adv_filled_mean_bps": float(f["adv_bps"].mean()) if len(f) else np.nan,
            "adv_filled_median_bps": float(f["adv_bps"].median()) if len(f) else np.nan, "slip15_mean_bps": float(d["slip15_bps"].mean()),
            "missed_unfilled_mean_bps": float(d.loc[~d["filled"], "missed_bps"].mean()) if (~d["filled"]).any() else np.nan,
            "leg_cost_mean_bps": float(d["leg_cost_bps"].mean()), "eff_rt_bps": 2 * float(d["leg_cost_bps"].mean()), "eff_rt_se_bps": 2 * se,
            "eff_rt_with_missed_bps": 2 * float(d["leg_cost_with_missed_bps"].mean()),
            "h_fill_share": float(d["h_fill"].mean()), "h_adv_filled_mean_bps": float(d.loc[d["h_fill"], "h_adv_bps"].mean()) if d["h_fill"].any() else np.nan,
            "h_eff_rt_bps": 2 * float(d["h_leg_cost_bps"].mean()), "days": int(len(by_day))}


def run(start: str, end: str, symbols: list[str], name: str | None = None) -> str:
    days = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="D")
    out = OUT / (name or f"{days[0]:%Y-%m-%d}_{days[-1]:%Y-%m-%d}")
    out.mkdir(parents=True, exist_ok=True)
    # validity (1): the files
    missing = [str(trades_file(s, d)) for s in symbols for d in days if not trades_file(s, d).exists()]
    lv_missing = [str(data.RAW / "levels" / f"{d:%Y-%m-%d}" / "levels.csv.gz") for d in days if not (data.RAW / "levels" / f"{d:%Y-%m-%d}" / "levels.csv.gz").exists()]
    v: dict = {"registration": "R39", "window": [str(days[0].date()), str(days[-1].date())], "days": len(days), "symbols": symbols, "notional": NOTIONAL, "wait_min": int(WAIT.total_seconds() // 60),
               "snap_max_age_s": int(SNAP_MAX_AGE.total_seconds()), "trades_files_missing": missing, "levels_files_missing": lv_missing,
               "clock_note": "trades are stamped by the exchange (ms); snapshots by receipt, about 160 ms later at p50 (DATA.md); a placement uses the last snapshot with ts ≤ s"}
    if missing or lv_missing:
        v["status"] = "FAIL"
        (out / "validity.json").write_text(json.dumps(v, indent=1))
        (out / "makercost.md").write_text(f"# R39 — VOID\n\nvalidity FAIL: {len(missing)} trade files and {len(lv_missing)} level files missing.\n")
        print(f"validity FAIL — {len(missing)} trade files, {len(lv_missing)} level files missing; the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)
    print(f"makercost: {len(symbols)} names × {len(days)} days…", flush=True)
    lad_all = {s: data.load("ladder", columns=["ts", "mid", "slip_buy_10000", "slip_sell_10000"], symbols=[s]).sort_values("ts").reset_index(drop=True) for s in symbols}
    c5 = data.load("candles_5m", columns=["symbol", "open_time", "high", "low", "close"], symbols=symbols)
    c5["t"] = c5["open_time"] + BAR
    c5["symbol"] = c5["symbol"].astype(str)
    cand = {s: g.set_index("t")[["close", "high", "low"]].sort_index() for s, g in c5.groupby("symbol")}
    repro, cover, parts = [], {}, []
    touches = {}
    for d in days:
        touches[d] = load_touch(d, symbols)
    for s in symbols:
        print(f"  {s}…", flush=True)
        tr_by_day = {d: load_trades(s, d) for d in days}
        nxt = None
        for n, d in enumerate(days):
            tr = tr_by_day[d]
            nxt = tr_by_day[days[n + 1]] if n + 1 < len(days) else None
            tr_plus = pd.concat([tr, nxt[nxt["t"] < days[n + 1] + WAIT]], ignore_index=True) if nxt is not None else tr
            # validity (2): the trades reproduce the tape part
            part = data.PROC / "tape" / "parts" / s / f"{d:%Y-%m-%d}.parquet"
            if part.exists():
                p = pd.read_parquet(part, columns=["volume", "n_trades"])
                repro.append({"symbol": s, "day": str(d.date()), "d_volume": float(abs(p["volume"].sum() - tr["qty"].sum())), "d_trades": int(abs(int(p["n_trades"].sum()) - len(tr)))})
            else:
                repro.append({"symbol": s, "day": str(d.date()), "d_volume": np.nan, "d_trades": -1})
            touch = touches[d]
            touch = touch[touch["symbol"] == s].reset_index(drop=True)
            parts.append(placements(s, touch, lad_all[s], tr_plus, cand[s], d))
    P_ = pd.concat(parts, ignore_index=True)
    rep = pd.DataFrame(repro)
    for s in symbols:
        g = P_[P_["symbol"] == s]
        cover[s] = float(1 - g["skipped"].mean())
    v["reproduction"] = {"name_days": int(len(rep)), "parts_missing": int((rep["d_trades"] < 0).sum()), "max_abs_d_volume": float(rep["d_volume"].max()), "max_d_trades": int(rep["d_trades"].max())}
    v["ladder_cover"] = cover
    v["status"] = "PASS" if (v["reproduction"]["parts_missing"] == 0 and v["reproduction"]["max_abs_d_volume"] <= TOL and v["reproduction"]["max_d_trades"] == 0
                             and all(x >= COVER_BAR for x in cover.values())) else "FAIL"
    (out / "validity.json").write_text(json.dumps(v, indent=1))
    P_.to_parquet(out / "placements.parquet", index=False)
    rep.to_csv(out / "reproduction.csv", index=False)
    head = [f"# R39 — the maker cost at the trade level on the twelve (`ft2 makercost`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · window {days[0]:%Y-%m-%d} → {days[-1]:%Y-%m-%d} "
            f"({len(days)} days) · {len(symbols)} names · {NOTIONAL:,} USDT · wait {int(WAIT.total_seconds() // 60)} min\n",
            f"\n## Validity — read first: **{v['status']}**\n", "```\n", json.dumps(v, indent=1), "\n```\n"]
    if v["status"] != "PASS":
        (out / "makercost.md").write_text("\n".join(head + ["\n**The read is VOID.**\n"]))
        print(f"validity FAIL — the read is void; wrote {out}/", flush=True)
        raise SystemExit(2)

    # the numbers
    summ = pd.DataFrame([{"symbol": s, **_summ(P_[P_["symbol"] == s])} for s in symbols])
    cd = pd.read_parquet(data.PROC / "cost_daily.parquet")
    cd["symbol"] = cd["symbol"].astype(str)
    cd = cd[(cd["day"] >= days[0]) & (cd["day"] <= days[-1]) & cd["symbol"].isin(symbols)]
    p1 = cd.groupby("symbol").agg(p1_fill_15=("maker_fill_15", "mean"), p1_adv_15=("maker_adv_15", "mean"), p1_spread_cal=("spread_cal_bps", "mean"),
                                   p1_imp_10000=(f"imp_{NOTIONAL}", "mean")).reset_index()
    p1["p1_rt_15"] = 2 * MAKER_BPS - 2 * p1["p1_adv_15"]
    p1["p1_taker_rt"] = 2 * TAKER_BPS + p1["p1_spread_cal"] + 2 * p1["p1_imp_10000"]
    summ = summ.merge(p1, on="symbol", how="left")
    summ["d_vs_p1"] = summ["eff_rt_bps"] - summ["p1_rt_15"]
    summ["d_vs_harness"] = summ["eff_rt_bps"] - summ["h_eff_rt_bps"]
    summ["sentence"] = np.where(summ["d_vs_harness"] <= 1.5, "OPEN", np.where(summ["d_vs_harness"] <= 4.0, "NARROWER", "CLOSED"))
    d = P_[~P_["skipped"]].copy()
    d["hour"] = pd.DatetimeIndex(d["s"]).hour
    d["day"] = pd.DatetimeIndex(d["s"]).floor("D")
    d["queue_bin"] = pd.cut(d["queue_x"], [-np.inf, 1, 10, np.inf], labels=["<1x", "1-10x", ">10x"])
    by_hour = d.groupby(["symbol", "hour"], observed=True).agg(fill=("filled", "mean"), leg=("leg_cost_bps", "mean"), n=("filled", "size")).reset_index()
    by_queue = d.groupby(["symbol", "queue_bin"], observed=True).agg(fill=("filled", "mean"), leg=("leg_cost_bps", "mean"), adv=("adv_bps", "mean"), n=("filled", "size")).reset_index()
    by_side = d.groupby(["symbol", "side"]).agg(fill=("filled", "mean"), leg=("leg_cost_bps", "mean"), adv=("adv_bps", "mean")).reset_index()
    # the day's volatility: the window's days split at the median |move| of the name (from the candles' daily log range of closes)
    vol = {}
    for s in symbols:
        c = cand[s]["close"]
        dm = np.log(c).groupby(c.index.floor("D")).agg(lambda x: x.max() - x.min())
        vol[s] = dm
    d["day_vol"] = [vol[s].get(dd, np.nan) for s, dd in zip(d["symbol"], d["day"])]
    med = d.groupby("symbol")["day_vol"].transform("median")
    d["vol_half"] = np.where(d["day_vol"] >= med, "active", "quiet")
    by_vol = d.groupby(["symbol", "vol_half"]).agg(fill=("filled", "mean"), leg=("leg_cost_bps", "mean"), n=("filled", "size")).reset_index()
    summ.to_csv(out / "summary.csv", index=False)
    by_hour.to_csv(out / "by_hour.csv", index=False)
    by_queue.to_csv(out / "by_queue.csv", index=False)
    by_vol.to_csv(out / "by_vol.csv", index=False)
    by_side.to_csv(out / "by_side.csv", index=False)
    show = lambda df, k=2: df.round(k).to_markdown(index=False)                       # noqa: E731
    med_rt = float(summ["eff_rt_bps"].median())
    cols = ["symbol", "placements", "skipped", "fill_share", "partial_share", "swept_share_of_fills", "t_fill_median_s", "queue_x_median", "adv_filled_mean_bps", "slip15_mean_bps",
            "missed_unfilled_mean_bps", "eff_rt_bps", "eff_rt_se_bps", "eff_rt_with_missed_bps", "h_fill_share", "h_adv_filled_mean_bps", "h_eff_rt_bps", "p1_fill_15", "p1_adv_15",
            "p1_rt_15", "p1_taker_rt", "d_vs_p1", "d_vs_harness", "sentence"]
    md = head + [
        f"\n## The number: the twelve's median effective maker round trip **{med_rt:.2f} bps** (the missed move excluded; with it "
        f"{float(summ['eff_rt_with_missed_bps'].median()):.2f}); the harness's bar-level maker on the same placements {float(summ['h_eff_rt_bps'].median()):.2f}; P1's day numbers "
        f"{float(summ['p1_rt_15'].median()):.2f}\n",
        "\nWords: a placement is a 10,000-USDT order resting at the touch at a 5-minute bar close, LAST in its level's queue (*queue_x* = the quantity ahead in units of the order's own). "
        "*fill_share*: filled within 15 minutes by the trades that followed (the queue consumed at the level, or the level swept — *swept_share_of_fills*); *partial*: the queue was "
        "reached but the order not completed. *adv*: the mid 15 minutes on against the resting price, negative = the maker was picked off. *slip15*: what crossing at 15 minutes "
        "costs beyond the fee (the ladder's walk at 10,000). *eff_rt*: 2 × [fill × (2.0 − adv) + (1 − fill) × (5.0 + slip15)], the missed move of unfilled orders apart. *h_*: the "
        "harness's bar-level maker (rest at the 5m close, filled if a later bar trades strictly through within 3 bars) on the same instants. *p1_*: P1's minute-level day "
        "numbers over the window's days. The sentence per name: OPEN if eff_rt is within +1.5 bps of the harness's, NARROWER up to +4, CLOSED beyond (R39's gate).\n",
        "\n## Per name\n", show(summ[cols]), "\n",
        "\n## By the queue ahead at placement (units of the order's own size)\n", show(by_queue), "\n",
        "\n## By side\n", show(by_side), "\n",
        "\n## By the day's volatility (the window's days split at the name's median daily range)\n", show(by_vol), "\n",
        "\n## By hour of day (UTC): fill share and leg cost\n", show(by_hour.pivot(index="hour", columns="symbol", values="leg").reset_index(), 1), "\n",
        show(by_hour.pivot(index="hour", columns="symbol", values="fill").reset_index(), 2), "\n"]
    (out / "makercost.md").write_text("\n".join(md))
    print(f"R39: median eff_rt {med_rt:.2f} bps; wrote {out}/", flush=True)
    return "\n".join(md)
