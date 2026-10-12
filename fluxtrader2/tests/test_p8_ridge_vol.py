"""R38 unit tests for the ridge's vol gate (`forecast.RidgeBook(q_vol=…)`): the default is R14 bit for bit (the same decisions, the same
`params()`); with a gate the rule trades a subset of the ungated rule's cells — those whose realised 4h volatility is at or above the
pair's quantile taken over the window BEFORE the block — with the same sides and sizes and a larger mean move; the cut is refitted per
block from pre-block rows only."""
import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import forecast as fc
from ft2.ceiling import W

from test_p5_forecast import HOLD, PAIRS, _synth

KEY = ["t", "symbol", "side", "size"]


def _dec(r):
    d = r["decisions"]
    return d[d["accepted"]][KEY].sort_values(["t", "symbol"]).reset_index(drop=True)


def test_the_default_is_r14_bit_for_bit(tmp_path):
    _synth(tmp_path)
    a = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2)
    b = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2, q_vol=None)
    assert a.params() == b.params() and "q_vol" not in a.params() and "vol_window_days" not in a.params() and a.q_vol is None and a.vol_window_days is None
    ra = bt.run(a, PAIRS, ["F1"], draws=1, refit_days=15, execs=("taker",), name="ungated")
    rb = bt.run(b, PAIRS, ["F1"], draws=1, refit_days=15, execs=("taker",), name="ungated_explicit")
    pd.testing.assert_frame_equal(_dec(ra), _dec(rb))
    assert len(_dec(ra)) > 200


def test_the_gate_trades_the_volatile_subset_with_a_cut_from_before_the_block(tmp_path):
    _synth(tmp_path)
    g = fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2, q_vol=0.7, vol_window_days=20)
    assert g.params()["q_vol"] == 0.7 and g.params()["vol_window_days"] == 20
    rg = bt.run(g, PAIRS, ["F1"], draws=1, refit_days=15, execs=("taker",), name="gated")
    ru = bt.run(fc.RidgeBook(hold=HOLD, min_bps=2.0, groups=2, min_pairs=2), PAIRS, ["F1"], draws=1, refit_days=15, execs=("taker",), name="ungated")
    dg, du = _dec(rg), _dec(ru)
    assert 20 < len(dg) < 0.6 * len(du)
    merged = dg.merge(du, on=["t", "symbol"], how="left", suffixes=("", "_u"))
    assert merged["side_u"].notna().all() and (merged["side"] == merged["side_u"]).all() and np.allclose(merged["size"], merged["size_u"])   # a subset, same sides and sizes
    # the cut: the pair's 0.7 quantile of its trailing-4h sd over the 20 days before the block, from pre-block rows only
    M = bt.market(PAIRS, bt.folds.bounds("F1")[1])
    v = (np.log(M.close).diff() * 1e4).rolling(W["4h"], min_periods=int(W["4h"] * 0.8)).std()
    blocks = bt.blocks("F1", M.index[-1], 15)
    for ba, bb in blocks:
        win = v.loc[ba - pd.Timedelta(days=20):ba - bt.BAR]
        cut = win.quantile(0.7)
        inb = dg[(dg["t"] >= ba) & (dg["t"] < bb)]
        if inb.empty:
            continue
        vv = v.to_numpy()[M.index.get_indexer(inb["t"]), M.columns.get_indexer(inb["symbol"])]
        assert (vv >= cut.reindex(inb["symbol"]).to_numpy() - 1e-9).all()
        # and at least one ungated cell of the block sits UNDER the cut (the gate did something here)
        inu = du[(du["t"] >= ba) & (du["t"] < bb)]
        vu = v.to_numpy()[M.index.get_indexer(inu["t"]), M.columns.get_indexer(inu["symbol"])]
        assert (vu < cut.reindex(inu["symbol"]).to_numpy()).any()
    # (the premise — the gated cells move more — is a described row of R38 on the real bars: this world's volatility is constant, so there is nothing to pick)
