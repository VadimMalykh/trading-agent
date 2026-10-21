"""M1's harness on planted data. Runs directly: ./scripts/m3.sh tests/test_makerpath.py
(the analysis image has no pytest)."""
import io
import os
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from m3 import makerpath as M  # noqa: E402
from m3 import execcost  # noqa: E402

NS = M.NS
T0 = pd.Timestamp("2026-08-10 12:05", tz="UTC").value


def _tape(rows):
    """rows: (seconds from T0, price, qty, buyer_maker)"""
    df = pd.DataFrame(rows, columns=["s", "price", "qty", "buyer_maker"])
    df["ts"] = T0 + (df["s"] * NS).astype(np.int64)
    df["pair"] = "XUSDT"
    return df[["pair", "ts", "price", "qty", "buyer_maker"]]


def _tape_obj(df):
    p = "/tmp/_m1_tape.parquet"
    df.to_parquet(p, index=False)
    return M.Tape.load(p)


def test_three_branch_rule_on_planted_tape():
    # touch at T: last aggressor-sell print 100.0 (bid), last aggressor-buy 100.1 (ask)
    base = [(-30, 100.0, 1.0, True), (-20, 100.1, 1.0, False)]
    T = np.array([T0])
    side = np.array([1])
    # 1. certain: a print strictly below our bid inside (T, T+60]
    tp = _tape_obj(_tape(base + [(10, 99.9, 0.5, True)]))
    bid, ask = tp.touch("XUSDT", T)
    assert bid[0] == 100.0 and ask[0] == 100.1
    agg = tp.window_agg("XUSDT", T, 60)
    fb = execcost.fill_branch(+1, np.array([100.0]), np.array([5.0]), np.array([1.0]), agg)
    assert fb["certain"][0] and fb["filled"][0] and not fb["queued"][0]
    thr, at = tp.through("XUSDT", T, 60, side, np.array([100.0]))
    assert thr[0] and at[0]
    # 2. queue-conditional: prints AT our price with enough aggressor-sell volume (Q0 + S = 6)
    tp = _tape_obj(_tape(base + [(10, 100.0, 4.0, True), (20, 100.0, 2.5, True), (30, 100.1, 9.0, False)]))
    agg = tp.window_agg("XUSDT", T, 60)
    assert agg["sell_volume"][0] == 6.5 and agg["buy_volume"][0] == 9.0 and agg["low"][0] == 100.0
    fb = execcost.fill_branch(+1, np.array([100.0]), np.array([5.0]), np.array([1.0]), agg)
    assert fb["queued"][0] and fb["filled"][0] and not fb["certain"][0]
    thr, at = tp.through("XUSDT", T, 60, side, np.array([100.0]))
    assert not thr[0] and at[0]          # the tape leg counts this as UNFILLED (branch 1 only)
    # 2b. not enough drain -> no fill
    fb = execcost.fill_branch(+1, np.array([100.0]), np.array([6.0]), np.array([1.0]), agg)
    assert not fb["filled"][0]
    # 3. nothing printed at or through -> no fill; a print after T+W does not count
    tp = _tape_obj(_tape(base + [(10, 100.1, 1.0, False), (61, 99.0, 1.0, True)]))
    agg = tp.window_agg("XUSDT", T, 60)
    fb = execcost.fill_branch(+1, np.array([100.0]), np.array([5.0]), np.array([1.0]), agg)
    assert not fb["filled"][0] and agg["n_rows"][0] == 1
    # a sell resting at the ask mirrors: a print strictly above fills
    tp = _tape_obj(_tape(base + [(10, 100.2, 1.0, False)]))
    agg = tp.window_agg("XUSDT", T, 60)
    fs = execcost.fill_branch(-1, np.array([100.1]), np.array([5.0]), np.array([1.0]), agg)
    assert fs["certain"][0]
    # a touch older than 60 s is stale
    tp = _tape_obj(_tape([(-61, 100.0, 1.0, True), (-20, 100.1, 1.0, False)]))
    bid, ask = tp.touch("XUSDT", T)
    assert np.isnan(bid[0]) and ask[0] == 100.1


def test_net_return_per_arm_equals_hand_computation_tape_leg():
    # long trade: entry T0, exit T0 + 240 min. Entry touch bid 100 / ask 100.1; exit touch bid 110 / ask 110.1.
    X = 240 * 60
    rows = [(-30, 100.0, 1.0, True), (-20, 100.1, 1.0, False),
            (10, 99.9, 1.0, True), (50, 100.1, 1.0, False),  # entry rest at 100.0 filled (print through); an ask print so the T+W touch exists
            (X - 30, 110.0, 1.0, True), (X - 20, 110.1, 1.0, False),
            (X + 30, 110.0, 1.0, True), (X + 40, 110.1, 1.0, False)]  # exit: prints only AT 110.1 in W -> unfilled on the tape leg -> cross at the T+W ask 110.1
    tp = _tape_obj(_tape(rows))
    trades = pd.DataFrame({"stratum": ["A"], "arm": ["x"], "pair": ["XUSDT"], "side": [1], "size": [1.0],
                           "entry_ts": [T0 - 5 * 60 * NS], "exit_ts": [T0 - 5 * 60 * NS + 240 * 60 * NS],
                           "entry_close": [100.05], "exit_close": [110.05]})
    trades["entry_T"] = T0
    trades["exit_T"] = T0 + X * NS
    trades["tid"] = ["t1"]
    mom = M.moments_of(trades)
    pr = M.price_all_moments(mom, None, tp, 60, 1000.0)
    tr = M.trade_returns(trades, pr)
    assert tr["kept"].all() and (tr["leg"] == "tape").all()
    taker = (110.0 / 100.1 - 1) * 1e4 - 10.0          # buy at ask, sell at bid, 5 + 5 fee
    maker = (110.0 / 100.0 - 1) * 1e4 - 2.0 - 5.0     # filled rest at 100.0 (maker fee); the exit SELL crosses late at the T+W BID 110.0 (taker fee)
    assert abs(tr["taker_ret_bps"][0] - taker) < 1e-9
    assert abs(tr["maker_ret_bps"][0] - maker) < 1e-9
    assert abs(tr["s1_bps"][0] - (maker - taker)) < 1e-9
    assert tr["entry_filled"][0] and not tr["exit_filled"][0]
    c = M.s1(tr)
    assert abs(c["diff_bps"] - (maker - taker)) < 1e-9


def test_net_return_quoted_leg_with_walk_and_queue():
    # a planted ladder: at T bid 100.0 x 5, ask 100.1 x 2 then 100.2 x 100; at T+60 the same book shifted up 0.5
    X = 240 * 60
    def row(ts_s, shift):
        d = {"symbol": "XUSDT", "ts": T0 + ts_s * NS}
        for i in range(M.LEVELS):
            d[f"b{i}p"], d[f"b{i}q"] = 100.0 - 0.1 * i + shift, 5.0 if i == 0 else 100.0
            d[f"a{i}p"], d[f"a{i}q"] = 100.1 + 0.1 * i + shift, 2.0 if i == 0 else 100.0
        return d
    wide = pd.DataFrame([row(-5, 0.0), row(55, 0.5), row(X - 5, 10.0), row(X + 55, 10.0)])
    os.makedirs("/tmp/_m1_book", exist_ok=True)
    wide.to_parquet("/tmp/_m1_book/ladder_wide20.parquet", index=False)
    book = M.Book.load("/tmp/_m1_book")
    # tape: entry window has prints AT 100.0 with 7 sold (>= Q0 5 + S 1000/100.05 ≈ 9.995? no -> plant 15)
    rows = [(-30, 100.0, 1.0, True), (-20, 100.1, 1.0, False), (10, 100.0, 15.0, True),
            (X - 30, 110.0, 1.0, True), (X - 20, 110.1, 1.0, False), (X + 10, 110.2, 1.0, False)]  # exit sell rest at 110.1: print 110.2 > 110.1 -> certain
    tp = _tape_obj(_tape(rows))
    trades = pd.DataFrame({"stratum": ["A"], "arm": ["x"], "pair": ["XUSDT"], "side": [1], "size": [1.0],
                           "entry_ts": [T0 - 5 * 60 * NS], "exit_ts": [T0 - 5 * 60 * NS + X * NS],
                           "entry_close": [100.05], "exit_close": [110.05], "entry_T": [T0], "exit_T": [T0 + X * NS], "tid": ["t1"]})
    mom = M.moments_of(trades)
    pr = M.price_all_moments(mom, book, tp, 60, 1000.0)
    tr = M.trade_returns(trades, pr)
    assert (tr["leg"] == "quoted").all() and tr["kept"].all()
    # taker entry: need 1000/100.05 = 9.995 units: 2 @100.1 then 7.995 @100.2
    need = 1000.0 / 100.05
    vwap_in = (2 * 100.1 + (need - 2) * 100.2) / need
    # taker exit at T+240: sell into bids 110.0 x 5 then 109.9: need = 1000/110.05
    need2 = 1000.0 / 110.05
    vwap_out = (5 * 110.0 + (need2 - 5) * 109.9) / need2
    taker = (vwap_out / vwap_in - 1) * 1e4 - 10.0
    # maker entry: rest at 100.0, Q0 = 5, S = 9.995, drain 15 >= 14.995 -> queued fill at 100.0 (fee 2)
    # maker exit: rest at ask 110.1, print at 110.2 strictly above -> certain fill at 110.1 (fee 2)
    maker = (110.1 / 100.0 - 1) * 1e4 - 4.0
    assert abs(tr["taker_ret_bps"][0] - taker) < 1e-9, (tr["taker_ret_bps"][0], taker)
    assert abs(tr["maker_ret_bps"][0] - maker) < 1e-9, (tr["maker_ret_bps"][0], maker)
    assert tr["entry_queued"][0] and tr["exit_certain"][0]


def test_streamed_window_extraction_keeps_exactly_the_rows_in_range():
    # a planted day file (with header) -> zip bytes -> parse -> cut to two overlapping windows
    n = 2000
    ts_ms = (T0 // 1_000_000) + np.arange(-1000, 1000) * 1000   # one print a second around T0
    csv = "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n" + "\n".join(
        f"{i},{100 + (i % 7) * 0.1:.1f},{1 + i % 3},{i},{i},{t},{'true' if i % 2 else 'false'}" for i, t in enumerate(ts_ms))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("X-aggTrades-2026-08-10.csv", csv)
    tape = M.parse_aggtrades(buf.getvalue())
    assert len(tape) == n and tape["buyer_maker"].sum() == n // 2 and tape["ts"].iloc[0] == (T0 - 1000 * NS)
    moments = np.array([T0, T0 + 200 * NS])                       # windows [T0-120, T0+360] ∪ [T0+80, T0+560]
    cut = M.cut_windows(tape, moments)
    lo, hi = T0 - 120 * NS, T0 + 560 * NS
    expect = tape[(tape["ts"] >= lo) & (tape["ts"] <= hi)]
    assert len(cut) == len(expect) == 681, (len(cut), len(expect))
    assert (cut["ts"].to_numpy() == expect["ts"].to_numpy()).all()
    # disjoint windows keep nothing in between
    cut2 = M.cut_windows(tape, np.array([T0 - 900 * NS, T0 + 600 * NS]))
    assert ((cut2["ts"] <= T0 - 540 * NS) | (cut2["ts"] >= T0 + 480 * NS)).all()
    # pair-days: a window crossing midnight names both days
    mom = pd.DataFrame({"pair": ["X"], "T": [pd.Timestamp("2026-08-10 23:59:00", tz="UTC").value]})
    pdays = M.pair_days(mom)
    assert list(pdays["day"]) == ["2026-08-10", "2026-08-11"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"{name}: ok")
