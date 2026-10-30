"""R72 unit tests for the attention screen (`wiki_ext.run_r72`) on made-up bars and planted pageviews, no network: the join reads the LATEST
stamped day and carries it 24 hours and no longer, at BOTH stamps (48 h / 36 h), with `hand_value` agreeing cell by cell; the frozen inputs,
the stamp, R62's reproduction on the planted Coinbase members, the strictness and the coverage each void the run before any wiki value is
joined to a label; a planted GIVE-BACK (views two days before a day whose relative return is negative) comes back with the registered
NEGATIVE sign on the member cells; the Terra tie is three identical columns; the proxy member and the twelve are described rows, never cells;
the old-article subset, the 3d horizon, the zero-view share and the per-block table are beside; the sources are unchanged by the run."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ft2 import cb_ext as cx, ceiling, wiki, wiki_ext as wx
from ft2.wiki_ext import DEV, DEV3, LVL, OLD, PROXY, TWELVE_ROW
from tests.test_p8_cb_ext import PAIRS, START, _world
from tests.test_p8_r62 import MEM, _kw, _members_world, _r60_saved

SLICES = ("candles_5m_archive", "candles_5m")
TIE = ["M01USDT", "M02USDT", "M03USDT"]                       # one article, three names
STRICT10 = sorted(m for m in MEM if m not in ("M10USDT", "THINUSDT"))   # M10 a proxy, THIN no article → 10 registered names
D0, D1 = pd.Timestamp("2023-02-01", tz="UTC"), pd.Timestamp("2023-06-20", tz="UTC")
LATE_FIRST = pd.Timestamp("2023-05-10", tz="UTC")             # LATE's article created inside F1: a young name
UTC = lambda s: pd.Timestamp(s, tz="UTC")                     # noqa: E731


def _articles(path: Path = Path("wiki_articles_test.csv")) -> Path:
    rows = [{"base": "M01", "article": "Terra (blockchain)", "source": "chain"}, {"base": "M02", "article": "Terra (blockchain)", "source": "chain"},
            {"base": "M03", "article": "Terra (blockchain)", "source": "chain"}] + \
           [{"base": f"M{i:02d}", "article": f"Coin M{i:02d}", "source": "own"} for i in range(4, 10)] + \
           [{"base": "M10", "article": "Ape thing", "source": "proxy"}, {"base": "LATE", "article": "Late protocol", "source": "own"}, {"base": "THIN", "article": "", "source": "none"}] + \
           [{"base": b, "article": f"Coin {b}", "source": "own"} for b in ("BTC", "ETH", "SOL", "XRP", "ADA", "AVAX")] + [{"base": "ZEC", "article": "Zcash frog", "source": "proxy"}]
    A = pd.DataFrame(rows)
    A["symbols"] = A["base"] + "USDT"
    A["note"] = ""
    A[["base", "symbols", "article", "source", "note"]].to_csv(path, index=False)
    return path


def _views_table(views: dict[str, pd.Series], arts: dict[str, str], known_at_h: int = 48) -> pd.DataFrame:
    parts = []
    for sym, v in views.items():
        parts.append(pd.DataFrame({"base": sym[:-4], "symbol": sym, "article": arts.get(sym, sym), "day": v.index, "views": v.to_numpy().astype("int64"), "present": True,
                                   "ts_known": v.index + pd.Timedelta(hours=known_at_h)}))
    return pd.concat(parts, ignore_index=True).sort_values(["symbol", "day"]).reset_index(drop=True)


def _wiki_world(known_at_h: int = 48, seed: int = 5, path: str = "data/wiki_views.parquet") -> pd.DataFrame:
    """The planted views: for each member name and day D, views(D − 2) = 300 × exp(−2 × sign(the mean over D's cells of the name's next-day
    RELATIVE return)) + a little noise — the deviation read on day D (at the 48 h stamp every cell of D reads D − 2) then GIVES BACK; the
    tie's three names share one series; M09 has zero-view days; LATE's article starts inside F1; the twelve's BTC / ETH / ZEC random."""
    rng = np.random.default_rng(seed)
    arch = pd.read_parquet("data/candles_5m_archive.parquet")
    arch["t"] = pd.DatetimeIndex(arch["open_time"]).tz_convert("UTC") + ceiling.BAR
    C = arch.pivot(index="t", columns="symbol", values="close")
    L = np.log(C[MEM].to_numpy())
    fwd = np.roll(L, -288, axis=0) - L
    fwd[-288:] = 0.0
    rel = pd.DataFrame(fwd - fwd.mean(axis=1, keepdims=True), index=C.index, columns=MEM)
    score = rel.groupby(rel.index.floor("D")).mean()                       # day D → the mean next-day relative return over D's cells
    days = pd.date_range(D0, D1, freq="D")
    views: dict[str, pd.Series] = {}
    for sym in MEM:
        sc = score[sym].reindex(days + 2 * pd.Timedelta("1D")).fillna(0.0).to_numpy()    # the value at day d encodes day d + 2
        v = np.round(300.0 * np.exp(-2.0 * np.sign(sc)) + rng.integers(0, 5, len(days))).astype(int)
        if sym == "M09USDT":
            v[::7] = 0
        s = pd.Series(v, index=days)
        if sym == "LATEUSDT":
            s = s[s.index >= LATE_FIRST]
        views[sym] = s
    for sym in TIE[1:]:
        views[sym] = views[TIE[0]].copy()
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "ZECUSDT"):                 # the twelve's: six strict, one proxy
        views[sym] = pd.Series(rng.integers(50, 150, len(days)), index=days)
    A = pd.read_csv("wiki_articles_test.csv", dtype=str).fillna("")
    arts = {b + "USDT": a for b, a in zip(A["base"], A["article"])}
    d = _views_table(views, arts, known_at_h)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(path, index=False)
    return d


def _expect(d: pd.DataFrame, **over) -> dict:
    return {"md5_articles": hashlib.md5(Path("wiki_articles_test.csv").read_bytes()).hexdigest(), "md5_members": hashlib.md5(Path("members.csv").read_bytes()).hexdigest(),
            "names": STRICT10, "rows": len(d), "symbols": int(d["symbol"].nunique()), "first_day": str(d["day"].min().date()), "last_day": str(d["day"].max().date()),
            "tie": TIE, "proxy_member": "M10USDT"} | over


def _kw72(saved, d, **over):
    return dict(draws=5, shift_min=25, shift_floor=20, path="data/wiki_views.parquet", cb_path="data/coinbase_1h_members.parquet", r62=Path("output/ceiling_coinbase_members"), r60=saved,
                cb_csv="cb_members_r62.csv", members_csv="members.csv", articles_csv="wiki_articles_test.csv", slices=SLICES, mult={}, n_check=100, start=pd.Timestamp(START, tz="UTC"),
                block_min_names=5, expect=_expect(d), known_at_h=48) | over


def _r62_saved(tmp_path):
    _world(tmp_path)
    _members_world(tmp_path)
    saved, _ = _r60_saved()
    cx.run_members(5.0, 2.0, "test", PAIRS, **_kw(saved, slices=SLICES))
    _articles()
    return saved


# ---- the join ---------------------------------------------------------------------------------------------------------------------------------
def _tiny(known_at_h: int, drop_day: pd.Timestamp | None = None) -> tuple[pd.DataFrame, pd.Series]:
    days = pd.date_range(UTC("2023-01-01"), UTC("2023-03-31"), freq="D")
    v = pd.Series(np.round(100 + 40 * np.sin(np.arange(len(days)) / 3.0)).astype(int), index=days)
    if drop_day is not None:
        v = v.drop(drop_day)
    return _views_table({"AAAUSDT": v}, {"AAAUSDT": "Aaa"}, known_at_h), v


def _hand_dev(v: pd.Series, day: pd.Timestamp) -> float:
    w = v[(v.index > day - 30 * pd.Timedelta("1D")) & (v.index <= day)]
    x = np.log1p(w.to_numpy(dtype=float))
    return (np.log1p(float(v[day])) - x.mean()) / np.std(x, ddof=1) if len(w) >= 15 and np.std(x, ddof=1) > 0 else np.nan


@pytest.mark.parametrize("stamp_h", [48, 36])
def test_the_join_reads_the_latest_stamped_day_carries_it_24_hours_and_no_longer_at_both_stamps(stamp_h):
    d, v = _tiny(stamp_h)
    idx = pd.date_range(UTC("2023-02-01 00:05"), UTC("2023-03-20"), freq="5min")
    W = wx.frames_wiki(d, ["AAAUSDT"], idx, ["AAAUSDT", "NOPEUSDT"])
    F, U = W["F"][DEV]["AAAUSDT"], W["U"]["AAAUSDT"]
    d0 = UTC("2023-03-01")
    k0 = d0 + pd.Timedelta(hours=stamp_h)                                   # ts_known(d0)
    assert abs(F.loc[k0 + wx.MARGIN] - _hand_dev(v, d0)) < 1e-9                                          # the first cell that may read d0
    assert abs(F.loc[k0 + wx.MARGIN - ceiling.BAR] - _hand_dev(v, d0 - pd.Timedelta("1D"))) < 1e-9      # one bar earlier: the day before
    assert abs(F.loc[k0 + pd.Timedelta(hours=24) + wx.MARGIN - ceiling.BAR] - _hand_dev(v, d0)) < 1e-9   # carried through the 24th hour
    assert abs(F.loc[k0 + pd.Timedelta(hours=24) + wx.MARGIN] - _hand_dev(v, d0 + pd.Timedelta("1D"))) < 1e-9   # then the next day's value
    assert U.loc[k0 + wx.MARGIN] == k0.value // 3_600_000_000_000 and U.loc[k0 + wx.MARGIN - ceiling.BAR] == k0.value // 3_600_000_000_000 - 24
    # the day arithmetic: a cell on day D at 10:00 reads D − 2 under both stamps; at 13:00 D − 2 at 48 h and D − 1 at 36 h
    D = UTC("2023-03-10")
    assert abs(F.loc[D + pd.Timedelta(hours=10)] - _hand_dev(v, D - 2 * pd.Timedelta("1D"))) < 1e-9
    read_13 = D - (2 if stamp_h == 48 else 1) * pd.Timedelta("1D")
    assert abs(F.loc[D + pd.Timedelta(hours=13)] - _hand_dev(v, read_13)) < 1e-9
    # a missing next day: d0's value is NOT carried past its 24 hours
    d2, v2 = _tiny(stamp_h, drop_day=d0 + pd.Timedelta("1D"))
    W2 = wx.frames_wiki(d2, ["AAAUSDT"], idx, ["AAAUSDT"])
    F2, U2 = W2["F"][DEV]["AAAUSDT"], W2["U"]["AAAUSDT"]
    assert abs(F2.loc[k0 + pd.Timedelta(hours=24) + wx.MARGIN - ceiling.BAR] - _hand_dev(v2, d0)) < 1e-9
    assert np.isnan(F2.loc[k0 + pd.Timedelta(hours=24) + wx.MARGIN]) and np.isnan(F2.loc[k0 + pd.Timedelta(hours=47) + wx.MARGIN]) and np.isnan(U2.loc[k0 + pd.Timedelta(hours=30)])
    assert abs(F2.loc[k0 + pd.Timedelta(hours=48) + wx.MARGIN] - _hand_dev(v2, d0 + 2 * pd.Timedelta("1D"))) < 1e-9
    # hand_value agrees cell by cell, the used hour included
    rows = d2[d2["symbol"] == "AAAUSDT"].reset_index(drop=True)
    n_val = 0
    for t in idx[::97]:
        got, u, exp = F2.loc[t], U2.loc[t], wx.hand_value(rows, t)
        assert (np.isnan(got) and np.isnan(exp[0])) or abs(got - exp[0]) < 1e-9
        assert (np.isnan(u) and np.isnan(exp[1])) or u == exp[1]
        n_val += int(np.isfinite(got))
    assert n_val > 100
    assert "NOPEUSDT" in W["F"][DEV].columns and W["F"][DEV]["NOPEUSDT"].isna().all()


# ---- the voids ---------------------------------------------------------------------------------------------------------------------------------
def test_the_inputs_the_stamp_the_reproduction_the_strictness_and_the_coverage_each_void_the_run_before_any_wiki_ic(tmp_path):
    saved = _r62_saved(tmp_path)
    d = _wiki_world()
    L = wx.names_r72("members.csv", "wiki_articles_test.csv")
    assert L["names"] == STRICT10 and L["proxy"] == ["M10USDT"] and L["source"]["M01USDT"] == "chain" and L["n_members"] == 12
    fp = wx.fingerprint(wiki.load("data/wiki_views.parquet"))
    assert fp["stamp_h"] == [48.0] and fp["symbols"] == 19 and fp["views_sum"] == int(d["views"].sum())
    with pytest.raises(SystemExit) as e:                                                   # (4) a name list that is not the files'
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d, expect=_expect(d, names=STRICT10[:-1])))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["status"] == "FAIL" and v["inputs"]["status"] == "FAIL" and "reproduction" not in v and v["inputs"]["names"] == STRICT10
    with pytest.raises(SystemExit) as e:                                                   # (4) a fingerprint that is not the parquet's
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d, expect=_expect(d, rows=len(d) + 1)))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["inputs"]["status"] == "FAIL" and v["inputs"]["fingerprint"]["rows"] == len(d)
    with pytest.raises(SystemExit) as e:                                                   # (6) the parquet's stamp is not the module's constant
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d, known_at_h=36))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["stamp"]["status"] == "FAIL" and v["stamp"]["stamp_h_in_parquet"] == [48.0] and v["stamp"]["known_at_h"] == 36 and "reproduction" not in v
    _wiki_world(known_at_h=40)                                                             # (6) a stamp outside the two allowed values
    with pytest.raises(SystemExit) as e:
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d, known_at_h=40))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["stamp"]["status"] == "FAIL" and v["stamp"]["stamp_h_in_parquet"] == [40.0]
    d = _wiki_world()
    with pytest.raises(SystemExit) as e:                                                   # the nulls' admissibility
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d, shift_min=20, shift_floor=wx.SHIFT_FLOOR))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["nulls"]["status"] == "FAIL" and "reproduction" not in v
    sc = pd.read_parquet("output/ceiling_coinbase_members/screen.parquet")                 # (1) R62's saved screen does not match
    sc.assign(t=sc["t"] * 1.01).to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "FAIL" and v["reproduction"]["max_abs_diff"]["t"] > 1e-6 and "hand" not in v
    assert not Path("output/ceiling_wiki_members/screen.parquet").exists() and "VOID" in Path("output/ceiling_wiki_members.md").read_text()
    sc.to_parquet("output/ceiling_coinbase_members/screen.parquet", index=False)
    with pytest.raises(SystemExit) as e:                                                   # (5) a registered name among "the twelve"
        wx.run_r72(5.0, 2.0, "test", ["M04USDT"] + PAIRS[1:], **_kw72(saved, d))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["reproduction"]["status"] == "PASS" and v["hand"]["status"] == "PASS" and v["known_at"]["status"] == "PASS"
    assert v["strictness"]["status"] == "FAIL" and v["strictness"]["twelve_in_frame"] == ["M04USDT"] and v["strictness"]["proxy_in_frame"] == [] and v["strictness"]["tie_identical_series"]
    with pytest.raises(SystemExit) as e:                                                   # (3) the first block has 9 registered members (LATE is not among them)
        wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d, block_min_names=10))
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert e.value.code == 2 and v["strictness"]["status"] == "PASS" and v["coverage"]["status"] == "FAIL" and v["coverage"]["blocks_under_minimum"] == ["2023-05-03"] and v["coverage"]["covered_min"] == 9


# ---- the plant -----------------------------------------------------------------------------------------------------------------------------------
def test_a_planted_give_back_is_found_with_the_negative_sign_on_the_member_cells_with_the_tie_the_proxy_the_twelve_and_the_rows_beside(tmp_path):
    saved = _r62_saved(tmp_path)
    d = _wiki_world()
    before = {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in ("data/wiki_views.parquet", "wiki_articles_test.csv", "members.csv", "output/ceiling_coinbase_members/screen.parquet")}
    md = wx.run_r72(5.0, 2.0, "test", PAIRS, **_kw72(saved, d))
    assert {f: hashlib.md5(Path(f).read_bytes()).hexdigest() for f in before} == before
    v = json.loads(Path("output/ceiling_wiki_members/validity.json").read_text())
    assert v["status"] == "PASS" and v["inputs"]["status"] == "PASS" and v["inputs"]["n_names"] == 10 and v["inputs"]["proxy_row"] == ["M10USDT"] and v["inputs"]["fingerprint"]["views_sum"] == int(d["views"].sum())
    assert v["stamp"]["status"] == "PASS" and v["stamp"]["known_at_h"] == 48 and v["reproduction"]["rows_compared"] == v["reproduction"]["rows_r62"] > 60 and v["gate"]["bar_status"] == "PASS"
    assert v["hand"]["recomputed"] == 100 and v["hand"]["max_abs_diff"] < 1e-9 and v["hand"]["cells_with_a_value"] > 80
    assert v["known_at"]["cells_read_too_early"] == 0 and v["known_at"]["cells_older_than_carry"] == 0 and v["known_at"]["cells_without_a_used_hour"] == 0 and v["known_at"]["cells_with_a_value"] > 0
    assert v["membership"]["values_off_membership"] == 0 and v["membership"]["values_on"] < v["membership"]["values_before_the_mask"]
    assert v["coverage"]["blocks_scored"] == 2 and v["coverage"]["covered_min"] == 9 and v["coverage"]["covered_max"] == 10
    assert v["strictness"]["status"] == "PASS" and v["strictness"]["tie_in_frame"] == TIE and v["strictness"]["tie_identical_series"] and v["strictness"]["names_with_a_value"] == 10
    assert v["old_names"]["n"] == 9 and v["old_names"]["young"] == ["LATEUSDT"] and v["names_with_a_value"] == 10 and v["names_in_parquet"] == 10
    rows = pd.read_parquet("output/ceiling_wiki_members/screen.parquet")
    g = rows.set_index(["feature", "bet", "horizon"])
    r = g.loc[DEV, "relative", "1d"]
    assert r["ic"] < -0.2 and r["t"] < -4 and r["ic_F1"] < -0.2 and np.isnan(r["ic_F2"]) and bool(r["folds_same_sign"]) is False
    assert r["p_family"] == 1 / 6 and r["verdict"] == "NOT DETECTABLE" and r["bar_maker_twelve"] == cx.BAR_TWELVE and r["bar_taker_members"] > 0
    assert g.loc[DEV, "relative", "4h"]["verdict"] == "reported, not gated" and np.isnan(g.loc[DEV, "relative", "4h"]["p_fw_shift"]) and np.isfinite(g.loc[DEV, "relative", "1h"]["p_single_shift"])
    assert g.loc[DEV, "relative", "15m"]["verdict"] == "" and np.isnan(g.loc[DEV, "relative", "15m"]["p_single_shuffle"])
    for f_, word in ((LVL, "the level"), (OLD, "9 names whose article existed before F1"), (TWELVE_ROW, "6 strict articles")):
        rr = g.loc[f_, "relative", "1d"]
        assert word in rr["verdict"] and np.isnan(rr["p_family"]) and np.isfinite(rr["ic"]), f_
    px = g.loc[PROXY, "directional", "1d"]                                                      # one name: no cross-section, the directional bet only
    assert "M10USDT" in px["verdict"] and np.isfinite(px["ic"]) and np.isnan(g.loc[PROXY, "relative", "1d"]["ic"]) and np.isnan(px["p_family"])
    assert g.loc[OLD, "relative", "1d"]["ic"] < -0.2 and abs(g.loc[OLD, "relative", "1d"]["ic"] - r["ic"]) < 0.1        # the young name is one of ten
    r3 = g.loc[DEV3, "relative", "3d"]
    assert "3-day horizon" in r3["verdict"] and np.isfinite(r3["ic"]) and np.isfinite(r3["bar_taker_members"]) and (DEV3, "relative", "1d") not in g.index
    assert set(rows.loc[rows["feature"] == TWELVE_ROW, "horizon"]) == set(ceiling.HORIZONS) and np.isfinite(g.loc[TWELVE_ROW, "relative", "1d"]["ic"])
    assert "THINUSDT" not in v["inputs"]["names"] and "M10USDT" not in v["inputs"]["names"]
    null = pd.read_parquet("output/ceiling_wiki_members/null_shift.parquet")
    assert set(null["feature"]) == {DEV} and null["draw"].max() == 5 and set(null["horizon"]) == set(cx.HZ)
    names = pd.read_parquet("output/ceiling_wiki_members/names.parquet").set_index("symbol")
    assert set(names.index) == set(STRICT10) | {"M10USDT"} and names.loc["M10USDT", "role"].startswith("proxy") and (names.loc[STRICT10, "role"] == "registered").all()
    assert names.loc["M09USDT", "share_zero_views"] > 0.05 and (names.loc[[m for m in STRICT10 if m != "M09USDT"], "share_zero_views"] == 0).all()
    assert bool(names.loc["LATEUSDT", "old"]) is False and names.loc[[m for m in STRICT10 if m != "LATEUSDT"], "old"].all() and names.loc["LATEUSDT", "first_day"] == str(LATE_FIRST.date())
    assert names.loc["M01USDT", "article"] == "Terra (blockchain)" and names.loc["M01USDT", "source"] == "chain"
    # the tie: three columns with the same value wherever both are members
    fr = wx.frames_r72(STRICT10, ["M10USDT"], wiki.load("data/wiki_views.parquet"), SLICES, "members.csv", pd.Timestamp(START, tz="UTC"))
    both = fr["F"][DEV]["M01USDT"].notna() & fr["F"][DEV]["M02USDT"].notna()
    assert both.sum() > 1000 and (fr["F"][DEV]["M01USDT"][both] == fr["F"][DEV]["M02USDT"][both]).all()
    assert fr["F"][DEV]["M10USDT"].isna().all() and fr["Fx"][DEV]["M10USDT"].notna().any() and "THINUSDT" not in fr["cols"]
    blocks = pd.read_parquet("output/ceiling_wiki_members/blocks.parquet")
    assert len(blocks) == 2 and list(blocks["covered"]) == [9, 10] and blocks["ic_wiki_dev"].notna().all() and (blocks["ic_wiki_dev"] < 0).all()
    daily = pd.read_parquet("output/ceiling_wiki_members/ic_daily.parquet")
    assert set(daily["feature"]) == {DEV, LVL, OLD, PROXY, DEV3, TWELVE_ROW}
    assert "## Verdict by R72's gate" in md and "the zero-view share" in md and "sum of views" in md
