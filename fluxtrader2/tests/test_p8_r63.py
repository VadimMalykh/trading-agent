"""R63 unit tests for `scripts/r63_fall.py` on made-up bars, no network (validity (4), run before the real bars): names follow BTC with
their own betas, and on the hour AFTER a BTC fall each gives back a share of what it fell with BTC (spread over that hour's bars 2 … 12,
nothing after a rise). The run reproduces R50's described rows by the mask path first (R50's own `_refs` code builds the reference), appends
the guard rows before the confirmation bars are loaded, and recovers the planted give-back on the FALL half with the registered NEGATIVE
sign while the rise half reads nothing of the kind; the masks and the feature at t do not change when the bars after t are altered; the
feature shifted one hour into the future does not recover the planted sign; a reference that does not match voids the run before any guard
row or confirmation output exists; a second run is refused; a missing registration block is refused."""
import dataclasses
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import audit, audit_index, screen
from ft2 import backtest as bt
from ft2.ceiling import BAR

from test_p8_screen import BLOCKS, RIGHT, TRAIN, WRONG, _members

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
NAMES = [*RIGHT, *WRONG]
BTC = "BTCUSDT"
HOLD = 12
DAYS, START = 100, "2023-03-20"
BETAS = np.linspace(0.3, 3.0, len(NAMES))                   # wide: the rank of beta ÷ sigma must spread across the names
FOLD = ["F1"]                                        # stands in for F3+F4 here: the run reads one fold, once


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _synth(seed: int = 5, give_back: float = 1.5, btc_sd: float = 8.0, sd: float = 5.0):
    """BTC a random walk; name i moves with it by beta_i, and in the hour after a BTC FALL gives back `give_back` × beta_i × that fall, spread over
    bars 2 … 12 of the hour (so the 1h label, which runs from the close one bar after t to twelve bars later, holds all of it and none of the
    next hour's); nothing after a rise; the name's own noise on every bar."""
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n = len(t5)
    b5 = rng.normal(0, btc_sd, n)
    gid = (np.arange(n) + 11) // 12                                          # the hour a bar belongs to on the feature's grid: closes :05 … :00
    G = int(gid.max()) + 1
    bh = np.bincount(gid, weights=b5, minlength=G)                           # BTC's hourly moves
    pos = (np.arange(n) + 11) % 12                                           # a bar's position in its hour: 0 the first (:05), 11 the last (:00)
    prev_fall = np.concatenate([[0.0], np.minimum(bh, 0.0)[:-1]])            # the previous hour's fall (≤ 0), by hour
    c5, fund, cost = [], [], []
    syms = [BTC, *TRAIN, *NAMES]
    for i, sym in enumerate(syms):
        if sym == BTC:
            r = b5
        else:
            beta = BETAS[NAMES.index(sym)] if sym in NAMES else 1.0
            gb = np.where(pos >= 1, -give_back * beta * prev_fall[gid] / 11.0, 0.0)
            r = beta * b5 + gb + rng.normal(0, sd, n)
        px = 100 * (i + 1) * np.exp(np.cumsum(r) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=DAYS * 3, freq="8h"), "rate": 1e-4, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def _world(tmp_path, monkeypatch, **kw):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PLAN.md").write_text("# plan\n\n### R63 — the test's registration block (registered, read —)\nQuestion: …\n")
    _synth(**kw)
    _members(tmp_path / "m.csv")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [BTC, *TRAIN, *NAMES], FOLD, draws=1, refit_days=15, execs=("taker",), name="transfer")


def _reference(r50, tmp_path, holds) -> Path:
    """R50's described rows by R50's own code on the test frame — the reference the mask path must reproduce."""
    A = audit.frame("transfer", str(tmp_path / "m.csv"))
    u = r50._universe("outside", A, holds, r50._btc(A, A))
    rows = pd.DataFrame(r50._refs(u, holds, audit._day(u["grid"]), None))
    p = tmp_path / "reference.csv"
    rows.to_csv(p, index=False)
    return p


def _run(m, tmp_path, ref, **kw):
    args = dict(members_csv=tmp_path / "m.csv", fold_names=FOLD, f12_run="transfer", f12_members=str(tmp_path / "m.csv"), ref_csv=ref, out=Path("output/audit/r63_test"),
                gap=5, min_shifts=10, jobs=1, reads=Path("output/backtest/confirmation_reads.csv"), plan=Path("docs/PLAN.md"))
    args.update(kw)
    return m.run(**args)


def test_a_planted_give_back_after_a_fall_is_confirmed_with_the_registered_sign_and_the_guard_rows_are_written_first(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    m, r50 = _module("r63_fall"), _module("r50_btchour")
    ref = _reference(r50, tmp_path, m.HOLDS)
    reads = Path("output/backtest/confirmation_reads.csv")
    assert not reads.exists()
    s = _run(m, tmp_path, ref)
    v = s["validity"]
    assert v["status"] == "PASS"
    r1 = v["1_reproduction"]
    assert r1["status"] == "PASS" and r1["rows"] == 6 and r1["max_abs_d_ic"] <= 1e-6 and r1["max_abs_d_t"] <= 1e-6 and r1["cells_equal"]
    c = v["2_cells"]
    assert c["cells_not_members"] == 0 and c["cells_outside_folds"] == 0 and c["min_names_at_a_bar"] >= 5 and c["cover"] > 0.95 and c["whole_days"]
    assert c["shifts"] == c["shifts_expected"] >= 10 and c["status"] == "PASS"
    k = v["3_mask"]
    assert k["status"] == "PASS" and k["fall_cells_at_non_fall_bars"] == 0 and k["rise_cells_at_non_rise_bars"] == 0
    assert k["cells_fall"] + k["cells_rise"] + k["cells_b_zero"] == k["cells_bx"] and k["cells_fall"] > 0 and k["cells_rise"] > 0
    # the guard rows: one per fold, R63's, written before the read
    rd = pd.read_csv(reads)
    assert list(rd["registration"]) == ["R63"] * len(FOLD) and sorted(rd["fold"]) == sorted(FOLD) and rd["strategy"].iloc[0] == "bx_1h_fall"
    assert json.loads(rd["params"].iloc[0])["sign"] == -1 and rd["read_at"].iloc[0] == v["5_guard"]["read_at"]
    # the family: the fall half at 1h recovers the planted give-back with the registered sign
    tab = pd.DataFrame(s["rows"]).set_index(["side", "hold"])
    f = tab.loc[("fall", 12)]
    assert f["family"] and f["sign"] == -1 and f["ic_c"] < -0.05 and f["signed_u"] > 2 and f["p_family"] <= 0.05 and f["verdict"] == "CLEARS", dict(f)
    assert f["t_hac"] < -2 and f["lo"] < f["ic_c"] < f["hi"] and f["money_bar"] == 0.14
    assert s["confirmed"] and s["verdict"] == "CONFIRMED"
    # the rise half reads nothing of the kind (described, outside the family): its raw IC and HAC t are noise where the fall half's are not.
    # (ic_c is not the measure in this world: the planted give-back is a positive DRIFT of the high-beta names, and the shift null's centre
    # carries that drift onto both halves with the sign of the half's ranking — ≈ −0.1 on the fall half, ≈ +0.1 on the rise half — so ic_c
    # reads ≈ −0.1 on both; the raw rows, which R50's described rows are, tell the halves apart)
    r = tab.loc[("rise", 12)]
    assert not r["family"] and r["verdict"] == "described" and np.isnan(r["p_family"]) and abs(r["ic"]) < 0.04 and abs(r["t_hac"]) < 3, dict(r)
    assert f["ic"] < -0.1 and r["ic"] > f["ic"] + 0.1 and r["centre"] > 0 > f["centre"]
    # the planted effect sits in the first hour: 4h and 1d hold it diluted, never with the opposite sign beyond noise
    assert tab.loc[("fall", 48), "ic_c"] < 0.03 and tab.loc[("fall", 288), "u"] < 2
    assert all(tab.loc[("fall", h), "cells"] == k["cells_fall"] for h in m.HOLDS)
    out = Path("output/audit/r63_test")
    for f_ in ("validity.json", "validity_f12.csv", "result.json", "result.md", "rows.csv", "shifts.parquet"):
        assert (out / f_).exists(), f_
    md = (out / "result.md").read_text()
    assert "CONFIRMED" in md and "after-rise half" in md and "guard rows appended" in md
    # a second run is refused by the guard before anything is touched
    (out / "result.md").write_text("sentinel")
    with pytest.raises(SystemExit) as e:
        _run(m, tmp_path, ref, skip_f12=True)
    assert e.value.code == 2 and (out / "result.md").read_text() == "sentinel" and len(pd.read_csv(reads)) == len(FOLD)


def test_the_masks_and_the_feature_know_nothing_after_t_and_a_future_feature_does_not_recover_the_sign(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    m, r50 = _module("r63_fall"), _module("r50_btchour")
    A = r50.cells_members(tmp_path / "m.csv", fold_names=FOLD, hold=HOLD)
    u = r50._universe("outside", A, m.HOLDS, r50._btc(A, A))
    cut = u["grid"][len(u["grid"]) // 2]
    close2 = A["M"].close.copy()
    close2.loc[close2.index > cut] *= 1.03                                   # the bars AFTER t altered (the names' and BTC's)
    A2 = {**A, "M": dataclasses.replace(A["M"], close=close2)}
    btc2 = r50._btc(A, A).copy()
    btc2.loc[btc2.index > cut] *= 1.03
    u2 = r50._universe("outside", A2, m.HOLDS, btc2)
    F, F2 = m.half(u["F"]["bx_1h"], m.masks(u["b_1h"])["fall"]), m.half(u2["F"]["bx_1h"], m.masks(u2["b_1h"])["fall"])
    before = u["grid"] <= cut
    pd.testing.assert_frame_equal(F.loc[before], F2.loc[before])
    assert (m.masks(u["b_1h"])["fall"][before] == m.masks(u2["b_1h"])["fall"][before]).all()
    assert not F.loc[~before].equals(F2.loc[~before])
    # the feature one hour into the future: the planted give-back is not recovered with the registered sign on the fall half
    day = audit._day(u["grid"])
    masks = m.masks(u["b_1h"])
    ic_now, _ = audit_index._ic_on(u["F"]["bx_1h"], u["Z"][12], day, masks["fall"], hold=12)
    Ff = u["F"]["bx_1h"].shift(-1)
    bf = np.concatenate([u["b_1h"][1:], [np.nan]])
    ic_future, _ = audit_index._ic_on(Ff, u["Z"][12], day, m.masks(bf)["fall"], hold=12)
    assert ic_now < -0.05 and ic_future > ic_now + 0.05, (ic_now, ic_future)


def test_a_reference_that_does_not_match_voids_the_run_before_the_guard_and_a_missing_block_is_refused(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    m, r50 = _module("r63_fall"), _module("r50_btchour")
    ref = _reference(r50, tmp_path, m.HOLDS)
    bad = pd.read_csv(ref)
    bad.loc[bad["row"].str.startswith("bx_1h after a BTC fall") & (bad["hold"] == 12), "ic"] += 1e-3
    bad_p = tmp_path / "bad.csv"
    bad.to_csv(bad_p, index=False)
    reads = Path("output/backtest/confirmation_reads.csv")
    with pytest.raises(SystemExit) as e:
        _run(m, tmp_path, bad_p)
    assert e.value.code == 2 and not reads.exists()
    v = json.loads(Path("output/audit/r63_test/validity.json").read_text())
    assert v["status"] == "FAIL" and v["1_reproduction"]["status"] == "FAIL" and v["1_reproduction"]["max_abs_d_ic"] > 1e-6 and "5_guard" not in v
    assert "VOID at validity (1)" in Path("output/audit/r63_test/result.md").read_text()
    for f_ in ("result.json", "rows.csv", "shifts.parquet"):
        assert not Path("output/audit/r63_test", f_).exists(), f_
    # a dropped reference row is a FAIL too (the outer merge sees it)
    short = pd.read_csv(ref)
    short = short[~(short["row"].str.startswith("bx_1h after a BTC rise") & (short["hold"] == 288))]
    got = m.half_rows(r50._universe("outside", (A := audit.frame("transfer", str(tmp_path / "m.csv"))), m.HOLDS, r50._btc(A, A)), m.HOLDS)
    assert m.reproduce(got, short)["status"] == "FAIL" and m.reproduce(got, pd.read_csv(ref))["status"] == "PASS"
    # the registration block must exist
    Path("docs/PLAN.md").write_text("# plan without the block\n")
    with pytest.raises(SystemExit) as e2:
        m.guard(reads, Path("docs/PLAN.md"), FOLD)
    assert "R63" in str(e2.value) and not reads.exists()
    # the verdict rule
    assert m.verdict({"u": -3.0, "se": 0.01, "signed_u": 3.0, "p_family": 0.01, "ic_c": -0.03}) == "CLEARS"
    assert m.verdict({"u": 3.0, "se": 0.01, "signed_u": -3.0, "p_family": 0.01, "ic_c": 0.03}) == "NOT DETECTABLE"      # the wrong sign never clears
    assert m.verdict({"u": -0.5, "se": 0.004, "signed_u": 0.5, "p_family": 0.6, "ic_c": -0.002}) == "CLOSED"
    assert m.verdict({"u": -1.5, "se": 0.01, "signed_u": 1.5, "p_family": 0.2, "ic_c": -0.015}) == "NOT DETECTABLE"
