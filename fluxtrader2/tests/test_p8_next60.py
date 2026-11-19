"""R100 (ft2/next60.py): planted bars only — the guard, the H-day hold and the twentieth, the 24 h average, the pooled IC and its gate, G and the choice."""
import hashlib

import numpy as np
import pandas as pd
import pytest

from ft2 import allbook as ab, allgbm as ag, next60 as n6
from tests.test_p8_allbook import _planted_days


def test_r100_the_constants_are_the_registrations_and_the_guard_refuses_a_draft_a_second_read_and_b_before_a(tmp_path, monkeypatch):
    assert {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in (*n6.LISTS.values(), n6.HERE / "screen_next60_f5.csv")} == n6.LISTS_MD5
    assert n6.SCORABLE == {"pre": 656_386, "f34": 693_589, "f5": 327_533, "f12": 696_005} and sum(n6.SCORABLE[k] for k in n6.SAMPLE) == 1_677_508
    assert len(n6.FORMS) == 12 and n6.BASE in n6.FORMS and n6.CW3_FORM in n6.FORMS and (n6.AVG_BARS, n6.AVG_MIN, n6.REG, n6.FOLD) == (24, 12, "R100", "N60")
    assert [str(n6.LABEL_END[k].date()) for k in n6.SAMPLE] == ["2023-05-01", "2026-01-01", "2026-09-15"] and n6.ABSENT["pre"] == ("hl_gap24_dev",)
    assert n6.seg_args("f34")["end"] == n6.LABEL_END["f34"] and n6.seg_args("f5")["end"] == n6.LABEL_END["f5"] and n6.seg_args("pre")["end"] == n6.LABEL_END["pre"]
    plan = tmp_path / "PLAN.md"
    monkeypatch.setattr(n6.bt, "PLAN", plan)
    monkeypatch.setattr(n6.bt, "READS", tmp_path / "reads.csv")
    monkeypatch.setattr(n6, "OUT", tmp_path / "r100")
    with pytest.raises(SystemExit, match="no '### R100 ' block"):
        n6._guard100("a")
    plan.write_text("### R100 — planted (DRAFT written before the word)\nValidity: the word DRAFT lower down does not count\n")
    with pytest.raises(SystemExit, match="DRAFT"):
        n6._guard100("a")
    plan.write_text("### R100 — planted (REGISTERED)\nValidity: … without \"DRAFT\" in its heading\n")
    n6._guard100("a")
    with pytest.raises(SystemExit, match="after \\(A\\)"):
        n6._guard100("b")
    pd.DataFrame({"read_at": ["x"], "registration": ["R100"], "fold": ["N60"], "strategy": ["s"], "params": ["{}"]}).to_csv(tmp_path / "reads.csv", index=False)
    with pytest.raises(SystemExit, match="already read N60"):
        n6._guard100("a")
    with pytest.raises(SystemExit, match="after \\(A\\)"):
        n6._guard100("b")                                                          # the ledger row without (A)'s file
    (tmp_path / "r100").mkdir()
    (tmp_path / "r100" / "a.json").write_text("{}")
    n6._guard100("b")
    (tmp_path / "r100" / "b.json").write_text("{}")
    with pytest.raises(SystemExit, match="has been read"):
        n6._guard100("b")


def test_r100_the_tail_is_examined_at_whole_multiples_of_the_hold_and_the_twentieth_needs_twenty():
    t, fc, fund = _planted_days()
    m = ab.midnight(fc)
    base, _ = n6.form_positions(m, fund, 1, 10)
    d99, _ = ab.positions99(fc, fund)
    assert (base[["t", "symbol", "hold", "why"]] == d99[["t", "symbol", "hold", "why"]]).all().all()                 # (1 day, tenth, raw) IS R99's rule
    h3, _ = n6.form_positions(m, fund, 3, 10)
    got = {(r.symbol, r.t, r.hold, r.why) for r in h3.itertuples()}
    assert ("C01USDT", t[0], 3 * 288, "left_tenth") in got                         # out of the tenth at day 2 (age 2: not examined), closed at day 3
    assert ("C04USDT", t[48], 3 * 288, "funding") in got                           # entered at day 2 beside it; the funding exit is examined EVERY day
    assert ("C00USDT", t[0], 7 * 288, "cap") in got                                # the cap every day
    h2, _ = n6.form_positions(m, fund, 2, 10)
    assert ("C01USDT", t[0], 2 * 288, "left_tenth") in {(r.symbol, r.t, r.hold, r.why) for r in h2.itertuples()}     # age 2 is a whole multiple of 2
    tw, _ = n6.form_positions(m, fund, 1, 20)
    got = {(r.symbol, r.t, r.hold, r.why) for r in tw.itertuples()}
    assert ("C00USDT", t[0], 2 * 288, "left_twentieth") in got and ("C04USDT", t[48], 3 * 288, "funding") in got and "C01USDT" not in set(tw["symbol"])    # k = 1
    thin, _ = n6.form_positions(m[m["symbol"] != "C19USDT"], fund, 1, 20)
    assert len(thin) == 0                                                          # nineteen cells: no twentieth
    ten, _ = n6.form_positions(m[m["symbol"] != "C19USDT"], fund, 1, 10)
    assert len(ten) > 0                                                            # … and still a tenth (n ≥ 10)
    assert (h3["hold"] % 288 == 0).all() and (pd.DatetimeIndex(h3["t"]).hour == 0).all()


def test_r100_the_average_is_the_24_bars_ending_at_midnight_with_twelve_present_for_names_in_the_list():
    t, fc, fund = _planted_days()
    syms = sorted(fc["symbol"].unique())
    mem = pd.DataFrame({"block": [t[0]] * 20 + [t[5 * 24]] * 19, "symbol": syms + [s for s in syms if s != "C03USDT"]})    # C03 out of the list from day 5
    a = n6.averaged(fc, mem).set_index(["t", "symbol"])["f"]
    assert t[0] not in a.index.get_level_values(0)                                  # one bar: under twelve
    assert np.isclose(a[(t[48], "C07USDT")], (10 * -9.0 + 14 * 7.0) / 24)           # ten hours at −9 inside day 1
    assert np.isclose(a[(t[48], "C04USDT")], (23 * 4.0 - 5.0) / 24) and np.isclose(a[(t[24], "C05USDT")], 5.0)
    assert (t[24], "C19USDT") in a.index and (t[4 * 24], "C03USDT") in a.index and (t[5 * 24], "C03USDT") not in a.index      # 23 hourly forecasts behind it, but not a cell at the bar
    assert (pd.DatetimeIndex(a.index.get_level_values(0)).hour == 0).all()
    short = fc[~((fc["symbol"] == "C02USDT") & (fc["t"] > t[24]) & (fc["t"] <= t[24 + 13]))]         # thirteen of day 1's bars missing: eleven present at day 2's 00:00
    b = n6.averaged(short, mem).set_index(["t", "symbol"])["f"]
    assert (t[48], "C02USDT") not in b.index and (t[72], "C02USDT") in b.index
    dec, _ = n6.form_positions(n6.form_fc(fc, mem, "avg"), fund, 1, 10)
    assert "C07USDT" in set(dec["symbol"]) and "C07USDT" not in set(n6.form_positions(n6.form_fc(fc, mem, "raw"), fund, 1, 10)[0]["symbol"])


def test_r100_the_pooled_ic_is_one_statistic_over_the_segments_and_the_gate_needs_the_three_positive():
    rng = np.random.default_rng(100)
    f = rng.normal(0, 1, (480, 12))
    z = 0.2 * f + rng.normal(0, 1, (480, 12))
    z[:, 11] = np.nan
    day = np.arange(480) // 24
    one = n6.pooled_ic([(f, z, day)])
    row = ag.ic_row(f, z, day)
    assert one["cells"] == row["cells"] == 480 * 11 and np.isclose(one["ic"], row["ic"]) and np.isclose(one["se"], row["se"])
    two = n6.pooled_ic([(f, z, day), (f[:, :8], z[:, :8], day + 500)])               # another build on another calendar stretch, other names
    assert two["cells"] == 480 * 11 + 480 * 8 and two["days"] == 40 and abs(two["ic"] - one["ic"]) < 0.03 and 0 < two["se"] < 0.05
    assert n6.verdict100(0.03, 0.004, 7.5, [0.02, 0.03, 0.04]) == "CONFIRMED AT THE TAKER BAR"
    assert n6.verdict100(0.03, 0.004, 7.5, [0.02, -0.001, 0.09]) == "NOT CONFIRMED"                 # one segment not positive
    assert n6.verdict100(0.010, 0.004, 2.5, [0.01, 0.01, 0.01]) == "CONFIRMED"
    assert n6.verdict100(0.010, 0.008, 1.25, [0.01, 0.01, 0.01]) == "NOT CONFIRMED"
    assert n6.verdict100(-0.004, 0.004, -1.0, [0.0, 0.0, 0.0]) == "NOT CONFIRMED — CLOSED"
    grid = pd.date_range("2022-01-01", periods=24 * 70, freq="h", tz="UTC")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/m.csv"
        pd.DataFrame({"block": ["2022-01-11", "2022-01-11", "2022-02-10"], "symbol": ["AAA", "BBB", "AAA"]}).to_csv(p, index=False)
        mc = n6.member_cells([p], ["AAA", "BBB", "CCC"], grid)
    days = (grid - grid[0]).days.to_numpy()
    assert not mc[days < 10].any() and mc[(days >= 10) & (days < 40)][:, :2].all() and mc[days >= 40][:, 0].all() and not mc[days >= 40][:, 1].any() and not mc[:, 2].any()
    late = pd.date_range("2022-03-20", periods=48, freq="h", tz="UTC")
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/m.csv"
        pd.DataFrame({"block": ["2022-01-11", "2022-02-10"], "symbol": ["AAA", "AAA"]}).to_csv(p, index=False)
        assert not n6.member_cells([p], ["AAA"], late).any()                        # a list does not reach past its last block's thirty days


def _fills(seg, day0, n, hedged, funding, fee=10.0, other=20.0):
    t = pd.date_range(day0, periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"t": t, "size": 1.0, "seg": seg, "hold": 288, "hedged_bps": hedged, "funding_bps": funding, "fee_bps": fee, "other_cost_bps": other,
                         "net_bps": hedged + funding - fee - other + 7.0, "hedged_net_bps": hedged + funding - fee - other})


def test_r100_g_is_before_every_cost_and_the_choice_is_the_registrations():
    rng = np.random.default_rng(1)
    f = pd.concat([_fills("pre", "2022-01-01", 60, 40.0 + rng.normal(0, 5, 60), 2.0), _fills("f34", "2025-01-01", 30, 10.0 + rng.normal(0, 5, 30), -1.0)], ignore_index=True)
    f.loc[0, "net_bps"] = np.nan                                                    # an unpriced position is in no number
    days = {"pre": pd.date_range("2022-01-01", periods=60, freq="D", tz="UTC"), "f34": pd.date_range("2025-01-01", periods=30, freq="D", tz="UTC"), "f5": pd.DatetimeIndex([], tz="UTC")}
    r = n6.form_row(f, days)
    p = f.dropna(subset=["net_bps"])
    assert r["positions"] == 89 and np.isclose(r["G"], (p["hedged_bps"] + p["funding_bps"]).mean()) and np.isclose(r["net"], r["G"] - 10 - 20 - 4)
    assert np.isclose(r["G_early"], (p["hedged_bps"] + p["funding_bps"])[p["seg"] == "pre"].mean()) and np.isclose(r["G_late"], 9.0, atol=3) and r["G_se"] > 0
    assert np.isclose(r["a_day"], 89 / 90) and np.isclose(r["crossings_a_day"], 2 * 89 / 90) and np.isclose(r["hold_days"], 1.0) and np.isclose(r["net_other_cost_x1.5"], r["net"] - 10)

    def tab(over):
        rows = [{"H": h, "tail": d, "fc": k, "G": 20.0, "G_se": 10.0, "G_early": 5.0, "G_late": 5.0} for h, d, k in n6.FORMS]
        t = pd.DataFrame(rows)
        for (h, d, k), kv in over.items():
            for c, x in kv.items():
                t.loc[(t["H"] == h) & (t["tail"] == d) & (t["fc"] == k), c] = x
        return t
    c = n6.choose(tab({}), True)
    assert c["winner"] is None and c["candidates"] == [] and not c["cw3_opened"]                    # nobody beats the base by its own se
    c = n6.choose(tab({(2, 10, "raw"): {"G": 31.0}, (3, 20, "avg"): {"G": 45.0, "G_se": 30.0}, (3, 10, "raw"): {"G": 50.0, "G_late": -1.0}}), True)
    assert c["winner"] == (2, 10, "raw") and c["candidates"] == [(2, 10, "raw")] and c["cw3_opened"]     # +25 under its se of 30; a negative half; CW3 reads G alone (50 ≥ 30)
    c = n6.choose(tab({(2, 20, "avg"): {"G": 40.0}, (2, 20, "raw"): {"G": 40.0}, (2, 10, "avg"): {"G": 40.0}, (3, 10, "raw"): {"G": 40.0}}), True)
    assert c["winner"] == (2, 10, "avg") and c["candidates"][:3] == [(2, 10, "avg"), (2, 20, "raw"), (2, 20, "avg")]      # ties: the shorter hold, then the tenth, then raw
    c = n6.choose(tab({(2, 10, "raw"): {"G": 80.0}}), False)
    assert c["winner"] is None and c["candidates"] == [(2, 10, "raw")] and "NOT CONFIRMED" in c["why"]  # (A) failed: no winner whatever the grid shows
    c = n6.choose(tab({(1, 10, "raw"): {"G": 90.0}}), True)
    assert c["winner"] is None and c["base_G"] == 90.0                               # the base itself is never a candidate
    v = n6.check_form(pd.DataFrame({"t": f["t"], "why": "left_tenth", "hold": 288}), f.assign(entry_t=f["t"] + pd.Timedelta(minutes=5), exit_t=f["t"] + pd.Timedelta(days=1), symbol="A"), 10)
    assert v["ok"] and v["priced_share"] > 0.98
    assert not n6.check_form(pd.DataFrame({"t": f["t"], "why": "left_fifth", "hold": 288}), f.assign(entry_t=f["t"] + pd.Timedelta(minutes=5), exit_t=f["t"] + pd.Timedelta(days=1), symbol="A"), 10)["ok"]
    t, fc, fund = _planted_days()
    ro = n6.reopen(ab.midnight(fc), fund)
    assert (ro["hold"] == 288).all() and len(ro[ro["symbol"] == "C00USDT"]) == 10 and ro["t"].max() == t[9 * 24]      # sold again every day; nothing at the last bar
