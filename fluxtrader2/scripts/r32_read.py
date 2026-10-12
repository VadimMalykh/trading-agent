"""R32 — stage 1 read from the pulled fills (`output/backtest/trend1d/`): the gate's per-calendar-year nets with the harness's own
`summarize` on the SCORED days of each year (the harness's denominator: a day without a trade counts as a zero), long and short apart
(the long side IS the "long when up, flat when down" variant's per-trade mean), and the described rows of the registration:
(a) the HELD position — the daily gross chained, funding every day, the round trip's legs charged only on the days the sign flips
    (half a round trip on the first and the last day), from the saved fills; (b) the sides apart with the basket's drift on the same
    days; (c) R30's session as a size — entries whose day holds a US session (Mon → Fri 00:00 UTC) against the weekend's, with the
    basket's mean |1d move| on each; (d) maker_ev beside maker.
Run: docker run --rm -v "$PWD/fluxtrader2:/workspace/ft2" -w /workspace/ft2 -e PYTHONPATH=/workspace/ft2 fluxtrader2-analysis:latest python scripts/r32_read.py"""

import json
import sys

import numpy as np
import pandas as pd

from ft2 import backtest as bt, folds

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
pd.set_option("display.float_format", lambda v: f"{v:+.2f}")
RUN = sys.argv[1] if len(sys.argv) > 1 else "trend1d"
B = f"output/backtest/{RUN}"
HOLD = 288


def fills(ex):
    return pd.read_parquet(f"{B}/fills_{ex}.parquet")


def row(f, days, label):
    f = f.dropna(subset=["net_bps"])
    s = bt.summarize(f, days, HOLD)
    return {"scope": label, "trades": s["trades"], "days": s["days"], "t/day": round(s["trades_per_day"], 2), "hit": round(s["hit"], 3), "gross": s["gross"],
            "fee": s["fee"], "other": s["other_cost"], "fund": s["funding"], "net": s["net"], "lo": s["net_lo"], "hi": s["net_hi"], "mde": s["net_mde"], "p_fill": s["p_fill"]}


meta = json.load(open(f"{B}/meta.json"))
print("=== meta ===")
print({k: meta[k] for k in meta if k in ("strategy", "params", "folds", "registration", "unit", "charged", "decisions", "accepted", "pairs", "max_open", "avg_open")})
last = folds.bounds(folds.order(meta["folds"])[-1])[1] - bt.BAR
days_all = bt.scored_days(meta["folds"], last)
res = pd.read_parquet(f"{B}/results.parquet")
print("\n=== stage 1: per fold and long / short (results.parquet) ===")
print(res[res["scope"].isin(["all", *meta["folds"], "long", "short"])][["exec", "scope", "trades", "trades_per_day", "hit", "gross", "hedged", "fee", "other_cost", "funding",
                                                                         "net", "net_lo", "net_hi", "net_mde", "p_fill"]].to_string(index=False))
nul = pd.read_parquet(f"{B}/null.parquet")
print("\n=== the nulls (null.parquet) ===")
print(nul.head(3).to_string(index=False))
try:
    print(nul.groupby(["exec", "null"])["net"].describe()[["count", "mean", "std", "min", "max"]])
except Exception:
    pass

for ex in ("taker", "maker", "maker_ev"):
    f = fills(ex)
    f["year"] = pd.DatetimeIndex(f["entry_t"]).year
    print(f"\n=== by calendar year — {ex} (the gate's condition on taker: net ≥ −5 in each) ===")
    print(pd.DataFrame([row(g, days_all[days_all.year == y], str(y)) for y, g in f.groupby("year")]).to_string(index=False))
    if ex in ("taker", "maker"):
        print(f"\n=== by calendar year, the sides apart — {ex} ===")
        rows = []
        for y, g in f.groupby("year"):
            d = days_all[days_all.year == y]
            for side, lab in ((1, "long"), (-1, "short")):
                rows.append(row(g[g["side"] == side], d, f"{y} {lab}"))
        print(pd.DataFrame(rows).to_string(index=False))

# (a) the HELD position: one basket a day; the round trip's legs only on flip days
print("\n=== described (a): the position held until the sign flips, from the fills (arithmetic, not a rule) ===")
for ex in ("taker", "maker"):
    f = fills(ex).dropna(subset=["net_bps"])
    g = f.groupby("entry_t").agg(side=("side", "mean"), n=("side", "size"), gross=("gross_bps", "sum"), fund=("funding_bps", "sum"),
                                 cost=("fee_bps", "sum"), other=("other_cost_bps", "sum")).sort_index()
    assert (g["side"].abs() == 1).all(), "a day with mixed sides"
    g["rt"] = g["cost"] + g["other"]                                   # the day's round trips, all pairs
    flip = g["side"].ne(g["side"].shift()).to_numpy()
    flip[0] = False
    charged = np.where(flip, g["rt"], 0.0)
    charged[0] += g["rt"].iloc[0] / 2                                 # the first day's entry leg
    charged[-1] += g["rt"].iloc[-1] / 2                               # the last day's exit leg
    n = g["n"].sum()
    print(f"{ex:9s} days {len(g):5d}  flips {int(flip.sum()):4d}  mean hold {len(g) / max(int(flip.sum()) + 1, 1):6.1f} d  "
          f"per trade: gross {g['gross'].sum() / n:+.2f}  funding {g['fund'].sum() / n:+.2f}  daily round trips {-g['rt'].sum() / n:+.2f} → net as run {(g['gross'].sum() + g['fund'].sum() - g['rt'].sum()) / n:+.2f}  "
          f"| legs on flips only {-charged.sum() / n:+.2f} → HELD net {(g['gross'].sum() + g['fund'].sum() - charged.sum()) / n:+.2f}")
    long_days = int((g["side"] > 0).sum())
    print(f"          long days {long_days}, short days {len(g) - long_days}; the basket's mean 1d move on long days {g.loc[g['side'] > 0, 'gross'].div(g.loc[g['side'] > 0, 'n']).mean():+.2f}, "
          f"on short days (as a long) {-g.loc[g['side'] < 0, 'gross'].div(g.loc[g['side'] < 0, 'n']).mean():+.2f}")

# (c) R30's session as a size: weekday vs weekend entries
print("\n=== described (c): entries whose day holds a US session (Mon → Fri 00:00 UTC) vs the weekend's — the basket's |1d move| and the net ===")
for ex in ("taker", "maker"):
    f = fills(ex).dropna(subset=["net_bps"])
    e = f.groupby("entry_t").apply(lambda g: (g["side"] * g["gross_bps"]).mean(), include_groups=False)
    dow = pd.DatetimeIndex(e.index).dayofweek
    f["dow"] = pd.DatetimeIndex(f["entry_t"]).dayofweek
    for lab, m, mf in (("Mon-Fri", dow < 5, f["dow"] < 5), ("Sat-Sun", dow >= 5, f["dow"] >= 5)):
        d = days_all[(days_all.dayofweek < 5) if lab == "Mon-Fri" else (days_all.dayofweek >= 5)]
        r = row(f[mf], d, f"{ex} {lab}")
        print(f"{r['scope']:16s} entries {int(m.sum()):5d}  mean |1d basket move| {e[m].abs().mean():7.2f} bps  net {r['net']:+.2f} [{r['lo']:+.2f}, {r['hi']:+.2f}]  gross {r['gross']:+.2f}")

# (d) maker_ev beside maker: the rule's own adverse selection
a = res[(res["scope"] == "all")].set_index("exec")
if {"maker", "maker_ev"} <= set(a.index):
    print(f"\n=== described (d): maker {a.loc['maker', 'net']:+.2f} vs maker_ev {a.loc['maker_ev', 'net']:+.2f} → adverse selection {a.loc['maker_ev', 'net'] - a.loc['maker', 'net']:+.2f} bps a trade; "
          f"p_fill {a.loc['maker', 'p_fill']:.3f} ===")
