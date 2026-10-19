"""R60 unit tests for the Coinbase-premium screen (`ft2/cb_ext.py`) on made-up bars and a planted hourly premium, no network: the 5m
frame reads the hourly bar floor(t − 5 min) and nothing later (known-at on every cell, the recomputation from the rows agrees), a hole
is carried over STALE hours and no further, the trailing month exists only once MIN_MONTH bars do, nothing after a bar changes a
feature before it; a premium whose deviation is planted to predict the next day's RELATIVE return comes back in `cbprem_dev` with the
registered sign and beats every draw of both nulls over the family of four; `run` writes validity first — a saved P2 screen that does
not match voids the run (exit 2) before any row of the registered features exists, a registered name without the source fails
coverage, and a matching world lets it through with the described row and the level beside."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, coinbase as cb
from ft2.cb_ext import CHG, DEV, LVL

LIQ = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT"]
PAIRS = LIQ + ["ZECUSDT", "WLDUSDT"]              # ZEC has the source (described), WLD has none (a NaN column)
DAYS, START = 80, "2023-03-25"                     # F1's first scored bar is 2023-05-01: the trailing month exists before it
HOLE = (pd.Timestamp("2023-05-20 06:00", tz="UTC"), 5)      # five missing hours on BTC from 06:00


def _world(tmp_path, fast: float = 0.8, seed: int = 11):
    """Ten random-walk pairs. The Coinbase premium at the hour ending at k = +3 bps + a slow sine + `fast` × −sign(the name's next-day
    return minus the names' mean) + noise — planted to predict a RELATIVE fall when a name is bid up, R60's sign. Binance's 5m close at
    the hour's end is the panel's; Coinbase's close = Binance × USDT-USD × (1 + prem / 1e4)."""
    os.chdir(tmp_path)
    for d in ("data", "output"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    hrs = t5[(t5.minute == 0)]
    hi = np.flatnonzero(t5.minute == 0)
    lr, c5, cost = {}, [], []
    for i, sym in enumerate(PAIRS):
        lr[sym] = np.cumsum(rng.normal(0, 6.0, len(t5))) / 1e4
        px = 100 * (i + 1) * np.exp(lr[sym])
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{ceiling.NOTIONAL}": 0.5, f"maker_adv_{ceiling.MAKER_H}": -1.5}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    L = np.column_stack([lr[s] for s in PAIRS])
    fwd = np.roll(L, -288, axis=0) - L
    fwd[-288:] = 0.0
    rel = fwd - fwd.mean(axis=1, keepdims=True)
    usdt = 0.9995 + rng.normal(0, 1e-4, len(hrs))
    prem, rows = {}, []
    with_source = LIQ + ["ZECUSDT"]
    for i, sym in enumerate(PAIRS):
        if sym not in with_source:
            continue
        p = 3.0 + 0.5 * np.sin(2 * np.pi * np.arange(len(hrs)) / (20 * 24) + i) - fast * np.sign(rel[hi, i]) + rng.normal(0, 0.3, len(hrs))
        prem[sym] = pd.Series(p, index=hrs)
        px = 100 * (i + 1) * np.exp(lr[sym][hi]) * usdt * (1 + p / 1e4)
        keep = np.ones(len(hrs), bool)
        if sym == "BTCUSDT":
            j = hrs.get_loc(HOLE[0])
            keep[j:j + HOLE[1]] = False
        rows.append(pd.DataFrame({"product": f"{cb.BASES.get(sym, sym[:-4])}-USD", "symbol": sym, "ts": hrs - cb.HOUR, "ts_known": hrs, "open": px, "high": px,
                                  "low": px, "close": px, "volume": 1.0})[keep])
    rows.append(pd.DataFrame({"product": cb.CONTROL, "symbol": None, "ts": hrs - cb.HOUR, "ts_known": hrs, "open": usdt, "high": usdt, "low": usdt, "close": usdt, "volume": 1.0}))
    pd.concat(rows, ignore_index=True).to_parquet("data/coinbase_1h.parquet", index=False)
    return prem


def _frame(tmp_path, **kw):
    prem = _world(tmp_path, **kw)
    P = ceiling.panel(PAIRS)
    D = ceiling.derive(P)
    F_all, U, G = cx.features(D["lr"].index, list(D["lr"].columns), LIQ + ["ZECUSDT"], "data/coinbase_1h.parquet")
    return prem, D, F_all, U, G


def test_the_frame_reads_the_hour_before_the_margin_and_nothing_later(tmp_path):
    prem, D, F_all, U, G = _frame(tmp_path)
    s = D["scored"]
    idx = D["lr"].index
    # the grid is the planted premium; the frame at t is the grid at floor(t − 5 min)
    for sym in ("ETHUSDT", "ZECUSDT"):
        g = G[sym].dropna()
        assert np.abs(g - prem[sym].reindex(g.index)).max() < 1e-6
    t = pd.Timestamp("2023-05-10 13:05", tz="UTC")
    assert abs(F_all[LVL].loc[t, "ETHUSDT"] - prem["ETHUSDT"].loc[pd.Timestamp("2023-05-10 13:00", tz="UTC")]) < 1e-6
    t = pd.Timestamp("2023-05-10 13:00", tz="UTC")                                             # at the boundary itself: the bar ending 12:00 is the last readable
    assert abs(F_all[LVL].loc[t, "ETHUSDT"] - prem["ETHUSDT"].loc[pd.Timestamp("2023-05-10 12:00", tz="UTC")]) < 1e-6
    # the hole: carried for STALE hours, NaN after
    h0 = HOLE[0]
    v = F_all[LVL]["BTCUSDT"]
    assert abs(v.loc[h0 + pd.Timedelta("5min")] - prem["BTCUSDT"].loc[h0 - cb.HOUR]) < 1e-6         # 06:05: the 06:00 bar is missing → the 05:00 bar carried
    assert abs(v.loc[h0 + pd.Timedelta("1h5min")] - prem["BTCUSDT"].loc[h0 - cb.HOUR]) < 1e-6      # 07:05: still the 05:00 bar (the second carried hour)
    assert np.isnan(v.loc[h0 + pd.Timedelta("2h5min")]) and np.isnan(v.loc[h0 + pd.Timedelta("4h55min")])   # 08:05 … 10:55: nothing (three to five hours old)
    assert abs(v.loc[h0 + pd.Timedelta("5h5min")] - prem["BTCUSDT"].loc[h0 + 5 * cb.HOUR]) < 1e-6  # 11:05: the 11:00 bar is back
    # the trailing month exists once MIN_MONTH bars do; the registered frames have no WLD / ZEC
    first = F_all[DEV]["ETHUSDT"].first_valid_index()
    assert G["ETHUSDT"].loc[:cx.keys(pd.DatetimeIndex([first]))[0]].notna().sum() == cx.MIN_MONTH
    F = cx.restrict(F_all, LIQ)
    assert F[DEV]["ZECUSDT"].isna().all() and F[DEV]["WLDUSDT"].isna().all() and F_all[DEV]["ZECUSDT"].notna().sum() > 1000 and F_all[DEV]["WLDUSDT"].isna().all()
    # known-at on every cell, the recomputation from the rows agrees; coverage passes
    ka = cx.known_at(F, U, G, s, LIQ, n_check=400)
    assert ka["status"] == "PASS" and ka["cells_read_too_early"] == 0 and ka["cells_older_than_stale"] == 0 and ka["max_abs_diff"] < 1e-9
    cov = cx.coverage(F, s)
    assert cov["status"] == "PASS" and cov["by_name"]["BTCUSDT"] > 0.99 and cov["bars_with_min_pairs"] > 0.99
    # a frame that reads one hour too early is caught
    early = {k: v.shift(-12) for k, v in F.items()}
    assert cx.known_at(early, U.shift(-12), G, s, LIQ, n_check=50)["cells_read_too_early"] > 0
    # nothing after a bar changes a feature before it
    cut = pd.Timestamp("2023-05-25", tz="UTC")
    x = pd.read_parquet("data/coinbase_1h.parquet")
    late = pd.DatetimeIndex(x["ts_known"]).tz_convert("UTC") >= cut
    x.loc[late & x["symbol"].notna(), "close"] *= 1.01
    x.to_parquet("data/coinbase_1h.parquet", index=False)
    F1, _, _ = cx.features(idx, list(D["lr"].columns), LIQ + ["ZECUSDT"], "data/coinbase_1h.parquet")
    for k in (LVL, DEV, CHG):
        pd.testing.assert_frame_equal(F_all[k][idx < cut], F1[k][idx < cut], obj=k)
        assert not F_all[k][idx > cut + pd.Timedelta(days=1)].equals(F1[k][idx > cut + pd.Timedelta(days=1)])


def test_a_planted_deviation_is_found_with_its_sign_over_the_family(tmp_path):
    prem, D, F_all, U, G = _frame(tmp_path)
    s = D["scored"]
    F = cx.restrict(F_all, LIQ)
    sc, daily = ceiling.ic_screen(D, F, set())
    g = sc.set_index(["bet", "horizon", "feature"])
    dev = g.loc["relative", "1d", DEV]
    assert dev["ic"] < -0.3 and dev["t"] < -4                                                    # the planted relative fall after a name is bid up
    fi = cx.fold_ics(daily, ("F1",))
    assert fi.set_index(["bet", "horizon", "feature"]).loc[("relative", "1d", DEV), "ic_F1"] < -0.3
    assert cx.verdict(dev["ic"], dev["ic_mde"] / ceiling.MDE_K, 0.01, True, 0.016) == "CLEARS"
    assert cx.verdict(-dev["ic"], dev["ic_mde"] / ceiling.MDE_K, 0.01, True, 0.016) == "CLEARS WITH THE OPPOSITE SIGN"
    assert cx.verdict(0.001, 0.002, 0.5, True, 0.016) == "CLOSED" and cx.verdict(0.02, 0.01, 0.3, True, 0.016) == "NOT DETECTABLE"
    assert cx.verdict(-0.05, 0.01, 0.01, False, 0.016) == "NOT DETECTABLE"                        # signs differing between folds: no clear
    Zs = {h: D["z"][h][s].clip(-ceiling.Z_CLIP, ceiling.Z_CLIP).to_numpy() for h in cx.HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in cx.HZ}
    shuf = pd.concat([ceiling._null_feature(k, F[k][s], Zs, Zr, 20, 0) for k in (DEV, CHG)], ignore_index=True)
    shift = pd.concat([cx.shift_feature(k, F[k], D, s, 20, 0, shift_min=5) for k in (DEV, CHG)], ignore_index=True)
    cells = [(f, h) for f in cx.REGISTERED for h in cx.FAMILY_HZ]
    t_real = {c: g.loc["relative", c[1], c[0]]["t"] for c in cells}
    for null in (shuf, shift):
        pf, bar = cx.family_p(null, cells, t_real)
        assert pf[DEV, "1d"] == 1 / 21 and bar["draws"] == 20 and bar["bar_t_p95"] < 4             # the planted |t| beats every draw's largest |t| over the four
        assert cx.single_p(null, "relative", DEV, "1d", t_real[DEV, "1d"]) == 1 / 21
        real = null[(null["draw"] == 0) & (null["bet"] == "relative") & (null["horizon"] == "1d") & (null["feature"] == DEV)]["t"].iloc[0]
        assert abs(real - t_real[DEV, "1d"]) < 1e-9


def test_run_writes_validity_first_voids_on_a_mismatch_or_a_missing_name_and_passes(tmp_path):
    prem, D, F_all, U, G = _frame(tmp_path)
    s = D["scored"]
    saved = tmp_path / "output" / "ceiling"
    saved.mkdir(parents=True)
    f_p2 = ceiling.dir_features(D)[cx.P2_ROW]
    sc_p2, _ = ceiling.ic_screen(D, {cx.P2_ROW: f_p2}, set())
    Zs = {h: D["z"][h][s].clip(-ceiling.Z_CLIP, ceiling.Z_CLIP).to_numpy() for h in cx.HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in cx.HZ}
    null_p2 = ceiling._null_feature(cx.P2_ROW, f_p2[s], Zs, Zr, 5, 0)
    sc_p2.assign(t=sc_p2["t"] * 1.01).to_parquet(saved / "ic.parquet", index=False)              # P2's screen "as saved", but not this run's
    null_p2.to_parquet(saved / "noise_ic.parquet", index=False)
    kw = dict(draws=5, shift_min=5, saved=saved, path="data/coinbase_1h.parquet", n_check=100)
    with pytest.raises(SystemExit) as e:
        cx.run(5.0, 2.0, "test", PAIRS, **kw)
    assert e.value.code == 2
    v = json.loads(Path("output/ceiling_coinbase/validity.json").read_text())
    assert v["status"] == "FAIL" and v["reproduction"]["status"] == "FAIL" and "known_at" not in v       # nothing of the premium was touched
    assert not Path("output/ceiling_coinbase/screen.parquet").exists() and "VOID" in Path("output/ceiling_coinbase.md").read_text()
    sc_p2.to_parquet(saved / "ic.parquet", index=False)                                           # the saved screen matches …
    with pytest.raises(SystemExit) as e:                                                          # … but a registered name without the source fails coverage
        cx.run(5.0, 2.0, "test", PAIRS, liquid=LIQ + ["WLDUSDT"], cover_min=cx.COVER_MIN | {"WLDUSDT": 0.9}, **kw)
    v = json.loads(Path("output/ceiling_coinbase/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["known_at"]["status"] == "PASS" and v["coverage"]["status"] == "FAIL"
    assert v["coverage"]["under_minimum"] == {"WLDUSDT": 0.0} and not Path("output/ceiling_coinbase/screen.parquet").exists()
    md = cx.run(5.0, 2.0, "test", PAIRS, **kw)
    v = json.loads(Path("output/ceiling_coinbase/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == 12 and v["reproduction"]["null_rows_compared"] == 5 * 3 * 2
    assert v["known_at"]["recomputed"] == 100 and v["coverage"]["by_name"]["XRPUSDT"] > 0.9 and v["registered_names"] == LIQ
    rows = pd.read_parquet("output/ceiling_coinbase/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    d = g.loc[DEV, "relative", "1d"]
    assert d["ic"] < -0.3 and d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE"       # five draws cannot certify anything
    assert d["bar_maker"] > 0 and d["bar_taker"] > d["bar_maker"] and d["ic_F1"] < -0.3 and np.isnan(d["ic_F2"]) and bool(d["folds_same_sign"]) is False
    assert g.loc[DEV, "relative", "4h"]["verdict"].endswith("(reported, not gated)") and np.isnan(g.loc[DEV, "relative", "1h"]["p_fw_shift"])
    assert np.isfinite(g.loc[DEV, "relative", "1h"]["p_single_shift"]) and np.isfinite(g.loc[LVL, "directional", "1d"]["p_single_shuffle"])
    assert g.loc[LVL, "relative", "1d"]["verdict"].startswith("described") and g.loc[cx.P2_ROW, "relative", "1d"]["verdict"].startswith("validity")
    assert g.loc[f"{DEV}_zec", "relative", "1d"]["verdict"].startswith("described (ZEC") and np.isnan(g.loc[f"{DEV}_zec", "relative", "1d"]["p_family"])
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R60's gate" in md and "ZECUSDT" in md
    for f_ in ("null_shuffle", "null_shift", "ic_daily", "move_vs_cost", "names"):
        assert Path(f"output/ceiling_coinbase/{f_}.parquet").exists()
    names = pd.read_parquet("output/ceiling_coinbase/names.parquet").set_index("symbol")
    assert "ZECUSDT" in names.index and abs(names.loc["BTCUSDT", "lvl_mean_bps"] - 3.0) < 0.5
