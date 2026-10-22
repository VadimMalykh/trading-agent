"""R68 unit tests for the spot source path of the breadth screen (`spot_ext.run_r68`) on made-up bars, no network: R62's saved screen on the
planted Coinbase members is reproduced FIRST through `cb_ext.frames` (a saved screen that does not match voids the run before any spot value
is touched; an inconsistent list voids at the lists); the spot frame is the trailing-day taker-buy share and the trailing-day spot/perp
ratio, each against its month, masked to the kept names and to membership; a planted CONTINUATION on both comes back with the registered
POSITIVE sign on the member cells; the hand check recomputes the features from the rows by cumulative sums (a hole of three hours leaves
NaN cells by the STALE rule, and the check reads them as NaN = NaN); the hourly forms and the levels are described beside; the name
dropped by the stamp check never enters; five draws certify nothing."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, spot_ext as sx
from ft2.spot_ext import SR, SR24, SR24L, TB, TB24, TB24L
from tests.test_p8_cb_ext import PAIRS, START, _world
from tests.test_p8_r62 import MEM, _kw, _members_world, _r60_saved

SLICES = ("candles_5m_archive", "candles_5m")
KEPT68 = [m for m in MEM if m != "THINUSDT"]                 # THIN is dropped by the stamp check (a different asset); 11 kept
HOLE = (pd.Timestamp("2023-05-12 08:00", tz="UTC"), 3)        # three missing hours on M05 from 08:00: the cells after two carried hours are NaN


def _spot_world(fast: float = 0.08, slow: float = 0.3, seed: int = 11):
    """The members' spot hourly rows from the planted archive closes: the taker-buy share of the hour = 0.5 + fast × the sign of the
    name's next-day relative return + noise; the spot quote volume = 0.2 × the perpetual's hour × exp(slow × the same sign + noise) — both
    trailing-day forms then CONTINUE into the next day's relative return. The list with THIN failing the stamp check."""
    rng = np.random.default_rng(seed)
    arch = pd.read_parquet("data/candles_5m_archive.parquet")
    arch["t"] = pd.DatetimeIndex(arch["open_time"]).tz_convert("UTC") + ceiling.BAR
    C = arch.pivot(index="t", columns="symbol", values="close")
    V = arch.pivot(index="t", columns="symbol", values="volume")
    hrs = C.index[C.index.minute == 0]
    hi = np.flatnonzero(C.index.minute == 0)
    L = np.log(C[MEM].to_numpy())
    fwd = np.roll(L, -288, axis=0) - L
    fwd[-288:] = 0.0
    rel = fwd - fwd.mean(axis=1, keepdims=True)
    dv = (C * V)
    pv = dv.groupby(dv.index.ceil("h")).sum(min_count=1).reindex(hrs)
    rows = []
    for i, sym in enumerate(MEM):
        sg = np.sign(rel[hi, i])
        tb = np.clip(0.5 + fast * sg + rng.normal(0, 0.03, len(hrs)), 0.02, 0.98)
        qv = 0.2 * pv[sym].to_numpy() * np.exp(slow * sg + rng.normal(0, 0.1, len(hrs)))
        px = C[sym].to_numpy()[hi] * (1 + 3e-4)
        keep = np.ones(len(hrs), bool)
        if sym == "M05USDT":
            k0 = int(np.flatnonzero(hrs == HOLE[0])[0])
            keep[k0:k0 + HOLE[1]] = False
        r = pd.DataFrame({"spot_symbol": sym[:-4] + "USDT", "symbol": sym, "ts": hrs - sx.HOUR, "ts_known": hrs, "open": px, "high": px, "low": px, "close": px,
                          "volume": qv / px, "quote_volume": qv, "count": 100, "taker_buy_volume": tb * qv / px, "taker_buy_quote_volume": tb * qv})
        rows.append(r[keep])
    pd.concat(rows, ignore_index=True).to_parquet("data/spot_1h.parquet", index=False)
    lst = pd.DataFrame({"symbol": MEM + ["NOPEUSDT"], "spot_symbol": [m[:-4] + "USDT" for m in MEM] + [""], "hours": [len(hrs)] * len(MEM) + [0], "cover_member": 1.0,
                        "abs_basis_median_bps": 3.0, "share_abs_basis_gt_50": [0.5 if m == "THINUSDT" else 0.001 for m in MEM] + [np.nan]})
    lst["r68"] = ((lst["hours"] > 0) & (lst["share_abs_basis_gt_50"] <= sx.R68_SHARE_CUT)).fillna(False)
    lst.to_csv("spot_members_r68.csv", index=False)


def _kw68(saved, **over):
    return dict(draws=5, shift_min=25, shift_floor=20, path="data/spot_1h.parquet", cb_path="data/coinbase_1h_members.parquet", r62=Path("output/ceiling_coinbase_members"),
                csv="spot_members_r68.csv", cb_csv="cb_members_r62.csv", members_csv="members.csv", slices=SLICES, mult={}, n_check=100,
                start=pd.Timestamp(START, tz="UTC"), block_min_names=5, r60=saved) | over


def _r62_saved(tmp_path):
    _world(tmp_path)
    _members_world(tmp_path)
    saved, _ = _r60_saved()
    cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, slices=SLICES))
    return saved


def test_the_lists_the_reproduction_and_the_coverage_each_void_the_run_before_any_spot_ic(tmp_path):
    saved = _r62_saved(tmp_path)
    _spot_world()
    L = sx.r68_list("spot_members_r68.csv")
    assert L["kept"] == KEPT68 and L["consistent"] and L["n_rows"] == 13 and L["with_series"] == 12
    assert L["md5"] == hashlib.md5(Path("spot_members_r68.csv").read_bytes()).hexdigest()
    bad = pd.read_csv("spot_members_r68.csv")
    bad.loc[bad["symbol"] == "THINUSDT", "r68"] = True
    bad.to_csv("spot_members_bad.csv", index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r68(5.0, 2.0, "test", **_kw68(saved, csv="spot_members_bad.csv"))
    v = json.loads(Path("output/ceiling_spot_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["lists"]["status"] == "FAIL" and "reproduction" not in v
    with pytest.raises(SystemExit) as e:                                                  # inadmissible nulls void before anything is read
        sx.run_r68(5.0, 2.0, "test", **_kw68(saved, shift_min=20, shift_floor=sx.SHIFT_FLOOR))
    v = json.loads(Path("output/ceiling_spot_members/validity.json").read_text())
    assert e.value.code == 2 and v["nulls"]["status"] == "FAIL" and "reproduction" not in v
    sc = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r68(5.0, 2.0, "test", **_kw68(saved))
    v = json.loads(Path("output/ceiling_spot_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "FAIL" and v["reproduction"]["max_abs_diff"]["t"] > 1e-6 and "hand" not in v
    assert not Path("output/ceiling_spot_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_spot_members.md").read_text()
    sc.to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:                                                  # the first block has 10 kept members (LATE is not among them)
        sx.run_r68(5.0, 2.0, "test", **_kw68(saved, block_min_names=11))
    v = json.loads(Path("output/ceiling_spot_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["hand"]["status"] == "PASS" and v["known_at"]["status"] == "PASS"
    assert v["coverage"]["status"] == "FAIL" and v["coverage"]["blocks_under_minimum"] == ["2023-05-03"] and v["coverage"]["covered_min"] == 10


def test_a_planted_continuation_on_both_flows_is_found_with_the_sign_on_the_member_cells_with_the_rows_beside(tmp_path):
    saved = _r62_saved(tmp_path)
    _spot_world()
    before = {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in ("data/spot_1h.parquet", "output/ceiling_coinbase_members/screen.parquet", "spot_members_r68.csv")}
    md = sx.run_r68(5.0, 2.0, "test", **_kw68(saved))
    assert {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in before} == before
    v = json.loads(Path("output/ceiling_spot_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == v["reproduction"]["rows_r62"] > 60 and v["lists"]["universe"]["n_kept"] == 11 and v["gate"]["bar_status"] == "PASS"
    assert v["hand"]["recomputed"] == 100 and v["hand"]["max_abs_diff"] < 1e-9 and v["hand"]["cells_with_a_value"] > 80 and v["hand"]["cells_nan_both"] >= 0
    for k in (TB24, SR24):
        assert v["known_at"][k]["cells_read_too_early"] == 0 and v["known_at"][k]["cells_older_than_stale"] == 0 and v["known_at"][k]["cells_with_a_value"] > 0
        assert v["membership"]["values_off_membership"][k] == 0
    assert v["coverage"]["blocks_scored"] == 2 and v["coverage"]["covered_min"] == 10 and v["coverage"]["covered_max"] == 11 and v["coverage_sr24"]["status"] == "PASS"
    assert v["kept_in_panel"] == 11 and v["names_in_panel"] == 11 and "THINUSDT" not in v and abs(v["features_corr_on_scored_cells"]["corr"]) > 0.3
    rows = pd.read_parquet("output/ceiling_spot_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    for k in (TB24, SR24):
        d = g.loc[k, "relative", "1d"]
        assert d["ic"] > 0.2 and d["t"] > 4 and d["ic_F1"] > 0.2 and np.isnan(d["ic_F2"]) and bool(d["folds_same_sign"]) is False
        assert d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE" and d["bar_maker_twelve"] == cx.BAR_TWELVE and d["bar_taker_members"] > 0
        assert g.loc[k, "relative", "4h"]["verdict"] == "reported, not gated" and np.isnan(g.loc[k, "relative", "4h"]["p_fw_shift"])
        assert np.isfinite(g.loc[k, "relative", "1h"]["p_single_shift"]) and np.isnan(g.loc[k, "relative", "1h"]["bar_maker_twelve"])
    for f_, word in ((TB, "HOURLY taker-buy"), (SR, "HOURLY spot/perp"), (TB24L, "the level"), (SR24L, "the level")):
        r = g.loc[f_, "relative", "1d"]
        assert word in r["verdict"] and np.isnan(r["p_family"]) and np.isfinite(r["ic"])
    assert g.loc[TB, "relative", "1d"]["ic"] > 0.1                                        # the hourly form carries the plant too, undiluted by the day
    null = pd.read_parquet("output/ceiling_spot_members/null_shift.parquet")
    assert set(null["feature"]) == {TB24, SR24} and null["draw"].max() == 5
    names = pd.read_parquet("output/ceiling_spot_members/names.parquet").set_index("symbol")
    assert set(names.index) == set(KEPT68) and abs(names["tb24_mean"].mean() - 0.5) < 0.02 and abs(names["sr24_mean"].mean() - np.log(0.2)) < 0.1
    # the hole: on the HOURLY form M05's cell reading the hole's third hour is NaN (the STALE carry covers two), the first two carried, the
    # hour after the hole back; the trailing-day forms ride through a three-hour hole (a 24-bar sum needs 20 present)
    Fr = sx.frames_spot(sx.r68_list("spot_members_r68.csv"), "data/spot_1h.parquet", SLICES, "members.csv", pd.Timestamp(START, tz="UTC"))["F"]
    t_nan = HOLE[0] + pd.Timedelta(hours=sx.STALE) + sx.MARGIN
    assert np.isnan(Fr[TB]["M05USDT"].loc[t_nan]) and np.isfinite(Fr[TB]["M05USDT"].loc[HOLE[0] + pd.Timedelta(hours=1) + sx.MARGIN])
    assert np.isfinite(Fr[TB]["M05USDT"].loc[HOLE[0] + pd.Timedelta(hours=HOLE[1]) + sx.MARGIN]) and np.isfinite(Fr[TB24]["M05USDT"].loc[t_nan])
    blocks = pd.read_parquet("output/ceiling_spot_members/blocks.parquet")
    assert len(blocks) == 2 and (blocks["covered"] >= 10).all() and blocks["ic_tb24"].notna().all() and blocks["ic_sr24"].notna().all()
    assert "## Verdict by R68's gate" in md and "## The kept names" in md
