"""R37 unit tests for the forced-flow audit (`ft2/audit_flow.py`): the ingredients read nothing stamped at or after their bar; the family
is zero when open interest grew and when the takers pushed against the move; a planted cascade (a far hourly move with open interest
leaving and one-sided takers, then a partial reversal over the next hour) comes back through the read with the registered sign, clearing
the gate and ADDING to the plain reversal, while the reference parts alone do not; the forced hours are found and their faded money is
positive; a world without metrics voids the run before any number of the family."""
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import audit, audit_flow, audit_index, screen
from ft2 import backtest as bt
from ft2.ceiling import BAR

from test_p8_screen import RIGHT, TRAIN, WRONG, _members

NAMES = [*RIGHT, *WRONG]
HOLD = 12
DAYS, START = 100, "2023-03-20"


def _synth_flow(seed: int = 11, p_event: float = 0.02, size: float = 4.0, back: float = 0.5, fall: float = 0.08):
    """Random-walk names (5m bars). On a fraction `p_event` of a name's hours, a CASCADE: the hour's return is `size` × the hourly sd
    in a random direction, open interest falls by `fall` over that hour, and the taker balance leans the move's way; the NEXT hour
    gives back `back` of the move. Elsewhere open interest drifts and the takers are noise. Metrics rows are stamped t − 5 min."""
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n, sd = len(t5), 6.0
    hours = n // 12
    c5, met, fund, cost = [], [], [], []
    for i, sym in enumerate([*TRAIN, *NAMES]):
        r = rng.normal(0, sd, n)
        loi = np.cumsum(rng.normal(0, 0.0005, n))
        ltk = rng.normal(0, 0.2, n)
        if sym in NAMES:
            ev = np.flatnonzero(rng.random(hours) < p_event)
            ev = ev[(ev >= 2) & (ev < hours - 2)]
            for e in ev:
                sgn = rng.choice([-1.0, 1.0])
                a, b = e * 12, (e + 1) * 12
                r[a:b] += sgn * size * sd * np.sqrt(12) / 12                       # the cascade hour: size σ_hour, spread over its bars
                r[b:b + 12] -= sgn * back * size * sd * np.sqrt(12) / 12           # the next hour gives part of it back
                loi[a + 1:] -= fall                                                # open interest leaves during the hour (from its second bar), for good
                ltk[a:b] += sgn * 0.8                                              # the takers pushed with the move
        px = 100 * (i + 1) * np.exp(np.cumsum(r) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        if sym in NAMES:
            met.append(pd.DataFrame({"symbol": sym, "ts": t5 - BAR, "oi": 1e6 * np.exp(loi), "oi_value": 1e6 * np.exp(loi) * px, "top_ls_sum": 1.0, "global_ls": 1.0,
                                     "taker_ratio": np.exp(ltk)}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=DAYS * 3, freq="8h"), "rate": 1e-4, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(met).to_parquet("data/metrics.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def _world(tmp_path, monkeypatch, **kw):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth_flow(**kw)
    _members(tmp_path / "m.csv")
    monkeypatch.setattr(audit_index, "TWELVE_RUN", "transfer")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [*TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")


def test_ingredients_read_nothing_at_or_after_their_bar_and_the_family_is_zero_where_it_should_be(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    M = bt.market([*TRAIN, *NAMES], audit_index.folds.bounds("F1")[1])
    idx = M.index[M.index >= M.index[len(M.index) // 2]]
    I0, notes = audit_flow.ingredients(idx, NAMES, M.close.loc[idx, NAMES], M.index[-1] + BAR)
    assert not notes and all(I0[k].loc[idx[0] + pd.Timedelta(days=10):].notna().to_numpy().mean() > 0.9 for k in I0)      # σ_1w needs a week of bars
    cut = idx[len(idx) // 2]
    m = pd.read_parquet("data/metrics.parquet")
    late = m["ts"] >= cut
    m.loc[late, ["oi", "taker_ratio"]] *= 3.0                                      # the metrics change from the cut on
    m.to_parquet("data/metrics.parquet", index=False)
    I1, _ = audit_flow.ingredients(idx, NAMES, M.close.loc[idx, NAMES], M.index[-1] + BAR)
    for k in ("oi_chg_1h", "taker_1h"):
        pd.testing.assert_frame_equal(I0[k][I0[k].index <= cut], I1[k][I1[k].index <= cut], obj=k)       # the row stamped at the cut is used from cut + 5 min
        assert not I0[k][I0[k].index > cut + BAR].equals(I1[k][I1[k].index > cut + BAR])
    F, R = audit_flow.features_flow(I0)
    mv, oi, tk = I0["move_1h"], I0["oi_chg_1h"], I0["taker_1h"]
    grew = (oi > 0) & mv.notna()
    g = grew.to_numpy()
    assert (F["rev_oi"].to_numpy()[g] == 0).all() and (F["rev_flow"].to_numpy()[g] == 0).all()                  # nothing when open interest grew
    against = (oi < 0) & (np.sign(tk) != np.sign(mv)) & mv.notna() & tk.notna()
    ag = against.to_numpy()
    assert (F["rev_flow"].to_numpy()[ag] == 0).all() and (F["rev_oi"].to_numpy()[ag] != 0).all()           # rev_flow needs the takers with the move
    assert np.allclose(R["rev_1h"].to_numpy(), -mv.to_numpy(), equal_nan=True)
    with_ = (oi < 0) & (np.sign(tk) == np.sign(mv)) & mv.notna() & tk.notna()
    w = with_.to_numpy()
    assert np.allclose(F["rev_flow"].to_numpy()[w], (F["rev_oi"] * tk.abs()).to_numpy()[w])


def test_the_read_finds_the_planted_cascade_and_it_adds_to_the_plain_reversal(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch, p_event=0.1)                                        # one hour in ten a cascade: a rare event dilutes a cross-sectional IC, so the test plants many
    txt = audit_flow.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1)
    out = audit_flow.OUT / "transfer_flow"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["whole_days"] and v["shifts"] == v["shifts_expected"] == v["days"] - 2 * 3 + 1 >= 20 and v["registration"] == "R37"
    assert v["outside"]["ingredients_cover"] > 0.95 and v["twelve"]["ingredients_cover"] > 0.95 and "**PASS**" in txt
    tab = pd.read_csv(out / "features.csv").set_index(["universe", "feature", "hold"])
    assert len(tab) == 2 * 6 * 2 and set(tab[tab["family"]].index.get_level_values("feature")) == set(audit_flow.FAMILY)
    for uni in ("outside", "twelve"):
        r = tab.loc[(uni, "rev_oi", 12)]
        assert r["ic_c"] > 0.05 and r["u"] > 3 and r["p_family"] <= 0.05 and bool(r["parts_same_sign"]) and r["u_delta"] > 2 and r["verdict"] == "CLEARS", (uni, dict(r))
        f = tab.loc[(uni, "rev_flow", 12)]
        assert f["ic_c"] > 0.05 and f["verdict"] == "CLEARS", (uni, dict(f))
        plain = tab.loc[(uni, "rev_1h", 12)]
        assert plain["verdict"] == "reference" and np.isnan(plain["u_delta"]) and plain["ic_c"] < r["ic_c"]                  # the footprint beats the plain reversal
        assert tab.loc[(uni, "taker_1h", 12), "verdict"] == "reference" and abs(tab.loc[(uni, "taker_1h", 12), "ic_c"]) < r["ic_c"] / 2
        assert 0 < r["nonzero"] < 0.6                                                                                        # zero where open interest grew
    ev = pd.read_csv(out / "events.csv").set_index(["universe", "hold"])
    for uni in ("outside", "twelve"):
        e = ev.loc[(uni, 12)]
        assert e["forced_hours"] > 20 and 0.005 < e["share_of_cells"] < 0.06 and e["mean_abs_move"] > 2
        assert e["faded_bps"] > 20 and e["u"] > 2 and e["faded_bps"] > e["centre"]                                          # fading the forced hour earns, beyond chance
    sh = pd.read_parquet(out / "shifts.parquet")
    assert set(sh["hold"]) == {12, 48} and sh["shift"].min() == 0 and sh["shift"].max() == v["days"] - 3
    for f_ in ("audit.md", "features.csv", "events.csv", "reference.csv", "shifts.parquet"):
        assert (out / f_).exists()


def test_no_metrics_voids_the_run_before_any_number_of_the_family(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    (tmp_path / "data" / "metrics.parquet").unlink()
    with pytest.raises(SystemExit) as e:
        audit_flow.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1)
    assert e.value.code == 2
    out = audit_flow.OUT / "transfer_flow"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "FAIL" and v["outside"]["ingredients_cover"] == 0.0 and "metrics absent" in v["outside"]["notes"][0]
    assert "VOID" in (out / "audit.md").read_text() and not (out / "features.csv").exists()
    assert audit_flow.verdict({"u": 3.0, "p_family": 0.01, "parts_same_sign": True, "ic_c": 0.05, "se": 0.01, "u_delta": 1.0}) == "CLEARS AS THE PLAIN REVERSAL"
    assert audit_flow.verdict({"u": -3.0, "p_family": 0.01, "parts_same_sign": True, "ic_c": -0.05, "se": 0.01, "u_delta": np.nan}) == "CLEARS WITH THE OPPOSITE SIGN"
    assert audit_flow.verdict({"u": 0.5, "p_family": 0.6, "parts_same_sign": False, "ic_c": 0.001, "se": 0.005, "u_delta": 0.0}) == "CLOSED"
