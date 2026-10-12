"""R39 unit tests for the trade-level maker cost (`ft2/makercost.py`): the FIFO fill rule (the queue ahead consumed by same-side trades at
the level, a sweep beyond the level, the other side's trades not counting, a partial), the touch parsed from a raw ladder row, the sign of
the drift, and an end-to-end run on made-up trades, ladders, tape parts and candles that reproduces its own tape and prices a known book."""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import makercost as mc
from ft2.ceiling import BAR

SYM = "AAAUSDT"
DAY = pd.Timestamp("2026-08-15", tz="UTC")


def test_fill_time_fifo_sweep_sides_and_partial():
    t = np.arange(10)
    price = np.array([100.0, 100.0, 100.1, 100.0, 99.9, 100.0, 100.0, 100.0, 100.0, 100.0])
    qty = np.array([30.0, 30.0, 500.0, 50.0, 1.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    sell = np.array([True, True, False, True, True, True, True, True, True, True])
    # a buy at 100 with 50 ahead and 100 own: sells at 100 cumulate 30, 60, 110 (index 3) < 150 → the sweep at index 4 (a print below) fills it
    i, partial, traded = mc.fill_time(t, price, qty, sell, "buy", 100.0, 50.0, 100.0)
    assert i == 4 and not partial and traded == 160.0
    # with 20 ahead and 40 own: the queue (60) is reached at index 1 → filled there, before the sweep
    assert mc.fill_time(t, price, qty, sell, "buy", 100.0, 20.0, 40.0)[0] == 1
    # the buy's own side (buys at 100) does not consume its queue: the trade at index 2 is a buy, at 100.1, and counts for nothing
    assert mc.fill_time(t[:4], price[:4], qty[:4], sell[:4], "buy", 100.0, 100.0, 50.0)[0] == -1 and mc.fill_time(t[:4], price[:4], qty[:4], sell[:4], "buy", 100.0, 100.0, 50.0)[1]   # partial: 110 ≥ 100 ahead, < 150
    # a sell at 100.1 with 100 ahead: buys at 100.1 cumulate 500 at index 2 ≥ 100 + 50 → filled at 2; with 1,000 ahead, no sweep above → not filled, partial False
    assert mc.fill_time(t, price, qty, sell, "sell", 100.1, 100.0, 50.0)[0] == 2
    k, p, _ = mc.fill_time(t, price, qty, sell, "sell", 100.1, 1000.0, 50.0)
    assert k == -1 and not p
    # a sell at 100.0 is swept by a print above (index 2 at 100.1)
    assert mc.fill_time(t, price, qty, sell, "sell", 100.0, 1e9, 50.0)[0] == 2
    # nothing after the placement
    assert mc.fill_time(t[:0], price[:0], qty[:0], sell[:0], "buy", 100.0, 1.0, 1.0) == (-1, False, 0.0)


def test_the_touch_is_the_first_level_of_the_json_ladder(tmp_path):
    rows = pd.DataFrame({"symbol": [SYM, SYM, "BBBUSDT"], "ts": ["2026-08-15T00:00:03.100000+00:00", "2026-08-15T00:00:15.200000+00:00", "2026-08-15T00:00:03.100000+00:00"],
                         "event_time": [""] * 3, "bids": ['[[99.9, 12.5], [99.8, 100.0]]', '[["99.95", "3.0"], ["99.9", "9"]]', "[]"], "asks": ['[[100.1, 7.0], [100.2, 20.0]]', '[[100.15, 1.5]]', "[]"]})
    src = tmp_path / "levels.csv.gz"
    rows.to_csv(src, index=False, compression="gzip")
    tch = mc.load_touch(DAY, [SYM, "BBBUSDT"], src=src)
    a = tch[tch["symbol"] == SYM].reset_index(drop=True)
    assert list(a["bid"]) == [99.9, 99.95] and list(a["bid_qty"]) == [12.5, 3.0] and list(a["ask"]) == [100.1, 100.15] and list(a["ask_qty"]) == [7.0, 1.5]
    assert a["ts"].dt.tz is not None and a["ts"].iloc[1] > a["ts"].iloc[0]
    b = tch[tch["symbol"] == "BBBUSDT"]
    assert len(b) == 1 and np.isnan(b["bid"].iloc[0])                                     # an empty ladder → NaN, skipped later


def _world(tmp_path, swept_minutes=(5, 25), days=2):
    """A name quoted 100.00 / 100.10 all day (the touch 50 units a side), one trade a second: sells at the bid of 0.4 units (the queue of 50
    plus a 100-unit order takes 150 units: 375 s — so a buy never completes by the queue alone within 15 min? it does: 900 s × 0.4 = 360
    ≥ 150), buys at the ask likewise; and at `swept_minutes` of every hour a print at 99.90 (a sweep of the bid). The mid is constant, so
    every drift is zero; the tape parts, the ladder parquet, the candles and the cost rows are written to match."""
    root = Path("data/raw/external/binance/aggTrades") / SYM
    root.mkdir(parents=True)
    Path("data/raw/levels").mkdir(parents=True)
    Path("data/tape/parts").joinpath(SYM).mkdir(parents=True)
    Path("data/ladder").mkdir(parents=True)
    rng = np.random.default_rng(0)
    lad, c5, cd = [], [], []
    for n in range(days):
        day = DAY + pd.Timedelta(days=n)
        t = pd.date_range(day, day + pd.Timedelta(days=1) - pd.Timedelta("1s"), freq="1s")
        sec = (t - day).total_seconds().to_numpy().astype(int)
        sell = (sec % 2 == 0)
        price = np.where(sell, 100.0, 100.1)
        qty = np.full(len(t), 0.4)
        minute = (sec // 60) % 60
        sweep = np.isin(minute, swept_minutes) & (sec % 60 == 1)
        price = np.where(sweep, 99.9, price); sell = sell | sweep
        tr = pd.DataFrame({"agg_trade_id": np.arange(len(t)), "price": price, "quantity": qty, "first_trade_id": 0, "last_trade_id": 0,
                           "transact_time": (t.astype("int64") // 1_000_000), "is_buyer_maker": sell})
        buf = io.StringIO(); tr.to_csv(buf, index=False)
        with zipfile.ZipFile(root / f"{SYM}-aggTrades-{day:%Y-%m-%d}.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{SYM}-aggTrades-{day:%Y-%m-%d}.csv", buf.getvalue())
        (root / f"{SYM}-aggTrades-{day:%Y-%m-%d}.zip.ok").touch()
        # the tape part: per minute, volume and n_trades (what the trades must reproduce)
        m = tr.assign(ts=pd.to_datetime((tr["transact_time"] // 60_000) * 60_000, unit="ms", utc=True)).groupby("ts").agg(volume=("quantity", "sum"), n_trades=("quantity", "size")).reset_index()
        m.assign(symbol=SYM).to_parquet(f"data/tape/parts/{SYM}/{day:%Y-%m-%d}.parquet", index=False)
        # the ladder: a snapshot every 12 s, the touch 50 a side
        ts = pd.date_range(day, day + pd.Timedelta(days=1) - pd.Timedelta("1s"), freq="12s")
        lv = pd.DataFrame({"symbol": SYM, "ts": ts.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"), "event_time": "", "transaction_time": "", "last_update_id": 0, "depth": 100,
                           "bids": '[[100.0, 50.0], [99.9, 500.0]]', "asks": '[[100.1, 50.0], [100.2, 500.0]]'})
        d = Path("data/raw/levels") / f"{day:%Y-%m-%d}"; d.mkdir()
        lv.to_csv(d / "levels.csv.gz", index=False, compression="gzip")
        lad.append(pd.DataFrame({"symbol": SYM, "ts": ts, "mid": 100.05, "slip_buy_10000": 5.0 + 0.5, "slip_sell_10000": 5.0 + 0.5}))
        t5 = pd.date_range(day, day + pd.Timedelta(days=1) - BAR, freq="5min")
        c5.append(pd.DataFrame({"symbol": SYM, "open_time": t5 - BAR, "high": 100.1, "low": 100.0, "close": 100.05 + rng.normal(0, 0.001, len(t5))}))
        cd.append(pd.DataFrame({"symbol": [SYM], "day": [day], "spread_cal_bps": [10.0], "imp_10000": [0.5], "maker_fill_15": [0.95], "maker_adv_15": [-1.5]}))
    pd.concat(lad).to_parquet(f"data/ladder/{SYM}.parquet", index=False)
    pd.concat(c5).to_parquet("data/candles_5m.parquet", index=False)
    pd.concat(cd).to_parquet("data/cost_daily.parquet", index=False)


def test_end_to_end_prices_a_known_book_and_reproduces_its_tape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _world(tmp_path)
    md = mc.run("2026-08-15", "2026-08-16", [SYM], name="t")
    out = mc.OUT / "t"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["reproduction"]["max_abs_d_volume"] <= 1e-6 and v["reproduction"]["max_d_trades"] == 0 and v["ladder_cover"][SYM] > 0.99
    s = pd.read_csv(out / "summary.csv").iloc[0]
    # every order fills within 15 min: a buy by the queue (150 units of sells at 0.4 every other second → 750 s) or by the hour's sweeps; a sell by the queue (750 s)
    assert s["fill_share"] > 0.99 and s["partial_share"] < 0.01 and 700 < s["t_fill_median_s"] < 800 and abs(s["queue_x_median"] - 0.5) < 1e-3   # the sell at 100.1 has q 99.9; 150 units of sells at 0.4 every 2 s → 750 s; the last bars of the last day see no next-day trades
    # the mid never moves: the drift against the resting price is the half-spread earned (+5 bps), so a leg costs 2.0 − 5.0 = −3.0 and the round trip −6.0
    assert abs(s["adv_filled_mean_bps"] - 5.0) < 0.01 and abs(s["eff_rt_bps"] - (-6.0)) < 0.2 and abs(s["eff_rt_with_missed_bps"] - s["eff_rt_bps"]) < 1e-9
    # the harness's maker: resting at the 5m close (≈ the mid) it is 'filled' when a later bar's low (100.0) trades strictly through — always, for a buy; its adv is ~0
    assert s["h_fill_share"] > 0.95 and abs(s["h_adv_filled_mean_bps"]) < 1.0 and abs(s["h_eff_rt_bps"] - 4.0) < 1.0
    assert s["p1_fill_15"] == 0.95 and abs(s["p1_rt_15"] - 7.0) < 1e-9 and s["sentence"] == "OPEN"
    p = pd.read_parquet(out / "placements.parquet")
    assert len(p) == 2 * 288 * 2 and (p["swept"][p["side"] == "sell"] == False).all()                               # noqa: E712  — nothing prints above the ask
    assert (p[(p["side"] == "buy") & p["swept"]]["t_fill_s"] <= 10 * 60 + 2).all()                                  # the sweeps at minutes 5 and 25: at most ten minutes from a placement
    assert "**PASS**" in md and "## Per name" in md and (out / "by_hour.csv").exists() and (out / "by_queue.csv").exists()


def test_a_missing_trade_file_voids_the_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _world(tmp_path, days=1)
    with pytest.raises(SystemExit) as e:
        mc.run("2026-08-15", "2026-08-16", [SYM], name="t2")              # the second day's file is not there
    assert e.value.code == 2
    v = json.loads((mc.OUT / "t2" / "validity.json").read_text())
    assert v["status"] == "FAIL" and len(v["trades_files_missing"]) == 1 and "VOID" in (mc.OUT / "t2" / "makercost.md").read_text()
