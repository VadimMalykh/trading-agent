"""The harness change of 2026-10-01 (PLAN §7, "The harness charges funding and the exit leg's costs on the size at entry" → on the
position's value; `backtest.CHARGED`) must reproduce the numbers `scripts/actual_describe.py` described beside the re-execution
of 2026-09-30, its "in full" rows: R25 net −66.74, R24 pooled −13.83. Decides nothing: it re-prices the SAVED decisions of the
named runs through the changed `backtest.price` (the same market, the same cost series) and sets each number against the
described.csv of the reference. Nothing is re-decided and no fold is read.
Run where the data is (the work VM): python scripts/charged_check.py <output name> <described dir>=<run> [<described dir>=<run> …]
  e.g. python scripts/charged_check.py charged_check r25_read_actual=r25_oibook_7d_f34_actual r24_pool_actual=r24_oibook_7d_pre_actual,r24_oibook_7d_f12_actual
→ output/backtest/<output name>/charged_check.md, charged_check.json; exit 1 if any number is off by more than TOL bps."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from ft2 import backtest as bt
from ft2 import ceiling, folds

sys.path.insert(0, str(Path(__file__).parent))
from actual_describe import read                                   # noqa: E402  the same statistic, the same flip null

TOL = 1e-6


def reprice(run: str) -> tuple[pd.DataFrame, pd.DatetimeIndex, int]:
    rd = bt.OUT / run
    meta = json.loads((rd / "meta.json").read_text())
    assert meta.get("unit") == "actual", f"{run} was counted in logs"
    fo = meta["folds"]
    end = folds.bounds(fo[-1])[1]
    dec = pd.read_parquet(rd / "decisions.parquet")
    M = bt.market(meta["pairs"], end, bt.PRE_START if "FP" in fo else ceiling.START)
    C = bt.load_costs(M.index, M.columns, end, meta["cost_mult"], M.close)
    f = bt.price(dec, M, C, "taker", meta["taker_bps"], meta["maker_bps"], meta["latency_bars"]).dropna(subset=["net_bps"]).copy()
    old = pd.read_parquet(rd / "fills_taker.parquet").dropna(subset=["net_bps"])
    assert len(f) == len(old) and (f["id"].to_numpy() == old["id"].to_numpy()).all(), f"{run}: not the same priced trades"
    assert np.allclose(f["gross_bps"], old["gross_bps"], atol=1e-6), f"{run}: the gross changed — it must not"
    f["cost"], f["run"] = f["fee_bps"] + f["other_cost_bps"], run
    return f, bt.scored_days(fo, folds.bounds(fo[-1])[1] - bt.BAR), int(meta["params"]["hold"])


if __name__ == "__main__":
    name, groups = sys.argv[1], [a.split("=") for a in sys.argv[2:]]
    rows, bad = [], []
    for ref, runs in groups:
        runs = runs.split(",")
        want = pd.read_csv(bt.OUT / ref / "described.csv")
        want = want[want["counted"].str.startswith("in full")].set_index("sample")
        parts = {k: reprice(k) for k in runs}
        hold = {h for _, _, h in parts.values()}.pop()
        samples = dict(parts)
        if len(parts) > 1:
            days = [d for _, d, _ in parts.values()]
            samples["pooled"] = (pd.concat([f for f, _, _ in parts.values()], ignore_index=True), days[0].append(days[1:]).unique().sort_values(), hold)
        for k, (f, days, _) in samples.items():
            got = read(f, days, hold, "gross_bps", "funding_bps", "cost")
            w = want.loc[k]
            row = {"reference": ref, "sample": k, "trades": got["trades"], "trades_ref": int(w["trades"])}
            for c in ("gross", "cost", "funding", "net", "net_lo", "net_hi", "net_long", "net_short", "flip_p"):
                row |= {c: got[c], f"{c}_ref": float(w[c]), f"d_{c}": got[c] - float(w[c])}
                if abs(got[c] - float(w[c])) > TOL or got["trades"] != int(w["trades"]):
                    bad.append((ref, k, c))
            rows.append(row)
    tab = pd.DataFrame(rows)
    ok = not bad
    out = bt.OUT / name
    out.mkdir(parents=True, exist_ok=True)
    md = [f"# The harness charged on the position's value, against the numbers described on 2026-09-30 (`scripts/charged_check.py`)\n",
          f"generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC · {'PASS' if ok else 'FAIL'}: {'every' if ok else str(len(bad)) + ' of the'} number{'s' if not ok else ''} "
          f"within {TOL:g} bps of the reference's *in full* row\n",
          "\nThe saved decisions of each run re-priced through `backtest.price` as it is now; the gross asserted unchanged trade by trade. bps per trade.\n",
          "\n## Net\n", tab[["reference", "sample", "trades", "trades_ref", "net", "net_ref", "d_net", "cost", "cost_ref", "funding", "funding_ref", "flip_p", "flip_p_ref"]].round(4).to_markdown(index=False), "\n",
          "\n## Everything compared\n", tab.round(6).to_markdown(index=False), "\n",
          *([f"\n**OFF:** " + ", ".join(f"{a} / {b} / {c}" for a, b, c in bad) + "\n"] if bad else [])]
    (out / "charged_check.md").write_text("\n".join(md))
    (out / "charged_check.json").write_text(json.dumps({"pass": ok, "tol_bps": TOL, "rows": tab.to_dict("records"), "off": bad}, indent=1, default=float))
    print("\n".join(md))
    sys.exit(0 if ok else 1)
