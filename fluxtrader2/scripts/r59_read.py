"""R59 (PLAN §8; decision AR1): R8 gated on the basket's volatility regime, confirmed ONCE on F3+F4.

    ft2 backtest trendfall4h_v90 --folds F3 F4 --registration R59 --execs taker maker     # the registered read, under the guard
    python scripts/r59_read.py calm      → output/backtest/r59_calm/   the DESCRIBED calm half (state +1) on the same bars, by the
                                           same harness code (market → walk → price → summarize; no noise floor), outside `run`:
                                           the guard logged F3 and F4 under R59 at the gated run; this row is R59's and no other's.
    python scripts/r59_read.py report    → output/backtest/r59/{r59.md, r59.json}: the gate on the gated run's own numbers (the
                                           taker net's clustered interval, the shuffle and flip p from null.parquet, each fold),
                                           the half-year tables of both halves, the calm half beside — described, not deciding.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ft2 import backtest as bt, ceiling, folds, rules  # noqa: E402

OUT = Path("output/backtest")
GATED, CALM, NAME = "trendfall4h_v90", "r59_calm", "r59"
FOLDS = ["F3", "F4"]
FOLD_FLOOR, HY_MIN_DAYS, P_BAR = -5.0, 15, 0.05


def _halfyear(t: pd.Series) -> pd.Series:
    return t.dt.year.astype(str) + np.where(t.dt.month <= 6, "-H1", "-H2")


def calm(gated_dir: Path = OUT / GATED, out: Path = OUT / CALM, fold_names=FOLDS) -> pd.DataFrame:
    """The calm half priced exactly as the gated run was (its meta's pairs, fees, latency, blocks), state +1."""
    meta = json.loads((gated_dir / "meta.json").read_text())
    q = {k: v for k, v in meta["params"].items() if k != "state"}
    S = rules.TrendFallV90(state=+1, **q)
    fold_names = folds.order(fold_names)
    end = folds.bounds(fold_names[-1])[1]
    M = bt.market(meta["pairs"], end, bt.PRE_START if "FP" in fold_names else ceiling.START, S.needs)
    C = bt.load_costs(M.index, M.columns, end, meta.get("cost_mult", 1.0), M.close)
    y = bt.labels(M, S.hold, meta["latency_bars"])
    dec = bt.walk(S, M, fold_names, y, meta["latency_bars"], meta["refit_days"])
    days = bt.scored_days(fold_names, M.index[-1])
    f = bt.price(dec, M, C, "taker", meta["taker_bps"], meta["maker_bps"], meta["latency_bars"])
    rows = [{"exec": "taker", "scope": "all", **bt.summarize(f, days, S.hold)}]
    rows += [{"exec": "taker", "scope": fo, **bt.summarize(f[f["fold"] == fo], bt.scored_days([fo], M.index[-1]), S.hold)} for fo in fold_names]
    res = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    dec.to_parquet(out / "decisions.parquet", index=False)
    f.to_parquet(out / "fills_taker.parquet", index=False)
    res.to_parquet(out / "results.parquet", index=False)
    (out / "meta.json").write_text(json.dumps({**meta, "strategy": S.name, "params": S.params(), "registration": "R59 (the described calm half; not a read of its own)",
                                               "role": "described", "decisions": len(dec), "accepted": int(dec["accepted"].sum()),
                                               "generated": f"{pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC"}, indent=1))
    return res


def halfyears(f: pd.DataFrame, hold: int, last: pd.Timestamp) -> pd.DataFrame:
    """Per calendar half-year inside the scored folds: trades, trade-days, the size-weighted net with its clustered interval."""
    f = f.dropna(subset=["net_bps"]).copy()
    t = pd.to_datetime(f["t"], utc=True)
    f["halfyear"] = _halfyear(t)
    rows = []
    for hy, g in f.groupby("halfyear", sort=True):
        y, h = int(hy[:4]), hy[-2:]
        a, b = (pd.Timestamp(f"{y}-01-01", tz="UTC"), pd.Timestamp(f"{y}-07-01", tz="UTC")) if h == "H1" else (pd.Timestamp(f"{y}-07-01", tz="UTC"), pd.Timestamp(f"{y + 1}-01-01", tz="UTC"))
        days = bt.scored_days(FOLDS, last)
        days = days[(days >= a) & (days < b)]
        st = bt.trade_stats(g["net_bps"].to_numpy(), g["size"].to_numpy(), pd.DatetimeIndex(pd.to_datetime(g["t"], utc=True)).floor("D"), days, bt.day_lags(hold))
        rows.append({"halfyear": hy, "trades": len(g), "trade_days": int(pd.to_datetime(g["t"], utc=True).dt.floor("D").nunique()), "days": len(days),
                     "net": st["mean"], "lo": st["lo"], "hi": st["hi"], "gross": float(np.average(g["gross_bps"], weights=g["size"]))})
    return pd.DataFrame(rows)


def null_p(nul: pd.DataFrame, real: float, exec_: str = "taker") -> dict:
    out = {}
    for kind, key in (("shuffle", "p_shuffle"), ("flip", "p_flip")):
        x = nul.loc[(nul["exec"] == exec_) & (nul["kind"] == kind), "net"].dropna()
        out[key] = float((1 + int((x >= real).sum())) / (len(x) + 1)) if len(x) else np.nan
        out[f"{kind}_draws"] = int(len(x))
    return out


def verdict(all_row: dict, by_fold: dict[str, float], p: dict) -> tuple[str, list[str]]:
    """The gate as registered: CONFIRMED iff lo > 0 AND max(p) ≤ 0.05 AND each fold ≥ −5; REFUTED iff hi < 0; else NOT DETECTABLE."""
    lines = [f"the taker net {all_row['net']:+.1f} [{all_row['net_lo']:+.1f}, {all_row['net_hi']:+.1f}] on {all_row['trades']:,} trades, MDE {all_row['net_mde']:.0f}",
             f"shuffle p {p['p_shuffle']:.3f}, flip p {p['p_flip']:.3f} ({p['shuffle_draws']} draws)",
             "by fold " + ", ".join(f"{k} {v:+.1f}" for k, v in by_fold.items())]
    pmax = max(p["p_shuffle"], p["p_flip"])
    folds_ok = all(v >= FOLD_FLOOR for v in by_fold.values())
    if all_row["net_lo"] > 0 and pmax <= P_BAR and folds_ok:
        return "CONFIRMED", lines
    if all_row["net_hi"] < 0:
        return "REFUTED", lines
    if all_row["net_lo"] > 0 and pmax <= P_BAR and not folds_ok:
        lines.append(f"the interval and the nulls pass but a fold is under {FOLD_FLOOR:+.0f}: NOT DETECTABLE by the fold line (a regime bet, R9's line)")
    return "NOT DETECTABLE", lines


def _tbl(df: pd.DataFrame, cols: list[str], fmt: dict) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = "".join("| " + " | ".join(fmt.get(c, "{}").format(r[c]) for c in cols) + " |\n" for _, r in df.iterrows())
    return head + body


def report(gated_dir: Path = OUT / GATED, calm_dir: Path = OUT / CALM, out: Path = OUT / NAME) -> dict:
    meta = json.loads((gated_dir / "meta.json").read_text())
    res = pd.read_parquet(gated_dir / "results.parquet")
    nul = pd.read_parquet(gated_dir / "null.parquet")
    f = pd.read_parquet(gated_dir / "fills_taker.parquet")
    tk = res[res["exec"] == "taker"].set_index("scope")
    all_row = tk.loc["all"].to_dict()
    by_fold = {fo: float(tk.loc[fo, "net"]) for fo in FOLDS if fo in tk.index}
    p = null_p(nul, float(all_row["net"]))
    last = folds.bounds(FOLDS[-1])[1] - bt.BAR            # the folds' own end, not the last fill: every scored day of both halves is in the table
    hy_g = halfyears(f, meta["params"]["hold"], last)
    v, lines = verdict(all_row, by_fold, p)
    maker = res[(res["exec"] == "maker") & (res["scope"] == "all")]
    c = None
    if (calm_dir / "results.parquet").exists():
        cres = pd.read_parquet(calm_dir / "results.parquet").set_index("scope")
        cf = pd.read_parquet(calm_dir / "fills_taker.parquet")
        c = {"all": cres.loc["all"].to_dict(), "by_fold": {fo: float(cres.loc[fo, "net"]) for fo in FOLDS if fo in cres.index},
             "halfyears": halfyears(cf, meta["params"]["hold"], last)}
    out.mkdir(parents=True, exist_ok=True)
    md = [f"# R59 — `{GATED}` on F3+F4, read once (`ft2 backtest … --registration R59`; generated {pd.Timestamp.now('UTC'):%Y-%m-%d %H:%M} UTC)\n",
          f"\nparams {meta['params']} · folds {'+'.join(meta['folds'])} · registration {meta['registration']} · {meta['decisions']:,} decisions, {meta['accepted']:,} taken · pairs {len(meta['pairs'])}\n",
          f"\n## VERDICT: {v}\n", *(f"- {ln}\n" for ln in lines),
          f"\nThe gate (registered): CONFIRMED iff the taker net's clustered lower bound > 0 AND the larger of the shuffle and flip p ≤ {P_BAR} AND each fold ≥ {FOLD_FLOOR:+.0f}; REFUTED iff the upper bound < 0; else NOT DETECTABLE.\n",
          "\n## The gated run (taker, bps per unit of notional)\n", _tbl(res[res["exec"] == "taker"].reset_index(), ["scope", "trades", "trades_per_day", "hit", "gross", "net", "net_lo", "net_hi", "net_mde"],
                                                                        {"trades": "{:,}", "trades_per_day": "{:.2f}", "hit": "{:.3f}", "gross": "{:+.1f}", "net": "{:+.1f}", "net_lo": "{:+.1f}", "net_hi": "{:+.1f}", "net_mde": "{:.0f}"})]
    if len(maker):
        m = maker.iloc[0]
        md.append(f"\nmaker (reported, not deciding): net {m['net']:+.1f} [{m['net_lo']:+.1f}, {m['net_hi']:+.1f}] on {int(m['trades']):,} trades, fill share {m['p_fill']:.2f}\n")
    md += ["\n### By calendar half-year (gated; described)\n", _tbl(hy_g, ["halfyear", "trades", "trade_days", "gross", "net", "lo", "hi"], {"gross": "{:+.1f}", "net": "{:+.1f}", "lo": "{:+.1f}", "hi": "{:+.1f}"}),
           f"\n(a half-year with under {HY_MIN_DAYS} trade-days is shown but not described as a half-year)\n"]
    if c is not None:
        a = c["all"]
        md += ["\n## The calm half (state +1) on the same bars — DESCRIBED, not deciding\n",
               f"- net {a['net']:+.1f} [{a['net_lo']:+.1f}, {a['net_hi']:+.1f}] on {int(a['trades']):,} trades ({a['trades_per_day']:.2f} a day), gross {a['gross']:+.1f}, MDE {a['net_mde']:.0f}; by fold " + ", ".join(f"{k} {v_:+.1f}" for k, v_ in c["by_fold"].items()) + "\n",
               ("- **the calm half's lower bound is > 0: the state did not travel — written beside the verdict**\n" if a["net_lo"] > 0 else "- the calm half's interval holds zero or lies below it: as expected\n"),
               "\n### By calendar half-year (calm; described)\n", _tbl(c["halfyears"], ["halfyear", "trades", "trade_days", "gross", "net", "lo", "hi"], {"gross": "{:+.1f}", "net": "{:+.1f}", "lo": "{:+.1f}", "hi": "{:+.1f}"})]
    else:
        md.append("\n(the calm half not priced: `python scripts/r59_read.py calm` first)\n")
    (out / "r59.md").write_text("".join(md))
    j = {"verdict": v, "lines": lines, "gated": {"all": {k: (float(x) if isinstance(x, (int, float, np.floating, np.integer)) else x) for k, x in all_row.items()}, "by_fold": by_fold, "p": p,
                                                "halfyears": hy_g.to_dict("records")},
         "calm": None if c is None else {"all": {k: (float(x) if isinstance(x, (int, float, np.floating, np.integer)) else x) for k, x in c["all"].items()}, "by_fold": c["by_fold"],
                                        "halfyears": c["halfyears"].to_dict("records"), "lower_bound_positive": bool(c["all"]["net_lo"] > 0)},
         "meta": {k: meta[k] for k in ("params", "folds", "registration", "pairs", "decisions", "accepted", "draws", "generated")}}
    (out / "r59.json").write_text(json.dumps(j, indent=1, default=str))
    return j


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("calm", "report"):
        raise SystemExit(__doc__)
    if argv[0] == "calm":
        print(calm().to_string())
    else:
        j = report()
        print((OUT / NAME / "r59.md").read_text())
        return j


if __name__ == "__main__":
    main()
