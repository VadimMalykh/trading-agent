"""BOOK_WAVE2_PLAN §S1 — X23 on planted data, before any real bar is read.

Runs directly: `./scripts/m3.sh tests/test_bookfilter.py` (no pytest in `ml_analysis`).
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import bookfilter as B  # noqa: E402
from m3 import forward as F  # noqa: E402

NS_MIN = 60 * 1_000_000_000
T0 = pd.Timestamp("2026-08-01 00:00", tz="UTC")


def _booked(n: int = 40, seed: int = 1) -> pd.DataFrame:
    """Trades with decision scalars on two pairs whose spread scales differ by 100x."""
    rng = np.random.default_rng(seed)
    pair = np.where(np.arange(n) % 2 == 0, "AUSDT", "BUSDT")
    scale = np.where(pair == "AUSDT", 1.0, 100.0)
    t = pd.DataFrame({
        "seed": np.where(np.arange(n) % 3 == 0, "s1", np.where(np.arange(n) % 3 == 1, "s2", "s3")),
        "pair": pair,
        "side": rng.choice([-1.0, 1.0], n),
        "entry_ts": (T0.value + np.arange(n) * 240 * NS_MIN).astype(np.int64),
        "size": 1.0,
        "signed_ret": rng.normal(0, 0.01, n),
        "spread_bps": rng.uniform(0.5, 1.5, n) * scale,
        "imbalance": rng.uniform(-1, 1, n),
        "depth_near_imb": rng.uniform(-1, 1, n),
    })
    ref = pd.DataFrame({"pair": np.repeat(["AUSDT", "BUSDT"], 1000),
                        "spread_bps": np.concatenate([np.linspace(0.5, 1.5, 1000),
                                                      np.linspace(50, 150, 1000)])})
    return B.with_keys(B.frame(t), ref)


def test_arms_partition_and_signs():
    t = _booked()
    ok, msg = B.check_partition(t)
    assert ok, msg
    a, b = B.split(t, "imb_with")
    assert (a["imb_signed"] > 0).all() and not (b["imb_signed"] > 0).any()
    assert len(a) + len(b) == len(t)
    # the sign is the trade's: a long on a bid-heavy book and a short on an ask-heavy one both "with"
    t2 = t.copy()
    t2.loc[:, "side"] = -1.0
    t2.loc[:, "imbalance"] = -0.3
    t2 = B.with_keys(t2.drop(columns=["imb_signed", "near_signed", "spread_pct"]),
                     pd.DataFrame({"pair": ["AUSDT", "BUSDT"], "spread_bps": [1.0, 100.0]}))
    assert (B.split(t2, "imb_with")[0].shape[0] == len(t2))
    # zero never agrees: it lands in "against"
    t2.loc[:, "imb_signed"] = 0.0
    assert B.split(t2, "imb_with")[0].empty and len(B.split(t2, "imb_against")[0]) == len(t2)


def test_spread_percentile_is_within_pair():
    t = _booked()
    # a 1.0 spread is the median of AUSDT's reference (0.5..1.5) but far below BUSDT's (50..150)
    probe = pd.DataFrame({"pair": ["AUSDT", "BUSDT", "BUSDT"], "spread_bps": [1.0, 1.0, 100.0]})
    ref = pd.DataFrame({"pair": np.repeat(["AUSDT", "BUSDT"], 1000),
                        "spread_bps": np.concatenate([np.linspace(0.5, 1.5, 1000),
                                                      np.linspace(50, 150, 1000)])})
    pct = B.pair_percentile(probe, ref)
    assert abs(pct[0] - 0.5) < 0.01 and pct[1] == 0.0 and abs(pct[2] - 0.5) < 0.01
    assert ((t["spread_pct"] >= 0) & (t["spread_pct"] <= 1)).all()
    lo, hi = B.split(t, "spread_lo")
    assert abs(len(lo) - len(hi)) <= len(t) // 4        # roughly a median split on each pair's own scale


def test_verdict_rule():
    tab = pd.DataFrame({"arm": ["a", "b", "c"], "in − out": [10.0, 30.0, 20.0],
                        "lo": [-5.0, 2.0, 1.0], "hi": [25.0, 58.0, 39.0],
                        "median seed": [1.0, 5.0, -1.0]})
    arm, passed, _ = B.verdict(tab)
    assert arm == "b" and passed
    tab.loc[1, "lo"] = -1.0                           # the best arm's interval touches zero
    arm, passed, _ = B.verdict(tab)
    assert arm == "b" and not passed
    tab.loc[1, "lo"], tab.loc[1, "median seed"] = 2.0, -0.5    # clear of zero, median seed negative
    assert not B.verdict(tab)[1]


def _ledger(n: int = 200, planted: bool = True, late_snapshot: bool = False,
            days: int = 25) -> tuple[str, str]:
    """A fifth-start-shaped ledger (policy + explore_cov05 arms) and its book_at_bars export,
    written to a temp dir. Planted: a trade whose top-20 imbalance leans its way earns +100
    net per notional, otherwise −100 (plus noise)."""
    rng = np.random.default_rng(23)
    d = tempfile.mkdtemp()
    pairs = np.array(["BTCUSDT", "ETHUSDT", "ADAUSDT"])
    rows, bars = [], []
    start = pd.Timestamp("2026-10-22 00:00", tz="UTC")           # after the bar-key change
    per_day = int(np.ceil(n / days))
    k = 0
    for day in range(days):
        for j in range(per_day):
            if k >= n:
                break
            entry = start + pd.Timedelta(days=day, minutes=5 * (j * 50 + 1))
            pair = pairs[k % 3]
            side = int(rng.choice([-1, 1]))
            imb = float(rng.uniform(-1, 1))
            signed = side * imb
            net = (100.0 if signed > 0 else -100.0) if planted else 0.0
            net += float(rng.normal(0, 20))
            snap = entry + pd.Timedelta(minutes=5) - pd.Timedelta(seconds=3)
            inserted = entry + pd.Timedelta(minutes=5, seconds=45)
            if late_snapshot and k == 7:
                snap = inserted + pd.Timedelta(seconds=1)
            for arm in ("policy", "explore_cov05"):
                rows.append({"id": len(rows) + 1, "arm": arm, "pair": pair, "side": side, "size": 1.0,
                             "entry_ts": entry.strftime("%Y-%m-%d %H:%M:%S"),
                             "exit_after_ts": (entry + pd.Timedelta(minutes=240)).strftime("%Y-%m-%d %H:%M:%S"),
                             "exit_ts": (entry + pd.Timedelta(minutes=240)).strftime("%Y-%m-%d %H:%M:%S"),
                             "entry_price": 100.0, "exit_price": 100.0, "net_bps": net, "status": "closed",
                             "confidence": 0.6 if arm == "policy" else 0.56,
                             "threshold": F.CUTS[0.02] if arm == "policy" else F.EXT_CUT,
                             "regime": 0.01, "ladder_p80": F.LADDER_P80, "checkpoint": "x8pp_s3",
                             "inserted_at": inserted.strftime("%Y-%m-%d %H:%M:%S")})
            # a lookahead plant: the export's age column says "fine" while the snapshot's own
            # timestamp is after the row was written — only the known-at check can catch it
            age = 3.0 if (late_snapshot and k == 7) else (entry + pd.Timedelta(minutes=5) - snap).total_seconds()
            bars.append({"pair": pair, "bar_ts": entry.strftime("%Y-%m-%d %H:%M:%S"),
                         "snap_ts": snap.strftime("%Y-%m-%d %H:%M:%S.%f"),
                         "age_s": age,
                         "spread_bps": float(rng.uniform(0.5, 1.5)), "imbalance": imb,
                         "depth_near_imb": float(rng.uniform(-1, 1))})
            k += 1
    lp, bp = os.path.join(d, "paper_trades.csv"), os.path.join(d, "book_at_bars.csv")
    pd.DataFrame(rows).to_csv(lp, index=False)
    pd.DataFrame(bars).to_csv(bp, index=False)
    return lp, bp


def _capture(fn, *a, **kw) -> tuple[int, str]:
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **kw)
    return rc, buf.getvalue()


def test_confirm_refuses_before_the_200th_trade():
    lp, bp = _ledger(n=150)
    rc, out = _capture(B.confirm, lp, bp, "imb_with")
    assert rc == 2 and "refusing" in out and "150 now" in out


def test_confirm_reads_a_planted_filter():
    lp, bp = _ledger(n=200, planted=True)
    rc, out = _capture(B.confirm, lp, bp, "imb_with")
    assert rc == 0, out
    assert "look #1 of 2" in out
    assert "harness check 2 (known-at): PASS" in out
    assert "CONFIRMED" in out and "NOT CONFIRMED" not in out.split("ARM explore_cov05")[0]
    # the opposite orientation of the same key reads the mirror image
    rc, out2 = _capture(B.confirm, lp, bp, "imb_against")
    assert "NOT CONFIRMED" in out2.split("ARM explore_cov05")[0]
    # a null plant: nothing confirms
    lp0, bp0 = _ledger(n=200, planted=False)
    rc, out3 = _capture(B.confirm, lp0, bp0, "imb_with")
    assert rc == 0 and "NOT CONFIRMED at look #1" in out3 and "second look at 400" in out3


def test_confirm_voids_on_a_lookahead_snapshot():
    lp, bp = _ledger(n=200, planted=True, late_snapshot=True)
    rc, out = _capture(B.confirm, lp, bp, "imb_with")
    assert rc == 3 and "known-at): FAIL" in out and "VOID" in out
    assert "CONFIRMED" not in out.split("ARM explore_cov05")[0].replace("NOT CONFIRMED", "")


def test_decision_scalars_join_the_bar_after_the_entry_bar():
    """On the dumps the decision instant is entry_ts + 5 min: the 5m row AT that instant."""
    t0 = T0.value
    book5 = pd.DataFrame({"pair": ["XUSDT"] * 3, "ts": [t0, t0 + 5 * NS_MIN, t0 + 10 * NS_MIN],
                          "has_book": [1, 1, 0], "spread_bps": [1.0, 2.0, 3.0],
                          "imbalance": [0.1, 0.2, 0.3], "depth_near_imb": [0.0, 0.5, 0.9]})
    trades = pd.DataFrame({"pair": ["XUSDT", "XUSDT"], "entry_ts": [t0, t0 + 5 * NS_MIN],
                           "side": [1.0, 1.0], "size": [1.0, 1.0], "signed_ret": [0.0, 0.0]})
    j = B.decision_scalars(trades, book5)
    assert j.loc[0, "spread_bps"] == 2.0 and j.loc[0, "has_book"]
    assert not j.loc[1, "has_book"]                      # the row at +10 has no book


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
