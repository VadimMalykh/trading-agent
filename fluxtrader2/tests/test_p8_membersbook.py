"""R53 (`ft2/membersbook.py`): the ridge is fitted on the members' cells alone (never an excluded name, never a bar outside a
name's membership), a member is scored by the model that never saw its group, the excluded names by the model fitted on all
members; the read finds a planted signal on both and prices the two books apart."""
import json

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import membersbook as mb

MEMBERS = [f"M{i}USDT" for i in range(12)]          # the members: their next hour follows their last hour with sign +PHI
EXCL = [f"X{i}USDT" for i in range(4)]              # the "twelve": the same behaviour, never fitted on
OUTSIDE = "N0USDT"                                  # in the panel, never a member, not excluded: never scored, never traded
HOLD, SD, PHI = 12, 5.0, 0.06
BLOCKS = ["2023-04-01", "2023-05-18", "2023-06-02"]           # the first block starts before F1 so that member rows exist at F1's first fit


def _synth(days=75, start="2023-03-20", seed=3):
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    mkt = rng.normal(0, SD, len(t5))
    c5, fund, cost = [], [], []
    for i, sym in enumerate([*MEMBERS, *EXCL, OUTSIDE]):
        eps = rng.normal(0, SD, len(t5))
        r = eps.copy()
        for k in range(2, 14):
            r[k:] += PHI * eps[:-k]
        px = 100 * (i + 1) * np.exp(np.cumsum(r + mkt) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - pd.Timedelta("5min"), "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 0.0, "interval_h": 8}))
        dd = pd.date_range(t5[0].floor("D"), periods=days + 1, freq="D")
        cost.append(pd.DataFrame({"symbol": sym, "day": dd, "spread_cal_bps": 1.0, f"imp_{bt.NOTIONAL}": 0.5, f"maker_adv_{bt.MAKER_H}": -1.5, f"maker_fill_{bt.MAKER_H}": 0.9}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    pd.concat(cost).to_parquet("data/cost_daily.parquet", index=False)


def _members(path, late=None):
    """Every member in every block — `late` is a member of the second block only."""
    rows = [{"block": b, "symbol": s, "liq_musd": 100 + i, "vol_pct": 8.0 - 0.1 * i, "play": np.nan if i == 0 else 1.0 + 0.1 * i, "age_days": 100 * (i + 1)}
            for b in BLOCKS for i, s in enumerate(MEMBERS) if not (s == late and b != BLOCKS[1])]
    pd.DataFrame(rows).to_csv(path, index=False)


def _run(tmp_path, monkeypatch, late=None, draws=2):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth()
    _members(tmp_path / "m.csv", late)
    s = mb.MembersBook(hold=HOLD, min_bps=2.0, min_pairs=2, exclude=",".join(EXCL), members=str(tmp_path / "m.csv"))
    return bt.run(s, [*EXCL, *MEMBERS, OUTSIDE], ["F1"], draws=draws, refit_days=15, execs=("taker", "maker"), name="mbook")


def test_the_fit_is_on_member_cells_alone_and_the_groups_are_static(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch, late="M0USDT")
    p = r["meta"]["params"]
    assert p["train_rows"] > 5000 and p["train_rows_excluded"] == 0 and p["train_rows_nonmember"] == 0
    o = pd.read_parquet(r["dir"] / "forecast.parquet")
    assert set(o.loc[o["group"] == mb.TWELVE, "symbol"]) == set(EXCL) and OUTSIDE not in set(o["symbol"])
    g = o[o["group"] != mb.TWELVE].groupby("symbol")["group"].agg(["nunique", "first"])
    assert (g["nunique"] == 1).all() and dict(g["first"]) == {s: i % 4 for i, s in enumerate(sorted(MEMBERS))}
    late = o.query("symbol == 'M0USDT'")["t"]                                                   # scored inside its one block only
    assert late.min() >= pd.Timestamp(BLOCKS[1], tz="UTC") and late.max() < pd.Timestamp(BLOCKS[2], tz="UTC")
    dec = r["decisions"]
    assert set(dec["symbol"]) <= set(MEMBERS + EXCL) and set(dec["symbol"]) & set(EXCL) and set(dec["symbol"]) & set(MEMBERS)
    assert dec["t"].min() >= pd.Timestamp("2023-05-03", tz="UTC")                              # nothing before F1's first scored bar
    t0 = dec.query("symbol == 'M0USDT'")["t"]
    assert len(t0) and t0.min() >= pd.Timestamp(BLOCKS[1], tz="UTC") and t0.max() < pd.Timestamp(BLOCKS[2], tz="UTC")


def test_the_read_finds_the_planted_signal_on_both_universes_and_prices_the_books_apart(tmp_path, monkeypatch):
    r = _run(tmp_path, monkeypatch)
    txt = mb.read("mbook", draws=20, members=str(tmp_path / "m.csv"), reference=None)
    out = mb.OUT / "mbook"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["train_rows_excluded"] == 0 and v["member_cells_outside_blocks"] == 0 and v["groups"] == {"0": 3, "1": 3, "2": 3, "3": 3}, v
    ic = pd.read_csv(out / "ic.csv").set_index(["universe", "scope"])
    m, x = ic.loc[("members", "all")], ic.loc[("twelve", "all")]
    assert m["ic"] > 0.05 and m["t"] > 2 and m["cells"] > 5000, m
    assert x["ic"] > 0.05 and x["t"] > 2 and x["cells"] > 1500, x
    assert set(ic.loc["members"].index) >= {"all", "F1", "group 0", "group 3"}
    vd = pd.read_csv(out / "verdicts.csv").set_index("universe")
    assert vd.loc["members", "verdict"] in ("CLEARS", "REAL, NOT FUNDED") and np.isfinite(vd.loc["members", "ic_needed_maker"])
    money = pd.read_csv(out / "money.csv").set_index(["book", "exec"])
    assert {b for b, _ in money.index} == {"members", "twelve"}
    res = r["results"].query("exec == 'taker' and scope == 'all'").iloc[0]
    assert money.loc[("members", "taker"), "trades"] + money.loc[("twelve", "taker"), "trades"] == res["trades"]      # the two books are the run's book
    assert money.loc[("members", "taker"), "gross"] > 1 and 0 < money.loc[("members", "taker"), "flip_p"] <= 1
    need = pd.read_csv(out / "ic_needed.csv")
    assert len(need) == 4 and (need["ic_needed"] > 0).all()
    assert "not read" in txt and "**PASS**" in txt
