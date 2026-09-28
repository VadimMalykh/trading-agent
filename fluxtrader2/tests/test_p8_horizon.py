"""P8 — the longer hold (`ft2/horizon.py`, registration R22): every admissible shift moves whole days and keeps its
distance; the statistic is the money of the extreme tenths; the label is what the harness pays a long; the read finds a
signal planted at the longer hold, and only there."""
import json

import numpy as np
import pandas as pd

from ft2 import audit, horizon
from ft2 import backtest as bt
from ft2 import screen
from ft2.ceiling import BAR

from test_p8_audit import NAMES, _sources
from test_p8_screen import HOLD, TRAIN, _members, _synth

LONG = 72                                          # the longer hold of the tests, bars


def test_every_admissible_shift_moves_whole_days_and_keeps_its_distance():
    nd, gap = 40, horizon.gap_days([LONG, 2016])
    assert gap == 15 and horizon.gap_days(horizon.HOLDS) == 15 and horizon.gap_days([36, LONG]) == 9
    ks = horizon.shifts(nd, gap)
    assert list(ks) == list(range(15, 26)) and len(horizon.shifts(485, 15)) == 456
    n = nd * horizon.PER_DAY
    for k in ks:
        src = horizon.shifted(n, k)
        assert sorted(src) == list(range(n)) and (src % horizon.PER_DAY == np.arange(n) % horizon.PER_DAY).all()
        d, s = np.arange(n) // horizon.PER_DAY, src // horizon.PER_DAY
        assert (np.abs(s - d) >= gap).all() and all(len(set(s[i:i + horizon.PER_DAY])) == 1 for i in range(0, n, horizon.PER_DAY))


def test_the_statistic_is_the_money_of_the_extreme_tenths():
    S = np.tile(np.arange(30.0), (48, 1))
    Y = S * 10.0
    assert np.allclose(horizon._tenths(S, Y), [(280.0 - 10.0) / 2] * 2)             # 30 names: three a side
    S2, Y2 = S.copy(), Y.copy()
    S2[:, :2], Y2[:, 27:] = np.nan, np.nan                                          # 25 left: two a side, the lowest are names 2, 3 and the highest 25, 26
    assert np.allclose(horizon._tenths(S2, Y2), [(255.0 - 25.0) / 2] * 2)
    S2[:24, :11] = np.nan                                                           # the first day: 16 cells, under MIN_CELLS
    m = horizon._tenths(S2, Y2)
    assert np.isnan(m[0]) and np.isclose(m[1], 115.0)
    Y3 = Y.copy()
    Y3[:, 29] = -1e4                                                                # one large loser among the highest: the mean sees it, the rank would not
    assert np.allclose(horizon._tenths(S, Y3), [((270.0 + 280.0 - 1e4) / 3 - 10.0) / 2] * 2)
    t = horizon._by_tenth(S, Y)
    assert list(t.index) == list(range(1, 11)) and (t["cells"] == 48 * 3).all() and np.isclose(t.loc[10, "mean"], 280.0 - 145.0) and np.isclose(t.loc[1, "median"], 10.0 - 145.0)


def test_the_verdicts():
    r = {"m_c": 50.0, "u": 3.5, "se": 14.0, "p_family": 0.02, "folds_same_sign": True, "after_same_sign": True}
    assert horizon.verdict(r) == "CLEARS"
    for k, x in (("m_c", 17.0), ("u", 1.9), ("p_family", 0.06), ("folds_same_sign", False), ("after_same_sign", False)):
        assert horizon.verdict({**r, k: x}) == "NOT DETECTABLE", k
    assert horizon.verdict({**r, "m_c": -50.0, "u": -3.5}) == "CLEARS"                                   # two-sided
    assert horizon.verdict({**r, "m_c": 3.0, "u": 0.6, "se": 5.0}) == "CLOSED" and horizon.verdict({**r, "m_c": 3.0, "u": 0.3, "se": 10.0}) == "NOT DETECTABLE"


def _plant(col: str = "global_ls", hold: int = LONG, seed: int = 13):
    """`_sources`' metrics with `col` leaning the way the name is about to move against the others over the next `hold` bars."""
    c = pd.read_parquet("data/candles_5m.parquet")
    c = c[c["symbol"].isin(NAMES)]
    lr = np.log(c.assign(t=c["open_time"] + BAR).pivot(index="t", columns="symbol", values="close")[NAMES])
    fwd = (lr.shift(-(hold + 1)) - lr.shift(-1)) * 1e4
    lean = (fwd.sub(fwd.mean(axis=1), axis=0) / fwd.stack().std()).fillna(0.0)
    rng = np.random.default_rng(seed)
    m = pd.read_parquet("data/metrics.parquet")
    for sym in NAMES:
        m.loc[(m["symbol"] == sym).to_numpy(), col] = np.exp(0.3 * lean[sym].to_numpy() + rng.normal(0, 0.3, len(lr)))
    m.to_parquet("data/metrics.parquet", index=False)


def test_the_read_finds_the_signal_planted_at_the_longer_hold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth(days=95)
    _members(tmp_path / "m.csv")
    _sources(planted="taker_ratio")                                                  # outside R22's signals
    _plant()
    monkeypatch.setattr(horizon, "MIN_CELLS", 10)                                    # twelve members: one a side
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    r = bt.run(s, [*TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")
    audit.run("transfer", draws=3, members=str(tmp_path / "m.csv"), jobs=1)
    txt = horizon.run("transfer", holds=(36, LONG), members=str(tmp_path / "m.csv"), jobs=1)
    out = horizon.OUT / "transfer"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["days"] == 51 and v["shifts"] == 51 - 17 and v["whole_days"] and v["max_abs_d_ic_r20"] < 1e-12 and "**PASS**" in txt, v
    tab = pd.read_csv(out / "signals.csv").set_index(["signal", "hold"])
    assert set(tab.index.get_level_values(0)) == {*horizon.SIGNALS, horizon.SCORE} and set(tab.index.get_level_values(1)) == {HOLD, 36, LONG}
    fam = tab[tab["family"]]
    assert len(fam) == 12 and (tab[~tab["family"]]["verdict"] == "reference").all() and len(tab) == 21
    g = tab.loc[("global_ls", LONG)]
    assert g["m_c"] > 30 and g["u"] > 5 and g["p_family"] <= 0.05 and g["m_after_first"] > 20 and g["verdict"] == "CLEARS", g
    assert abs(g["centre"]) < 3 * g["se"] and 0.3 < g["se_hac"] / g["se"] < 3 and g["ic"] > 0.3
    assert tab.loc[("top_vs_global", LONG), "m_c"] < -15                             # it holds the planted column, with the other sign
    assert tab.loc[("global_ls", 36), "m"] > 10 and tab.loc[("global_ls", HOLD), "m"] < tab.loc[("global_ls", 36), "m"] < g["m"]
    rest = fam.drop(index=[(k, h) for k in ("global_ls", "top_vs_global") for h in (36, LONG)])
    assert (rest["verdict"] != "CLEARS").all() and (rest["u"].abs() < 4).all(), rest
    d = pd.read_parquet(out / "shifts.parquet")
    assert d["shift"].nunique() == 1 + v["shifts"] and len(d) == 7 * 3 * (1 + v["shifts"])
    t = pd.read_csv(out / "tenths.csv")
    assert len(t) == 21 * 10 and t.groupby(["signal", "hold"])["cells"].sum().min() > 5000

    # the label is what the harness pays a long: a fill's gross + funding, by its side
    end = bt.folds.bounds("F1")[1]
    M = bt.market([*TRAIN, *NAMES], end)
    y, earned = horizon.labels(M, bt.load_costs(M.index, M.columns, end).fundcum, HOLD, 1)
    f = pd.read_parquet(r["dir"] / "fills_taker.parquet").dropna(subset=["net_bps"])
    i, j = M.index.get_indexer(f["t"]), M.columns.get_indexer(f["symbol"])
    assert len(f) > 500 and np.allclose(f["side"] * y.to_numpy()[i, j], f["gross_bps"]) and np.allclose(f["side"] * earned.to_numpy()[i, j], f["gross_bps"] + f["funding_bps"])
    assert (f["funding_bps"] != 0).mean() > 0.05 and abs(tab.loc[("global_ls", LONG), "funding_part"]) < 2
