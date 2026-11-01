"""R73 unit tests for the participant-mix path of the breadth screen (`mix_ext.run_r73`) on made-up bars, no network: the tables' fingerprints
and the lists void the run before any count is touched; R62's saved screen is reproduced first; a planted SWARM OF SMALL TRADES that GIVES
BACK — the perp and spot counts above their month when the name's next-day relative return is negative, the mean size below — comes back
with the registered signs (count −, size +) on the member cells; the hand check recomputes both features from the two tables' rows by
cumulative sums (a spot hole of three hours leaves NaN cells by the STALE rule); each market alone, the volume control, the hourly forms
and the levels are described beside; five draws certify nothing."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import ceiling, mix, mix_ext as mx
from ft2.mix_ext import CNT, HOURLY, LEVEL, PERP, QV, SIZE, SPOT
from tests.test_p8_cb_ext import START
from tests.test_p8_r62 import MEM
from tests.test_p8_spot_ext import HOLE, KEPT68, SLICES, _r62_saved, _spot_world


def _mix_world(fast: float = 0.6, seed: int = 5):
    """The perp table from the planted archive bars (the hour's Σ volume × close as its quote volume) with a count planted to SWARM when the
    name's next-day relative return is NEGATIVE; the spot table's count re-planted the same way at a quarter of the size. The spot hole
    on M05 (three hours) stays — the combined quantity is NaN there."""
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
    sp = pd.read_parquet("data/spot_1h.parquet")
    perp, spot_parts = [], []
    for i, sym in enumerate(MEM):
        sg = np.sign(rel[hi, i])
        n_p = np.maximum(1, np.round(400.0 * np.exp(-fast * sg + rng.normal(0, 0.15, len(hrs))))).astype("int64")
        n_s = np.maximum(1, np.round(100.0 * np.exp(-fast * sg + rng.normal(0, 0.15, len(hrs))))).astype("int64")
        qv = pv[sym].to_numpy()
        perp.append(pd.DataFrame({"symbol": sym, "ts": hrs - mx.HOUR, "ts_known": hrs, "close": C[sym].to_numpy()[hi], "volume": qv / C[sym].to_numpy()[hi], "quote_volume": qv,
                                  "count": n_p, "taker_buy_volume": qv / C[sym].to_numpy()[hi] / 2, "taker_buy_quote_volume": qv / 2, "bars": 12}))
        g = sp[sp["symbol"] == sym].set_index("ts_known")
        g["count"] = pd.Series(n_s, index=hrs).reindex(g.index).to_numpy()
        spot_parts.append(g.reset_index())
    other = sp[~sp["symbol"].isin(MEM)]
    pd.concat(spot_parts + [other], ignore_index=True)[sp.columns].to_parquet("data/spot_1h.parquet", index=False)
    P = pd.concat(perp, ignore_index=True)
    P["symbol"] = P["symbol"].astype("category")
    P[mix.COLS].to_parquet("data/perp_mix_1h.parquet", index=False)


def _fps():
    perp_fp = mix.fingerprint(mix.load("data/perp_mix_1h.parquet"))
    sd = pd.read_parquet("data/spot_1h.parquet", columns=["symbol"])
    return perp_fp, {"rows": int(len(sd)), "symbols": int(sd["symbol"].astype(str).nunique())}


def _kw73(saved, **over):
    perp_fp, spot_fp = _fps()
    return dict(draws=5, shift_min=25, shift_floor=20, perp_path="data/perp_mix_1h.parquet", spot_path="data/spot_1h.parquet", cb_path="data/coinbase_1h_members.parquet",
                r62=Path("output/ceiling_coinbase_members"), csv="spot_members_r68.csv", cb_csv="cb_members_r62.csv", members_csv="members.csv", slices=SLICES, mult={},
                n_check=100, start=pd.Timestamp(START, tz="UTC"), block_min_names=5, r60=saved, perp_fp=perp_fp, spot_fp=spot_fp) | over


def test_the_tables_the_lists_and_the_reproduction_each_void_the_run_before_any_count_is_read(tmp_path):
    saved = _r62_saved(tmp_path)
    _spot_world()
    _mix_world()
    perp_fp, spot_fp = _fps()
    with pytest.raises(SystemExit) as e:                                                  # a fingerprint that is not the audited one
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved, perp_fp=perp_fp | {"count_sum": perp_fp["count_sum"] + 1}))
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["tables"]["status"] == "FAIL" and "reproduction" not in v
    with pytest.raises(SystemExit) as e:                                                  # no audited fingerprint at all
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved, perp_fp={}))
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert e.value.code == 2 and v["tables"]["status"] == "FAIL" and v["tables"]["expected" if False else "perp"]["expected"] == {}
    with pytest.raises(SystemExit) as e:                                                  # the spot table's rows not as audited
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved, spot_fp=spot_fp | {"rows": spot_fp["rows"] - 1}))
    assert e.value.code == 2
    bad = pd.read_csv("spot_members_r68.csv")
    bad.loc[bad["symbol"] == "THINUSDT", "r68"] = True
    bad.to_csv("spot_members_bad.csv", index=False)
    with pytest.raises(SystemExit) as e:
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved, csv="spot_members_bad.csv"))
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert e.value.code == 2 and v["lists"]["status"] == "FAIL" and "reproduction" not in v
    with pytest.raises(SystemExit) as e:                                                  # inadmissible nulls
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved, shift_min=20, shift_floor=mx.SHIFT_FLOOR))
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert e.value.code == 2 and v["nulls"]["status"] == "FAIL" and "reproduction" not in v
    sc = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved))
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert e.value.code == 2 and v["tables"]["status"] == "PASS" and v["reproduction"]["status"] == "FAIL" and "hand" not in v
    assert not Path("output/ceiling_mix_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_mix_members.md").read_text()
    sc.to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:                                                  # the first block has 10 kept members
        mx.run_r73(5.0, 2.0, "test", **_kw73(saved, block_min_names=11))
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["hand"]["status"] == "PASS" and v["known_at"]["status"] == "PASS"
    assert v["coverage"]["status"] == "FAIL" and v["coverage"]["blocks_under_minimum"] == ["2023-05-03"] and v["coverage"]["covered_min"] == 10


def test_a_planted_swarm_that_gives_back_is_found_with_both_signs_on_the_member_cells_with_the_rows_beside(tmp_path):
    saved = _r62_saved(tmp_path)
    _spot_world()
    _mix_world()
    before = {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in ("data/perp_mix_1h.parquet", "data/spot_1h.parquet", "output/ceiling_coinbase_members/screen.parquet", "spot_members_r68.csv")}
    md = mx.run_r73(5.0, 2.0, "test", **_kw73(saved))
    assert {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in before} == before
    v = json.loads(Path("output/ceiling_mix_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["tables"]["status"] == "PASS" and v["reproduction"]["rows_compared"] == v["reproduction"]["rows_r62"] > 60 and v["lists"]["universe"]["n_kept"] == 11
    assert v["hand"]["recomputed"] == 100 and v["hand"]["max_abs_diff"] < 1e-9 and v["hand"]["cells_with_a_value"] > 80
    for k in (CNT, SIZE):
        assert v["known_at"][k]["cells_read_too_early"] == 0 and v["known_at"][k]["cells_older_than_stale"] == 0 and v["known_at"][k]["cells_with_a_value"] > 0
        assert v["membership"]["values_off_membership"][k] == 0
    assert v["coverage"]["blocks_scored"] == 2 and v["coverage"]["covered_min"] == 10 and v["coverage"]["covered_max"] == 11 and v["coverage_size"]["status"] == "PASS"
    assert v["kept_in_panel"] == 11 and v["names_in_panel"] == 11 and v["gate"]["sign"] == {CNT: -1.0, SIZE: 1.0}
    assert v["features_corr_on_scored_cells"][f"{CNT}_x_{SIZE}"]["corr"] < -0.5                  # the size is the volume over the count
    rows = pd.read_parquet("output/ceiling_mix_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    c, z = g.loc[CNT, "relative", "1d"], g.loc[SIZE, "relative", "1d"]
    assert c["ic"] < -0.2 and c["t"] < -4 and c["ic_F1"] < -0.2 and np.isnan(c["ic_F2"]) and bool(c["folds_same_sign"]) is False
    assert z["ic"] > 0.2 and z["t"] > 4 and z["ic_F1"] > 0.2
    for d in (c, z):
        assert d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE" and d["bar_maker_twelve"] == mx.BAR_TWELVE and d["bar_taker_members"] > 0
    for k in (CNT, SIZE):
        assert g.loc[k, "relative", "4h"]["verdict"] == "reported, not gated" and np.isnan(g.loc[k, "relative", "4h"]["p_fw_shift"])
        assert np.isfinite(g.loc[k, "relative", "1h"]["p_single_shift"]) and np.isnan(g.loc[k, "relative", "1h"]["bar_maker_twelve"])
    assert g.loc[PERP[CNT], "relative", "1d"]["ic"] < -0.2 and g.loc[SPOT[CNT], "relative", "1d"]["ic"] < -0.2            # each market alone carries the plant
    assert g.loc[PERP[SIZE], "relative", "1d"]["ic"] > 0.2 and g.loc[SPOT[SIZE], "relative", "1d"]["ic"] > 0.2
    assert g.loc[QV, "relative", "1d"]["ic"] > 0.2                                     # the volume control rides R68's planted spot-volume CONTINUATION (+), the count's plant is the other way
    for f_, word in ((QV, "magnitude control"), (PERP[CNT], "perpetual's count"), (SPOT[SIZE], "spot market's mean size"), (HOURLY[CNT], "HOURLY count"), (LEVEL[SIZE], "the level")):
        r = g.loc[f_, "relative", "1d"]
        assert word in r["verdict"] and np.isnan(r["p_family"]) and np.isfinite(r["ic"])
    null = pd.read_parquet("output/ceiling_mix_members/null_shift.parquet")
    assert set(null["feature"]) == {CNT, SIZE} and null["draw"].max() == 5
    names = pd.read_parquet("output/ceiling_mix_members/names.parquet").set_index("symbol")
    assert set(names.index) == set(KEPT68) and (names["spot_share_of_count_median"].between(0.1, 0.3)).all() and (names["hours_both"] > 1000).all()
    # the spot hole: the combined quantity is NaN where the spot bar is missing — the HOURLY form's cell reading the hole's third hour is NaN
    # (the STALE carry covers two); the trailing-day forms ride through (a 24-bar sum needs 20 present)
    Fr = mx.frames_mix(mx.r68_list("spot_members_r68.csv"), "data/perp_mix_1h.parquet", "data/spot_1h.parquet", SLICES, "members.csv", pd.Timestamp(START, tz="UTC"))["F"]
    t_nan = HOLE[0] + pd.Timedelta(hours=mx.STALE) + mx.MARGIN
    assert np.isnan(Fr[HOURLY[CNT]]["M05USDT"].loc[t_nan]) and np.isfinite(Fr[HOURLY[CNT]]["M05USDT"].loc[HOLE[0] + pd.Timedelta(hours=1) + mx.MARGIN])
    assert np.isfinite(Fr[CNT]["M05USDT"].loc[t_nan])
    blocks = pd.read_parquet("output/ceiling_mix_members/blocks.parquet")
    assert len(blocks) == 2 and (blocks["covered"] >= 10).all() and blocks["ic_cnt24"].notna().all() and blocks["ic_size24"].notna().all()
    assert "## Verdict by R73's gate" in md and "## The kept names" in md
