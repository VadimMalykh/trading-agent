"""ft2 etf (P8 B3′, PLAN §9 #7): Farside's table read with its conventions (parentheses, dashes, commas, the seed and footer
rows, the day in progress), the funds summing to the total or the page refused; the ingest's holiday flag; the known-at
classification of a live snapshot against the final table, no network."""
import numpy as np
import pandas as pd
import pytest

from ft2 import etf


def _page(rows, funds=("IBIT", "FBTC", "GBTC"), extra_header="", footer=True, live=False):
    th = "".join(f'<th><div align="right"><span class="tabletext">{f}</span></div></th>' for f in funds)
    logos = "".join('<th><div align="center"><img src="x.jpg"></div></th>' for _ in funds) if live else ""
    head = (f'<tr><th><span class="tabletext">&nbsp;&nbsp;</span></th>{logos}<th>Total</th></tr>' if live else "") + \
        f'<tr><th><span class="tabletext">Date</span></th>{th}<th><div align="right"><span class="tabletext">Total</span></div></th></tr>' + extra_header
    body = ""
    for r in rows:
        tds = "".join(f'<td><div align="right"><span class="tabletext">{c}</span></div></td>' for c in r[1:])
        body += f'<tr><td><span class="tabletext">{r[0]}</span></td>{tds}</tr>'
    if footer:
        body += '<tr><td><span class="tabletext">Total</span></td>' + "".join('<td><span class="tabletext">1.0</span></td>' for _ in range(len(funds) + 1)) + "</tr>"
    return f'<html><body><p>Flows (US$m)</p><table class="etf"><thead>{head}</thead><tbody>{body}</tbody></table></body></html>'.encode()


ROWS = [("11 Jan 2024", "111.7", "227.0", '<span class="redFont">(95.1)</span>', "243.6"),
        ("12 Jan 2024", "1,386.0", "-", "(484.1)", "901.9"),
        ("15 Jan 2024", "-", "-", "-", "0.0"),                                                           # a US holiday: every fund blank, kept
        ("16 Jan 2024", "-", "-", "-", "0.0")]                                                           # the last row blank: the day in progress, dropped


def test_parse_reads_farsides_conventions_and_drops_the_day_in_progress():
    df = etf.parse(_page(ROWS))
    assert list(df.columns) == ["day", "IBIT", "FBTC", "GBTC", "Total"] and len(df) == 3                 # the blank 16 Jan is the day in progress
    assert df[["IBIT", "FBTC", "GBTC"]].iloc[2].isna().all() and df["Total"].iloc[2] == 0.0             # the holiday row stays
    assert df["day"].iloc[0] == pd.Timestamp("2024-01-11", tz="UTC") and df["day"].is_monotonic_increasing
    r = df.set_index("day").loc[pd.Timestamp("2024-01-12", tz="UTC")]
    assert r["IBIT"] == 1386.0 and np.isnan(r["FBTC"]) and r["GBTC"] == -484.1 and r["Total"] == 901.9
    assert df.set_index("day").loc[pd.Timestamp("2024-01-11", tz="UTC"), "GBTC"] == -95.1
    seed = '<tr><th>Fee</th><th>0.25%</th><th>0.25%</th><th>1.50%</th><th></th></tr>'
    seeded = [("Seed", "10.6", "4.4", "9,199.3*", "9,214.3"), *ROWS]
    assert etf.parse(_page(seeded, extra_header=seed)).equals(df)                                        # ETH's fee row and seed row are not days
    live = etf.parse(_page(ROWS, live=True))
    assert live.equals(df)                                                                                 # the live page's logo row does not shift the tickers
    old = _page(ROWS, live=True).replace(b"<th>Total</th>", b"").replace(b'<th><span class="tabletext">Date</span></th>', b'<th><span class="tabletext">Date</span></th><th>Total</th>')
    assert etf.parse(old).equals(df)                                                                       # a 2024 live page names Total before the tickers; the total is still the last cell
    with pytest.raises(ValueError):
        etf.parse(_page([("11 Jan 2024", "100.0", "200.0", "0.0", "250.0")]))                              # funds do not sum to the total
    with pytest.raises(ValueError):
        etf.parse(b"<html><body>nothing</body></html>")
    with pytest.raises(ValueError):
        etf.parse(_page([*ROWS, ("11 Jan 2024", "1.0", "1.0", "1.0", "3.0")]))                             # a day twice


def test_ingest_flags_the_holidays_from_the_btc_table_and_lends_them_to_eth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(etf, "RAW", tmp_path / "raw")
    monkeypatch.setattr(etf, "OUT", tmp_path / "data" / "etf_flows.parquet")
    etf.RAW.mkdir()
    (etf.RAW / "BTC_all_20260101.html").write_bytes(_page(ROWS[:2]))
    (etf.RAW / "BTC_all_20260102.html").write_bytes(_page(ROWS))                                           # the latest copy is the one read
    eth_rows = [("11 Jan 2024", "5.0", "-", "(2.0)", "3.0"), ("12 Jan 2024", "0.0", "0.0", "0.0", "0.0"), ("16 Jan 2024", "0.0", "0.0", "0.0", "0.0")]
    (etf.RAW / "ETH_all_20260102.html").write_bytes(_page(eth_rows, funds=("ETHA", "FETH", "ETHE")))
    r = etf.ingest()
    x = etf.load()
    assert r["days"] == {"BTC": 3, "ETH": 3} and set(x["fund"]) == {"IBIT", "FBTC", "GBTC", "ETHA", "FETH", "ETHE", "Total"}
    b = x[(x["asset"] == "BTC") & (x["fund"] == "Total")].set_index("day")
    assert b["holiday"].to_dict() == {pd.Timestamp("2024-01-11", tz="UTC"): False, pd.Timestamp("2024-01-12", tz="UTC"): False, pd.Timestamp("2024-01-15", tz="UTC"): True}
    e = x[(x["asset"] == "ETH") & (x["fund"] == "Total")].set_index("day")["holiday"]
    assert not e[pd.Timestamp("2024-01-12", tz="UTC")] and not e[pd.Timestamp("2024-01-16", tz="UTC")]   # a real zero day on ETH is not a holiday
    t = etf.totals("BTC")
    assert list(t.round(1)) == [243.6, 901.9] and etf.totals("ETH").to_dict()[pd.Timestamp("2024-01-16", tz="UTC")] == 0.0
    assert etf.load().query("asset == 'ETH' and fund == 'Total'")["day"].nunique() == 3


def test_known_at_classifies_a_live_snapshot_against_the_final_table():
    final = etf.parse(_page(ROWS))
    d11, d12 = pd.Timestamp("2024-01-11", tz="UTC"), pd.Timestamp("2024-01-12", tz="UTC")
    snaps = {"20240112020000": etf.parse(_page(ROWS[:1])),                                                  # 02:00 UTC on the 12th: the 11th's row, final
             "20240112230000": etf.parse(_page([ROWS[0], ("12 Jan 2024", "1,000.0", "-", "-", "1000.0")])),  # 23:00 on the 12th: the 12th's session closed, row partial
             "20240113030000": etf.parse(_page(ROWS[:2])),                                                  # 03:00 on the 13th: the 12th, final
             "20240113120000": etf.parse(_page(ROWS[:1]))}                                                  # 12:00 on the 13th: the 12th's row absent
    k = etf.known_at(snaps, final).set_index("snapshot")
    assert list(k["day"]) == [d11, d12, d12, d12] and list(k["has_row"]) == [True, True, True, False] and list(k["final"]) == [True, False, True, False]
    assert np.isclose(k["hours_after_close"].iloc[0], 5.0) and np.isclose(k["hours_after_close"].iloc[1], 2.0) and np.isclose(k["hours_after_close"].iloc[3], 15.0)
    assert k["live_total"].iloc[1] == 1000.0 and k["final_total"].iloc[1] == 901.9
    assert etf.known_at({"20240110120000": etf.parse(_page(ROWS[:1]))}, final).empty                       # before the first day: nothing to compare


def test_sample_spreads_a_few_snapshots_over_each_hour():
    stamps = [f"2024{m:02d}{d:02d}{h:02d}0000" for m in (8, 9, 10) for d in (1, 15) for h in (3, 12)]      # six per hour, two hours
    out = etf.sample(stamps, 3)
    assert len(out) == 6 and {s[8:10] for s in out} == {"03", "12"} and out[0] == "20240801030000" and out[2] == "20241015030000"
    assert etf.sample(stamps, None) == sorted(stamps, key=lambda s: (s[8:10], s)) and etf.sample(stamps, 3, {12}) == out[3:]
