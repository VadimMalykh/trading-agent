"""P5 unit tests: the pre-history plumbing (archive klines under the collector's, the fold order, proxied
costs, the read-once guard) and the two rules registered as R4 / R5."""
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt, ceiling, data, folds
from ft2.rules import Panic, RankContinuation, RankReversal
from test_p3 import PAIRS, _synth


def _market(n_fall: int, n: int = 6) -> bt.Market:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=60 * 288, freq="5min", tz="UTC")
    r = rng.normal(0, 5.0, (len(idx), n))
    r[-300:] *= 4
    r[-60:, :n_fall] -= 15                            # the first n_fall pairs have just fallen ~900 bps …
    r[-60:, n_fall:] += 8                             # … the others rose, so that none of them falls by chance
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=list("ABCDEFGH")[:n])
    return bt.Market(close, close, close, close)


def test_panic_buys_every_pair_only_when_a_third_fell_together():
    for n_fall, traded in ((1, False), (2, True), (4, True)):
        M = _market(n_fall)
        now = M.index[-288]
        rule = Panic(window_days=30)
        rule.fit(M.until(now), None, now)
        d = rule.decide(M, now, M.index[-1] + bt.BAR)
        last = d[d["t"] == M.index[-1]]
        assert (len(last) == 6 and (last["side"] == 1).all()) if traded else last.empty
    bt.causal_check(rule, M, now, M.index[-1] + bt.BAR)


def test_rank_continuation_is_the_mirror_of_the_rank_rule():
    M = _market(1)
    now = M.index[-288]
    a, b = RankReversal(window_days=30), RankContinuation(window_days=30)
    for rule in (a, b):
        rule.fit(M.until(now), None, now)
    da, db = (r.decide(M, now, M.index[-1] + bt.BAR) for r in (a, b))
    assert len(da) and (da["t"].to_numpy() == db["t"].to_numpy()).all() and (da["side"].to_numpy() == -db["side"].to_numpy()).all() and (da["group"] == db["group"]).all()
    assert db[(db["t"] == M.index[-1]) & (db["symbol"] == "A")]["side"].iloc[0] == -1              # the fallen pair is SOLD


def test_archive_klines_are_ingested_with_and_without_a_header(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "data/raw/external/binance/klines/AUSDT"
    d.mkdir(parents=True)
    row = lambda ms, c: f"{ms},1,2,0.5,{c},10,{ms + 299999},100,5,4,40,0"                           # noqa: E731
    for name, body in (("AUSDT-5m-2020-01-01", row(1577836800000, 1.5) + "\n" + row(1577837100000, 1.6)),
                       ("AUSDT-5m-2020-01-02", ",".join(data.KLINE_COLS) + "\n" + row(1577923200000, 1.7))):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(name + ".csv", body)
        (d / (name + ".zip")).write_bytes(buf.getvalue())
        (d / (name + ".zip.ok")).touch()
    r = data.ingest_klines(["AUSDT", "BUSDT"])
    k = pd.read_parquet(r["file"])
    assert r["rows_out"] == 3 and list(k["close"]) == [1.5, 1.6, 1.7] and k["open_time"].iloc[0] == pd.Timestamp("2020-01-01", tz="UTC")


def test_prehistory_runs_under_the_collector_and_is_read_once_by_registration(tmp_path):
    _synth(tmp_path, start="2022-08-10", days=40)                                                   # the collector: from inside FP's last days
    c, c_cost = pd.read_parquet("data/candles_5m.parquet"), pd.read_parquet("data/cost_daily.parquet")
    _synth(tmp_path, start="2022-04-01", days=135, seed=2)                                          # the archive: before it, overlapping it
    pd.read_parquet("data/candles_5m.parquet").to_parquet("data/candles_5m_archive.parquet", index=False)
    cost = pd.concat([pd.read_parquet("data/cost_daily.parquet"), c_cost]).drop_duplicates(["symbol", "day"]).assign(**{f"maker_fill_{bt.MAKER_H}": np.nan})
    cost.to_parquet("data/cost_daily_pre.parquet", index=False)
    c.to_parquet("data/candles_5m.parquet", index=False)
    assert folds.order(["F1", "FP", "F0"]) == ["FP", "F0", "F1"]
    P = ceiling.panel(PAIRS, pd.Timestamp("2022-09-01", tz="UTC"), bt.PRE_START)
    seam = pd.Timestamp("2022-08-10 00:00", tz="UTC")
    assert P["close"].index[0] < pd.Timestamp("2022-04-02", tz="UTC") and P["close"].loc[seam, PAIRS[0]] == c[(c["symbol"] == PAIRS[0])]["close"].iloc[0]
    with pytest.raises(SystemExit):
        bt.run(bt.Coin(hold=12), PAIRS, ["FP"], draws=2)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/PLAN.md").write_text("### R9 — test\n")
    r = bt.run(bt.Coin(hold=12), PAIRS, ["FP"], execs=("taker", "maker"), draws=2, registration="R9", cost_mult=2.0)
    x = r["results"].query("scope == 'all' and exec == 'taker'").iloc[0]
    assert x["trades"] > 100 and x["unpriced"] < 10 and abs(x["other_cost"] - 2 * 2 * (0.5 + 0.5)) < 1e-9       # two legs × (half of 1 bps spread + 0.5 impact) × 2; unpriced: only trades still open when the fold's market ends
    with pytest.raises(SystemExit):
        bt.run(bt.Coin(hold=12), PAIRS, ["FP"], draws=2, registration="R9")
