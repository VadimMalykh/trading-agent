"""R65 unit tests for the score path (`score_ext.run_r65`) on made-up bars, no network: R62's saved screen is reproduced FIRST on the very
frame the score uses, then R50's reference rows through R63's mask path (R50's own `_refs` code builds the reference on a hand-built
frame) — a saved screen or a reference that does not match voids the run before any score is joined to a label; the members move with
BTC by their betas and give back part of a BTC FALL over the next hour (R63's plant) while their Coinbase premium is planted to CONTINUE
into the next day (R62's plant); the score recovers both with the registered POSITIVE sign — −bx_1h alone carries on the fall bars, the
score on the fall half carries more than on the other half, the score beats `cbprem_dev` alone at the hour, R62's input row is R62's
row exactly; the construction holds (Spearman 1 with `cbprem_dev` on the non-fall bars, a value exactly where both inputs have one on
the fall bars); the hand recomputation matches; bx shifted an hour into the future changes the score, and an hour used after t fails
the known-at check; score3 with the Korean rank is described beside; five draws certify nothing."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import audit, cb_ext as cx, ceiling, folds, score_ext as sx
from ft2 import backtest as bt
from ft2.cb_ext import DEV
from ft2.score_ext import BXF, S3, SCF, SCO, SCORE
from tests.test_p8_cb_ext import DAYS, PAIRS, START, _world
from tests.test_p8_r62 import BLOCKS, KEPT, MEM, SD, _kw, _r60_saved
from tests.test_p8_r64 import _krw_world

SLICES = ("candles_5m_archive", "candles_5m")
BETAS = np.linspace(0.3, 3.0, len(MEM))                     # wide: the rank of beta ÷ sigma must spread across the names
BTC = "BTCUSDT"


def _r65_world(tmp_path, fast: float = 0.8, give_back: float = 1.5, seed: int = 7, noise: float = 5.0):
    """The twelve's world (BTC a random walk in the collector's slice), then the members in the ARCHIVE slice: name i moves with BTC by
    beta_i and, in the hour after a BTC FALL, gives back `give_back` × beta_i × that fall over bars 2 … 12 of the hour (R63's plant;
    nothing after a rise); its Coinbase premium = 3 + `fast` × the sign of its next-day relative return (R62's plant); THIN noisy."""
    _world(tmp_path)
    rng = np.random.default_rng(seed)
    c = pd.read_parquet("data/candles_5m.parquet")
    b = c[c["symbol"] == BTC].sort_values("open_time")
    t5 = pd.DatetimeIndex(b["open_time"]).tz_convert("UTC") + ceiling.BAR
    b5 = np.concatenate([[0.0], np.diff(np.log(b["close"].to_numpy()))]) * 1e4
    n = len(t5)
    gid = (np.arange(n) + 11) // 12                                           # the hour a bar belongs to: closes :05 … :00
    bh = np.bincount(gid, weights=b5, minlength=int(gid.max()) + 1)          # BTC's hourly moves
    pos = (np.arange(n) + 11) % 12
    prev_fall = np.concatenate([[0.0], np.minimum(bh, 0.0)[:-1]])
    hrs, hi = t5[t5.minute == 0], np.flatnonzero(t5.minute == 0)
    lr, c5, cost = {}, [], []
    for i, sym in enumerate(MEM):
        gb = np.where(pos >= 1, -give_back * BETAS[i] * prev_fall[gid] / 11.0, 0.0)
        lr[sym] = np.cumsum(BETAS[i] * b5 + gb + rng.normal(0, noise, n)) / 1e4
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
        nz = 150.0 if sym == "THINUSDT" else 0.3
        p = 3.0 + fast * np.sign(rel[hi, i]) + rng.normal(0, nz, len(hrs))
        px = 2.0 * (i + 1) * np.exp(lr[sym][hi]) * usdt * (1 + p / 1e4)
        vol = 0.1 * 12 * 50.0 * (1 + 0.5 * np.sin(np.arange(len(hrs)) / 7))
        rows.append(pd.DataFrame({"product": f"{sym[:-4]}-USD", "symbol": sym, "ts": hrs - pd.Timedelta("1h"), "ts_known": hrs, "open": px, "high": px, "low": px, "close": px, "volume": vol}))
    rows.append(pd.DataFrame({"product": "USDT-USD", "symbol": None, "ts": hrs - pd.Timedelta("1h"), "ts_known": hrs, "open": usdt, "high": usdt, "low": usdt, "close": usdt, "volume": 1.0}))
    pd.concat(rows, ignore_index=True).to_parquet("data/coinbase_1h_members.parquet", index=False)
    pd.DataFrame([{"block": b_, "symbol": s} for b_, syms in BLOCKS.items() for s in syms]).to_csv("members.csv", index=False)
    lst = pd.DataFrame({"symbol": MEM + ["NOPEUSDT"], "sd_adj_bps": [SD[m] for m in MEM] + [np.nan]})
    lst["r62"] = (lst["sd_adj_bps"] <= cx.R62_SD_CUT).fillna(False)
    lst.to_csv("cb_members_r62.csv", index=False)


def _r62_saved():
    """R62's run on the planted members — its saved screen is R65's validity (1)."""
    saved, _ = _r60_saved()
    cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, slices=SLICES))
    return saved


def _r50_reference() -> tuple[dict, Path]:
    """R50's described rows by R50's own `_refs` on a hand-built stage-1 frame (the members' archive closes and BTC's) — the reference the
    mask path must reproduce; the frame handed to the run as validity (2)'s."""
    r50 = sx.script("r50_btchour")
    arch = pd.read_parquet("data/candles_5m_archive.parquet")
    arch["t"] = pd.DatetimeIndex(arch["open_time"]).tz_convert("UTC") + ceiling.BAR
    C = arch.pivot(index="t", columns="symbol", values="close")[MEM]
    c = pd.read_parquet("data/candles_5m.parquet")
    b = c[c["symbol"] == BTC]
    C[BTC] = pd.Series(b["close"].to_numpy(), index=pd.DatetimeIndex(b["open_time"]).tz_convert("UTC") + ceiling.BAR).reindex(C.index)
    M = bt.Market(close=C, high=C * 1.0005, low=C * 0.9995, dv=C * 0 + 10.0)
    t5 = pd.Series(M.index, index=M.index)
    scored = np.zeros(len(M.index), dtype=bool)
    for f in folds.EXPLORATION:
        scored |= folds.mask(t5, f).to_numpy()
    grid = M.index[scored & (M.index.minute == 0)]
    A = {"M": M, "names": MEM, "grid": grid, "cell": pd.DataFrame(True, index=grid, columns=MEM), "latency": 1}
    u = r50._universe("outside", A, r50.HOLDS, r50._btc(A, A))
    rows = pd.DataFrame(r50._refs(u, r50.HOLDS, audit._day(u["grid"]), None))
    p = Path("output/audit/r50_btchour/reference.csv")
    p.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(p, index=False)
    return A, p


def _kw65(saved, A, ref, **over):
    return dict(draws=5, shift_min=5, cb_path="data/coinbase_1h_members.parquet", r62=Path("output/ceiling_coinbase_members"), csv="cb_members_r62.csv",
                members_csv="members.csv", slices=SLICES, btc_slices=("candles_5m",), mult={}, n_check=100, start=pd.Timestamp(START, tz="UTC"), block_min_names=5,
                r60=saved, ref_csv=ref, f12_frame=A, kr_csv=None, kr_path=None) | over


def test_the_planted_give_back_and_continuation_are_found_on_the_score_with_the_construction_and_the_rows_beside(tmp_path):
    _r65_world(tmp_path)
    saved = _r62_saved()
    A, ref = _r50_reference()
    _krw_world()                                                              # R64's Korean parquet and list: score3 described beside
    md = sx.run_r65(5.0, 2.0, "test", **_kw65(saved, A, ref, kr_csv="krw_members_r64.csv", kr_path="data/krw_1h_bithumb.parquet"))
    v = json.loads(Path("output/ceiling_score_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["status"] == "PASS" and v["reproduction"]["rows_compared"] == v["reproduction"]["rows_r62"] > 0
    assert v["r50_reproduction"]["status"] == "PASS" and v["r50_reproduction"]["rows"] == 6 and v["r50_reproduction"]["cells_equal"]
    assert v["known_at"]["status"] == "PASS" and v["known_at"]["cells_read_too_early"] == 0
    assert v["hour_check"]["status"] == "PASS" and v["hour_check"]["bars_hour_after_t"] == 0 and v["hour_check"]["bars_without_an_hour"] == 0
    assert v["recompute"]["status"] == "PASS" and v["recompute"]["recomputed"] == 100 and v["recompute"]["max_abs_diff_score"] < 1e-9 and v["recompute"]["max_abs_diff_bx"] < 1e-6
    k = v["construction"]
    assert k["status"] == "PASS" and k["other_bars_under_one"] == 0 and k["fall_cells_mismatching_the_inputs"] == 0 and k["bars_fall"] > 0 and k["bars_other"] > 0
    assert 0.3 < k["fall_share"] < 0.7 and k["cells_fall"] + k["cells_other"] == k["cells_with_a_score"]
    assert v["membership"]["values_off_membership"] == 0 and v["coverage"]["blocks_scored"] == 2 and v["coverage"]["status"] == "PASS"
    assert v["universe_file"]["n_kept"] == 11 and len(v["members_file"]["md5"]) == 32 and v["gate"]["bar_status"] == "PASS"
    assert np.isfinite(v["rho"]["rho_mean"]) and v["rho"]["bars"] > 100 and v["score3"]["kr_list"]["n_kept"] == 11 and v["score3"]["cells"] > 1000
    rows = pd.read_parquet("output/ceiling_score_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    d = g.loc[SCORE, "relative", "1d"]
    assert d["ic"] > 0.2 and d["ic_F1"] > 0.2 and d["p_family"] == 1 / 6 and d["verdict"] == "NOT DETECTABLE" and d["bar_maker_twelve"] == cx.BAR_TWELVE
    assert g.loc[SCORE, "relative", "4h"]["verdict"].endswith("(reported, not gated)")
    assert g.loc[BXF, "relative", "1h"]["ic"] > 0.2                                       # the give-back after a fall, the sign made positive
    assert g.loc[SCF, "relative", "1h"]["ic"] > g.loc[SCO, "relative", "1h"]["ic"]         # the fall half carries the hour, the other half does not
    assert g.loc[SCORE, "relative", "1h"]["ic"] > g.loc[DEV, "relative", "1h"]["ic"]       # the score beats the Coinbase input alone at the hour
    assert g.loc[S3, "relative", "1d"]["ic"] > 0.2 and "Korean" in g.loc[S3, "relative", "1d"]["verdict"]
    for f_, word in ((DEV, "R62's row"), (BXF, "fall bars only"), (SCF, "fall bars"), (SCO, "other bars")):
        assert word in g.loc[f_, "relative", "1d"]["verdict"] and np.isnan(g.loc[f_, "relative", "1d"]["p_family"]), f_
    r62 = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet").set_index(["feature", "bet", "horizon"])
    assert abs(g.loc[DEV, "relative", "1d"]["ic"] - r62.loc[DEV, "relative", "1d"]["ic"]) == 0.0           # R62's input row is R62's row
    assert pd.read_parquet("output/ceiling_score_members/rho.parquet")["rho"].notna().sum() > 10
    B = pd.read_parquet("output/ceiling_score_members/blocks.parquet")
    assert len(B) == 2 and list(B["covered"]) == [10, 11]
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R65's gate" in md and "## The construction and ρ" in md
    # the carry is backward only: bx an hour into the future changes the score on the fall bars; an hour used after t fails the check
    L = cx.r62_list("cb_members_r62.csv")
    fr = cx.frames(L, "coinbase", "data/coinbase_1h_members.parquet", SLICES, {}, "members.csv", pd.Timestamp(START, tz="UTC"))
    bxf = sx.bx_frames(fr["D"], fr["idx"], fr["cols"], sx.btc_close(fr["idx"]))
    SF = sx.score_frames(fr["F"][DEV], bxf["bx5"], bxf["fall"])
    future = bxf["bx5"].shift(-12)
    SFf = sx.score_frames(fr["F"][DEV], future, bxf["fall"])
    s, fall = fr["s"], bxf["fall"]
    a, b_ = SF[SCORE][s & fall].to_numpy(), SFf[SCORE][s & fall].to_numpy()
    ok = np.isfinite(a) & np.isfinite(b_)
    assert ok.sum() > 1000 and np.nanmax(np.abs(a[ok] - b_[ok])) > 0.1
    assert np.allclose(SF[SCORE][s & ~fall].to_numpy(), SFf[SCORE][s & ~fall].to_numpy(), equal_nan=True)     # the other half knows nothing of bx
    assert sx.hour_check(bxf["hour_used"], fr["idx"], s, SF[SCORE])["status"] == "PASS"
    assert sx.hour_check(bxf["hour_used"] + pd.Timedelta("1h"), fr["idx"], s, SF[SCORE])["status"] == "FAIL"
    assert sx.hour_check(bxf["hour_used"] - pd.Timedelta("1h"), fr["idx"], s, SF[SCORE])["status"] == "FAIL"


def test_a_mismatching_r62_screen_or_r50_reference_voids_the_run_before_any_score(tmp_path):
    _r65_world(tmp_path)
    saved = _r62_saved()
    A, ref = _r50_reference()
    sc = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r65(5.0, 2.0, "test", **_kw65(saved, A, ref))
    v = json.loads(Path("output/ceiling_score_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["reproduction"]["status"] == "FAIL" and "r50_reproduction" not in v and "known_at" not in v
    assert not Path("output/ceiling_score_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_score_members.md").read_text()
    sc.to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    r = pd.read_csv(ref)
    r.assign(ic=r["ic"] + 1e-3).to_csv(ref, index=False)
    with pytest.raises(SystemExit) as e:
        sx.run_r65(5.0, 2.0, "test", **_kw65(saved, A, ref))
    v = json.loads(Path("output/ceiling_score_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["r50_reproduction"]["status"] == "FAIL" and v["r50_reproduction"]["max_abs_d_ic"] > 1e-6
    assert "known_at" not in v and "construction" not in v and not Path("output/ceiling_score_members/screen.parquet").exists()
