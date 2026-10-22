"""WALKFORWARD_PROTOCOL §9.9 (X18) — the long-head harness on made-up dumps, before any real bar.

Runs under pytest in `ml_trainer`, or directly: `./scripts/m3.sh tests/test_longhead.py`.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from m3 import backtest, dumps  # noqa: E402
from m3 import longhead as L  # noqa: E402

BAR = 300 * 1_000_000_000
T0 = pd.Timestamp("2026-01-01 00:00", tz="UTC").value

# Flat-size specs for the synthetic dumps (no regime column, so no BTC rows are needed).
INC = dict(coverage=0.5, signal_horizon=240, hold_horizon=240, regime_col=None,
           regime_quantile=None, regime_min=None, size_by_regime=False, max_concurrent=None,
           sides="both", side_from="model")


def _dump(seed: str, n_bars: int = 3 * 288, pairs=("AUSDT", "BUSDT"), nan_tail_1440: int = 0,
          rng_seed: int = 0) -> dumps.Dump:
    """n_bars 5m bars per pair over three days; conf random; fwd_ret at 240 = +1 bp × side for
    bars with conf ≥ 0.9 and −1 bp otherwise (so the 240 head is right on its confident bars);
    fwd_ret at 1440 = +5 bp × side for bars with conf_1440 ≥ 0.9, −2 bp otherwise."""
    rng = np.random.default_rng(rng_seed)
    rows = []
    for p in pairs:
        ts = T0 + np.arange(n_bars) * BAR
        for h, good, bad in ((240, 1e-4, -1e-4), (1440, 5e-4, -2e-4)):
            conf = rng.uniform(0.5, 1.0, n_bars)
            side = rng.choice([-1.0, 1.0], n_bars)
            ret = np.where(conf >= 0.9, good, bad) * side
            if h == 1440 and nan_tail_1440:
                ret[-nan_tail_1440:] = np.nan
            rows.append(pd.DataFrame({"ts": ts, "pair": p, "horizon": h, "side": side, "conf": conf,
                                      "p_up": 0.5, "fwd_ret": ret, "y3": 1, "has_book": 0}))
    df = pd.concat(rows, ignore_index=True)
    return dumps.Dump(seed=seed, run_id=f"synthetic_{seed}", df=df)


def test_clean_counts_and_drops_nan():
    d = _dump("s1", nan_tail_1440=7)
    c, counts = L.clean(d)
    assert counts == {1440: 14}                      # two pairs × 7
    assert not c.df["fwd_ret"].isna().any()
    assert len(c.df) == len(d.df) - 14
    c2, counts2 = L.clean(c)
    assert counts2 == {} and c2 is c


def test_daily_net_by_hand():
    days = pd.date_range("2026-01-01", "2026-01-03", freq="D", tz="UTC")
    t = pd.DataFrame({"entry_ts": [T0, T0 + 10 * BAR, T0 + 300 * BAR],      # day 1, day 1, day 2
                      "exit_ts": [T0 + 48 * BAR, T0 + 58 * BAR, T0 + 348 * BAR],
                      "signed_ret": [2e-4, -1e-4, 3e-4], "size": [1.0, 2.0, 1.0], "seed": "s1"})
    n = L.daily_net(t, days, n_seeds=1)
    # day 1: (2 − 14·1) + (−1 − 14·2) = −12 − 29 = −41; day 2: 3 − 14 = −11; day 3: 0
    assert np.allclose(n.to_numpy(), [-41.0, -11.0, 0.0])
    assert np.allclose(L.daily_net(t, days, n_seeds=2).to_numpy(), [-20.5, -5.5, 0.0])
    assert np.allclose(L.daily_net(t.iloc[0:0], days, 1).to_numpy(), [0.0, 0.0, 0.0])


def test_diff_stats_by_hand():
    D = np.array([1.0, 3.0, 2.0, 4.0])
    st = L.diff_stats(D)
    assert np.isclose(st["mean"], 2.5)
    assert np.isclose(st["se"], np.std(D, ddof=1) / np.sqrt(4))
    assert np.isclose(st["lo95"], 2.5 - 1.96 * st["se"])
    e = D - 2.5
    g0 = (e * e).mean()
    g1 = (e[1:] * e[:-1]).mean()
    assert np.isclose(st["se_nw"], np.sqrt(max(g0 + 2 * g1, 0.0) / 4))
    assert st["days"] == 4
    assert np.isnan(L.diff_stats(np.array([1.0]))["se"])


def test_arms_and_incumbent_check():
    raw = [_dump("s1", nan_tail_1440=5, rng_seed=1), _dump("s2", nan_tail_1440=5, rng_seed=2)]
    cleaned = [L.clean(d)[0] for d in raw]
    specs = L.arm_specs(INC)
    assert set(specs) == {"INC", "L02", "L05", "H24"}
    assert specs["L02"].signal_horizon == 1440 and specs["L02"].hold_horizon == 1440
    assert specs["H24"].signal_horizon == 240 and specs["H24"].hold_horizon == 1440
    assert specs["L05"].coverage == 0.05 and specs["L02"].coverage == 0.02
    ok, lines = L.check_incumbent(raw, cleaned, specs["INC"])
    assert ok, lines                                   # the 240 rows were untouched by the clean
    res = L.run_arms(cleaned, specs)
    for name, r in res.items():
        assert len(r.trades) > 0, name
        hold = specs[name].hold_horizon
        held = (r.trades["exit_ts"] - r.trades["entry_ts"]).unique()
        assert set(held) == {backtest.HORIZON_BARS[hold] * BAR}, name
    tab = L.daily_table(res, cleaned)
    assert list(tab["days"]) == ["served"] and len(tab["days"]["served"]) == 3
    inc = tab["pooled"]["INC"]["served"]
    assert np.isclose(inc.sum(), L.net_bps(res["INC"].trades).sum() / 2)
    per = sum(tab["per_seed"]["INC"][s].sum() for s in ("s1", "s2"))
    assert np.isclose(per, L.net_bps(res["INC"].trades).sum())


def test_fold_of_and_confirm_days():
    assert L.fold_of("F2s1") == "F2" and L.fold_of("s3") == "served"
    assert L.confirm_days() > 300


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
