"""R90 unit tests for `ft2/allbook.py`: the rule takes a tenth a side from bars with at least ten forecasts and nothing from thinner ones;
the verdict names its three outcomes; a coin entered again before its exit is counted."""
import numpy as np
import pandas as pd

import pytest

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


def _planted():
    """Twenty coins, 201 hourly bars, the forecast = the coin's number (coin 0 the lowest) except where a scenario moves it."""
    t = pd.date_range("2026-10-01", periods=201, freq="h", tz="UTC")
    f = np.tile(np.arange(20, dtype=float), (len(t), 1))
    f[10:30, 2] = -5.0                                    # coin 2: the lowest for hours 10 … 29 …
    f[20:30, 2] = 1.5                                     # … then third from hour 20 (still in the fifth) …
    f[30:, 2] = 10.0                                      # … and out of the fifth from hour 30
    f[40:, 3] = -6.0                                      # coin 3: the lowest from hour 40
    f[60:70, 5] = -7.0                                    # coin 5: the lowest for hours 60 … 69, then gone from the table
    fc = pd.DataFrame({"t": np.repeat(t, 20), "symbol": np.tile([f"C{j:02d}USDT" for j in range(20)], len(t)), "f": f.ravel()})
    fc = fc[~((fc["symbol"] == "C05USDT") & (fc["t"] >= t[70]))]
    ev = pd.date_range("2026-09-30", periods=40, freq="8h", tz="UTC")
    fund = pd.DataFrame({"symbol": np.repeat([f"C{j:02d}USDT" for j in range(20)], len(ev)), "ts": np.tile(ev, 20), "rate": 1e-4, "interval_h": 8})   # +3 bps a day
    fund.loc[fund["symbol"] == "C01USDT", "rate"] = -50 / 3e4                                                    # coin 1: −50 bps a day, always
    fund.loc[(fund["symbol"] == "C03USDT") & (fund["ts"] >= t[50]), "rate"] = -40 / 3e4                          # coin 3: −40 bps a day from hour 50
    return t, fc, fund


def test_r91_the_short_is_held_while_in_the_fifth_and_every_exit_has_its_clause():
    t, fc, fund = _planted()
    dec, skipped = ab.positions(fc, fund)
    got = {(r.symbol, r.t, r.hold, r.why) for r in dec.itertuples()}
    want = {("C00USDT", t[0], 168 * 12, "cap"),                                   # held seven days, closed at the cap …
                                                                                  # … and not re-entered: 19 coins from hour 70, so the tenth is ONE coin (coin 3)
            ("C02USDT", t[10], 20 * 12, "left_fifth"),                            # in the tenth from hour 10; third at hour 20 — HELD; out of the fifth at 30
            ("C03USDT", t[40], 16 * 12, "funding"),                               # entered at +3 a day; the first −40 event is stamped at hour 56 (08:00)
            ("C05USDT", t[60], 10 * 12, "no_forecast")}                           # gone from the table at hour 70
    assert got == want, got ^ want
    assert (dec["side"] == -1).all() and dec["accepted"].all() and ab.overlaps(dec.assign(entry_t=dec["t"], exit_t=dec["t"] + pd.to_timedelta(dec["hold"] * 5, "min"))) == 0
    assert set(skipped["symbol"]) == {"C01USDT", "C03USDT"} and (skipped["why"] == "funding_floor").all()        # never short a coin whose short pays more than 10 a day
    assert skipped.loc[skipped["symbol"] == "C03USDT", "t"].min() == t[56]                                       # coin 3 is not re-entered after its funding exit
    thin = fc[fc["symbol"].isin([f"C{j:02d}USDT" for j in range(9)])]
    assert len(ab.positions(thin, fund)[0]) == 0                                  # nine forecasts a bar: nothing is entered
    nofund = fund[fund["symbol"] != "C00USDT"]
    d2, s2 = ab.positions(fc, nofund)
    assert "C00USDT" not in set(d2["symbol"]) and (s2.loc[s2["symbol"] == "C00USDT", "why"] == "no_funding_row").all()


def test_r91_the_gate_needs_both_halves_and_the_guard_refuses_a_look_before_the_span_ends(tmp_path, monkeypatch):
    assert ab.verdict91(200.0, 80.0, 150.0, 250.0) == "CLEARS" and ab.verdict91(200.0, 80.0, -10.0, 400.0) == "NOT DETECTABLE"
    assert ab.verdict91(100.0, 80.0, 50.0, 150.0) == "NOT DETECTABLE" and ab.verdict91(-200.0, 80.0, -1.0, -1.0) == "FAILS"
    assert (ab.F6_START, ab.F6_END) == (pd.Timestamp("2026-09-17", tz="UTC"), pd.Timestamp("2027-03-16", tz="UTC"))
    assert (ab.FUND_ENTRY, ab.FUND_EXIT, ab.CAP_BARS, ab.FIFTH, ab.TENTH, ab.HEDGE_BPS) == (-10.0, -30.0, 2016, 5, 10, 4.0) and ab.MODEL_MD5.startswith("816b994c")
    plan = tmp_path / "PLAN.md"
    plan.write_text("### R91 — planted\n")
    monkeypatch.setattr(ab.bt, "PLAN", plan)
    monkeypatch.setattr(ab.bt, "READS", tmp_path / "reads.csv")
    if pd.Timestamp.now("UTC") < ab.F6_END:
        with pytest.raises(SystemExit, match="a look is the read"):
            ab._guard91("R91")
    monkeypatch.setattr(ab, "F6_END", pd.Timestamp("2020-01-01", tz="UTC"))
    ab._guard91("R91")                                                             # after the span: allowed once …
    pd.DataFrame({"read_at": ["x"], "registration": ["R91"], "fold": ["F6"], "strategy": ["s"], "params": ["{}"]}).to_csv(tmp_path / "reads.csv", index=False)
    with pytest.raises(SystemExit, match="already read F6"):
        ab._guard91("R91")                                                         # … and never twice
    with pytest.raises(SystemExit, match="write the registration"):
        ab._guard91("R99")


def test_r91_a_coin_closed_at_the_cap_is_re_entered_at_the_same_bar_if_still_in_the_tenth():
    t, fc, fund = _planted()
    stay = pd.DataFrame({"t": t[70:], "symbol": "C05USDT", "f": 5.0})             # coin 5 stays in the table: twenty coins a bar, the tenth is two
    dec, _ = ab.positions(pd.concat([fc, stay], ignore_index=True), fund)
    c0 = dec[dec["symbol"] == "C00USDT"].sort_values("t")
    assert [(r.t, r.hold, r.why) for r in c0.itertuples()] == [(t[0], 2016, "cap"), (t[168], 32 * 12, "span_end")]
