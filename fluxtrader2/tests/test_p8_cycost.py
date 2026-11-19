"""Decision CY1's arithmetic (`ft2/cycost.py`) on planted rows: the regression recovers a planted relation and weighs every NAME the
same; the held-out check passes on names that follow the fit and fails on names that do not; the rebuild touches only its targets
and only the names priced by the wide file; the re-pricing reproduces `backtest.price`'s other cost from the old file, moves the
nets by the difference alone, and says so when the old file does not reproduce a stored cost."""
import numpy as np
import pandas as pd

from ft2 import cxcost, cycost

B = {"spread_cal_bps": [1.0, 0.2, -0.1, 0.5], "imp_1000": [8.0, 0.3, -0.6, 0.1], "imp_2500": [8.5, 0.3, -0.6, 0.1], "imp_5000": [9.0, 0.3, -0.6, 0.1], "imp_10000": [9.5, 0.3, -0.6, 0.1]}


def rows(names, n, rng, mult=1.0, noise=0.0):
    f = pd.DataFrame({"symbol": np.repeat(names, n), "range_bps": rng.uniform(100, 900, len(names) * n), "dollar_vol": np.exp(rng.uniform(15, 20, len(names) * n)),
                      "tick_bps": rng.uniform(0.01, 0.3, len(names) * n)})        # the tick under every planted spread: the floor does not bind
    X = cycost._X(f)
    for tg, b in B.items():
        f[tg] = np.exp(X @ np.array(b) + noise * rng.standard_normal(len(f))) * (mult if tg != "spread_cal_bps" else 1.0)
    for k in cxcost.NOTIONALS:
        f[f"cens_{k}"] = False
    f["tier"] = pd.cut(f["dollar_vol"], cxcost.TIER_EDGES, labels=cxcost.TIER_LABELS, right=False)
    return f


def test_fit_recovers_the_planted_relation_and_weighs_names_not_rows():
    rng = np.random.default_rng(0)
    m = rows([f"N{i}" for i in range(8)], 50, rng)
    c = cycost.fit(m)
    assert all(np.allclose(c[tg], B[tg], atol=1e-8) for tg in B)
    p = cycost.predict(c, m)
    assert np.allclose(p["imp_10000"], m["imp_10000"]) and (p["spread_cal_bps"] >= m["tick_bps"]).all()
    big, small = rows(["BIG"], 5000, rng), rows([f"S{i}" for i in range(9)], 20, rng, mult=np.e)      # one name with 5,000 rows, nine names e times dearer
    c2 = cycost.fit(pd.concat([big, small], ignore_index=True), ["imp_10000"])
    lift = float(np.log(cycost.predict(c2, big)["imp_10000"] / big["imp_10000"]).mean())
    assert abs(lift - 0.9) < 0.1                                               # the level is the names' mean (9 of 10 names are e times dearer), not the rows' (0.035)


def test_check_passes_on_names_like_the_fit_and_fails_on_names_that_are_not():
    rng = np.random.default_rng(1)
    tw = rows([f"T{i}" for i in range(12)], 200, rng, noise=0.1).drop(columns=["tier"])
    wd = rows([f"W{i:03d}" for i in range(60)], 8, rng, mult=0.5, noise=0.2)
    wd["dollar_vol"] = np.exp(rng.uniform(np.log(6e6), np.log(2e8), len(wd)))   # every rule tier populated
    X = cycost._X(wd)
    for tg, b in B.items():
        wd[tg] = np.exp(X @ np.array(b)) * (0.5 if tg != "spread_cal_bps" else 1.0)
    wd["tier"] = pd.cut(wd["dollar_vol"], cxcost.TIER_EDGES, labels=cxcost.TIER_LABELS, right=False)
    t = cycost.check_tables(tw, wd)
    assert t["status"] == "PASS" and t["fit_names"] == 30 and t["held_names"] == 30
    assert ((t["main"].loc[cxcost.RULE_TIERS, "ratio_10000"] - 1).abs() < 0.25).all()
    a, b_ = cycost.halves(wd["symbol"])
    bad = wd.copy()
    bad.loc[bad["symbol"].isin(b_), [f"imp_{n}" for n in cxcost.NOTIONALS]] *= 6.0      # the held-out names six times dearer than the fit half
    assert cycost.check_tables(tw, bad)["status"] == "FAIL"


def test_k_fixed_changes_the_lowest_bin_only():
    v = pd.DataFrame({"k": [1e11, 0.9, 0.7, 0.8, 0.96, 1.0], "k_mean": [0.58, 0.64, 0.71, 0.86, 0.97, 1.0]}, index=cxcost.F_LABELS)
    k = cycost.k_fixed(v)
    assert k["<0.02"] == 0.58 and list(k.iloc[1:]) == [0.9, 0.7, 0.8, 0.96, 1.0]
    assert np.isfinite(cxcost.est_impact(9_000, 2_000, 9_000, 3.0)) and np.isnan(cxcost.est_impact(10_000, 2_000, 9_000, 3.0))      # the bound is the band's end


def wide_file(rng):
    w = rows(["AAAUSDT", "BBBUSDT", "BTCUSDT"], 4, rng)[["symbol", "range_bps", "dollar_vol", "tick_bps", "spread_cal_bps", "imp_10000", "imp_5000", "imp_2500", "imp_1000"]]
    w["day"] = np.tile(pd.date_range("2026-03-01", periods=4, tz="UTC"), 3)
    w["imp_25000"], w["spread_src"], w["px"] = w["imp_10000"] * 2, "proxy_wide", 1.0
    return w


def test_rebuild_touches_only_its_targets_and_only_the_wide_names():
    rng = np.random.default_rng(2)
    w = wide_file(rng)
    coef = {tg: [x * 0.9 for x in b] for tg, b in B.items()}
    o = cycost.apply(w, coef, keep={"BTCUSDT"})
    btc = (w["symbol"] == "BTCUSDT").to_numpy()
    assert o[btc].equals(w[btc])
    assert (o.loc[~btc, "spread_src"] == cycost.SRC).all() and o[["range_bps", "dollar_vol", "tick_bps", "imp_25000", "px", "day", "symbol"]].equals(w[["range_bps", "dollar_vol", "tick_bps", "imp_25000", "px", "day", "symbol"]])
    assert np.allclose(o.loc[~btc, "imp_10000"], cycost.predict(coef, w[~btc])["imp_10000"]) and not np.allclose(o.loc[~btc, "imp_10000"], w.loc[~btc, "imp_10000"])


def test_reprice_reproduces_the_old_cost_and_moves_the_net_by_the_difference():
    rng = np.random.default_rng(3)
    w = wide_file(rng)
    new = w.assign(imp_10000=w["imp_10000"] * 0.4)
    keep = {"BTCUSDT"}
    lo, ln = cycost.leg_table(w, keep), cycost.leg_table(new, keep)
    f = pd.DataFrame({"symbol": ["AAAUSDT", "BBBUSDT", "BTCUSDT", "AAAUSDT"], "entry_t": pd.to_datetime(["2026-03-01 00:05", "2026-03-02 13:00", "2026-03-01 00:05", "2026-03-03 23:55"], utc=True),
                      "exit_t": pd.to_datetime(["2026-03-02 00:05", "2026-03-03 13:00", "2026-03-02 00:05", "2026-03-04 23:55"], utc=True), "entry_px": [10.0, 2.0, 5.0, 10.0], "exit_px": [11.0, 1.8, 5.0, 9.0]})
    f["other_cost_bps"] = cycost.other_cost(f, lo)
    f.loc[2, "other_cost_bps"] = 3.3                                           # a tape pair: its cost is not the wide file's
    e0, x0 = lo[("AAAUSDT", pd.Timestamp("2026-03-01", tz="UTC"))], lo[("AAAUSDT", pd.Timestamp("2026-03-02", tz="UTC"))]
    assert np.isclose(f.loc[0, "other_cost_bps"], e0 + x0 * 1.1)               # entry-day leg + exit-day leg × exit / entry
    f["net_bps"], f["hedged_net_bps"] = 20.0 - f["other_cost_bps"], 15.0 - f["other_cost_bps"]
    g, v = cycost.reprice(f, lo, ln, keep)
    assert v["ok"] and v["wide_positions"] == 3 and v["old_file_max_dev_bps"] < 1e-9
    assert g.loc[2].equals(f.loc[2])
    d = f["other_cost_bps"] - g["other_cost_bps"]
    assert (d[[0, 1, 3]] > 0).all() and np.allclose(g["net_bps"] - f["net_bps"], d) and np.allclose(g["hedged_net_bps"] - f["hedged_net_bps"], d)
    assert np.allclose(g["other_cost_bps"][[0, 1, 3]], cycost.other_cost(f, ln)[[0, 1, 3]])
    f.loc[1, "other_cost_bps"] += 0.01                                         # a stored cost the old file does not give: the arithmetic is not valid
    assert not cycost.reprice(f, lo, ln, keep)[1]["ok"]


def test_the_frozen_coefficients_are_the_five_targets():
    import json
    from ft2 import cost
    j = json.loads(cost.CY1_COEF.read_text())
    assert set(j["coef"]) == set(cycost.TARGETS) and all(len(v) == 4 for v in j["coef"].values()) and j["features"] == ["const", *cost.WIDE_FEATURES]
    assert -1.1 < j["coef"]["imp_10000"][2] < -0.8                              # the impact falls about one for one with the day's dollar volume
