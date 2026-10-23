"""R69 unit tests for the Hyperliquid source path of the breadth screen (`hl_ext.run_r69`) on made-up bars, no network: R62's saved screen on
the planted Coinbase members is reproduced FIRST through `cb_ext.frames` (a saved screen that does not match voids the run before any venue
value is touched; an inconsistent list voids at the lists; inadmissible nulls void before anything is read); the venue's frame is the
cross-venue gap of the trailing-day premiums against its month, masked to the kept names and to membership; a planted GIVE-BACK comes
back with the registered NEGATIVE sign on the member cells; the hand check recomputes the feature from the two parquets' rows by
cumulative sums (a hole of three hours rides through a 24-row mean); the venue's own, Binance's own and the level are described beside;
the name cut by the stamp check never enters; the scored sample's start cuts the blocks before it; five draws certify nothing."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, hl, hl_ext as hx
from ft2.hl_ext import BNP, FUND, GAP, GAPL, PREM
from tests.test_p8_cb_ext import PAIRS, START, _world
from tests.test_p8_r62 import MEM, _kw, _members_world, _r60_saved

SLICES = ("candles_5m_archive", "candles_5m")
KEPT69 = [m for m in MEM if m != "THINUSDT"]                 # THIN is cut by the stamp check (no correlation with Binance's bar); 11 kept
HOLE = (pd.Timestamp("2023-05-12 08:00", tz="UTC"), 3)        # three missing settlement hours on M05 from 08:00


def _hl_world(fast: float = 0.8, seed: int = 13):
    """The members' venue rows and Binance's premium bars from the planted archive closes: Binance's premium = 2 bps + a slow sine + noise;
    the venue's premium = Binance's + 1 bp − fast × the sign of the name's next-day relative return + noise — the day's gap then GIVES BACK
    into the next day's relative return (R69's sign). THIN's premium is 150 bps of noise and its stamp check fails the list's cut."""
    rng = np.random.default_rng(seed)
    arch = pd.read_parquet("data/candles_5m_archive.parquet")
    arch["t"] = pd.DatetimeIndex(arch["open_time"]).tz_convert("UTC") + ceiling.BAR
    C = arch.pivot(index="t", columns="symbol", values="close")
    hrs = C.index[C.index.minute == 0]
    hi = np.flatnonzero(C.index.minute == 0)
    L = np.log(C[MEM].to_numpy())
    fwd = np.roll(L, -288, axis=0) - L
    fwd[-288:] = 0.0
    rel = fwd - fwd.mean(axis=1, keepdims=True)
    rows, bars = [], []
    for i, sym in enumerate(MEM):
        bnp = 2.0 + 0.5 * np.sin(2 * np.pi * np.arange(len(hrs)) / (20 * 24) + i) + rng.normal(0, 0.3, len(hrs))
        prem = bnp + 1.0 - fast * np.sign(rel[hi, i]) + rng.normal(0, 0.3, len(hrs)) if sym != "THINUSDT" else rng.normal(0, 150.0, len(hrs))
        keep = np.ones(len(hrs), bool)
        if sym == "M05USDT":
            k0 = int(np.flatnonzero(hrs == HOLE[0])[0])
            keep[k0:k0 + HOLE[1]] = False
        r = pd.DataFrame({"coin": sym[:-4], "symbol": sym, "ts": hrs, "ts_known": hrs, "stamp": hrs + pd.Timedelta("50ms"), "lag_s": 0.05, "rate": prem / 1e4 + 1.25e-5, "premium": prem / 1e4, "frozen": False})
        rows.append(r[keep])
        bars.append(pd.DataFrame({"symbol": sym, "ts": hrs - hx.HOUR, "ts_known": hrs, "open": bnp / 1e4, "high": bnp / 1e4, "low": bnp / 1e4, "close": bnp / 1e4}))
    pd.concat(rows, ignore_index=True).to_parquet("data/hl_funding_1h.parquet", index=False)
    pd.concat(bars, ignore_index=True).to_parquet("data/premium_1h.parquet", index=False)
    lst = pd.DataFrame({"symbol": MEM + ["NOPEUSDT"], "coin": [m[:-4] for m in MEM] + [""], "listed": [True] * len(MEM) + [False], "rows": [len(hrs)] * len(MEM) + [0],
                        "corr_lag0": [0.05 if m == "THINUSDT" else 0.7 for m in MEM] + [np.nan], "best_lag": 0})
    lst["r69"] = (lst["listed"] & (lst["rows"] >= hx.R69_MIN_ROWS) & (lst["corr_lag0"] >= hx.R69_CORR_CUT)).fillna(False)
    lst.to_csv("hl_members_r69.csv", index=False)


def _kw69(saved, **over):
    return dict(draws=5, shift_min=25, shift_floor=20, path="data/hl_funding_1h.parquet", bn_path="data/premium_1h.parquet", cb_path="data/coinbase_1h_members.parquet",
                r62=Path("output/ceiling_coinbase_members"), csv="hl_members_r69.csv", cb_csv="cb_members_r62.csv", members_csv="members.csv", slices=SLICES, mult={},
                n_check=100, start=pd.Timestamp(START, tz="UTC"), scored_from=pd.Timestamp(START, tz="UTC"), block_min_names=5, r60=saved) | over


def _r62_saved(tmp_path):
    _world(tmp_path)
    _members_world(tmp_path)
    saved, _ = _r60_saved()
    cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, slices=SLICES))
    return saved


def test_the_lists_the_nulls_the_reproduction_and_the_coverage_each_void_the_run_before_any_venue_ic(tmp_path):
    saved = _r62_saved(tmp_path)
    _hl_world()
    L = hx.r69_list("hl_members_r69.csv")
    assert L["kept"] == KEPT69 and L["consistent"] and L["n_rows"] == 13 and L["with_rows"] == 12
    assert L["md5"] == hashlib.md5(Path("hl_members_r69.csv").read_bytes()).hexdigest()
    bad = pd.read_csv("hl_members_r69.csv")
    bad.loc[bad["symbol"] == "THINUSDT", "r69"] = True
    bad.to_csv("hl_members_bad.csv", index=False)
    with pytest.raises(SystemExit) as e:
        hx.run_r69(5.0, 2.0, "test", **_kw69(saved, csv="hl_members_bad.csv"))
    v = json.loads(Path("output/ceiling_hl_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["lists"]["status"] == "FAIL" and "reproduction" not in v
    with pytest.raises(SystemExit) as e:
        hx.run_r69(5.0, 2.0, "test", **_kw69(saved, shift_min=20, shift_floor=hx.SHIFT_FLOOR))
    v = json.loads(Path("output/ceiling_hl_members/validity.json").read_text())
    assert e.value.code == 2 and v["nulls"]["status"] == "FAIL" and "reproduction" not in v
    sc = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        hx.run_r69(5.0, 2.0, "test", **_kw69(saved))
    v = json.loads(Path("output/ceiling_hl_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "FAIL" and v["reproduction"]["max_abs_diff"]["t"] > 1e-6 and "hand" not in v
    assert not Path("output/ceiling_hl_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_hl_members.md").read_text()
    sc.to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:                                                  # the first block has 10 kept members (LATE is not among them)
        hx.run_r69(5.0, 2.0, "test", **_kw69(saved, block_min_names=11))
    v = json.loads(Path("output/ceiling_hl_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["hand"]["status"] == "PASS" and v["known_at"]["status"] == "PASS" and v["scored_from"]["status"] == "PASS"
    assert v["coverage"]["status"] == "FAIL" and v["coverage"]["blocks_under_minimum"] == ["2023-05-03"] and v["coverage"]["covered_min"] == 10


def test_a_planted_give_back_on_the_gap_is_found_with_the_negative_sign_on_the_member_cells_with_the_rows_beside(tmp_path):
    saved = _r62_saved(tmp_path)
    _hl_world()
    before = {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in ("data/hl_funding_1h.parquet", "data/premium_1h.parquet", "output/ceiling_coinbase_members/screen.parquet", "hl_members_r69.csv")}
    md = hx.run_r69(5.0, 2.0, "test", **_kw69(saved))
    assert {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in before} == before
    v = json.loads(Path("output/ceiling_hl_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == v["reproduction"]["rows_r62"] > 60 and v["lists"]["universe"]["n_kept"] == 11 and v["gate"]["bar_status"] == "PASS"
    assert v["hand"]["recomputed"] == 100 and v["hand"]["max_abs_diff"] < 1e-9 and v["hand"]["cells_with_a_value"] > 80
    assert v["known_at"][GAP]["cells_read_too_early"] == 0 and v["known_at"][GAP]["cells_older_than_stale"] == 0 and v["known_at"][GAP]["cells_with_a_value"] > 0
    assert v["membership"]["values_off_membership"][GAP] == 0
    assert v["coverage"]["blocks_scored"] == 2 and v["coverage"]["covered_min"] == 10 and v["coverage"]["covered_max"] == 11
    assert v["scored_from"]["status"] == "PASS" and pd.Timestamp(v["scored_from"]["first"]) == pd.Timestamp("2023-05-03", tz="UTC")
    assert v["kept_in_panel"] == 11 and v["names_in_panel"] == 11 and "THINUSDT" not in v and abs(v["corr_with_bn_prem24_dev_on_scored_cells"]["corr"]) < 0.5
    rows = pd.read_parquet("output/ceiling_hl_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    d = g.loc[GAP, "relative", "1d"]
    assert d["ic"] < -0.2 and d["t"] < -4 and d["ic_F1"] < -0.2 and np.isnan(d["ic_F2"]) and bool(d["folds_same_sign"]) is False
    assert d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE" and d["bar_maker_twelve"] == cx.BAR_TWELVE and d["bar_taker_members"] > 0
    assert g.loc[GAP, "relative", "4h"]["verdict"] == "reported, not gated" and np.isnan(g.loc[GAP, "relative", "4h"]["p_fw_shift"])
    assert np.isfinite(g.loc[GAP, "relative", "1h"]["p_single_shift"]) and np.isnan(g.loc[GAP, "relative", "1h"]["bar_maker_twelve"])
    for f_, word in ((PREM, "venue's own trailing-day premium"), (FUND, "venue's own trailing-day funding"), (BNP, "Binance's own"), (GAPL, "the level")):
        r = g.loc[f_, "relative", "1d"]
        assert word in r["verdict"] and np.isnan(r["p_family"]) and np.isfinite(r["ic"])
    assert g.loc[PREM, "relative", "1d"]["ic"] < -0.2 and abs(g.loc[BNP, "relative", "1d"]["ic"]) < 0.1   # the plant sits in the venue's premium, not in Binance's
    null = pd.read_parquet("output/ceiling_hl_members/null_shift.parquet")
    assert set(null["feature"]) == {GAP} and null["draw"].max() == 5
    names = pd.read_parquet("output/ceiling_hl_members/names.parquet").set_index("symbol")
    assert set(names.index) == set(KEPT69) and abs(names["gap24_mean"].mean() - 1.0) < 0.15
    # the hole: the 24-row mean rides through three missing settlements (≥ 20 present), so M05's cells across the hole have a value
    fr = hx.frames_hl(hx.r69_list("hl_members_r69.csv"), "data/hl_funding_1h.parquet", "data/premium_1h.parquet", SLICES, "members.csv", pd.Timestamp(START, tz="UTC"), scored_from=pd.Timestamp(START, tz="UTC"))
    t_in = HOLE[0] + pd.Timedelta(hours=hx.STALE) + hx.MARGIN
    assert np.isfinite(fr["F"][GAP]["M05USDT"].loc[t_in]) and np.isfinite(fr["F"][GAP]["M05USDT"].loc[HOLE[0] + pd.Timedelta(hours=HOLE[1] + 1) + hx.MARGIN])
    # the scored sample's start: from the second block only the second block is scored, and the first bar is at or after it
    fr2 = hx.frames_hl(hx.r69_list("hl_members_r69.csv"), "data/hl_funding_1h.parquet", "data/premium_1h.parquet", SLICES, "members.csv", pd.Timestamp(START, tz="UTC"), scored_from=pd.Timestamp("2023-06-02", tz="UTC"))
    assert fr2["s"].sum() < fr["s"].sum() and fr2["idx"][fr2["s"]][0] >= pd.Timestamp("2023-06-02", tz="UTC") and fr2["D"]["scored"].sum() == fr2["s"].sum()
    cov2, _ = cx.block_coverage(fr2["F"][GAP], fr2["s"], fr2["m"], fr2["kept"], 5)
    assert cov2["blocks_scored"] == 1
    blocks = pd.read_parquet("output/ceiling_hl_members/blocks.parquet")
    assert len(blocks) == 2 and (blocks["covered"] >= 10).all() and blocks["ic_gap24"].notna().all()
    assert "## Verdict by R69's gate" in md and "## The kept names" in md
