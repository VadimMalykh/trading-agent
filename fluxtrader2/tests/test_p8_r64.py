"""R64 unit tests for the Korean source path of the breadth screen (`cb_ext.run_r64`) on made-up bars, no network: R62's saved screen on
the planted Coinbase members is reproduced FIRST through the new source path (a saved screen that does not match voids the run before any
Korean value is touched); the Korean frame is the BTC-relative premium (BTC's own rows divided out) masked to the kept names and to
membership; a planted CONTINUATION on Bithumb's premium comes back in `krprem_dev` with the registered POSITIVE sign on the member cells,
with the adjusted premium's row, Upbit's row, the volume share and the OVERLAP rows beside — the Korean deviation orthogonalised to R62's
Coinbase deviation on the same cells has zero correlation with it by construction; a block short of names voids at coverage."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, krw
from ft2.cb_ext import CB_SAME, KADJ, KCHG, KDEV, KLVL, KR_ORTH, KR_SAME, KTHIN, KTIGHT, KVOL, UPDEV
from tests.test_p8_cb_ext import PAIRS, START, _world
from tests.test_p8_r62 import KEPT, MEM, _kw, _members_world, _r60_saved

SLICES = ("candles_5m_archive", "candles_5m")


def _krw_world(fast: float = 0.8, seed: int = 5, venue: str = "bithumb", shared: float = 0.5):
    """Bithumb's hourly KRW bars for the members, BTC and KRW-USDT from the planted Binance closes: the member's premium = 3 + fast × the
    sign of its next-day relative return + `shared` × the Coinbase plant's own noise-free part is NOT reused — an independent noise; BTC's
    premium 2 + noise (divided out of the BTC-relative quantity); THIN with 150 bps of noise. The list at the BTC-relative sd cut."""
    rng = np.random.default_rng(seed)
    arch = pd.read_parquet("data/candles_5m_archive.parquet")
    arch["t"] = pd.DatetimeIndex(arch["open_time"]).tz_convert("UTC") + ceiling.BAR
    C = arch.pivot(index="t", columns="symbol", values="close")
    hrs = C.index[C.index.minute == 0]
    L = np.log(C[MEM].to_numpy())
    fwd = np.roll(L, -288, axis=0) - L
    fwd[-288:] = 0.0
    rel = fwd - fwd.mean(axis=1, keepdims=True)
    hi = np.flatnonzero(C.index.minute == 0)
    fx = 1400.0 + np.cumsum(rng.normal(0, 0.5, len(hrs)))
    btc = pd.read_parquet("data/candles_5m.parquet")
    btc = btc[btc["symbol"] == "BTCUSDT"].set_index(pd.DatetimeIndex(btc.loc[btc["symbol"] == "BTCUSDT", "open_time"]).tz_convert("UTC") + ceiling.BAR)["close"].reindex(hrs)
    p_btc = 2.0 + rng.normal(0, 0.2, len(hrs))
    rows, sd = [], {}
    def _rows(market, sym, px_usdt, p):
        px = px_usdt * fx * (1 + p / 1e4)
        return pd.DataFrame({"venue": venue, "market": market, "symbol": sym, "ts": hrs - krw.HOUR, "ts_known": hrs, "open": px, "high": px, "low": px, "close": px,
                             "volume_krw": 2e8 * (1 + 0.3 * np.sin(np.arange(len(hrs)) / 5)), "volume": 1.0, "last_tick": hrs - pd.Timedelta(minutes=10)})
    for i, sym in enumerate(MEM):
        noise = 150.0 if sym == "THINUSDT" else 0.3
        p = 3.0 + fast * np.sign(rel[hi, i]) + rng.normal(0, noise, len(hrs))
        rows.append(_rows(f"KRW-{sym[:-4]}", sym, C[sym].to_numpy()[hi], p))
        sd[sym] = float(np.std(p - p_btc))
    rows.append(_rows("KRW-BTC", "BTCUSDT", btc.to_numpy(), p_btc))
    rows.append(pd.DataFrame({"venue": venue, "market": krw.CONTROL, "symbol": None, "ts": hrs - krw.HOUR, "ts_known": hrs, "open": fx, "high": fx, "low": fx, "close": fx,
                              "volume_krw": 1e9, "volume": 1e9 / fx, "last_tick": hrs - pd.Timedelta(minutes=10)}))
    pd.concat(rows, ignore_index=True).to_parquet(f"data/krw_1h_{venue}.parquet", index=False)
    lst = pd.DataFrame({"symbol": MEM + ["NOPEUSDT"], "sd_btc_bps": [sd[m] for m in MEM] + [np.nan], "hours": len(hrs), "mean_btc_bps": 1.0})
    lst["r64"] = (lst["sd_btc_bps"] <= cx.R64_SD_CUT).fillna(False)
    lst.to_csv("krw_members_r64.csv", index=False)


def _kw64(saved, **over):
    return dict(draws=5, shift_min=5, path="data/krw_1h_bithumb.parquet", up_path="data/krw_1h_upbit.parquet", cb_path="data/coinbase_1h_members.parquet",
                r62=Path("output/ceiling_coinbase_members"), csv="krw_members_r64.csv", cb_csv="cb_members_r62.csv", members_csv="members.csv", slices=SLICES, mult={},
                n_check=100, start=pd.Timestamp(START, tz="UTC"), block_min_names=5, r60=saved) | over


def _r62_saved(tmp_path):
    """R62's run on the planted Coinbase members — its saved screen is R64's validity (1)."""
    _world(tmp_path)
    _members_world(tmp_path)
    saved, _ = _r60_saved()
    cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, slices=SLICES))
    return saved


def test_r62s_saved_screen_is_reproduced_first_and_a_mismatch_or_a_short_block_voids_the_run(tmp_path):
    saved = _r62_saved(tmp_path)
    _krw_world()
    L = cx.r64_list("krw_members_r64.csv")
    assert L["kept"] == KEPT and L["thin"] == ["THINUSDT"] and L["consistent"] and L["n_rows"] == 13
    sc = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        cx.run_r64(5.0, 2.0, "test", **_kw64(saved))
    v = json.loads(Path("output/ceiling_krw_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["reproduction"]["status"] == "FAIL" and v["reproduction"]["max_abs_diff"]["t"] > 1e-6 and "known_at" not in v
    assert not Path("output/ceiling_krw_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_krw_members.md").read_text()
    sc.to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        cx.run_r64(5.0, 2.0, "test", **_kw64(saved, block_min_names=11))
    v = json.loads(Path("output/ceiling_krw_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["known_at"]["status"] == "PASS" and v["membership"]["status"] == "PASS"
    assert v["coverage"]["status"] == "FAIL" and v["coverage"]["blocks_under_minimum"] == ["2023-05-03"] and v["overlap"]["status"] == "PASS"
    assert not Path("output/ceiling_krw_members/screen.parquet").exists()


def test_a_planted_continuation_on_bithumb_is_found_with_the_overlap_and_the_rows_beside(tmp_path):
    saved = _r62_saved(tmp_path)
    _krw_world()
    _krw_world(seed=9, venue="upbit")                                       # Upbit's parquet: the same plant, another noise
    md = cx.run_r64(5.0, 2.0, "test", **_kw64(saved))
    v = json.loads(Path("output/ceiling_krw_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == v["reproduction"]["rows_r62"] > 0 and v["reproduction"]["cb_list"]["n_kept"] == 11
    assert v["known_at"]["recomputed"] == 100 and v["known_at"]["cells_read_too_early"] == 0 and v["known_at"]["max_abs_diff"] < 1e-9
    assert v["membership"]["values_off_membership"] == 0 and v["membership"]["values_before_the_mask"] > v["membership"]["values_on"]
    assert v["coverage"]["blocks_scored"] == 2 and v["coverage"]["covered_min"] == 10 and v["universe_file"]["n_kept"] == 11 and v["gate"]["bar_status"] == "PASS"
    ov = v["overlap"]
    assert ov["status"] == "PASS" and ov["names"] == 11 and ov["cells"] > 1000 and np.isfinite(ov["beta"]) and ov["corr_before"] > 0.3 and abs(ov["corr_after"]) < 1e-6
    assert v["upbit"]["n_kept"] == 11 and v["upbit"]["n_series"] == 12
    rows = pd.read_parquet("output/ceiling_krw_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    d = g.loc[KDEV, "relative", "1d"]
    assert d["ic"] > 0.3 and d["t"] > 4 and d["ic_F1"] > 0.3 and d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE" and d["bar_maker_twelve"] == cx.BAR_TWELVE
    assert g.loc[KDEV, "relative", "4h"]["verdict"].endswith("(reported, not gated)")
    for f_, word in ((KLVL, "the level"), (KCHG, "24-h change"), (KTIGHT, "sd ≤ 30"), (KTHIN, "sd > 48, 1 names"), (KADJ, "ADJUSTED"), (UPDEV, "Upbit"), (KVOL, "AX2"),
                     (CB_SAME, "Coinbase deviation on the"), (KR_SAME, "same cells"), (KR_ORTH, "taken out")):
        r = g.loc[f_, "relative", "1d"]
        assert word in r["verdict"] and np.isnan(r["p_family"]), f_
    assert g.loc[KADJ, "relative", "1d"]["ic"] > 0.3 and g.loc[UPDEV, "relative", "1d"]["ic"] > 0.3 and g.loc[KTIGHT, "relative", "1d"]["ic"] > 0.3
    assert g.loc[CB_SAME, "relative", "1d"]["ic"] > 0.3 and g.loc[KR_SAME, "relative", "1d"]["ic"] > 0.3
    assert g.loc[KR_ORTH, "relative", "1d"]["ic"] < g.loc[KR_SAME, "relative", "1d"]["ic"]            # the shared plant taken out, the orthogonal part carries less
    assert abs(g.loc[KVOL, "relative", "1d"]["ic"]) < 0.2 and np.isnan(g.loc[KTHIN, "relative", "1d"]["ic"])
    O = pd.read_parquet("output/ceiling_krw_members/overlap.parquet")
    assert len(O) == 1 and O["cells"].iloc[0] == ov["cells"]
    B = pd.read_parquet("output/ceiling_krw_members/blocks.parquet")
    assert len(B) == 2 and list(B["covered"]) == [10, 11] and (B["ic"] > 0.2).all()
    names = pd.read_parquet("output/ceiling_krw_members/names.parquet").set_index("symbol")
    assert "THINUSDT" not in names.index and abs(names.loc["M01USDT", "lvl_mean_bps"] - 1.0) < 0.5           # the BTC-relative level ≈ 3 − 2
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R64's gate" in md and "## The overlap" in md
    # R62's own outputs are untouched by the run
    assert pd.read_parquet("output/ceiling_coinbase_members/screen.parquet").shape[0] > 0
