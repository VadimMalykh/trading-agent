"""Decision CW1's Data line (`ft2/next60data.py`) on made-up files: what a list row needs is its own months and days and nothing later; the
row check passes when holes inside a name's old extent are filled and fails on a changed, a dropped old row or a dropped name; the tables
written a name at a time are `data.ingest_klines` / `ingest_metrics`' tables row for row."""
import zipfile

import numpy as np
import pandas as pd
import pytest

from ft2 import data, next60data as nd


def test_the_frozen_lists_and_what_a_row_needs():
    R = nd.rows()
    assert R.groupby("seg").size().to_dict() == {"pre": 944, "f12": 1080, "f34": 1020, "f5": 478}             # F5: the PERPETUAL rows only
    coins = pd.read_csv(nd.F5_COINS_CSV)
    f5 = pd.read_csv(nd.LISTS["f5"])
    pd.testing.assert_frame_equal(coins, f5[f5["type"] == "PERPETUAL"].reset_index(drop=True))
    assert ((R["b"] - R["a"]) <= nd.BLOCK).all() and (R["b"] > R["a"]).all()
    for seg, g in R.groupby("seg"):
        assert g["b"].max() <= nd.ENDS[seg]
    one = pd.DataFrame({"seg": ["pre", "f5"], "symbol": ["AAAUSDT", "BBBUSDT"], "a": pd.to_datetime(["2022-06-08", "2026-08-31"], utc=True),
                        "b": pd.to_datetime(["2022-07-08", "2026-09-15"], utc=True)})
    N = nd.need(one)
    assert N["klines"]["AAAUSDT"] == ["2022-03", "2022-04", "2022-05", "2022-06", "2022-07"]                  # 91 days back … the label's two days after
    assert N["klines"]["BBBUSDT"] == ["2026-06", "2026-07", "2026-08", "2026-09"]                             # cut at the segment's end: no 2026-10
    assert N["funding"]["AAAUSDT"] == ["2022-05", "2022-06", "2022-07"]
    assert N["metrics"]["AAAUSDT"] == [(pd.Timestamp("2022-05-29").date(), pd.Timestamp("2022-07-07").date())]
    assert N["metrics"]["BBBUSDT"][0][1] == pd.Timestamp("2026-09-14").date()                                 # the last day INSIDE the block
    two = pd.concat([one, one.assign(a=one["a"] + nd.BLOCK, b=one["b"] + nd.BLOCK).iloc[:1]], ignore_index=True)
    assert len(nd.need(two)["metrics"]["AAAUSDT"]) == 1                                                       # touching intervals are one


def _tab(names=("AAAUSDT", "BBBUSDT"), start="2022-01-01", n=300):
    rng = np.random.default_rng(7)
    parts = []
    for i, s in enumerate(names):
        ts = pd.date_range(pd.Timestamp(start, tz="UTC"), periods=n, freq="5min")
        parts.append(pd.DataFrame({"symbol": s, "ts": ts, "x": rng.random(n), "y": np.where(np.arange(n) % 7 == 0, np.nan, rng.random(n))}))
    d = pd.concat(parts, ignore_index=True)
    d["symbol"] = d["symbol"].astype("category")
    return d


def test_the_row_check_passes_on_filled_holes_and_fails_on_any_change():
    full = _tab()
    old = full[(full["ts"].dt.hour % 3 != 1)].reset_index(drop=True)                    # holes inside each name's extent
    r = nd.old_rows_in(old, full, "ts", ("x", "y"))
    assert r["pass"] and r["names_checked"] == 2 and r["rows_checked"] == len(old) and r["old_rows_missing"] == 0     # NaN equals NaN
    more = pd.concat([full.assign(symbol=full["symbol"].astype(str)), _tab(("CCCUSDT",)).assign(symbol="CCCUSDT")], ignore_index=True)
    more["symbol"] = more["symbol"].astype("category")
    assert nd.old_rows_in(old, more.sample(frac=1, random_state=1).reset_index(drop=True), "ts", ("x", "y"))["pass"]   # a new name, any row order
    ch = full.copy()
    ch.loc[10, "x"] += 1e-12
    r = nd.old_rows_in(old, ch, "ts", ("x", "y"))
    assert not r["pass"] and r["old_rows_changed"] == 1 and list(r["bad_names"]) == ["AAAUSDT"]
    nan = full.copy()
    nan.loc[10, "x"] = np.nan
    assert nd.old_rows_in(old, nan, "ts", ("x", "y"))["old_rows_changed"] == 1
    dropped = full.drop(index=full.index[full["ts"] == old["ts"].iloc[5]][:1]).reset_index(drop=True)
    r = nd.old_rows_in(old, dropped, "ts", ("x", "y"))
    assert not r["pass"] and r["old_rows_missing"] == 1
    gone = full[full["symbol"] != "BBBUSDT"].reset_index(drop=True)
    gone["symbol"] = gone["symbol"].cat.remove_unused_categories()
    r = nd.old_rows_in(old, gone, "ts", ("x", "y"))
    assert not r["pass"] and r["old_rows_missing"] == int((old["symbol"] == "BBBUSDT").sum())


def _zip(path, name, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, text)
    path.with_suffix(".zip.ok").touch()


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "EXT", tmp_path / "raw")
    monkeypatch.setattr(data, "PROC", tmp_path)
    rng = np.random.default_rng(11)
    for i, s in enumerate(("BBBUSDT", "AAAUSDT", "CCCUSDT")):
        for m, days in (("2022-03", 2), ("2022-05", 1)):                               # a hole between the two months; the second file repeats a bar of the first
            t0 = int(pd.Timestamp(f"{m}-01", tz="UTC").timestamp() * 1000)
            ts = [t0 + 300_000 * k for k in range(288 * days)]
            rows = [f"{t},{1 + i},{2 + i},{0.5 + i},{rng.random() + i},{rng.random() * 100},{t + 299_999},{rng.random() * 1e4},10,1,1,0" for t in ts]
            if m == "2022-05":
                rows.append(f"{int(pd.Timestamp('2022-03-01', tz='UTC').timestamp() * 1000)},9,9,9,9,9,0,9,1,1,1,0")
            head = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n" if m == "2022-05" else ""
            _zip(tmp_path / "raw" / "klines" / s / f"{s}-5m-{m}.zip", f"{s}-5m-{m}.csv", head + "\n".join(rows))
        for d in ("2022-03-01", "2022-03-03"):
            ts = pd.date_range(pd.Timestamp(d, tz="UTC"), periods=288, freq="5min")
            body = "\n".join(f"{t:%Y-%m-%d %H:%M:%S},{s},{100 + k + i},{1e6 + k},{'' if k % 5 == 0 else 1.5},{1.2},{0.9},{1.1}" for k, t in enumerate(ts))
            body += f"\n{ts[0]:%Y-%m-%d %H:%M:%S},{s},7,7,7,7,7,7"                    # a repeated stamp: the last row is kept
            _zip(tmp_path / "raw" / "metrics" / s / f"{s}-metrics-{d}.zip", f"{s}-metrics-{d}.csv",
                 "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n" + body)
    return tmp_path


def _same(a: pd.DataFrame, b: pd.DataFrame):
    assert list(a["symbol"].cat.categories) == list(b["symbol"].cat.categories)
    pd.testing.assert_frame_equal(a.assign(symbol=a["symbol"].astype(str)), b.assign(symbol=b["symbol"].astype(str)))


def test_the_tables_written_a_name_at_a_time_are_the_whole_ingests_tables(raw):
    syms = ["BBBUSDT", "AAAUSDT", "CCCUSDT", "NOFILESUSDT"]
    a = data.ingest_klines(syms)
    whole = pd.read_parquet(raw / "candles_5m_archive.parquet")
    b = nd.stream_klines(syms)
    _same(whole, pd.read_parquet(raw / "candles_5m_archive.parquet"))
    assert (a["rows_in"], a["rows_out"], a["dups_dropped"]) == (b["rows_in"], b["rows_out"], b["dups_dropped"]) and b["dups_dropped"] == 3 and b["names"] == 3
    assert not (raw / "candles_5m_archive.parquet.tmp").exists()
    assert sorted(nd.held("candles_5m_archive")) == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    assert float(whole.loc[(whole["symbol"] == "AAAUSDT") & (whole["open_time"] == pd.Timestamp("2022-03-01", tz="UTC")), "close"].iloc[0]) == 9.0    # the last file's bar
    a = data.ingest_metrics(syms[:3])
    whole = pd.read_parquet(raw / "metrics.parquet")
    b = nd.stream_metrics(syms)
    _same(whole, pd.read_parquet(raw / "metrics.parquet"))
    assert (a["rows_in"], a["rows_out"]) == (b["rows_in"], b["rows_out"]) and b["dups_dropped"] == 6                 # each day file repeats its first stamp
    # the before-copy and the check through the files: an old table with a hole passes against the streamed one
    old = whole[whole["ts"] < pd.Timestamp("2022-03-02", tz="UTC")]
    old.to_parquet(raw / f"metrics_before_{nd.TAG}.parquet", index=False)
    r = nd.check_table("metrics", "ts", (("oi", "oi_value", "top_ls_count"), ("top_ls_sum", "global_ls", "taker_ratio")))
    assert r["pass"] and len(r["passes"]) == 2 and r["passes"][0]["rows_checked"] == len(old)
