"""R90 unit tests for `ft2/allbook.py`: the rule takes a tenth a side from bars with at least ten forecasts and nothing from thinner ones;
the verdict names its three outcomes; a coin entered again before its exit is counted."""
import numpy as np
import pandas as pd

from ft2 import allbook as ab


def test_the_rule_takes_a_tenth_a_side_and_skips_a_thin_bar():
    t = pd.date_range("2026-02-01", periods=3, freq="h", tz="UTC")
    rng = np.random.default_rng(90)
    rows = []
    for i, n in enumerate((25, 9, 60)):
        f = rng.normal(size=n)
        rows += [{"t": t[i], "symbol": f"N{j:02d}USDT", "f": f[j], "z": 0.0} for j in range(n)]
    fc = pd.DataFrame(rows)
    d = ab.decisions(fc)
    assert set(d["t"]) == {t[0], t[2]}                                              # nine forecasts: no decision
    for ti, k in ((t[0], 2), (t[2], 6)):
        x, src = d[d["t"] == ti], fc[fc["t"] == ti].sort_values("f")
        assert (x["side"] > 0).sum() == (x["side"] < 0).sum() == k and (x["k"] == k).all()
        assert set(x.loc[x["side"] < 0, "symbol"]) == set(src["symbol"].head(k)) and set(x.loc[x["side"] > 0, "symbol"]) == set(src["symbol"].tail(k))
    assert (d["hold"] == 288).all() and (d["size"] == 1.0).all() and (d["fold"] == "F5").all()
    nan = fc.assign(f=np.where(fc["symbol"] == "N00USDT", np.nan, fc["f"]))
    assert "N00USDT" not in set(ab.decisions(nan)["symbol"])                       # a cell without a forecast is never traded


def test_the_verdict_and_the_overlap_count():
    assert ab.verdict(40.0, 20.0) == "CLEARS" and ab.verdict(20.0, 20.0) == "NOT DETECTABLE" and ab.verdict(-50.0, 20.0) == "FAILS"
    assert ab.verdict(-10.0, 20.0) == "NOT DETECTABLE" and ab.verdict(float("nan"), 1.0) == "NOT DETECTABLE"
    e = pd.to_datetime(["2026-02-01 00:05", "2026-02-02 00:05", "2026-02-02 12:00", "2026-02-01 00:05"], utc=True)
    f = pd.DataFrame({"symbol": ["A", "A", "A", "B"], "entry_t": e, "exit_t": e + pd.Timedelta(days=1)})
    assert ab.overlaps(f) == 1                                                      # A's third position is entered before its second one's exit
    assert ab.FORECAST_MD5 == "0473adf9eabf1747b576c849fe484f98" and ab.FIVE == ("LABUSDT", "SIRENUSDT", "HOMEUSDT", "SLXUSDT", "TRXUSDT")
