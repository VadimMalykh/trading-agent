"""ft2 events (P8, PLAN §9 #8): the unlock page read from its embedded data (gzip or not, old events without a type), cliffs
summed to one event a protocol-day, a perpetual's ticker, Binance's titles read into kinds and contracts, the known-at
classification of a snapshot against today's schedule and the point-in-time status of an event — no network."""
import gzip
import json

import pandas as pd
import pytest

from ft2 import events

D = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
TS = lambda s: D(s).timestamp()  # noqa: E731


def _proto(pid, sym, evs, max_supply=1000.0, **kw):
    return {"protocolId": pid, "name": f"P{pid}", "tSymbol": sym, "gecko_id": None, "maxSupply": max_supply, "events": evs, **kw}


def _cliff(day, tokens, rec="Investors", typed=True):
    e = {"description": f"A cliff of {{tokens[0]}} tokens was unlocked from {rec} on {{timestamp}}", "timestamp": TS(day), "noOfTokens": [tokens]}
    return {**e, "category": "privateSale", "unlockType": "cliff"} if typed else e


def _linear(day, a, b):
    return {"description": "Linear unlock was increased from {tokens[0]} to {tokens[1]} tokens per week from Team on {timestamp}", "timestamp": TS(day), "noOfTokens": [a, b]}


def _page(protocols):
    return ('<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"data": protocols}}}) + "</script></html>").encode()


def test_the_page_is_read_gzipped_or_not_and_refused_when_it_is_not_the_page():
    ps = [_proto("1", "aaa", [_cliff("2024-03-01", 10.0)])]
    assert events.parse_page(_page(ps)) == ps and events.parse_page(gzip.compress(_page(ps))) == ps
    with pytest.raises(ValueError):
        events.parse_page(b"<html>blocked</html>")
    with pytest.raises(ValueError):
        events.parse_page(_page([]))
    assert events.parse_index(json.dumps({"data": ps}).encode()) == ps


def test_schedule_tells_cliffs_from_linear_changes_and_sums_a_day():
    ps = [_proto("1", "aaa", [_cliff("2024-03-01 06:00", 10.0, typed=False), _cliff("2024-03-01 18:00", 5.0, rec="Team"), _linear("2024-03-01", 0, 7.0),
                              {**_cliff("2024-04-01", 2.0), "timestamp": str(TS("2024-04-01"))}, {"description": "x", "timestamp": None, "noOfTokens": [1]}]),
          _proto("2", None, [], tokenPrice=[{"symbol": "bbb"}])]
    s = events.schedule(ps)
    assert len(s) == 4 and list(s["kind"]) == ["cliff", "cliff", "linear", "cliff"]              # an untyped event is a cliff unless it says "Linear unlock"; a timestamp as text is read; none is dropped
    assert list(s["recipient"]) == ["Investors", "Team", "Team", "Investors"] and s["symbol"].eq("AAA").all()
    assert s["tokens"].tolist() == [10.0, 5.0, 7.0, 2.0]                                         # a linear change carries the new weekly rate
    c = events.cliff_days(s)
    assert len(c) == 2 and c["tokens"].tolist() == [15.0, 2.0] and c["pct_max"].tolist() == [1.5, 0.2]
    assert c["day"].iloc[0] == D("2024-03-01") and c["recipients"].iloc[0] == "Investors; Team"
    assert events._symbol(ps[1]) == "BBB"


def test_a_perpetuals_ticker():
    assert [events.base(x) for x in ("1000PEPEUSDT", "ARBUSDT", "1000000MOGUSDT", "1MBABYDOGEUSDT", "1INCHUSDT", "BTCUSDC")] == ["PEPE", "ARB", "MOG", "BABYDOGE", "1INCH", "BTC"]


TITLES = [
    (48, "Binance Futures Will Launch USDT-Margined CELO & AR Perpetual Contracts with Up to 25X Leverage", "perp_launch", ["CELO", "AR"]),
    (48, "Binance Futures Will Launch USDⓈ-Margined COOKIEUSDT, ALCHUSDT, and SWARMSUSDT Perpetual Contracts With up to 75x Leverage", "perp_launch", ["COOKIE", "ALCH", "SWARMS"]),
    (48, "Binance Futures Will Launch USDⓈ-M OXT Perpetual Contract With Up to 20x Leverage", "perp_launch", ["OXT"]),
    (48, "Binance Futures Will Launch COMP/USDT Perpetual Contract With Up to 50x Leverage", "perp_launch", ["COMP"]),
    (48, "Binance Futures Launches XRP/USDT Perpetual Contract With Up to 75x Leverage", "perp_launch", ["XRP"]),
    (48, "Sapien (SAPIEN) Will Be Available on Binance Alpha and Binance Futures (2025-08-20)", "perp_launch", ["SAPIEN"]),
    (48, "Binance Will Add KAITO (KAITO) on Earn, Buy Crypto, Convert, Margin & Futures", "perp_launch", ["KAITO"]),
    (48, "Binance Futures Will Launch USDⓈ-Margined OPNUSDT Perpetual Contract Pre-Market Trading (2026-02-21)", "perp_launch", ["OPN"]),
    (48, "Binance Futures Will Launch EGLD, SOL, ICX and BTT USDT-Margined Perpetual Contracts With Up to 50x Leverage", "perp_launch", ["EGLD", "SOL", "ICX", "BTT"]),
    (48, "Binance Will Enable Isolated Margin Trading and Launch a USDT-Margined Perpetual Contract with Up to 20X Leverage for 1INCH", "perp_launch", ["1INCH"]),
    (48, "Binance Futures Will Launch USDC-Margined BCH and WIF Perpetual Contracts With Up to 75x Leverage", "perp_other", []),
    (48, "Humanity Protocol (H) Will Be Available on Binance Alpha and Binance Futures (2025-06-25)", "perp_launch", ["H"]),
    (48, "Binance Adds LayerZero (ZRO) on Earn, Buy Crypto, Convert, Margin & Futures", "perp_launch", ["ZRO"]),
    (48, "Binance Futures Will Launch BUSD-Margined AVAX Perpetual Contracts with Up to 20X Leverage", "perp_other", []),
    (48, "Binance Futures Copy Trading Adds New USDⓈ-M Perpetual Contracts (2024-12-18)", "other", []),
    (48, "Binance Futures Will Launch USDⓈ-Margined ALL Composite Index Perpetual Contract with Up to 75x Leverage (2025-08-06)", "other", []),
    (48, "Binance Futures Will Launch USDⓈ-M APTBUSD and COIN-M APTUSD Perpetual Contracts", "perp_other", []),
    (48, "Binance Futures Will Launch Multiple USDⓈ-Margined TradFi Perpetual Contracts (2026-07-21)", "other", []),
    (48, "Binance Futures Will List Coin-Margined Quarterly 1229 Futures Contracts", "other", []),
    (48, "BTT USDT-Margined Perpetual Contract Listing is Cancelled", "other", []),
    (48, "Binance Will List Notcoin (NOT) with Seed Tag Applied", "spot_list", ["NOT"]),
    (48, "Introducing Thena (THE) on Binance HODLer Airdrops! Subscribe your BNB to Simple Earn", "spot_list", ["THE"]),
    (48, "Notice on New Trading Pairs & Trading Bots Services on Binance Spot - 2025-08-12", "other", []),
    (161, "Binance Futures Will Delist 1000BTTC and YFII USDT-Margined Contracts", "perp_delist", ["1000BTTC", "YFII"]),
    (161, "Binance Futures Will Delist USDT-Margined ANC Perpetual Contract", "perp_delist", ["ANC"]),
    (161, "Binance Futures Will Delist RAYUSDT and SRMUSDT Perpetual Futures Contracts", "perp_delist", ["RAY", "SRM"]),
    (161, "Binance Futures Will Delist USDⓈ-M DEFIUSDT and MEMEFI Perpetual Contracts (2025-08-11)", "perp_delist", ["DEFI", "MEMEFI"]),
    (161, "Binance Futures Will Delist USDⓈ-Margined IPUSDT and IPUSDC Perpetual Contracts (2026-06-28)", "perp_delist", ["IP"]),
    (161, "Binance Futures Will Delist USDⓈ-M SLERFUSDT and COIN-M CHZUSD Perpetual Contracts (2025-10-20 & 2025-10-21)", "perp_delist", ["SLERF"]),
    (161, "Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts (2026-10-05)", "perp_delist", []),
    (161, "Binance Futures Will Delist FTTBUSD USDT-Margined Contract", "perp_other", []),
    (161, "Binance Futures Will Delist and Update the Leverage & Margin Tiers of USDⓈ-M 1000SHIBBUSD Perpetual Contract", "perp_other", []),
    (161, "Binance Futures Will Delist CRV Coin-Margined Perpetual Contract", "perp_other", []),
    (161, "Delisting of USDⓈ-M OMGUSDT Perpetual Contract Postponed", "other", []),
    (161, "Binance Will Delist DEGO, DENT, TRU on 2026-04-28", "spot_delist", ["DEGO", "DENT", "TRU"]),
    (161, "Binance Will Delist MCO (MCO) on 2020/11/02", "spot_delist", ["MCO"]),
    (161, "Notice of Removal of Margin Trading Pairs - 2024-08-22", "other", []),
    (49, "Binance Will Extend the Monitoring Tag to Include ACA, CHESS and NKN on 2025-06-05", "monitoring", ["ACA", "CHESS", "NKN"]),
    (49, "Binance Completes Maintenance", "other", []),
]


@pytest.mark.parametrize("catalog,title,kind,syms", TITLES)
def test_a_title_is_read_into_its_kind_and_contracts(catalog, title, kind, syms):
    assert events.parse_title(title, catalog) == (kind, syms)


def test_announcements_explode_tickers_and_read_a_multiple_article_from_its_summary():
    lists = {161: [{"id": 1, "code": "c1", "title": "Binance Futures Will Delist Multiple USDⓈ-M Perpetual Contracts (2026-10-05)", "releaseDate": int(TS("2026-10-01 02:45") * 1000)},
                   {"id": 2, "code": "c2", "title": "Notice of Removal of Margin Trading Pairs - 2024-08-22", "releaseDate": int(TS("2024-08-14 04:00") * 1000)}],
             48: [{"id": 3, "code": "c3", "title": "Binance Futures Will Launch USDT-Margined CELO & AR Perpetual Contracts with Up to 25X Leverage", "releaseDate": int(TS("2021-09-24 08:53") * 1000)}]}
    det = {"c1": {"seoDesc": "settlement as below: 2026-10-05 09:00 (UTC): USDⓈ-M PROMPTUSDT, PUMPBTCUSDT and 1000000BOBUSDT", "body": "e.g. BTCUSDT"}}
    a = events.announcements(lists, det)
    assert a[a["id"] == 1]["symbol"].tolist() == ["1000000BOB", "PROMPT", "PUMPBTC"] and (a[a["id"] == 1]["effective"] == D("2026-10-05")).all()
    assert a[a["id"] == 2]["symbol"].tolist() == [""] and a[a["id"] == 2]["kind"].iloc[0] == "other"         # an article with no ticker keeps its row
    assert a[a["id"] == 3]["symbol"].tolist() == ["AR", "CELO"] and a[a["id"] == 3]["release"].iloc[0] == D("2021-09-24 08:53")
    assert a["release"].is_monotonic_increasing
    assert events.announcements(lists)[lambda x: x["id"] == 1]["symbol"].tolist() == [""]                    # without the article the tickers are not invented


def _cd(rows, asof=None):
    df = pd.DataFrame(rows, columns=["pid", "day", "tokens"]).assign(max_supply=1000.0)
    df["day"] = pd.to_datetime(df["day"], utc=True)
    df["pct_max"] = 100 * df["tokens"] / df["max_supply"]
    return df.assign(asof=D(asof)) if asof else df


def test_known_at_classifies_what_followed_a_snapshot_and_what_the_snapshot_promised():
    final = _cd([("1", "2024-03-10", 50.0), ("1", "2024-03-20", 50.0), ("1", "2024-04-25", 30.0), ("1", "2024-03-25", 80.0), ("2", "2024-03-12", 40.0), ("1", "2024-03-15", 0.5)])
    snap = _cd([("1", "2024-03-11", 51.0),        # the 10th: a day off, 2 % off → same
                ("1", "2024-03-20", 20.0),        # the 20th: the day, another size → amount
                ("1", "2024-04-05", 30.0),        # the 25 Apr cliff stood at 5 Apr → moved (it is in the 30–90 d window of today's schedule)
                ("1", "2024-03-18", 99.0)],       # promised, and not in today's schedule as dated
               asof="2024-03-01")
    k = events.known_at(snap, final).set_index("window")
    a = k.loc["0-30d"]
    assert (a["protocols"], a["final"], a["same"], a["amount"], a["moved"], a["absent"]) == (1, 3, 1, 1, 0, 1)   # protocol 2 is not on the page: not counted; the 0.05 % cliff is dust; the 25 Mar cliff was absent
    assert (a["snap"], a["snap_unmatched"]) == (3, 2)                                                            # the 20-token and the 99-token cliffs are not in today's schedule as dated
    b = k.loc["30-90d"]
    assert (b["final"], b["moved"], b["snap"], b["snap_unmatched"]) == (1, 1, 1, 1)


def test_point_in_time_uses_the_last_snapshot_a_week_before_the_event():
    final = _cd([("1", "2024-03-10", 50.0), ("2", "2024-03-10", 40.0), ("1", "2024-01-05", 10.0), ("1", "2024-03-30", 60.0), ("3", "2024-03-30", 60.0)])
    asof = pd.concat([_cd([("1", "2024-03-10", 50.0)], asof="2024-02-01"),                                       # the old page had the 10 Mar cliff and nothing of the 30th
                      _cd([("1", "2024-03-30", 60.0), ("3", "2024-04-02", 60.0)], asof="2024-03-08")])           # the page of 8 Mar: too late for the 10th, in time for the 30th
    covered = {D("2024-02-01"): {"1"}, D("2024-03-08"): {"1", "3"}}
    st = events.point_in_time(asof, final, covered)
    assert st.tolist() == ["same", "uncovered", "no_snapshot", "same", "moved"]
    assert events.point_in_time(asof, final, covered, lead=pd.Timedelta(days=1)).tolist() == ["absent", "uncovered", "no_snapshot", "same", "moved"]   # a day's lead reads the 8 Mar page for the 10th, which no longer lists it as coming


def test_events_on_a_member_count_only_inside_its_block():
    mem = pd.DataFrame({"universe": "f12", "block": [D("2024-03-01"), D("2024-03-31")], "symbol": ["1000PEPEUSDT", "ARBUSDT"]}).assign(ticker=lambda x: x["symbol"].map(events.base))
    ev = pd.DataFrame({"key": ["PEPE", "PEPE", "ARB", "ARB"], "day": [D("2024-03-05"), D("2024-04-02"), D("2024-03-05"), D("2024-04-29")]})
    j = events.in_blocks(ev, "day", mem)
    assert j[["key", "day", "perp"]].values.tolist() == [["PEPE", D("2024-03-05"), "1000PEPEUSDT"], ["ARB", D("2024-04-29"), "ARBUSDT"]]
    assert len(events.in_blocks(ev.assign(key="1000PEPEUSDT"), "day", mem, on="perp")) == 2                      # by the contract: the two days inside PEPE's block
    assert events.fold_of(pd.Series([D("2019-01-01"), D("2023-06-01"), D("2024-09-01"), D("2026-10-01")])).tolist() == ["before FP", "F1", "F3", "after F5"]
