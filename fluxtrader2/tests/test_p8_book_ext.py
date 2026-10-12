"""R33 unit tests for the demeaned-imbalance screen (`ft2/book_ext.py`) on made-up bars and a made-up archive book: raw = lvl30 + dm
exactly, the trailing month appears only once MIN_MONTH bars of book exist, nothing after a bar changes a feature before it; a book
whose FAST part is planted to predict the next day comes back in `depth_imb_1_dm` with the registered sign and in neither the slow
part nor the shuffled or shifted nulls; the shift null keeps the time of day; and `run` writes validity first — a saved P2 screen
that does not match voids the run (exit 2) before any row of the registered feature exists, a matching one lets it through."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import book_ext as bx, ceiling
from ft2.book_ext import DM, LVL, RAW

PAIRS = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT"]
DAYS, START = 80, "2023-03-25"                     # the book from late March: the trailing month exists before F1's first scored bar


def _world(tmp_path, fast: float = 0.3, seed: int = 11):
    """Six random-walk pairs. The ±1 % book's imbalance at the bar closing at t = a SLOW per-pair level (a 20-day sine plus an offset,
    predicting nothing) + `fast` × −sign(the pair's next-day return) + noise — the fast part is planted to predict a FALL when
    bid-heavy, P2's sign. Ten 30 s samples per 5m bar, all strictly before the bar's close."""
    os.chdir(tmp_path)
    for d in ("data/depth", "output"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(START, tz="UTC"), periods=DAYS * 288, freq="5min")
    c5, cost = [], []
    for i, sym in enumerate(PAIRS):
        lr = np.cumsum(rng.normal(0, 6.0, len(t5))) / 1e4
        px = 100 * (i + 1) * np.exp(lr)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - ceiling.BAR, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fwd = np.roll(lr, -288) - lr
        fwd[-288:] = 0.0
        slow = 0.25 * np.sin(2 * np.pi * np.arange(len(t5)) / (20 * 288) + i) + 0.1 * (i - 2.5)
        imb = np.clip(slow - fast * np.sign(fwd) + rng.normal(0, 0.05, len(t5)), -0.95, 0.95)
        ts = pd.DatetimeIndex(((t5 - ceiling.BAR).tz_convert(None).to_numpy()[:, None] + pd.to_timedelta(np.arange(10) * 30, unit="s").to_numpy()[None, :]).ravel(), tz="UTC")
        im = np.repeat(imb, 10)
        pd.DataFrame({"symbol": sym, "ts": ts, "usd_m1": 1e6 * (1 + im), "usd_p1": 1e6 * (1 - im), "usd_m5": 5e6, "usd_p5": 5e6}).to_parquet(f"data/depth/{sym}.parquet", index=False)
        dd = pd.date_range(t5[0].floor("D"), periods=DAYS + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{ceiling.NOTIONAL}": 0.5, f"maker_adv_{ceiling.MAKER_H}": -1.5}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def _frame(tmp_path, **kw):
    _world(tmp_path, **kw)
    P = ceiling.panel(PAIRS)
    D = ceiling.derive(P)
    F = bx.features_depth(D["lr"].index, list(D["lr"].columns), ceiling.END)
    return P, D, F


def test_decomposition_coverage_and_the_past_only(tmp_path):
    _, D, F = _frame(tmp_path)
    both = F[LVL].notna() & F[DM].notna()
    assert both.to_numpy().sum() > 40 * 288 * 6
    assert float((F[RAW] - F[LVL] - F[DM]).abs().where(both).max().max()) < 1e-12
    first = F[LVL]["AAAUSDT"].first_valid_index()
    assert F[RAW]["AAAUSDT"].notna().loc[:first].sum() in (bx.MIN_MONTH, bx.MIN_MONTH + 1)        # the month exists once MIN_MONTH bars do
    v = bx.decomposition(F, D["scored"])
    assert v["status"] == "PASS" and v["coverage"][DM] > 0.95
    # nothing after a bar changes a feature before it
    cut = F[RAW].index[len(F[RAW]) // 2]
    for sym in PAIRS:
        x = pd.read_parquet(f"data/depth/{sym}.parquet")
        late = x["ts"] >= cut
        x.loc[late, ["usd_m1", "usd_p1"]] = x.loc[late, ["usd_p1", "usd_m1"]].to_numpy()                # the book flips from the cut on
        x.to_parquet(f"data/depth/{sym}.parquet", index=False)
    F1 = bx.features_depth(D["lr"].index, list(D["lr"].columns), ceiling.END)
    for k in (RAW, LVL, DM):
        pd.testing.assert_frame_equal(F[k][F[k].index < cut], F1[k][F1[k].index < cut], obj=k)
        assert not F[k][F[k].index > cut + pd.Timedelta(days=1)].equals(F1[k][F1[k].index > cut + pd.Timedelta(days=1)])


def test_a_planted_fast_part_is_found_with_its_sign_and_the_slow_part_is_not(tmp_path):
    _, D, F = _frame(tmp_path)
    s = D["scored"]
    sc, daily = ceiling.ic_screen(D, {k: F[k] for k in (LVL, DM)}, set())
    g = sc.set_index(["bet", "horizon", "feature"])
    dm, lvl = g.loc["directional", "1d", DM], g.loc["directional", "1d", LVL]
    assert dm["ic"] < -0.3 and dm["t"] < -4                                                      # the planted fall after a bid-heavy book
    assert abs(lvl["t"]) < 2.5                                                                   # the slow part predicts nothing
    fi = bx.fold_ics(daily, ("F1",))
    assert fi.set_index(["bet", "horizon", "feature"]).loc[("directional", "1d", DM), "ic_F1"] < -0.3
    assert bx.verdict(dm["ic"], dm["ic_mde"] / ceiling.MDE_K, 0.01, True, 0.011) == "CLEARS"
    assert bx.verdict(-dm["ic"], dm["ic_mde"] / ceiling.MDE_K, 0.01, True, 0.011) == "CLEARS WITH THE OPPOSITE SIGN"
    assert bx.verdict(0.001, 0.002, 0.5, True, 0.011) == "CLOSED" and bx.verdict(0.02, 0.01, 0.3, True, 0.011) == "NOT DETECTABLE"
    # both nulls break the link: the planted |t| beats every draw's largest |t| over the three horizons
    Zs = {h: D["z"][h][s].clip(-ceiling.Z_CLIP, ceiling.Z_CLIP).to_numpy() for h in bx.HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in bx.HZ}
    shuf = ceiling._null_feature(DM, F[DM][s], Zs, Zr, 20, 0)
    shift = bx.shift_feature(DM, F[DM], D, s, 20, 0, shift_min=5)
    t_real = {h: g.loc["directional", h, DM]["t"] for h in bx.HZ}
    for null in (shuf, shift):
        pf, ps, bar = bx.family_p(null, "directional", DM, t_real)
        assert pf["1d"] == ps["1d"] == 1 / 21 and bar["bar_t_p95"] < 4 and bar["draws"] == 20
        real = null[(null["draw"] == 0) & (null["bet"] == "directional") & (null["horizon"] == "1d")]["t"].iloc[0]
        assert abs(real - t_real["1d"]) < 1e-9                                                   # draw 0 is the real statistic
    assert (shift["shift_days"][shift["draw"] > 0] >= 5).all() and (shift["shift_days"][shift["draw"] == 0] == 0).all()


def test_shift_null_keeps_the_time_of_day_and_breaks_the_link():
    """A label that is +1 on the 00:00 bar of every day and 0 elsewhere, rolled by whole days, is unchanged — the shift keeps the
    time of day; a feature equal to that label reads IC 1 on draw 0 and, against a label that lives on another bar, nothing."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2023-05-01", periods=40 * 288 + 1, freq="5min", tz="UTC")
    cols = list("ABCDEF")
    at0 = ((idx.hour == 0) & (idx.minute == 0)).astype(float)
    z = pd.DataFrame(np.tile(at0[:, None], (1, 6)) + rng.normal(0, 1e-3, (len(idx), 6)), index=idx, columns=cols)
    D = {"z": {h: z for h in bx.HZ}, "zres": {h: z.sub(z.mean(axis=1), axis=0) for h in bx.HZ}}
    s = np.ones(len(idx), dtype=bool)
    s[-1] = False                                                                               # the last bar, a fold's end instant, is not scored
    f = pd.DataFrame(np.tile(at0[:, None], (1, 6)) + rng.normal(0, 1e-3, (len(idx), 6)), index=idx, columns=cols)
    out = bx.shift_feature("f", f, D, s, 10, 0, shift_min=5)
    d = out[(out["bet"] == "directional") & (out["horizon"] == "1d")].set_index("draw")["ic"]
    assert d.loc[0] > 0.09 and np.allclose(d.loc[1:], d.loc[0], atol=0.01)                        # the 00:00 label stays on the 00:00 bar after any whole-day shift (the per-pair rank of a one-bar-a-day feature caps the IC near 0.10)
    f8 = pd.DataFrame(np.tile(((idx.hour == 8) & (idx.minute == 0)).astype(float)[:, None], (1, 6)), index=idx, columns=cols)
    out8 = bx.shift_feature("f8", f8, D, s, 10, 0, shift_min=5)
    assert (out8[(out8["bet"] == "directional") & (out8["horizon"] == "1d")]["ic"].abs() < 0.05).all()
    with pytest.raises(AssertionError):
        bx.shift_feature("f", f, D, np.ones(len(idx), dtype=bool), 10, 0, shift_min=5)          # a scored bar beyond the whole days is refused


def test_run_writes_validity_first_and_voids_on_a_saved_screen_that_does_not_match(tmp_path, monkeypatch):
    P, D, F = _frame(tmp_path)
    s = D["scored"]
    saved = tmp_path / "output" / "ceiling"
    saved.mkdir(parents=True)
    sc_raw, _ = ceiling.ic_screen(D, {RAW: F[RAW]}, set())
    Zs = {h: D["z"][h][s].clip(-ceiling.Z_CLIP, ceiling.Z_CLIP).to_numpy() for h in bx.HZ}
    Zr = {h: D["zres"][h][s].to_numpy() for h in bx.HZ}
    null_raw = ceiling._null_feature(RAW, F[RAW][s], Zs, Zr, 5, 0)
    sc_raw.assign(t=sc_raw["t"] * 1.01).to_parquet(saved / "ic.parquet", index=False)              # P2's screen, "as saved", but not this run's
    null_raw.to_parquet(saved / "noise_ic.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        bx.run(5.0, 2.0, "test", PAIRS, draws=5, shift_min=5, saved=saved)
    assert e.value.code == 2
    v = json.loads(Path("output/ceiling_depth/validity.json").read_text())
    assert v["status"] == "FAIL" and v["reproduction"]["status"] == "FAIL" and v["decomposition"]["status"] == "PASS"
    assert not Path("output/ceiling_depth/screen.parquet").exists() and "VOID" in Path("output/ceiling_depth.md").read_text()
    sc_raw.to_parquet(saved / "ic.parquet", index=False)                                           # the saved screen matches
    md = bx.run(5.0, 2.0, "test", PAIRS, draws=5, shift_min=5, saved=saved)
    v = json.loads(Path("output/ceiling_depth/validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["rows_compared"] == 12 and v["reproduction"]["null_rows_compared"] == 5 * 3 * 2
    rows = pd.read_parquet("output/ceiling_depth/screen.parquet")
    g = rows[(rows["feature"] == DM) & (rows["bet"] == "directional") & (rows["horizon"] == "1d")].iloc[0]
    assert g["ic"] < -0.3 and g["p_family"] == 1 / 6 and g["verdict"] == "NOT DETECTABLE"       # five draws cannot certify anything
    assert g["bar_maker"] > 0 and g["bar_taker"] > g["bar_maker"]
    assert g["ic_F1"] < -0.3 and np.isnan(g["ic_F2"]) and bool(g["folds_same_sign"]) is False      # this world has no F2 days: no same-sign claim without both folds
    assert "## Validity — read first: **PASS**" in md and "## Verdict by R33's gate" in md
    for f_ in ("null_shuffle", "null_shift", "ic_daily", "move_vs_cost", "variance_share"):
        assert Path(f"output/ceiling_depth/{f_}.parquet").exists()
