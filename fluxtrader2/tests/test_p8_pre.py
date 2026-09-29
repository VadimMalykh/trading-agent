"""P8 — the open-interest score on the months before F1 (`horizon.run_pre`, registration R23): the cells are the block's
members on whole days and nothing else; the verdicts are one-sided; the pooled rule is the registered one; the read finds
the score planted at the longer hold, and leaves a market without one alone."""
import json

import numpy as np
import pandas as pd
import pytest

from ft2 import horizon
from ft2.ceiling import BAR

from test_p8_audit import NAMES, _sources
from test_p8_screen import BLOCKS, HOLD, OUTSIDE, _members, _synth

LONG = 72
DAYS = ("2023-05-03", "2023-07-01")                 # 60 scored days
END = "2023-07-10"


def _plant_score(hold: int = LONG, strength: float = 1.0, seed: int = 17):
    """`_sources`' metrics with open interest over the day's dollar volume leaning the way the name is about to move against
    the others over the next `hold` bars — the score's first term; `oi` itself stays a random walk."""
    c = pd.read_parquet("data/candles_5m.parquet")
    c = c[c["symbol"].isin(NAMES)]
    px = c.assign(t=c["open_time"] + BAR).pivot(index="t", columns="symbol", values="close")[NAMES]
    lr = np.log(px)
    fwd = (lr.shift(-(hold + 1)) - lr.shift(-1)) * 1e4
    lean = (fwd.sub(fwd.mean(axis=1), axis=0) / fwd.stack().std()).fillna(0.0)
    dv = (c["close"] * c["volume"]).groupby(c["symbol"]).mean()
    rng = np.random.default_rng(seed)
    m = pd.read_parquet("data/metrics.parquet")
    for sym in NAMES:
        m.loc[(m["symbol"] == sym).to_numpy(), "oi_value"] = dv[sym] * 288 * np.exp(strength * lean[sym].to_numpy() + rng.normal(0, 0.3, len(px)))
    m.to_parquet("data/metrics.parquet", index=False)


def _market(tmp_path, monkeypatch, plant: bool):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth(days=120)
    _members(tmp_path / "m.csv")
    _sources(planted="taker_ratio")                                                  # outside the score
    if plant:
        _plant_score()
    monkeypatch.setattr(horizon, "MIN_CELLS", 10)                                    # twelve members: one a side
    monkeypatch.setattr(horizon, "PRE_SKIP", ("2023-06",))


def _run(tmp_path, **kw):
    return horizon.run_pre(holds=(LONG,), refs=(HOLD, 36), members=str(tmp_path / "m.csv"), days=DAYS, end=END, registration=None, jobs=1, **kw)


def test_the_verdicts_are_one_sided_and_the_pooled_rule_is_the_registered_one():
    r = {"m_c": 60.0, "u": 2.2, "se": 27.0, "p_one": 0.02, "halves_positive": True, "m_after_first": 40.0}
    assert horizon.verdict_pre(r) == "CLEARS"
    for k, x in (("u", 1.9), ("p_one", 0.06), ("halves_positive", False), ("m_after_first", -1.0)):
        assert horizon.verdict_pre({**r, k: x}) == "GO ON", k                       # above the cost, not certified
    assert horizon.verdict_pre({**r, "m_c": 17.0, "u": 0.6}) == "PARKED" and horizon.verdict_pre({**r, "m_c": -30.0, "u": -1.1}) == "PARKED"
    assert horizon.verdict_pre({**r, "m_c": -60.0, "u": -2.2}) == "CLOSED"           # the wrong way round cannot clear: the direction is fixed
    assert horizon.verdict_pre({**r, "m_c": 3.0, "u": 0.6, "se": 5.0}) == "CLOSED"
    s1, s2 = {"m_c": 40.0, "se": 27.0, "days": 500, "m_after_first": 30.0}, {"m_c": 50.0, "se": 27.0, "days": 500, "m_after_first": 30.0}
    p = horizon.pooled(s1, s2)
    assert np.isclose(p["m_c"], 45.0) and np.isclose(p["se"], 27.0 / np.sqrt(2)) and p["verdict"] == "CLEARS"
    assert horizon.pooled(s1, {**s2, "m_c": 20.0})["verdict"] == "NOT DETECTABLE"                         # u 1.57
    assert horizon.pooled({**s1, "m_c": 120.0}, {**s2, "m_c": -5.0})["verdict"] == "NOT DETECTABLE"      # stage 2 must agree
    assert horizon.pooled(s1, {**s2, "m_after_first": -1.0})["verdict"] == "NOT DETECTABLE"
    assert horizon.pooled({**s1, "se": 5.0, "m_c": 2.0}, {**s2, "se": 5.0, "m_c": 2.0})["verdict"] == "CLOSED"
    q = horizon.pooled({**s1, "days": 300}, {**s2, "days": 100})
    assert np.isclose(q["m_c"], 0.75 * 40 + 0.25 * 50) and np.isclose(q["se"], 27.0 * np.sqrt(0.75 ** 2 + 0.25 ** 2))


def test_the_cells_are_the_blocks_members_on_whole_days(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch, plant=False)
    A = horizon.frame_pre(str(tmp_path / "m.csv"), DAYS, END)
    v, cell, grid = A["validity"], A["cell"], A["grid"]
    assert v["days"] == 60 and v["whole_days"] and v["grid_in_market"] and v["shifts"] == 60 - 29
    assert sorted(cell.columns) == sorted(NAMES) and OUTSIDE not in cell.columns and cell.to_numpy().all() and v["cells"] == 60 * 24 * 12
    assert v["cells_not_a_member"] == 0 and v["cells_of_the_twelve"] == 0 and v["cells_at_or_after_end"] == 0 and not v["members_without_a_bar"]
    assert grid[0] == pd.Timestamp(DAYS[0], tz="UTC") and grid[-1] == pd.Timestamp(DAYS[1] + " 23:00", tz="UTC") and A["M"].index[-1] <= pd.Timestamp(END, tz="UTC")
    # a member of the later blocks only has no cell before its first block; a name that stops trading has none after
    m = pd.read_csv(tmp_path / "m.csv")
    m[~((m["symbol"] == NAMES[0]) & (m["block"] == BLOCKS[0]))].to_csv(tmp_path / "m2.csv", index=False)
    c = pd.read_parquet("data/candles_5m.parquet")
    c[~((c["symbol"] == NAMES[1]) & (c["open_time"] >= pd.Timestamp("2023-06-10", tz="UTC")))].to_parquet("data/candles_5m.parquet", index=False)
    B = horizon.frame_pre(str(tmp_path / "m2.csv"), DAYS, END)
    c2 = B["cell"]
    assert not c2.loc[:pd.Timestamp(BLOCKS[1], tz="UTC") - BAR, NAMES[0]].any() and c2.loc[pd.Timestamp(BLOCKS[1], tz="UTC"):, NAMES[0]].all()
    assert c2.loc[:"2023-06-09", NAMES[1]].all() and not c2.loc["2023-06-11":, NAMES[1]].any() and B["validity"]["cells_not_a_member"] == 0


def test_the_read_finds_the_score_planted_at_the_longer_hold(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch, plant=True)
    txt = _run(tmp_path, cost=5.0)
    out = horizon.OUT / horizon.PRE
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["days"] == 60 and v["shifts"] == 60 - 17 and v["score_coverage"] > 0.95 and "**PASS**" in txt, v
    tab = pd.read_csv(out / "signals.csv").set_index(["signal", "hold"])
    assert len(tab) == 4 * 3 and list(tab[tab["family"]].index) == [(horizon.SCORE, LONG)] and (tab[~tab["family"]]["verdict"] == "reference").all()
    g = tab.loc[(horizon.SCORE, LONG)]
    assert g["m_c"] > 20 and g["u"] > 4 and g["p_one"] <= 0.05 and g["halves_positive"] and g["m_after_first"] > 10 and g["verdict"] == "CLEARS", g
    assert abs(g["centre"]) < 3 * g["se"] and g["ic"] > 0.2 and 0.9 < g["kept_by_a_shift"] <= 1.0 and g["m_skip"] > 20
    assert tab.loc[("oi_turn", LONG), "m_c"] > g["m_c"] * 0.8                        # the planted term itself
    assert abs(tab.loc[("oi_chg_1d", LONG), "u"]) < 3 and abs(tab.loc[("oi_chg_1w", LONG), "u"]) < 3
    assert tab.loc[(horizon.SCORE, HOLD), "m"] < tab.loc[(horizon.SCORE, 36), "m"] < g["m"]
    d = pd.read_parquet(out / "shifts.parquet")
    assert d["shift"].nunique() == 1 + v["shifts"] and len(d) == 4 * 3 * (1 + v["shifts"])
    b = pd.read_csv(out / "blocks.csv")
    assert len(b) == 3 and np.allclose(b["cells_per_bar"], 12) and b["bars"].sum() == 60 * 24
    assert not (tmp_path / "output/backtest/confirmation_reads.csv").exists()        # no registration, no log


def test_without_a_signal_nothing_clears_and_a_thin_score_voids_the_run(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch, plant=False)
    _run(tmp_path, cost=5.0)
    g = pd.read_csv(horizon.OUT / horizon.PRE / "signals.csv").set_index(["signal", "hold"]).loc[(horizon.SCORE, LONG)]
    assert g["verdict"] != "CLEARS" and abs(g["u"]) < 3, g
    m = pd.read_parquet("data/metrics.parquet")                                      # open interest missing on a quarter of the names
    m.loc[m["symbol"].isin(NAMES[:3]), ["oi", "oi_value"]] = np.nan
    m.to_parquet("data/metrics.parquet", index=False)
    with pytest.raises(SystemExit, match="validity FAIL"):
        _run(tmp_path, name="thin")
    v = json.loads((horizon.OUT / "thin" / "validity.json").read_text())
    assert v["status"] == "FAIL" and v["score_coverage"] < 0.9 and not (horizon.OUT / "thin" / "signals.csv").exists()


def test_a_registered_read_waits_for_r22_to_come_back(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/PLAN.md").write_text("### R23 — the score on the months before F1\n")
    with pytest.raises(SystemExit, match="r22_check.json"):
        horizon.run_pre(registration="R23")
    with pytest.raises(SystemExit, match="no '### R99 ' block"):
        horizon.run_pre(registration="R99")


def test_the_lean_ingest_writes_what_the_string_ingest_wrote(tmp_path, monkeypatch):
    """R23: the archive slices are built with the symbol as a category from the start. Same rows, same order, same last
    duplicate kept, the same categories (the pairs present, sorted) as sorting strings and casting at the end gave."""
    import io
    import zipfile

    from ft2 import data
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    rng = np.random.default_rng(0)
    raw, syms = [], ["ZZUSDT", "1000AUSDT", "BBUSDT", "aaUSDT"]                     # asked for in no order; one has no file
    for sym in syms[:3]:
        d = tmp_path / "data/raw/external/binance/metrics" / sym
        d.mkdir(parents=True)
        for day in ("2021-12-02", "2021-12-01"):
            ts = pd.date_range(day, periods=6, freq="5min").strftime("%Y-%m-%d %H:%M:%S")
            df = pd.DataFrame({"create_time": ts, "symbol": sym, **{k: rng.random(6) for k in data.METRICS_COLS if k != "create_time"}})
            df = pd.concat([df, df.iloc[[2]].assign(sum_open_interest=9.0)])       # a duplicate key: the last one is kept
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr(f"{sym}-metrics-{day}.csv", df.to_csv(index=False))
            (d / f"{sym}-metrics-{day}.zip").write_bytes(buf.getvalue())
            (d / f"{sym}-metrics-{day}.zip.ok").touch()
            raw.append(df)
    r = data.ingest_metrics(syms)
    got = pd.read_parquet(r["file"])
    old = pd.concat(raw, ignore_index=True).rename(columns=data.METRICS_COLS)[["symbol", "ts", *[c for c in data.METRICS_COLS.values() if c != "ts"]]]
    old["ts"] = pd.to_datetime(old["ts"], utc=True)
    # files are read in name order (sorted glob): 12-01 before 12-02
    old = pd.concat([old[old["symbol"] == s].sort_values("ts", kind="mergesort") for s in syms[:3]], ignore_index=True)
    old = old.sort_values(["symbol", "ts"], kind="mergesort").drop_duplicates(["symbol", "ts"], keep="last").reset_index(drop=True)
    old["symbol"] = old["symbol"].astype("category")
    assert r["rows_in"] == 42 and r["dups_dropped"] == 6 and len(got) == 36 and (got.groupby("symbol", observed=True)["oi"].apply(lambda x: (x == 9.0).sum()) == 2).all()
    assert list(got["symbol"].cat.categories) == list(old["symbol"].cat.categories) == ["1000AUSDT", "BBUSDT", "ZZUSDT"]
    pd.testing.assert_frame_equal(got, old)
    with pytest.raises(ValueError, match="not among the pairs"):
        data.ingest_metrics(["ZZUSDT", "BBUSDT"] + ["1000BUSDT"]) if (tmp_path / "data/raw/external/binance/metrics/1000AUSDT").rename(
            tmp_path / "data/raw/external/binance/metrics/1000BUSDT") else None


# ---- R24: two `oibook` runs read as one book --------------------------------------------------------------------------------
def test_the_pooled_gate():
    from ft2 import audit
    r = {"net": 20.0, "net_hi": 50.0, "hedged_net": 18.0, "flip_p": 0.03, "gross_positive_in_each": True, "maker_net": 25.0}
    assert audit.pool_verdict(r) == "CANDIDATE"
    for k, x in (("net", -1.0), ("hedged_net", -1.0), ("flip_p", 0.06), ("gross_positive_in_each", False)):
        assert audit.pool_verdict({**r, k: x}) == "NOT FUNDED", k
    assert audit.pool_verdict({**r, "net": -30.0, "net_hi": -5.0, "maker_net": -2.0}) == "CLOSED"
    assert audit.pool_verdict({**r, "net": -30.0, "net_hi": -5.0, "maker_net": 2.0}) == "NOT FUNDED"
    n = [pd.DataFrame({"kind": "flip", "draw": [1, 2, 3], "exec": "taker", "trades": [100, 100, 100], "net": [10.0, -20.0, 0.0]}),
         pd.DataFrame({"kind": "flip", "draw": [1, 2, 3], "exec": "taker", "trades": [300, 300, 300], "net": [-10.0, 20.0, 4.0]})]
    p = audit._pooled_p(n, "taker", "flip", 6.0)
    assert p["draws"] == 3 and np.isclose(p["mean"], (-5.0 + 10.0 + 3.0) / 3) and p["p"] == (1 + 1) / 4


def test_two_runs_are_read_as_one_book_and_costs_are_doubled_by_repricing(tmp_path, monkeypatch):
    from ft2 import audit
    from ft2 import backtest as bt
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth(days=120)
    _members(tmp_path / "m.csv")
    _sources(planted="taker_ratio")
    _plant_score(hold=LONG)
    runs = []
    for name, syms in (("a", NAMES), ("b", [*NAMES, OUTSIDE])):
        bt.run(audit.OIBook(hold=LONG, k=2, members=str(tmp_path / "m.csv")), syms, ["F1"], draws=20, refit_days=15, execs=("taker", "maker"), name=name)
        runs.append(name)
    with pytest.raises(SystemExit, match="validity FAIL"):                           # no book check yet
        audit.pool(runs, name="pool")
    for r in runs:
        assert audit.book_check(r)["status"] == "PASS"
    txt = audit.pool(runs, name="pool")
    out = bt.OUT / "pool"
    v, g = json.loads((out / "validity.json").read_text()), json.loads((out / "gate.json").read_text())
    assert v["status"] == "PASS" and all(x["reprice_max_abs_diff"] < 1e-9 and x["exits_at_or_after_end"] == 0 for x in v["runs"]) and "**PASS**" in txt
    tab = pd.read_csv(out / "pool.csv").set_index(["exec", "scope"])
    one = pd.read_parquet(bt.OUT / "a" / "results.parquet").query("exec == 'taker' and scope == 'all'").iloc[0]
    a, pooled, x2 = tab.loc[("taker", "a")], tab.loc[("taker", "pooled")], tab.loc[("taker, costs doubled", "pooled")]
    assert a["trades"] == one["trades"] and np.isclose(a["net"], one["net"]) and np.isclose(a["gross"], one["gross"])      # a run alone is the harness's own read
    assert pooled["trades"] == 2 * a["trades"] and np.isclose(pooled["net"], a["net"]) and np.isclose(pooled["gross"], x2["gross"])   # the same book twice
    assert np.isclose(pooled["other_cost"], 2.0) and np.isclose(x2["other_cost"], 4.0) and np.isclose(pooled["net"] - x2["net"], 2.0)   # 2 × (0.5 spread + 0.5 impact)
    assert g["gross"] > 10 and g["net"] > 0 and g["flip_p"] <= 0.05 and g["gross_positive_in_each"] and g["verdict"] == "CANDIDATE", g
    assert tab.loc[("taker", "long"), "trades"] == tab.loc[("taker", "short"), "trades"] and ("maker", "pooled") in tab.index
    # a run made with other costs, or of another hold, is not pooled
    m = json.loads((bt.OUT / "b" / "meta.json").read_text())
    (bt.OUT / "b" / "meta.json").write_text(json.dumps({**m, "cost_mult": 2.0}))
    with pytest.raises(SystemExit, match="validity FAIL"):
        audit.pool(runs, name="pool2")
