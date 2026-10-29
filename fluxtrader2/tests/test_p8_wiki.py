"""BP1 — Wikipedia's pageviews per name as a source: the names, the candidate articles and the pick, the probe, the fetch → parquet → audit on planted answers."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from ft2 import wiki


def _plant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wiki, "RAW", tmp_path / "data" / "raw" / "external" / "wikipedia")
    monkeypatch.setattr(wiki, "PARQUET", tmp_path / "data" / "wiki_views.parquet")
    monkeypatch.setattr(wiki, "ARTICLES", tmp_path / "wiki_articles.csv")
    monkeypatch.setattr(wiki, "OUT", tmp_path / "output" / "wiki_audit.md")
    monkeypatch.setattr(wiki, "NAMES_CSV", tmp_path / "output" / "wiki_names.csv")
    monkeypatch.setattr(wiki, "CANDIDATES_CSV", tmp_path / "output" / "wiki_candidates.csv")
    monkeypatch.setattr(wiki, "PICK_CSV", tmp_path / "output" / "wiki_pick.csv")
    monkeypatch.setattr(wiki.time, "sleep", lambda s: None)
    monkeypatch.setattr(wiki, "bases", lambda: pd.DataFrame({"base": ["ARB", "BTC", "ZZZ"], "symbols": ["ARBUSDT", "BTCUSDT", "ZZZUSDT"],
                                                              "twelve": [False, True, False], "F1+F2": [True, False, True], "F3+F4": [True, False, False]}))


def test_names_puts_the_venues_first_then_coingecko_by_rank(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    monkeypatch.setattr(wiki.krw, "markets_file", lambda U: pd.DataFrame({"symbol": ["BTCUSDT", "ARBUSDT"], "english_name": ["Bitcoin", None]}) if U["venue"] == "upbit" else None)

    def fake(u, **kw):
        if u == wiki.CG_LIST:
            return [{"id": "arbitrum", "symbol": "arb", "name": "Arbitrum"}, {"id": "arb-fake", "symbol": "arb", "name": "Arb Fake"},
                    {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin"}, {"id": "other", "symbol": "xyz", "name": "Other"}]
        if "coins/markets" in u:
            return [{"id": "bitcoin", "market_cap_rank": 1}, {"id": "arbitrum", "market_cap_rank": 50}] if "page=1" in u else []
        raise AssertionError(u)
    monkeypatch.setattr(wiki, "_get", fake)
    n = wiki.names(today=pd.Timestamp("2026-10-29", tz="UTC"))
    arb = n[n["base"] == "ARB"]
    assert arb["name"].tolist() == ["Arbitrum", "Arb Fake"] and arb["rank"].tolist() == [50, 10**6]      # the ranked first
    btc = n[n["base"] == "BTC"]
    assert btc["name"].tolist() == ["Bitcoin"] and btc["source"].tolist() == ["upbit"]                  # the venue's row kept, CoinGecko's duplicate dropped
    assert n[n["base"] == "ZZZ"]["name"].isna().all()                                                  # a base without a name stays a row
    assert (wiki.RAW / "coingecko_list_20261029.json").exists() and wiki.NAMES_CSV.exists()


def test_articles_resolves_redirects_hints_crypto_and_picks_the_venue_name_first(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    N = pd.DataFrame({"base": ["ARB", "ARB", "BTC", "ZZZ"], "name": ["Arbitrum", "Arb Fake", "Bitcoin", None], "source": ["upbit", "coingecko", "upbit", None]})
    pages = {"Arbitrum": ("Arbitrum", "Arbitrum is a layer 2 blockchain for Ethereum."), "Arb Fake": None, "Bitcoin": ("Bitcoin", "Bitcoin is a cryptocurrency."),
             "Arbitrum (cryptocurrency)": ("Arbitrum", "Arbitrum is a layer 2 blockchain for Ethereum."), "Arb": ("Arb (band)", "Arb are a rock band.")}

    def fake_wp(params):
        if params.get("list") == "search":
            return {"query": {"search": [{"title": "Arb"}]}} if "Arbitrum" in params["srsearch"] else {"query": {"search": []}}
        titles = params["titles"].split("|")
        q = {"redirects": [], "normalized": [], "pages": []}
        for t in titles:
            p = pages.get(t)
            if p is None:
                q["pages"].append({"title": t, "missing": True})
            else:
                if p[0] != t:
                    q["redirects"].append({"from": t, "to": p[0]})
                if not any(x["title"] == p[0] for x in q["pages"]):
                    q["pages"].append({"title": p[0], "extract": p[1]})
        return {"query": q}
    monkeypatch.setattr(wiki, "_wp", fake_wp)
    C = wiki.articles(N)
    arb = C[C["base"] == "ARB"]
    assert arb[arb["candidate"] == "Arbitrum (cryptocurrency)"]["title"].iloc[0] == "Arbitrum"          # the redirect followed
    assert not arb[arb["candidate"] == "Arb Fake"]["exists"].iloc[0]
    assert arb[arb["candidate"] == "Arb"]["exists"].iloc[0] and not arb[arb["candidate"] == "Arb"]["crypto_hint"].iloc[0]   # a band is not a hint
    P = pd.read_csv(wiki.PICK_CSV).fillna("")
    assert P.set_index("base").loc["ARB", "pick"] == "Arbitrum" and P.set_index("base").loc["ARB", "how"] == "upbit"
    assert P.set_index("base").loc["BTC", "pick"] == "Bitcoin"
    assert P.set_index("base").loc["ZZZ", "pick"] == "" and P.set_index("base").loc["ZZZ", "how"] == "none"


def test_probe_reads_the_last_day_present_against_the_servers_date(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    body = {"items": [{"timestamp": "2026102700", "views": 1}, {"timestamp": "2026102800", "views": 2}]}
    monkeypatch.setattr(wiki, "_get", lambda u, **kw: (body, {"Date": "Thu, 29 Oct 2026 19:38:18 GMT"}))
    r = wiki.probe(now=pd.Timestamp("2026-10-29 19:38", tz="UTC"))
    assert r["last_day_present"] == "2026-10-28" and abs(r["hours_after_that_day_ended"] - 19.64) < 0.01 and r["days_returned"] == 2
    assert len(wiki.probes()) == 1 and wiki.probes()[0]["server_date"].startswith("2026-10-29 19:38")


def test_fetch_ingest_and_audit_on_planted_views(tmp_path, monkeypatch):
    _plant(tmp_path, monkeypatch)
    pd.DataFrame({"base": ["ARB", "BTC", "ZZZ"], "article": ["Arbitrum", "Bitcoin", ""], "source": ["upbit", "upbit", ""], "note": ["", "", "no article"]}).to_csv(wiki.ARTICLES, index=False)
    days = pd.date_range("2023-04-01", "2023-07-01", freq="D", inclusive="left", tz="UTC")

    def fake(u, **kw):
        art = u.split("/user/")[1].split("/")[0]
        if art == "Arbitrum":        # created 2023-05-10, a day without data on 05-20 (the API omits it)
            return {"items": [{"timestamp": f"{d:%Y%m%d}00", "views": 100 + i} for i, d in enumerate(days) if d >= pd.Timestamp("2023-05-10", tz="UTC") and d.day != 20]}
        return {"items": [{"timestamp": f"{d:%Y%m%d}00", "views": 1000} for d in days]}
    monkeypatch.setattr(wiki, "_get", fake)
    monkeypatch.setattr(wiki, "_wp", lambda params: {"query": {"pages": [{"title": params["titles"], "revisions": [{"timestamp": "2023-05-10T08:00:00Z" if params["titles"] == "Arbitrum" else "2009-03-08T00:00:00Z"}]}]}})
    t = wiki.fetch("2023-04-01", "2023-07-01")
    assert t["ok"] == 2 and t["created"] == 2 and t["skip"] == 0
    assert wiki.fetch("2023-04-01", "2023-07-01")["skip"] == 2                                          # resumable
    r = wiki.ingest("2023-04-01", "2023-07-01")
    d = wiki.load(wiki.PARQUET)
    arb = d[d["base"] == "ARB"].set_index("day")
    assert str(arb.index.min().date()) == "2023-05-10" and len(arb) == (pd.Timestamp("2023-07-01") - pd.Timestamp("2023-05-10")).days   # from the creation, every day
    assert arb.loc[pd.Timestamp("2023-05-20", tz="UTC"), "views"] == 0 and not arb.loc[pd.Timestamp("2023-05-20", tz="UTC"), "present"]   # the omitted day a zero, marked
    assert (d["ts_known"] - d["day"] == pd.Timedelta(hours=48)).all() and r["symbols"] == 2 and "ZZZ" not in set(d["base"])
    (wiki.RAW / "probe_20261029T1938.json").write_text(json.dumps({"article": "Bitcoin", "server_date": "2026-10-29 19:38:18+00:00", "last_day_present": "2026-10-28",
                                                                  "hours_after_that_day_ended": 19.6, "days_returned": 2, "asked": ["a", "b"], "views": {}}))
    monkeypatch.setattr(wiki.cb, "member_symbols", lambda: pd.DataFrame({"block": pd.to_datetime(["2023-05-03", "2023-05-03", "2023-06-02"], utc=True),
                                                                         "symbol": ["ARBUSDT", "ZZZUSDT", "ARBUSDT"], "folds": ["F1+F2"] * 3}))
    out = wiki.audit(today=pd.Timestamp("2026-10-29", tz="UTC"))
    j = json.loads((wiki.OUT.with_suffix(".json")).read_text())
    assert j["sets"]["F1+F2 members"] == {"bases": 2, "with_article": 1, "share": 0.5, "strict": 1, "share_strict": 0.5} and j["sets"]["twelve"]["with_article"] == 1
    b = {x["block"]: x for x in j["blocks"]}
    assert b["2023-05-03"]["with_article"] == 1 and b["2023-05-03"]["strict"] == 1 and b["2023-05-03"]["article_live_at_block_start"] == 0   # created 05-10, after the block's start
    assert b["2023-06-02"]["article_live_at_block_start"] == 1
    assert j["probes"][0]["last_day_present"] == "2026-10-28"
    per = {x["base"]: x for x in j["per_base"]}
    assert per["ARB"]["created"] == "2023-05-10" and per["ZZZ"]["days"] == 0 and 0 < per["ARB"]["cover_F1"] < 1
    assert "The covered bases" in open(out).read()
