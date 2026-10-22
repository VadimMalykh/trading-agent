"""R67 unit tests for the hold path (`hold_ext.run_r67`) on made-up bars, no network: R62's members' world with the Coinbase premium planted
to continue over THREE days (R62's plant on the 3-day relative return) — R62's saved screen (its own run on this world) is reproduced
through the extended path FIRST at P2's horizons; the long labels recomputed by hand match and none reaches past the panel's end; the
twelve's bar code reproduces R60's saved 1d bar; the 3d cell is found with the registered POSITIVE sign and above the 1d and 7d cells (the
plant is three days long); BG2's description is written with R61's decision line; a saved R62 screen that does not match voids the run
before any long label is checked; the verdict's threshold is the halved one; five draws certify nothing."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, coinbase as cb, hold_ext as hx
from ft2.cb_ext import DEV
from tests.test_p8_cb_ext import DAYS, LIQ, PAIRS, START, _world
from tests.test_p8_r62 import BLOCKS, MEM, SD, _kw, _r60_saved

HOLD = 864                                           # the plant's horizon: three days
DAYS67 = 160                                         # the shift null at R67's admissible minimum (38 > 30 + 7 days) needs > 3 × 38 scored days


def _members_world_hold(tmp_path, monkeypatch, fast: float = 0.8, seed: int = 7, hold: int = HOLD, days: int = DAYS67):
    """R62's members' world (`test_p8_r62._members_world`) with the premium planted on the `hold`-bar relative return instead of the day's,
    over `days` days (the twelve's world lengthened the same way)."""
    import tests.test_p8_cb_ext as w
    monkeypatch.setattr(w, "DAYS", days)
    _world(tmp_path)
    DAYS = days
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    hrs, hi = t5[t5.minute == 0], np.flatnonzero(t5.minute == 0)
    lr, c5, cost = {}, [], []
    for i, sym in enumerate(MEM):
        lr[sym] = np.cumsum(rng.normal(0, 6.0, len(t5))) / 1e4
        px = 2.0 * (i + 1) * np.exp(lr[sym])
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 50.0}))
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 4.0, f"imp_{ceiling.NOTIONAL}": 2.0, f"maker_adv_{ceiling.MAKER_H}": np.nan}))
    pd.concat(c5).to_parquet("data/candles_5m_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily_wide.parquet", index=False)
    L = np.column_stack([lr[s] for s in MEM])
    fwd = np.roll(L, -hold, axis=0) - L
    fwd[-hold:] = 0.0
    rel = fwd - fwd.mean(axis=1, keepdims=True)
    usdt = 0.9995 + rng.normal(0, 1e-4, len(hrs))
    rows = []
    for i, sym in enumerate(MEM):
        noise = 150.0 if sym == "THINUSDT" else 0.3
        p = 3.0 + fast * np.sign(rel[hi, i]) + rng.normal(0, noise, len(hrs))
        px = 2.0 * (i + 1) * np.exp(lr[sym][hi]) * usdt * (1 + p / 1e4)
        vol = 0.1 * 12 * 50.0 * (1 + 0.5 * np.sin(np.arange(len(hrs)) / 7))
        rows.append(pd.DataFrame({"product": f"{cb.base(sym)}-USD", "symbol": sym, "ts": hrs - cb.HOUR, "ts_known": hrs, "open": px, "high": px, "low": px, "close": px, "volume": vol}))
    rows.append(pd.DataFrame({"product": cb.CONTROL, "symbol": None, "ts": hrs - cb.HOUR, "ts_known": hrs, "open": usdt, "high": usdt, "low": usdt, "close": usdt, "volume": 1.0}))
    pd.concat(rows, ignore_index=True).to_parquet("data/coinbase_1h_members.parquet", index=False)
    pd.DataFrame([{"block": b, "symbol": s} for b, syms in BLOCKS.items() for s in syms]).to_csv("members.csv", index=False)
    lst = pd.DataFrame({"symbol": MEM + ["NOPEUSDT"], "sd_adj_bps": [SD[m] for m in MEM] + [np.nan]})
    lst["r62"] = (lst["sd_adj_bps"] <= cx.R62_SD_CUT).fillna(False)
    lst.to_csv("cb_members_r62.csv", index=False)


def _r62_saved():
    """R62's run on this world — its saved screen is R67's validity (2); R60's saved bars rewritten with the twelve's computed values
    (the test's twelve are random walks, so the 1d bar is not 0.0159 — validity (4) compares the run's code with the saved file)."""
    saved, _ = _r60_saved()
    cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, slices=("candles_5m_archive",)))
    D = ceiling.derive(ceiling.panel(PAIRS))
    ct, cm = ceiling.bar_cost(D["lr"].index, list(D["lr"].columns), 5.0, 2.0)
    mv, _ = ceiling.move_vs_cost(D, ct, cm)
    mv.to_parquet(saved / "move_vs_cost.parquet", index=False)
    return saved


def _kw67(saved, **over):
    return dict(draws=5, shift_min=38, path="data/coinbase_1h_members.parquet", csv="cb_members_r62.csv", members_csv="members.csv", r62=Path("output/ceiling_coinbase_members"),
                r60=saved, slices=("candles_5m_archive",), mult={}, n_check=100, start=pd.Timestamp(START, tz="UTC"), block_min_names=5, gap=15) | over


def test_the_three_day_plant_is_found_at_3d_with_the_validity_and_the_description_beside(tmp_path, monkeypatch):
    _members_world_hold(tmp_path, monkeypatch)
    saved = _r62_saved()
    md = hx.run_r67(5.0, 2.0, "test", PAIRS, **_kw67(saved))
    v = json.loads(Path("output/ceiling_hold_members/validity.json").read_text())
    assert v["status"] == "PASS"
    assert v["reproduction_r62"]["status"] == "PASS" and v["reproduction_r62"]["rows_compared"] == v["reproduction_r62"]["rows_r62"] > 0
    assert v["reproduction_r62"]["max_abs_diff"]["ic"] == 0.0 and v["reproduction_r62"]["max_abs_diff"]["t"] == 0.0
    for h in ("3d", "7d"):
        lc = v["label_check"]["holds"][h]
        assert lc["status"] == "PASS" and lc["recomputed"] == 100 and lc["tail_all_nan"] and max(lc["max_abs_diff"].values()) < 1e-9
    assert v["label_check"]["panel_ends_in_time"]
    assert v["bars"]["status"] == "PASS" and abs(v["bars"]["bar_1d_this_run"] - v["bars"]["bar_1d_r60_saved"]) <= cx.BAR_TOL
    assert v["bars"]["maker"]["3d"] < v["bars"]["maker"]["1d"] and v["bars"]["maker"]["7d"] < v["bars"]["maker"]["3d"]          # the bar falls with the hold
    assert v["known_at"]["status"] == "PASS" and v["membership"]["status"] == "PASS" and v["coverage"]["status"] == "PASS"
    assert v["nulls"]["status"] == "PASS" and v["nulls"]["gap_needed"] == 14 and v["nulls"]["shift_min_needed_above"] == 37
    sc = pd.read_parquet("output/ceiling_hold_members/screen.parquet")
    rel = sc[(sc["bet"] == "relative") & (sc["feature"] == DEV)].set_index("horizon")
    assert set(rel.index) == set(hx.ALL_H)
    assert rel.loc["3d", "ic"] > 0 and rel.loc["3d", "ic"] > rel.loc["1d", "ic"] and rel.loc["3d", "ic"] > rel.loc["7d", "ic"]
    assert rel.loc["3d", "ic_F1"] > 0 and np.isnan(rel.loc["3d", "ic_F2"]) and not rel.loc["3d", "folds_same_sign"]       # the world spans F1 only
    assert rel.loc["3d", "verdict"] in ("CLEARS", "NOT DETECTABLE") and rel.loc["7d", "verdict"] in ("CLEARS", "NOT DETECTABLE", "CLOSED")
    assert np.isfinite(rel.loc["3d", "p_family"]) and rel.loc["3d", "p_family"] >= 1 / 6                                        # five draws certify nothing
    assert rel.loc["1d", "verdict"].startswith("reported")
    assert np.isnan(rel.loc["1d", "p_family"])
    sv = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    old = sv[(sv["bet"] == "relative") & (sv["feature"] == DEV) & (sv["horizon"] == "1d")].iloc[0]
    assert abs(rel.loc["1d", "ic"] - old["ic"]) == 0.0                                                                          # the 1d row is R62's
    assert rel.loc["3d", "bar_maker_twelve"] == pytest.approx(v["bars"]["maker"]["3d"])
    ns = pd.read_parquet("output/ceiling_hold_members/null_shuffle.parquet")
    assert set(ns["horizon"]) == {"3d", "7d"} and ns["draw"].max() == 5
    bg = json.loads(Path("output/ceiling_hold_members/bg2.json").read_text())
    for h in ("1d", "3d"):
        assert bg[h]["decision"] in ("A TAIL RULE IS WORTH ITS OWN REGISTRATION", "CLOSED IN MONEY ON THE MEMBERS")
        assert bg[h]["unit_daily"]["days"] > 0 and np.isfinite(bg[h]["unit_every_bar"]["gross"])
        dec = pd.read_parquet(f"output/ceiling_hold_members/bg2_deciles_{h}.parquet")
        assert len(dec) == 10 and dec["cells"].sum() > 0
        assert np.isfinite(dec["top_minus_bottom"].iloc[0])
        trig = pd.read_parquet(f"output/ceiling_hold_members/bg2_triggers_{h}.parquet")
        assert len(trig) == 8 and trig["named"].sum() == 2
    d3 = pd.read_parquet("output/ceiling_hold_members/bg2_deciles_3d.parquet")
    assert d3["top_minus_bottom"].iloc[0] > 0                                                                                    # the plant: the top decile outruns the bottom over three days
    assert "## BG2" in md and "Verdict by R67's gate" in md


def test_the_verdict_uses_the_halved_threshold_and_a_mismatching_r62_screen_voids_before_any_long_label(tmp_path, monkeypatch):
    assert hx.verdict_r67(0.012, 0.004, 0.03, True, 0.009) == "NOT DETECTABLE"             # p 0.03 would clear at R62's 0.05, not at 0.025
    assert hx.verdict_r67(0.012, 0.004, 0.02, True, 0.009) == "CLEARS"
    assert hx.verdict_r67(-0.012, 0.004, 0.02, True, 0.009) == "CLEARS WITH THE OPPOSITE SIGN"
    assert hx.verdict_r67(0.003, 0.002, 0.5, True, 0.009) == "CLOSED"
    assert hx.verdict_r67(0.012, 0.004, 0.03, True, 0.009, p_max=0.05) == "CLEARS"
    _members_world_hold(tmp_path, monkeypatch)
    saved = _r62_saved()
    p = Path("output/ceiling_coinbase_members/screen.parquet")
    sc = pd.read_parquet(p)
    sc.loc[(sc["feature"] == DEV) & (sc["horizon"] == "1d") & (sc["bet"] == "relative"), "ic"] += 0.01
    sc.to_parquet(p, index=False)
    with pytest.raises(SystemExit) as e:
        hx.run_r67(5.0, 2.0, "test", PAIRS, **_kw67(saved))
    assert e.value.code == 2
    v = json.loads(Path("output/ceiling_hold_members/validity.json").read_text())
    assert v["status"] == "FAIL" and v["reproduction_r62"]["status"] == "FAIL" and "label_check" not in v and "bars" not in v
    assert not Path("output/ceiling_hold_members/screen.parquet").exists()


def test_extend_appends_the_holds_in_derive_s_form_with_nan_past_the_end():
    idx = pd.date_range("2024-01-01", periods=3000, freq="5min", tz="UTC")
    rng = np.random.default_rng(3)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 6e-4, (3000, 6)), axis=0)), index=idx, columns=[f"P{i}" for i in range(6)])
    D = ceiling.derive({"close": close})
    D = hx.extend(D, {"3d": 864})
    f = D["fwd"]["3d"]
    assert f.iloc[-864:].isna().all().all() and f.iloc[:-864].notna().all().all()
    i, j = 2000, 2
    assert f.iat[i, j] == pytest.approx(np.log(close.iat[i + 864, j] / close.iat[i, j]) * 1e4, abs=1e-9)
    assert D["res"]["3d"].iat[i, j] == pytest.approx(f.iat[i, j] - f.iloc[i].mean(), abs=1e-9)
    assert D["z"]["3d"].iat[i, j] == pytest.approx(f.iat[i, j] / (D["sig"]["1w"].iat[i, j] * np.sqrt(864)), abs=1e-9)
