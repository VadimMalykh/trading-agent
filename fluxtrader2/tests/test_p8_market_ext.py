"""R30 unit tests for `ft2/market_ext.py` on made-up bars: the index minute's known-from rule on the 5m grid, open / closed,
the lag's sign (a basket that follows the index with a delay reads positive on lag_4h and ix_1h, through the screen and the
shift null), a basket that ignores the index reads nothing, the flow's known-at, the family-wise p across horizons, the cut
to a fold's whole days, and a planted flow-led drift coming back with its sign."""
import numpy as np
import pandas as pd
import pytest

from ft2 import market as mk
from ft2 import market_ext as mx
from ft2.audit_index import Minutes

DAYS, N = 200, 6
START = pd.Timestamp("2023-09-04", tz="UTC")          # a Monday


def _minutes(days: int = DAYS + 2, seed: int = 7) -> pd.DataFrame:
    """A made-up index: traded every minute Monday 00:00 → Friday 21:00 UTC, except the daily break 21:00–21:59; a random walk."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(START - pd.Timedelta(days=1), periods=days * 1440, freq="1min")
    keep = (ts.dayofweek < 5) & (ts.hour != 21) & ~((ts.dayofweek == 4) & (ts.hour >= 21))
    ts = ts[keep]
    lc = np.cumsum(rng.normal(0, 1.5e-4, len(ts)))
    return pd.DataFrame({"ts": ts, "close": 100 * np.exp(lc)})


def _world(follow: float, seed: int = 3, flow_drift: float = 0.0, flows: pd.Series | None = None):
    """Six pairs = one market factor + own noise. `follow`: the basket makes `follow` × the index's hourly moves, spread over
    the hour they happen in and the three after it (weights 0.4, 0.3, 0.2, 0.1 — a slow follower; 0 = the basket ignores
    the index). `flow_drift`: bps per 5m bar per unit of the flow known at t (planted for the ETF test)."""
    rng = np.random.default_rng(seed)
    n = DAYS * 288
    idx = pd.date_range(START, periods=n, freq="5min", name="t")
    m = rng.normal(0, 6.0, n)
    mins = _minutes()
    mi = Minutes(mins)
    if follow:
        for k, w in enumerate((0.4, 0.3, 0.2, 0.1)):
            a, b = mi.at(idx - pd.Timedelta(hours=k + 1)), mi.at(idx - pd.Timedelta(hours=k))
            move = np.where(a["open"] & b["open"], (b["lc"] - a["lc"]) * 1e4, 0.0)
            m = m + follow * w * move / 12.0
    if flow_drift and flows is not None:
        F, _ = mx.features_etf(idx, flows, idx[-1] + pd.Timedelta("1h"))
        m = m + flow_drift * np.nan_to_num(F["flow"].to_numpy())
    r = m[:, None] + rng.normal(0, 4.0, (n, N))
    close = pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0) / 1e4), index=idx, columns=list("ABCDEF"))
    P = {"close": close, "high": close, "low": close, "dv": pd.DataFrame(1e6, index=idx, columns=close.columns)}
    D = mk.derive(P)
    F6, signed6 = mk.features(P, D)
    s = np.asarray(idx >= idx[0] + pd.Timedelta(days=40))
    return P, D, F6, signed6, s, mi, idx


def test_known_from_and_open_closed():
    P, D, F6, _, s, mi, idx = _world(0.0)
    F, own = mx.features_index(idx, F6, mi)
    chk = mx.check_known_index(idx, mi, own)
    assert chk["used_before_known"] == 0 and chk["with_minute"] > 0.99 * chk["bars"]
    # a bar 30 s after a minute's stamp still sees the minute before it (known from ts + 1 min)
    t = pd.DatetimeIndex([pd.Timestamp("2023-09-13 15:00:30", tz="UTC")])
    r = mi.at(t)["row"][0]
    assert mi.ts[r] == pd.Timestamp("2023-09-13 14:59", tz="UTC")
    wk = (idx.dayofweek < 5)
    warm = np.asarray(idx >= idx[0] + pd.Timedelta(days=40))                # σ_ix needs 30 days of open hours
    brk = wk & (idx.hour == 21) & (idx.minute >= 20)                        # the daily break, once the last minute is > 15 min old
    sess = wk & (idx.hour == 15)
    assert (F["ix_open"][brk] == 0).all() and (F["ix_open"][sess] == 1).all()
    assert F["ix_1h"][brk].isna().all() and F["ix_gap"][brk & warm].notna().all()
    assert F["ix_gap"][sess].isna().all() and F["ix_1h"][sess & warm].notna().all()
    wkend = idx.dayofweek == 6
    assert (F["ix_open"][wkend] == 0).all() and F["ix_vol"][wkend].isna().all()
    assert F["lag_4h"].notna().sum() > 0.3 * len(idx)


def _screen(D, F, signed, s, draws=20):
    sc, null = mk.screen(D, F, signed, s, draws)
    return sc, null


def test_follower_reads_positive_through_the_null():
    P, D, F6, signed6, s, mi, idx = _world(1.0)
    F, own = mx.features_index(idx, F6, mi)
    assert np.nanmedian(own["b"][s]) > 0.3                                   # the 24-hour slope sees the whole response
    names = mx.FAMILIES["index"]["direction"]
    sc, null = _screen(D, {k: F[k] for k in names}, mx.SIGNED, s)
    d = sc[(sc["bet"] == "directional") & (sc["horizon"] == "1h")].set_index("feature")
    assert d.loc["lag_4h", "ic"] > 0.02 and d.loc["lag_4h", "t"] > 1 and d.loc["ix_1h", "ic"] > 0.02
    p, info = mx.family_p(null, "directional", names, d.loc[["lag_4h", "ix_1h"], "t"].to_numpy())
    assert p[1] <= 0.05 and info["rows"] == 2 and info["bar_p95"] > info["bar_mean"]
    parts = mx.parts_of(idx[s], "index", mk.FOLDS)
    pi = mx.part_ics(D, F, mx.SIGNED, s, names, parts)
    assert pi[(pi["horizon"] == "1h") & (pi["feature"] == "lag_4h")]["parts_same_sign"].item()


def test_a_basket_that_ignores_the_index_reads_nothing():
    P, D, F6, signed6, s, mi, idx = _world(0.0)
    F, _ = mx.features_index(idx, F6, mi)
    names = mx.FAMILIES["index"]["direction"]
    sc, null = _screen(D, {k: F[k] for k in names}, mx.SIGNED, s)
    d = sc[sc["bet"] == "directional"]
    assert d["t"].abs().max() < 3.5
    pr = mx.partial_ics(D, {**F, **F6}, s, mx.FAMILIES["index"]["sizing"])
    assert len(pr) == 6 and np.isfinite(pr["partial_ic"]).all()


def test_flow_known_at():
    idx = pd.date_range(START, periods=5 * 288, freq="5min", name="t")
    flows = pd.Series([100.0, -400.0], index=pd.DatetimeIndex([START, START + pd.Timedelta(days=1)]))
    F, own = mx.features_etf(idx, flows, idx[-1])
    at = lambda t: F["flow"][pd.Timestamp(t, tz="UTC")]            # noqa: E731
    assert np.isnan(at("2023-09-05 08:55"))
    assert at("2023-09-05 09:00") == pytest.approx(100 / 300)
    assert at("2023-09-06 08:55") == pytest.approx(100 / 300) and at("2023-09-06 09:00") == pytest.approx(-400 / 300)
    assert np.isnan(F["flow_big"][pd.Timestamp("2023-09-05 12:00", tz="UTC")]) and F["flow_big"][pd.Timestamp("2023-09-06 12:00", tz="UTC")] == pytest.approx(-400 / 300)
    assert mx.check_known_etf(idx, own)["used_before_known"] == 0
    # a flow not yet known at `end` is not loaded
    F2, _ = mx.features_etf(idx, flows, START + pd.Timedelta(days=1, hours=12))
    assert F2["flow"].dropna().abs().max() == pytest.approx(100 / 300)


def test_family_p_across_horizons():
    null = pd.DataFrame([{"bet": "directional", "horizon": h, "feature": f, "draw": d, "ic": 0.0, "t": t}
                         for d in range(1, 5) for h, f, t in (("1h", "a", 1.0 * d), ("4h", "a", -0.5 * d), ("1h", "b", 0.2))])
    p, info = mx.family_p(null, "directional", ["a", "b"], np.array([3.5, -4.5]))
    assert list(p) == [pytest.approx(2 / 5), pytest.approx(1 / 5)] and info["bar_mean"] == pytest.approx(2.5)


def test_cut_days():
    P, D, F6, signed6, s, mi, idx = _world(0.0)
    s2 = np.asarray((idx >= pd.Timestamp("2023-11-01 03:00", tz="UTC")) & (idx < pd.Timestamp("2024-01-10 12:00", tz="UTC")))
    D2, F2, s3 = mx.cut_days(D, F6, s2)
    i2 = D2["blr"].index
    assert i2[0] == pd.Timestamp("2023-11-01", tz="UTC") and i2[-1] == pd.Timestamp("2024-01-10 23:55", tz="UTC")
    assert len(i2) % 288 == 0 and s3.sum() == s2.sum() and len(F2["mret_4h"]) == len(i2)


def test_planted_flow_drift():
    days = pd.date_range(START - pd.Timedelta(days=3), periods=DAYS + 3, freq="D")
    flows = pd.Series(np.random.default_rng(11).normal(0, 300, len(days)), index=days)
    P, D, F6, signed6, s, mi, idx = _world(0.0, flow_drift=2.0, flows=flows)
    F, _ = mx.features_etf(idx, flows, idx[-1] + pd.Timedelta("1h"))
    names = mx.FAMILIES["etf"]["direction"]
    sc, null = _screen(D, {k: F[k] for k in names}, mx.SIGNED, s)
    d = sc[(sc["bet"] == "directional") & (sc["horizon"] == "1d")].set_index("feature")
    assert d.loc["flow", "ic"] > 0.05
    p, _ = mx.family_p(null, "directional", names, np.array([d.loc["flow", "t"]]))
    assert p[0] <= 0.05
