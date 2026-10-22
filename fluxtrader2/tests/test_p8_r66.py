"""R66 unit tests for the confirmation path (`score_ext.run_r66`) on made-up bars, no network: R65's world (its plants — the Coinbase
premium continuing the next day's relative return, the high-beta names giving back a BTC fall — F0 as warm-up, F1 scored) gives R65's
saved screen by R65's own run; a second span of the same world, F3's first nine weeks with its own member file, is appended to the same
files. The run checks the lists, reproduces R65's rows through the fold-parameterised frame to 0.0 and R50's reference rows, appends the
guard rows (R66, F3) and (R66, F4) BEFORE any F3+F4 bar, then finds the score on F3 with the registered POSITIVE sign and above either
input alone on the planted cells, `cbprem_dev`'s first F3+F4 read and −bx_1h on the fall bars described beside; a second invocation is
refused by the guard (exit 2, nothing written); a mismatching R65 screen, R50 reference or list voids BEFORE the guard (no row appended);
an hourly bar after t fails the check; five draws certify nothing (a fold without bars leaves the folds' sign check unmet)."""
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import tests.test_p8_cb_ext as w_cb
import tests.test_p8_r62 as w62
import tests.test_p8_r65 as w65
from ft2 import cb_ext as cx, score_ext as sx
from ft2.cb_ext import DEV
from ft2.score_ext import BXF, SCF, SCO, SCORE
from tests.test_p8_cb_ext import DAYS, START
from tests.test_p8_r62 import MEM
from tests.test_p8_r65 import SLICES, _kw65, _r50_reference, _r62_saved, _r65_world

END1 = pd.Timestamp(START, tz="UTC") + pd.Timedelta(minutes=5 * (DAYS * 288 - 1))     # the last bar of R65's world (span 1)
START2, DAYS2 = "2024-08-01", 98                                                       # span 2: a month of warm-up, then F3's first nine weeks
HOLE2 = (pd.Timestamp("2024-09-20 06:00", tz="UTC"), 5)
BLOCKS34 = {"2024-09-03": [m for m in MEM if m != "LATEUSDT"], "2024-10-03": MEM}
SPAN_FILES = ("data/candles_5m.parquet", "data/candles_5m_archive.parquet", "data/coinbase_1h_members.parquet", "data/cost_daily_wide.parquet")
READS, PLAN = Path("output/backtest/confirmation_reads.csv"), Path("docs/PLAN.md")


def _r66_world(tmp_path, monkeypatch):
    """Span 1: R65's world, R62's and R65's saved screens and R50's reference by their own runs. Span 2: the same generator moved to F3
    by the constants its helpers read, written beside and APPENDED to span 1's files (the twelve's and the members' candles, the members'
    Coinbase premium, the cost proxy); its member file becomes the F3+F4 one; R66's list = R62's rows under the `r66` flag; a PLAN stub
    holds the registration header."""
    _r65_world(tmp_path)
    saved = _r62_saved()
    A, ref = _r50_reference()
    sx.run_r65(5.0, 2.0, "test", **_kw65(saved, A, ref))                 # R65's saved screen on span 1: validity (2) of R66
    span2 = tmp_path / "span2"
    span2.mkdir()
    with monkeypatch.context() as m:
        for mod, names in ((w_cb, ("START", "DAYS", "HOLE")), (w62, ("START", "DAYS")), (w65, ("START", "DAYS", "BLOCKS"))):
            for n in names:
                m.setattr(mod, n, {"START": START2, "DAYS": DAYS2, "HOLE": HOLE2, "BLOCKS": BLOCKS34}[n])
        _r65_world(span2)
    os.chdir(tmp_path)
    for f in SPAN_FILES:
        pd.concat([pd.read_parquet(tmp_path / f), pd.read_parquet(span2 / f)], ignore_index=True).to_parquet(tmp_path / f, index=False)
    shutil.copy(span2 / "members.csv", "members_f34.csv")
    pd.read_csv("cb_members_r62.csv").rename(columns={"r62": "r66"}).to_csv("cb_members_r66.csv", index=False)
    PLAN.parent.mkdir(exist_ok=True)
    PLAN.write_text("# plan\n\n### R66 — the test's registration block (registered, read —)\nQuestion: …\n")
    return saved, A, ref


def _kw66(saved, A, ref, **over):
    return dict(draws=5, shift_min=5, cb_path="data/coinbase_1h_members.parquet", csv="cb_members_r66.csv", members_csv="members_f34.csv",
                r62_csv="cb_members_r62.csv", r62_members_csv="members.csv", r65=Path("output/ceiling_score_members"), slices=SLICES, btc_slices=("candles_5m",),
                mult={}, n_check=100, start=pd.Timestamp(START2, tz="UTC"), f12_start=pd.Timestamp(START, tz="UTC"), f12_end=END1, block_min_names=5, r60=saved,
                ref_csv=ref, f12_frame=A, reads=READS, plan=PLAN) | over


def test_the_score_is_confirmed_on_f3_after_r65_is_reproduced_and_the_guard_rows_are_appended(tmp_path, monkeypatch):
    saved, A, ref = _r66_world(tmp_path, monkeypatch)
    assert not READS.exists()
    md = sx.run_r66(5.0, 2.0, "test", **_kw66(saved, A, ref))
    v = json.loads(Path("output/ceiling_score_members_f34/validity.json").read_text())
    assert v["status"] == "PASS" and v["folds"] == ["F3", "F4"] and v["universe_file"]["n_kept"] == 11 and v["rows_equal_r62"]["status"] == "PASS"
    r = v["reproduction_r65"]
    assert r["status"] == "PASS" and r["rows_compared"] == r["rows_saved"] == 60 and r["max_abs_diff"]["ic"] == 0.0 and r["max_abs_diff"]["t"] == 0.0
    assert v["r50_reproduction"]["status"] == "PASS" and v["r50_reproduction"]["rows"] == 6
    assert v["guard"]["status"] == "PASS" and v["guard"]["folds"] == ["F3", "F4"]
    led = pd.read_csv(READS)
    assert list(led["registration"]) == ["R66", "R66"] and list(led["fold"]) == ["F3", "F4"] and set(led["strategy"]) == {"score_f34"}
    p = json.loads(led["params"].iloc[0])
    assert p["feature"] == SCORE and p["sign"] == 1 and p["list_md5"] == v["universe_file"]["md5"] and p["members_md5"] == v["members_file"]["md5"]
    fc = v["folds_check"]
    assert fc["status"] == "PASS" and fc["bars_outside_folds"] == 0 and fc["first"] >= "2024-09-03" and fc["whole_days"] > 50
    assert v["known_at"]["status"] == "PASS" and v["known_at"]["cells_read_too_early"] == 0
    assert v["hour_check"]["status"] == "PASS" and v["hour_check"]["bars_hour_after_t"] == 0
    assert v["recompute"]["status"] == "PASS" and v["recompute"]["recomputed"] == 100 and v["recompute"]["max_abs_diff_score"] < 1e-9
    k = v["construction"]
    assert k["status"] == "PASS" and k["other_bars_under_one"] == 0 and k["fall_cells_mismatching_the_inputs"] == 0 and 0.3 < k["fall_share"] < 0.7
    assert v["membership"]["values_off_membership"] == 0 and v["coverage"]["status"] == "PASS" and v["coverage"]["blocks_scored"] == 2
    assert np.isfinite(v["rho"]["rho_mean"]) and "score3" not in v
    rows = pd.read_parquet("output/ceiling_score_members_f34/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    d = g.loc[SCORE, "relative", "1d"]
    assert d["ic"] > 0.2 and d["ic_F3"] > 0.2 and np.isnan(d["ic_F4"]) and not d["folds_same_sign"]        # F4 has no bars in the world
    assert d["p_family"] == 1 / 6 and d["verdict"] == "NOT CONFIRMED — NOT DETECTABLE" and d["bar_maker_twelve"] == cx.BAR_TWELVE
    assert g.loc[SCORE, "relative", "4h"]["verdict"].endswith("(reported, not gated)")
    assert g.loc[BXF, "relative", "1h"]["ic"] > 0.1                                       # the give-back after a fall, the sign made positive (nine weeks of F3)
    assert g.loc[SCF, "relative", "1h"]["ic"] > g.loc[SCO, "relative", "1h"]["ic"]         # the fall half carries the hour
    assert g.loc[SCORE, "relative", "1h"]["ic"] > g.loc[DEV, "relative", "1h"]["ic"]       # the score beats the Coinbase input alone at the hour
    assert g.loc[DEV, "relative", "1d"]["ic"] > 0.2 and "first read on F3+F4" in g.loc[DEV, "relative", "1d"]["verdict"]
    for f_ in (DEV, BXF, SCF, SCO):
        assert np.isnan(g.loc[f_, "relative", "1d"]["p_family"]) and "described" in g.loc[f_, "relative", "1d"]["verdict"], f_
    B = pd.read_parquet("output/ceiling_score_members_f34/blocks.parquet")
    assert len(B) == 2 and list(B["covered"]) == [10, 11]
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R66's gate" in md and "F3+F4 (embargoed)" in md
    assert Path("output/ceiling_score_members_f34/validity_r65.csv").exists() and Path("output/ceiling_score_members_f34/rho.parquet").exists()
    assert sx.VERDICT_R66["CLEARS"] == "CONFIRMED" and sx.VERDICT_R66["CLOSED"].startswith("NOT CONFIRMED")
    # once: the second invocation is refused by the guard before any F3+F4 bar — the ledger unchanged, the read void
    with pytest.raises(SystemExit) as e:
        sx.run_r66(5.0, 2.0, "test", **_kw66(saved, A, ref))
    v2 = json.loads(Path("output/ceiling_score_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v2["status"] == "FAIL" and v2["guard"]["status"] == "FAIL" and "folds_check" not in v2 and "known_at" not in v2
    assert len(pd.read_csv(READS)) == 2 and "VOID" in Path("output/ceiling_score_members_f34.md").read_text()
    # the fold-parameterised frame on F3: the hourly bar used is at or before t; an hour after t fails
    L = sx.r66_list("cb_members_r66.csv")
    fr = sx.frame_folds(L, ("F3", "F4"), pd.Timestamp(START2, tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC"), "members_f34.csv",
                        "data/coinbase_1h_members.parquet", SLICES, {})
    assert fr["s"].sum() == v["scored_bars"] and fr["folds"] == ["F3", "F4"]
    bxf = sx.bx_frames(fr["D"], fr["idx"], fr["cols"], sx.btc_close(fr["idx"]))
    SF = sx.score_frames(fr["F"][DEV], bxf["bx5"], bxf["fall"])
    assert sx.hour_check(bxf["hour_used"], fr["idx"], fr["s"], SF[SCORE])["status"] == "PASS"
    assert sx.hour_check(bxf["hour_used"] + pd.Timedelta("1h"), fr["idx"], fr["s"], SF[SCORE])["status"] == "FAIL"


def test_a_mismatching_r65_screen_r50_reference_or_list_voids_before_the_guard(tmp_path, monkeypatch):
    saved, A, ref = _r66_world(tmp_path, monkeypatch)
    sc = pd.read_parquet("output/ceiling_score_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_score_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r66(5.0, 2.0, "test", **_kw66(saved, A, ref))
    v = json.loads(Path("output/ceiling_score_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["reproduction_r65"]["status"] == "FAIL" and "r50_reproduction" not in v and "guard" not in v
    assert not READS.exists() and not Path("output/ceiling_score_members_f34/screen.parquet").exists()
    sc.to_parquet("output/ceiling_score_members/screen.parquet", index=False)
    r = pd.read_csv(ref)
    r.assign(ic=r["ic"] + 1e-3).to_csv(ref, index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r66(5.0, 2.0, "test", **_kw66(saved, A, ref))
    v = json.loads(Path("output/ceiling_score_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction_r65"]["status"] == "PASS" and v["r50_reproduction"]["status"] == "FAIL" and "guard" not in v
    assert not READS.exists()
    r.to_csv(ref, index=False)
    lst = pd.read_csv("cb_members_r66.csv")
    lst.loc[lst["symbol"] == "M03USDT", "sd_adj_bps"] = 11.0                              # a row that is not R62's row for the name
    lst.to_csv("cb_members_r66.csv", index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r66(5.0, 2.0, "test", **_kw66(saved, A, ref))
    v = json.loads(Path("output/ceiling_score_members_f34/validity.json").read_text())
    assert e.value.code == 2 and v["rows_equal_r62"]["status"] == "FAIL" and v["rows_equal_r62"]["rows_off_r62"] == ["M03USDT"] and "reproduction_r65" not in v
    assert not READS.exists()
