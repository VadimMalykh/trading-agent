"""Decision CU1's Data line (`ft2/predata.py`) on made-up files: a month file that exists is never rewritten and a missing one is fetched once; a
table whose old rows come back unchanged passes with earlier rows added, and a changed, dropped or added old row fails."""
import json

import numpy as np
import pandas as pd

from ft2 import predata as pdx


def _table(first="2023-04-01", hours=48, names=("A-USD", "B-USD"), bump=0.0):
    ts = pd.date_range(pd.Timestamp(first, tz="UTC"), periods=hours, freq="h")
    return pd.concat([pd.DataFrame({"product": n, "ts": ts, "close": np.arange(hours) + 10.0 * i + bump, "volume": 1.0}) for i, n in enumerate(names)], ignore_index=True)


def test_old_rows_identical_with_earlier_rows_added_passes_and_any_change_fails():
    old = _table()
    b = pdx.old_rows(old, "product", ("close", "volume"))
    early = _table("2021-11-01", 24)
    ok, a = pdx.same_old(b, pd.concat([early, old], ignore_index=True), "product", ("close", "volume"))
    assert ok and a["rows"] == b["rows"] == 96
    changed = old.copy()
    changed.loc[5, "close"] += 0.01
    assert not pdx.same_old(b, pd.concat([early, changed], ignore_index=True), "product", ("close", "volume"))[0]
    assert not pdx.same_old(b, pd.concat([early, old.iloc[1:]], ignore_index=True), "product", ("close", "volume"))[0]              # a dropped old row
    extra = pd.concat([old, _table("2023-04-02", 1, names=("C-USD",))], ignore_index=True)
    assert not pdx.same_old(b, extra, "product", ("close", "volume"))[0]                                                           # a new name inside the old extent


def test_a_held_month_is_never_rewritten_and_a_missing_one_is_fetched_once(tmp_path):
    raw = tmp_path / "raw"
    (raw / "A-USD").mkdir(parents=True)
    held = raw / "A-USD" / f"{pdx.SRC_MONTHS[3]}.json"
    held.write_text(json.dumps({"rows": [[1, 2, 3]], "fetched": "2026-10-19 14:00 UTC", "mark": "held"}))
    calls = []

    def candles(i, a, b):
        calls.append((i, str(a), str(b)))
        return [[int(a.timestamp()), 1.0, 2.0, 1.5, 1.7, 9.0]]
    rep = pdx._months_once(raw, ["A-USD"], candles, {"idkey": "product"})
    assert json.loads(held.read_text())["mark"] == "held"
    assert rep["A-USD"] == {"months_fetched": len(pdx.SRC_MONTHS) - 1, "months_kept": 1, "rows": len(pdx.SRC_MONTHS) - 1}
    assert len(calls) == len(pdx.SRC_MONTHS) - 1 and all(pd.Timestamp(b) - pd.Timestamp(a) <= pd.Timedelta(days=31) for _, a, b in calls)
    first = json.loads((raw / "A-USD" / f"{pdx.SRC_MONTHS[0]}.json").read_text())
    assert first["product"] == "A-USD" and first["start"].startswith("2021-11-01") and first["end"].startswith("2021-12-01")
    n = len(calls)
    pdx._months_once(raw, ["A-USD"], candles, {"idkey": "product"})                     # a second pass fetches nothing
    assert len(calls) == n
    assert pdx.SRC_MONTHS[0] == "2021-11" and pdx.SRC_MONTHS[-1] == "2023-03" and pdx.KL_MONTHS == ["2021-09", "2021-10"]


def test_the_light_fingerprint_equals_the_old_one_with_and_without_an_extent(tmp_path, monkeypatch):
    from ft2 import data, krlist
    rng = np.random.default_rng(3)
    parts = []
    for i, n in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT")):
        ts = pd.date_range(pd.Timestamp("2022-01-01", tz="UTC") + pd.Timedelta(days=i), periods=500 + 100 * i, freq="5min")
        parts.append(pd.DataFrame({"symbol": n, "open_time": ts, "close": rng.random(len(ts)) * 100, "volume": rng.random(len(ts)) * 1e6}))
    d = pd.concat(parts, ignore_index=True)
    d["symbol"] = d["symbol"].astype("category")
    monkeypatch.setattr(data, "PROC", tmp_path)
    d.to_parquet(tmp_path / f"{krlist.SLICE}.parquet", index=False)
    a, b = krlist.fingerprint(), pdx.fingerprint_light()
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    ext = a[a["symbol"] != "CCCUSDT"].copy()
    ext["first"] = ext["first"] + pd.Timedelta(hours=3)                                                                             # an old extent inside the rows held now
    a2, b2 = krlist.fingerprint(ext), pdx.fingerprint_light(ext)
    pd.testing.assert_frame_equal(a2, b2, check_exact=True)
    assert list(b2["symbol"]) == ["AAAUSDT", "BBBUSDT"] and int(b2["rows"].iloc[0]) == 500 - 36
    assert krlist.fingerprint_check(ext.assign(rows=a2["rows"].to_numpy(), sum_close=a2["sum_close"].to_numpy(), sum_volume=a2["sum_volume"].to_numpy()), after_fn=pdx.fingerprint_light)["pass"]
