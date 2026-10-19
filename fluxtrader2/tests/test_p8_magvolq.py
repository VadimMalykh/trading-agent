"""R56 (`ft2/magvolq.py`): on a planted market where the realised volatility is the straddle's own implied plus noise, a noise forecast
reads CLOSED; when the forecast carries the realised beyond the implied, ALIVE on both names; the 0.8 and the tenor leave every ΔR²
unchanged; an uncovered day's forecast row is not scored; a changed R54 file fails validity (1)."""
import hashlib
import json

import numpy as np
import pandas as pd

from ft2 import folds, magvolq, straddle, varbook

START, END = folds.bounds("F1")[0], folds.bounds("F2")[1]
UNCOVERED = pd.Timestamp("2023-09-15", tz="UTC")


def _plant(tmp_path, monkeypatch, signal: float, seed=3):
    """Q_d ~ N(log 50, 0.3²); y_d = Q_d + signal × z_d + ε_d; the forecast = log 50 + z_d + noise (z known to it, at DVOL's level)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "output/magvol/f12").mkdir(parents=True)
    rng = np.random.default_rng(seed)
    days = pd.date_range(START, END, freq="D", inclusive="left")
    st_rows, fc_rows = [], []
    for cur, sym in straddle.NAMES.items():
        q = np.log(50.0) + rng.normal(0, 0.3, len(days))
        z = rng.normal(0, 0.3, len(days))
        y = q + signal * z + rng.normal(0, 0.3, len(days))
        f = np.log(50.0) + z + rng.normal(0, 0.1, len(days)) - 0.4                     # the wrong level: R54 fitted it to DVOL's scale
        for i, d in enumerate(days):
            covered = d != UNCOVERED and i % 23 != 0                                 # a few uncovered days, one planted
            m = varbook.BS_FACTOR * (np.exp(q[i]) / 100) * np.sqrt(straddle.TENOR_H / 8760)     # the straddle priced at σ_q = exp(Q)
            st_rows.append({"currency": cur, "day": d, "spot_00": 30000.0, "strike": 30000, "c_last": m / 2, "p_last": m / 2,
                            "c_last_ts": d - pd.Timedelta(hours=1 + i % 3), "p_last_ts": d if i % 2 else d - pd.Timedelta(hours=1),      # the bars' ENDS: 00:00 = the 23:00 hour's trades
                            "covered": covered, "skip": None if covered else "parity"})
            fold = "F1" if d < folds.bounds("F2")[0] else "F2"
            for h in (1, 7):
                fc_rows.append({"day": d, "y": y[i], "yhat_I": f[i] + 0.2, "yhat_C": f[i] - 0.1, "yhat_I+C": f[i], "fold": fold, "symbol": sym, "hold_days": h})
    pd.DataFrame(st_rows).to_parquet("data/straddle_1d.parquet", index=False)
    path = tmp_path / "output/magvol/f12/loss.csv"
    pd.DataFrame(fc_rows).to_csv(path, index=False)
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows_hold1": len(days) * 2}


def test_a_noise_forecast_reads_closed_and_the_constants_cannot_move_it(tmp_path, monkeypatch):
    exp = _plant(tmp_path, monkeypatch, signal=0.0)
    txt = magvolq.run("t", expect=exp)
    out = magvolq.OUT / "t"
    v = json.loads((out / "validity.json").read_text())
    assert v["status"] == "PASS" and v["(1) R54's file unchanged"]["status"] == "PASS", v
    assert v["names"]["BTC"]["(3) Q known at 00:00"]["entry_bars_ending_at_midnight"] > 100 and v["names"]["BTC"]["(3) Q known at 00:00"]["entry_bars_ending_after_midnight"] == 0
    for cur in ("BTC", "ETH"):
        nv = v["names"][cur]
        assert nv["(2) coverage"] == "PASS (full)" and nv["(3) Q known at 00:00"]["status"] == "PASS" and nv["(4) refits causal"] == "PASS" and nv["(5) scored-day floor"] == "PASS"
        assert nv["scored_days"] >= 250 and nv["scored_F1"] >= 60 and abs(nv["corr_excess"]) < 0.15
    rows = pd.read_csv(out / "rows.csv")
    fam = rows[rows["family"]].set_index("currency")
    assert len(fam) == 2 and (fam["verdict"] == "CLOSED").all() and (fam["dr2"].abs() < 0.02).all(), fam
    rev = rows[rows["contrast"] == "one-day implied beyond forecast"].set_index("currency")
    assert (rev["dr2"] > 0.3).all() and (rev["t"] > 5).all()                                  # the implied is the forecast here
    assert set(rows["contrast"]) == {*magvolq.CONTRASTS, "R54: candles beyond 30-day index, same days (file)"}
    loss = pd.read_csv(out / "loss.csv")
    assert UNCOVERED.isoformat() not in set(loss["day"]) and str(UNCOVERED.date()) not in " ".join(loss["day"].astype(str))
    r2 = pd.read_csv(out / "r2.csv").set_index(["currency", "model"])
    assert r2.loc[("BTC", "Q"), "r2_all"] > 0.4 and r2.loc[("BTC", "F"), "r2_all"] < 0.1
    assert "**0 of 2 ALIVE**" in txt
    # the constants shift Q by a number: nothing moves
    monkeypatch.setattr(varbook, "BS_FACTOR", 0.5)
    monkeypatch.setattr(straddle, "TENOR_H", 24)
    magvolq.run("t2", expect=exp)
    rows2 = pd.read_csv(magvolq.OUT / "t2" / "rows.csv")
    assert np.allclose(rows["dr2"].to_numpy(), rows2["dr2"].to_numpy(), atol=1e-9) and np.allclose(rows["t"].to_numpy(), rows2["t"].to_numpy(), atol=1e-7)


def test_a_forecast_that_carries_the_realised_beyond_the_implied_reads_alive_and_a_changed_file_fails(tmp_path, monkeypatch):
    exp = _plant(tmp_path, monkeypatch, signal=0.6)
    txt = magvolq.run("t", expect=exp)
    rows = pd.read_csv(magvolq.OUT / "t" / "rows.csv")
    fam = rows[rows["family"]].set_index("currency")
    assert (fam["verdict"] == "ALIVE").all() and (fam["dr2"] > 0.1).all() and (fam["t"] > 1.96).all() and (fam["dr2_F1"] > 0).all() and (fam["dr2_F2"] > 0).all(), fam
    assert "**2 of 2 ALIVE**" in txt
    coef = pd.read_csv(magvolq.OUT / "t" / "coef.csv").set_index(["currency", "model"])
    assert abs(coef.loc[("BTC", "Q+F"), "b_F_I+C"] - 0.55) < 0.25 and abs(coef.loc[("BTC", "Q+F"), "b_Q"] - 1.0) < 0.2      # 0.6 attenuated by the forecast's own noise
    v = json.loads((magvolq.OUT / "t" / "validity.json").read_text())
    assert v["status"] == "PASS"
    # the file changed → validity (1) FAIL
    d = pd.read_parquet("data/straddle_1d.parquet")
    d.loc[(d["currency"] == "ETH") & (d["day"] == pd.Timestamp("2024-03-03", tz="UTC")), "p_last_ts"] = pd.Timestamp("2024-03-03 01:00", tz="UTC")
    d.to_parquet("data/straddle_1d.parquet", index=False)
    magvolq.run("t4", expect=exp)
    v4 = json.loads((magvolq.OUT / "t4" / "validity.json").read_text())
    assert v4["status"] == "FAIL" and v4["names"]["ETH"]["(3) Q known at 00:00"]["entry_bars_ending_after_midnight"] == 1 and v4["names"]["BTC"]["(5) scored-day floor"] == "PASS"
    magvolq.run("t3", expect={**exp, "sha256": "0" * 64})
    v3 = json.loads((magvolq.OUT / "t3" / "validity.json").read_text())
    assert v3["status"] == "FAIL" and v3["(1) R54's file unchanged"]["status"] == "FAIL"
