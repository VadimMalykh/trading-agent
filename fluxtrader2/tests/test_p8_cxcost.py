"""Decision CX1's arithmetic (`ft2/cxcost.py`) on planted books: the linear-book impact estimate equals the walk of a book that IS
evenly spread, inside the first band and across both; a notional above the ±1 % band is censored; the tier verdicts follow the
1 / 1.5 … 1.5 band and DEFECTIVE needs an outside tier holding a quarter of a read's positions."""
import numpy as np
import pandas as pd

from ft2 import cxcost, ladder


def even_book(u02, u1, h, mid=100.0, step=0.05):
    """Ask levels every `step` bps from the touch (h bps) to 100 bps, the notional even in [h, 20) and in [20, 100)."""
    b1, b2 = np.arange(h, 20, step), np.arange(20, 100, step)
    px = mid * (1 + np.concatenate([b1, b2]) / 1e4)
    notion = np.concatenate([np.full(len(b1), u02 / len(b1)), np.full(len(b2), (u1 - u02) / len(b2))])
    return px, notion / px


def test_estimate_equals_the_walk_of_an_even_book():
    for u02, u1, h, n in [(50_000, 400_000, 2.0, 10_000), (4_000, 60_000, 5.0, 10_000), (9_000, 30_000, 0.5, 25_000)]:
        px, qty = even_book(u02, u1, h)
        true = ladder.walk(px, qty, 100.0, [n])[0] - h
        est = float(cxcost.est_impact(n, u02, u1, h))
        assert abs(est - true) < 0.05 + 0.01 * true, (u02, u1, h, n, est, true)      # the planted book is discrete and the walk averages in quantity
    assert np.isclose(float(cxcost.est_impact(10_000, 50_000, 400_000, 2.0)), 10_000 * 18 / (2 * 50_000))      # 1.8 bps


def test_censored_and_degenerate():
    assert np.isnan(cxcost.est_impact(10_000, 2_000, 9_000, 3.0))        # above the ±1 % band
    assert np.isnan(cxcost.est_impact(10_000, 0.0, 9_000, 3.0))
    out = cxcost.est_impact(np.array([1_000, 10_000]), np.array([5_000, 5_000]), np.array([50_000, 50_000]), 4.0)
    assert out[0] < out[1] and np.isfinite(out).all()


def test_verdict_needs_an_outside_tier_with_a_quarter_of_the_positions():
    t = pd.DataFrame({"verdict": ["OVERSTATED", "CERTIFIED", "UNDERSTATED", "CERTIFIED", "OVERSTATED"]}, index=["<5M", "5-15M", "15-30M", "30-60M", ">60M"])
    sh = pd.DataFrame({"R100 base": [0.5, 0.2, 0.2, 0.05, 0.05], "R90": [0.0, 0.1, 0.24, 0.3, 0.36]}, index=t.index)
    assert cxcost.verdict(t, sh) == ("DEFECTIVE", [">60M"])             # <5M is described only; 15-30M holds under a quarter of both
    sh.loc[">60M", "R90"] = 0.2
    assert cxcost.verdict(t, sh) == ("CERTIFIED", [])


def test_the_frozen_sample_is_what_the_rule_makes(tmp_path, monkeypatch):
    frozen = pd.read_csv(cxcost.SAMPLE)
    monkeypatch.setattr(cxcost, "SAMPLE", tmp_path / "s.csv")
    again = cxcost.sample()
    assert len(frozen) == 1368 and frozen.equals(pd.read_csv(tmp_path / "s.csv")) and len(again) == 1368
