"""P8 (B3) — the US index as per-name information (`ft2/audit_index.py`, registration R26): a minute is known a minute after
its stamp and the index is open within 15 minutes of its last minute; the move features follow the open/closed rule and
bx_gap is the move into the close; beta is the least-squares slope on the open hours of its window; the shifts keep their
distance; the read finds the planted feature on a synthetic market and its labels are the run's."""
import json

import numpy as np
import pandas as pd

from ft2 import audit, audit_index, horizon, screen
from ft2 import backtest as bt
from ft2.ceiling import BAR

from test_p8_screen import BLOCKS, RIGHT, TRAIN, WRONG, _members

NAMES = [*RIGHT, *WRONG]
HOLD = 12                                                  # the tests' hold: an hour
MIN = pd.Timedelta("1min")


def _minutes(hours: pd.DatetimeIndex, lc_end: np.ndarray, u: np.ndarray, is_open: np.ndarray, sym: str = "US100") -> pd.DataFrame:
    """Traded minutes of the open hours: the hour's log return `u` spread evenly over its 60 minutes, so that the close of
    minute (t − 1 min) is exp(lc_end[t])."""
    rows = []
    for h, e, r, o in zip(hours, lc_end, u, is_open):
        if o:
            mm = np.arange(60)
            rows.append(pd.DataFrame({"symbol": sym, "ts": h - pd.Timedelta("1h") + mm * MIN, "close": np.exp(e - r + r * (mm + 1) / 60)}))
    m = pd.concat(rows, ignore_index=True)
    for c in ("open", "high", "low"):
        m[c] = m["close"]
    return m


def _open_mask(hours: pd.DatetimeIndex) -> np.ndarray:
    """The hour ending at t is open on weekdays except 21:00–22:00 (the daily break), from Sunday 23:00, until Friday 21:00."""
    end_h, wd = hours.hour, hours.dayofweek                   # the hour ending at t: its minutes are t−1h … t−1min
    o = (wd < 5) & (end_h != 21) & (end_h != 22) & ~((wd == 4) & (end_h == 23))      # Sunday 23:00–24:00 ends Monday 00:00 (wd 0, end_h 0): open
    o |= (wd == 6) & (end_h == 23)                                                     # Sunday 22:00–23:00
    return np.asarray(o)


def test_the_minute_in_force_is_known_a_minute_after_its_stamp_and_open_within_fifteen():
    h = pd.date_range("2023-05-01 10:00", periods=60, freq="1min", tz="UTC")
    m = pd.DataFrame({"ts": [*h, *pd.date_range("2023-05-01 12:30", periods=300, freq="1min", tz="UTC")], "close": np.exp(np.linspace(0, 0.36, 360))})
    mi = audit_index.Minutes(m)
    s = pd.DatetimeIndex([pd.Timestamp("2023-05-01 09:00", tz="UTC"), pd.Timestamp("2023-05-01 10:30:30", tz="UTC"), pd.Timestamp("2023-05-01 10:30", tz="UTC"),
                          pd.Timestamp("2023-05-01 11:30", tz="UTC"), pd.Timestamp("2023-05-01 17:30", tz="UTC")])
    a = mi.at(s)
    assert a["row"][0] == -1 and np.isnan(a["lc"][0]) and not a["open"][0]
    assert a["row"][1] == 29 and a["age_min"][1] == 1.5 and a["open"][1]                       # 10:29 is in force at 10:30:30; 10:30's close is not yet known
    assert a["row"][2] == 29 and a["age_min"][2] == 1.0                                         # at 10:30 exactly: 10:29 (known from 10:30), not 10:30
    assert a["row"][3] == 59 and a["age_min"][3] == 31.0 and not a["open"][3]                   # the gap: the last minute is 31 min old → closed
    assert a["row"][4] == 359 and a["open"][4] and np.isclose(a["gap"][4], mi.lc[359] - mi.lc[359 - audit_index.GAP_MINUTES])
    assert np.isnan(a["gap"][1])                                                                # fewer than 240 traded minutes before it
    later = m.copy()
    later.loc[later["ts"] >= pd.Timestamp("2023-05-01 10:30", tz="UTC"), "close"] *= 2          # a minute stamped at s or later changes nothing at s
    b = audit_index.Minutes(later).at(s[:3])
    assert np.array_equal(a["lc"][:3], b["lc"], equal_nan=True)


def test_the_features_follow_the_open_closed_rule_and_beta_is_the_slope_on_open_hours(monkeypatch):
    monkeypatch.setattr(audit_index, "BETA_MIN_HOURS", 60)
    rng = np.random.default_rng(1)
    hours = pd.date_range("2023-04-03", "2023-05-15", freq="1h", tz="UTC")                        # Monday → Monday
    is_open = _open_mask(hours)
    u = np.where(is_open, rng.normal(0, 30e-4, len(hours)), 0.0)
    lc_end = np.cumsum(u)
    mi = audit_index.Minutes(_minutes(hours, lc_end, u, is_open))
    b_true = {"A": 2.0, "B": -1.0, "C": 0.0}
    r = {k: b * u * 1e4 + rng.normal(0, 20, len(hours)) for k, b in b_true.items()}
    close_h = pd.DataFrame({k: 100 * np.exp(np.cumsum(v) / 1e4) for k, v in r.items()}, index=hours)
    F, own = audit_index.features_index(hours, list(b_true), close_h, hours[-1] + MIN, beta_days=10, minutes=mi)
    t = hours[-1]                                                                                  # Monday 00:00: the hour ending here is open
    for k, b in b_true.items():
        assert abs(F["beta"].loc[t, k] - b) < 0.15, (k, F["beta"].loc[t, k])
    # beta against a plain least-squares fit on the same rows: the last 240 hours ending ≤ t with the index open at both ends
    w = hours[(hours > t - pd.Timedelta(hours=240)) & (hours <= t)]
    x = pd.Series(np.where(is_open & np.r_[False, is_open[:-1]], u * 1e4, np.nan), index=hours).loc[w]
    y = (np.log(close_h["A"]) - np.log(close_h["A"]).shift(1)).loc[w] * 1e4
    ok = x.notna() & y.notna()
    assert ok.sum() > 100 and np.isclose(F["beta"].loc[t, "A"], np.polyfit(x[ok], y[ok], 1)[0], atol=1e-9)
    # the rule: 1h and 4h need both ends open; 24h the end; gap the end closed
    at = lambda ts: pd.Timestamp(ts, tz="UTC")                                                     # noqa: E731
    fri, sat, mon = at("2023-05-12 15:00"), at("2023-05-13 10:00"), at("2023-05-15 00:00")
    assert np.isfinite(F["bx_1h"].loc[fri, "A"]) and np.isclose(F["bx_1h"].loc[fri, "A"], F["beta"].loc[fri, "A"] * own["m_1h"][hours.get_loc(fri)])
    assert np.isclose(own["m_1h"][hours.get_loc(fri)], u[hours.get_loc(fri)] * 1e4)                 # the hour's own return
    assert np.isnan(F["bx_1h"].loc[at("2023-05-12 21:00"), "A"]) and np.isnan(F["bx_1h"].loc[at("2023-05-11 23:00"), "A"])      # closed at t; open at t, closed at t − 1h
    assert np.isfinite(F["bx_1h"].loc[at("2023-05-12 00:00"), "A"]) and np.isnan(F["bx_4h"].loc[at("2023-05-12 02:00"), "A"])   # 4h: t − 4h is 22:00, closed
    assert np.isfinite(F["bx_4h"].loc[at("2023-05-12 04:00"), "A"])
    assert F["bx_gap"].loc[fri].isna().all() and np.isfinite(F["bx_gap"].loc[sat, "A"])
    i_fri_last = mi.at(pd.DatetimeIndex([sat]))["row"][0]
    assert np.isclose(F["bx_gap"].loc[sat, "A"], F["beta"].loc[sat, "A"] * (mi.lc[i_fri_last] - mi.lc[i_fri_last - 240]) * 1e4)
    assert F["bx_24h"].loc[sat].isna().all() and F["bx_1h"].loc[sat].isna().all()
    m24 = own["m_24h"][hours.get_loc(mon)]                                                         # Monday 00:00: open at t; t − 24h is Sunday, closed → Friday's last minute
    assert np.isfinite(m24) and np.isclose(m24, (mi.lc[-1] - mi.lc[i_fri_last]) * 1e4) and not own["open"][hours.get_loc(sat)]
    assert (own["age_min"][hours.get_loc(sat)] > 60) and own["age_min"][hours.get_loc(fri)] == 1.0


def test_the_shifts_keep_their_distance():
    assert audit_index.gap_days() == 32 and len(horizon.shifts(485, 32)) == 422
    assert audit_index.gap_days(10, HOLD) == 12


def _synth_index(days: int = 140, start: str = "2023-03-20", seed: int = 7, kappa: float = 0.6):
    """A market whose names move WITH the index hour by hour (RIGHT +1.5, WRONG −1.5, the training names +0.5), and whose
    next hour also carries κ × that sensitivity × the index's move over the last 24 h (the planted continuation): the
    index family should find bx_24h, and the open-interest family nothing."""
    rng = np.random.default_rng(seed)
    hours = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 24, freq="1h")
    is_open = _open_mask(hours)
    u = np.where(is_open, rng.normal(0, 25e-4, len(hours)), 0.0)
    lc_end = np.cumsum(u)
    mi = audit_index.Minutes(_minutes(hours, lc_end, u, is_open))
    m24 = np.nan_to_num(np.where(is_open, mi.at(hours)["lc"] - mi.at(hours - pd.Timedelta("24h"))["lc"], 0.0))
    _minutes(hours, lc_end, u, is_open).to_parquet("data/index_1m.parquet", index=False)
    t5 = pd.date_range(hours[0] - pd.Timedelta("55min"), periods=days * 288, freq="5min")
    c5, fund, cost = [], [], []
    for i, sym in enumerate([*TRAIN, *NAMES]):
        b = 1.5 if sym in RIGHT else (-1.5 if sym in WRONG else 0.5)
        rh = b * u * 1e4 + kappa * b * np.r_[0.0, m24[:-1]] * 1e4 + rng.normal(0, 25, len(hours))
        r5 = np.repeat(rh / 12, 12)
        px = 100 * (i + 1) * np.exp(np.cumsum(r5) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def test_the_read_finds_the_planted_continuation_and_the_twelves_labels_are_the_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth_index()
    _members(tmp_path / "m.csv")
    monkeypatch.setattr(audit_index, "BETA_DAYS", 10)
    monkeypatch.setattr(audit_index, "BETA_MIN_HOURS", 60)
    monkeypatch.setattr(audit_index, "TWELVE_RUN", "transfer")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [*TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")
    # the twelve's cells: the run's own labels on the cells it scored, and the same grid
    B = audit_index.cells_twelve(NAMES, ["F1"], HOLD, bt.LATENCY, run="transfer")
    A = audit.frame("transfer", str(tmp_path / "m.csv"))
    assert B["validity"]["status"] == "PASS" and B["validity"]["checked"] == "forecast" and B["validity"]["max_abs_dz"] < 1e-9 and B["grid"].equals(A["grid"]), B["validity"]
    assert audit_index.cells_twelve(NAMES, ["F1"], HOLD, run=None)["validity"]["status"] == "PASS"
    assert audit_index.cells_twelve(NAMES, ["F1"], HOLD, run="no_such_run")["validity"]["status"] == "FAIL"
    txt = audit_index.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1)
    out = audit_index.OUT / "transfer_index"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["whole_days"] and v["shifts"] == v["days"] - 2 * 12 + 1 and v["shifts"] > 30 and "**PASS**" in txt
    tab = pd.read_csv(out / "features.csv").set_index(["universe", "feature"])
    assert len(tab) == 10 and set(tab.index.get_level_values("feature")) == set(audit_index.FEATURES)
    cov = tab["coverage"]
    assert (cov.xs("beta", level="feature") > 0.85).all() and (cov.xs("bx_gap", level="feature").between(0.25, 0.5)).all() and (cov.xs("bx_24h", level="feature").between(0.45, 0.7)).all()
    ref = pd.read_csv(out / "reference.csv").set_index(["universe", "row"])
    for uni in ("outside", "twelve"):
        r = tab.loc[(uni, "bx_24h")]
        assert r["ic"] > 0.1 and r["u"] > 3 and r["p_family"] <= 0.05 and r["verdict"] == "CLEARS", (uni, r)
        g = tab.loc[(uni, "bx_gap")]
        assert g["verdict"] != "CLEARS" and abs(g["ic_c"]) < r["ic_c"] / 4, (uni, g)                # nothing was planted on the closed hours
        assert ref.loc[(uni, "beta after an index rise (m_24h > 0)"), "ic"] > 0.15 and ref.loc[(uni, "beta after an index fall (m_24h < 0)"), "ic"] < -0.15      # the index's move itself
        assert ref.loc[(uni, "bx_24h on closed hours"), "cells"] == 0 and ref.loc[(uni, "bx_24h on open hours"), "cells"] > 0        # read on open hours only
    assert {"beta on open hours", "beta on closed hours", "beta_90d", "the run's forecast (R18's candle ridge)"} <= set(ref.loc["outside"].index)
    assert "R14's held-out forecast" in ref.loc["twelve"].index and np.isfinite(v["twelve"]["ic_needed"]) and v["twelve"]["checked"] == "forecast"
    assert (audit_index.OUT / "twelve_index" / "audit.md").exists() and (out / "coverage_month.csv").exists()
    d = pd.read_parquet(out / "shifts.parquet")
    assert d["shift"].max() == v["days"] - 12 and (d.groupby(["universe", "feature"])["shift"].count() == v["shifts"] + 1).all()
