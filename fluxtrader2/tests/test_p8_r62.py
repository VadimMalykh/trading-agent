"""R62 unit tests for the members' path of the Coinbase-premium screen (`cb_ext.run_members`) on made-up bars, no network: the frozen
list is read and checked for self-consistency; the twelve's R60 frame is reproduced FIRST and a saved screen that does not match voids
the run before any member's premium is touched; the members' frame is masked to membership (a name has no value outside its blocks);
a block short of names fails coverage and voids; a planted CONTINUATION on the members' premium comes back in `cbprem_dev` with the
registered POSITIVE sign on the member cells only, with the tight / thin / volume-share rows described beside and the per-block table,
while five draws cannot certify anything; the twelve's parquet is unchanged by the run."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, coinbase as cb
from ft2.cb_ext import CHG, DEV, LVL, THIN, TIGHT, VOL
from tests.test_p8_cb_ext import DAYS, HOLE, LIQ, PAIRS, START, _world

MEM = [f"M{i:02d}USDT" for i in range(1, 11)] + ["LATEUSDT", "THINUSDT"]       # LATE a member of the second block only; THIN above the cut
KEPT = MEM[:-1]
BLOCKS = {"2023-05-03": [m for m in MEM if m != "LATEUSDT"], "2023-06-02": MEM}
SD = {m: 10.0 for m in MEM[:8]} | {"M09USDT": 40.0, "M10USDT": 40.0, "LATEUSDT": 20.0, "THINUSDT": 120.0}


def _members_world(tmp_path, fast: float = 0.8, seed: int = 7):
    """The members' bars in the ARCHIVE slice, their Coinbase parquet with the premium planted to CONTINUE (R62's sign: + fast × the
    sign of the name's next-day relative return) — THIN with 150 bps of noise — the member file, the frozen list, the cost proxy."""
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
    fwd = np.roll(L, -288, axis=0) - L
    fwd[-288:] = 0.0
    rel = fwd - fwd.mean(axis=1, keepdims=True)
    usdt = 0.9995 + rng.normal(0, 1e-4, len(hrs))
    rows = []
    for i, sym in enumerate(MEM):
        noise = 150.0 if sym == "THINUSDT" else 0.3
        p = 3.0 + fast * np.sign(rel[hi, i]) + rng.normal(0, noise, len(hrs))
        px = 2.0 * (i + 1) * np.exp(lr[sym][hi]) * usdt * (1 + p / 1e4)
        vol = 0.1 * 12 * 50.0 * (1 + 0.5 * np.sin(np.arange(len(hrs)) / 7))                   # a tenth of Binance's hour, wobbling
        rows.append(pd.DataFrame({"product": f"{cb.base(sym)}-USD", "symbol": sym, "ts": hrs - cb.HOUR, "ts_known": hrs, "open": px, "high": px, "low": px, "close": px, "volume": vol}))
    rows.append(pd.DataFrame({"product": cb.CONTROL, "symbol": None, "ts": hrs - cb.HOUR, "ts_known": hrs, "open": usdt, "high": usdt, "low": usdt, "close": usdt, "volume": 1.0}))
    pd.concat(rows, ignore_index=True).to_parquet("data/coinbase_1h_members.parquet", index=False)
    pd.DataFrame([{"block": b, "symbol": s} for b, syms in BLOCKS.items() for s in syms]).to_csv("members.csv", index=False)
    lst = pd.DataFrame({"symbol": MEM + ["NOPEUSDT"], "sd_adj_bps": [SD[m] for m in MEM] + [np.nan]})
    lst["r62"] = (lst["sd_adj_bps"] <= cx.R62_SD_CUT).fillna(False)
    lst.to_csv("cb_members_r62.csv", index=False)


def _r60_saved(draws: int = 5):
    """R60's outputs 'as saved' on the twelve's world, made by the same functions: screen.parquet, null_shuffle.parquet, move_vs_cost."""
    saved = Path("output/ceiling_coinbase")
    saved.mkdir(parents=True, exist_ok=True)
    D = ceiling.derive(ceiling.panel(PAIRS))
    s, idx, cols = D["scored"], D["lr"].index, list(D["lr"].columns)
    F = cx.restrict(cx.features(idx, cols, LIQ + ["ZECUSDT"], "data/coinbase_1h.parquet")[0], LIQ)
    sc, _ = ceiling.ic_screen(D, F, set())
    Zs = {h: D["z"][h][s].clip(-ceiling.Z_CLIP, ceiling.Z_CLIP).to_numpy() for h in cx.HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in cx.HZ}
    null = ceiling._null_feature(DEV, F[DEV][s], Zs, Zr, draws, 0)
    sc.to_parquet(saved / "screen.parquet", index=False)
    null.to_parquet(saved / "null_shuffle.parquet", index=False)
    pd.DataFrame({"bet": ["relative"], "horizon": ["1d"], "ic_needed_maker": [cx.BAR_TWELVE], "ic_needed_taker": [0.0274]}).to_parquet(saved / "move_vs_cost.parquet", index=False)
    return saved, sc


def _kw(saved, **over):
    return dict(draws=5, shift_min=5, path="data/coinbase_1h_members.parquet", twelve_path="data/coinbase_1h.parquet", r60=saved, csv="cb_members_r62.csv",
                members_csv="members.csv", slices=("candles_5m_archive",), mult={}, liquid=LIQ, n_check=100, start=pd.Timestamp(START, tz="UTC"), block_min_names=5) | over


def test_the_list_the_reproduction_and_the_coverage_each_void_the_run_before_any_member_ic(tmp_path):
    _world(tmp_path)
    _members_world(tmp_path)
    saved, sc = _r60_saved()
    L = cx.r62_list("cb_members_r62.csv")
    assert L["kept"] == KEPT and L["thin"] == ["THINUSDT"] and set(L["tight"]) == set(MEM[:8]) | {"LATEUSDT"} and L["consistent"] and L["n_rows"] == 13
    assert L["md5"] == hashlib.md5(Path("cb_members_r62.csv").read_bytes()).hexdigest()
    # an inconsistent list (a thin name marked kept) voids the run at validity (4), before the members' panel
    bad = pd.read_csv("cb_members_r62.csv")
    bad.loc[bad["symbol"] == "THINUSDT", "r62"] = True
    bad.to_csv("cb_members_bad.csv", index=False)
    with pytest.raises(SystemExit) as e:
        cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, csv="cb_members_bad.csv"))
    v = json.loads(Path("output/ceiling_coinbase_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["universe_file"]["status"] == "FAIL" and "known_at" not in v
    # a saved R60 screen that does not match this run's frame voids it at validity (1)
    sc.assign(t=sc["t"] * 1.01).to_parquet(saved / "screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved))
    v = json.loads(Path("output/ceiling_coinbase_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "FAIL" and v["reproduction"]["max_abs_diff"]["t"] > 1e-6 and "known_at" not in v
    assert not Path("output/ceiling_coinbase_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_coinbase_members.md").read_text()
    sc.to_parquet(saved / "screen.parquet", index=False)
    # a block short of kept names with ≥ 90 % cover voids at validity (3): the first block has 10 kept members, LATE is not among them
    with pytest.raises(SystemExit) as e:
        cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, block_min_names=11))
    v = json.loads(Path("output/ceiling_coinbase_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["known_at"]["status"] == "PASS" and v["membership"]["status"] == "PASS"
    assert v["coverage"]["status"] == "FAIL" and v["coverage"]["blocks_under_minimum"] == ["2023-05-03"] and v["coverage"]["covered_min"] == 10
    assert not Path("output/ceiling_coinbase_members/screen.parquet").exists()


def test_a_planted_continuation_on_the_members_is_found_on_their_member_cells_with_the_rows_beside(tmp_path):
    _world(tmp_path)
    _members_world(tmp_path)
    saved, _ = _r60_saved()
    before = hashlib.md5(Path("data/coinbase_1h.parquet").read_bytes()).hexdigest()
    md = cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved))
    assert hashlib.md5(Path("data/coinbase_1h.parquet").read_bytes()).hexdigest() == before
    v = json.loads(Path("output/ceiling_coinbase_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == 36 and v["reproduction"]["null_rows_compared"] == 5 * 3 * 2
    assert v["known_at"]["recomputed"] == 100 and v["known_at"]["cells_read_too_early"] == 0 and v["known_at"]["max_abs_diff"] < 1e-9
    assert v["membership"]["values_off_membership"] == 0 and v["membership"]["values_before_the_mask"] > v["membership"]["values_on"]   # LATE's first-block cells masked
    assert v["coverage"]["blocks_scored"] == 2 and v["coverage"]["covered_min"] == 10 and v["coverage"]["covered_max"] == 11
    assert v["universe_file"]["n_kept"] == 11 and v["gate"]["bar_status"] == "PASS" and v["names_in_panel"] == 12 and v["kept_in_panel"] == 11
    rows = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    d = g.loc[DEV, "relative", "1d"]
    assert d["ic"] > 0.3 and d["t"] > 4 and d["ic_F1"] > 0.3 and np.isnan(d["ic_F2"]) and bool(d["folds_same_sign"]) is False
    assert d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE" and d["bar_maker_twelve"] == cx.BAR_TWELVE and d["bar_taker_members"] > 0
    assert g.loc[DEV, "relative", "4h"]["verdict"].endswith("(reported, not gated)") and np.isnan(g.loc[DEV, "relative", "1h"]["p_fw_shift"])
    assert np.isfinite(g.loc[DEV, "relative", "1h"]["p_single_shift"]) and np.isnan(g.loc[DEV, "relative", "1h"]["bar_maker_twelve"])
    for f_, word in ((LVL, "the level"), (CHG, "24-h change"), (TIGHT, "sd ≤ 30, 9 names"), (THIN, "sd > 48, 1 names"), (VOL, "AX2")):
        r = g.loc[f_, "relative", "1d"]
        assert word in r["verdict"] and np.isnan(r["p_family"]), f_
    assert g.loc[TIGHT, "relative", "1d"]["ic"] > 0.3 and abs(g.loc[VOL, "relative", "1d"]["ic"]) < 0.2        # the tight subset carries the plant; the volume share is nothing
    assert np.isnan(g.loc[THIN, "relative", "1d"]["ic"])                                                       # one name alone: no cross-section
    B = pd.read_parquet("output/ceiling_coinbase_members/blocks.parquet")
    assert len(B) == 2 and list(B["covered"]) == [10, 11] and (B["ic"] > 0.2).all() and list(B["days"]) == [30, 10]
    names = pd.read_parquet("output/ceiling_coinbase_members/names.parquet").set_index("symbol")
    assert "THINUSDT" not in names.index and names.loc["M01USDT", "sd_audit_bps"] == 10.0 and abs(names.loc["M01USDT", "lvl_mean_bps"] - 3.0) < 0.5
    assert names.loc["LATEUSDT", "cells"] < names.loc["M01USDT", "cells"]                                     # a member of the second block only
    assert cx.verdict_r62(0.03, 0.005, 0.01, True) == "CLEARS" and cx.verdict_r62(-0.03, 0.005, 0.01, True) == "CLEARS WITH THE OPPOSITE SIGN"
    assert cx.verdict_r62(0.001, 0.002, 0.5, True) == "CLOSED" and cx.verdict_r62(0.02, 0.01, 0.3, True) == "NOT DETECTABLE"
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R62's gate" in md and "## By block" in md
    for f_ in ("null_shuffle", "null_shift", "ic_daily", "move_vs_cost", "names", "blocks"):
        assert Path(f"output/ceiling_coinbase_members/{f_}.parquet").exists()


def test_the_carry_is_per_feature_and_the_hand_recomputation_follows_it(tmp_path):
    """The day after BTC's five-hour hole the 24-h change has no lagged bar at 06:00 … 10:00 while the level is present: the frame carries
    the 05:00 change for two hours (06:05, 07:05) and nothing after (08:05 …); `recompute_cell` says the same, and `known_at` counts the
    carried cells (the void of R62's first run on the work VM, 2026-10-19: the hand rule had said NaN under a fresh level)."""
    _world(tmp_path)
    D = ceiling.derive(ceiling.panel(PAIRS))
    idx = D["lr"].index
    F, U, G = cx.features(idx, list(D["lr"].columns), LIQ, "data/coinbase_1h.parquet")
    g = G["BTCUSDT"].dropna()
    day_after = HOLE[0] + pd.Timedelta("1d")
    for off, carried in (("5min", True), ("1h5min", True), ("2h5min", False), ("4h5min", False)):
        t = day_after + pd.Timedelta(off)
        got = [F[k]["BTCUSDT"].loc[t] for k in (LVL, DEV, CHG)]
        exp = cx.recompute_cell(g, t)
        assert np.isfinite(got[0]) and np.isfinite(got[1]) and np.isfinite(got[2]) == carried, off
        for a, b in zip(got, exp[:3]):
            assert (np.isnan(a) and np.isnan(b)) or abs(a - b) < 1e-9, off
        assert exp[3] == float((t - cx.MARGIN).floor("h").value // 3_600_000_000_000)                     # the used hour is the level's own
    assert abs(F[CHG]["BTCUSDT"].loc[day_after + pd.Timedelta("5min")] - F[CHG]["BTCUSDT"].loc[day_after - pd.Timedelta("55min")]) < 1e-12   # the 05:00 change carried
    ka = cx.known_at(F, U, G, D["scored"], LIQ, n_check=200)
    assert ka["status"] == "PASS" and ka["cells_feature_carried_beyond_the_level"][CHG] == 2 * 12 and ka["cells_feature_carried_beyond_the_level"][DEV] == 0
