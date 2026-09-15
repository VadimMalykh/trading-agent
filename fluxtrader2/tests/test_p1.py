"""P1 unit tests on synthetic data: the ladder walk, the levels ingest, and an end-to-end `cost`
run over a few synthetic days (catches column/merge errors before a VM run)."""
import gzip
import json
import os

import numpy as np
import pandas as pd
import pytest

from ft2 import data, ladder


def test_walk_fills_across_levels():
    px = np.array([100.0, 101.0, 102.0])      # asks, best first
    qty = np.array([1.0, 1.0, 1.0])           # 100 + 101 + 102 USDT of notional
    mid = 99.5
    s = ladder.walk(px, qty, mid, [50, 150, 400])
    assert s[0] == pytest.approx((100 / 99.5 - 1) * 1e4)                 # inside the first level
    vwap = 150 / (1.0 + 50 / 101.0)                                       # one full level + half of the next
    assert s[1] == pytest.approx((vwap / 99.5 - 1) * 1e4)
    assert np.isnan(s[2])                                                 # more than the ladder holds → censored


def test_walk_bid_side_is_positive():
    s = ladder.walk(np.array([99.0, 98.0]), np.array([1.0, 1.0]), 99.5, [50, 150])
    assert s[0] == pytest.approx((1 - 99 / 99.5) * 1e4) and s[1] > s[0]


def test_summarize_row():
    bids = json.dumps([[99.0, 2.0], [98.0, 5.0]])
    asks = json.dumps([[101.0, 1.0], [102.0, 10.0]])       # 101 + 1,020 USDT: the 1k notional walks into level 2
    r = dict(zip(ladder.COLS[3:], ladder.summarize(bids, asks)))
    assert r["mid"] == 100 and r["spread_bps"] == pytest.approx(200) and r["n_bid"] == 2
    assert r["usd_ask_1"] == pytest.approx(101.0) and r["usd_ask_02"] == 0 and r["usd_bid_02"] == 0
    assert np.isnan(r[ladder.slip_col("buy", 2500)])                    # asks hold 1,121 USDT: 2.5k is censored
    assert r["bid_extent_bps"] == pytest.approx(200) and r["ask_extent_bps"] == pytest.approx(200)
    assert r[ladder.slip_col("buy", 1000)] > r["spread_bps"] / 2    # walks into the second level


def _synth(tmp_path, days=6, pairs=("AAAUSDT", "BBBUSDT")):
    os.chdir(tmp_path)
    (tmp_path / "data/raw").mkdir(parents=True)
    (tmp_path / "output").mkdir()
    rng = np.random.default_rng(0)
    t0 = pd.Timestamp("2022-12-29", tz="UTC")           # straddles TAPE_START so the proxy path is exercised
    minutes = pd.date_range(t0, periods=days * 1440, freq="min")
    c5, tape, snaps, depth, lad, fund = [], [], [], [], [], []
    for i, sym in enumerate(pairs):
        px = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 2e-4, len(minutes))))
        m = pd.DataFrame({"symbol": sym, "ts": minutes, "close": px})
        m["open"] = m["close"].shift(1).fillna(m["close"]); m["high"] = m[["open", "close"]].max(axis=1) * 1.0002
        m["low"] = m[["open", "close"]].min(axis=1) * 0.9998
        c = m.set_index("ts").resample("5min").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                                   close=("close", "last")).reset_index().rename(columns={"ts": "open_time"})
        c["symbol"], c["volume"], c["interval"] = sym, rng.uniform(10, 20, len(c)), "5m"
        c["close_time"] = c["open_time"] + pd.Timedelta("5min")
        c5.append(c)
        sp = 2.0 + i                                      # full spread in bps
        tape.append(pd.DataFrame({"symbol": sym, "ts": minutes, "n_trades": 50, "n_buy": 25, "n_sell": 25, "volume": 5.0,
                                  "buy_vol": 2.5, "sell_vol": 2.5, "notional": 5.0 * px, "vwap": px, "open": m["open"],
                                  "high": m["high"], "low": m["low"], "close": px, "ask_last": px * (1 + sp / 2e4),
                                  "bid_last": px * (1 - sp / 2e4), "eff_spread_bps": sp + rng.normal(0, 0.1, len(minutes)),
                                  "n_flips": 20, "last_ms": 0}))
        snaps.append(pd.DataFrame({"symbol": sym, "ts": minutes[-2 * 1440:] + pd.Timedelta("3s"), "mid": px[-2 * 1440:],
                                   "spread": px[-2 * 1440:] * sp / 1e4}))
        dts = pd.date_range(t0, periods=days * 2880, freq="30s")
        depth.append(pd.DataFrame({"symbol": sym, "ts": dts, "usd_m1": 1e6 * (i + 1), "usd_p1": 1e6 * (i + 1)}))
        lts = minutes[-2 * 1440:]
        rows = []
        for t, p in zip(lts, px[-2 * 1440:]):
            bids = [[round(p * (1 - sp / 2e4) * (1 - k * 1e-4), 4), 20.0 / (i + 1)] for k in range(20)]
            asks = [[round(p * (1 + sp / 2e4) * (1 + k * 1e-4), 4), 20.0 / (i + 1)] for k in range(20)]
            rows.append((sym, t.isoformat(), t.isoformat(), t.isoformat(), 1, 20, json.dumps(bids), json.dumps(asks)))
        lad += rows
        fund.append(pd.DataFrame({"symbol": sym, "ts": pd.date_range(t0, periods=days * 3, freq="8h"),
                                  "rate": rng.normal(1e-4, 5e-5, days * 3), "interval_h": 8}))
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    (tmp_path / "data/tape").mkdir()
    for t in tape:
        t.to_parquet(f"data/tape/{t['symbol'].iloc[0]}.parquet", index=False)
    pd.concat(snaps).to_parquet("data/snapshots.parquet", index=False)
    (tmp_path / "data/depth").mkdir()
    for d in depth:
        d.to_parquet(f"data/depth/{d['symbol'].iloc[0]}.parquet", index=False)
    pd.concat(fund).to_parquet("data/funding_archive.parquet", index=False)
    with gzip.open("data/raw/levels.csv.gz", "wt") as f:
        pd.DataFrame(lad, columns=["symbol", "ts", "event_time", "transaction_time", "last_update_id", "depth", "bids", "asks"]).to_csv(f, index=False)
    return list(pairs)


def test_ingest_levels_and_cost_end_to_end(tmp_path):
    pairs = _synth(tmp_path)
    r = data.ingest_levels(pairs, chunksize=1000)
    assert r["rows_out"] == 2 * 2 * 1440 and r["dups_dropped"] == 0
    lad = data.load("ladder", symbols=[pairs[0]])
    assert lad["spread_bps"].median() == pytest.approx(2.0, abs=0.05)
    assert lad[ladder.slip_col("buy", 1000)].notna().all()
    assert (lad[ladder.slip_col("buy", 250_000)].isna()).all()          # 20 levels × 20 units × ~100 USDT < 250k
    from ft2 import cost
    text = cost.run(5.0, 2.0, "test", pairs)
    assert "Round trip" in text and cost.DAILY.exists() and cost.TABLE.exists()
    d = pd.read_parquet(cost.DAILY)
    assert set(d["spread_src"]) <= {"tape", "proxy", "none"}
    tab = pd.read_parquet(cost.TABLE)
    row = tab[(tab["symbol"] == pairs[0])].iloc[0]
    assert 2 * 5 + 1.5 < row["taker_rt_1000"] < 2 * 5 + 3.5     # fees + spread (calibrated ≈ raw here) + ~0 impact
    assert 0 <= row["maker_fill_5"] <= 1
