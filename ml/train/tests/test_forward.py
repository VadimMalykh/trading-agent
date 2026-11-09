"""M3_5_INTEGRATION §4.3 — R5's counterfactual on planted rows, in the ledger's own units.

The ledger books `gross_bps = side · ret · size · 1e4` and `net_bps = gross_bps − cost · size`
(ledger.ex `close_trade`). R5 must (i) leave an unextended trade's booked net untouched and
(ii) re-price an extended trade as size × (raw return to the later bar − cost). Found
2026-11-09 at reading #2: the unextended branch multiplied the booked gross by size again.

Runs directly: `./scripts/m3.sh tests/test_forward.py` (no pytest in `ml_analysis`).
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import forward as F  # noqa: E402

T0 = pd.Timestamp("2026-10-07 00:00", tz="UTC")
H = pd.Timedelta(minutes=240)
COST = 12.0


def _trade(i, pair, size, entry, exit_, side=1, entry_off_h=0):
    e = T0 + pd.Timedelta(hours=entry_off_h)
    raw = side * (exit_ / entry - 1.0) * 1e4
    gross = raw * size
    return {"id": i, "arm": "policy", "pair": pair, "side": side, "size": size,
            "entry_ts": e, "exit_after_ts": e + H, "exit_ts": e + H, "entry_price": entry,
            "exit_price": exit_, "gross_bps": gross, "cost_bps": COST, "net_bps": gross - COST * size,
            "status": "closed", "confidence": 0.6, "threshold": F.CUTS[F.SERVED_COVERAGE], "regime": 0.01,
            "checkpoint": "ck", "ladder_p80": F.LADDER_P80}


def _bar(pair, ts, side, conf, price):
    return {"pair": pair, "bar_ts": ts, "horizon_m": 240, "confidence": conf, "side": side,
            "price": price, "gated": False, "regime": 0.01}


def _run(trades, bars):
    with tempfile.TemporaryDirectory() as d:
        lp, bp = os.path.join(d, "l.csv"), os.path.join(d, "b.csv")
        pd.DataFrame(trades).to_csv(lp, index=False)
        pd.DataFrame(bars).to_csv(bp, index=False)
        led, b = F.load(lp), F.load_bars(bp)
    with contextlib.redirect_stdout(io.StringIO()):
        return led.arm(F.ARM_POLICY), F.reading_extension(led, b)


def test_unextended_trades_keep_their_booked_net():
    # Sized 5/3 and 4/3 trades, the signal gone at the exit bar: the counterfactual arm IS the
    # recorded arm, row for row, so the contrast is exactly zero.
    trades = [_trade(1, "AUSDT", 5 / 3, 100.0, 101.0), _trade(2, "BUSDT", 4 / 3, 50.0, 49.0, side=-1)]
    bars = [_bar("AUSDT", T0 + H, side=-1, conf=0.9, price=101.0),      # opposite side
            _bar("BUSDT", T0 + H, side=-1, conf=0.3, price=49.0),       # same side, under the cut
            _bar("AUSDT", T0 + 2 * H, 1, 0.9, 102.0), _bar("BUSDT", T0 + 2 * H, -1, 0.9, 48.0)]
    p, cf = _run(trades, bars)
    assert len(cf) == 2 and (cf["extensions"] == 0).all()
    assert abs(cf["net_bps"].sum() - p["net_bps"].sum()) < 1e-9, (cf["net_bps"].sum(), p["net_bps"].sum())
    assert abs(cf["net_bps"].iloc[0] - (5 / 3) * (100.0 - COST)) < 1e-9   # +100 bps raw, booked once


def test_extended_trade_is_repriced_in_the_ledgers_units():
    # One 5/3 trade, +100 bps at the timer; the exit bar persists above the cut and the bar
    # 240 m later is at +200 bps: net = 5/3 × (200 − cost), one extension.
    trades = [_trade(1, "AUSDT", 5 / 3, 100.0, 101.0)]
    bars = [_bar("AUSDT", T0 + H, 1, F.EXT_CUT + 0.01, 101.0),
            _bar("AUSDT", T0 + 2 * H, 1, 0.2, 102.0),
            _bar("AUSDT", T0 + 3 * H, 1, 0.9, 110.0)]            # not reached: 2nd bar under the cut
    p, cf = _run(trades, bars)
    assert len(cf) == 1 and int(cf["extensions"].iloc[0]) == 1
    assert abs(cf["net_bps"].iloc[0] - (5 / 3) * (200.0 - COST)) < 1e-9
    assert abs((cf["net_bps"].sum() - p["net_bps"].sum()) - (5 / 3) * 100.0) < 1e-9


def test_swallowed_trade_leaves_the_arm():
    trades = [_trade(1, "AUSDT", 1.0, 100.0, 101.0), _trade(2, "AUSDT", 1.0, 101.0, 100.0, entry_off_h=5)]
    bars = [_bar("AUSDT", T0 + H, 1, 0.9, 101.0), _bar("AUSDT", T0 + 2 * H, 1, 0.2, 103.0)]
    p, cf = _run(trades, bars)
    assert len(p) == 2 and len(cf) == 1
    assert abs(cf["net_bps"].iloc[0] - (300.0 - COST)) < 1e-9


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
