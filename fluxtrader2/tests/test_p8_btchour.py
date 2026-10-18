"""R50 unit tests for `scripts/r50_btchour.py` on made-up bars: names that follow BTC with their own betas and receive a part of BTC's hour an
hour LATE come back through stage 1 with lead_1h clearing at 1h (positive, adding to the plain reversal, which reads the other way there)
and bx_1h clearing two-sided, then CONFIRMED by stage 2 on the same cells read as the confirmation; a world without the lag clears nothing
and stage 2 writes NOTHING TO CONFIRM without loading any bar; the features at t do not change when the bars after t are altered; beta
equals numpy's slope; the members-by-block cells follow the frozen csv."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ft2 import audit_index, screen, universe
from ft2 import backtest as bt
from ft2.ceiling import BAR
from ft2.forecast import _derive

from test_p8_screen import RIGHT, TRAIN, WRONG, _members, BLOCKS

READ = Path(__file__).resolve().parents[1] / "scripts" / "r50_btchour.py"
NAMES = [*RIGHT, *WRONG]
BTC = "BTCUSDT"
HOLD = 12
DAYS, START = 100, "2023-03-20"
BETAS = np.linspace(0.4, 2.0, len(NAMES))


def _module():
    spec = importlib.util.spec_from_file_location("r50_btchour", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _synth(seed: int = 5, lag: float = 0.6, p_lag: float = 0.5, btc_sd: float = 8.0, sd: float = 5.0):
    """BTC a random walk; name i follows it with beta_i, and on a random half of its hours (p_lag) a share `lag` of BTC's hour arrives an
    hour LATE — the name lags BTC's hour and catches up the next (a systematic lag would be absorbed by the contemporaneous beta and is
    not what lead_1h measures); every hour's share spread evenly over its 12 bars, plus the name's own noise. The training names and BTC
    are in the market; the members are NAMES."""
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    n = len(t5)
    b5 = rng.normal(0, btc_sd, n)
    gid = (np.arange(n) + 11) // 12                                          # the hour a bar belongs to ON THE FEATURE'S GRID: closes :05 … :00 (the first bar alone)
    G = int(gid.max()) + 1
    size = np.bincount(gid, minlength=G).astype(float)
    bh = np.bincount(gid, weights=b5, minlength=G)                           # BTC's hourly moves
    c5, fund, cost = [], [], []
    syms = [BTC, *TRAIN, *NAMES]
    for i, sym in enumerate(syms):
        if sym == BTC:
            r = b5
        else:
            beta = BETAS[NAMES.index(sym)] if sym in NAMES else 1.0
            late = (rng.random(G) < p_lag) * lag                             # the share of this hour's BTC move that arrives next hour
            deferred = np.concatenate([[0.0], (late * bh)[:-1]])
            share = beta * ((1 - late) * bh + deferred) / size
            r = share[gid] + rng.normal(0, sd, n)
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
    _synth(**kw)
    _members(tmp_path / "m.csv")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [BTC, *TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")


def _stage1(m, tmp_path):
    return m.stage1(run="transfer", pairs=NAMES, members=str(tmp_path / "m.csv"), twelve_run="transfer", jobs=1, out=Path("output/audit/r50_test"), gap=5,
                    state_daily=None, min_shifts=10)


def test_features_know_nothing_after_t_and_beta_is_numpys_slope(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    m = _module()
    M = bt.market([BTC, *NAMES], pd.Timestamp("2024-01-01", tz="UTC"))
    idx = M.index
    hidx = idx[(idx.minute == 0)]
    sig = (_derive(M.close[NAMES])["sig"]["1w"] * np.sqrt(12)).loc[hidx]
    F0, rb = m.features(hidx, NAMES, M.close.loc[hidx, NAMES], M.close.loc[hidx, BTC], sig)
    cut = hidx[len(hidx) // 2]
    close2 = M.close.copy()
    close2.loc[close2.index > cut] *= 1.02                                  # the bars AFTER t altered
    F1, _ = m.features(hidx, NAMES, close2.loc[hidx, NAMES], close2.loc[hidx, BTC], sig)
    for k in F0:
        pd.testing.assert_frame_equal(F0[k].loc[:cut], F1[k].loc[:cut], obj=k)
        assert not F0[k].loc[cut + pd.Timedelta("2h"):].equals(F1[k].loc[cut + pd.Timedelta("2h"):])
    # beta against numpy's slope on one name and one hour
    rc = (np.log(M.close.loc[hidx, NAMES]) - np.log(M.close.loc[hidx, NAMES].shift(1))).to_numpy() * 1e4
    rbb = (np.log(M.close.loc[hidx, BTC]) - np.log(M.close.loc[hidx, BTC].shift(1))).to_numpy() * 1e4
    j, i = len(hidx) - 10, 3
    x, y = rbb[j - 720 + 1: j + 1], rc[j - 720 + 1: j + 1, i]
    ok = np.isfinite(x) & np.isfinite(y)
    slope = np.polyfit(x[ok], y[ok], 1)[0]
    assert abs(F0["beta_btc"].iloc[j, i] - slope) < 1e-6 and abs(slope - BETAS[i] * (1 - 0.3)) < 0.25        # the contemporaneous share of the planted beta
    assert np.isfinite(F0["beta_btc"].iloc[j]).all()
    lead, bx, rev = (F0[k].iloc[j] for k in ("lead_1h", "bx_1h", "rev_1h"))
    assert np.allclose(lead, bx + rev, equal_nan=True)                        # lead = BTC's term + the plain reversal, by construction


def test_members_by_block_follow_the_frozen_csv(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    m = _module()
    mem = pd.read_csv(tmp_path / "m.csv")
    mem = mem[~((mem["block"] == BLOCKS[1]) & (mem["symbol"] == WRONG[0]))]       # one name leaves one block
    mem.to_csv(tmp_path / "m2.csv", index=False)
    C = m.cells_members(tmp_path / "m2.csv", fold_names=["F1"], hold=HOLD)
    v = C["validity"]
    assert v["status"] == "PASS" and v["cells_not_members"] == 0 and v["cells_outside_folds"] == 0 and v["names"] == len(NAMES) and v["blocks"] == 3
    cell = C["cell"]
    b1, b2 = pd.Timestamp(BLOCKS[1], tz="UTC"), pd.Timestamp(BLOCKS[2], tz="UTC")
    inside = (cell.index >= b1) & (cell.index < b2)
    assert not cell.loc[inside, WRONG[0]].any() and cell.loc[inside, WRONG[1]].all() and cell.loc[~inside, WRONG[0]].mean() > 0.9
    assert (cell.index >= pd.Timestamp("2023-05-03", tz="UTC")).all() and BTC not in cell.columns


def test_a_planted_lag_clears_stage_1_adding_to_the_plain_reversal_and_is_confirmed(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch)
    m = _module()
    s = _stage1(m, tmp_path)
    v = s["validity"]
    assert v["status"] == "PASS" and v["whole_days"] and v["shifts"] == v["shifts_expected"] >= 10 and v["btc_hour_max_abs_diff"] == 0.0
    assert all(c > 0.95 for c in v["outside"]["cover"].values()) and all(c > 0.95 for c in v["twelve"]["cover"].values())
    tab = pd.read_csv("output/audit/r50_test/features.csv").set_index(["universe", "feature", "hold"])
    assert len(tab) == 2 * 4 * 3 and tab["family"].sum() == 12
    for uni in ("outside", "twelve"):
        r = tab.loc[(uni, "lead_1h", 12)]
        assert r["ic_c"] > 0.05 and r["u"] > 2 and r["p_family"] <= 0.05 and bool(r["parts_same_sign"]) and r["u_delta"] > 2 and r["verdict"] == "CLEARS", (uni, dict(r))
        b = tab.loc[(uni, "bx_1h", 12)]
        assert b["ic_c"] > 0.05 and b["verdict"] == "CLEARS", (uni, dict(b))
        plain = tab.loc[(uni, "rev_1h", 12)]
        assert plain["verdict"] == "reference" and plain["ic_c"] < r["ic_c"] and np.isnan(plain["u_delta"])  # the plain reversal sees the laggards too (a low mover is a laggard or a low beta); lead tells them apart
        assert tab.loc[(uni, "beta_btc", 12), "verdict"] == "reference"
    cl = {(c["universe"], c["feature"], c["hold"]) for c in s["cleared"]}
    assert {("outside", "lead_1h", 12), ("twelve", "lead_1h", 12), ("outside", "bx_1h", 12), ("twelve", "bx_1h", 12)} <= cl and s["run_stage2"]
    assert all(c["sign"] == 1 for c in s["cleared"] if c["hold"] == 12)
    refs = pd.read_csv("output/audit/r50_test/reference.csv")
    assert {"lead_1h after a BTC rise (b_1h > 0)", "lead_1h at 13-21 UTC", "break-even IC for the top tenth, taker", "the run's forecast (R18's candle ridge)"} <= set(refs["row"])
    assert (refs[refs["row"].str.startswith("break-even")]["ic"] > 0).all()
    out = Path("output/audit/r50_test")
    for f in ("stage1.md", "stage1.json", "features.csv", "reference.csv", "shifts.parquet", "validity.json"):
        assert (out / f).exists(), f
    assert "CLEARS" in (out / "stage1.md").read_text() and "stage 2 RUNS" in (out / "stage1.md").read_text()
    # stage 2 on the same cells as the confirmation half
    s2 = m.stage2(members_csv=tmp_path / "m.csv", pairs=NAMES, twelve_run=None, fold_names=["F1"], jobs=1, out=out, gap=5, min_shifts=10)
    assert s2["validity"]["status"] == "PASS" and s2["validity"]["outside"]["cells_not_members"] == 0 and s2["validity"]["stage1_written"] == s["written"]
    res = pd.DataFrame(s2["rows"]).set_index(["universe", "feature", "hold"])
    for uni in ("outside", "twelve"):
        r = res.loc[(uni, "lead_1h", 12)]
        assert r["signed_u"] > 2 and r["p_family"] <= 0.05 and r["u_delta"] > 2 and r["verdict"] == "CLEARS", dict(r)
    assert s2["confirmed"] and s2["verdict"] == "CONFIRMED" and len(s2["cleared_confirmed"]) >= 4
    for f in ("stage2.md", "stage2.json", "features_f34.csv", "shifts_f34.parquet", "validity_f34.json"):
        assert (out / f).exists(), f
    assert "CONFIRMED" in (out / "stage2.md").read_text()


def test_a_world_without_the_lag_clears_nothing_and_stage_2_is_not_run(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch, lag=0.0)
    m = _module()
    s = _stage1(m, tmp_path)
    assert s["validity"]["status"] == "PASS" and s["cleared"] == [] and not s["run_stage2"]
    tab = pd.read_csv("output/audit/r50_test/features.csv")
    fam = tab[tab["family"]]
    assert (fam["verdict"] != "CLEARS").all() and (fam["ic_c"].abs() < 0.08).all(), fam[["universe", "feature", "hold", "ic_c", "u", "verdict"]]
    s2 = m.stage2(members_csv=tmp_path / "m.csv", pairs=NAMES, twelve_run=None, fold_names=["F1"], jobs=1, out=Path("output/audit/r50_test"), gap=5)
    assert s2["verdict"] == "NOTHING TO CONFIRM" and not s2["confirmed"] and not Path("output/audit/r50_test/features_f34.csv").exists()
    assert "NOTHING TO CONFIRM" in Path("output/audit/r50_test/stage2.md").read_text()
    assert m.verdict1({"family": True, "feature": "lead_1h", "u": 3.0, "p_family": 0.01, "parts_same_sign": True, "ic_c": 0.05, "se": 0.01, "u_delta": 1.0}) == "CLEARS AS THE PLAIN REVERSAL"
    assert m.verdict1({"family": True, "feature": "lead_1h", "u": -3.0, "p_family": 0.01, "parts_same_sign": True, "ic_c": -0.05, "se": 0.01, "u_delta": np.nan}) == "CLEARS WITH THE OPPOSITE SIGN"
    assert m.verdict1({"family": True, "feature": "bx_1h", "u": -3.0, "p_family": 0.01, "parts_same_sign": True, "ic_c": -0.05, "se": 0.01, "u_delta": np.nan}) == "CLEARS"
    assert m.verdict1({"family": True, "feature": "bx_1h", "u": 0.5, "p_family": 0.6, "parts_same_sign": False, "ic_c": 0.001, "se": 0.005, "u_delta": np.nan}) == "CLOSED"
    assert m.verdict2(0.01, 0.004, 0.2, 1, 0.1, None, False) == "REFUTED" and m.verdict2(0.004, 0.004, 0.2, 1, 0.005, None, False) == "NOT DETECTABLE"
