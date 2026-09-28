"""P8 — the screener (`ft2/screen.py`, `ft2/universe.py`, registration R18): the universe's members are chosen from the days
before the block alone; the transfer model is the training names' in-pair model and trades members only; the read finds a
planted screen."""
import json

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import forecast as fc
from ft2 import screen, universe

TRAIN = [f"T{i}USDT" for i in range(6)]
RIGHT = [f"A{i}USDT" for i in range(6)]            # behave as the training names do: the forecast is right on them
WRONG = [f"B{i}USDT" for i in range(6)]            # behave the opposite way: the forecast is wrong on them
OUTSIDE = "N0USDT"                                 # in the panel, never a member
HOLD, SD, PHI = 12, 5.0, 0.06
BLOCKS = ["2023-05-03", "2023-05-18", "2023-06-02"]


def _synth(days=75, start="2023-03-20", seed=3):
    """`tests/test_p5_forecast.py`'s market: a pair's next hour follows its last hour with sign φ — +PHI on the training and
    the RIGHT names, −PHI on the WRONG ones and the outsider."""
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    mkt = rng.normal(0, SD, len(t5))
    c5, fund, cost = [], [], []
    for i, sym in enumerate([*TRAIN, *RIGHT, *WRONG, OUTSIDE]):
        phi = PHI if sym in TRAIN + RIGHT else -PHI
        eps = rng.normal(0, SD, len(t5))
        r = eps.copy()
        for k in range(2, 14):
            r[k:] += phi * eps[:-k]
        px = 100 * (i + 1) * np.exp(np.cumsum(r + mkt) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def _members(path):
    """Every RIGHT and WRONG name a member of every block. `vol_pct` is the planted screen (its top third are RIGHT names, its
    bottom third WRONG ones); `age_days` and `liq_musd` cut across it; two names have no `play`."""
    rows = []
    for b in BLOCKS:
        for i, s in enumerate(RIGHT):
            rows.append({"block": b, "symbol": s, "liq_musd": 100 + i, "vol_pct": 8.0 - 0.1 * i, "play": np.nan if i == 0 else 1.0 + 0.1 * i, "age_days": 100 * (i + 1)})
        for i, s in enumerate(WRONG):
            rows.append({"block": b, "symbol": s, "liq_musd": 100.5 + i, "vol_pct": 2.0 - 0.1 * i, "play": np.nan if i == 0 else 1.05 + 0.1 * i, "age_days": 100 * (i + 1) + 50})
    pd.DataFrame(rows).to_csv(path, index=False)


def _daily(n_days=260, start="2023-01-01"):
    days = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n_days, freq="D")
    rng = np.random.default_rng(0)
    out = []
    for i, (sym, first, vol) in enumerate([("AAAUSDT", 0, 50e6), ("BBBUSDT", 0, 40e6), ("CCCUSDT", 0, 30e6), ("DDDUSDT", 0, 20e6), ("EEEUSDT", 0, 10e6),
                                           ("YOUNGUSDT", 200, 35e6), ("TRAINUSDT", 0, 90e6), ("GAPUSDT", 0, 80e6)]):
        d = days[first:]
        out.append(pd.DataFrame({"symbol": sym, "day": d, "quote_volume": vol * (1 + 0.01 * rng.normal(size=len(d))),
                                 "close": 10 * np.exp(np.cumsum(rng.normal(0, 0.01 * (i + 1), len(d))))}))
    d = pd.concat(out, ignore_index=True)
    return d[~((d["symbol"] == "GAPUSDT") & (d["day"] == days[235]))], days


def test_members_come_from_the_days_before_the_block_alone():
    d, days = _daily()
    a = days[240]
    m = universe.characteristics(d, [a], {"TRAINUSDT"}, k=4)
    assert list(m["symbol"]) == ["AAAUSDT", "BBBUSDT", "YOUNGUSDT", "CCCUSDT"]                 # by volume; the training name and the one with a missing day are out
    y = m.set_index("symbol").loc["YOUNGUSDT"]
    assert y["age_days"] == 40 and np.isnan(y["play"])                                         # 40 daily bars: no 180-day base to compare with
    o = m.set_index("symbol").loc["AAAUSDT"]
    assert o["age_days"] == 240 and abs(o["play"] - 1) < 0.02 and abs(o["liq_musd"] - 50) < 1 and 0.5 < o["vol_pct"] < 2
    later = d.copy()
    later.loc[later["day"] >= a, ["quote_volume", "close"]] *= 100.0                            # whatever happens from the block start on
    assert universe.characteristics(later, [a], {"TRAINUSDT"}, k=4).equals(m)
    assert m["vol_pct"].is_monotonic_increasing is False and (m["vol_pct"] > 0).all()


def test_a_halted_pair_gets_no_regime_and_does_not_stop_the_others():
    from ft2 import cost
    days = pd.date_range("2023-06-01", periods=30, freq="D", tz="UTC")
    v = pd.DataFrame({"symbol": ["LIVE"] * 30 + ["HALT"] * 30, "vol_pct": [*np.linspace(1, 5, 30), *([0.0] * 25), *np.linspace(1, 5, 5)]}, index=[*days, *days])
    r = v.groupby("symbol")["vol_pct"].transform(cost._terciles).astype(str)
    assert set(r[v["symbol"] == "LIVE"]) == set(cost.REGIMES) and set(r[v["symbol"] == "HALT"]) == {"nan"}


def test_thirds_are_cut_inside_the_block_and_young_means_the_lowest_age(tmp_path):
    _members(tmp_path / "m.csv")
    m = universe.members(tmp_path / "m.csv")
    b = m[m["block"] == m["block"].min()].set_index("symbol")
    assert (b.groupby("violent").size() == 4).all() and set(b.index[b["violent"] == 2]) == set(RIGHT[:4]) and set(b.index[b["violent"] == 0]) == set(WRONG[2:])
    assert set(b.index[b["young"] == 2]) == {"A0USDT", "B0USDT", "A1USDT", "B1USDT"}
    assert (b.loc[["A0USDT", "B0USDT"], "in_play"] == -1).all() and sorted(b["in_play"].value_counts().to_dict().items()) == [(-1, 2), (0, 4), (1, 3), (2, 3)]
    assert universe.screen_symbols(tmp_path / "m.csv") == sorted(RIGHT + WRONG)


def _run(tmp_path, monkeypatch, draws=3):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth()
    _members(tmp_path / "m.csv")
    ref = bt.run(fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2, holdout=False), TRAIN, ["F1"], draws=1, refit_days=15, execs=("taker",), name="ref")
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    r = bt.run(s, [*TRAIN, *RIGHT, *WRONG, OUTSIDE], ["F1"], draws=draws, refit_days=15, execs=("taker", "maker"), name="transfer")
    return ref, r


def test_the_transfer_model_is_the_training_names_in_pair_model_and_trades_members_only(tmp_path, monkeypatch):
    ref, r = _run(tmp_path, monkeypatch)
    o = pd.read_parquet(r["dir"] / "forecast.parquet")
    assert set(o.loc[o["group"] == screen.TRAIN, "symbol"]) == set(TRAIN) and set(o.loc[o["group"] == screen.SCORED, "symbol"]) == set(RIGHT + WRONG)
    v = screen.validity(r["dir"], ref["dir"])
    assert v["status"] == "PASS" and v["cells"] > 3000 and v["max_abs_df_bps"] < 1e-9, v
    dec = r["decisions"]
    assert len(dec) > 500 and set(dec["symbol"]) <= set(RIGHT + WRONG)                          # never a training name, never the outsider
    assert dec["t"].min() >= pd.Timestamp(BLOCKS[0], tz="UTC")
    # a forecast the reference does not hold: void
    bad = pd.read_parquet(ref["dir"] / "forecast.parquet")
    bad.loc[bad.index[5], "f_bps"] += 1e-3
    (tmp_path / "bad").mkdir()
    bad.to_parquet(tmp_path / "bad" / "forecast.parquet", index=False)
    assert screen.validity(r["dir"], tmp_path / "bad")["status"] == "FAIL"


def test_a_member_is_traded_only_inside_its_blocks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth()
    _members(tmp_path / "m.csv")
    m = pd.read_csv(tmp_path / "m.csv")
    m[~((m["symbol"] == "A0USDT") & (m["block"] != BLOCKS[1]))].to_csv(tmp_path / "m.csv", index=False)      # A0: a member of the second block only
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    r = bt.run(s, [*TRAIN, *RIGHT, *WRONG, OUTSIDE], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")
    t = r["decisions"].query("symbol == 'A0USDT'")["t"]
    assert len(t) > 10 and t.min() >= pd.Timestamp(BLOCKS[1], tz="UTC") and t.max() < pd.Timestamp(BLOCKS[2], tz="UTC")
    o = pd.read_parquet(r["dir"] / "forecast.parquet").query("symbol == 'A0USDT'")
    assert o["t"].min() >= pd.Timestamp(BLOCKS[1], tz="UTC") and o["t"].max() < pd.Timestamp(BLOCKS[2], tz="UTC")


def test_the_read_finds_the_planted_screen(tmp_path, monkeypatch):
    ref, r = _run(tmp_path, monkeypatch)
    txt = screen.read("transfer", reference=str(ref["dir"]), draws=40, members=str(tmp_path / "m.csv"))
    assert "**PASS**" in txt and "Best spread: **violent**" in txt
    out = screen.OUT / "transfer"
    scr = pd.read_csv(out / "screens.csv").set_index("screen")
    v = scr.loc["violent"]
    assert v["ic_top"] > 0.05 and v["ic_bottom"] < -0.05 and v["spread_t"] > 3 and v["p_family"] <= 0.1, v
    assert abs(scr.loc["young", "spread_t"]) < v["spread_t"] and abs(scr.loc["liquid", "spread_t"]) < v["spread_t"]
    tr = pd.read_csv(out / "transfer.csv")
    assert abs(tr.loc[0, "ic"]) < 0.05                                                         # half right, half wrong: nothing without the screen
    money = pd.read_csv(out / "money.csv").set_index(["book", "exec"])
    top, all_ = money.loc[("violent: top third", "taker")], money.loc[("all members", "taker")]
    assert top["names"] == 4 and top["gross"] > 2 and top["gross"] > all_["gross"] and top["net_cost_x2"] < top["net"] and 0 < top["flip_p"] <= 1
    # the re-run book on all members is the harness's own book
    res = r["results"].query("exec == 'taker' and scope == 'all'").iloc[0]
    assert all_["trades"] == res["trades"] and abs(all_["net"] - res["net"]) < 1e-9
    assert json.loads((out / "validity.json").read_text())["status"] == "PASS"


# ---- R19: the hindsight diagnostic ------------------------------------------------------------------------------------------
def test_hindsight_volume_reads_the_window_alone_and_counts_a_missing_day_as_zero():
    from datetime import date
    d, days = _daily(n_days=260, start="2025-10-01")                                           # 2025-10-01 → 2026-06-17
    w = (date(2026, 1, 1), date(2026, 3, 31))
    gone = d[~((d["symbol"] == "EEEUSDT") & (d["day"] >= pd.Timestamp("2026-02-01", tz="UTC")))]      # delisted a third of the way in
    h = universe.hindsight_volume(gone[["symbol", "day", "quote_volume"]], ["AAAUSDT", "EEEUSDT", "NEVERUSDT"], w).set_index("symbol")
    assert abs(h.loc["AAAUSDT", "hind_musd"] - 50) < 1 and h.loc["AAAUSDT", "hind_days"] == 90
    assert h.loc["EEEUSDT", "hind_musd"] == 0 and h.loc["EEEUSDT", "hind_days"] == 31          # a bar on 31 of 90 days: the median day has none
    assert h.loc["NEVERUSDT", "hind_musd"] == 0 and h.loc["NEVERUSDT", "hind_days"] == 0
    other = gone.copy()
    other.loc[(other["day"] < pd.Timestamp(w[0], tz="UTC")) | (other["day"] > pd.Timestamp(w[1], tz="UTC")), "quote_volume"] *= 100.0
    assert universe.hindsight_volume(other[["symbol", "day", "quote_volume"]], ["AAAUSDT", "EEEUSDT", "NEVERUSDT"], w).set_index("symbol").equals(h)


def _hindsight(path, flip=False):
    """The RIGHT names are the ones still traded later (the planted hindsight screen); two WRONG names are gone."""
    hi, lo = (WRONG, RIGHT) if flip else (RIGHT, WRONG)
    pd.DataFrame([*({"symbol": s, "hind_musd": 500.0 - i, "hind_days": 243} for i, s in enumerate(hi)),
                  *({"symbol": s, "hind_musd": 0.0 if i < 2 else 5.0 + i, "hind_days": 0 if i < 2 else 243} for i, s in enumerate(lo))]).to_csv(path, index=False)


def test_the_hindsight_read_finds_the_planted_screen_and_leaves_r18s_read_alone(tmp_path, monkeypatch):
    ref, r = _run(tmp_path, monkeypatch)
    _hindsight(tmp_path / "h.csv")
    m = universe.members(tmp_path / "m.csv", tmp_path / "h.csv")
    b = m[m["block"] == m["block"].min()].set_index("symbol")
    assert set(b.index[b["hindsight"] == 2]) <= set(RIGHT) and set(b.index[b["hindsight"] == 0]) <= set(WRONG) and (b.groupby("hindsight").size() == 4).all()
    assert m[[*universe.CHARACTERISTICS]].equals(universe.members(tmp_path / "m.csv")[[*universe.CHARACTERISTICS]])       # R18's thirds are not moved by it
    before = screen.read("transfer", reference=str(ref["dir"]), draws=20, members=str(tmp_path / "m.csv"))
    txt = screen.read("transfer", reference=str(ref["dir"]), draws=20, members=str(tmp_path / "m.csv"), hindsight=tmp_path / "h.csv")
    assert "**PASS**" in txt and "Best spread: **hindsight**" in txt and "best of 5" in txt and "best of 4" in before
    out = screen.OUT / ("transfer" + screen.HINDSIGHT_SUFFIX)
    scr = pd.read_csv(out / "screens.csv").set_index("screen")
    assert list(scr.index) == ["hindsight"]
    h = scr.loc["hindsight"]
    assert h["ic_top"] > 0.05 and h["ic_bottom"] < -0.05 and h["spread_t"] > 3 and h["p_family"] <= 0.1, h
    assert abs(h["ic_of_means_top"]) < abs(h["ic_top"]) and np.isfinite(h["zres_mean_top"])      # the planted skill is in the variation, not in the means
    money = pd.read_csv(out / "money.csv").set_index(["book", "exec"])
    assert {b for b, _ in money.index} == {"all members", "hindsight: top third", "hindsight: bottom third"}
    assert money.loc[("hindsight: top third", "taker"), "gross"] > 2 > money.loc[("hindsight: bottom third", "taker"), "gross"]
    assert "split by R18's `young`" in txt and "hindsight top ∩ young top" in txt and "young top, not hindsight top" in txt
    screen.read("transfer", reference=str(ref["dir"]), draws=20, members=str(tmp_path / "m.csv"))
    assert list(pd.read_csv(screen.OUT / "transfer" / "screens.csv")["screen"]) == list(universe.CHARACTERISTICS)


def test_the_blocks_before_f1_are_fixed_by_the_calendar_and_end_before_f1():
    """R23: seventeen 30-day blocks from 2021-12-10; the last scored day's 7-day label ends before F1's first instant."""
    s = universe.pre_starts()
    assert len(s) == 17 and s[0] == pd.Timestamp("2021-12-10", tz="UTC") and s[-1] == pd.Timestamp("2023-04-04", tz="UTC")
    assert set(np.diff(pd.DatetimeIndex(s)) / pd.Timedelta(days=1)) == {30.0}
    last_bar = pd.Timestamp(universe.PRE_DAYS[1], tz="UTC") + pd.Timedelta(hours=23)
    assert last_bar + pd.Timedelta("5min") * (1 + 2016) < universe.PRE_END == bt.folds.bounds("F1", embargoed=False)[0]
    assert (pd.Timestamp(universe.PRE_DAYS[1]) - pd.Timestamp(universe.PRE_DAYS[0])).days + 1 == 500
