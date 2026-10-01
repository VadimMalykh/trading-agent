"""P8 (B3′) — the ETF flows as per-name information (`ft2/audit_index.py` family "etf", registration R27): a flow stamped d is
not seen before d + 1 09:00 UTC; beta × flow has the order of the betas on an inflow day and the reverse on an outflow day;
the large-flow cut; own_flow's shape; the halves of one fold; the cut grid and its shift count; the read finds a planted
flow effect on a synthetic market and the twelve's labels are the run's."""
import json

import numpy as np
import pandas as pd

from ft2 import audit, audit_index, folds, horizon, screen
from ft2 import backtest as bt
from ft2.ceiling import BAR

from test_p8_screen import RIGHT, TRAIN, WRONG, _members

NAMES = [*RIGHT, *WRONG]
HOLD = 12
BTC = "A0USDT"                                             # the test's bitcoin: a member, so the twelve's universe holds it


def _flows(days: pd.DatetimeIndex, totals: np.ndarray) -> pd.Series:
    return pd.Series(totals, index=days)


def test_a_flow_is_known_from_nine_utc_the_next_day_and_beta_times_flow_has_the_betas_order(monkeypatch):
    monkeypatch.setattr(audit_index, "BETA_MIN_HOURS", 60)
    monkeypatch.setattr(audit_index, "BTC_COL", [BTC])
    rng = np.random.default_rng(2)
    hours = pd.date_range("2024-01-01", "2024-02-12", freq="1h", tz="UTC")
    rb = rng.normal(0, 30, len(hours))
    btc_h = pd.Series(100 * np.exp(np.cumsum(rb) / 1e4), index=hours)
    b_true = {BTC: 1.0, "A1USDT": 2.0, "B0USDT": -1.0, "B1USDT": 0.5}
    close_h = pd.DataFrame({k: btc_h if k == BTC else 100 * np.exp(np.cumsum(b * rb + rng.normal(0, 15, len(hours))) / 1e4) for k, b in b_true.items()}, index=hours)
    days = pd.bdate_range("2024-01-02", "2024-02-09", tz="UTC")
    tot = np.where(np.arange(len(days)) % 2 == 0, 400.0, -120.0)          # inflow 400 on even days, outflow 120 on odd ones
    flows = _flows(days, tot)
    cols = list(b_true)
    F, R, own = audit_index.features_etf(hours, cols, close_h, btc_h, flows, hours[-1] + pd.Timedelta("1h"), beta_days=10)
    at = lambda ts: hours.get_loc(pd.Timestamp(ts, tz="UTC"))                                           # noqa: E731
    # known-at: Tuesday 2024-01-02's flow (400) is seen from Wednesday 09:00, not at 08:00; before any flow is known, NaN
    assert np.isnan(own["F"][at("2024-01-03 08:00")]) and own["F"][at("2024-01-03 09:00")] == 400.0 and own["F"][at("2024-01-04 08:00")] == 400.0
    assert own["F"][at("2024-01-04 09:00")] == -120.0
    i_fri = list(days).index(pd.Timestamp("2024-01-05", tz="UTC"))
    assert own["F"][at("2024-01-06 12:00")] == tot[i_fri] and own["F"][at("2024-01-08 08:00")] == tot[i_fri]      # the weekend and Monday morning carry Friday's
    assert np.isnan(own["F5"][at("2024-01-05 12:00")]) and own["F5"][at("2024-01-09 12:00")] == tot[:5].sum()      # five known days from the fifth day's morning
    later = flows.copy()
    later[later.index >= pd.Timestamp("2024-01-10", tz="UTC")] += 1000                                            # a later day's flow changes nothing before it is known
    F2, _, own2 = audit_index.features_etf(hours, cols, close_h, btc_h, later, hours[-1] + pd.Timedelta("1h"), beta_days=10)
    cut = at("2024-01-11 09:00")
    assert np.array_equal(own["F"][:cut], own2["F"][:cut], equal_nan=True) and own2["F"][cut] == own["F"][cut] + 1000
    # beta: BTC's own is NaN (by definition 1); the others near their planted slope
    t = hours[-1]
    assert np.isnan(R["beta_btc"].loc[t, BTC]) and abs(R["beta_btc"].loc[t, "A1USDT"] - 2.0) < 0.2 and abs(R["beta_btc"].loc[t, "B0USDT"] + 1.0) < 0.2
    # order: on an inflow day bflow ranks as beta; on an outflow day the reverse
    tin, tout = pd.Timestamp("2024-02-08 12:00", tz="UTC"), pd.Timestamp("2024-02-09 12:00", tz="UTC")        # Wed 02-07 (index 26, even: +400) known Thu; Thu (odd) known Fri
    assert own["F"][at("2024-02-08 12:00")] == 400.0 and own["F"][at("2024-02-09 12:00")] == -120.0
    others = ["A1USDT", "B0USDT", "B1USDT"]
    assert F["bflow"].loc[tin, others].rank().tolist() == R["beta_btc"].loc[tin, others].rank().tolist()
    assert F["bflow"].loc[tout, others].rank().tolist() == (4 - R["beta_btc"].loc[tout, others].rank()).tolist()
    # the cut: |F| ≥ 300 keeps the inflow day and drops the outflow day; the surprise is F minus the mean of the five before
    assert np.isfinite(F["bflow_big"].loc[tin, "A1USDT"]) and np.isnan(F["bflow_big"].loc[tout, "A1USDT"]) and own["big"][at("2024-02-08 12:00")] and not own["big"][at("2024-02-09 12:00")]
    assert np.isclose(own["S"][at("2024-02-08 12:00")], 400.0 - np.mean(tot[21:26]))
    # own_flow: F for BTC, 0 for the others, NaN before a flow is known
    assert F["own_flow"].loc[tin, BTC] == 400.0 and (F["own_flow"].loc[tin, others] == 0).all() and F["own_flow"].loc[pd.Timestamp("2024-01-02", tz="UTC")].isna().all()


def test_the_halves_and_the_cut_grids_shift_count():
    assert audit_index.gap_days() == 32 and len(horizon.shifts(242, 32)) == 179
    dates = pd.date_range("2024-01-03", "2024-08-31", freq="D", tz="UTC")
    p = audit_index._parts(dates, ["F2"], "etf")
    assert (p[dates < "2024-05-01"] == "H1").all() and (p[dates >= "2024-05-01"] == "H2").all() and len(dates) == 242
    d1 = pd.date_range("2023-05-03", "2023-08-06", freq="D", tz="UTC")
    q = audit_index._parts(d1, ["F1"], "etf")                                                                # another fold: the middle of the days read
    assert set(q) == {"H1", "H2"} and abs((q == "H1").sum() - (q == "H2").sum()) <= 2
    r = audit_index._parts(dates, ["F1", "F2"], "index")
    assert set(r[dates >= "2024-01-01"]) == {"F2"}


def _synth_flow(days: int = 140, start: str = "2023-03-20", seed: int = 9, kappa: float = 2.0):
    """A market whose names move with the test's bitcoin hour by hour (RIGHT +1.5, WRONG −1.5, the training names +0.5), and
    whose next hour also carries κ × that sensitivity × yesterday's flow once it is known (the planted effect); the bitcoin
    itself carries its own flow, which the others do not inherit (own_flow's plant). The flows: random, one a weekday."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 24, freq="1h")
    bdays = pd.bdate_range(hours[0], hours[-1], tz="UTC")
    tot = rng.normal(50, 350, len(bdays)).round(1)
    pd.DataFrame({"asset": "BTC", "day": np.repeat(bdays, 2), "fund": ["IBIT", "Total"] * len(bdays), "flow_musd": np.repeat(tot, 2), "holiday": False}).to_parquet("data/etf_flows.parquet", index=False)
    known = pd.DatetimeIndex(bdays) + audit_index.FLOW_KNOWN
    i = known.searchsorted(hours, side="right") - 1
    Fk = np.where(i >= 0, tot[np.clip(i, 0, None)], 0.0) / 100.0                                               # the flow known at each hour, in US$100m
    rb = rng.normal(0, 30, len(hours))                                                                          # what every name shares
    t5 = pd.date_range(hours[0] - pd.Timedelta("55min"), periods=days * 288, freq="5min")
    c5, fund, cost = [], [], []
    for k, sym in enumerate([*TRAIN, *NAMES]):
        b = 1.5 if sym in RIGHT else (-1.5 if sym in WRONG else 0.5)
        rh = rb + 40.0 * np.r_[0.0, Fk[:-1]] if sym == BTC else b * rb + kappa * b * np.r_[0.0, Fk[:-1]] * 10 + rng.normal(0, 25, len(hours))   # BTC alone: yesterday's flow, its own
        r5 = np.repeat(rh / 12, 12)
        px = 100 * (k + 1) * np.exp(np.cumsum(r5) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def test_the_read_finds_the_planted_flow_effect_on_the_cut_grid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth_flow()
    _members(tmp_path / "m.csv")
    monkeypatch.setattr(audit_index, "BETA_DAYS", 10)
    monkeypatch.setattr(audit_index, "BETA_MIN_HOURS", 60)
    monkeypatch.setattr(audit_index, "BTC_COL", [BTC])
    monkeypatch.setattr(audit_index, "TWELVE_RUN", "transfer")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [*TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")
    txt = audit_index.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1, family="etf", fold_names=["F1"])
    out = audit_index.OUT / "transfer_etf"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["family"] == "etf" and v["folds"] == ["F1"] and v["shifts"] == v["days"] - 2 * 12 + 1 and "**PASS**" in txt
    tab = pd.read_csv(out / "features.csv").set_index(["universe", "feature"])
    assert len(tab) == 7 and list(tab.loc["twelve"].index) == audit_index.ETF_FEATURES["twelve"] and "own_flow" not in tab.loc["outside"].index
    assert {"ic_H1", "ic_H2", "parts_same_sign"} <= set(tab.columns)
    assert (tab["coverage"].drop(index=("outside", "bflow_big")).drop(index=("twelve", "bflow_big")) > 0.85).all() and tab.loc[("outside", "bflow_big"), "coverage"] < 0.6
    for uni in ("outside", "twelve"):
        r = tab.loc[(uni, "bflow")]
        assert r["ic"] > 0.1 and r["u"] > 3 and r["p_family"] <= 0.05 and r["verdict"] == "CLEARS" and r["parts_same_sign"], (uni, r)
    assert tab.loc[("twelve", "own_flow"), "ic"] > 0.05, tab.loc[("twelve", "own_flow")]                        # BTC ahead of the others after an inflow day
    ref = pd.read_csv(out / "reference.csv").set_index(["universe", "row"])
    assert ref.loc[("outside", "beta_btc after an inflow day (F > 0)"), "ic"] > 0.1 and ref.loc[("outside", "beta_btc after an outflow day (F < 0)"), "ic"] < -0.1
    assert {"beta_btc", "bflow_sur", "bflow_5d_sur", "bflow_big_sur", "the run's forecast (R18's candle ridge)"} <= set(ref.loc["outside"].index)
    assert (audit_index.OUT / "twelve_etf" / "audit.md").exists()
    # the cut: a run over F1 read on F1 is the whole run; a cut to a fold the run never scored is refused by its empty grid
    A = audit.frame("transfer", str(tmp_path / "m.csv"))
    C = audit_index._cut(A, ["F1"])
    assert C["grid"].equals(A["grid"]) and C["validity"]["cells_in_folds"] == A["validity"]["cells"]
    # the twelve's check against a run's decisions counts a decision in a fold not read apart, not as off the grid
    dec = pd.read_parquet(bt.OUT / "transfer" / "forecast.parquet").query("group == 0")[["t", "symbol"]].iloc[::9]
    f0 = pd.DataFrame({"t": [pd.Timestamp("2023-04-20 10:00", tz="UTC")] * 2, "symbol": NAMES[:2]})            # F0: not read
    (bt.OUT / "dec_f0").mkdir()
    pd.concat([f0, dec]).to_parquet(bt.OUT / "dec_f0" / "decisions.parquet", index=False)
    vd = audit_index.cells_twelve(NAMES, ["F1"], HOLD, run="dec_f0")["validity"]
    assert vd["status"] == "PASS" and vd["run_cells_outside_folds"] == 2 and vd["run_cells_off_grid"] == 0 and vd["run_cells"] == len(dec), vd
