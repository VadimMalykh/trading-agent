"""R55 (`ft2/straddle.py`, `ft2/varbook.py`): a planted market — the one-day straddle priced at 50 % vol every day, days that move 6 %
and days that move 0.3 %, R54's stand-in forecast naming them — the fetch keeps one JSON a day, the ingest takes the LAST trade before
00:00 (a planted trade at 00:00 changes nothing), the settlement is the 07:30 → 07:59 TWAP (a planted 08:30 bar changes nothing), the
stale and untraded days are skipped and counted, the touch is read from the free-day quotes, and the read funds the sign."""
import gzip
import json
import re
import urllib.parse

import numpy as np
import pandas as pd

from ft2 import optsrc
from ft2 import straddle as st
from ft2 import varbook as vb

S0 = {"BTC": 30000.0, "ETH": 2000.0}
SIG_Q = 0.5
M = 0.8 * SIG_Q * np.sqrt(32 / 8760)                 # the straddle's price in units of spot (≈ 0.0242)
START, END = "2023-05-01", "2023-05-31"              # 30 days of F1
HOUR, MIN = 3_600_000, 60_000


def _day_index(ms):
    return (ms - int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)) // 86_400_000


def _amp(i):
    """Day i's move over the 32 hours: ± 6 % on even days (the 'high' days), ± 0.3 % on odd days."""
    return (0.06 if i % 2 == 0 else 0.003) * (1 if (i // 2) % 2 == 0 else -1)


def _perp(cur, s_ms, e_ms):
    ticks = list(range(s_ms, e_ms + 1, MIN))
    d0 = s_ms
    i = _day_index(d0)
    a = _amp(i)
    n = 32 * 60
    px = [S0[cur] * (1 + a * min(k, n - 60) / (n - 60)) for k in range(len(ticks))]      # flat over the last hour: the settlement window
    ticks.append(d0 + 32 * HOUR + 30 * MIN)            # a planted bar at 08:30 of d + 1 — must change nothing
    px.append(S0[cur] * 3)
    return {"status": "ok", "ticks": ticks, "open": px, "close": px, "high": px, "low": px, "volume": [1.0] * len(ticks), "cost": [1.0] * len(ticks)}


def _leg(cur, name, s_ms, e_ms):
    m = re.match(rf"{cur}-(\d{{1,2}}[A-Z]{{3}}\d{{2}})-(\d+)-([CP])$", name)
    k = int(m.group(2))
    if k != int(S0[cur]):
        return {"status": "no_data"}                   # only the at-the-money strike exists
    ticks = list(range(s_ms, e_ms, HOUR))
    d0 = s_ms + 24 * HOUR
    i = _day_index(d0)
    px, vol = [], []
    for t in ticks:
        if t == d0 - 2 * HOUR:                        # the last trade before 00:00: the bar 22:00 → 23:00 of d − 1
            px.append(M / 2 if not (i == 5 and m.group(3) == "C") else M)      # day 5: a stale call at twice its price → parity fails
            vol.append(0.0 if i == 7 else 1.0)         # day 7: no trade in the 24 h before → skipped
        elif t == d0:                                  # a planted trade AT 00:00 → 01:00 at ten times the price: must not be the entry
            px.append(M * 5)
            vol.append(1.0)
        else:
            px.append(M / 2)
            vol.append(0.0)
    return {"status": "ok", "ticks": ticks, "open": px, "close": px, "high": px, "low": px, "volume": vol, "cost": [p * v for p, v in zip(px, vol)]}


def _quotes_csv(name, day):
    d0 = int(day.timestamp() * 1e6)
    rows = ["exchange,symbol,timestamp,local_timestamp,ask_amount,ask_price,bid_price,bid_amount"]
    rows.append(f"deribit,{name},{d0 - 5_000_000},{d0 - 4_000_000},1,{M / 2 + 0.005},{M / 2 - 0.005},1")       # before midnight: wide, must not be read
    rows.append(f"deribit,{name},{d0 + 3_000_000},{d0 + 3_100_000},1,{M / 2 + 0.0005},{M / 2 - 0.0005},1")     # the first at or after 00:00: 10 bps a leg
    rows.append(f"deribit,{name},{d0 + 1_800_000_000},{d0 + 1_800_100_000},1,{M / 2 + 0.0005},{M / 2 - 0.0005},1")
    return gzip.compress("\n".join(rows).encode())


def fake_get(u, raw=False, timeout=120, retries=5, head_only=False):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    if "get_tradingview_chart_data" in u:
        name, s, e, res = q["instrument_name"][0], int(q["start_timestamp"][0]), int(q["end_timestamp"][0]), q["resolution"][0]
        cur = name.split("-")[0]
        if name.endswith("PERPETUAL"):
            return _perp(cur, s, e)
        return _leg(cur, name, s, e)
    if "datasets.tardis.dev" in u:
        m = re.search(r"/quotes/(\d{4})/(\d{2})/(\d{2})/(.+)\.csv\.gz", u)
        return _quotes_csv(m.group(4), pd.Timestamp(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", tz="UTC"))
    raise AssertionError(u)


def _r54_file(path):
    rows = []
    for cur, sym in st.NAMES.items():
        for i, d in enumerate(pd.date_range(START, END, freq="D", tz="UTC", inclusive="left")):
            hi = i % 2 == 0
            y = np.log(80.0 if hi else 30.0)
            for h in (1, 7):
                rows.append({"day": d, "y": y, "yhat_I": np.log(50.0), "yhat_C": y, "yhat_I+C": y + 0.05, "fold": "F1", "symbol": sym, "hold_days": h})
    pd.DataFrame(rows).to_csv(path, index=False)


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(optsrc, "_get", fake_get)
    monkeypatch.setattr(st, "PAUSE", 0.0)
    (tmp_path / "data").mkdir()
    (tmp_path / "output/magvol/f12").mkdir(parents=True)
    _r54_file(tmp_path / "output/magvol/f12/loss.csv")
    days = pd.date_range(START, END, freq="D", tz="UTC")
    pd.DataFrame([{"symbol": s, "day": d, "spread_cal_bps": 1.0} for s in st.NAMES.values() for d in days]).to_parquet("data/cost_daily.parquet", index=False)


def test_fetch_ingest_inventory_take_the_last_trade_before_midnight_and_skip_the_stale_days(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rep = st.fetch(start=START, end=END)
    assert rep == {"BTC": 30, "ETH": 30} and (st.RAW / "BTC" / "2023-05-01.json").exists()
    j = json.loads((st.RAW / "BTC" / "2023-05-03.json").read_text())
    assert j["strike"] == 30000 and j["legs"]["C"]["name"] == "BTC-4MAY23-30000-C" and j["spot_00"] == 30000.0
    st.quotes()
    assert (st.RAW_Q / "2023-05-01" / "BTC-2MAY23-30000-C.csv.gz").exists() and len(list(st.RAW_Q.glob("*/*.csv.gz"))) == 4
    st.ingest()
    d = pd.read_parquet(st.PARQUET)
    b = d[d["currency"] == "BTC"].set_index(pd.to_datetime(d.loc[d["currency"] == "BTC", "day"], utc=True))
    assert len(b) == 30 and b["covered"].sum() == 28
    ok = b[b["covered"]]
    assert np.allclose(ok["c_last"], M / 2) and np.allclose(ok["p_last"], M / 2)                       # the planted 00:00 trade at 5 M is not the entry
    assert (pd.to_datetime(ok["c_last_ts"], utc=True) == ok.index - pd.Timedelta(hours=1)).all()        # the bar 22:00 → 23:00 ends at 23:00
    assert b.loc["2023-05-06", "skip"] == "parity" and b.loc["2023-05-08", "skip"] == "a leg without a trade in the 24 h before"
    i3 = 2
    assert abs(b.loc["2023-05-03", "settle"] - S0["BTC"] * (1 + _amp(i3))) < 1e-6                     # the TWAP of a path already flat at 07:30 → 07:59; the 08:30 bar ignored
    h = pd.read_parquet(st.HEDGE)
    hb = h[(h["currency"] == "BTC") & (pd.to_datetime(h["day"], utc=True) == pd.Timestamp("2023-05-03", tz="UTC"))].sort_values("i")
    assert len(hb) == 33 and hb["price"].iloc[0] == S0["BTC"] and hb["price"].iloc[-1] == b.loc["2023-05-03", "settle"]
    t = pd.read_parquet(st.TOUCH)
    assert len(t) == 4 and np.allclose(t["ask"] - t["bid"], 0.001)
    sp = st.touch_spread(t)
    assert abs(sp["BTC"]["median_bps"] - 20) < 1e-6 and sp["BTC"]["days"] == 1
    txt = st.inventory()
    assert "| BTC | all | 30 |" in txt and "**straddle_1d**" in txt and "28 covered (93%)" in txt


def test_varbook_funds_the_planted_sign_and_its_formulas_hold(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    st.fetch(start=START, end=END)
    st.quotes()
    st.ingest()
    txt = vb.run("t")
    out = vb.OUT / "t"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["coverage"]["BTC"] > 0.9 and len(v["r54_loss_sha256"]) == 64, v
    days = pd.read_csv(out / "days.csv")
    assert np.allclose(days["payoff"], (days["settle"] - days["strike"]).abs() / days["spot"], atol=1e-12)
    assert np.allclose(days["sigma_q"], SIG_Q) and np.allclose(days["m"], M)
    hi = days[days["sign_I+C"] > 0]
    assert len(hi) and (hi["rv_real"] > 0.7).all() and (days.loc[days["sign_I+C"] < 0, "rv_real"] < 0.4).all()
    assert np.allclose(days["crossing"] * 1e4, 10.0) and np.allclose(days["fee_entry"], 2 * 0.0003) and np.allclose(days["fee_delivery"], 2 * 0.00015)
    rows = pd.read_csv(out / "rows.csv")
    fam = rows[rows["family"]].set_index("currency")
    assert len(fam) == 2 and (fam["gross"] > 0).all() and (fam["gross_t"] > 1.96).all() and set(fam["verdict"]) <= {"FUNDED", "REAL, NOT FUNDED"}
    assert fam.loc["BTC", "hit"] == 1.0
    assert set(rows["sign"]) == {"I+C", "I", "C", "short", "long"} and set(rows["accounting"]) == {"hedged", "unhedged"}
    assert "**FUNDED**" in txt or "**REAL, NOT FUNDED**" in txt
    # the formulas
    assert abs(vb.straddle_delta(np.array([30000.0]), 30000.0, 0.5, np.array([32.0]))[0]) < 0.05
    flat = np.full(33, 30000.0)
    pnl, cost, units = vb.hedge_leg(flat, 30000.0, 0.5, 0.0005)
    assert pnl == 0.0 and cost >= 0 and units >= 0
    assert abs(vb.breakeven_vol(M) - SIG_Q) < 1e-12
