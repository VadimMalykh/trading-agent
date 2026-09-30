"""The reads made before the unit of money was corrected (PLAN §3), R1–R21: each saved run's fills as measured (gross =
side × log(exit / entry)) and with the actual return of a position (side × (exit / entry − 1)) — decisions, prices,
costs and funding the runs' own. One table, no new verdict. Run anywhere the runs' output is (locally:
  docker run --rm -v "$PWD:/workspace/ft2" -w /workspace/ft2 -e PYTHONPATH=. fluxtrader2-analysis:latest python scripts/actual_table.py)
→ output/backtest/actual_table.md, actual_table.csv"""
import json

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import folds

RUNS = {"reversal4h": "R1", "rank4h": "R2", "rev_cap3": "R3", "rev_invvol": "R3", "rev_invvol_cap3": "R3", "panic4h": "R4", "panic4h_pre": "R4", "rankcont4h": "R5",
        "trendfall4h": "R8", "bookimb1d": "R9", "r10_rankcont4h_k4": "R10", "r11_bookimb1d_long": "R11", "r12_ridgebook_4h": "R12", "r12_ridgebook_1d": "R12",
        "r13_ridgebook_1d_inpair": "R13", "r13_ridgebook_1d_inpair12": "R13", "r14_ridgebook_1d_ho12": "R14", "r15_ridgebook_1d_ho12_all": "R15",
        "r16_ridgebook_1d_ho12_f34": "R16", "r18_transferbook_1d": "R18", "r21_oibook_1d": "R21"}


def row(run: str, reg: str, exec_: str) -> dict | None:
    rd = bt.OUT / run
    if not (rd / f"fills_{exec_}.parquet").exists():
        return None
    meta = json.loads((rd / "meta.json").read_text())
    assert "unit" not in meta, f"{run} is already counted in actual returns"
    f = pd.read_parquet(rd / f"fills_{exec_}.parquet").dropna(subset=["net_bps"])
    if not len(f):
        return None
    fo = meta["folds"]
    days = bt.scored_days(fo, folds.bounds(fo[-1])[1] - bt.BAR)
    hold = int(round(((f["exit_t"] - f["entry_t"]) / bt.BAR).median()))
    s, r = f["side"].to_numpy(float), (f["exit_px"] / f["entry_px"]).to_numpy()
    assert np.allclose(s * np.log(r) * 1e4, f["gross_bps"], rtol=0, atol=1e-6), run
    act = s * (r - 1) * 1e4
    day, w, lags = pd.DatetimeIndex(f["t"]).floor("D"), f["size"].to_numpy(), bt.day_lags(hold)
    rest = (f["funding_bps"] - f["fee_bps"] - f["other_cost_bps"]).to_numpy()
    a, b = bt.trade_stats(f["gross_bps"].to_numpy() + rest, w, day, days, lags), bt.trade_stats(act + rest, w, day, days, lags)
    side = lambda v, g: float(np.average(g[s == v], weights=w[s == v])) if (s == v).any() else np.nan      # noqa: E731
    return {"reg": reg, "run": run, "folds": "+".join(fo), "exec": exec_, "hold_bars": hold, "trades": len(f), "gross_log": float(np.average(f["gross_bps"], weights=w)),
            "gross_actual": float(np.average(act, weights=w)), "net_log": a["mean"], "net_log_lo": a["lo"], "net_log_hi": a["hi"], "net_actual": b["mean"], "net_actual_lo": b["lo"],
            "net_actual_hi": b["hi"], "diff": b["mean"] - a["mean"], "long_diff": side(1, act) - side(1, f["gross_bps"].to_numpy()),
            "short_diff": side(-1, act) - side(-1, f["gross_bps"].to_numpy()), "abs_move_pct_median": float(np.median(np.abs(r - 1)) * 100)}


if __name__ == "__main__":
    tab = pd.DataFrame([x for run, reg in RUNS.items() for e in ("taker", "maker") if (x := row(run, reg, e)) is not None])
    md = ["# R1–R21 as measured and with the actual return of a position (`scripts/actual_table.py`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · the saved fills of {tab['run'].nunique()} runs; no run was made again and no verdict changes here\n",
          "\nWords: *log* — as the harness counted a trade until 2026-09-30, side × log(exit / entry). *actual* — what a position of fixed size earns, side × (exit / entry − 1). "
          "bps per unit of notional (1 bps = 1 USDT on 10,000); the interval is 95 %, clustered by day. *diff* = actual − log: about half the squared move, positive for a "
          "long and negative for a short, so a book's diff is what its long side gains minus what its short side loses.\n",
          "\n", tab.round(2).to_markdown(index=False), "\n"]
    (bt.OUT / "actual_table.md").write_text("\n".join(md))
    tab.to_csv(bt.OUT / "actual_table.csv", index=False)
    print("\n".join(md))
