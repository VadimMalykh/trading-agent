"""P7 — the serving path (`ft2/serve.py`). On synthetic data: the hourly live path (fresh scorer from the JSON model, the
tail of the market, the book rule from the ledger) must reproduce the harness's forecasts and accepted decisions exactly;
decide/mark runs against a fake exchange write the ledger the docstring describes; a late decision is recorded and not
taken; a stored bar is never overwritten; the causal check passes on a clean ledger and fails on a tampered one; the
refit schedule is the harness's."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt
from ft2 import forecast as fc
from ft2 import serve as sv
from ft2.ceiling import BAR

PAIRS = ["AAUSDT", "BBUSDT", "CCUSDT", "DDUSDT", "EEUSDT", "FFUSDT"]
HOLD, SD, PHI = 12, 5.0, 0.06
PARAMS = {"hold": HOLD, "min_bps": 2.0, "cap": 2.0, "groups": 2, "grid": 12, "min_pairs": 2, "holdout": True, "features": "candle"}


def _synth(tmp_path, days=75, start="2023-03-20", seed=3):
    """tests/test_p5_forecast.py's market: random walks sharing a factor, each pair's next hour following its last hour with
    φ = +PHI on group 0 and −PHI on group 1 — so a held-out ridge has something to forecast (wrongly, which is fine here)."""
    os.chdir(tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    rng = np.random.default_rng(seed)
    t5 = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=days * 288, freq="5min")
    mkt = rng.normal(0, SD, len(t5))
    c5, fund = [], []
    for i, sym in enumerate(PAIRS):
        phi = PHI if i % 2 == 0 else -PHI
        eps = rng.normal(0, SD, len(t5))
        r = eps.copy()
        for k in range(2, 14):
            r[k:] += phi * eps[:-k]
        px = 100 * (i + 1) * np.exp(np.cumsum(r + mkt) / 1e4)
        c5.append(pd.DataFrame({"symbol": sym, "open_time": t5 - BAR, "open": px, "high": px * 1.0005, "low": px * 0.9995, "close": px, "volume": 10.0, "close_time": t5 - pd.Timedelta("1ms")}))
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t5[0], periods=days * 3, freq="8h"), "rate": 1e-4 * (i + 1), "interval_h": 8}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)


def _cfg(**kw):
    return sv.Config(pairs=PAIRS, params=dict(PARAMS), refit_folds=("F1",), **kw)


class FakeExchange:
    """Binance's three endpoints, answered from the synthetic candles and funding: closed bars only (open_time + 5 min ≤ now),
    paged like the real one; the quote is the bar's close ± 1 bps."""

    def __init__(self, candles: pd.DataFrame, funding: pd.DataFrame):
        self.c, self.f, self.now, self.calls = candles, funding, None, []

    def __call__(self, path, params):
        self.calls.append(path)
        if path == "/fapi/v1/klines":
            c = self.c[(self.c["symbol"] == params["symbol"]) & (self.c["open_time"] >= pd.Timestamp(params["startTime"], unit="ms", tz="UTC"))]
            c = c[c["open_time"] + BAR <= self.now].head(params["limit"])
            return [[str(sv._ms(r.open_time)), str(r.open), str(r.high), str(r.low), str(r.close), str(r.volume), str(sv._ms(r.open_time) + 299_999), "0", "0", "0", "0", "0"]
                    for r in c.itertuples()]
        if path == "/fapi/v1/ticker/bookTicker":
            t = self.now.floor("5min")
            c = self.c[self.c["open_time"] + BAR == t]
            return [{"symbol": r.symbol, "bidPrice": f"{r.close * (1 - 1e-4):.8f}", "askPrice": f"{r.close * (1 + 1e-4):.8f}"} for r in c.itertuples()] + [{"symbol": "ZZUSDT", "bidPrice": "1", "askPrice": "2"}]
        if path == "/fapi/v1/fundingRate":
            f = self.f[(self.f["symbol"] == params["symbol"]) & (self.f["ts"] >= pd.Timestamp(params["startTime"], unit="ms", tz="UTC")) & (self.f["ts"] <= self.now)]
            return [{"symbol": r.symbol, "fundingTime": sv._ms(r.ts), "fundingRate": str(r.rate), "markPrice": "0"} for r in f.itertuples()]
        raise AssertionError(path)


# ---- identity: the live path IS the harness ------------------------------------------------------------------------------------------
def test_replay_reproduces_the_harness_forecasts_and_decisions_exactly(tmp_path):
    _synth(tmp_path, days=75)
    cfg = _cfg()
    sv.seed(cfg)
    # the harness, as `bt.run` walks it (no noise floor, no pricing needed): fit per block, decide, accept
    M = sv.market(sv.load_candles(cfg), PAIRS)
    s = fc.RidgeBook(**PARAMS)
    dec = bt.walk(s, M, ["F1"], bt.labels(M, HOLD, bt.LATENCY), bt.LATENCY, bt.REFIT_DAYS)
    ref_f = s.oos()
    assert dec["accepted"].sum() > 30 and ref_f["f_bps"].notna().sum() > 1000
    # the live path: JSON model, tail market, one bar at a time, the ledger's book rule
    r = sv.replay(cfg, ["F1"], against=None, verbose=False)
    led = r["ledger"]
    d = sv.diff(led, ref_f, dec, explain=False, hold_bars=HOLD)
    assert d["pass"], d
    assert d["cells_compared"] == len(ref_f) and d["cells_only_ledger"] == 0 and d["cells_only_ref"] == 0
    assert d["max_abs_df_bps"] <= sv.F_TOL and d["taken_same"] == dec["accepted"].sum() == d["taken_ledger"]   # round-off between the tail's and the panel's rolling windows: ~1e-13
    assert set(led["skip"]) <= {"", "no_signal", "position_open"}          # hold 12 = one grid step here, so a position never blocks the next bar
    # the models on disk are what scored: reloading one and scoring a bar gives the ledger's row
    mid = led["model_id"].iloc[-1]
    s2 = sv.load_model(cfg.out / "replay" / "models" / f"{mid}.json", cfg)
    t = led["t"].max()
    row = sv.forecast_at(s2, M, t).set_index("symbol")
    got = led[led["t"] == t].set_index("symbol")
    assert np.allclose(row["f_bps"], got["f_bps"], equal_nan=True) and (row["side"] == got["side"]).all()


def test_the_tail_market_scores_like_the_full_one_and_the_json_round_trip_is_exact(tmp_path):
    _synth(tmp_path, days=40)
    cfg = _cfg()
    sv.seed(cfg)
    M = sv.market(sv.load_candles(cfg), PAIRS)
    ba = pd.Timestamp("2023-04-20", tz="UTC")
    s = sv.fit(M, ba, cfg)
    path = sv.save_model(s, ba, M, cfg)
    doc = json.loads(path.read_text())
    assert doc["model_id"] == "model_2023-04-20" and set(doc["groups"]) == {"0", "1"} and doc["params"] == PARAMS
    s2 = sv.load_model(path, cfg)
    for g in s._models:
        for a, b in zip(s._models[g], s2._models[g]):
            assert np.array_equal(a, b)
    assert s2._sigma_ref == s._sigma_ref
    t = pd.Timestamp("2023-04-25 13:00", tz="UTC")
    # the persistent, fully-cached strategy on the full market vs a fresh scorer on the tail
    s._ensure(M)
    ts, f_full, sig_full, _ = s._forecast(M, t, t + BAR)
    row = sv.forecast_at(s2, M, t)
    assert np.allclose(row["f_bps"], f_full[0], equal_nan=True) and np.allclose(row["sigma_h"], sig_full[0], equal_nan=True)
    assert row["f_bps"].notna().all() and (row["side"] != 0).any()
    with pytest.raises(ValueError):
        sv.load_model(path, sv.Config(pairs=PAIRS, params=dict(PARAMS, min_bps=3.0)))


def test_ensure_chunked_equals_one_shot(tmp_path):
    _synth(tmp_path, days=40)
    cfg = _cfg()
    sv.seed(cfg)
    M = sv.market(sv.load_candles(cfg), PAIRS)
    a, b = fc.RidgeBook(**PARAMS), fc.RidgeBook(**PARAMS)
    a._ensure(M)
    sv.ensure_chunked(b, M, days=7)
    assert a._ts == b._ts
    Xa, Sa = a._rows(pd.DatetimeIndex(a._ts))
    Xb, Sb = b._rows(pd.DatetimeIndex(a._ts))
    assert (np.isnan(Xa) == np.isnan(Xb)).all() and (np.isnan(Sa) == np.isnan(Sb)).all()
    assert np.allclose(np.nan_to_num(Xa), np.nan_to_num(Xb), atol=1e-9, rtol=0) and np.allclose(np.nan_to_num(Sa), np.nan_to_num(Sb), atol=1e-9, rtol=0)   # ~1e-14: rolling-std round-off


# ---- the live runs against a fake exchange ---------------------------------------------------------------------------------------------
def _live(tmp_path, hours=30, t0="2023-05-20 00:00"):
    """Seed to t0, then decide/mark runs every hour for `hours` hours, the exchange serving the rest of the synthetic candles."""
    _synth(tmp_path, days=75)
    cfg = _cfg()
    c, f = pd.read_parquet("data/candles_5m.parquet"), pd.read_parquet("data/funding_archive.parquet")
    t0 = pd.Timestamp(t0, tz="UTC")
    c[c["open_time"] + BAR <= t0].to_parquet("data/candles_seed_src.parquet", index=False)
    sv.seed(cfg, src=Path("data/candles_seed_src.parquet"))
    ex = FakeExchange(c, f)
    ex.now = t0 + pd.Timedelta("15s")
    st = sv.start(cfg, now=ex.now, http=ex)
    assert st["ledger_start"] == t0.isoformat()
    for h in range(hours):
        ex.now = t0 + h * sv.GRID + pd.Timedelta("15s")
        sv.run_decide(cfg, now=ex.now, http=ex)
        ex.now = t0 + h * sv.GRID + BAR + pd.Timedelta("15s")
        sv.run_mark(cfg, now=ex.now, http=ex)
    return cfg, ex, t0


def test_decide_and_mark_write_the_ledger(tmp_path):
    cfg, ex, t0 = _live(tmp_path, hours=30)
    dec, marks, quotes, fund = sv.read_decisions(cfg), sv.read_marks(cfg), pd.read_csv(cfg.quotes), sv.read_funding(cfg)
    assert len(dec) == 30 * len(PAIRS) and dec["t"].nunique() == 30 and dec["t"].min() == t0
    assert set(dec["skip"]) <= {"", "no_signal", "position_open"} and (dec["skip"] == "").sum() > 5
    assert dec["f_bps"].notna().all() and (dec["model_id"] == "model_2023-05-03").all()
    assert (dec["decided_at"] < dec["t"] + BAR).all()
    taken = dec[dec["skip"] == ""]
    # one position per pair: a taken decision blocks the pair for HOLD bars (an hour here)
    for sym, d in taken.groupby("symbol"):
        assert (d["t"].diff().dropna() >= HOLD * BAR).all()
    # every taken decision has its entry mark at t + 5 min with the bar's close, and an exit mark HOLD bars later once the bar exists
    e = marks[marks["leg"] == "entry"].set_index("id")
    assert set(e.index) == set(taken["id"]) and (e["mark_t"] == e["t"] + BAR).all() and e["close"].notna().all()
    px = ex.c.assign(t=ex.c["open_time"] + BAR).set_index(["t", "symbol"])["close"]
    assert np.allclose(e["close"], [px[(r.mark_t, r.symbol)] for r in e.itertuples()])
    assert np.allclose(e["bid"], e["close"] * (1 - 1e-4)) and np.allclose(e["ask"], e["close"] * (1 + 1e-4))
    x = marks[marks["leg"] == "exit"].set_index("id")
    due = taken[taken["t"] + (1 + HOLD) * BAR <= ex.now.floor("5min")]
    assert set(x.index) == set(due["id"]) and (x["mark_t"] == x["t"] + (1 + HOLD) * BAR).all()
    # funding: −side × Σ rate over (entry, exit], the synthetic rate is 1e-4 × (pair number) every 8 h
    for r in x.itertuples():
        ev = fund[(fund["symbol"] == r.symbol) & (fund["ts"] > r.t + BAR) & (fund["ts"] <= r.mark_t)]
        assert np.isclose(r.funding_bps, -r.side * ev["rate"].sum() * 1e4)
    assert (x["funding_bps"] != 0).any()
    # quotes for every pair at every mark time
    assert len(quotes) == 30 * len(PAIRS) and quotes["mark_t"].nunique() == 30
    # health and status
    h = json.loads(cfg.health.read_text())
    assert h["taken"] == len(taken) and h["entries_marked"] == len(e) and h["exits_marked"] == len(x) and h["bars_missing_24h"] == 0
    assert h["open_positions"] == len(taken) - len(x) and h["model_id"] == "model_2023-05-03" and h["last_error"] is None
    assert "decisions" in sv.status(cfg)
    led = sv.ledger(cfg)
    assert len(led) == len(taken) and led["entry_close"].notna().all() and led["exit_close"].notna().sum() == len(x)
    # the live candle file holds exactly the bars after the seed, and a re-fetch adds nothing
    live = pd.read_parquet(cfg.live)
    assert live["open_time"].min() == t0 and live.groupby("symbol").size().nunique() == 1        # the seed ends with the bar closing at t0
    rep = sv.fetch(cfg, ex.now, ex)
    assert all(r["new"] == 0 and r["mismatch"] == 0 for r in rep.values())


def test_live_decisions_equal_the_replay_and_the_check_passes(tmp_path):
    cfg, ex, t0 = _live(tmp_path, hours=30)
    dec = sv.read_decisions(cfg)
    r = sv.check(cfg, now=ex.now)
    assert r["pass"] and r["cells_compared"] == len(dec) and r["cells_differ"] == 0 and r["taken_differ"] == 0 and r["causal_check"] == "pass"
    assert (cfg.out / "checks").exists() and json.loads(cfg.health.read_text())["last_check"]["pass"]
    # the same bars, hour by hour by a fresh scorer, agree with the persistent one used in the replay
    rp = sv.replay(cfg, ["F1"], against=None, verbose=False, models=cfg.out / "replay_models")["ledger"]
    rp = rp[(rp["t"] >= t0) & (rp["t"] <= dec["t"].max())]
    m = dec.merge(rp, on=["t", "symbol"], suffixes=("", "_rp"))
    assert len(m) == len(dec) and np.allclose(m["f_bps"], m["f_bps_rp"], equal_nan=True)


def test_a_tampered_ledger_fails_the_check(tmp_path):
    cfg, ex, t0 = _live(tmp_path, hours=8)
    dec = sv.read_decisions(cfg)
    i = dec.index[dec["skip"] == ""][0]
    dec.loc[i, "side"] = -dec.loc[i, "side"]
    dec.to_csv(cfg.decisions, index=False)
    r = sv.check(cfg, now=ex.now)
    assert not r["pass"] and r["taken_differ"] >= 1 and r["differ_rows"]


def test_a_late_decision_is_recorded_and_not_taken(tmp_path):
    cfg, ex, t0 = _live(tmp_path, hours=3)
    # the host was down for two hours: the next decide run finds three pending bars, two of them late
    ex.now = t0 + 5 * sv.GRID + pd.Timedelta("15s")
    r = sv.run_decide(cfg, now=ex.now, http=ex)
    dec = sv.read_decisions(cfg)
    assert r["pending"] == 3 and dec["t"].nunique() == 6
    late = dec[dec["t"].isin([t0 + 3 * sv.GRID, t0 + 4 * sv.GRID])]
    assert set(late["skip"]) <= {"no_signal", "late", "position_open"} and (late["skip"] == "late").sum() >= 1
    now_rows = dec[dec["t"] == t0 + 5 * sv.GRID]
    assert "late" not in set(now_rows["skip"])
    assert r["late"] == (dec["skip"] == "late").sum() and json.loads(cfg.health.read_text())["late"] == r["late"]
    # the check explains a difference at or after a late row as downtime, not as a bug
    ex.now = t0 + 6 * sv.GRID + pd.Timedelta("15s")
    c = sv.check(cfg, now=ex.now)
    assert c["taken_differ"] == 0 and c["cells_differ"] == 0, c


def test_a_stored_bar_is_never_overwritten_and_a_disagreement_is_counted(tmp_path):
    cfg, ex, t0 = _live(tmp_path, hours=2)
    # the exchange now reports a different close for a stored bar inside the re-fetched overlap (the last OVERLAP_BARS)
    t_bad = t0 + sv.GRID                          # the last bar stored so far (the runs went up to t0 + 1 h 05 m)
    ex.c.loc[(ex.c["symbol"] == "AAUSDT") & (ex.c["open_time"] + BAR == t_bad), "close"] *= 1.01
    ex.now = t0 + 2 * sv.GRID + pd.Timedelta("15s")
    rep = sv.fetch(cfg, ex.now, ex)
    assert rep["AAUSDT"]["mismatch"] == 1 and all(rep[p]["mismatch"] == 0 for p in PAIRS[1:])
    stored = sv.load_candles(cfg)
    orig = pd.read_parquet("data/candles_5m.parquet")
    o = orig[(orig["symbol"] == "AAUSDT") & (orig["open_time"] + BAR == t_bad)]["close"].iloc[0]
    assert stored[(stored["symbol"] == "AAUSDT") & (stored["open_time"] + BAR == t_bad)]["close"].iloc[0] == o
    sv.run_decide(cfg, now=ex.now, http=ex)
    assert json.loads(cfg.health.read_text())["overlap_mismatch"] == 1


def test_a_missing_bar_is_no_bar_and_the_model_refits_on_schedule(tmp_path):
    cfg, ex, t0 = _live(tmp_path, hours=2)
    # one pair's bar for the next hour is missing at the exchange
    t = t0 + 2 * sv.GRID
    ex.c = ex.c[~((ex.c["symbol"] == "FFUSDT") & (ex.c["open_time"] + BAR == t))]
    ex.now = t + pd.Timedelta("15s")
    sv.run_decide(cfg, now=ex.now, http=ex)
    dec = sv.read_decisions(cfg)
    row = dec[(dec["t"] == t) & (dec["symbol"] == "FFUSDT")].iloc[0]
    assert row["skip"] == "no_bar" and np.isnan(row["f_bps"])
    # the block schedule: F1's blocks are the harness's, then every 30 days after F1's last one for ever
    M = sv.market(sv.load_candles(cfg), PAIRS)
    assert sv.block_starts(pd.Timestamp("2023-12-31", tz="UTC"), ("F1",)) == [a for a, _ in bt.blocks("F1", pd.Timestamp("2024-01-01", tz="UTC"), 30)]
    far = sv.block_starts(pd.Timestamp("2024-06-01", tz="UTC"), ("F1",))
    assert far[-1] > pd.Timestamp("2024-05-01", tz="UTC") and (far[-1] - far[-2]) == pd.Timedelta(days=30)
    assert sv.block_start(t, cfg) == pd.Timestamp("2023-05-03", tz="UTC")
    # a bar in the next block refits (the model file appears) and is scored by the new model; the refit uses the market before the block only
    t2 = pd.Timestamp("2023-06-02 00:00", tz="UTC")
    ex.now = t2 + pd.Timedelta("15s")
    r = sv.run_decide(cfg, now=ex.now, http=ex)
    assert r["refits"] == 1 and (cfg.models / "model_2023-06-02.json").exists()
    doc = json.loads((cfg.models / "model_2023-06-02.json").read_text())
    assert pd.Timestamp(doc["data_end"]) < t2
    dec = sv.read_decisions(cfg)
    assert (dec.loc[dec["t"] == t2, "model_id"] == "model_2023-06-02").all()
