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

R29 — `ft2 listing confirm`: the confirmation read of R28's candidate on the launches of F3+F4 (PLAN §8 R29). One rule: sold at
the same entry, held 2,016 bars, bought back at the bar after the first close at or above 1.9 × the entry; priced by
`backtest.price` (a leg on the entry day at twice the contract's proxy row), hedged with the block's members, the hedge's round
trips paid. H = own + hedge; M = its mean; u on the larger of the bootstrap's and the week-clustered se. A guarded read: once.
"""
from __future__ import annotations

import dataclasses
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

# R29, the confirmation read
CONF_FOLDS = ("F3", "F4")
LAUNCHES34_CSV = Path(__file__).with_name("launches_f34.csv")      # frozen from OUT / launches_f34.csv, once, and committed
HOLD = 2016                            # 7 days: R28's candidate
STOP = 1.9                             # a close at or above this × the entry price closes the sold position at the next bar
ENTRY_MULT = 2.0                       # a leg on the entry day: this × the contract's proxy row (the proxy has none for a first day)
HEAVY = (4.0, 2.0)                     # the heavy reading: the entry day × 4, every other proxy cost × 2
SEED_CONFIRM = 29
MIN_CONFIRM = 200
CHECKS29 = {"fingerprint": OUT / "r29_fingerprint_check.json", "costwide": Path("output/backtest/r29_costwide_check.json"), "r28_comes_back": OUT / "r29_r28_check.json"}
TAGS = {FOLDS: "f12", CONF_FOLDS: "f34"}


def window(fold_names=FOLDS) -> tuple[pd.Timestamp, pd.Timestamp]:
    return folds.bounds(fold_names[0], embargoed=False)[0], folds.bounds(fold_names[-1], embargoed=False)[1]


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


def select(fold_names=FOLDS) -> pd.DataFrame:
    fold_names = tuple(fold_names)
    bn, first = pd.read_parquet(events.BINANCE), pd.read_csv(events.FIRST, dtype=str).fillna("")
    L = launch_list(bn, first, *window(fold_names))
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"launches_{TAGS[fold_names]}.csv"
    L.to_csv(dest, index=False)
    by = events.fold_of(L["release"]).value_counts().to_dict()
    print(f"{len(L)} launches, release {L['release'].min():%Y-%m-%d} → {L['release'].max():%Y-%m-%d}, by fold {by} → {dest}")
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


# ---- R29: the sold position, its stop, its costs and its hedge ---------------------------------------------------------------------
def stop_exit(c: np.ndarray, e: int, hold: int = HOLD, level: float = STOP) -> tuple[int, bool]:
    """One contract's closes, the entry row → (the exit row, stopped). The trigger is the first bar after the entry and before
    the full-hold exit whose close is at or above `level` × the entry price; the exit is the bar after it. A missing close
    triggers nothing."""
    last = e + hold
    with np.errstate(invalid="ignore"):
        hit = np.flatnonzero(c[e + 1:last] >= level * c[e])
    return (e + 2 + int(hit[0]), True) if len(hit) else (last, False)


def entry_day_legs(leg: np.ndarray, days: pd.DatetimeIndex, entry_days, own: np.ndarray, mult: float) -> np.ndarray:
    """The cost legs (day × pair) with, for each trade, its contract's leg on the day of the entry set to `mult` × that day's
    row if it has one, else `mult` × the contract's first row after it."""
    out = leg.copy()
    for p, j in zip(days.get_indexer(pd.DatetimeIndex(entry_days)), own):
        if p < 0:
            continue
        col = leg[p:, j]
        ok = np.flatnonzero(np.isfinite(col))
        out[p, j] = mult * col[ok[0]] if len(ok) else np.nan
    return out


def hedge(close: np.ndarray, fv: np.ndarray, leg: np.ndarray, days: pd.DatetimeIndex, idx: pd.DatetimeIndex, e: np.ndarray, x: np.ndarray,
          mask: np.ndarray, taker_bps: float) -> pd.DataFrame:
    """Per trade: one unit spread equally over the masked members, bought at row e and sold at row x — the mean of what a long
    earns, funding paid on the value, and the mean of the members' own taker round trips (the exit leg on the value), over the
    members that have both."""
    de, dx = days.get_indexer(idx[e].floor("D")), days.get_indexer(idx[x].floor("D"))
    rows = []
    for i in range(len(e)):
        m = np.flatnonzero(mask[i])
        with np.errstate(invalid="ignore", divide="ignore"):
            r = close[x[i], m] / close[e[i], m]
            gain = (r - 1.0) * 1e4 - (fv[x[i], m] - fv[e[i], m]) / close[e[i], m]
            cost = (taker_bps + (leg[de[i], m] if de[i] >= 0 else np.nan)) + (taker_bps + (leg[dx[i], m] if dx[i] >= 0 else np.nan)) * r
        ok = np.isfinite(gain) & np.isfinite(cost)
        rows.append({"hedge_gain": gain[ok].mean() if ok.any() else np.nan, "hedge_cost": cost[ok].mean() if ok.any() else np.nan, "n_b": int(ok.sum())})
    return pd.DataFrame(rows)


def sold_trades(M: bt.Market, C: bt.Costs, E: pd.DataFrame, mask: np.ndarray, taker_bps: float, entry_mult: float = ENTRY_MULT, other_mult: float = 1.0,
                hold: int = HOLD, level: float = STOP, shift: int = 0) -> pd.DataFrame:
    """One sold unit per launch of E (its decision row `row`, + `shift` bars), by the rule; `C` as loaded (cost × 1). The
    scenario's legs are `other_mult` × the proxy, the entry day `entry_mult` × it."""
    close, idx = M.close.to_numpy(), M.index
    own = M.columns.get_indexer(E["contract"])
    rows = E["row"].to_numpy() + shift
    e = rows + bt.LATENCY
    ex = [stop_exit(close[:, j], int(a), hold, level) for a, j in zip(e, own)]
    x, stopped = np.array([v[0] for v in ex]), np.array([v[1] for v in ex])
    legs = entry_day_legs(other_mult * C.taker_leg, C.days, idx[e].floor("D"), own, entry_mult / other_mult)
    Cs = dataclasses.replace(C, taker_leg=legs)
    dec = pd.DataFrame({"t": idx[rows], "symbol": E["contract"].to_numpy(), "side": -1, "hold": x - e, "size": 1.0, "fold": E["fold"].to_numpy(), "accepted": True})
    f = bt.price(dec, M, Cs, "taker", taker_bps, 2.0)
    m = mask.copy()
    m[np.arange(len(own)), own] = False
    h = hedge(close, C.fundval, other_mult * C.taker_leg, C.days, idx, e, x, m, taker_bps)
    out = pd.DataFrame({"contract": E["contract"].to_numpy(), "fold": E["fold"].to_numpy(), "t": idx[rows], "e": e, "x": x, "stopped": stopped, "entry_t": f["entry_t"].to_numpy(), "exit_t": f["exit_t"].to_numpy(),
                        "entry_px": f["entry_px"].to_numpy(), "exit_px": f["exit_px"].to_numpy(), "gross": f["gross_bps"].to_numpy(), "funding": f["funding_bps"].to_numpy(), "fee": f["fee_bps"].to_numpy(),
                        "spread_impact": f["other_cost_bps"].to_numpy(), "own": f["net_bps"].to_numpy(), "leg_entry": legs[C.days.get_indexer(idx[e].floor("D")), own], "leg_exit": legs[C.days.get_indexer(idx[x].floor("D")), own]})
    out = pd.concat([out, h], axis=1)
    out["hedge"] = out["hedge_gain"] - out["hedge_cost"]
    out["H"] = out["own"] + out["hedge"]
    return out


def verdict_confirm(m: float, se: float, m_heavy: float) -> str:
    if m > 0 and m / se >= 2 and m_heavy > 0:
        return "CONFIRMED"
    if m + 1.96 * se < 0:
        return "CLOSED"
    return "NOT CONFIRMED"


def noise(h: np.ndarray, t: pd.DatetimeIndex, seed: int = SEED_CONFIRM) -> dict:
    wk, W = weeks(t)
    b = bootstrap(h[:, None], wk, W, seed=seed)
    r = {"n": int(b["n"][0]), "M": float(b["m"][0]), "se_bootstrap": float(b["se"][0]), "se_week": float(b["se_week"][0]), "se_plain": float(b["se_plain"][0]), "weeks": W}
    r["se"] = max(r["se_bootstrap"], r["se_week"])                # the gate's: the larger of the two
    r["u"] = r["M"] / r["se"]
    return r


def confirm(registration: str, name: str = "r29", taker_bps: float = 5.0) -> str:
    conf = bt._guard(CONF_FOLDS, registration)                    # a confirmation read: registered, and once
    a0, end = window(CONF_FOLDS)
    L = launches(LAUNCHES34_CSV)
    mem = universe.members(universe.F34_MEMBERS_CSV)
    syms = list(dict.fromkeys([*L["contract"], *universe.screen_symbols(universe.F34_MEMBERS_CSV), BTC]))
    M = bt.market(syms, end, a0 - pd.Timedelta(days=1))
    C = bt.load_costs(M.index, M.columns, end, close=M.close)
    close, idx = M.close.to_numpy(), M.index
    E_all = entries(M, L, end, mem["block"].min(), longest=HOLD)
    E_all["fold"] = events.fold_of(E_all["t"].fillna(pd.Timestamp("1970-01-01", tz="UTC")))
    E = E_all[E_all["eligible"]].reset_index(drop=True)
    own = M.columns.get_indexer(E["contract"])
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    mask = member_mask(mem, M.columns, E["t"])
    T = sold_trades(M, C, E, mask, taker_bps)
    TH = sold_trades(M, C, E, mask, taker_bps, entry_mult=HEAVY[0], other_mult=HEAVY[1])

    # validity, read first
    could = E_all[E_all["release"] + T0_WINDOW[0] + (WAIT + bt.LATENCY + HOLD) * BAR < end]
    span = [np.isfinite(close[r:r + bt.LATENCY + HOLD + 1, c]).mean() for r, c in zip(E["row"], own)]
    e, x = T["e"].to_numpy(), T["x"].to_numpy()
    pe, px_ = close[e, own], close[x, own]
    r = px_ / pe
    mine = {"gross": -(r - 1.0) * 1e4, "funding": (C.fundval[x, own] - C.fundval[e, own]) / pe, "fee": taker_bps + taker_bps * r, "spread_impact": T["leg_entry"].to_numpy() + T["leg_exit"].to_numpy() * r}
    mine["own"] = mine["gross"] - mine["fee"] - mine["spread_impact"] + mine["funding"]
    d6 = {k: float(np.nanmax(np.abs(v - T[k].to_numpy()))) for k, v in mine.items()}
    full = horizon.labels(M, C, HOLD, bt.LATENCY)[1].to_numpy()[E["row"].to_numpy(), own]
    free = ~T["stopped"].to_numpy()
    d6["unstopped_vs_horizon_labels"] = float(np.nanmax(np.abs((T["gross"] + T["funding"]).to_numpy()[free] + full[free]))) if free.any() else 0.0
    del full
    again = [stop_exit(close[:, j], int(a)) for a, j in zip(e, own)]
    early = [bool(np.nanmax(close[a + 1:b - 1, j], initial=-np.inf) >= STOP * close[a, j]) if b - 1 > a + 1 else False for a, b, j in zip(e, x, own)]
    outside = {k: (json.loads(p.read_text()).get("status") if p.exists() else "MISSING") for k, p in CHECKS29.items()}
    fp = json.loads(CHECKS29["fingerprint"].read_text()) if CHECKS29["fingerprint"].exists() else {}
    V = {"1_latest_bar_in_the_slice": fp.get("latest_bar", "MISSING"), "2_3_fingerprint_costwide_r28": outside,
         "4_frozen": len(L), "4_could_be_eligible": len(could), "4_t0_ok_share": float(could["t0_ok"].mean()) if len(could) else 0.0, "4_eligible": len(E),
         "5_launches_under_95pct_bars": int(sum(v < MIN_BARS for v in span)), "5_H_share": float(T["H"].notna().mean()), "5_min_members": int(T["n_b"].min()),
         "6_identity_max_abs_diff": d6, "7_stop_recomputed_same": bool(all(a[0] == b and a[1] == c for a, b, c in zip(again, x, T["stopped"]))), "7_close_over_the_level_before_the_trigger": int(sum(early)),
         "7_exits_at_or_after_end": int((T["exit_t"] >= end).sum())}
    V["status"] = "PASS" if (all(v == "PASS" for v in outside.values()) and str(V["1_latest_bar_in_the_slice"]) < "2026-01-01" and V["4_t0_ok_share"] >= MIN_T0_SHARE and len(E) >= MIN_CONFIRM
                             and V["5_launches_under_95pct_bars"] == 0 and V["5_H_share"] >= MIN_LABELS and V["5_min_members"] >= MIN_MEMBERS and max(d6.values()) <= 1e-9
                             and V["7_stop_recomputed_same"] and V["7_close_over_the_level_before_the_trigger"] == 0 and V["7_exits_at_or_after_end"] == 0) else "FAIL"
    (out / "validity.json").write_text(json.dumps(V, indent=1))
    E_all.to_csv(out / "launches_all.csv", index=False)
    md = [f"# R29 — the confirmation read of the new listing, sold, 7 days (`ft2 listing confirm`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · unit {bt.UNIT}, charged on {bt.CHARGED} · market {idx[0]:%Y-%m-%d} → {idx[-1]:%Y-%m-%d %H:%M}, {len(M.columns)} names\n",
          f"\n## Validity: {V['status']}\n", "\n```\n" + json.dumps(V, indent=1) + "\n```\n",
          "\nLaunches by what became of them:\n", E_all["why"].replace("", "eligible").value_counts().rename("launches").to_frame().to_markdown(), "\n"]
    if V["status"] != "PASS":
        md += ["\n**VOID — the number is not computed, and the read is not logged.**\n"]
        (out / "confirm.md").write_text("\n".join(md))
        return "\n".join(md)

    # the number
    ok = T["H"].notna().to_numpy()
    t = pd.DatetimeIndex(T["t"])
    N = noise(T["H"].to_numpy()[ok], t[ok])
    m_heavy = float(TH["H"].mean())
    N.update({"M_heavy": m_heavy, "MDE": 2.8 * N["se"], "verdict": verdict_confirm(N["M"], N["se"], m_heavy)})
    (out / "confirm.json").write_text(json.dumps(N, indent=1))
    T.to_csv(out / "trades.csv", index=False)
    TH.to_csv(out / "trades_heavy.csv", index=False)
    pd.DataFrame({"read_at": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC", "registration": registration, "fold": conf, "strategy": "listing_sold_7d",
                  "params": json.dumps({"hold": HOLD, "stop": STOP, "wait": WAIT, "entry_mult": ENTRY_MULT})}).to_csv(bt.READS, mode="a", header=not bt.READS.exists(), index=False)
    md += [f"\n## The number — H = own + hedge, bps of the position; {N['n']} trades in {N['weeks']} weeks\n",
           pd.DataFrame([{k: N[k] for k in ("n", "M", "se", "u", "MDE", "M_heavy", "se_bootstrap", "se_week", "se_plain", "verdict")}]).round(3).to_markdown(index=False), "\n"]

    # described — decides nothing
    parts = ["gross", "funding", "fee", "spread_impact", "own", "hedge_gain", "hedge_cost", "hedge", "H"]
    by = pd.concat([T[parts].mean().rename("all"), *[T.loc[T["fold"] == f, parts].mean().rename(f) for f in CONF_FOLDS], TH[parts].mean().rename("heavy")], axis=1).T
    by.insert(0, "n", [len(T), *[int((T["fold"] == f).sum()) for f in CONF_FOLDS], len(TH)])
    No = noise(T["own"].to_numpy()[ok], t[ok])
    q = T.assign(q=t.tz_localize(None).to_period("Q").astype(str)).groupby("q")["H"].agg(["size", "mean", "median"])
    st = T[T["stopped"]]
    unst = sold_trades(M, C, E[T["stopped"].to_numpy()].reset_index(drop=True), mask[T["stopped"].to_numpy()], taker_bps, level=np.inf) if len(st) else st
    late = E[E["row"].to_numpy() + LATE + bt.LATENCY + HOLD < len(idx)].reset_index(drop=True)
    TL = sold_trades(M, C, late, member_mask(mem, M.columns, pd.DatetimeIndex(late["t"]) + LATE * BAR), taker_bps, shift=LATE)
    y7 = label_at(close, C.fundval, E["row"].to_numpy(), HOLD)
    a7, b7, _ = excess(y7, own, mask)
    hype = T["contract"] != "HYPEUSDT"
    md += ["\n## Described — decides nothing\n", "\nM's parts (means; `heavy` = the entry day at four times the proxy, every other proxy cost doubled):\n", by.round(1).to_markdown(), "\n",
           f"\n- the sold position alone (own): mean {No['M']:.1f}, se {No['se']:.1f} (bootstrap {No['se_bootstrap']:.1f}, week {No['se_week']:.1f}), u {No['u']:.2f}\n",
           f"- H: median {T['H'].median():.1f}, share of trades above zero {(T['H'] > 0).mean():.3f}; quantiles 5/25/75/95 % {', '.join(f'{v:.0f}' for v in T['H'].quantile([0.05, 0.25, 0.75, 0.95]))}; worst {T['H'].min():.0f}, best {T['H'].max():.0f}\n",
           f"- trades stopped: {len(st)} of {len(T)}" + (f"; their H: mean {st['H'].mean():.0f}, worst {st['H'].min():.0f}; the same trades unstopped: mean {unst['H'].mean():.0f}, worst {unst['H'].min():.0f}" if len(st) else "") + "\n",
           f"- without HYPE: M {T.loc[hype, 'H'].mean():.1f} ({int(hype.sum())} trades)\n",
           f"- the entry a day later, the same stop and costs (reference): mean H {TL['H'].mean():.1f}, median {TL['H'].median():.1f} ({len(TL)} trades)\n",
           f"- R28's own number on these launches (y at 7 days: no stop, no trading cost; a − the members' mean): mean {np.nanmean(a7 - b7):.1f}, median {np.nanmedian(a7 - b7):.1f} — R28 on F1+F2: −673.8, −1,183.3\n",
           "\nBy calendar quarter of the entry (trades, mean H, median H):\n", q.round(1).to_markdown(), "\n",
           "\nThe trades stopped:\n", (st[["contract", "entry_t", "exit_t", "gross", "funding", "own", "hedge", "H"]].round(0).to_markdown(index=False) if len(st) else "none"), "\n",
           "\nThe five best and the five worst trades:\n", pd.concat([T.nlargest(5, "H"), T.nsmallest(5, "H")])[["contract", "entry_t", "stopped", "gross", "funding", "own", "hedge", "H"]].round(0).to_markdown(index=False), "\n"]
    (out / "meta.json").write_text(json.dumps({"registration": registration, "unit": bt.UNIT, "charged": bt.CHARGED, "hold": HOLD, "stop": STOP, "wait": WAIT, "entry_mult": ENTRY_MULT, "heavy": HEAVY,
                                                "block_weeks": BLOCK_WEEKS, "draws": DRAWS, "seed": SEED_CONFIRM, "launches": len(L), "eligible": len(E), "taker_bps": taker_bps}, indent=1))
    text = "\n".join(md)
    (out / "confirm.md").write_text(text)
    return text


def main(action: str, fold_names=None, name: str | None = None, registration: str | None = None) -> None:
    if action == "select":
        select(tuple(fold_names) if fold_names else FOLDS)
    elif action == "run":
        print(run(name or "r28"))
        print(f"wrote {OUT / (name or 'r28')}/")
    elif action == "confirm":
        print(confirm(registration, name or "r29"))
        print(f"wrote {OUT / (name or 'r29')}/")
