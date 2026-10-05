"""P8, R28 — the new listing: what a new USDT perpetual does against the names already trading over its first 1, 3, 7 and 30
days. `ft2 listing select|run` (PLAN §8 R28 is the registration; this file is its code and changes nothing of it).

launches   `select`: Binance's launch announcements (`events.BINANCE`) whose contract begins in the archive in the month of
           the release or the next (`events.FIRST`), release inside F1+F2 → output/listing/launches_f12.csv, frozen as
           ft2/launches_f12.csv before any bar is fetched. No price is read by `select`.
entry      t0 = the open of the contract's first 5m bar with volume; the decision bar closes at t = t0 + 60 minutes; the
           position is entered one bar later (the harness's latency).
label      a = what a long earns before trading costs, funding paid on the position's value — `horizon.labels`' number, taken
           here at the launch's own row (`label_at`; the run checks the two are the same on the real market);
           b = the mean of the same over the members of the screener's block that holds t; y = a − b.
statistic  M = the mean of y per hold; its noise by a moving-block bootstrap over calendar weeks; family-wise over the holds.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import events, folds, horizon, universe
from .ceiling import BAR

OUT = Path("output/listing")
LAUNCHES_CSV = Path(__file__).with_name("launches_f12.csv")       # frozen from OUT / launches_f12.csv, once, and committed
FOLDS = ("F1", "F2")
HOLDS = (288, 864, 2016, 8640)         # 1, 3, 7, 30 days, the family
WAIT = 12                              # bars from the first bar's open to the decision bar's close: 60 minutes
LATE = 288                             # reference rows: the entry a day later
BAR_BPS = 46.0                         # twice a typical member's taker round trip
BLOCK_WEEKS, DRAWS, SEED = 6, 10_000, 28
TRIM = 3
T0_WINDOW = (pd.Timedelta(hours=-1), pd.Timedelta(days=14))        # t0 against the announcement's release
MIN_MEMBERS, MIN_ELIGIBLE, MIN_T0_SHARE, MIN_BARS, MIN_LABELS = 40, 80, 0.90, 0.95, 0.95
BTC = "BTCUSDT"
OWN = ("1000PEPEUSDT", "WLDUSDT")      # the two of the twelve that began in F1: described with and without
CHECKS = {"fingerprint": OUT / "r28_fingerprint_check.json", "costwide": Path("output/backtest/r28_costwide_check.json")}


def window() -> tuple[pd.Timestamp, pd.Timestamp]:
    return folds.bounds(FOLDS[0], embargoed=False)[0], folds.bounds(FOLDS[-1], embargoed=False)[1]


# ---- the launch list (no price) -----------------------------------------------------------------------------------------------
def launch_list(bn: pd.DataFrame, first: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp) -> pd.DataFrame:
    """Every ticker of kind `perp_launch` whose contract <ticker>USDT begins in the archive in the calendar month of the
    announcement's release or the next; per contract the earliest such release; release in [a, b)."""
    la = bn[(bn["kind"] == "perp_launch") & (bn["symbol"] != "")].assign(contract=lambda x: x["symbol"] + "USDT", rmo=lambda x: x["release"].dt.year * 12 + x["release"].dt.month)
    fm = first[first["symbol"].str.fullmatch(r"[A-Z0-9]+USDT") & (first["first_month"] != "")].rename(columns={"symbol": "contract"})
    fm = fm.assign(mo=fm["first_month"].str[:4].astype(int) * 12 + fm["first_month"].str[5:7].astype(int))
    j = la.merge(fm[["contract", "first_month", "mo"]], on="contract")
    j = j[(j["mo"] - j["rmo"]).between(0, 1)].sort_values(["contract", "release"]).drop_duplicates("contract")
    j = j[(j["release"] >= a) & (j["release"] < b)]
    return j[["contract", "release", "first_month", "id"]].sort_values(["release", "contract"]).reset_index(drop=True)


def select() -> pd.DataFrame:
    bn, first = pd.read_parquet(events.BINANCE), pd.read_csv(events.FIRST, dtype=str).fillna("")
    L = launch_list(bn, first, *window())
    OUT.mkdir(parents=True, exist_ok=True)
    L.to_csv(OUT / "launches_f12.csv", index=False)
    by = events.fold_of(L["release"]).value_counts().to_dict()
    print(f"{len(L)} launches, release {L['release'].min():%Y-%m-%d} → {L['release'].max():%Y-%m-%d}, by fold {by} → {OUT / 'launches_f12.csv'}")
    return L


def launches(path: Path | str | None = None) -> pd.DataFrame:
    L = pd.read_csv(path or LAUNCHES_CSV)
    L["release"] = pd.to_datetime(L["release"], utc=True)
    return L


def launch_symbols(path: Path | str | None = None) -> list[str]:
    return sorted(set(launches(path)["contract"]))


# ---- entries, labels, the benchmark ---------------------------------------------------------------------------------------------
def entries(M: bt.Market, L: pd.DataFrame, end: pd.Timestamp, first_block: pd.Timestamp, wait: int = WAIT, latency: int = bt.LATENCY, longest: int = max(HOLDS)) -> pd.DataFrame:
    """Per launch: t0, the decision row and why it is or is not eligible. `t0_ok` is the event's own rule (the contract began
    within T0_WINDOW of the release); the calendar then cuts what F1+F2 cannot hold."""
    idx, n = M.index, len(M.index)
    dv, cl = M.dv.to_numpy(), M.close.to_numpy()
    col = M.columns.get_indexer(L["contract"])
    rows = []
    for c, rel in zip(col, L["release"]):
        live = np.flatnonzero((dv[:, c] > 0) & np.isfinite(cl[:, c])) if c >= 0 else np.array([], dtype=int)
        if not len(live) or live[0] == 0:                          # no bar, or bars from the market's first row on: the beginning is not seen
            rows.append({"t0": pd.NaT, "row": -1, "t0_ok": False, "why": "no first bar in the market"})
            continue
        i0 = int(live[0])
        t0, row = idx[i0] - BAR, i0 + wait - 1                     # the index is the bar's CLOSE
        t0_ok = bool(rel + T0_WINDOW[0] <= t0 <= rel + T0_WINDOW[1])
        x = row + latency + longest
        why = ("t0 outside the release's window" if not t0_ok else "before F1's first scored instant" if row >= n or idx[row] < first_block
               else "the 30-day exit is not before the end" if x >= n or not idx[x] < end else "")
        rows.append({"t0": t0, "row": row if row < n else -1, "t0_ok": t0_ok, "why": why})
    out = pd.concat([L.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    out["t"] = [idx[r] if r >= 0 else pd.NaT for r in out["row"]]
    out["eligible"] = out["why"] == ""
    return out


def label_at(close: np.ndarray, fundval: np.ndarray, rows: np.ndarray, hold: int, latency: int = bt.LATENCY) -> np.ndarray:
    """`horizon.labels`' second number at the given decision rows, every column: exit ÷ entry − 1 minus the funding a long
    pays on the position's value, bps of the size at entry. NaN where a bar is beyond the market or a price is missing."""
    n = len(close)
    e, x = rows + latency, rows + latency + hold
    ok = (rows >= 0) & (x < n)
    e_, x_ = np.where(ok, e, 0), np.where(ok, x, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        pe = close[e_]
        y = (close[x_] / pe - 1.0) * 1e4 - (fundval[x_] - fundval[e_]) / pe
    y[~ok] = np.nan
    return y


def member_mask(mem: pd.DataFrame, cols: pd.Index, ts) -> np.ndarray:
    """launch × column: the members of the block that holds each t (the last block begun at or before it)."""
    starts = pd.DatetimeIndex(sorted(mem["block"].unique()))
    pos = np.clip(starts.searchsorted(pd.DatetimeIndex(ts), side="right") - 1, 0, None)
    out = np.zeros((len(pos), len(cols)), dtype=bool)
    by = {b: cols.get_indexer(g["symbol"]) for b, g in mem.groupby("block")}
    for i, p in enumerate(pos):
        j = by[starts[p]]
        out[i, j[j >= 0]] = True
    return out


def excess(A: np.ndarray, own: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(a, b, the number of members in b) per launch: its own label, and the mean label of the block's members that have one."""
    i = np.arange(len(own))
    m = mask.copy()
    m[i, own] = False                                              # a launch is never its own benchmark
    v = np.where(m, A, np.nan)
    nb = np.isfinite(v).sum(axis=1)
    with np.errstate(invalid="ignore"):
        b = np.where(nb > 0, np.nansum(v, axis=1) / np.maximum(nb, 1), np.nan)
    return A[i, own], b, nb


# ---- the statistic ----------------------------------------------------------------------------------------------------------------
def weeks(t: pd.DatetimeIndex) -> tuple[np.ndarray, int]:
    """The calendar week (Monday 00:00 UTC) of each t, numbered from the first launch's week; and how many weeks the sequence holds."""
    d = (pd.DatetimeIndex(t).floor("D") - pd.Timestamp("2018-01-01", tz="UTC")).days.to_numpy() // 7          # 2018-01-01 is a Monday
    return d - d.min(), int(d.max() - d.min() + 1)


def bootstrap(Y: np.ndarray, wk: np.ndarray, W: int, block: int = BLOCK_WEEKS, draws: int = DRAWS, seed: int = SEED) -> dict:
    """Y: launch × hold. A draw is ⌈W/block⌉ circular runs of `block` consecutive weeks, cut to W weeks; its M* is the sum of y
    over those weeks ÷ the launches in them. se = the sd of M*; u = M ÷ se; the family-wise p is two-sided over the holds."""
    fin = np.isfinite(Y)
    S, N = np.zeros((W, Y.shape[1])), np.zeros((W, Y.shape[1]))
    np.add.at(S, wk, np.where(fin, Y, 0.0))
    np.add.at(N, wk, fin.astype(float))
    m = S.sum(0) / N.sum(0)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, W, size=(draws, int(np.ceil(W / block))))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % W).reshape(draws, -1)[:, :W]
    with np.errstate(invalid="ignore", divide="ignore"):
        Ms = S[idx].sum(1) / N[idx].sum(1)
    Ms = Ms[np.isfinite(Ms).all(1)]
    se = Ms.std(axis=0, ddof=1)
    u = m / se
    T = (np.abs(Ms - m) / se).max(axis=1)
    resid = S - m * N                                              # the week-clustered se of a ratio: launches of a week move together
    return {"m": m, "se": se, "u": u, "p_fw": float((T >= np.abs(u).max()).mean()), "n": N.sum(0).astype(int), "draws": len(Ms),
            "se_week": np.sqrt(W / (W - 1) * (resid ** 2).sum(0)) / N.sum(0), "se_plain": np.nanstd(Y, axis=0, ddof=1) / np.sqrt(N.sum(0))}


def trimmed(y: np.ndarray, k: int = TRIM) -> float:
    v = np.sort(y[np.isfinite(y)])
    return float(v[k:-k].mean()) if len(v) > 2 * k else np.nan


def verdict(m: float, se: float, u: float, p_fw: float, m_f1: float, m_f2: float, m_trim: float, bar: float = BAR_BPS) -> str:
    s = np.sign(m)
    if abs(m) > bar and abs(u) >= 2 and p_fw <= 0.05 and np.sign(m_f1) == s == np.sign(m_f2) and np.sign(m_trim) == s and abs(m_trim) > bar:
        return "CLEARS"
    if abs(m) + 1.96 * se < bar:
        return "CLOSED"
    return "NOT DETECTABLE"


# ---- the run ------------------------------------------------------------------------------------------------------------------------
def _label_days(h: int) -> str:
    return f"{h // 288}d"


def _priced(M: bt.Market, C: bt.Costs, E: pd.DataFrame, hold: int, side: int, taker_bps: float) -> pd.DataFrame:
    dec = pd.DataFrame({"t": E["t"].to_numpy(), "symbol": E["contract"].to_numpy(), "side": side, "hold": hold, "size": 1.0, "fold": E["fold"].to_numpy(), "accepted": True})
    dec["t"] = pd.DatetimeIndex(E["t"])
    return bt.price(dec, M, C, "taker", taker_bps, 2.0)


def run(name: str = "r28", taker_bps: float = 5.0) -> str:
    a0, end = window()
    L = launches()
    mem = universe.members()
    first_block = mem["block"].min()
    syms = list(dict.fromkeys([*L["contract"], *universe.screen_symbols(), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, fv = M.close.to_numpy(), C.fundval
    E_all = entries(M, L, end, first_block)
    E_all["fold"] = events.fold_of(E_all["t"].fillna(pd.Timestamp("1970-01-01", tz="UTC")))
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    rows, own = E["row"].to_numpy(), M.columns.get_indexer(E["contract"])
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)

    # labels: the family, the entry a day later, the benchmark of BTC
    mask, mask_late = member_mask(mem, M.columns, E["t"]), member_mask(mem, M.columns, pd.DatetimeIndex(E["t"]) + LATE * BAR)
    btc = np.full(len(E), M.columns.get_loc(BTC))
    A, B, NB, Y, YL, YB = ({} for _ in range(6))
    for h in HOLDS:
        lab = label_at(close, fv, rows, h)
        A[h], B[h], NB[h] = excess(lab, own, mask)
        Y[h] = A[h] - B[h]
        al, bl, _ = excess(label_at(close, fv, rows + LATE, h), own, mask_late)
        YL[h], YB[h] = al - bl, A[h] - lab[np.arange(len(E)), btc]
        E[f"a_{_label_days(h)}"], E[f"b_{_label_days(h)}"], E[f"n_b_{_label_days(h)}"], E[f"y_{_label_days(h)}"] = A[h], B[h], NB[h], Y[h]

    # validity, read first
    could = E_all[E_all["release"] + T0_WINDOW[0] + (WAIT + bt.LATENCY + max(HOLDS)) * BAR < end]
    span = [np.isfinite(close[r:r + bt.LATENCY + max(HOLDS) + 1, c]).mean() for r, c in zip(rows, own)]
    ident = {}
    for h in HOLDS:                                                # (6) the module's label is horizon's, and the harness's gross + funding of a long
        full = horizon.labels(M, C, h, bt.LATENCY)[1].to_numpy()
        f = _priced(M, C, E, h, 1, taker_bps)
        ident[h] = (float(np.nanmax(np.abs(full[rows, own] - A[h]))), float(np.nanmax(np.abs((f["gross_bps"] + f["funding_bps"]).to_numpy() - A[h]))), bool((np.isfinite(full[rows, own]) == np.isfinite(A[h])).all()))
        del full
    outside = {k: (json.loads(p.read_text()).get("status") if p.exists() else "MISSING") for k, p in CHECKS.items()}
    V = {"1_2_fetch_fingerprint_costwide": outside,
         "3_frozen": len(L), "3_could_be_eligible": len(could), "3_t0_ok_share": float(could["t0_ok"].mean()) if len(could) else 0.0, "3_eligible": len(E),
         "4_min_share_of_bars": float(min(span)) if span else 0.0, "4_launches_under_95pct_bars": int(sum(s < MIN_BARS for s in span)),
         "4_label_share": {_label_days(h): float(np.isfinite(Y[h]).mean()) for h in HOLDS},
         "5_min_members": {_label_days(h): int(NB[h].min()) for h in HOLDS},
         "6_identity_max_abs_diff": {_label_days(h): ident[h][:2] for h in HOLDS}, "6_same_cells": all(ident[h][2] for h in HOLDS)}
    V["status"] = "PASS" if (all(v == "PASS" for v in outside.values()) and V["3_t0_ok_share"] >= MIN_T0_SHARE and len(E) >= MIN_ELIGIBLE and V["4_launches_under_95pct_bars"] == 0
                             and min(V["4_label_share"].values()) >= MIN_LABELS and min(V["5_min_members"].values()) >= MIN_MEMBERS
                             and max(max(v) for v in V["6_identity_max_abs_diff"].values()) <= 1e-9 and V["6_same_cells"]) else "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1))
    E_all.to_csv(out / "launches_all.csv", index=False)
    md = [f"# R28 — the new listing (`ft2 listing run`)\n", f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {M.index[0]:%Y-%m-%d} → {M.index[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names\n",
          f"\n## Validity: {V['status']}\n", "\n```\n" + json.dumps(V, indent=1) + "\n```\n",
          "\nLaunches by what became of them:\n", E_all["why"].replace("", "eligible").value_counts().rename("launches").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the family is not computed.**\n"]
        (out / "listing.md").write_text("\n".join(md))
        return "\n".join(md)

    # the family
    t = pd.DatetimeIndex(E["t"])
    wk, W = weeks(t)
    Ymat = np.column_stack([Y[h] for h in HOLDS])
    bs = bootstrap(Ymat, wk, W)
    f1, f2 = (E["fold"] == "F1").to_numpy(), (E["fold"] == "F2").to_numpy()
    fam = []
    for k, h in enumerate(HOLDS):
        y = Y[h]
        r = {"hold": _label_days(h), "n": int(bs["n"][k]), "M": bs["m"][k], "se": bs["se"][k], "u": bs["u"][k], "p_fw": bs["p_fw"], "MDE": 2.8 * bs["se"][k],
             "M_F1": float(np.nanmean(y[f1])), "M_F2": float(np.nanmean(y[f2])), "M_trim": trimmed(y), "se_week": bs["se_week"][k], "se_plain": bs["se_plain"][k]}
        r["verdict"] = verdict(r["M"], r["se"], r["u"], r["p_fw"], r["M_F1"], r["M_F2"], r["M_trim"])
        fam.append(r)
    fam = pd.DataFrame(fam)
    fam.to_csv(out / "holds.csv", index=False)
    md += [f"\n## The family — y = a − b, bps of the position; {len(E)} launches in {W} weeks; bar {BAR_BPS:.0f}; {bs['draws']:,} draws of {BLOCK_WEEKS}-week blocks\n", fam.round(3).to_markdown(index=False), "\n",
           f"\nn in F1 {int(f1.sum())}, in F2 {int(f2.sum())}; launches per week: mean {len(E) / W:.2f}, most {int(np.bincount(wk, minlength=W).max())}, weeks with none {int((np.bincount(wk, minlength=W) == 0).sum())}.\n"]

    # described — decides nothing
    q = [0.05, 0.25, 0.5, 0.75, 0.95]
    desc, sold, ref, net = [], [], [], []
    C2 = bt.load_costs(M.index, M.columns, end, cost_mult=2.0, close=M.close)
    notown = ~E["contract"].isin(OWN).to_numpy()
    for h in HOLDS:
        y, d = Y[h], _label_days(h)
        v = y[np.isfinite(y)]
        fl = _priced(M, C, E, h, 1, taker_bps)
        desc.append({"hold": d, "median": np.median(v), "share_below_0": (v < 0).mean(), **{f"q{int(x * 100):02d}": np.quantile(v, x) for x in q}, "min": v.min(), "max": v.max(),
                     "mean_a": np.nanmean(A[h]), "mean_b": np.nanmean(B[h]), "median_a": np.nanmedian(A[h]), "funding_part_of_a": float(np.nanmean(fl["funding_bps"])),
                     "M_without_PEPE_WLD": float(np.nanmean(y[notown]))})
        sold.append({"hold": d, "mean_sold": -v.mean(), "mean_sold_loss_capped_at_size": np.maximum(-v, -1e4).mean(), "largest_single_loss": float(v.max()), "sold_positions_losing_over_half": int((v > 5000).sum())})
        ref.append({"hold": d, "M_entry_a_day_later": float(np.nanmean(YL[h])), "median_entry_a_day_later": float(np.nanmedian(YL[h])), "M_against_BTC": float(np.nanmean(YB[h])),
                    "median_against_BTC": float(np.nanmedian(YB[h])), "M_a_alone": float(np.nanmean(A[h]))})
        for side, sname in ((1, "bought"), (-1, "sold")):
            for mult, CC in ((1, C), (2, C2)):
                f = _priced(M, CC, E, h, side, taker_bps)
                net.append({"hold": d, "side": sname, "cost": f"×{mult}", "n_priced": int(f["net_bps"].notna().sum()), "gross": f["gross_bps"].mean(), "fee": f["fee_bps"].mean(), "spread_impact": f["other_cost_bps"].mean(),
                            "funding": f["funding_bps"].mean(), "net": f["net_bps"].mean(), "net_median": f["net_bps"].median()})
        E[f"y_late_{d}"], E[f"y_btc_{d}"] = YL[h], YB[h]
    E.to_csv(out / "launches.csv", index=False)
    qt = E.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")[[f"y_{_label_days(h)}" for h in HOLDS]].agg(["size", "mean", "median"]).round(1)
    h7 = "y_7d"
    ext = pd.concat([E.nlargest(5, h7), E.nsmallest(5, h7)])[["contract", "t", *[f"y_{_label_days(h)}" for h in HOLDS], *[f"a_{_label_days(h)}" for h in HOLDS]]].round(0)
    md += ["\n## Described — decides nothing\n", "\nThe distribution of y, and a and b apart:\n", pd.DataFrame(desc).round(1).to_markdown(index=False), "\n",
           "\nThe money of a SOLD position (−y; a loss capped at the position's size is a different rule, shown beside):\n", pd.DataFrame(sold).round(1).to_markdown(index=False), "\n",
           f"\nEach position through the harness as a taker (fee {taker_bps} bps a leg, `costwide`'s proxy and its double; the contract's own legs, no benchmark):\n", pd.DataFrame(net).round(1).to_markdown(index=False), "\n",
           "\nBy calendar quarter of the entry (launches, mean, median):\n", qt.to_markdown(), "\n",
           "\nThe five largest and the five smallest y at 7 days:\n", ext.to_markdown(index=False), "\n",
           "\n## Reference rows — no verdict\n", pd.DataFrame(ref).round(1).to_markdown(index=False), "\n"]
    (out / "meta.json").write_text(json.dumps({"registration": "R28", "unit": bt.UNIT, "charged": bt.CHARGED, "holds": HOLDS, "wait": WAIT, "bar_bps": BAR_BPS, "block_weeks": BLOCK_WEEKS,
                                                "draws": DRAWS, "seed": SEED, "launches": len(L), "eligible": len(E), "weeks": W, "taker_bps": taker_bps}, indent=1))
    text = "\n".join(md)
    (out / "listing.md").write_text(text)
    return text


def main(action: str) -> None:
    if action == "select":
        select()
    elif action == "run":
        print(run())
        print(f"wrote {OUT / 'r28'}/")
