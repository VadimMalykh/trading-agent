"""OI_JOIN_AT_CLOSE — the open-interest join at the bar's close, checked without a database.

Run inside the trainer image (nothing on the host):
    docker compose --profile ml run --rm --no-deps ml_trainer python tests/test_oi_join_at_close.py

What it asserts (config.OI_JOIN_AT_CLOSE; WALKFORWARD_PROTOCOL §10.1):
  1. The knob is OFF by default, and with it off the frame is what it always was.
  2. IDENTITY: knob ON with ARCHIVE_OI_SHIFT_MIN=5 gives, on every bar of the archive era,
     exactly the `oi` / `oi_chg` / `has_funding_oi` that X8 trained on (knob off, shift 0) —
     bit for bit — and never touches another column.
  3. NO LOOKAHEAD on true-time rows (the collector's polls, i.e. serving): with the knob ON
     bar T sees the last poll at or before T + one bar and never a later one; with it OFF,
     at or before T.
  4. The unsafe combination (knob ON, archive set, archive not shifted by 5) raises.
"""
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from data import db, features  # noqa: E402

SYMBOL = "TESTUSDT"
OI_COLS = ["oi", "oi_chg", "has_funding_oi"]
BAR = pd.Timedelta(minutes=5)


def _candles(n=600, start="2026-07-01 00:00"):
    rng = np.random.default_rng(7)
    t = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
    return pd.DataFrame({
        "open_time": t, "open": close * 0.999, "high": close * 1.002, "low": close * 0.998,
        "close": close, "volume": rng.uniform(1, 10, n), "close_time": t + BAR,
    })


def _patch_db(candles, collector):
    """Everything but open interest is absent; the OI loader itself runs for real."""
    db.load_candles = lambda symbol, interval="1m", limit=None: candles.copy()
    db.load_orderbook = lambda symbol, since=None: pd.DataFrame()
    db.load_market_trades = lambda symbol, since=None: pd.DataFrame()
    db.load_funding = lambda symbol, since=None: pd.DataFrame()
    db._read_sql = lambda sql, params=None: collector.copy()


def _set(archive_path, shift, at_close):
    db.ARCHIVE_OI = archive_path
    db.ARCHIVE_OI_SHIFT_MIN = float(shift)
    db._archive_oi_cache = None
    features.OI_JOIN_AT_CLOSE = bool(at_close)


def _frame():
    return features.build_feature_frame(SYMBOL, "5m", feature_cols=features.LEGACY_FEATURE_COLS)


def test_default_off():
    from config import OI_JOIN_AT_CLOSE
    assert OI_JOIN_AT_CLOSE is False and features.OI_JOIN_AT_CLOSE is False
    print("PASS default: OI_JOIN_AT_CLOSE off")


def test_identity_with_x8(tmp_dir="/tmp"):
    candles = _candles()
    rng = np.random.default_rng(11)
    # The archive as published: label = bucket START, value = open interest at bucket END.
    labels = pd.date_range("2026-06-30 22:00", "2026-07-03 02:00", freq="5min", tz="UTC")
    labels = labels.delete([40, 41, 42, 200])          # gaps, as in the real archive
    arch = pd.DataFrame({"symbol": SYMBOL, "ts": labels,
                         "open_interest": 1e6 * np.exp(np.cumsum(rng.normal(0, 2e-3, len(labels))))})
    path = os.path.join(tmp_dir, "oi_join_test.parquet")
    arch.to_parquet(path)
    # The collector: true-time polls every 60 s from 2026-07-02 12:01:30 on.
    c0 = pd.Timestamp("2026-07-02 12:01:30", tz="UTC")
    polls = pd.date_range(c0, periods=1200, freq="60s")
    collector = pd.DataFrame({"ts": polls,
                              "open_interest": 1e6 * np.exp(np.cumsum(rng.normal(0, 5e-4, len(polls))))})
    _patch_db(candles, collector)

    _set(path, shift=0, at_close=False)
    x8 = _frame()                                       # what X8 trained on
    _set(path, shift=5, at_close=True)
    new = _frame()                                      # the registered recipe
    _set(path, shift=5, at_close=False)
    x8p = _frame()                                      # X8′

    assert list(x8.index) == list(new.index)
    era = x8.index < (c0 - 2 * BAR)                     # bars whose join never reaches a poll
    assert era.sum() > 400, era.sum()
    for c in OI_COLS:
        a, b = x8.loc[era, c].to_numpy(), new.loc[era, c].to_numpy()
        assert np.array_equal(a, b), (c, np.abs(a - b).max())
    assert float(np.abs(x8.loc[era, "oi_chg"]).sum()) > 0, "the OI columns are live in the test"
    others = [c for c in x8.columns if c not in OI_COLS]
    assert x8[others].equals(new[others]) and x8[others].equals(x8p[others])
    # X8′ is the same series one bar later — the difference the two reads measured.
    a, b = x8.loc[era, "oi"].to_numpy(), x8p.loc[era, "oi"].to_numpy()
    assert not np.array_equal(a, b)
    ok = np.ones(len(a) - 1, dtype=bool)
    ok[[i for i in range(len(a) - 1) if a[i] == 0.0 or b[i + 1] == 0.0]] = False
    assert np.array_equal(a[:-1][ok], b[1:][ok])
    os.remove(path)
    print(f"PASS identity: knob on + shift 5 == X8's rows on {int(era.sum())} archive-era bars, "
          "bit for bit; other columns untouched")


def test_no_lookahead_on_polls():
    candles = _candles(n=60, start="2026-08-01 00:00")
    t0 = pd.Timestamp("2026-08-01 00:00", tz="UTC")
    # values are chosen so that expm1(oi) identifies the poll that was read
    polls = pd.DataFrame({
        "ts": [t0 + pd.Timedelta(s, "s") for s in (-30, 200, 300, 301, 590, 905)],
        "open_interest": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    })
    _patch_db(candles, polls)

    def seen(frame, i):
        return round(float(np.expm1(frame["oi"].iloc[i])), 6)

    _set("", shift=0, at_close=True)
    on = _frame()
    # bar 00:00 closes 00:05:00 -> the poll AT 300 s is seen, the one at 301 s is not
    assert seen(on, 0) == 30.0, seen(on, 0)
    # bar 00:05 closes 00:10:00 (600 s) -> last poll at 590 s
    assert seen(on, 1) == 50.0, seen(on, 1)
    # bar 00:10 closes 00:15:00 (900 s) -> still 590 s; the 905 s poll is in the future
    assert seen(on, 2) == 50.0, seen(on, 2)
    assert seen(on, 3) == 60.0, seen(on, 3)

    _set("", shift=0, at_close=False)
    off = _frame()
    assert seen(off, 0) == 10.0 and seen(off, 1) == 30.0 and seen(off, 2) == 50.0, \
        [seen(off, i) for i in range(3)]
    assert (on["has_funding_oi"] == 1.0).all()
    print("PASS no lookahead: knob on -> last poll at or before the close; off -> before the open")


def test_refuses_unshifted_archive(tmp_dir="/tmp"):
    candles = _candles(n=60)
    labels = pd.date_range("2026-06-30 22:00", periods=100, freq="5min", tz="UTC")
    path = os.path.join(tmp_dir, "oi_join_guard.parquet")
    pd.DataFrame({"symbol": SYMBOL, "ts": labels, "open_interest": 1.0}).to_parquet(path)
    _patch_db(candles, pd.DataFrame(columns=["ts", "open_interest"]))
    _set(path, shift=0, at_close=True)
    try:
        _frame()
    except ValueError as e:
        assert "lookahead" in str(e), e
    else:
        raise AssertionError("knob on with an unshifted archive must raise")
    finally:
        os.remove(path)
        _set("", shift=0, at_close=False)
    print("PASS guard: knob on + unshifted archive is refused")


if __name__ == "__main__":
    test_default_off()
    test_identity_with_x8()
    test_no_lookahead_on_polls()
    test_refuses_unshifted_archive()
    print("PASS test_oi_join_at_close")
