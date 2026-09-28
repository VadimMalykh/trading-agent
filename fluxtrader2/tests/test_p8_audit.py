"""P8 — the ceiling audit on the point-in-time universe (`ft2/audit.py`, registration R20): a feature at t reads nothing
stamped at or after t; the audit's labels are the run's; the read finds a planted feature and only that one.
`oibook` (registration R21): it trades the audit's own open-interest features, members only, in whole dollar-neutral
units, and earns what was planted; its validity check fails a book that is not."""
import json

import numpy as np
import pandas as pd

from ft2 import audit
from ft2 import backtest as bt
from ft2 import screen
from ft2.ceiling import BAR, _shuffle_days

from test_p8_screen import BLOCKS, HOLD, OUTSIDE, RIGHT, TRAIN, WRONG, _members, _synth

NAMES = [*RIGHT, *WRONG]


def _sources(planted: str = "top_ls_sum", seed: int = 5):
    """metrics, premium and funding for the members of `_synth`'s market: noise, except `planted` — the metrics column
    that leans the way the name is about to move against the others over the next HOLD bars."""
    c = pd.read_parquet("data/candles_5m.parquet")
    c["t"] = c["open_time"] + BAR
    px = c.pivot(index="t", columns="symbol", values="close")[NAMES]
    lr = np.log(px)
    fwd = (lr.shift(-(HOLD + 1)) - lr.shift(-1)) * 1e4
    lean = fwd.sub(fwd.mean(axis=1), axis=0) / fwd.stack().std()
    rng = np.random.default_rng(seed)
    met, pre, fun = [], [], []
    for sym in NAMES:
        n = len(px)
        m = pd.DataFrame({"symbol": sym, "ts": px.index - BAR,                                  # the row stamped ts is used at ts + 5 min
                          "oi": 1e6 * np.exp(np.cumsum(rng.normal(0, 0.002, n))), "top_ls_sum": np.exp(rng.normal(0, 0.3, n)), "global_ls": np.exp(rng.normal(0, 0.3, n)),
                          "taker_ratio": np.exp(rng.normal(0, 0.3, n))})
        m["oi_value"] = m["oi"] * px[sym].to_numpy()
        m[planted] = np.exp(0.3 * lean[sym].fillna(0).to_numpy() + rng.normal(0, 0.3, n))
        met.append(m)
        pre.append(pd.DataFrame({"symbol": sym, "open_time": px.index - BAR, "premium": rng.normal(0, 3e-4, n)}))
        ft = pd.date_range(px.index[0].floor("D"), px.index[-1], freq="8h")
        fun.append(pd.DataFrame({"symbol": sym, "ts": ft, "rate": rng.normal(1e-4, 1e-4, len(ft)), "interval_h": 8}))
    pd.concat(met).to_parquet("data/metrics.parquet", index=False)
    pd.concat(pre).to_parquet("data/premium.parquet", index=False)
    f0 = pd.read_parquet("data/funding_archive.parquet")                                         # the training names keep theirs (the harness prices with it)
    pd.concat([f0[~f0["symbol"].isin(NAMES)], *fun]).to_parquet("data/funding_archive.parquet", index=False)


def _market(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _synth()
    _members(tmp_path / "m.csv")
    _sources()


def test_a_feature_reads_nothing_stamped_at_or_after_its_bar(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch)
    end = pd.Timestamp("2023-06-03", tz="UTC")
    M = bt.market(NAMES, end, start=pd.Timestamp("2023-03-20", tz="UTC"))
    idx = M.index[M.index >= pd.Timestamp("2023-04-10", tz="UTC")]
    F, notes = audit.features(idx, NAMES, M.dv.loc[idx], end)
    assert not notes and list(F) == audit.FEATURES and all(x.notna().to_numpy().mean() > 0.6 for x in F.values())
    cut = pd.Timestamp("2023-05-10 12:00", tz="UTC")
    m = pd.read_parquet("data/metrics.parquet")
    m.loc[m["ts"] >= cut, ["oi", "oi_value", "top_ls_sum", "global_ls", "taker_ratio"]] *= 3.0          # a metrics row stamped at the bar's time or later
    m.to_parquet("data/metrics.parquet", index=False)
    p = pd.read_parquet("data/premium.parquet")
    p.loc[p["open_time"] + BAR > cut, "premium"] += 0.01                                                 # a premium bar that closes after the bar
    p.to_parquet("data/premium.parquet", index=False)
    f = pd.read_parquet("data/funding_archive.parquet")
    f.loc[f["ts"] >= cut, "rate"] += 0.01                                                                 # a rate settled at the bar's time or later
    f.to_parquet("data/funding_archive.parquet", index=False)
    G, _ = audit.features(idx, NAMES, M.dv.loc[idx], end)
    for k in audit.FEATURES:
        assert F[k].loc[:cut].equals(G[k].loc[:cut]), k
        assert not F[k].loc[cut + BAR:].equals(G[k].loc[cut + BAR:]), k
    # per 8 h: a 4-hour rate counts double
    f = pd.read_parquet("data/funding_archive.parquet")
    f.loc[f["symbol"] == NAMES[0], ["rate", "interval_h"]] = [1e-4, 4]
    f.to_parquet("data/funding_archive.parquet", index=False)
    H, _ = audit.features(idx, NAMES, M.dv.loc[idx], end)
    assert np.allclose(H["funding_last"][NAMES[0]].dropna(), 2.0) and np.allclose(H["funding_7d"][NAMES[0]].dropna(), 2.0)


def test_whole_days_trade_places_on_an_hourly_grid():
    ts = pd.date_range("2023-05-03", periods=40 * 24, freq="1h", tz="UTC")
    src = _shuffle_days(ts, np.ones(len(ts)), np.random.default_rng(1), audit.GRID)
    d = lambda i: (ts[i].floor("D") - ts[0].floor("D")).days                                              # noqa: E731
    assert sorted(src) == list(range(len(ts))) and (ts[src].hour == ts.hour).all() and (src != np.arange(len(ts))).mean() > 0.8
    gap = np.array([d(i) - d(s) for i, s in enumerate(src)])
    assert not ((gap > 0) & (gap <= 8)).any() and all(len({d(s) for s in src[k:k + 24]}) == 1 for k in range(0, len(ts), 24))


def test_the_audit_finds_the_planted_feature_and_its_labels_are_the_runs(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch)
    s = screen.TransferBook(hold=HOLD, min_bps=2.0, min_pairs=2, train=",".join(TRAIN), members=str(tmp_path / "m.csv"))
    bt.run(s, [*TRAIN, *NAMES], ["F1"], draws=1, refit_days=15, execs=("taker",), name="transfer")
    txt = audit.run("transfer", draws=30, members=str(tmp_path / "m.csv"), jobs=1)
    out = audit.OUT / "transfer"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["cells"] > 5000 and v["names"] == 12 and v["max_abs_dz"] < 1e-9 and "**PASS**" in txt
    tab = pd.read_csv(out / "features.csv").set_index("feature")
    assert list(tab.index) == audit.FEATURES and (tab["coverage"] > 0.9).all()
    top = tab.loc["top_ls"]
    assert top["ic"] > 0.05 and top["t"] > 4 and top["p_family"] <= 0.05 and top["verdict"] == "CLEARS", top
    assert tab.loc["top_vs_global", "ic"] > 0.02                                                          # it holds the planted column
    rest = tab.drop(index=["top_ls", "top_vs_global"])
    assert (rest["verdict"] != "CLEARS").all() and (rest["ic"].abs() < 0.03).all(), rest
    assert v["reference_ic"] < 0.02 and v["ic_needed"] > 0                                                # half the members follow the ridge, half go against it
    d = pd.read_parquet(out / "draws.parquet")
    assert d["draw"].max() == 30 and d[d["draw"] > 0].groupby("draw")["t"].apply(lambda t: t.abs().max()).quantile(0.95) < top["t"]


# ---- R21: oibook ------------------------------------------------------------------------------------------------------------
def _plant_oi(strength: float = 1.0, seed: int = 11):
    """`_sources`' metrics with the open interest planted: `oi_value` over the day's dollar volume leans the way the name is
    about to move against the others over the next HOLD bars; `oi` itself (the two change features) stays a random walk."""
    c = pd.read_parquet("data/candles_5m.parquet")
    c = c[c["symbol"].isin(NAMES)]
    px = c.assign(t=c["open_time"] + BAR).pivot(index="t", columns="symbol", values="close")[NAMES]
    lr = np.log(px)
    fwd = (lr.shift(-(HOLD + 1)) - lr.shift(-1)) * 1e4
    lean = (fwd.sub(fwd.mean(axis=1), axis=0) / fwd.stack().std()).fillna(0.0)
    dv = (c["close"] * c["volume"]).groupby(c["symbol"]).mean()
    rng = np.random.default_rng(seed)
    m = pd.read_parquet("data/metrics.parquet")
    for sym in NAMES:
        m.loc[(m["symbol"] == sym).to_numpy(), "oi_value"] = dv[sym] * 288 * np.exp(strength * lean[sym].to_numpy() + rng.normal(0, 0.3, len(px)))
    m.to_parquet("data/metrics.parquet", index=False)


def test_only_builds_the_same_numbers_and_the_harness_attaches_them(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch)
    end = pd.Timestamp("2023-06-03", tz="UTC")
    M = bt.market(NAMES, end, start=pd.Timestamp("2023-03-20", tz="UTC"), needs=("oi",))
    F, _ = audit.features(M.index, NAMES, M.dv, end)
    G, notes = audit.features(M.index, NAMES, M.dv, end, only=audit.OI)
    assert not notes and list(G) == audit.OI and all(G[k].equals(F[k]) for k in audit.OI)
    X = M.extra["oi"]
    assert list(X.columns.get_level_values(0).unique()) == audit.OI and all(X[k].equals(F[k]) for k in audit.OI)
    cut = M.until(pd.Timestamp("2023-05-10", tz="UTC"))
    assert cut.extra["oi"].index.equals(cut.close.index)


def test_oibook_trades_members_in_whole_units_and_earns_what_was_planted(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch)
    _plant_oi()
    m = pd.read_csv(tmp_path / "m.csv")
    m[~((m["symbol"] == "A0USDT") & (m["block"] != BLOCKS[1]))].to_csv(tmp_path / "m.csv", index=False)      # A0: a member of the second block only
    s = audit.OIBook(hold=HOLD, k=2, members=str(tmp_path / "m.csv"))
    r = bt.run(s, [*NAMES, OUTSIDE], ["F1"], draws=20, refit_days=15, execs=("taker",), name="oibook")
    dec = r["decisions"]
    t = pd.DatetimeIndex(dec["t"])
    assert len(dec) > 1500 and set(dec["symbol"]) <= set(NAMES) and (t.minute == 0).all() and t.min() >= pd.Timestamp(BLOCKS[0], tz="UTC")
    a0 = dec.loc[dec["symbol"] == "A0USDT", "t"]
    assert len(a0) > 10 and a0.min() >= pd.Timestamp(BLOCKS[1], tz="UTC") and a0.max() < pd.Timestamp(BLOCKS[2], tz="UTC")
    per_bar = dec.groupby("t")["side"].agg(["size", "sum"])
    assert (per_bar["size"] == 4).all() and (per_bar["sum"] == 0).all()                                   # two a side at every decision bar
    v = audit.book_check("oibook", members=str(tmp_path / "m.csv"))
    assert v["status"] == "PASS" and v["accepted"] > 1000 and v["accepted_long"] == v["accepted_short"] and v["units"] * 2 == v["accepted"], v
    res = r["results"].query("exec == 'taker'").set_index("scope")
    assert res.loc["all", "gross"] > 10 and res.loc["all", "hedged"] > 10 and res.loc["all", "net"] > 0, res.loc["all"]
    assert res.loc["long", "hedged"] > 5 and res.loc["short", "hedged"] > 5
    assert r["floor"].set_index("exec").loc["taker", "flip_p"] <= 0.05
    # the score is a rank among the members present: the same decisions whatever the other columns of the panel hold
    s2 = audit.OIBook(hold=HOLD, k=2, members=str(tmp_path / "m.csv"))
    r2 = bt.run(s2, NAMES, ["F1"], draws=1, refit_days=15, execs=("taker",), name="oibook_members_only")
    k = ["t", "symbol", "side", "accepted"]
    assert r2["decisions"][k].equals(dec[k])
    # a book that is not whole fails its check
    d = pd.read_parquet(r["dir"] / "decisions.parquet")
    d.loc[d.index[d["accepted"]][0], "side"] *= -1
    d.to_parquet(r["dir"] / "decisions.parquet", index=False)
    assert audit.book_check("oibook", members=str(tmp_path / "m.csv"))["status"] == "FAIL"


def test_oibook_without_a_signal_pays_its_costs(tmp_path, monkeypatch):
    _market(tmp_path, monkeypatch)                                                                        # the open interest is noise
    s = audit.OIBook(hold=HOLD, k=2, members=str(tmp_path / "m.csv"))
    r = bt.run(s, NAMES, ["F1"], draws=20, refit_days=15, execs=("taker",), name="oibook_noise")
    a = r["results"].query("exec == 'taker'").set_index("scope").loc["all"]
    assert abs(a["gross"]) < 3 * a["net_se"] and a["net"] < 0 and abs(a["net"] + 12.0) < 3 * a["net_se"], a   # 2 × (5 fee + 0.5 spread + 0.5 impact)
    assert r["floor"].set_index("exec").loc["taker", "flip_p"] > 0.05
