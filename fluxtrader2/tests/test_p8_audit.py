"""P8 — the ceiling audit on the point-in-time universe (`ft2/audit.py`, registration R20): a feature at t reads nothing
stamped at or after t; the audit's labels are the run's; the read finds a planted feature and only that one."""
import json

import numpy as np
import pandas as pd

from ft2 import audit
from ft2 import backtest as bt
from ft2 import screen
from ft2.ceiling import BAR, _shuffle_days

from test_p8_screen import HOLD, RIGHT, TRAIN, WRONG, _members, _synth

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
