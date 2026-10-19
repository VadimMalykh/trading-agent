"""varmonth (decision AQ2's described row) on planted markets: the calendar's last Fridays; a planted GBM at a realised vol below the
straddle's own break-even vol reads the Black–Scholes gain of the short hedged straddle within its se, and at the break-even vol about
zero; the costs are what the arithmetic says; a planted month file goes through `month_row` with its skips by cause."""
import json

import numpy as np
import pandas as pd

from ft2 import varmonth as vm

HOURS = 30 * 24


def test_monthly_expiries_are_the_last_fridays_at_0800():
    ex = vm.monthly_expiries(pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-04-30", tz="UTC"))
    assert [str(e.date()) for e in ex] == ["2024-01-26", "2024-02-23", "2024-03-29", "2024-04-26"]
    assert all(e.hour == 8 and e.dayofweek == 4 for e in ex)
    pairs = vm.month_pairs("BTC", pd.Timestamp("2020-08-01", tz="UTC"))
    assert [str(a.date()) for a, _ in pairs] == ["2020-05-29", "2020-06-26"] and str(pairs[-1][1].date()) == "2020-07-31"


def _paths(sigma: float, n_paths: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dt = 1 / 8760.0
    lr = rng.normal(-0.5 * sigma ** 2 * dt, sigma * np.sqrt(dt), size=(n_paths, HOURS))
    return 100.0 * np.exp(np.concatenate([np.zeros((n_paths, 1)), np.cumsum(lr, axis=1)], axis=1))     # HOURS + 1 points, the last the settlement


def _month(path: np.ndarray, sigma_q: float, half_spread_bps=0.0, touch_bps=0.0) -> dict:
    T = HOURS / 8760.0
    m = vm.BS_FACTOR * sigma_q * np.sqrt(T)
    return vm.price_month(path, 100.0, m / 2, m / 2, half_spread_bps, touch_bps)


def test_a_short_straddle_hedged_daily_earns_the_vega_times_the_vol_gap_and_nothing_at_the_breakeven_vol():
    sig_q, sig_r = 0.6, 0.4
    rows = [_month(p, sig_q) for p in _paths(sig_r, 400)]
    g = np.array([r["gross_daily"] for r in rows])
    expected = 1e4 * vm.BS_FACTOR * np.sqrt(HOURS / 8760.0) * (sig_q - sig_r)          # vega × the vol gap, first order: ≈ 459 bps
    se = g.std() / np.sqrt(len(g))
    assert abs(g.mean() - expected) < max(3 * se, 0.15 * expected), (g.mean(), expected, se)
    h = np.array([r["gross_hourly"] for r in rows])
    assert abs(h.mean() - expected) < max(3 * h.std() / np.sqrt(len(h)), 0.15 * expected) and h.std() < g.std()     # the hourly hedge replicates closer
    flat = np.array([_month(p, sig_r)["gross_daily"] for p in _paths(sig_r, 400, seed=1)])
    assert abs(flat.mean()) < 3 * flat.std() / np.sqrt(len(flat)) + 15
    r = rows[0]
    assert r["sigma_q"] == sig_q * 1.0 or abs(r["sigma_q"] - sig_q) < 1e-9
    assert abs(r["rv_month"] - sig_r) < 0.1 and r["hours"] == HOURS and abs(r["net_daily"] - (r["gross_daily"] - r["fee_entry_bps"] - r["fee_delivery_bps"])) < 1e-9


def test_the_costs_are_the_arithmetic_and_the_sensitivity_row_doubles_the_crossing():
    p = _paths(0.5, 1)[0]
    a = _month(p, 0.6)
    b = _month(p, 0.6, half_spread_bps=6.0, touch_bps=20.0)
    assert a["hedge_cost_daily"] == 0 and b["hedge_cost_daily"] > 0 and b["hedge_cost_hourly"] > b["hedge_cost_daily"]
    assert abs(b["crossing_bps"] - 10.0) < 1e-9 and abs((b["net_daily"] - b["net_daily_2x"]) - 10.0) < 1e-9
    assert abs((b["gross_daily"] - b["net_daily"]) - (b["hedge_cost_daily"] + b["crossing_bps"] + b["fee_entry_bps"] + b["fee_delivery_bps"])) < 1e-9
    m = a["m"]
    assert abs(a["fee_entry_bps"] - 1e4 * 2 * min(vm.FEE_ENTRY, vm.FEE_CAP * m / 2)) < 1e-9


def _month_json(cur="BTC", legs=True, trade_before=True, parity_ok=True, settle_bars=30):
    e_prev, e = pd.Timestamp("2024-01-26 08:00", tz="UTC"), pd.Timestamp("2024-02-23 08:00", tz="UTC")
    t0 = e_prev + pd.Timedelta(hours=1)
    n = int((e - t0) / pd.Timedelta(hours=1))
    ticks = [int((e_prev - pd.Timedelta(hours=1)).timestamp() * 1000) + i * vm.HOUR_MS for i in range(n + 2)]
    close = [40000.0 + 10 * i for i in range(n + 2)]
    perp = {"status": "ok", "ticks": ticks, "open": close, "close": close, "volume": [1] * len(ticks)}
    sett = {"status": "ok", "ticks": list(range(settle_bars)), "close": [41000.0] * settle_bars, "volume": [1] * settle_bars}
    ms0 = int(t0.timestamp() * 1000)
    spot = 40000.0 + 10 * 1          # the close of the bar ending at 09:00: index 1
    k = 40000
    c, p = (0.06, 0.06) if parity_ok else (0.08, 0.02)
    lt = [ms0 - 2 * vm.HOUR_MS] if trade_before else [ms0 + vm.HOUR_MS]
    leg = lambda px: {"status": "ok", "ticks": lt, "open": [px], "close": [px], "volume": [3]}     # noqa: E731
    j = {"currency": cur, "expiry": str(e), "prev_expiry": str(e_prev), "entry": str(t0), "perp_1h": perp, "settle_1m": sett, "spot": spot, "strike": k,
         "legs": {"C": {"name": "BTC-23FEB24-40000-C", "chart": leg(c)}, "P": {"name": "BTC-23FEB24-40000-P", "chart": leg(p)}} if legs else None, "tried": []}
    return j


def test_a_planted_month_file_is_priced_and_the_skips_are_by_cause(tmp_path, monkeypatch):
    row, path = vm.month_row(_month_json())
    assert row["covered"] and path is not None and len(path) == row["hours"] + 1 and path[-1] == 41000.0 and row["path_missing"] == 0
    assert row["c_last"] == 0.06 and abs(row["parity"] - (0 - (row["spot"] - 40000) / row["spot"])) < 1e-9
    assert vm.month_row(_month_json(legs=False))[0]["skip"] == "no served pair"
    assert vm.month_row(_month_json(trade_before=False))[0]["skip"] == "a leg without a trade in the 24 h before"
    assert vm.month_row(_month_json(parity_ok=False))[0]["skip"] == "parity"
    assert vm.month_row(_month_json(settle_bars=10))[0]["skip"] == "settlement window short"
    # the run on the planted file, the touch given (no network), no cost table
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "data" / "raw" / "external" / "deribit" / "varmonth" / "BTC"
    raw.mkdir(parents=True)
    (raw / "2024-02-23.json").write_text(json.dumps(_month_json()))
    (raw / "2024-03-29.json").write_text(json.dumps(_month_json(parity_ok=False)))
    monkeypatch.setattr(vm, "RAW", tmp_path / "data" / "raw" / "external" / "deribit" / "varmonth")
    monkeypatch.setattr(vm, "OUT", tmp_path / "output" / "varmonth")
    md = vm.run("t", currencies=("BTC",), touch={"BTC": {"touch_bps": 20.0, "measured": True}})
    months = pd.read_csv(tmp_path / "output" / "varmonth" / "t" / "months.csv")
    assert len(months) == 2 and months["covered"].sum() == 1 and "parity" in md and "| all | net_daily | 1 |" in md
    v = json.loads((tmp_path / "output" / "varmonth" / "t" / "validity.json").read_text())
    assert v["covered"]["BTC"] == 1 and v["skips"]["BTC"]["parity"] == 1 and v["touch"]["BTC"]["touch_bps"] == 20.0
    assert months.loc[months["covered"], "fold"].iloc[0] == "F2" and months.loc[months["covered"], "year"].iloc[0] == 2024
