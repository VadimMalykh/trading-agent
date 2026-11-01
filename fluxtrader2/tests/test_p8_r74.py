"""R74 unit tests for the confirmation path of the participant mix (`mix_ext.run_r74`) on made-up bars, no network: R73's test world (R62's
saved screen, the spot world, the swarm planted on the perp and spot counts — F0 as warm-up, F1 scored) gives R73's saved screen by R73's own
run; a second span of the same generators, F3's first nine weeks with its own member file, is appended to the same files. The run checks the
lists and the two tables' fingerprints, reproduces R73's 132 rows through the fold-parameterised frame to 0.0, appends the guard rows (R74,
F3) and (R74, F4) BEFORE any F3+F4 bar, then finds the count on F3 with the registered NEGATIVE sign on the planted cells, the size cell (the
opposite sign on F1+F2) and the other nine forms described beside; a second invocation is refused by the guard (exit 2, nothing written); a
mismatching R73 screen, a fingerprint off by one or an inconsistent list voids BEFORE the guard (no row appended); five draws certify nothing
(a fold without bars leaves the folds' sign check unmet)."""
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tests.test_p8_cb_ext as w_cb
import tests.test_p8_r62 as w62
import tests.test_p8_spot_ext as wsp
from ft2 import cb_ext as cx, mix_ext as mx
from ft2.mix_ext import CNT, HOURLY, LEVEL, PERP, QV, SIZE, SPOT
from tests.test_p8_cb_ext import START, _world
from tests.test_p8_mix_ext import _fps, _kw73, _mix_world
from tests.test_p8_r62 import _members_world
from tests.test_p8_r66 import BLOCKS34, DAYS2, END1, HOLE2, START2
from tests.test_p8_spot_ext import SLICES, _r62_saved, _spot_world

READS, PLAN = Path("output/backtest/confirmation_reads.csv"), Path("docs/PLAN.md")
SPAN_FILES = ("data/candles_5m.parquet", "data/candles_5m_archive.parquet", "data/cost_daily.parquet", "data/cost_daily_wide.parquet", "data/spot_1h.parquet",
              "data/perp_mix_1h.parquet")


def _r74_world(tmp_path, monkeypatch):
    """Span 1: R73's world and R73's own run (its saved screen = validity (2) of R74). Span 2: the same generators moved to F3 by the
    constants their helpers read, written beside and APPENDED to span 1's files (the twelve's and the members' candles, the cost files,
    the spot table, the perp table); its member file becomes the F3+F4 one; a PLAN stub holds the registration header."""
    saved = _r62_saved(tmp_path)
    _spot_world()
    _mix_world()
    mx.run_r73(5.0, 2.0, "test", **_kw73(saved))
    span2 = tmp_path / "span2"
    span2.mkdir()
    with monkeypatch.context() as m:
        for mod, names in ((w_cb, ("START", "DAYS", "HOLE")), (w62, ("START", "DAYS", "BLOCKS"))):
            for n in names:
                m.setattr(mod, n, {"START": START2, "DAYS": DAYS2, "HOLE": HOLE2, "BLOCKS": BLOCKS34}[n])
        m.setattr(wsp, "HOLE", (HOLE2[0], 3))
        _world(span2)
        _members_world(span2)
        _spot_world()
        _mix_world()
    os.chdir(tmp_path)
    for f in SPAN_FILES:
        pd.concat([pd.read_parquet(tmp_path / f), pd.read_parquet(span2 / f)], ignore_index=True).to_parquet(tmp_path / f, index=False)
    shutil.copy(span2 / "members.csv", "members_f34.csv")
    PLAN.parent.mkdir(exist_ok=True)
    PLAN.write_text("# plan\n\n### R74 — the test's registration block (registered, read —)\nQuestion: …\n")
    return saved


def _kw74(saved, **over):
    perp_fp, spot_fp = _fps()
    return dict(draws=5, shift_min=25, shift_floor=20, perp_path="data/perp_mix_1h.parquet", spot_path="data/spot_1h.parquet", csv="spot_members_r68.csv",
                members_csv="members_f34.csv", r73_members_csv="members.csv", r73=Path("output/ceiling_mix_members"), slices=SLICES, n_check=100,
                start=pd.Timestamp(START2, tz="UTC"), f12_start=pd.Timestamp(START, tz="UTC"), f12_end=END1, block_min_names=5, r60=saved, perp_fp=perp_fp, spot_fp=spot_fp,
                reads=READS, plan=PLAN) | over


def test_the_count_is_read_on_f3_after_r73_is_reproduced_and_the_guard_rows_are_appended(tmp_path, monkeypatch):
    saved = _r74_world(tmp_path, monkeypatch)
    assert not READS.exists()
    md = mx.run_r74(5.0, 2.0, "test", **_kw74(saved))
    v = json.loads(Path("output/ceiling_mix_members_f34/validity.json").read_text())
    assert v["status"] == "PASS" and v["folds"] == ["F3", "F4"] and v["lists"]["universe"]["n_kept"] == 11 and v["tables"]["status"] == "PASS"
    r = v["reproduction_r73"]
    assert r["status"] == "PASS" and r["rows_compared"] == r["rows_saved"] == 132 and r["max_abs_diff"]["ic"] == 0.0 and r["max_abs_diff"]["t"] == 0.0
    assert v["guard"]["status"] == "PASS" and v["guard"]["folds"] == ["F3", "F4"]
    led = pd.read_csv(READS)
    assert list(led["registration"]) == ["R74", "R74"] and list(led["fold"]) == ["F3", "F4"] and set(led["strategy"]) == {"mix_cnt24_f34"}
    p = json.loads(led["params"].iloc[0])
    assert p["feature"] == CNT and p["sign"] == -1 and p["list_md5"] == v["lists"]["universe"]["md5"] and p["members_f34_md5"] == v["lists"]["members_f34"]["md5"]
    assert p["perp_fp"]["rows"] == v["tables"]["perp"]["fingerprint"]["rows"]
    fc = v["folds_check"]
    assert fc["status"] == "PASS" and fc["bars_outside_folds"] == 0 and fc["first"] >= "2024-09-03" and fc["whole_days"] > 50
    assert v["hand"]["status"] == "PASS" and v["hand"]["recomputed"] == 100 and v["hand"]["max_abs_diff"] < 1e-9
    for k in (CNT, SIZE):
        assert v["known_at"][k]["cells_read_too_early"] == 0 and v["known_at"][k]["cells_older_than_stale"] == 0 and v["known_at"][k]["cells_with_a_value"] > 0
        assert v["membership"]["values_off_membership"][k] == 0
    assert v["coverage"]["status"] == "PASS" and v["coverage"]["blocks_scored"] == 2 and v["kept_in_panel"] == 11
    assert v["features_corr_on_scored_cells"][f"{CNT}_x_{SIZE}"]["corr"] < -0.5
    rows = pd.read_parquet("output/ceiling_mix_members_f34/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    c = g.loc[CNT, "relative", "1d"]
    assert c["ic"] < -0.2 and c["t"] < -4 and c["ic_F3"] < -0.2 and np.isnan(c["ic_F4"]) and not c["folds_same_sign"]       # F4 has no bars in the world
    assert c["p_family"] == 1 / 6 and c["verdict"] == "NOT CONFIRMED — NOT DETECTABLE" and c["bar_maker_twelve"] == cx.BAR_TWELVE and c["bar_taker_members"] > 0
    assert g.loc[CNT, "relative", "4h"]["verdict"] == "reported, not gated" and np.isfinite(g.loc[CNT, "relative", "1h"]["p_single_shift"])
    z = g.loc[SIZE, "relative", "1d"]
    assert z["ic"] > 0.2 and np.isnan(z["p_family"]) and "first read on F3+F4" in z["verdict"]
    assert g.loc[PERP[CNT], "relative", "1d"]["ic"] < -0.2 and g.loc[SPOT[CNT], "relative", "1d"]["ic"] < -0.2
    for f_ in (QV, PERP[SIZE], SPOT[SIZE], HOURLY[CNT], HOURLY[SIZE], LEVEL[CNT], LEVEL[SIZE]):
        assert np.isnan(g.loc[f_, "relative", "1d"]["p_family"]) and "described" in g.loc[f_, "relative", "1d"]["verdict"], f_
    assert set(rows["feature"]) == set(mx.ALL) and len(rows) == 132
    B = pd.read_parquet("output/ceiling_mix_members_f34/blocks.parquet")
    assert len(B) == 2 and list(B["covered"]) == [10, 11] and "ic_size24" in B
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R74's gate" in md and "F3+F4 (embargoed)" in md
    assert Path("output/ceiling_mix_members_f34/validity_r73.csv").exists() and Path("output/ceiling_mix_members_f34/names.parquet").exists()
    # R73's outputs untouched by the confirmation's run
    assert json.loads(Path("output/ceiling_mix_members/validity.json").read_text())["registration"] == "R73"
    # once: the second invocation is refused by the guard before any F3+F4 bar — the ledger unchanged, the read void
    with pytest.raises(SystemExit) as e:
        mx.run_r74(5.0, 2.0, "test", **_kw74(saved))
    v2 = json.loads(Path("output/ceiling_mix_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v2["status"] == "FAIL" and v2["guard"]["status"] == "FAIL" and "folds_check" not in v2 and "hand" not in v2
    assert len(pd.read_csv(READS)) == 2 and "VOID" in Path("output/ceiling_mix_members_f34.md").read_text()
    # the fold-parameterised frame: with F1+F2 the mask is derive's own
    L = mx.r68_list("spot_members_r68.csv")
    fr = mx.frames_mix_folds(L, ("F1", "F2"), "data/perp_mix_1h.parquet", "data/spot_1h.parquet", SLICES, "members.csv", pd.Timestamp(START, tz="UTC"), END1)
    assert fr["folds"] == ["F1", "F2"] and fr["s"].sum() == fr["D"]["scored"].sum() > 0 and not fr["s"][fr["idx"] >= pd.Timestamp("2024-09-01", tz="UTC")].any()
    fr34 = mx.frames_mix_folds(L, ("F3", "F4"), "data/perp_mix_1h.parquet", "data/spot_1h.parquet", SLICES, "members_f34.csv", pd.Timestamp(START2, tz="UTC"),
                               pd.Timestamp("2026-01-01", tz="UTC"))
    assert fr34["folds"] == ["F3", "F4"] and fr34["s"].sum() == v["scored_bars"]


def test_a_mismatching_r73_screen_a_fingerprint_off_by_one_or_a_bad_list_voids_before_the_guard(tmp_path, monkeypatch):
    saved = _r74_world(tmp_path, monkeypatch)
    perp_fp, _ = _fps()
    with pytest.raises(SystemExit) as e:                                                  # the perp table is not the audited one
        mx.run_r74(5.0, 2.0, "test", **_kw74(saved, perp_fp=perp_fp | {"count_sum": perp_fp["count_sum"] + 1}))
    v = json.loads(Path("output/ceiling_mix_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["tables"]["status"] == "FAIL" and "reproduction_r73" not in v and "guard" not in v and not READS.exists()
    bad = pd.read_csv("spot_members_r68.csv")
    bad.loc[bad["symbol"] == "THINUSDT", "r68"] = True
    bad.to_csv("spot_members_bad.csv", index=False)
    with pytest.raises(SystemExit) as e:
        mx.run_r74(5.0, 2.0, "test", **_kw74(saved, csv="spot_members_bad.csv"))
    v = json.loads(Path("output/ceiling_mix_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["lists"]["status"] == "FAIL" and "reproduction_r73" not in v and not READS.exists()
    sc = pd.read_parquet("output/ceiling_mix_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_mix_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        mx.run_r74(5.0, 2.0, "test", **_kw74(saved))
    v = json.loads(Path("output/ceiling_mix_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["tables"]["status"] == "PASS" and v["reproduction_r73"]["status"] == "FAIL" and "guard" not in v
    assert not READS.exists() and not Path("output/ceiling_mix_members_f34/screen.parquet").exists() and "VOID" in Path("output/ceiling_mix_members_f34.md").read_text()
    sc.to_parquet("output/ceiling_mix_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:                                                  # inadmissible nulls void before anything is read
        mx.run_r74(5.0, 2.0, "test", **_kw74(saved, shift_min=20, shift_floor=mx.SHIFT_FLOOR))
    v = json.loads(Path("output/ceiling_mix_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["nulls"]["status"] == "FAIL" and "reproduction_r73" not in v and not READS.exists()
