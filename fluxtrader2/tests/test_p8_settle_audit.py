"""R41 unit tests for the funding-settlement audit (`ft2/audit_settle.py`): the ingredients read nothing stamped at or after their bar and the
event masks sit on S − 1 h and S; fund_due is Binance's formula of the period's mean premium (flat at I inside the dead band); a planted
dip-and-snap — the names with a rate due far from I lag their peers in the hour into the settlement and come back in the hour after, with a
made-up schedule (8 h at 00/08/16, two names at 4 h) — comes back through the read with the registered signs on both universes, ADDING to the
plain reversal, the control flat, the fifths' money positive and the profile dipping then recovering; the formula check passes on the made-up
rates and fails on noise; a world without the premium voids the run before any number of the family."""
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import audit_index, audit_settle, screen
from ft2 import backtest as bt
from ft2.ceiling import BAR

from test_p8_screen import RIGHT, TRAIN, WRONG, _members

NAMES = [*RIGHT, *WRONG]
HOLD = 12
DAYS, START = 100, "2023-03-20"
FOUR_H = NAMES[:2]


def _formula(P, I):
    return P + np.clip(I - P, -audit_settle.CLAMP, audit_settle.CLAMP)


def _synth_settle(seed: int = 7, k_dip: float = 1.2, k_snap: float = 1.0, rate_noise: bool = False):
    """Random-walk names (5m bars, sd 6 bps). Each name has a schedule (8 h at 00/08/16 UTC; two names 4 h). Per period a premium level is
    drawn — six in ten inside the dead band, the rest up to ±30 bps — and the bar premium is the level plus noise. The settled rate at S is the
    formula of the period's mean premium (or noise, to break the check). The PLANT: in the hour into S the name's return is pushed by
    −k_dip × (fund_due − I) spread over the hour, and in the hour after by +k_snap × the same."""
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")        # bar CLOSE times
    n, sd = len(t5), 6.0
    tt = t5.asi8
    c5, prem, fund, cost = [], [], [], []
    for i, sym in enumerate([*TRAIN, *NAMES]):
        r = rng.normal(0, sd, n)
        iv = 4 if sym in FOUR_H else 8
        I = audit_settle.I_8H * iv / 8.0
        S = pd.date_range(t5[0].floor("D"), t5[-1] + pd.Timedelta("1D"), freq=f"{iv}h")
        S = S[(S > t5[0]) & (S <= t5[-1])]
        Si = S.asi8
        pid = np.searchsorted(Si, tt, side="left")                                           # the period of the bar closing at t: (S_prev, S_next]
        nper = len(Si) + 1
        level = np.where(rng.random(nper) < 0.6, rng.uniform(-3, 5, nper), rng.uniform(-30, 30, nper))
        p = level[pid] + rng.normal(0, 2.0, n)
        rates = []
        for k, s_ in enumerate(Si):
            inper = pid == k
            Pm = p[inper].mean() if inper.any() else level[k]
            rates.append(_formula(Pm, I) if not rate_noise else rng.normal(0, 10))
            due = _formula(level[k], I) - I                                                   # the excess over the dead band's rate: the plant's size
            at = np.searchsorted(tt, s_)                                                      # the bar closing at S
            a, b = max(at - 12, 0), at
            r[a:b] -= k_dip * due / 12.0
            r[at:min(at + 12, n)] += k_snap * due / 12.0
        px = 100 * (i + 1) * np.exp(np.cumsum(r) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        prem.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "premium": p / 1e4}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": S, "rate": np.asarray(rates) / 1e4, "interval_h": iv}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(prem).to_parquet("data/premium.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def _world(tmp_path, monkeypatch, **kw):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth_settle(**kw)
    _members(tmp_path / "m.csv")
    monkeypatch.setattr(audit_index, "TWELVE_RUN", "transfer")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [*TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")


def test_ingredients_read_nothing_at_or_after_their_bar_and_the_masks_and_the_formula_are_as_written(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    M = bt.market([*TRAIN, *NAMES], audit_index.folds.bounds("F1")[1])
    idx = M.index[M.index >= M.index[len(M.index) // 2]]
    end = M.index[-1] + BAR
    I0, notes = audit_settle.ingredients(idx, NAMES, M.close.loc[idx, NAMES], end)
    assert not notes
    S = pd.read_parquet("data/funding_archive.parquet")
    for sym in (NAMES[0], NAMES[-1]):                                                           # a 4 h name and an 8 h one
        s = pd.DatetimeIndex(S[S["symbol"] == sym]["ts"])
        s = s[(s >= idx[0] + pd.Timedelta("2h")) & (s <= idx[-1] - pd.Timedelta("2h"))]
        assert I0["after"][sym].loc[s].all() and I0["into"][sym].loc[s - pd.Timedelta("1h")].all()
        assert I0["after"][sym].sum() >= len(s) and I0["into"][sym].sum() >= len(s)
        assert I0["near"][sym].loc[s - pd.Timedelta("2h")].all() and I0["near"][sym].loc[s + pd.Timedelta("1h")].all()
        assert sym in FOUR_H or not I0["near"][sym].loc[s + pd.Timedelta("3h")].any()                      # an 8 h name is clear from S + 2 h to S + 5 h
        iv = 4 if sym in FOUR_H else 8
        assert (I0["interval"][sym].dropna() == iv).all()
        # fund_due at S is the formula of the period's mean premium, and inside the dead band it is exactly I
        P, fd = I0["P"][sym], I0["fund_due"][sym]
        I = audit_settle.I_8H * iv / 8.0
        np.testing.assert_allclose(fd.dropna(), _formula(P.dropna(), I), atol=1e-9)
        band = P.between(I - audit_settle.CLAMP, I + audit_settle.CLAMP)
        assert np.allclose(fd[band & P.notna()], I) and np.allclose(fd[P > I + audit_settle.CLAMP], P[P > I + audit_settle.CLAMP] - audit_settle.CLAMP)
        # the settled rate at S equals fund_due at S (the full period) and fund_due at S − 1 h is within a bp of it
        at = I0["rate_S"][sym].dropna().iloc[1:]                                                   # the first period's bars begin before the window: P is NaN there
        np.testing.assert_allclose(fd.loc[at.index], at, atol=0.05)
        assert (np.abs(fd.shift(12).loc[at.index] - at) <= 1.0).mean() > 0.95
        # funding_last at S is the rate settled at the PREVIOUS settlement
        ss = at.index
        assert np.allclose(I0["funding_last"][sym].loc[ss[1:]], at.loc[ss[:-1]].to_numpy(), atol=1e-9)
    # the look-ahead cut: premium rows stamped from the cut on change nothing at or before it
    cut = idx[len(idx) // 2]
    pr = pd.read_parquet("data/premium.parquet")
    late = pr["open_time"] + BAR > cut                                                           # bars CLOSING after the cut
    pr.loc[late, "premium"] += 0.002
    pr.to_parquet("data/premium.parquet", index=False)
    I1, _ = audit_settle.ingredients(idx, NAMES, M.close.loc[idx, NAMES], end)
    for k in ("P", "fund_due", "prem_dev"):
        pd.testing.assert_frame_equal(I0[k][I0[k].index <= cut], I1[k][I1[k].index <= cut], obj=k)
        assert not I0[k][I0[k].index > cut + pd.Timedelta("2h")].equals(I1[k][I1[k].index > cut + pd.Timedelta("2h")])
    # the slot's sign
    F = audit_settle.features_settle({k: v for k, v in I0.items()}, pd.DataFrame(True, index=idx, columns=NAMES))
    f_into, f_after = F[("fund_due", "into", "event")], F[("fund_due", "after_1h", "event")]
    assert np.allclose(f_into.stack().to_numpy(), -I0["fund_due"].where(I0["into"]).stack().to_numpy())
    assert np.allclose(f_after.stack().to_numpy(), I0["fund_due"].where(I0["after"]).stack().to_numpy())
    assert not (F[("fund_due", "into", "control")].notna() & I0["near"]).to_numpy().any()


def test_the_read_finds_the_planted_dip_and_snap_with_the_registered_signs_and_the_control_is_flat(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    txt = audit_settle.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1)
    out = audit_settle.OUT / "transfer_settle"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["whole_days"] and v["shifts"] == v["shifts_expected"] == v["days"] - 2 * 3 + 1 >= 20 and v["registration"] == "R41"
    for uni in ("outside", "twelve"):
        assert v[uni]["fund_due_cover"] > 0.95 and v[uni]["formula"]["at_S_minus_1h"]["status"] == "PASS"
        assert v[uni]["formula"]["at_S_minus_1h"]["rho_median"] > 0.95 and v[uni]["formula"]["at_S"]["within_1bp"] > 0.95
        assert v[uni]["schedule"]["share_at_00_08_16"] > 0.8 and set(v[uni]["schedule"]["interval_mix"]) == {"4", "8"}
    assert "**PASS**" in txt
    tab = pd.read_csv(out / "features.csv").set_index(["universe", "feature", "slot", "cells"])
    fam = tab[tab["family"]]
    assert len(fam) == 6
    for uni in ("outside", "twelve"):
        for slot in ("into", "after_1h"):
            r = tab.loc[(uni, "fund_due", slot, "event")]
            assert r["ic_c"] > 0.15 and r["u"] > 3 and r["p_family"] <= 0.05 and bool(r["parts_same_sign"]) and r["u_delta"] > 2, (uni, slot, dict(r))
            assert r["verdict"] == "CLEARS", (uni, slot, r["verdict"], dict(r))
            c = tab.loc[(uni, "fund_due", slot, "control")]
            assert abs(c["ic_c"]) < 0.5 * r["ic_c"] and c["verdict"] == "control", (uni, slot, dict(c))
            p = tab.loc[(uni, "P", slot, "event")]
            assert p["verdict"] == "reference" and p["ic_c"] > 0.1                                  # the raw premium reads the plant too (it is monotone in fund_due outside the band)
            plain = tab.loc[(uni, "rev_1h", slot, "event")]
            assert np.isnan(plain["u_delta"]) and plain["ic_c"] < r["ic_c"]
    money = pd.read_csv(out / "money.csv").set_index(["universe", "slot", "cut"])
    for uni in ("outside", "twelve"):
        m_in, m_af = money.loc[(uni, "into", "all")], money.loc[(uni, "after_1h", "all")]
        assert m_in["positions"] > 100 and m_in["bps"] > 5 and m_in["u"] > 2 and m_in["bps"] > m_in["centre"], dict(m_in)
        assert m_af["bps"] > 5 and m_af["u"] > 2, dict(m_af)
        assert money.loc[(uni, "into", "8h names"), "positions"] > money.loc[(uni, "into", "4h names"), "positions"] > 0
        assert money.loc[(uni, "into", "S at 00 UTC"), "positions"] > 0 and money.loc[(uni, "into", "S at other hours"), "positions"] == 0        # too few 4 h names at 04/12/20 for a fifth
    prof = pd.read_csv(out / "profile.csv")
    for uni in ("outside", "twelve"):
        p = prof[prof["universe"] == uni].set_index("offset_min")
        assert list(p.index) == [(o - audit_settle.PROFILE) * 5 for o in range(1, 2 * audit_settle.PROFILE + 1)]
        assert p.loc[-55:0, "bps"].mean() > 0.3 and p.loc[5:60, "bps"].mean() < -0.3                   # the INTO side earns into S and gives back after
    sh = pd.read_parquet(out / "shifts.parquet")
    assert set(sh["slot"]) == set(audit_settle.SLOTS) and sh["shift"].min() == 0 and sh["shift"].max() == v["days"] - 3
    for f_ in ("audit.md", "features.csv", "money.csv", "profile.csv", "reference.csv", "shifts.parquet"):
        assert (out / f_).exists()


def test_a_wrong_formula_or_a_missing_premium_voids_the_run_before_any_number_of_the_family(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch, rate_noise=True)
    with pytest.raises(SystemExit) as e:
        audit_settle.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1)
    assert e.value.code == 2
    out = audit_settle.OUT / "transfer_settle"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "FAIL" and v["outside"]["formula"]["at_S_minus_1h"]["status"] == "FAIL" and v["outside"]["fund_due_cover"] > 0.95
    assert "VOID" in (out / "audit.md").read_text() and not (out / "features.csv").exists()
    (tmp_path / "data" / "premium.parquet").unlink()
    with pytest.raises(SystemExit) as e2:
        audit_settle.run("transfer", pairs=NAMES, twelve=True, members=str(tmp_path / "m.csv"), jobs=1)
    assert e2.value.code == 2
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "FAIL" and v["outside"]["fund_due_cover"] == 0.0 and "premium absent" in v["outside"]["notes"][0]
    base = {"u": 3.0, "p_family": 0.01, "parts_same_sign": True, "ic_c": 0.05, "se": 0.01, "u_delta": 3.0, "control_u": 0.5, "control_ic_c": 0.005}
    assert audit_settle.verdict(base) == "CLEARS"
    assert audit_settle.verdict({**base, "u_delta": 1.0}) == "CLEARS AS THE PLAIN REVERSAL"
    assert audit_settle.verdict({**base, "control_u": 2.5, "control_ic_c": 0.03}) == "NOT THE SETTLEMENT'S"
    assert audit_settle.verdict({**base, "control_u": 2.5, "control_ic_c": 0.01}) == "CLEARS"
    assert audit_settle.verdict({**base, "u": -3.0, "ic_c": -0.05}) == "CLEARS WITH THE OPPOSITE SIGN"
    assert audit_settle.verdict({**base, "u": 0.5, "p_family": 0.6, "parts_same_sign": False, "ic_c": 0.001, "se": 0.005}) == "CLOSED"
    assert audit_settle.verdict({**base, "u": 1.0, "p_family": 0.6, "ic_c": 0.01, "se": 0.01}) == "NOT DETECTABLE"
