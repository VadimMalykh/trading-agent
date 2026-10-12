"""R34 unit tests for the screen's universe path (`ft2/book_ext.py`, `ft2 ceiling --family depth --universe new`): a breadth read
writes under its own paths and leaves R33's untouched; its validity is R33's rows reproduced on the twelve in the same run (a
changed saved screen voids it, exit 2, before any row of the new names exists); the gate's bar is R33's number at 1d while the new
names' own taker bar comes from the cost proxy and their maker bar is NaN (`ceiling.bar_cost` reads `cost_daily_wide.parquet` for
names the twelve's file lacks); `--universe new` resolves to the 32 names outside the twelve."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import book_ext as bx, ceiling
from ft2.book_ext import DM, LVL, RAW

TWELVE = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT"]
NEW = ["GGGUSDT", "HHHUSDT", "IIIUSDT", "JJJUSDT", "KKKUSDT", "LLLUSDT"]
DAYS, START = 80, "2023-03-25"


def _world(tmp_path, fast_new: float = 0.3, seed: int = 12):
    """Twelve-like names with a tape cost file; new names with the candle-proxy cost file only (no maker columns). Every name's book
    carries a slow level plus a fast part planted against its next-day return (`fast_new` for the new names, 0.3 for the twelve)."""
    os.chdir(tmp_path)
    for d in ("data/depth", "output"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    c5, cost, cost_wide = [], [], []
    for i, sym in enumerate([*TWELVE, *NEW]):
        lr = np.cumsum(rng.normal(0, 6.0, len(t5))) / 1e4
        px = 100 * (i + 1) * np.exp(lr)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fwd = np.roll(lr, -288) - lr
        fwd[-288:] = 0.0
        fast = 0.3 if sym in TWELVE else fast_new
        slow = 0.25 * np.sin(2 * np.pi * np.arange(len(t5)) / (20 * 288) + i) + 0.05 * (i - 5.5)
        imb = np.clip(slow - fast * np.sign(fwd) + rng.normal(0, 0.05, len(t5)), -0.95, 0.95)
        ts = pd.DatetimeIndex(((t5 - ceiling.BAR).tz_convert(None).to_numpy()[:, None] + pd.to_timedelta(np.arange(10) * 30, unit="s").to_numpy()[None, :]).ravel(), tz="UTC")
        im = np.repeat(imb, 10)
        pd.DataFrame({"symbol": sym, "ts": ts, "usd_m1": 1e6 * (1 + im), "usd_p1": 1e6 * (1 - im), "usd_m5": 5e6, "usd_p5": 5e6}).to_parquet(f"data/depth/{sym}.parquet", index=False)
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        if sym in TWELVE:
            cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{ceiling.NOTIONAL}": 0.5, f"maker_adv_{ceiling.MAKER_H}": -1.5}))
        else:
            cost_wide.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 3.0, f"imp_{ceiling.NOTIONAL}": 1.0, f"maker_adv_{ceiling.MAKER_H}": np.nan,
                                           f"maker_fill_{ceiling.MAKER_H}": np.nan, "spread_src": "proxy_wide"}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)
    pd.concat(cost_wide).to_parquet("data/cost_daily_wide.parquet", index=False)


def _save_r33(symbols=TWELVE):
    """R33's saved screen, as the run on the twelve would have written it (its rows without nulls suffice for the reproduction)."""
    _, D, F = bx.frame(symbols)
    sc, _ = ceiling.ic_screen(D, F, set())
    out = bx.out_paths(None)[1]
    out.mkdir(parents=True, exist_ok=True)
    sc.to_parquet(out / "screen.parquet", index=False)
    return sc


def test_bar_cost_takes_the_proxy_for_names_without_a_tape_and_has_no_maker_bar_for_them(tmp_path):
    _world(tmp_path)
    P = ceiling.panel([*TWELVE, *NEW])
    idx = P["close"].index
    ct, cm = ceiling.bar_cost(idx, [*TWELVE, *NEW], 5.0, 2.0)
    assert np.allclose(ct["AAAUSDT"].dropna(), 2 * 5.0 + 1.0 + 2 * 0.5) and np.allclose(cm["AAAUSDT"].dropna(), 2 * 2.0 + 3.0)
    assert np.allclose(ct["GGGUSDT"].dropna(), 2 * 5.0 + 3.0 + 2 * 1.0) and cm["GGGUSDT"].isna().all()           # the proxy: taker only
    assert ct["GGGUSDT"].notna().sum() > 0.9 * len(idx)


def test_universe_new_is_the_32_outside_the_twelve():
    from ft2.__main__ import PAIRS, _symbols
    from ft2.universe import NEW as NEW32, WIDE

    class A:
        universe, symbols = "new", None
    got = _symbols(A())
    assert got == list(NEW32) and len(got) == 32 and not set(got) & set(PAIRS) and set(got) < set(WIDE)
    assert bx.out_paths("new") == (Path("output/ceiling_depth_new.md"), Path("output/ceiling_depth_new")) and bx.out_paths(None) == (bx.OUT_MD, bx.OUT_DIR)


def test_a_breadth_read_reproduces_r33_first_and_voids_on_a_changed_saved_screen(tmp_path):
    _world(tmp_path)
    sc12 = _save_r33()
    saved = bx.out_paths(None)[1]
    sc12.assign(t=sc12["t"] * 1.01).to_parquet(saved / "screen.parquet", index=False)              # R33 "as saved", but not this frame's
    with pytest.raises(SystemExit) as e:
        bx.run(5.0, 2.0, "test", NEW, draws=5, shift_min=5, universe="new", twelve=TWELVE)
    assert e.value.code == 2
    v = json.loads(Path("output/ceiling_depth_new/validity.json").read_text())
    assert v["status"] == "FAIL" and v["reproduction"]["status"] == "FAIL" and v["registration"] == "R34" and v["universe"] == "new"
    assert not Path("output/ceiling_depth_new/screen.parquet").exists() and "VOID" in Path("output/ceiling_depth_new.md").read_text()
    assert not Path("output/ceiling_depth/validity.json").exists()                                   # R33's directory is not written to
    sc12.to_parquet(saved / "screen.parquet", index=False)                                           # the saved screen matches
    md = bx.run(5.0, 2.0, "test", NEW, draws=5, shift_min=5, universe="new", twelve=TWELVE)
    v = json.loads(Path("output/ceiling_depth_new/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == len(sc12) == 36 and v["decomposition"]["names_under_half"] == []
    assert set(v["decomposition"]["coverage_by_name"]) == set(NEW) and v["pairs"] == NEW
    rows = pd.read_parquet("output/ceiling_depth_new/screen.parquet")
    g = rows[(rows["feature"] == DM) & (rows["bet"] == "directional")].set_index("horizon")
    assert g.loc["1d", "bar_gate"] == bx.R33_BAR and np.isnan(g.loc["4h", "bar_gate"]) and np.isnan(g.loc["1d", "bar_maker"]) and g.loc["1d", "bar_taker"] > 0.01
    assert g.loc["1d", "ic"] < -0.3 and g.loc["1d", "p_family"] == 1 / 6 and g.loc["1d", "verdict"] == "NOT DETECTABLE"   # five draws certify nothing
    assert "R34" in md and "## Verdict by R34's gate" in md and f"the gate's bar {bx.R33_BAR:.4f}" in md
    assert set(rows[rows["feature"] == RAW]["verdict"]) == {"described (the raw imbalance)"}
    assert sorted(p.name for p in Path("output/ceiling_depth").iterdir()) == ["screen.parquet"]        # R33's outputs untouched
    for f_ in ("null_shuffle", "null_shift", "ic_daily", "move_vs_cost", "variance_share"):
        assert Path(f"output/ceiling_depth_new/{f_}.parquet").exists()


def test_the_verdict_can_clear_on_the_breadth_read_when_the_draws_allow(tmp_path):
    _world(tmp_path)
    _save_r33()
    bx.run(5.0, 2.0, "test", NEW, draws=20, shift_min=5, universe="new", twelve=TWELVE)
    rows = pd.read_parquet("output/ceiling_depth_new/screen.parquet")
    g = rows[(rows["feature"] == DM) & (rows["bet"] == "directional") & (rows["horizon"] == "1d")].iloc[0]
    # twenty draws put p_family at its floor, the sign and the size pass — but this world has no F2 days, so the folds cannot agree and the
    # gate holds at NOT DETECTABLE; with both folds the same numbers would clear
    assert g["p_family"] == 1 / 21 and g["ic"] < -0.3 and bool(g["folds_same_sign"]) is False and np.isnan(g["ic_F2"])
    assert g["verdict"] == "NOT DETECTABLE" and bx.verdict(g["ic"], g["ic_se"], g["p_family"], True, bx.R33_BAR) == "CLEARS"
    lvl = rows[(rows["feature"] == LVL) & (rows["bet"] == "directional") & (rows["horizon"] == "1d")].iloc[0]
    assert lvl["verdict"] == "described (the slow part)"
