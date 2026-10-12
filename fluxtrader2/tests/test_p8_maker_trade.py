"""R40 unit tests for the `maker_trade` execution: the old executions are untouched (their fills on a made-up market are identical whether or
not the constants file exists), the new leg's fee and cost are the constants' arithmetic on every leg to 1e-9 (fee = p·2 + (1−p)·5, cost =
p·(−adv) + (1−p)·slip, at the bar's close with no wait), a name without a row is unpriced, the frozen csv equals R39's summary on its columns,
and the CLI accepts the exec."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import backtest as bt

from test_p3 import HOLD, PAIRS, Planted, _synth


def _costs(tmp_path, monkeypatch, rows: dict | None):
    """Point the harness at a made-up constants file (or at none)."""
    if rows is None:
        monkeypatch.setattr(bt, "MAKER_TRADE", tmp_path / "none.csv")
    else:
        p = tmp_path / "mt.csv"
        pd.DataFrame({"symbol": list(rows), "window": "test", "fill_share": [r[0] for r in rows.values()], "adv_filled_mean_bps": [r[1] for r in rows.values()],
                      "slip15_mean_bps": [r[2] for r in rows.values()]}).to_csv(p, index=False)
        monkeypatch.setattr(bt, "MAKER_TRADE", p)


def test_the_old_execs_are_untouched_and_the_new_leg_is_the_constants_arithmetic(tmp_path, monkeypatch):
    _synth(tmp_path)
    rows = {"AAAUSDT": (0.9, -1.5, 0.5), "BBBUSDT": (0.8, -3.0, 2.0), "CCCUSDT": (0.95, -1.0, 0.1)}       # DDDUSDT has no row
    _costs(tmp_path, monkeypatch, None)
    r0 = bt.run(Planted(), PAIRS, ["F1"], draws=1, execs=("taker", "maker", "maker_ev"), name="without")
    _costs(tmp_path, monkeypatch, rows)
    r1 = bt.run(Planted(), PAIRS, ["F1"], draws=1, execs=("taker", "maker", "maker_ev", "maker_trade"), name="with")
    for e in ("taker", "maker", "maker_ev"):
        pd.testing.assert_frame_equal(r0["fills"][e].reset_index(drop=True), r1["fills"][e].reset_index(drop=True))     # bit for bit
    f = r1["fills"]["maker_trade"]
    ev = r1["fills"]["maker_ev"]
    assert len(f) == len(ev) and (f["id"].to_numpy() == ev["id"].to_numpy()).all()
    assert np.allclose(f["entry_px"], ev["entry_px"]) and np.allclose(f["exit_px"], ev["exit_px"]) and np.allclose(f["gross_bps"], ev["gross_bps"], equal_nan=True)   # the same prices, no wait
    for sym, (p, adv, slip) in rows.items():
        g = f[f["symbol"] == sym].dropna(subset=["net_bps"])
        r = g["exit_px"] / g["entry_px"]
        leg_fee, leg_other = p * 2.0 + (1 - p) * 5.0, p * -adv + (1 - p) * slip
        assert np.allclose(g["fee_bps"], leg_fee * (1 + r), atol=1e-9) and np.allclose(g["other_cost_bps"], leg_other * (1 + r), atol=1e-9) and np.allclose(g["p_fill"], p)
        assert np.allclose(g["net_bps"], g["gross_bps"] - g["fee_bps"] - g["other_cost_bps"] + g["funding_bps"], atol=1e-9)
    d = f[f["symbol"] == "DDDUSDT"]
    assert len(d) > 0 and d["net_bps"].isna().all() and d["fee_bps"].isna().all()                                       # no row → unpriced
    res = r1["results"]
    assert set(res["exec"]) == {"taker", "maker", "maker_ev", "maker_trade"}
    mt = res[(res["exec"] == "maker_trade") & (res["scope"] == "all")].iloc[0]
    assert mt["unpriced"] >= len(d) and np.isfinite(mt["net"])
    assert "maker_trade" in (r1["dir"] / "report.md").read_text()


def test_without_the_constants_the_exec_refuses_and_the_others_do_not_need_it(tmp_path, monkeypatch):
    _synth(tmp_path)
    _costs(tmp_path, monkeypatch, None)
    M = bt.market(PAIRS, bt.folds.bounds("F1")[1])
    C = bt.load_costs(M.index, M.columns, M.index[-1] + bt.BAR, close=M.close)
    assert C.mt_fill is not None and np.isnan(C.mt_fill).all()                                   # no file: every name NaN
    r = bt.run(Planted(), PAIRS, ["F1"], draws=1, execs=("taker", "maker_trade"), name="nan_mt")
    assert r["fills"]["maker_trade"]["net_bps"].isna().all() and r["fills"]["taker"]["net_bps"].notna().sum() > 100
    C2 = bt.Costs(C.days, C.taker_leg, C.maker_adv, C.maker_fill, C.fundcum, C.fundval)        # a Costs built the old way (the tests do): the exec refuses, the others price
    with pytest.raises(ValueError):
        bt.price(r["decisions"], M, C2, "maker_trade", 5.0, 2.0)
    assert len(bt.price(r["decisions"], M, C2, "taker", 5.0, 2.0)) == len(r["fills"]["taker"])


def test_the_frozen_constants_are_r39s_and_the_cli_knows_the_exec():
    here = Path(__file__).resolve().parents[1]
    mt = pd.read_csv(here / "ft2" / "maker_trade.csv")
    assert list(mt["symbol"]) == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "ZECUSDT", "1000PEPEUSDT", "WLDUSDT", "HYPEUSDT"]
    assert (mt["window"] == "2026-08-15_2026-08-28").all() and mt["fill_share"].between(0.85, 0.97).all() and mt["adv_filled_mean_bps"].between(-3.5, -1.0).all()
    rt = 2 * (mt["fill_share"] * (2.0 - mt["adv_filled_mean_bps"]) + (1 - mt["fill_share"]) * (5.0 + mt["slip15_mean_bps"]))
    assert (rt - mt["eff_rt_bps"]).abs().max() < 0.02 and abs(mt["eff_rt_bps"].median() - 8.43) < 0.01            # the EV form against R39's per-placement mean
    s = here / "output" / "makercost" / "2026-08-15_2026-08-28" / "summary.csv"
    if s.exists():
        r39 = pd.read_csv(s).set_index("symbol").reindex(mt["symbol"])
        for c in ("fill_share", "adv_filled_mean_bps", "slip15_mean_bps", "eff_rt_bps"):
            assert np.allclose(mt[c].to_numpy(), r39[c].to_numpy(), atol=1e-6), c
    from ft2.__main__ import main
    with pytest.raises(SystemExit):
        main(["backtest", "coin", "--execs", "maker_trad"])                                      # not a choice
    assert "maker_trade" in bt.EXECS_ALL and "maker_trade" not in bt.EXECS
